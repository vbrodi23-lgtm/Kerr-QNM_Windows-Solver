from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from windows_solver.campaign_policy import (
    CampaignEvidenceRecord,
    CampaignExecutionPolicy,
    EvidenceLevel,
    EvidenceReceipt,
    ExecutionProfile,
    SurveyEvidenceCache,
)
from windows_solver.response_batches import (
    CampaignLeafRecord,
    PrecisionCapabilities,
    StageOutcome,
    _atomic_json,
    _campaign_stage_record,
    _checkpoint_mapping,
    _survey_evidence_record,
    build_campaign_evidence_queue_selection,
    build_campaign_plan,
    build_campaign_selection,
    run_campaign_selection,
    synthetic_stage_signed_error_channels,
    validate_campaign_checkpoint,
)
from windows_solver.response_engine import (
    FULL_COMPLEX_LADDER_VALIDATION_IDENTITY,
    NumericalPolicy,
    VettedNativeDeterminantKernel,
)
from tests.test_campaign_survey_orchestration import RecordingSurveyBackend


def _plan_and_selection():
    plan = build_campaign_plan(
        policy=NumericalPolicy(),
        backend_identity=VettedNativeDeterminantKernel.identity,
        precision_capabilities=PrecisionCapabilities((64, 80, 120)),
    )
    leaf = next(
        item
        for item in plan.leaves
        if item.role == "primary"
        and item.mechanism_id == "exterior-fixed-r3"
    )
    selection = build_campaign_selection(
        plan, role="primary", leaf_ids=(leaf.leaf_id,)
    )
    return plan, selection


class EvidenceUpgradeBackend:
    identity = VettedNativeDeterminantKernel.identity
    precision_capabilities = PrecisionCapabilities((64, 80, 120))

    def __init__(self, profile: ExecutionProfile, *, centre_shift=0.0j):
        self.profile = profile
        self.centre_shift = centre_shift
        self.calls = []

    def scientific_execution_contract_for(self, leaf):
        return None

    def execute_evidence_stage(self, leaf, retained_record, policy):
        if not isinstance(policy, CampaignExecutionPolicy):
            raise AssertionError("evidence upgrade lacks a typed policy")
        if policy.profile is not self.profile:
            raise AssertionError("evidence upgrade used the wrong profile")
        if self.profile is ExecutionProfile.CERTIFY:
            if policy.allow_full_complex_root_ladder:
                raise AssertionError("certification enabled full root ladders")
            if policy.allow_independent_validation:
                raise AssertionError("certification enabled independent validation")
            digits = 80
        else:
            if not policy.allow_full_complex_root_ladder:
                raise AssertionError("validation disabled full root ladders")
            if not policy.allow_independent_validation:
                raise AssertionError("validation disabled independent routes")
            digits = 120
        central = retained_record.stages[-1].outcome.component_result["response"]
        response = complex(central["real"], central["imaginary"])
        response += self.centre_shift
        result = {
            "synthetic_test_response": {
                "real": response.real,
                "imaginary": response.imag,
            }
        }
        payload = {
            "evidence_kind": (
                "targeted-local-certification/v1"
                if self.profile is ExecutionProfile.CERTIFY
                else "independent-publication-validation/v1"
            ),
            "execution_profile": self.profile.value,
            "leaf_id": leaf.leaf_id,
            "response": {
                "real": response.real,
                "imaginary": response.imag,
            },
            "result": result,
            "heavy_local_stage_chain": (
                [{"digits": digits, "component_result": {"result": result}}]
                if self.profile is ExecutionProfile.CERTIFY
                else []
            ),
            "validation_policy": (
                None
                if self.profile is ExecutionProfile.CERTIFY
                else {
                    "identity": FULL_COMPLEX_LADDER_VALIDATION_IDENTITY,
                    "reason": "PUBLICATION_VALIDATION",
                }
            ),
            "bounded_response_disk": True,
        }
        radius = 1.0e-8
        self.calls.append((leaf.leaf_id, retained_record.record_sha256))
        return StageOutcome(
            digits=digits,
            numerical_state="CONVERGED",
            component_result=payload,
            local_disk_radius_abs=radius,
            signed_error_channels=synthetic_stage_signed_error_channels(
                payload,
                radius,
                precision_ladder_applicable=False,
            ),
        )


