from __future__ import annotations

import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from contextvars import copy_context
from threading import Thread
import unittest
from unittest.mock import patch

from windows_solver.progress import (
    PROGRESS_SCHEMA,
    ProgressEventKind,
    ProgressMode,
    activate_progress,
    emit_progress,
    ingest_external_progress,
    progress_scope,
)
from windows_solver.progress_output import CampaignProgressReporter


class RecordingObserver:
    def __init__(self) -> None:
        self.events = []

    def publish(self, event) -> None:
        self.events.append(event)


class ProgressBusTests(unittest.TestCase):
    def test_progress_scope_carries_the_complete_hierarchy_without_global_leakage(self):
        observer = RecordingObserver()
        with activate_progress(observer), progress_scope(
            leaf_index=1,
            leaf_count=1,
            leaf_id="leaf-1",
            role="primary",
            mode={"s": -2, "ell": 2, "m": 2, "n": 0},
            spin=0.95,
            mechanism_id="horizon-admittance",
            precision_digits=64,
        ):
            emit_progress(ProgressEventKind.ROOT_PHASE_STARTED, phase="PRIMARY")
        emit_progress(ProgressEventKind.ROOT_PHASE_STARTED, phase="OUTSIDE")

        self.assertEqual(len(observer.events), 1)
        event = observer.events[0]
        self.assertEqual(event.context.leaf_id, "leaf-1")
        self.assertEqual(event.context.mode["ell"], 2)
        self.assertEqual(event.payload["phase"], "PRIMARY")

    def test_progress_modes_are_exact(self):
        self.assertEqual(
            [item.value for item in ProgressMode], ["quiet", "normal", "trace"]
        )

    def test_progress_scope_restores_outer_context_after_nested_exception(self):
        observer = RecordingObserver()
        with activate_progress(observer), progress_scope(leaf_id="leaf-1"):
            with self.assertRaisesRegex(RuntimeError, "stop"):
                with progress_scope(phase="PRIMARY"):
                    raise RuntimeError("stop")
            emit_progress(ProgressEventKind.LEAF_COMPLETED)

        event = observer.events[0]
        self.assertEqual(event.context.leaf_id, "leaf-1")
        self.assertIsNone(event.context.phase)

    def test_event_context_and_payload_are_immutable_snapshots(self):
        observer = RecordingObserver()
        mode = {"ell": 2}
        payload = {"result": {"residual": 1.0}}
        with activate_progress(observer), progress_scope(mode=mode):
            emit_progress(ProgressEventKind.DETERMINANT_EVALUATED, **payload)
        mode["ell"] = 99
        payload["result"]["residual"] = 99.0

        event = observer.events[0]
        self.assertEqual(event.context.mode["ell"], 2)
        self.assertEqual(event.payload["result"]["residual"], 1.0)
        with self.assertRaises(TypeError):
            event.payload["new"] = "value"

    def test_external_event_rejects_unknown_schema_kind_or_context_key(self):
        valid = {
            "schema": PROGRESS_SCHEMA,
            "kind": ProgressEventKind.ROOT_PHASE_STARTED.value,
            "context": {"leaf_id": "leaf-1"},
            "payload": {"phase": "PRIMARY"},
        }
        observer = RecordingObserver()
        with activate_progress(observer):
            ingest_external_progress(valid)
            with self.assertRaises(ValueError):
                ingest_external_progress({**valid, "schema": "unknown/v1"})
            with self.assertRaises(ValueError):
                ingest_external_progress({**valid, "kind": "unknown_kind"})
            with self.assertRaises(ValueError):
                ingest_external_progress(
                    {**valid, "context": {"leaf_id": "leaf-1", "untrusted": 1}}
                )

        self.assertEqual([event.kind for event in observer.events], [
            ProgressEventKind.ROOT_PHASE_STARTED
        ])

    def test_external_progress_overlays_only_its_context_fragment(self):
        observer = RecordingObserver()
        with activate_progress(observer), progress_scope(
            leaf_index=4,
            leaf_id="leaf-4",
            readout_index=9,
            readout_role="positive",
        ):
            ingest_external_progress(
                {
                    "schema": PROGRESS_SCHEMA,
                    "kind": ProgressEventKind.ROOT_PHASE_STARTED.value,
                    "context": {"phase": "PRIMARY"},
                    "payload": {"source": "reader"},
                }
            )

        context = observer.events[0].context
        self.assertEqual(context.leaf_index, 4)
        self.assertEqual(context.leaf_id, "leaf-4")
        self.assertEqual(context.readout_index, 9)
        self.assertEqual(context.readout_role, "positive")
        self.assertEqual(context.phase, "PRIMARY")

    def test_external_progress_uses_explicitly_propagated_reader_context(self):
        observer = RecordingObserver()
        with activate_progress(observer), progress_scope(leaf_id="leaf-reader"):
            reader_context = copy_context()

            def read_one_event():
                ingest_external_progress(
                    {
                        "schema": PROGRESS_SCHEMA,
                        "kind": ProgressEventKind.ROOT_PHASE_STARTED.value,
                        "context": {"phase": "PRIMARY"},
                        "payload": {"source": "thread"},
                    }
                )

            thread = Thread(target=reader_context.run, args=(read_one_event,))
            thread.start()
            thread.join()

        self.assertEqual(len(observer.events), 1)
        self.assertEqual(observer.events[0].context.leaf_id, "leaf-reader")
        self.assertEqual(observer.events[0].context.phase, "PRIMARY")

    def test_mutable_leaf_values_are_snapshotted_without_live_references(self):
        class MutableLeaf:
            def __init__(self, value):
                self.value = value

            def __repr__(self):
                return f"MutableLeaf({self.value!r})"

        observer = RecordingObserver()
        mode_leaf = bytearray(b"before")
        payload_leaf = MutableLeaf("before")
        with activate_progress(observer), progress_scope(
            leaf_index=1, mode={"blob": mode_leaf}
        ):
            emit_progress(
                ProgressEventKind.DETERMINANT_EVALUATED,
                diagnostic=payload_leaf,
            )
        mode_leaf[:] = b"after!"
        payload_leaf.value = "after"

        event = observer.events[0]
        self.assertEqual(event.context.mode["blob"], b"before")
        self.assertEqual(event.payload["diagnostic"], "MutableLeaf('before')")

        with TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint.json"
            reporter = CampaignProgressReporter("trace", checkpoint, io.StringIO())
            reporter.publish(event)
            record = json.loads(
                (Path(f"{checkpoint}.progress") / "leaf-000001.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()[1]
            )

        self.assertEqual(record["context"]["mode"]["blob"], "b'before'")
        self.assertEqual(record["payload"]["diagnostic"], "MutableLeaf('before')")


def _event(kind: ProgressEventKind, **context_values):
    observer = RecordingObserver()
    with activate_progress(observer), progress_scope(**context_values):
        emit_progress(kind, phase=context_values.get("phase", "PRIMARY"))
    return observer.events[0]


class CampaignProgressReporterTests(unittest.TestCase):
    def test_quiet_renders_only_leaf_and_terminal_events(self):
        stream = io.StringIO()
        reporter = CampaignProgressReporter("quiet", Path("checkpoint.json"), stream)
        reporter.publish(_event(ProgressEventKind.CAMPAIGN_STARTED))
        reporter.publish(_event(ProgressEventKind.LEAF_STARTED, leaf_id="leaf-1"))
        reporter.publish(
            _event(
                ProgressEventKind.ROOT_PHASE_STARTED,
                leaf_id="leaf-1",
                phase="PRIMARY",
            )
        )
        reporter.publish(_event(ProgressEventKind.LEAF_COMPLETED, leaf_id="leaf-1"))

        output = stream.getvalue()
        self.assertIn("leaf_started", output)
        self.assertIn("leaf_completed", output)
        self.assertNotIn("campaign_started", output)
        self.assertNotIn("root_phase_started", output)

    def test_normal_renders_identity_phase_newton_and_in_place_determinant_status(self):
        stream = io.StringIO()
        reporter = CampaignProgressReporter("normal", Path("checkpoint.json"), stream)
        reporter.publish(
            _event(
                ProgressEventKind.LEAF_STARTED,
                leaf_id="leaf-1",
                leaf_index=1,
                leaf_count=1,
                role="primary",
            )
        )
        reporter.publish(
            _event(
                ProgressEventKind.ROOT_PHASE_STARTED,
                leaf_id="leaf-1",
                phase="PRIMARY",
            )
        )
        reporter.publish(
            _event(
                ProgressEventKind.NEWTON_ITERATION_STARTED,
                leaf_id="leaf-1",
                phase="PRIMARY",
            )
        )
        reporter.publish(
            _event(
                ProgressEventKind.DETERMINANT_STARTED,
                leaf_id="leaf-1",
                phase="PRIMARY",
            )
        )
        reporter.publish(
            _event(
                ProgressEventKind.DETERMINANT_COMPLETED,
                leaf_id="leaf-1",
                phase="PRIMARY",
            )
        )
        reporter.publish(
            _event(
                ProgressEventKind.DETERMINANT_EVALUATED,
                leaf_id="leaf-1",
                phase="PRIMARY",
            )
        )
        reporter.publish(_event(ProgressEventKind.LEAF_COMPLETED, leaf_id="leaf-1"))

        output = stream.getvalue()
        self.assertIn("leaf=leaf-1", output)
        self.assertIn("root_phase_started", output)
        self.assertIn("newton_iteration_started", output)
        self.assertEqual(output.count("\rdeterminant"), 3)
        self.assertIn("\nleaf_completed", output)

    def test_trace_appends_session_marker_and_flushes_each_leaf_jsonl_event(self):
        with TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint.json"
            event = _event(
                ProgressEventKind.LEAF_STARTED, leaf_id="leaf-1", leaf_index=1
            )
            reporter = CampaignProgressReporter("trace", checkpoint, io.StringIO())
            reporter.publish(event)
            trace_path = Path(f"{checkpoint}.progress") / "leaf-000001.jsonl"
            first_records = [
                json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()
            ]

            second_reporter = CampaignProgressReporter("trace", checkpoint, io.StringIO())
            second_reporter.publish(event)
            records = [
                json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(len(first_records), 2)
        self.assertEqual(len(records), 4)
        self.assertEqual([record["kind"] for record in records[::2]], [
            "session_started", "session_started"
        ])
        event_record = records[1]
        self.assertEqual(event_record["schema"], PROGRESS_SCHEMA)
        self.assertEqual(event_record["kind"], "leaf_started")
        self.assertIn("session", event_record)
        self.assertEqual(event_record["sequence"], 2)
        self.assertIn("timestamp_utc", event_record)
        self.assertIn("elapsed_seconds", event_record)
        self.assertEqual(event_record["context"]["leaf_id"], "leaf-1")
        self.assertEqual(event_record["payload"]["phase"], "PRIMARY")

    def test_trace_flushes_the_writer_for_each_record(self):
        class Writer:
            def __init__(self):
                self.flush_count = 0

            def write(self, value):
                return len(value)

            def flush(self):
                self.flush_count += 1

            def __enter__(self):
                return self

            def __exit__(self, *unused):
                return False

        writer = Writer()
        event = _event(ProgressEventKind.LEAF_STARTED, leaf_id="leaf-1", leaf_index=1)
        with TemporaryDirectory() as directory, patch.object(Path, "open", return_value=writer):
            reporter = CampaignProgressReporter(
                "trace", Path(directory) / "checkpoint.json", io.StringIO()
            )
            reporter.publish(event)

        self.assertEqual(writer.flush_count, 2)

    def test_trace_skips_non_leaf_events_without_diagnostics_then_starts_leaf_file(self):
        with TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint.json"
            reporter = CampaignProgressReporter("trace", checkpoint, io.StringIO())
            reporter.publish(_event(ProgressEventKind.CAMPAIGN_STARTED))
            reporter.publish(_event(ProgressEventKind.CAMPAIGN_COMPLETED))

            trace_directory = Path(f"{checkpoint}.progress")
            self.assertFalse(trace_directory.exists())
            self.assertEqual(reporter.diagnostics, [])

            reporter.publish(
                _event(ProgressEventKind.LEAF_STARTED, leaf_id="leaf-1", leaf_index=1)
            )
            records = [
                json.loads(line)
                for line in (trace_directory / "leaf-000001.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]

        self.assertEqual([record["kind"] for record in records], [
            "session_started", "leaf_started"
        ])
        self.assertEqual(reporter.diagnostics, [])

    def test_trace_sequences_remain_monotonic_across_leaf_files(self):
        with TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint.json"
            reporter = CampaignProgressReporter("trace", checkpoint, io.StringIO())
            reporter.publish(
                _event(ProgressEventKind.LEAF_STARTED, leaf_id="leaf-1", leaf_index=1)
            )
            reporter.publish(
                _event(ProgressEventKind.LEAF_STARTED, leaf_id="leaf-2", leaf_index=2)
            )
            trace_directory = Path(f"{checkpoint}.progress")
            sequences = []
            for leaf_index in (1, 2):
                records = [
                    json.loads(line)
                    for line in (trace_directory / f"leaf-{leaf_index:06d}.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()
                ]
                sequences.extend(record["sequence"] for record in records)

        self.assertEqual(sequences, [1, 2, 3, 4])

    def test_trace_human_identity_includes_suboperation_and_determinant_purpose(self):
        with TemporaryDirectory() as directory:
            stream = io.StringIO()
            reporter = CampaignProgressReporter(
                "trace", Path(directory) / "checkpoint.json", stream
            )
            reporter.publish(
                _event(
                    ProgressEventKind.SUBOPERATION_STARTED,
                    leaf_id="leaf-1",
                    leaf_index=1,
                    suboperation="angular",
                    determinant_purpose="candidate",
                )
            )

        output = stream.getvalue()
        self.assertIn("suboperation=angular", output)
        self.assertIn("determinant_purpose=candidate", output)

    def test_progress_event_kinds_include_stable_determinant_and_julia_lifecycle_names(self):
        self.assertEqual(ProgressEventKind.DETERMINANT_STARTED.value, "determinant_started")
        self.assertEqual(ProgressEventKind.DETERMINANT_COMPLETED.value, "determinant_completed")
        self.assertEqual(ProgressEventKind.REQUEST_STARTED.value, "request_started")
        self.assertEqual(ProgressEventKind.REQUEST_VALIDATED.value, "request_validated")
        self.assertEqual(ProgressEventKind.REQUEST_COMPLETED.value, "request_completed")
        self.assertEqual(ProgressEventKind.REQUEST_FAILED.value, "request_failed")

    def test_reporter_contains_stream_and_trace_failures(self):
        class BrokenStream:
            def write(self, value):
                raise OSError("broken progress stream")

            def flush(self):
                raise OSError("broken progress stream")

        event = _event(ProgressEventKind.LEAF_STARTED, leaf_id="leaf-1", leaf_index=1)
        reporter = CampaignProgressReporter("trace", Path("checkpoint.json"), BrokenStream())
        reporter.publish(event)

        self.assertEqual(len(reporter.diagnostics), 1)
        self.assertIn("OSError", reporter.diagnostics[0])

    def test_reporter_contains_trace_io_failure(self):
        event = _event(ProgressEventKind.LEAF_STARTED, leaf_id="leaf-1", leaf_index=1)
        stream = io.StringIO()
        with TemporaryDirectory() as directory:
            with patch.object(Path, "open", side_effect=OSError("trace unavailable")):
                reporter = CampaignProgressReporter(
                    "trace", Path(directory) / "checkpoint.json", stream
                )
                reporter.publish(event)

        self.assertEqual(len(reporter.diagnostics), 1)
        self.assertIn("trace unavailable", reporter.diagnostics[0])


if __name__ == "__main__":
    unittest.main()
