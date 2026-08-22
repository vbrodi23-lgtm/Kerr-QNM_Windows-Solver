from __future__ import annotations

import copy
import unittest

from windows_solver.campaign_policy import (
    CAMPAIGN_EVIDENCE_SCHEMA,
    CampaignEvidenceRecord,
    CampaignExecutionPolicy,
    EvidenceLevel,
    EvidenceReceipt,
    ExecutionProfile,
    stronger_evidence_level,
)


_SHA_A = "a" * 64
_SHA_B = "b" * 64
_SHA_C = "c" * 64


class CampaignExecutionPolicyTests(unittest.TestCase):
    def test_profile_values_are_stable_wire_values(self):
        self.assertEqual(
            [item.value for item in ExecutionProfile],
            ["survey", "certify", "validate"],
        )
        self.assertEqual(
            [item.value for item in EvidenceLevel],
            ["SCREENED", "CERTIFIED", "VALIDATED"],
        )

    def test_survey_forbids_every_routine_heavy_operation(self):
        policy = CampaignExecutionPolicy.for_profile(ExecutionProfile.SURVEY)

        self.assertTrue(policy.binary64_first)
        self.assertTrue(policy.stop_at_bounded_response)
        self.assertTrue(policy.continue_after_leaf_failure)
        self.assertFalse(policy.allow_truncation_root_solve)
        self.assertFalse(policy.allow_resolution_root_solve)
        self.assertFalse(policy.allow_seed_path_root_solve)
        self.assertFalse(policy.allow_expanded_derivative_ladder)
        self.assertFalse(policy.allow_full_complex_root_ladder)
        self.assertFalse(policy.allow_independent_validation)
        self.assertFalse(policy.allow_automatic_max_precision)

    def test_certification_retains_heavy_local_uncertainty_without_validation(self):
        policy = CampaignExecutionPolicy.for_profile(ExecutionProfile.CERTIFY)

        self.assertTrue(policy.allow_truncation_root_solve)
        self.assertTrue(policy.allow_resolution_root_solve)
        self.assertTrue(policy.allow_seed_path_root_solve)
        self.assertTrue(policy.allow_expanded_derivative_ladder)
        self.assertFalse(policy.allow_full_complex_root_ladder)
        self.assertFalse(policy.allow_independent_validation)

    def test_validation_owns_independent_and_full_ladder_work(self):
        policy = CampaignExecutionPolicy.for_profile(ExecutionProfile.VALIDATE)

        self.assertTrue(policy.allow_expanded_derivative_ladder)
        self.assertTrue(policy.allow_full_complex_root_ladder)
        self.assertTrue(policy.allow_independent_validation)

    def test_policy_rejects_untyped_profile(self):
        with self.assertRaisesRegex(ValueError, "execution profile"):
            CampaignExecutionPolicy.for_profile("survey")  # type: ignore[arg-type]


class CampaignEvidenceRecordTests(unittest.TestCase):
    def _screened(self) -> CampaignEvidenceRecord:
        return CampaignEvidenceRecord.create(
            leaf_id="leaf-1",
            central_stage_sha256=_SHA_A,
            receipt=EvidenceReceipt(
                execution_profile=ExecutionProfile.SURVEY,
                evidence_level=EvidenceLevel.SCREENED,
                receipt_sha256=_SHA_B,
            ),
        )

    def test_evidence_order_never_downgrades(self):
        self.assertIs(
            stronger_evidence_level(
                EvidenceLevel.VALIDATED, EvidenceLevel.SCREENED
            ),
            EvidenceLevel.VALIDATED,
        )
        self.assertIs(
            stronger_evidence_level(
                EvidenceLevel.SCREENED, EvidenceLevel.CERTIFIED
            ),
            EvidenceLevel.CERTIFIED,
        )

    def test_upgrade_is_additive_and_retains_the_survey_centre(self):
        screened = self._screened()
        certified = screened.with_receipt(EvidenceReceipt(
            execution_profile=ExecutionProfile.CERTIFY,
            evidence_level=EvidenceLevel.CERTIFIED,
            receipt_sha256=_SHA_C,
        ))

        self.assertEqual(certified.evidence_level, EvidenceLevel.CERTIFIED)
        self.assertEqual(certified.execution_profile, ExecutionProfile.CERTIFY)
        self.assertEqual(certified.central_stage_sha256, _SHA_A)
        self.assertEqual(len(certified.receipts), 2)
        self.assertEqual(certified.receipts[0], screened.receipts[0])

    def test_weaker_receipt_is_retained_without_downgrading(self):
        validated = self._screened().with_receipt(EvidenceReceipt(
            execution_profile=ExecutionProfile.VALIDATE,
            evidence_level=EvidenceLevel.VALIDATED,
            receipt_sha256=_SHA_C,
        ))
        repeated_survey = validated.with_receipt(EvidenceReceipt(
            execution_profile=ExecutionProfile.SURVEY,
            evidence_level=EvidenceLevel.SCREENED,
            receipt_sha256="d" * 64,
        ))

        self.assertEqual(repeated_survey.evidence_level, EvidenceLevel.VALIDATED)
        self.assertEqual(len(repeated_survey.receipts), 3)

    def test_duplicate_receipt_is_idempotent(self):
        screened = self._screened()
        self.assertIs(screened.with_receipt(screened.receipts[0]), screened)

    def test_canonical_mapping_round_trip(self):
        evidence = self._screened().with_discrepancy(
            "CENTRAL_RESPONSE_DISCREPANCY_REVIEW_REQUIRED"
        )
        mapping = evidence.to_mapping()
        restored = CampaignEvidenceRecord.from_mapping(mapping)

        self.assertEqual(restored, evidence)
        self.assertEqual(mapping["schema"], CAMPAIGN_EVIDENCE_SCHEMA)
        self.assertEqual(mapping["evidence_level"], "SCREENED")
        self.assertEqual(mapping["execution_profile"], "survey")

    def test_mapping_rejects_forged_summary_level(self):
        mapping = self._screened().to_mapping()
        forged = copy.deepcopy(mapping)
        forged["evidence_level"] = "VALIDATED"

        with self.assertRaisesRegex(ValueError, "evidence level"):
            CampaignEvidenceRecord.from_mapping(forged)

    def test_mapping_rejects_a_changed_central_stage(self):
        mapping = self._screened().to_mapping()
        forged = copy.deepcopy(mapping)
        forged["central_stage_sha256"] = _SHA_C

        with self.assertRaisesRegex(ValueError, "digest"):
            CampaignEvidenceRecord.from_mapping(forged)


if __name__ == "__main__":
    unittest.main()