class CampaignEvidenceUpgradeTests(unittest.TestCase):
    def _screened_checkpoint(self):
        plan, selection = _plan_and_selection()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        checkpoint = Path(temporary.name) / "checkpoint.json"
        survey = RecordingSurveyBackend()
        screened = run_campaign_selection(
            plan,
            selection,
            survey,
            checkpoint,
            resume=False,
            execution_profile=ExecutionProfile.SURVEY,
        )
        return plan, selection, checkpoint, screened.records[0]

    def test_certify_adds_heavy_local_evidence_around_retained_centre(self):
        plan, selection, checkpoint, screened = self._screened_checkpoint()
        backend = EvidenceUpgradeBackend(ExecutionProfile.CERTIFY)

        summary = run_campaign_selection(
            plan,
            selection,
            backend,
            checkpoint,
            resume=True,
            execution_profile=ExecutionProfile.CERTIFY,
        )

        record = summary.records[0]
        self.assertEqual(record.stages, screened.stages)
        self.assertEqual(record.evidence.evidence_level, EvidenceLevel.CERTIFIED)
        self.assertEqual(len(record.evidence_stages), 1)
        self.assertEqual(len(backend.calls), 1)
        restored = validate_campaign_checkpoint(plan, checkpoint)
        self.assertEqual(
            restored.records[0].evidence.evidence_level,
            EvidenceLevel.CERTIFIED,
        )

    def test_validate_retains_the_independent_full_ladder_path(self):
        plan, selection, checkpoint, _ = self._screened_checkpoint()
        certify = EvidenceUpgradeBackend(ExecutionProfile.CERTIFY)
        run_campaign_selection(
            plan,
            selection,
            certify,
            checkpoint,
            resume=True,
            execution_profile=ExecutionProfile.CERTIFY,
        )
        validate = EvidenceUpgradeBackend(ExecutionProfile.VALIDATE)

        summary = run_campaign_selection(
            plan,
            selection,
            validate,
            checkpoint,
            resume=True,
            execution_profile=ExecutionProfile.VALIDATE,
        )

        record = summary.records[0]
        self.assertEqual(record.evidence.evidence_level, EvidenceLevel.VALIDATED)
        self.assertEqual(len(record.evidence_stages), 2)
        self.assertEqual(len(validate.calls), 1)
        restored = validate_campaign_checkpoint(plan, checkpoint)
        self.assertEqual(
            restored.records[0].evidence.evidence_level,
            EvidenceLevel.VALIDATED,
        )

    def test_material_centre_change_is_a_discrepancy_not_a_replacement(self):
        plan, selection, checkpoint, screened = self._screened_checkpoint()
        backend = EvidenceUpgradeBackend(
            ExecutionProfile.CERTIFY,
            centre_shift=complex(1.0e-3, 0.0),
        )

        summary = run_campaign_selection(
            plan,
            selection,
            backend,
            checkpoint,
            resume=True,
            execution_profile=ExecutionProfile.CERTIFY,
        )

        record = summary.records[0]
        self.assertEqual(record.stages, screened.stages)
        self.assertEqual(record.evidence.evidence_level, EvidenceLevel.SCREENED)
        self.assertIn(
            "CERTIFICATION_CENTRE_OUTSIDE_SCREENED_DISK",
            record.evidence.discrepancy_codes,
        )

    def test_validate_requires_existing_certified_evidence(self):
        plan, selection, checkpoint, _ = self._screened_checkpoint()
        backend = EvidenceUpgradeBackend(ExecutionProfile.VALIDATE)

        with self.assertRaisesRegex(ValueError, "requires CERTIFIED"):
            run_campaign_selection(
                plan,
                selection,
                backend,
                checkpoint,
                resume=True,
                execution_profile=ExecutionProfile.VALIDATE,
            )
        self.assertEqual(backend.calls, [])

    def test_screened_centre_cannot_be_relabelled_without_upgrade_evidence(self):
        plan, selection, checkpoint, screened = self._screened_checkpoint()
        forged = replace(
            screened,
            evidence=CampaignEvidenceRecord.create(
                leaf_id=screened.leaf_id,
                central_stage_sha256=screened.stages[-1].stage_sha256,
                receipt=EvidenceReceipt(
                    execution_profile=ExecutionProfile.CERTIFY,
                    evidence_level=EvidenceLevel.CERTIFIED,
                    receipt_sha256="f" * 64,
                ),
            ),
        )
        _atomic_json(
            checkpoint,
            _checkpoint_mapping(plan, selection, (forged,)),
        )

        with self.assertRaisesRegex(
            ValueError,
            "survey receipt|upgrade receipt",
        ):
            validate_campaign_checkpoint(plan, checkpoint)

    def test_one_evidence_queue_can_cross_primary_deep_and_control_roles(self):
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        full = build_campaign_selection(plan, role="all")
        leaves = tuple(
            next(leaf for leaf in plan.leaves if leaf.role == role)
            for role in ("primary", "deep", "control")
        )
        survey_policy = CampaignExecutionPolicy.for_profile(
            ExecutionProfile.SURVEY
        )
        survey = RecordingSurveyBackend()
        records = []
        for leaf in leaves:
            outcome = survey.execute_profile_stage(
                leaf, 64, survey_policy, SurveyEvidenceCache()
            )
            stage = _campaign_stage_record(
                plan, plan.precision_capabilities, outcome
            )
            records.append(CampaignLeafRecord(
                leaf_id=leaf.leaf_id,
                role=leaf.role,
                state="PRODUCED",
                stages=(stage,),
                evidence=_survey_evidence_record(
                    leaf.leaf_id, stage, survey_policy
                ),
            ))
        queue = build_campaign_evidence_queue_selection(
            plan, tuple(leaf.leaf_id for leaf in leaves)
        )
        backend = EvidenceUpgradeBackend(ExecutionProfile.CERTIFY)

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "checkpoint.json"
            _atomic_json(
                checkpoint,
                _checkpoint_mapping(
                    plan,
                    full,
                    tuple(
                        record
                        for leaf in plan.leaves
                        for record in records
                        if record.leaf_id == leaf.leaf_id
                    ),
                ),
            )
            summary = run_campaign_selection(
                plan,
                queue,
                backend,
                checkpoint,
                resume=True,
                execution_profile=ExecutionProfile.CERTIFY,
            )

        upgraded = {
            record.leaf_id: record for record in summary.records
        }
        self.assertEqual(len(backend.calls), 3)
        self.assertEqual(
            {
                next(
                    leaf.role
                    for leaf in leaves
                    if leaf.leaf_id == leaf_id
                )
                for leaf_id, _ in backend.calls
            },
            {"primary", "deep", "control"},
        )
        self.assertTrue(all(
            upgraded[leaf.leaf_id].evidence.evidence_level
            is EvidenceLevel.CERTIFIED
            for leaf in leaves
        ))


if __name__ == "__main__":
    unittest.main()
