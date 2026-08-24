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


def _row(
    leaf_id: str,
    ordinal: int,
    *,
    reconstructed: bool = False,
    leaf_count: int = 50,
    spin: object = 0.9999,
    mechanism: str = "horizon-admittance",
    mode: str = "220",
):
    return {
        "leaf_id": leaf_id,
        "leaf_ordinal": ordinal,
        "leaf_count": leaf_count,
        "mode": mode,
        "spin_or_Mkappa": spin,
        "mechanism": mechanism,
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
    def test_full_layout_prints_ordinal_and_short_mechanism_once(self):
        stream = io.StringIO()
        rows = tuple(_row(f"leaf-{index}", index) for index in range(1, 43))
        dashboard = CleanTailDashboard(stream, width=140, ansi=False)

        dashboard.start(
            rows,
            counts={"completed": 42, "queued": 3, "system_failures": 0},
            profile="survey",
            pass_name="binary64",
            report_status={"basic": "COMPLETED", "advanced": "FAILED"},
        )
        # Duplicate start() must be idempotent.
        dashboard.start(
            rows,
            counts={"completed": 42, "queued": 3, "system_failures": 0},
            profile="survey",
            pass_name="binary64",
            report_status={"basic": "COMPLETED", "advanced": "FAILED"},
        )

        output = stream.getvalue()
        self.assertIn("=" * 108, output)
        self.assertIn("  M02 | DASHBOARD", output)
        self.assertIn("SURVEY / BINARY64", output)
        self.assertIn("REPORTS   basic=COMPLETED   advanced=FAILED", output)
        self.assertIn("DONE 42", output)
        self.assertIn("QUEUED 3", output)
        # Human ordinal rather than a truncated SHA appears in each row.
        row_ordinals = {
            line.split("/", 1)[0]
            for line in output.splitlines()
            if line and line[0].isdigit()
        }
        for index in range(1, 43):
            self.assertIn(str(index), row_ordinals)
        # No mutilated mechanism name.
        self.assertNotIn("horizon-~", output)
        self.assertNotIn("PRODUC~", output)
        self.assertIn("horizon", output)
        # The SHA-form leaf id is not shown to the operator.
        for index in range(1, 43):
            self.assertNotIn(f"leaf-{index} ", output)
        self.assertNotIn("\x1b[", output)

    def test_new_completion_appends_once_around_one_live_line(self):
        stream = io.StringIO()
        dashboard = CleanTailDashboard(stream, width=140, ansi=False)
        dashboard.start(
            (), counts={"completed": 0, "queued": 0}, pass_name="binary64"
        )
        for sample in range(100):
            dashboard.live(
                {
                    "elapsed": f"{sample}s",
                    "leaf": "1/2",
                    "profile": "survey",
                    "pass": "binary64",
                    "phase": "sample",
                }
            )
        dashboard.complete(_row("leaf-1", 1, leaf_count=2))
        dashboard.complete(_row("leaf-1", 1, leaf_count=2))

        output = stream.getvalue()
        row_starts = [
            line for line in output.splitlines() if line and line[0].isdigit()
        ]
        self.assertEqual(1, len(row_starts))
        self.assertTrue(row_starts[0].startswith("1/2"))
        self.assertNotIn("\x1b[0J", output)
        self.assertNotIn("\x1b[2J", output)
        self.assertNotIn("\x1b[", output)

    def test_spin_precision_is_never_truncated(self):
        stream = io.StringIO()
        dashboard = CleanTailDashboard(stream, width=140, ansi=False)
        # A representative range of Kerr spins the operator must be able to
        # tell apart at a glance.
        spins = (0.95, 0.99, 0.999, 0.9999, 0.99999, 0.999998)
        rows = tuple(
            _row(f"leaf-{index}", index, leaf_count=len(spins), spin=spin)
            for index, spin in enumerate(spins, start=1)
        )
        dashboard.start(rows, counts={"completed": len(spins)})

        output = stream.getvalue()
        for spin in spins:
            self.assertIn(format(spin, ".8g"), output)
        # None of the disallowed truncations from the old dashboard.
        self.assertNotIn("0.99~", output)

    def test_live_line_rejects_dict_values_and_uses_hierarchy(self):
        stream = io.StringIO()
        dashboard = CleanTailDashboard(stream, width=140, ansi=False)
        dashboard.start((), counts={"completed": 0}, pass_name="binary64")
        dashboard.live(
            {
                "leaf": "75/212",
                "mode": {"primary": "220"},  # must not be dumped verbatim
                "spin": 0.999,
                "mechanism": "horizon-admittance",
                "tier": "binary64",
                "role": "PRIMARY",
                "phase": "sample",
                "elapsed": "826.1s",
            }
        )
        live_tail = stream.getvalue().rsplit("\r", 1)[-1]
        self.assertIn("RUNNING", live_tail)
        self.assertIn("75/212", live_tail)
        self.assertIn("a=0.999", live_tail)
        self.assertIn("horizon", live_tail)
        self.assertIn("PRIMARY", live_tail)
        self.assertIn("826.1s", live_tail)
        self.assertNotIn("{'", live_tail)

    def test_compact_layout_keeps_all_rows_and_clips_live_text(self):
        stream = io.StringIO()
        rows = tuple(_row(f"leaf-{index}", index, leaf_count=7) for index in range(1, 8))
        dashboard = CleanTailDashboard(stream, width=80, ansi=False)
        dashboard.start(rows, counts={"completed": 7}, pass_name="binary64")
        dashboard.live({"leaf": "7/7", "phase": "x" * 200})

        output = stream.getvalue()
        # Each completed leaf appears as a row line starting with its ordinal.
        row_starts = [
            line for line in output.splitlines() if line and line[0].isdigit()
        ]
        row_ordinals = {line.split("/", 1)[0] for line in row_starts}
        for index in range(1, 8):
            self.assertIn(str(index), row_ordinals)
        self.assertTrue(all(len(line) <= 80 for line in output.splitlines()))
        self.assertLessEqual(len(output.rsplit("\r", 1)[-1]), 80)

    def test_reconstructed_timing_is_marked_without_changing_row_identity(self):
        stream = io.StringIO()
        dashboard = CleanTailDashboard(stream, width=140, ansi=False)
        dashboard.start(
            (_row("leaf-1", 1, reconstructed=True, leaf_count=1),),
            counts={"completed": 1},
        )
        self.assertIn("~1.25s", stream.getvalue())

    def test_promoted_pass_switches_to_promoted_columns(self):
        stream = io.StringIO()
        row = _row("leaf-1", 1, leaf_count=1)
        row.update({"survey_pass": "promoted", "bf80_seconds": 42.0})
        dashboard = CleanTailDashboard(stream, width=140, ansi=False)
        dashboard.start(
            (row,),
            counts={"completed": 1},
            pass_name="promoted",
        )
        output = stream.getvalue()
        self.assertIn("BF40", output)
        self.assertIn("BF80", output)
        self.assertIn("42.00s", output)
        # binary64-only TIME column is not the header for a promoted pass.
        header_line = next(
            line for line in output.splitlines() if "MECHANISM" in line
        )
        self.assertNotIn(" TIME ", header_line)

    def test_summary_line_never_truncates_profile_or_pass(self):
        stream = io.StringIO()
        dashboard = CleanTailDashboard(stream, width=140, ansi=False)
        counts = {
            "completed": 14,
            "queued": 59,
            "deferred": 0,
            "unresolved": 1,
            "rejected": 0,
            "system_failures": 0,
            "CERTIFIED": 0,
            "SCREENED": 14,
            "VALIDATED": 0,
        }
        dashboard.start(
            (),
            counts=counts,
            profile="survey",
            pass_name="binary64",
            report_status={
                "basic": "COMPLETED",
                "projective": "NOT_CONFIGURED",
                "triage": "NOT_CONFIGURED",
            },
        )
        output = stream.getvalue()
        # Every field the old dashboard truncated is present in full.
        self.assertIn("PROFILE=survey", output.replace("SURVEY", "PROFILE=survey"))
        self.assertIn("SURVEY / BINARY64", output)
        self.assertIn("DONE 14", output)
        self.assertIn("QUEUED 59", output)
        self.assertIn("UNRESOLVED 1", output)
        self.assertIn("SCREENED 14", output)
        # No clipped headline.
        self.assertNotIn("su…", output)
        self.assertNotIn("PROFILE=su", output)

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
        self.assertEqual("windows-solver.schema11-progress-status/2", status["schema"])
        self.assertEqual("binary64", status["survey_pass"])

if __name__ == "__main__":
    unittest.main()
