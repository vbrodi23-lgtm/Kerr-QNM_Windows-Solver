from __future__ import annotations

import hashlib
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from windows_solver.campaign_policy import (
    CampaignEvidenceRecord,
    EvidenceLevel,
    EvidenceReceipt,
    ExecutionProfile,
)
from windows_solver.campaign_triage import (
    build_campaign_triage,
    triage_leaf_ids_for_profile,
)
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
    ComponentStatus,
    NumericalPolicy,
    VettedNativeDeterminantKernel,
)


class CampaignTriageTests(unittest.TestCase):
    def test_queue_explicitly_ranks_largest_derivative_disagreement(self):
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        records = []
        rows = []
        results = []
        for index, leaf in enumerate(plan.leaves[:2]):
            response = complex(1.0e-3, -2.0e-3)
            payload = {
                "evidence_kind": "synthetic-triage-centre/v1",
                "response": {
                    "real": response.real,
                    "imaginary": response.imag,
                },
            }
            outcome = StageOutcome(
                digits=64,
                numerical_state="CONVERGED",
                component_result=payload,
                local_disk_radius_abs=1.0e-8,
                signed_error_channels=synthetic_stage_signed_error_channels(
                    payload, 1.0e-8, precision_ladder_applicable=False
                ),
            )
            stage = _campaign_stage_record(
                plan, plan.precision_capabilities, outcome
            )
            evidence = CampaignEvidenceRecord.create(
                leaf_id=leaf.leaf_id,
                central_stage_sha256=stage.stage_sha256,
                receipt=EvidenceReceipt(
                    execution_profile=ExecutionProfile.SURVEY,
                    evidence_level=EvidenceLevel.SCREENED,
                    receipt_sha256=hashlib.sha256(
                        leaf.leaf_id.encode()
                    ).hexdigest(),
                ),
            )
            records.append(CampaignLeafRecord(
                leaf_id=leaf.leaf_id,
                role=leaf.role,
                state="PRODUCED",
                stages=(stage,),
                evidence=evidence,
            ))
            rows.append({
                "leaf_id": leaf.leaf_id,
                "response_magnitude": abs(response),
                "local_disk_radius": 1.0e-8,
            })
            results.append(SimpleNamespace(
                status=ComponentStatus.CONVERGED,
                baseline=SimpleNamespace(
                    root_reference_id=leaf.job.root.root_reference_id,
                    branch_id=leaf.job.root.branch_id,
                    numerical_conditioning=None,
                ),
                derivative_evidence={
                    "raw_step_disagreement_abs": (
                        1.0e-3 if index == 0 else 1.0e-9
                    ),
                },
            ))

        summary = CampaignRunSummary(
            campaign_id=plan.campaign_id,
            selection_id="derivative-ranking-selection",
            state="COMPLETE",
            executed_stage_count=0,
            reused_stage_count=2,
            records=tuple(records),
            checkpoint_path="triage-test.json",
            execution_profile=ExecutionProfile.SURVEY,
        )
        with patch(
            "windows_solver.campaign_triage._component_result",
            side_effect=results,
        ):
            report = build_campaign_triage(
                plan,
                summary,
                rows,
                (),
                checkpoint_source_receipt="sha256:" + "a" * 64,
            )

        by_id = {entry.leaf_id: entry for entry in report.entries}
        self.assertIn(
            "LARGEST_DERIVATIVE_DISAGREEMENT",
            by_id[plan.leaves[0].leaf_id].reasons,
        )
        self.assertNotIn(
            "LARGEST_DERIVATIVE_DISAGREEMENT",
            by_id[plan.leaves[1].leaf_id].reasons,
        )

    def test_queue_covers_risks_projective_controllers_and_dynamic_sentinels(self):
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        records = []
        leaf_rows = []
        for index, leaf in enumerate(plan.leaves):
            response = complex(1.0e-3 + index * 1.0e-7, -2.0e-3)
            radius = 1.0e-7
            payload = {
                "evidence_kind": "synthetic-triage-centre/v1",
                "response": {
                    "real": response.real,
                    "imaginary": response.imag,
                },
            }
            outcome = StageOutcome(
                digits=64,
                numerical_state="CONVERGED",
                component_result=payload,
                local_disk_radius_abs=radius,
                signed_error_channels=synthetic_stage_signed_error_channels(
                    payload, radius, precision_ladder_applicable=False
                ),
            )
            stage = _campaign_stage_record(
                plan, plan.precision_capabilities, outcome
            )
            unresolved = index == 0
            evidence = None
            if not unresolved:
                digest = hashlib.sha256(leaf.leaf_id.encode()).hexdigest()
                evidence = CampaignEvidenceRecord.create(
                    leaf_id=leaf.leaf_id,
                    central_stage_sha256=stage.stage_sha256,
                    receipt=EvidenceReceipt(
                        execution_profile=ExecutionProfile.SURVEY,
                        evidence_level=EvidenceLevel.SCREENED,
                        receipt_sha256=digest,
                    ),
                )
            records.append(CampaignLeafRecord(
                leaf_id=leaf.leaf_id,
                role=leaf.role,
                state="UNRESOLVED" if unresolved else "PRODUCED",
                stages=(stage,),
                evidence=evidence,
            ))
            leaf_rows.append({
                "leaf_id": leaf.leaf_id,
                "response_magnitude": abs(response),
                "local_disk_radius": radius,
            })

        summary = CampaignRunSummary(
            campaign_id=plan.campaign_id,
            selection_id="triage-test-selection",
            state="COMPLETE",
            executed_stage_count=0,
            reused_stage_count=len(records),
            records=tuple(records),
            checkpoint_path="triage-test.json",
            execution_profile=ExecutionProfile.SURVEY,
        )
        left, right, tied_left, tied_right = plan.leaves[1:5]
        projective_rows = (
            {
                "row_id": "minimum-angle-row-a",
                "nominal_angle": 0.01,
                "left_component_ids": f'["{left.leaf_id}"]',
                "right_component_ids": f'["{right.leaf_id}"]',
            },
            {
                "row_id": "minimum-angle-row-b",
                "nominal_angle": 0.01,
                "left_component_ids": f'["{tied_left.leaf_id}"]',
                "right_component_ids": f'["{tied_right.leaf_id}"]',
            },
        )

        report = build_campaign_triage(
            plan,
            summary,
            leaf_rows,
            projective_rows,
            checkpoint_source_receipt="sha256:" + "a" * 64,
        )

        self.assertEqual(len(report.entries), len(plan.leaves))
        self.assertEqual(report.entries[0].leaf_id, plan.leaves[0].leaf_id)
        self.assertEqual(report.entries[0].recommended_action, "RESOLVE_SURVEY")
        by_id = {entry.leaf_id: entry for entry in report.entries}
        for leaf in (left, right, tied_left, tied_right):
            self.assertIn(
                "PROJECTIVE_CLASSIFICATION_CONTROLLER",
                by_id[leaf.leaf_id].reasons,
            )
        mechanism_sentinels = {
            entry.mechanism
            for entry in report.entries
            if "MECHANISM_SENTINEL" in entry.reasons
        }
        mode_sentinels = {
            entry.mode
            for entry in report.entries
            if "MODE_FAMILY_SENTINEL" in entry.reasons
        }
        self.assertEqual(
            mechanism_sentinels,
            {leaf.mechanism_id for leaf in plan.leaves},
        )
        self.assertEqual(
            mode_sentinels,
            {leaf.leaf.mode_label for leaf in plan.leaves},
        )
        self.assertIn("recommended_certification_queue", report.to_mapping())
        mixed = triage_leaf_ids_for_profile(
            plan,
            report.to_mapping(),
            ExecutionProfile.CERTIFY,
            checkpoint_source_receipt="sha256:" + "a" * 64,
        )
        low_risk = next(
            entry
            for entry in report.entries
            if entry.terminal_state == "PRODUCED" and not entry.reasons
        )
        self.assertEqual(low_risk.recommended_action, "REVIEW")
        self.assertNotIn(low_risk.leaf_id, mixed)
        self.assertEqual(
            set(mixed),
            {
                entry.leaf_id
                for entry in report.entries
                if entry.recommended_action == "CERTIFY"
            },
        )
        roles = {
            leaf.role for leaf in plan.leaves if leaf.leaf_id in set(mixed)
        }
        self.assertEqual(roles, {"primary", "deep", "control"})
        self.assertEqual(
            triage_leaf_ids_for_profile(
                plan,
                report.to_mapping(),
                ExecutionProfile.CERTIFY,
                checkpoint_source_receipt="sha256:" + "a" * 64,
                limit=3,
            ),
            mixed[:3],
        )

    def test_queue_rejects_a_stale_checkpoint_source_receipt(self):
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        leaf = plan.leaves[0]
        payload = {
            "evidence_kind": "synthetic-triage-centre/v1",
            "response": {"real": 1.0e-3, "imaginary": -2.0e-3},
        }
        outcome = StageOutcome(
            digits=64,
            numerical_state="CONVERGED",
            component_result=payload,
            local_disk_radius_abs=1.0e-8,
            signed_error_channels=synthetic_stage_signed_error_channels(
                payload, 1.0e-8, precision_ladder_applicable=False
            ),
        )
        stage = _campaign_stage_record(
            plan, plan.precision_capabilities, outcome
        )
        record = CampaignLeafRecord(
            leaf_id=leaf.leaf_id,
            role=leaf.role,
            state="PRODUCED",
            stages=(stage,),
            evidence=CampaignEvidenceRecord.create(
                leaf_id=leaf.leaf_id,
                central_stage_sha256=stage.stage_sha256,
                receipt=EvidenceReceipt(
                    execution_profile=ExecutionProfile.SURVEY,
                    evidence_level=EvidenceLevel.SCREENED,
                    receipt_sha256="b" * 64,
                ),
            ),
        )
        summary = CampaignRunSummary(
            campaign_id=plan.campaign_id,
            selection_id="stale-triage-selection",
            state="COMPLETE",
            executed_stage_count=0,
            reused_stage_count=1,
            records=(record,),
            checkpoint_path="triage-test.json",
            execution_profile=ExecutionProfile.SURVEY,
        )
        source_receipt = "sha256:" + "a" * 64
        report = build_campaign_triage(
            plan,
            summary,
            ({
                "leaf_id": leaf.leaf_id,
                "response_magnitude": abs(complex(1.0e-3, -2.0e-3)),
                "local_disk_radius": 1.0e-8,
            },),
            (),
            checkpoint_source_receipt=source_receipt,
        )

        with self.assertRaisesRegex(ValueError, "stale checkpoint"):
            triage_leaf_ids_for_profile(
                plan,
                report.to_mapping(),
                ExecutionProfile.CERTIFY,
                checkpoint_source_receipt="sha256:" + "c" * 64,
            )

    def test_evidence_discrepancy_requires_review_not_more_heavy_work(self):
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        leaf = plan.leaves[0]
        payload = {
            "evidence_kind": "synthetic-triage-centre/v1",
            "response": {"real": 1.0e-3, "imaginary": -2.0e-3},
        }
        outcome = StageOutcome(
            digits=64,
            numerical_state="CONVERGED",
            component_result=payload,
            local_disk_radius_abs=1.0e-8,
            signed_error_channels=synthetic_stage_signed_error_channels(
                payload, 1.0e-8, precision_ladder_applicable=False
            ),
        )
        stage = _campaign_stage_record(
            plan, plan.precision_capabilities, outcome
        )
        evidence = CampaignEvidenceRecord.create(
            leaf_id=leaf.leaf_id,
            central_stage_sha256=stage.stage_sha256,
            receipt=EvidenceReceipt(
                execution_profile=ExecutionProfile.SURVEY,
                evidence_level=EvidenceLevel.SCREENED,
                receipt_sha256="d" * 64,
            ),
        ).with_discrepancy(
            "CERTIFICATION_CENTRE_OUTSIDE_SCREENED_DISK"
        )
        record = CampaignLeafRecord(
            leaf_id=leaf.leaf_id,
            role=leaf.role,
            state="PRODUCED",
            stages=(stage,),
            evidence=evidence,
        )
        summary = CampaignRunSummary(
            campaign_id=plan.campaign_id,
            selection_id="discrepancy-triage-selection",
            state="COMPLETE",
            executed_stage_count=0,
            reused_stage_count=1,
            records=(record,),
            checkpoint_path="triage-test.json",
            execution_profile=ExecutionProfile.SURVEY,
        )
        source_receipt = "sha256:" + "a" * 64
        report = build_campaign_triage(
            plan,
            summary,
            ({
                "leaf_id": leaf.leaf_id,
                "response_magnitude": abs(complex(1.0e-3, -2.0e-3)),
                "local_disk_radius": 1.0e-8,
            },),
            (),
            checkpoint_source_receipt=source_receipt,
        )

        entry = report.entries[0]
        self.assertIn("EVIDENCE_DISCREPANCY", entry.reasons)
        self.assertEqual(entry.recommended_action, "REVIEW")
        with self.assertRaisesRegex(ValueError, "no CERTIFY leaves"):
            triage_leaf_ids_for_profile(
                plan,
                report.to_mapping(),
                ExecutionProfile.CERTIFY,
                checkpoint_source_receipt=source_receipt,
            )


if __name__ == "__main__":
    unittest.main()
