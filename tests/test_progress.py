from __future__ import annotations

import io
import json
import sys
from dataclasses import replace
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
from windows_solver.cli import build_parser


class RecordingObserver:
    def __init__(self) -> None:
        self.events = []

    def publish(self, event) -> None:
        self.events.append(event)


class ProgressBusTests(unittest.TestCase):
    def test_campaign_run_and_resume_default_to_normal_progress(self):
        parser = build_parser()
        for command in ("campaign-run", "campaign-resume"):
            arguments = parser.parse_args(
                [command, "selection.json", "--checkpoint", "checkpoint.json"]
            )
            self.assertEqual(arguments.progress, "normal")
            traced = parser.parse_args(
                [
                    command,
                    "selection.json",
                    "--checkpoint",
                    "checkpoint.json",
                    "--progress",
                    "trace",
                ]
            )
            self.assertEqual(traced.progress, "trace")

    def test_progress_context_carries_unambiguous_omega_and_counter_fields(self):
        observer = RecordingObserver()
        omega = {"real": 0.5, "imaginary": -0.1}
        with activate_progress(observer), progress_scope(
            seed_omega=omega,
            current_omega=omega,
            candidate_omega=omega,
            determinant_index_leaf=137,
            determinant_index_phase=42,
            determinant_index_newton=3,
        ):
            emit_progress(ProgressEventKind.DETERMINANT_COMPLETED)

        context = observer.events[0].context
        self.assertEqual(context.seed_omega, omega)
        self.assertEqual(context.current_omega, omega)
        self.assertEqual(context.candidate_omega, omega)
        self.assertEqual(context.determinant_index_leaf, 137)
        self.assertEqual(context.determinant_index_phase, 42)
        self.assertEqual(context.determinant_index_newton, 3)

    def test_progress_context_carries_seed_strategy_without_entering_scientific_payloads(self):
        observer = RecordingObserver()
        with activate_progress(observer), progress_scope(
            seed_kind="EPSILON_CONTINUATION",
            fallback_used=False,
        ):
            emit_progress(ProgressEventKind.ROOT_SEED_SELECTED)

        context = observer.events[0].context
        self.assertEqual(context.seed_kind, "EPSILON_CONTINUATION")
        self.assertIs(context.fallback_used, False)

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


def _payload_event(kind: ProgressEventKind, payload, **context_values):
    observer = RecordingObserver()
    with activate_progress(observer), progress_scope(**context_values):
        emit_progress(kind, **payload)
    return observer.events[0]


