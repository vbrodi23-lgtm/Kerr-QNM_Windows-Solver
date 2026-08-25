from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from windows_solver.structural_diagnostics import (
    DIAGNOSTIC_EVENT_SCHEMA,
    StructuralDiagnosticSession,
    read_structural_events,
)
from windows_solver.contracts import canonical_json_bytes


class StructuralDiagnosticSessionTests(unittest.TestCase):
    def test_hash_chain_authenticates_each_structural_boundary(self) -> None:
        """Catches accepting a rewritten or detached structural event."""

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "m02-campaign-checkpoint.json"
            session = StructuralDiagnosticSession.open(
                checkpoint_path=checkpoint,
                session_id="test-session",
                campaign_id="campaign-1",
                selection_id="selection-1",
            )
            first = session.append(
                "LEAF_ENTERED",
                leaf={"index": 1, "count": 3, "leaf_id": "leaf-1"},
            )
            second = session.append(
                "LEAF_DISPOSITION_COMMITTED",
                transition={
                    "prior_state": "PENDING",
                    "next_state": "COMPLETED",
                    "reason_code": "BOUNDED_RESPONSE",
                },
                durable=True,
            )
            session.close_completed()

            events = read_structural_events(session.paths.structural_events)
            latest = json.loads(session.paths.latest.read_text(encoding="utf-8"))

        self.assertEqual(DIAGNOSTIC_EVENT_SCHEMA, events[0]["schema"])
        self.assertEqual(first.event_sha256, events[0]["event_sha256"])
        self.assertEqual(first.event_sha256, second.previous_event_sha256)
        self.assertEqual(second.event_sha256, events[1]["event_sha256"])
        self.assertEqual("COMPLETED", latest["terminal_state"])
        self.assertEqual(str(session.paths.directory), latest["session_directory"])

    def test_reader_rejects_a_tampered_event_payload(self) -> None:
        """Catches treating a changed JSONL event as a trustworthy diagnostic trace."""

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "m02-campaign-checkpoint.json"
            session = StructuralDiagnosticSession.open(
                checkpoint_path=checkpoint,
                session_id="test-session",
                campaign_id="campaign-1",
                selection_id="selection-1",
            )
            session.append("LEAF_ENTERED", leaf={"leaf_id": "leaf-1"})
            path = session.paths.structural_events
            event = json.loads(path.read_text(encoding="utf-8"))
            event["event_kind"] = "LEAF_EXITED"
            path.write_text(json.dumps(event) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "authentication"):
                read_structural_events(path)
            session.close_failed()

    def test_reader_rejects_an_event_missing_required_structural_context(self) -> None:
        """Catches silently replacing a deleted connection field with a default."""

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "m02-campaign-checkpoint.json"
            session = StructuralDiagnosticSession.open(
                checkpoint_path=checkpoint,
                session_id="missing-context-session",
                campaign_id="campaign-1",
                selection_id="selection-1",
            )
            session.append("LEAF_ENTERED", leaf={"leaf_id": "leaf-1"})
            path = session.paths.structural_events
            event = json.loads(path.read_text(encoding="utf-8"))
            del event["connections"]["root_seal_sha256"]
            content = {key: value for key, value in event.items() if key != "event_sha256"}
            event["event_sha256"] = hashlib.sha256(
                canonical_json_bytes(content)
            ).hexdigest()
            path.write_text(json.dumps(event) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "connections schema"):
                read_structural_events(path)
            session.close_failed()

    def test_session_never_reuses_an_existing_diagnostic_directory(self) -> None:
        """Catches overwriting a previous failure's structural evidence."""

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "m02-campaign-checkpoint.json"
            first = StructuralDiagnosticSession.open(
                checkpoint_path=checkpoint,
                session_id="existing-session",
                campaign_id="campaign-1",
                selection_id="selection-1",
            )

            with self.assertRaisesRegex(ValueError, "already exists"):
                StructuralDiagnosticSession.open(
                    checkpoint_path=checkpoint,
                    session_id="existing-session",
                    campaign_id="campaign-1",
                    selection_id="selection-1",
                )
            first.close_completed()


if __name__ == "__main__":
    unittest.main()
