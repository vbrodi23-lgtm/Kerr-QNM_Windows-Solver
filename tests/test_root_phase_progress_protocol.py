from __future__ import annotations

import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from windows_solver.julia_response_backend import (
    JULIA_PROGRESS_PREFIX,
    _forward_julia_progress_line,
)
from windows_solver.progress import (
    PROGRESS_SCHEMA,
    ProgressContext,
    ProgressEventKind,
    activate_progress,
    ingest_external_progress,
    progress_scope,
)
from windows_solver.progress_output import CampaignProgressReporter


class RecordingObserver:
    def __init__(self) -> None:
        self.events = []

    def publish(self, event) -> None:
        self.events.append(event)


def _staged_authentication_event() -> dict[str, object]:
    return {
        "schema": PROGRESS_SCHEMA,
        "kind": ProgressEventKind.PRIMARY_STAGED_AUTHENTICATION_COMPLETED.value,
        "context": {
            "phase": "PRIMARY",
            "root_phase": "PRIMARY",
            "seed_omega": {"real": "0.744582", "imaginary": "-0.159687"},
            "current_omega": {"real": "0.744582", "imaginary": "-0.159687"},
        },
        "payload": {
            "phase": "PRIMARY",
            "root_phase": "PRIMARY",
            "authentication_mode": "STAGED_FULL_AUTHENTICATION",
            "authoritative": True,
            "full_authentication_escalated": False,
            "escalation_reason": None,
            "determinant_count_phase": 8,
            "residual_upper_bound_abs": "2.8e-14",
            "derivative_lower_bound_abs": "2",
            "required_derivative_lower_bound_abs": "1.4e-3",
            "correction_upper_bound": "1.4e-14",
            "root_correction_tolerance": "2e-11",
        },
    }


class RootPhaseProgressProtocolTests(unittest.TestCase):
    def test_external_staged_root_phase_context_is_accepted(self) -> None:
        observer = RecordingObserver()

        with activate_progress(observer), progress_scope(
            leaf_id="leaf-13",
            precision_digits=80,
            mechanism_id="horizon-admittance",
        ):
            forwarded = ingest_external_progress(
                _staged_authentication_event()
            )

        self.assertEqual(len(observer.events), 1)
        self.assertIs(forwarded, observer.events[0])
        self.assertIs(
            forwarded.kind,
            ProgressEventKind.PRIMARY_STAGED_AUTHENTICATION_COMPLETED,
        )
        self.assertEqual(forwarded.context.leaf_id, "leaf-13")
        self.assertEqual(forwarded.context.phase, "PRIMARY")
        self.assertEqual(forwarded.context.root_phase, "PRIMARY")
        self.assertEqual(
            forwarded.payload["authentication_mode"],
            "STAGED_FULL_AUTHENTICATION",
        )
        self.assertIs(forwarded.payload["authoritative"], True)
        self.assertEqual(forwarded.payload["determinant_count_phase"], 8)

    def test_progress_context_mapping_preserves_phase_and_root_phase(self) -> None:
        mapping = ProgressContext(
            phase="CAMPAIGN",
            root_phase="PRIMARY",
        ).to_mapping()

        self.assertEqual(mapping["phase"], "CAMPAIGN")
        self.assertEqual(mapping["root_phase"], "PRIMARY")

    def test_root_phase_context_remains_type_checked(self) -> None:
        observer = RecordingObserver()
        event = {
            "schema": PROGRESS_SCHEMA,
            "kind": ProgressEventKind.ROOT_PHASE_STARTED.value,
            "context": {
                "phase": "PRIMARY",
                "root_phase": 13,
            },
            "payload": {},
        }

        with activate_progress(observer):
            with self.assertRaisesRegex(
                ValueError,
                "progress context root_phase must be a string",
            ):
                ingest_external_progress(event)

        self.assertEqual(observer.events, [])

    def test_unknown_context_field_remains_fail_closed(self) -> None:
        observer = RecordingObserver()
        event = _staged_authentication_event()
        event["context"] = {
            "phase": "PRIMARY",
            "root_phase": "PRIMARY",
            "unregistered_context": "must-not-pass",
        }

        with activate_progress(observer):
            with self.assertRaisesRegex(
                ValueError,
                "unknown progress context fields: 'unregistered_context'",
            ):
                ingest_external_progress(event)

        self.assertEqual(observer.events, [])

    def test_reserved_staged_event_reaches_status_sidecar_without_loss(
        self,
    ) -> None:
        event = _staged_authentication_event()
        line = JULIA_PROGRESS_PREFIX + json.dumps(event)

        with TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint.json"
            reporter = CampaignProgressReporter(
                "quiet",
                checkpoint,
                io.StringIO(),
            )
            with activate_progress(reporter), progress_scope(
                leaf_id="leaf-13",
                precision_digits=80,
                mechanism_id="horizon-admittance",
            ):
                self.assertTrue(_forward_julia_progress_line(line))

            status = json.loads(
                Path(f"{checkpoint}.status.json").read_text(encoding="utf-8")
            )

        self.assertEqual(reporter.diagnostics, [])
        self.assertEqual(status["context"]["phase"], "PRIMARY")
        self.assertEqual(status["context"]["root_phase"], "PRIMARY")
        expected_payload = event["payload"]
        for name in (
            "authentication_mode",
            "authoritative",
            "determinant_count_phase",
            "residual_upper_bound_abs",
            "derivative_lower_bound_abs",
            "required_derivative_lower_bound_abs",
            "correction_upper_bound",
            "root_correction_tolerance",
        ):
            self.assertEqual(status["payload"][name], expected_payload[name])

        live = status["live_execution"]
        self.assertEqual(live["phase"], "PRIMARY")
        self.assertEqual(live["root_phase"], "PRIMARY")
        self.assertEqual(
            live["authentication_mode"],
            "STAGED_FULL_AUTHENTICATION",
        )
        self.assertIs(live["authoritative"], True)
        self.assertEqual(live["phase_determinant_count"], 8)
        self.assertEqual(live["phase_residual_upper_bound_abs"], "2.8e-14")
        self.assertEqual(live["phase_derivative_lower_bound_abs"], "2")
        self.assertEqual(
            live["phase_required_derivative_lower_bound_abs"],
            "1.4e-3",
        )
        self.assertEqual(live["phase_correction_upper_bound"], "1.4e-14")
        self.assertEqual(live["phase_root_correction_tolerance"], "2e-11")


if __name__ == "__main__":
    unittest.main()