class CampaignProgressReporterTests(unittest.TestCase):
    def setUp(self):
        self._reporter_directory = TemporaryDirectory()
        self.reporter_checkpoint = (
            Path(self._reporter_directory.name) / "checkpoint.json"
        )

    def tearDown(self):
        self._reporter_directory.cleanup()

    def _console_reporter(self, stream):
        # StringIO can model terminal output but can never supply a real Windows
        # console handle to SetConsoleMode.
        with patch.object(
            CampaignProgressReporter,
            "_enable_virtual_terminal",
            return_value=True,
        ):
            return CampaignProgressReporter(
                "normal", self.reporter_checkpoint, stream
            )

    def test_normal_defaults_to_the_main_stdout_console(self):
        class ConsoleStream(io.StringIO):
            def isatty(self):
                return True

        console = ConsoleStream()
        with patch("windows_solver.progress_output.sys.stdout", console):
            reporter = CampaignProgressReporter("normal", self.reporter_checkpoint)

        self.assertIs(reporter.stream, console)

    def test_normal_keeps_redirected_canonical_stdout_clean(self):
        redirected = io.StringIO()
        with patch("windows_solver.progress_output.sys.stdout", redirected):
            reporter = CampaignProgressReporter("normal", self.reporter_checkpoint)

        self.assertIs(reporter.stream, sys.stderr)

    def test_normal_non_terminal_preserves_lifecycle_and_detail_lines(self):
        stream = io.StringIO()
        reporter = CampaignProgressReporter("normal", self.reporter_checkpoint, stream)
        events = (
            _payload_event(
                ProgressEventKind.LEAF_REUSED,
                {"state": "PRODUCED"},
                leaf_id="leaf-1",
            ),
            _event(ProgressEventKind.CHECKPOINT_WRITING, leaf_id="leaf-2"),
            _event(ProgressEventKind.CHECKPOINT_WRITTEN, leaf_id="leaf-2"),
            _payload_event(
                ProgressEventKind.PRECISION_STAGE_COMPLETED,
                {"numerical_state": "CONVERGED", "leaf_state": "PRODUCED"},
                leaf_id="leaf-2",
            ),
            _event(ProgressEventKind.ROOT_PHASE_STARTED, leaf_id="leaf-2"),
            _event(ProgressEventKind.NEWTON_ITERATION_STARTED, leaf_id="leaf-2"),
            _payload_event(
                ProgressEventKind.DETERMINANT_COMPLETED,
                {"determinant_abs": 1.0e-12},
                leaf_id="leaf-2",
            ),
            _event(ProgressEventKind.SUBOPERATION_COMPLETED, leaf_id="leaf-2"),
        )
        for event in events:
            reporter.publish(event)

        output = stream.getvalue()
        for kind in (
            "leaf_reused",
            "checkpoint_writing",
            "checkpoint_written",
            "precision_stage_completed",
            "root_phase_started",
            "newton_iteration_started",
            "determinant_completed",
            "suboperation_completed",
        ):
            self.assertIn(kind, output)

    def test_normal_writes_atomic_live_status_for_second_process_inspection(self):
        with TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint.json"
            reporter = CampaignProgressReporter("normal", checkpoint, io.StringIO())
            reporter.publish(
                _event(
                    ProgressEventKind.LEAF_STARTED,
                    leaf_id="leaf-1",
                    leaf_index=1,
                    leaf_count=553,
                    role="primary",
                    mode={"s": -2, "ell": 2, "m": 2, "n": 0},
                    spin=0.95,
                    sampling_coordinate={"coordinate_id": "a_over_M", "value": 0.95},
                    mechanism_id="horizon-admittance",
                )
            )
            status_path = Path(f"{checkpoint}.status.json")
            status = json.loads(status_path.read_text(encoding="utf-8"))

        self.assertEqual(status["kind"], "leaf_started")
        self.assertEqual(status["context"]["leaf_index"], 1)
        self.assertEqual(status["context"]["leaf_count"], 553)
        self.assertEqual(status["context"]["mode"]["ell"], 2)

    def test_primary_seed_telemetry_aggregates_calls_iterations_fallbacks_and_time(self):
        reporter = CampaignProgressReporter(
            "normal", self.reporter_checkpoint, io.StringIO()
        )

        def publish_primary(
            *, readout_index, seed_kind, fallback_used, determinants, newtons, elapsed
        ):
            context = {
                "leaf_id": "leaf-1",
                "leaf_index": 1,
                "leaf_count": 212,
                "readout_index": readout_index,
                "phase": "PRIMARY",
                "seed_kind": seed_kind,
                "fallback_used": fallback_used,
                "seed_omega": {"real": 0.5, "imaginary": -0.1},
            }
            reporter.publish(_event(ProgressEventKind.ROOT_PHASE_STARTED, **context))
            reporter.publish(
                _payload_event(
                    ProgressEventKind.ROOT_SEED_SELECTED,
                    {
                        "requested_seed_kind": (
                            "EPSILON_CONTINUATION"
                            if fallback_used
                            else seed_kind
                        ),
                        "seed_kind": seed_kind,
                        "fallback_used": fallback_used,
                        "fallback_reason": (
                            "PREDICTOR_NEWTON_FAILED" if fallback_used else None
                        ),
                        "seed_omega": {"real": 0.5, "imaginary": -0.1},
                    },
                    **context,
                )
            )
            for index in range(determinants):
                reporter.publish(
                    _payload_event(
                        ProgressEventKind.DETERMINANT_STARTED,
                        {"purpose": f"det-{index}"},
                        **context,
                    )
                )
                reporter.publish(
                    _payload_event(
                        ProgressEventKind.DETERMINANT_COMPLETED,
                        {"determinant_abs": 1.0e-3 / (index + 1)},
                        **context,
                    )
                )
            for index in range(newtons):
                reporter.publish(
                    _event(
                        ProgressEventKind.NEWTON_ITERATION_STARTED,
                        **context,
                        newton_index=index + 1,
                    )
                )
            reporter.publish(
                _payload_event(
                    ProgressEventKind.ROOT_PHASE_COMPLETED,
                    {
                        "resulting_omega": {"real": 0.49, "imaginary": -0.09},
                        "resulting_determinant_abs": 1.0e-12,
                        "converged": True,
                        "elapsed_seconds": elapsed,
                    },
                    **context,
                )
            )

        publish_primary(
            readout_index=1,
            seed_kind="AUTHENTICATED_BACKGROUND",
            fallback_used=False,
            determinants=10,
            newtons=3,
            elapsed=12.0,
        )
        publish_primary(
            readout_index=2,
            seed_kind="EPSILON_CONTINUATION",
            fallback_used=False,
            determinants=6,
            newtons=2,
            elapsed=7.0,
        )
        publish_primary(
            readout_index=3,
            seed_kind="FALLBACK_BACKGROUND",
            fallback_used=True,
            determinants=14,
            newtons=5,
            elapsed=18.0,
        )
        reporter.publish(
            _event(
                ProgressEventKind.LEAF_COMPLETED,
                leaf_id="leaf-1",
                leaf_index=1,
                leaf_count=212,
            )
        )
        status = json.loads(
            Path(f"{self.reporter_checkpoint}.status.json").read_text(
                encoding="utf-8"
            )
        )

        summary = status["momentum_summary"]
        self.assertEqual(summary["primary_solve_count"], 3)
        self.assertEqual(summary["epsilon_continuation_fallback_rate"], 0.5)
        self.assertEqual(
            summary["by_seed_kind"]["EPSILON_CONTINUATION"],
            {
                "solve_count": 1,
                "fallback_count": 0,
                "total_newton_iterations": 2,
                "average_newton_iterations": 2.0,
                "total_determinant_calls": 6,
                "average_determinant_calls": 6.0,
                "total_elapsed_seconds": 7.0,
                "mean_solve_seconds": 7.0,
            },
        )
        self.assertEqual(
            summary["observed_epsilon_determinant_call_delta_vs_background_mean"],
            4.0,
        )
        root_solve_path = (
            Path(f"{self.reporter_checkpoint}.progress") / "root-solves.jsonl"
        )
        root_solves = [
            json.loads(line)
            for line in root_solve_path.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(len(root_solves), 3)
        self.assertEqual(
            root_solves[1]["root_solve"],
            {
                "requested_seed_kind": "EPSILON_CONTINUATION",
                "seed_kind": "EPSILON_CONTINUATION",
                "seed_omega": {"real": 0.5, "imaginary": -0.1},
                "fallback_used": False,
                "fallback_reason": None,
                "fallback_error_type": None,
                "initial_determinant_abs": 0.001,
                "predictor_initial_determinant_abs": None,
                "newton_iterations": 2,
                "determinant_calls": 6,
                "resulting_omega": {"real": 0.49, "imaginary": -0.09},
                "resulting_determinant_abs": 1.0e-12,
                "converged": True,
                "elapsed_seconds": 7.0,
            },
        )

    def test_root_telemetry_separates_precision_and_component_pass(self):
        reporter = CampaignProgressReporter(
            "normal", self.reporter_checkpoint, io.StringIO()
        )

        def publish_root(*, digits, component_pass):
            context = {
                "leaf_id": "leaf-1",
                "leaf_index": 1,
                "leaf_count": 212,
                "precision_digits": digits,
                "component_pass": component_pass,
                "readout_index": 1,
                "phase": "PRIMARY",
            }
            reporter.publish(_event(ProgressEventKind.ROOT_PHASE_STARTED, **context))
            reporter.publish(
                _payload_event(
                    ProgressEventKind.ROOT_SEED_SELECTED,
                    {
                        "requested_seed_kind": "AUTHENTICATED_BACKGROUND",
                        "seed_kind": "AUTHENTICATED_BACKGROUND",
                        "seed_omega": {"real": 0.5, "imaginary": -0.1},
                        "fallback_used": False,
                        "fallback_reason": None,
                    },
                    **context,
                )
            )
            reporter.publish(
                _payload_event(
                    ProgressEventKind.DETERMINANT_STARTED,
                    {"purpose": "initial"},
                    **context,
                )
            )
            reporter.publish(
                _payload_event(
                    ProgressEventKind.DETERMINANT_COMPLETED,
                    {"determinant_abs": 1.0e-3},
                    **context,
                )
            )
            reporter.publish(
                _payload_event(
                    ProgressEventKind.ROOT_PHASE_COMPLETED,
                    {
                        "resulting_omega": {"real": 0.49, "imaginary": -0.09},
                        "resulting_determinant_abs": 1.0e-12,
                        "converged": True,
                        "elapsed_seconds": 1.0,
                    },
                    **context,
                )
            )

        publish_root(digits=64, component_pass="primary")
        publish_root(digits=80, component_pass="primary")
        publish_root(digits=80, component_pass="self-refinement")

        root_solve_path = (
            Path(f"{self.reporter_checkpoint}.progress") / "root-solves.jsonl"
        )
        root_solves = [
            json.loads(line)
            for line in root_solve_path.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(len(root_solves), 3)
        self.assertEqual(
            [record["root_solve"]["determinant_calls"] for record in root_solves],
            [1, 1, 1],
        )
        self.assertEqual(
            root_solves[-1]["momentum_summary"]["primary_solve_count"], 3
        )

    def test_normal_console_dashboard_matches_the_working_status_view(self):
        class ConsoleStream(io.StringIO):
            def isatty(self):
                return True

        stream = ConsoleStream()
        reporter = self._console_reporter(stream)
        shared_context = {
            "leaf_id": (
                "b-prime-leaf-"
                "9e5777728144433e089f9559b92b6e139e16115a5a53099f40403a45297aa3c3"
            ),
            "leaf_index": 1,
            "leaf_count": 553,
            "role": "primary",
            "mode": {"s": -2, "ell": 2, "m": 2, "n": 0},
            "spin": 0.95,
            "mechanism_id": "horizon-admittance",
            "precision_digits": 64,
            "phase": "SEED-PATH",
            "newton_index": 1,
            "newton_limit": 12,
            "current_omega": {
                "real": 0.7467570512425654,
                "imaginary": -0.052930481783164646,
            },
        }
        reporter.publish(
            replace(
                _event(ProgressEventKind.DETERMINANT_STARTED, **shared_context),
                monotonic_seconds=1.0,
            )
        )
        reporter.publish(
            replace(
                _payload_event(
                    ProgressEventKind.DETERMINANT_COMPLETED,
                    {"determinant_abs": 3.2e-8},
                    **shared_context,
                ),
                monotonic_seconds=2.0,
            )
        )
        reporter.publish(
            replace(
                _payload_event(
                    ProgressEventKind.SUBOPERATION_COMPLETED,
                    {"elapsed_seconds": 0.42},
                    leaf_id=shared_context["leaf_id"],
                    leaf_index=1,
                    leaf_count=553,
                    precision_digits=64,
                    phase="SEED-PATH",
                    newton_index=1,
                    suboperation="Xup",
                ),
                monotonic_seconds=3.0,
            )
        )

        output = stream.getvalue()
        latest_panel = output.rsplit("\x1b8", 1)[-1]
        self.assertIn("Sequence       : 3", latest_panel)
        self.assertIn("Event          : suboperation_completed", latest_panel)
        self.assertIn("Leaf           : 1/553", latest_panel)
        self.assertIn("Role           : primary", latest_panel)
        self.assertIn("Mode           : @{ell=2; m=2; n=0; s=-2}", latest_panel)
        self.assertIn("Spin           : 0.95", latest_panel)
        self.assertIn("Mechanism      : horizon-admittance", latest_panel)
        self.assertIn("Precision      : 64", latest_panel)
        self.assertIn("Phase          : SEED-PATH", latest_panel)
        self.assertIn("Newton         : 1", latest_panel)
        self.assertIn(
            "CurrentOmega   : @{imaginary=-0.052930481783164646; "
            "real=0.7467570512425654}",
            latest_panel,
        )
        self.assertIn("DeterminantAbs : 3.2e-08", latest_panel)
        self.assertIn("DetLeaf        : 1", latest_panel)
        self.assertIn("DetPhase       : 1", latest_panel)
        self.assertIn("DetNewton      : 1", latest_panel)
        self.assertIn("Suboperation   : Xup", latest_panel)
        self.assertNotIn("\rdeterminant", latest_panel)
        self.assertNotIn(" leaf_id=", latest_panel)
        self.assertNotIn(" current_|D|=", latest_panel)
        self.assertNotIn("\x1b[2J", latest_panel)
        status = json.loads(
            Path(f"{self.reporter_checkpoint}.status.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(status["current_determinant_abs"], 3.2e-8)
        self.assertEqual(status["context"]["determinant_index_leaf"], 1)
        self.assertEqual(status["context"]["determinant_index_phase"], 1)
        self.assertEqual(status["context"]["determinant_index_newton"], 1)

    def test_live_status_throttles_detail_events_but_forces_leaf_visibility(self):
        reporter = CampaignProgressReporter(
            "normal", self.reporter_checkpoint, io.StringIO()
        )
        with patch.object(reporter, "_write_status") as write_status:
            reporter.publish(
                _event(
                    ProgressEventKind.LEAF_STARTED,
                    leaf_id="leaf-1",
                    leaf_index=1,
                    leaf_count=553,
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
                _payload_event(
                    ProgressEventKind.DETERMINANT_COMPLETED,
                    {"determinant_abs": 1.0e-12},
                    leaf_id="leaf-1",
                    phase="PRIMARY",
                )
            )

        self.assertEqual(write_status.call_count, 1)
    def test_quiet_renders_only_leaf_and_terminal_events(self):
        stream = io.StringIO()
        reporter = CampaignProgressReporter("quiet", self.reporter_checkpoint, stream)
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

    def test_normal_console_redraws_only_its_panel_without_clearing_history(self):
        class ConsoleStream(io.StringIO):
            def isatty(self):
                return True

        stream = ConsoleStream()
        history = "[bootstrap] solver plan succeeded\nPS> .\\m02.ps1\n"
        stream.write(history)
        reporter = self._console_reporter(stream)
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
                ProgressEventKind.LEAF_COMPLETED,
                leaf_id="leaf-1",
                leaf_index=1,
                leaf_count=1,
                role="primary",
            )
        )

        output = stream.getvalue()
        self.assertTrue(output.startswith(history + "\x1b[0J"))
        self.assertIn("\x1b[39F", output)
        self.assertNotIn("\x1b7", output)
        self.assertNotIn("\x1b8", output)
        self.assertEqual(output.count("\x1b[0J"), 2)
        self.assertNotIn("\x1b[2J", output)
        self.assertIn("Event          : leaf_started", output)
        self.assertIn("Event          : leaf_completed", output)

    def test_normal_console_compacts_without_wrapping_or_scrollback_panels(self):
        class ConsoleStream(io.StringIO):
            def isatty(self):
                return True

        stream = ConsoleStream()
        history = "[bootstrap] solver plan succeeded\nPS> .\\m02.ps1\n"
        stream.write(history)
        reporter = self._console_reporter(stream)
        with patch.object(reporter, "_terminal_dimensions", return_value=(80, 24)):
            first = _payload_event(
                ProgressEventKind.DETERMINANT_COMPLETED,
                {
                    "determinant_abs": 3.2e-8,
                    "best_determinant_abs": 2.1e-9,
                    "acceptance_threshold": 1.0e-10,
                },
                leaf_id="b-prime-leaf-" + "9" * 64,
                leaf_index=1,
                leaf_count=553,
                role="primary",
                mode={"s": -2, "ell": 2, "m": 2, "n": 0},
                spin=0.95,
                mechanism_id="horizon-admittance",
                precision_digits=64,
                phase="PRIMARY",
                newton_index=2,
                determinant_index_leaf=137,
                determinant_index_phase=42,
                determinant_index_newton=3,
                suboperation="Xup integration",
            )
            reporter.publish(first)
            reporter.publish(
                replace(
                    _event(
                        ProgressEventKind.SUBOPERATION_COMPLETED,
                        leaf_id="b-prime-leaf-" + "9" * 64,
                        leaf_index=1,
                        leaf_count=553,
                        phase="PRIMARY",
                        suboperation="Xup integration",
                    ),
                    monotonic_seconds=first.monotonic_seconds + 1.0,
                )
            )

        output = stream.getvalue()
        self.assertTrue(output.startswith(history + "\x1b[0J"))
        self.assertIn("\x1b[15F", output)
        self.assertNotIn("\x1b7", output)
        self.assertNotIn("\x1b8", output)
        self.assertNotIn("\x1b[2J", output)
        latest_panel = output.rsplit("\x1b[15F\x1b[0J", 1)[-1]
        lines = latest_panel.splitlines()
        self.assertEqual(len(lines), 15)
        self.assertTrue(all(len(line) <= 80 for line in lines))
        self.assertIn("M02 CAMPAIGN", latest_panel)
        self.assertIn("LeafStatus: RUNNING", latest_panel)
        self.assertIn("Completed: 0/553 | Accepted: 0 | Rejected: 0", latest_panel)
        self.assertIn("DeterminantAbs: 3.2e-08", latest_panel)
        self.assertIn("DetLeaf: 137 | DetPhase: 42 | DetNewton: 3", latest_panel)
        self.assertIn("Suboperation: Xup integration", latest_panel)

    def test_partial_campaign_settles_missing_precision_leaf_without_rejection(self):
        class ConsoleStream(io.StringIO):
            def isatty(self):
                return True

        stream = ConsoleStream()
        reporter = self._console_reporter(stream)
        leaf_context = {"leaf_id": "leaf-1", "leaf_index": 1, "leaf_count": 553}
        reporter.publish(_event(ProgressEventKind.LEAF_STARTED, **leaf_context))
        reporter.publish(
            _payload_event(
                ProgressEventKind.PRECISION_STAGE_COMPLETED,
                {
                    "numerical_state": "NOT_CONVERGED",
                    "leaf_state": "MISSING_PRECISION",
                },
                **leaf_context,
            )
        )
        reporter.publish(
            _payload_event(
                ProgressEventKind.CAMPAIGN_COMPLETED,
                {"state": "PARTIAL"},
            )
        )

        latest_panel = stream.getvalue().rsplit("\x1b[36F", 1)[-1]
        self.assertIn("CampaignStatus : PARTIAL", latest_panel)
        self.assertIn("LeafStatus     : MISSING_PRECISION", latest_panel)
        self.assertIn("Completed      : 0/553", latest_panel)
        self.assertIn("Rejected       : 0", latest_panel)
        self.assertIn("Indeterminate  : 0", latest_panel)

    def test_normal_console_estimates_eta_from_rolling_completed_leaf_timings(self):
        class ConsoleStream(io.StringIO):
            def isatty(self):
                return True

        stream = ConsoleStream()
        reporter = self._console_reporter(stream)
        reporter.publish(
            replace(
                _event(
                    ProgressEventKind.LEAF_STARTED,
                    leaf_id="leaf-1",
                    leaf_index=1,
                    leaf_count=553,
                ),
                monotonic_seconds=100.0,
            )
        )
        reporter.publish(
            replace(
                _event(
                    ProgressEventKind.LEAF_COMPLETED,
                    leaf_id="leaf-1",
                    leaf_index=1,
                    leaf_count=553,
                ),
                monotonic_seconds=892.0,
            )
        )
        reporter.publish(
            replace(
                _event(
                    ProgressEventKind.LEAF_STARTED,
                    leaf_id="leaf-2",
                    leaf_index=2,
                    leaf_count=553,
                ),
                monotonic_seconds=900.0,
            )
        )

        latest_panel = stream.getvalue().rsplit("\x1b8", 1)[-1]
        self.assertIn("TimingSample   : 1/10", latest_panel)
        self.assertIn("AvgLeaf        : 13m 12s", latest_panel)
        self.assertIn("MedianLeaf     : 13m 12s", latest_panel)
        self.assertIn("ETA            : 5d 1h 26m", latest_panel)
        self.assertRegex(
            latest_panel,
            r"Finish         : \d{4}-\d{2}-\d{2} \d{2}:\d{2} [+-]\d{2}:\d{2}",
        )

    def test_normal_console_timing_window_excludes_old_and_reused_leaves(self):
        class ConsoleStream(io.StringIO):
            def isatty(self):
                return True

        stream = ConsoleStream()
        reporter = self._console_reporter(stream)
        current = 0.0
        for leaf_index in range(1, 12):
            reporter.publish(
                replace(
                    _event(
                        ProgressEventKind.LEAF_STARTED,
                        leaf_id=f"leaf-{leaf_index}",
                        leaf_index=leaf_index,
                        leaf_count=20,
                    ),
                    monotonic_seconds=current,
                )
            )
            current += 100.0 if leaf_index == 1 else 10.0
            reporter.publish(
                replace(
                    _payload_event(
                        ProgressEventKind.LEAF_COMPLETED,
                        {"state": "PRODUCED"},
                        leaf_id=f"leaf-{leaf_index}",
                        leaf_index=leaf_index,
                        leaf_count=20,
                    ),
                    monotonic_seconds=current,
                )
            )
        reporter.publish(
            replace(
                _payload_event(
                    ProgressEventKind.LEAF_REUSED,
                    {"state": "PRODUCED"},
                    leaf_id="leaf-12",
                    leaf_index=12,
                    leaf_count=20,
                ),
                monotonic_seconds=current + 1.0,
            )
        )

        latest_panel = stream.getvalue().rsplit("\x1b8", 1)[-1]
        self.assertIn("TimingSample   : 10/10", latest_panel)
        self.assertIn("AvgLeaf        : 10s", latest_panel)
        self.assertIn("MedianLeaf     : 10s", latest_panel)
        self.assertIn("Completed      : 12/20", latest_panel)

    def test_normal_console_reports_authenticated_acceptance_and_checkpoint_state(self):
        class ConsoleStream(io.StringIO):
            def isatty(self):
                return True

        stream = ConsoleStream()
        reporter = self._console_reporter(stream)
        leaf_context = {
            "leaf_id": "leaf-1",
            "leaf_index": 1,
            "leaf_count": 553,
            "precision_digits": 64,
            "phase": "PRIMARY",
        }
        events = (
            _event(ProgressEventKind.LEAF_STARTED, **leaf_context),
            _event(ProgressEventKind.ROOT_PHASE_STARTED, **leaf_context),
            _payload_event(
                ProgressEventKind.NEWTON_ITERATION_STARTED,
                {
                    "determinant_abs": 3.2e-8,
                    "best_determinant_abs": 2.1e-9,
                    "acceptance_threshold": 1.0e-10,
                },
                **leaf_context,
                newton_index=2,
            ),
            _payload_event(
                ProgressEventKind.ROOT_PHASE_COMPLETED,
                {"converged": True, "resulting_determinant_abs": 2.1e-9},
                **leaf_context,
            ),
            _event(ProgressEventKind.PRECISION_STAGE_STARTED, **leaf_context),
            _event(ProgressEventKind.CHECKPOINT_WRITING, **leaf_context),
            _event(ProgressEventKind.CHECKPOINT_WRITTEN, **leaf_context),
            _payload_event(
                ProgressEventKind.PRECISION_STAGE_COMPLETED,
                {"numerical_state": "CONVERGED", "leaf_state": "PRODUCED"},
                **leaf_context,
            ),
            _payload_event(
                ProgressEventKind.LEAF_COMPLETED,
                {"state": "PRODUCED", "stage_count": 1},
                **leaf_context,
            ),
        )
        for index, event in enumerate(events, start=1):
            reporter.publish(replace(event, monotonic_seconds=float(index)))

        latest_panel = stream.getvalue().rsplit("\x1b8", 1)[-1]
        self.assertIn("LeafStatus     : ACCEPTED", latest_panel)
        self.assertIn("RootStatus     : CONVERGED", latest_panel)
        self.assertIn("PrecisionStatus: CONVERGED", latest_panel)
        self.assertIn("Completed      : 1/553", latest_panel)
        self.assertIn("Accepted       : 1", latest_panel)
        self.assertIn("Rejected       : 0", latest_panel)
        self.assertIn("Indeterminate  : 0", latest_panel)
        self.assertIn("Failed         : 0", latest_panel)
        self.assertIn("LastAccepted   : leaf-1", latest_panel)
        self.assertIn("BestDetAbs     : 2.1e-09", latest_panel)
        self.assertIn("Threshold      : 1e-10", latest_panel)
        self.assertIn("Checkpoint     : written", latest_panel)

        reporter.publish(
            replace(
                _payload_event(
                    ProgressEventKind.LEAF_REUSED,
                    {"state": "UNRESOLVED", "stage_count": 1},
                    leaf_id="leaf-2",
                    leaf_index=2,
                    leaf_count=553,
                ),
                monotonic_seconds=20.0,
            )
        )
        reused_panel = stream.getvalue().rsplit("\x1b8", 1)[-1]
        self.assertIn("LeafStatus     : INDETERMINATE", reused_panel)
        self.assertIn("Completed      : 2/553", reused_panel)
        self.assertIn("Accepted       : 1", reused_panel)
        self.assertIn("Indeterminate  : 1", reused_panel)
        self.assertIn("LastAccepted   : leaf-1", reused_panel)
        self.assertIn("Checkpoint     : written", reused_panel)

        reporter.publish(
            replace(
                _payload_event(
                    ProgressEventKind.LEAF_FAILED,
                    {"error_type": "RuntimeError", "message": "backend stopped"},
                    leaf_id="leaf-3",
                    leaf_index=3,
                    leaf_count=553,
                ),
                monotonic_seconds=21.0,
            )
        )
        failed_panel = stream.getvalue().rsplit("\x1b8", 1)[-1]
        self.assertIn("LeafStatus     : FAILED", failed_panel)
        self.assertIn("Completed      : 2/553", failed_panel)
        self.assertIn("Rejected       : 0", failed_panel)
        self.assertIn("Failed         : 1", failed_panel)

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
        reporter = CampaignProgressReporter(
            "trace", self.reporter_checkpoint, BrokenStream()
        )
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
