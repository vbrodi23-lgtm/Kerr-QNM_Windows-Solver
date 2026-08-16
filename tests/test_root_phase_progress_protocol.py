from __future__ import annotations

import unittest

from windows_solver.progress import (
    PROGRESS_SCHEMA,
    ProgressEventKind,
    activate_progress,
    ingest_external_progress,
    progress_scope,
)


class RecordingObserver:
    def __init__(self) -> None:
        self.events = []

    def publish(self, event) -> None:
        self.events.append(event)


class RootPhaseProgressProtocolTests(unittest.TestCase):
    def test_external_staged_root_phase_context_is_accepted(self) -> None:
        observer = RecordingObserver()
        event = {
            "schema": PROGRESS_SCHEMA,
            "kind": ProgressEventKind.ROOT_PHASE_STARTED.value,
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
                "determinant_count_phase": 0,
                "root_correction_tolerance": "2e-11",
            },
        }

        with activate_progress(observer), progress_scope(
            leaf_id="leaf-13",
            precision_digits=80,
            mechanism_id="horizon-admittance",
        ):
            ingest_external_progress(event)

        self.assertEqual(len(observer.events), 1)
        forwarded = observer.events[0]
        self.assertEqual(forwarded.context.leaf_id, "leaf-13")
        self.assertEqual(forwarded.context.phase, "PRIMARY")
        self.assertEqual(forwarded.context.root_phase, "PRIMARY")
        self.assertEqual(
            forwarded.payload["authentication_mode"],
            "STAGED_FULL_AUTHENTICATION",
        )

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


if __name__ == "__main__":
    unittest.main()
