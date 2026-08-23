from __future__ import annotations

import io
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from windows_solver.campaign_policy import (
    EvidenceLevel,
    SurveyDisposition,
    SurveyPass,
    add_numerical_record,
    empty_schema11_checkpoint,
    record_evidence,
    record_survey_disposition,
)
from windows_solver.contracts import canonical_json_bytes
from windows_solver.progress_output import (
    CleanTailDashboard,
    Schema11ProgressReporter,
    schema11_dashboard_snapshot,
)


def _row(leaf_id: str, ordinal: int, *, reconstructed: bool = False):
    return {
        "leaf_id": leaf_id,
        "leaf_ordinal": ordinal,
        "mode": "220",
        "spin_or_Mkappa": "0.9999",
        "mechanism": "horizon-admittance",
        "survey_pass": "binary64",
        "evidence_level": "SCREENED",
        "precision_tier": "binary64",
        "binary64_seconds": 1.25,
        "bf40_seconds": 0.0,
        "bf80_seconds": 0.0,
        "bf120_seconds": 0.0,
        "total_leaf_seconds": 1.25,
        "response_magnitude": 2.5,
        "relative_disk_radius": 3.0e-8,
        "terminal_state": "PRODUCED",
        "reconstructed_timing": reconstructed,
    }


class CleanTailDashboardTests(unittest.TestCase):
    def test_full_layout_prints_every_historical_completion_once(self):
        stream = io.StringIO()
        rows = tuple(_row(f"leaf-{index}", index) for index in range(1, 43))
        dashboard = CleanTailDashboard(stream, width=140, ansi=False)

        dashboard.start(
            rows,
            counts={"total": 50, "completed": 42, "queued": 3, "failed": 0},
            profile="survey",
            pass_name="binary64",
            report_status={"basic": "COMPLETED", "advanced": "FAILED"},
        )
        dashboard.start(
            rows,
            counts={"total": 50, "completed": 42, "queued": 3, "failed": 0},
            profile="survey",
            pass_name="binary64",
            report_status={"basic": "COMPLETED", "advanced": "FAILED"},
        )

        output = stream.getvalue()
        self.assertIn("=" * 108, output)
        self.assertIn("  M02 | DASHBOARD", output)
        self.assertIn("REPORTS basic=COMPLETED advanced=FAILED", output)
        for index in range(1, 43):
            self.assertEqual(output.count(f"leaf-{index} "), 1)
        self.assertNotIn("\x1b[", output)

    def test_new_completion_appends_once_around_one_live_line(self):
        stream = io.StringIO()
        dashboard = CleanTailDashboard(stream, width=140, ansi=False)
        dashboard.start((), counts={"total": 2, "completed": 0})
        for sample in range(100):
            dashboard.live(
                {
                    "elapsed": f"{sample}s",
                    "leaf": "1/2",
                    "profile": "survey",
                    "pass": "binary64",
                    "phase": "sample",
                    "sample": f"{sample}/100",
                }
            )
        dashboard.complete(_row("leaf-1", 1))
        dashboard.complete(_row("leaf-1", 1))

        output = stream.getvalue()
        self.assertEqual(output.count("leaf-1 "), 1)
        self.assertEqual(output.count("\n"), 6)
        self.assertNotIn("\x1b[0J", output)
        self.assertNotIn("\x1b[2J", output)
        self.assertNotIn("\x1b[", output)

    def test_compact_layout_keeps_all_rows_and_clips_live_text(self):
        stream = io.StringIO()
        rows = tuple(_row(f"leaf-{index}", index) for index in range(1, 8))
        dashboard = CleanTailDashboard(stream, width=80, ansi=False)
        dashboard.start(rows, counts={"total": 7, "completed": 7})
        dashboard.live({"leaf": "7/7", "suboperation": "x" * 200})

        output = stream.getvalue()
        for index in range(1, 8):
            self.assertEqual(output.count(f"leaf-{index} "), 1)
        self.assertTrue(all(len(line) <= 80 for line in output.splitlines()))
        self.assertLessEqual(len(output.rsplit("\r", 1)[-1]), 80)

    def test_reconstructed_timing_is_marked_without_changing_row_identity(self):
        stream = io.StringIO()
        dashboard = CleanTailDashboard(stream, width=140, ansi=False)
        dashboard.start((_row("leaf-1", 1, reconstructed=True),), counts={})
        self.assertIn("~1.25", stream.getvalue())

    def test_counts_come_from_schema11_when_advanced_reports_fail(self):
        content = {
            "leaf_id": "leaf-1",
            "state": "PRODUCED",
            "stages": [{"stage_sha256": "a" * 64, "digits": 64}],
        }
        record = {
            **content,
            "record_sha256": hashlib.sha256(
                canonical_json_bytes(content)
            ).hexdigest(),
        }
        checkpoint = add_numerical_record(
            empty_schema11_checkpoint("campaign", "selection"), record
        )
        checkpoint = record_evidence(
            checkpoint,
            leaf_id="leaf-1",
            central_record_sha256=record["record_sha256"],
            central_stage_sha256="a" * 64,
            evidence_level=EvidenceLevel.SCREENED,
        )
        checkpoint = record_survey_disposition(
            checkpoint,
            survey_pass=SurveyPass.BINARY64,
            leaf_id="leaf-1",
            disposition=SurveyDisposition.COMPLETED,
            result_record_sha256=record["record_sha256"],
            operation_identity="test/v1",
            precision_tiers=("binary64",),
            reason_code="TEST",
            sample_count=0,
            sample_limit=0,
            root_read_count=0,
            root_read_limit=0,
            worker_launch_count=0,
            worker_launch_limit=0,
            tier_timing=(),
            session_fragments=(),
        )
        checkpoint["report_status_receipt"] = {
            "basic": {"status": "COMPLETED"},
            "projective": {"status": "FAILED"},
            "triage": {"status": "NOT_RUN"},
        }

        rows, counts, reports = schema11_dashboard_snapshot(checkpoint)

        self.assertEqual(1, len(rows))
        self.assertEqual(1, counts["completed"])
        self.assertEqual("FAILED", reports["projective"])

    def test_quiet_reporter_writes_status_without_dashboard_output(self):
        checkpoint = empty_schema11_checkpoint("campaign", "selection")
        stream = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "checkpoint.json"
            path.write_bytes(canonical_json_bytes(checkpoint))
            reporter = Schema11ProgressReporter(
                path,
                stream=stream,
                mode="quiet",
                profile="survey",
                pass_name="binary64",
            )
            reporter.close()
            status = json.loads(
                Path(f"{path}.status.json").read_text(encoding="utf-8")
            )

        self.assertEqual("", stream.getvalue())
        self.assertEqual("windows-solver.schema11-progress-status/1", status["schema"])
        self.assertEqual("binary64", status["survey_pass"])


if __name__ == "__main__":
    unittest.main()
