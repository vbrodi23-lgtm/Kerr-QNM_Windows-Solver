from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from windows_solver.campaign_postmortem import (
    ARTIFACT_MANIFEST_SCHEMA,
    POSTMORTEM_SCHEMA,
    CampaignPostmortemBuilder,
)
from windows_solver.structural_diagnostics import StructuralDiagnosticSession


class CampaignPostmortemTests(unittest.TestCase):
    def test_postmortem_preserves_exception_chain_and_required_artifact_state(self) -> None:
        """Catches a diagnostic artifact that loses the original failure context."""

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "m02-campaign-checkpoint.json"
            checkpoint.write_text('{"checkpoint":"preserved"}', encoding="utf-8")
            session = StructuralDiagnosticSession.open(
                checkpoint_path=checkpoint,
                session_id="postmortem-session",
                campaign_id="campaign-1",
                selection_id="selection-1",
            )
            builder = CampaignPostmortemBuilder(session)
            try:
                try:
                    raise ValueError("root cause")
                except ValueError as cause:
                    raise RuntimeError("outer failure") from cause
            except RuntimeError as error:
                builder.capture_exception(
                    error,
                    failure_code="UNEXPECTED_SOFTWARE_ERROR",
                    failure_class="SYSTEM_FAILURE",
                    disposition="SYSTEM_FAILURE",
                    fingerprint_sha256="a" * 64,
                )
            builder.capture_checkpoint({
                "path": str(checkpoint),
                "pre_failure_sha256": "b" * 64,
                "post_failure_sha256": "b" * 64,
                "valid": True,
            })
            builder.capture_scheduler({
                "last_committed_leaf": "leaf-1",
                "active_leaf_at_failure": "leaf-2",
                "next_intended_leaf": "leaf-3",
                "next_leaf_started": False,
            })
            builder.capture_provider_summaries({"root_provider": {"count": 1}})

            postmortem_path = builder.write_atomic("SYSTEM_FAILURE")
            manifest_path = builder.write_manifest_atomic(
                required_artifacts={"checkpoint": checkpoint},
                optional_artifacts={"timing_log": checkpoint.with_suffix(".timing.jsonl")},
            )
            postmortem = json.loads(postmortem_path.read_text(encoding="utf-8"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            session.close_failed()

        self.assertEqual(POSTMORTEM_SCHEMA, postmortem["schema"])
        self.assertEqual("RuntimeError", postmortem["primary_failure"]["exception_type"])
        self.assertEqual(
            ["RuntimeError", "ValueError"],
            [item["exception_type"] for item in postmortem["primary_failure"]["chain"]],
        )
        self.assertEqual("leaf-2", postmortem["movement"]["active_leaf_at_failure"])
        self.assertEqual(ARTIFACT_MANIFEST_SCHEMA, manifest["schema"])
        self.assertTrue(manifest["artifacts"]["checkpoint"]["exists"])
        self.assertFalse(manifest["artifacts"]["timing_log"]["exists"])
        self.assertFalse(manifest["artifacts"]["timing_log"]["required"])


if __name__ == "__main__":
    unittest.main()
