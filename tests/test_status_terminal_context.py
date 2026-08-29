from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
import unittest

from windows_solver.campaign_policy import empty_schema11_checkpoint
from windows_solver.contracts import canonical_json_bytes
from windows_solver.progress import (
    ProgressEventKind,
    activate_progress,
    emit_progress,
    progress_scope,
)
from windows_solver.progress_output import Schema11ProgressReporter


class Schema11TerminalStatusTests(unittest.TestCase):
    def test_status_retains_terminal_context_after_reporter_close(self) -> None:
        """Catches close() erasing the only useful restart/postmortem context."""

        checkpoint = empty_schema11_checkpoint("campaign", "selection")
        metadata = {
            "leaf-1": {"leaf_ordinal": 1, "leaf_count": 2},
            "leaf-2": {"leaf_ordinal": 2, "leaf_count": 2},
        }
        diagnostic_paths = {
            "diagnostic_session_directory": "/diagnostics/session-1",
            "postmortem_path": "/diagnostics/session-1/postmortem.json",
            "bundle_path": "/diagnostics/session-1/diagnostic-bundle.zip",
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "checkpoint.json"
            path.write_bytes(canonical_json_bytes(checkpoint))
            reporter = Schema11ProgressReporter(
                path,
                stream=io.StringIO(),
                mode="quiet",
                profile="survey",
                pass_name="binary64",
                leaf_metadata=metadata,
                diagnostic_paths=diagnostic_paths,
            )

            def publish(kind: ProgressEventKind, **context: object) -> None:
                payload = context.pop("payload", {})
                self.assertIsInstance(payload, dict)
                with activate_progress(reporter), progress_scope(**context):
                    emit_progress(kind, **payload)

            publish(
                ProgressEventKind.LEAF_PASS_STARTED,
                leaf_id="leaf-1",
                leaf_index=1,
                leaf_count=2,
                execution_profile="SURVEY",
                survey_pass="binary64",
            )
            publish(
                ProgressEventKind.LEAF_PASS_DISPOSITION_RECORDED,
                leaf_id="leaf-1",
                leaf_index=1,
                leaf_count=2,
                execution_profile="SURVEY",
                survey_pass="binary64",
            )
            publish(
                ProgressEventKind.LEAF_PASS_STARTED,
                leaf_id="leaf-2",
                leaf_index=2,
                leaf_count=2,
                execution_profile="SURVEY",
                survey_pass="binary64",
            )
            publish(
                ProgressEventKind.CAMPAIGN_PASS_INTERRUPTED,
                execution_profile="SURVEY",
                survey_pass="binary64",
                payload={"reason": "injected interruption"},
            )
            reporter.close()
            status = json.loads(
                Path(f"{path}.status.json").read_text(encoding="utf-8")
            )

        self.assertEqual("windows-solver.schema11-progress-status/3", status["schema"])
        self.assertIsNone(status["current_live_event"])
        self.assertEqual(
            status["last_nonterminal_event"]["context"]["leaf_id"], "leaf-2"
        )
        self.assertEqual(
            status["terminal_event"]["kind"], "campaign_pass_interrupted"
        )
        self.assertEqual(
            status["active_leaf_at_terminal_event"]["context"]["leaf_id"],
            "leaf-2",
        )
        self.assertEqual(
            status["last_committed_leaf"]["context"]["leaf_id"], "leaf-1"
        )
        self.assertEqual(status["next_intended_leaf"]["leaf_id"], "leaf-2")
        self.assertEqual(
            status["terminal_failure"]["reason"], "injected interruption"
        )
        self.assertEqual(status["diagnostic_session_directory"], diagnostic_paths[
            "diagnostic_session_directory"
        ])
        self.assertEqual(status["postmortem_path"], diagnostic_paths["postmortem_path"])
        self.assertEqual(status["bundle_path"], diagnostic_paths["bundle_path"])


if __name__ == "__main__":
    unittest.main()
