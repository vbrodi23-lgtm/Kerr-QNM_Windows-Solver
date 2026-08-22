from __future__ import annotations

import csv
from pathlib import Path
import tempfile
import unittest

from windows_solver.campaign_policy import (
    CampaignEvidenceRecord,
    EvidenceLevel,
    EvidenceReceipt,
    ExecutionProfile,
)
from windows_solver.campaign_reports import (
    CampaignReportModel,
    LEAF_COLUMNS,
    _atomic_csv,
    _leaf_row,
)
from windows_solver.progress_output import CampaignProgressReporter
from windows_solver.response_batches import (
    CampaignLeafRecord,
    CampaignRunSummary,
    PrecisionCapabilities,
    StageOutcome,
    _campaign_stage_record,
    build_campaign_plan,
    synthetic_stage_signed_error_channels,
)
from windows_solver.response_engine import (
    NumericalPolicy,
    VettedNativeDeterminantKernel,
)
from tests.test_linear_response_batches import _produced_stage_outcome


class CampaignEvidenceReportingTests(unittest.TestCase):
    def test_csv_summary_and_dashboard_separate_all_evidence_levels(self):
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        profiles = (
            (ExecutionProfile.SURVEY, EvidenceLevel.SCREENED, "a" * 64),
            (ExecutionProfile.CERTIFY, EvidenceLevel.CERTIFIED, "b" * 64),
            (ExecutionProfile.VALIDATE, EvidenceLevel.VALIDATED, "c" * 64),
        )
        records = []
        rows = []
        for ordinal, (leaf, (profile, level, digest)) in enumerate(
            zip(plan.leaves[:3], profiles), start=1
        ):
            stage = _campaign_stage_record(
                plan,
                plan.precision_capabilities,
                _produced_stage_outcome(leaf, complex(0.01, -0.02)),
            )
            evidence = CampaignEvidenceRecord.create(
                leaf_id=leaf.leaf_id,
                central_stage_sha256=stage.stage_sha256,
                receipt=EvidenceReceipt(
                    execution_profile=profile,
                    evidence_level=level,
                    receipt_sha256=digest,
                ),
            )
            record = CampaignLeafRecord(
                leaf_id=leaf.leaf_id,
                role=leaf.role,
                state="PRODUCED",
                stages=(stage,),
                evidence=evidence,
            )
            records.append(record)
            rows.append(_leaf_row(
                ordinal,
                leaf,
                record,
                provenance="REUSED",
                source_receipt="sha256:" + "d" * 64,
            ))

        summary = CampaignRunSummary(
            campaign_id=plan.campaign_id,
            selection_id="report-test-selection",
            state="COMPLETE",
            executed_stage_count=0,
            reused_stage_count=3,
            records=tuple(records),
            checkpoint_path="report-test.json",
            execution_profile=ExecutionProfile.SURVEY,
        )
        self.assertEqual(summary.evidence_counts, {
            "SCREENED": 3,
            "CERTIFIED": 2,
            "VALIDATED": 1,
            "UNRESOLVED": 0,
            "REJECTED": 0,
            "FAILED": 0,
        })
        self.assertEqual(
            [row["evidence_level"] for row in rows],
            ["SCREENED", "CERTIFIED", "VALIDATED"],
        )
        self.assertEqual(
            [row["execution_profile"] for row in rows],
            ["survey", "certify", "validate"],
        )

        with tempfile.TemporaryDirectory() as temporary:
            csv_path = Path(temporary) / "m02-leaves.csv"
            _atomic_csv(csv_path, LEAF_COLUMNS, rows)
            with csv_path.open(newline="", encoding="utf-8") as handle:
                header = next(csv.reader(handle))
            reporter = CampaignProgressReporter(
                "normal", Path(temporary) / "checkpoint.json"
            )
            reporter._campaign_report_model = CampaignReportModel(
                leaf_rows=tuple(rows),
                error_channel_rows=(),
                projective_rows=(),
                checkpoint_source_receipt="fixture",
            )
            dashboard = "\n".join(reporter._dashboard_lines({
                "sequence": 1,
                "kind": "campaign_completed",
                "elapsed_seconds": 0.0,
            }))

        self.assertIn("evidence_level", header)
        self.assertIn("execution_profile", header)
        self.assertIn("Atlas screened 3", dashboard)
        self.assertIn("Certified      2", dashboard)
        self.assertIn("Validated      1", dashboard)

    def test_unresolved_survey_csv_row_keeps_its_execution_profile(self):
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        leaf = plan.leaves[0]
        payload = {
            "evidence_kind": "survey-contained-failure/v1",
            "execution_profile": "survey",
            "survey_failure_code": "SYNTHETIC",
        }
        outcome = StageOutcome(
            digits=64,
            numerical_state="FAILED",
            component_result=payload,
            local_disk_radius_abs=0.0,
            signed_error_channels=synthetic_stage_signed_error_channels(
                payload, 0.0, precision_ladder_applicable=False
            ),
        )
        record = CampaignLeafRecord(
            leaf_id=leaf.leaf_id,
            role=leaf.role,
            state="FAILED",
            stages=(_campaign_stage_record(
                plan, plan.precision_capabilities, outcome
            ),),
        )

        row = _leaf_row(
            1,
            leaf,
            record,
            provenance="EXECUTED",
            source_receipt="fixture",
        )

        self.assertEqual(row["execution_profile"], "survey")
        self.assertEqual(row["evidence_level"], "")


if __name__ == "__main__":
    unittest.main()
