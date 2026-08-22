from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from windows_solver.campaign_policy import (
    CampaignExecutionPolicy,
    EvidenceLevel,
    ExecutionProfile,
)
from windows_solver.response_batches import (
    CampaignPlan,
    CampaignSelection,
    PrecisionCapabilities,
    StageOutcome,
    _survey_execution_leaf_ids,
    build_campaign_plan,
    build_campaign_selection,
    run_campaign_selection,
    synthetic_stage_signed_error_channels,
    validate_campaign_checkpoint,
)
from windows_solver.response_engine import (
    NativeResourceUnavailableError,
    NumericalPolicy,
    VettedNativeDeterminantKernel,
)


def _plan() -> CampaignPlan:
    return build_campaign_plan(
        policy=NumericalPolicy(),
        backend_identity=VettedNativeDeterminantKernel.identity,
        precision_capabilities=PrecisionCapabilities((64, 80, 120)),
    )


def _matching_exterior_selection(plan: CampaignPlan) -> CampaignSelection:
    ids = tuple(
        leaf.leaf_id
        for leaf in plan.leaves
        if (
            leaf.role == "primary"
            and leaf.leaf.mode_label == "221"
            and leaf.job.spin == 0.95
            and leaf.mechanism_id != "horizon-admittance"
        )
    )
    return build_campaign_selection(plan, role="primary", leaf_ids=ids)


class RecordingSurveyBackend:
    identity = VettedNativeDeterminantKernel.identity

    def __init__(
        self,
        *,
        promote_leaf_id: str | None = None,
        fail_leaf_id: str | None = None,
    ) -> None:
        self.precision_capabilities = PrecisionCapabilities((64, 80, 120))
        self.promote_leaf_id = promote_leaf_id
        self.fail_leaf_id = fail_leaf_id
        self.operations: list[tuple[str, str, int]] = []

    def scientific_execution_contract_for(self, leaf):
        return None

    def execute_profile_stage(self, leaf, digits, policy, survey_cache):
        self.assert_policy(policy)
        self.operations.append((
            "SURVEY_FIXED_ROOT_RESPONSE", leaf.leaf_id, digits
        ))
        bounded = True
        promotion_required = False
        failure_code = None
        if leaf.leaf_id == self.promote_leaf_id and digits == 64:
            bounded = False
            promotion_required = True
        if leaf.leaf_id == self.fail_leaf_id:
            bounded = False
            promotion_required = False
            failure_code = "SYNTHETIC_SURVEY_CONTROL_FAILURE"
        payload = {
            "evidence_kind": "synthetic-survey-orchestration-contract",
            "leaf_id": leaf.leaf_id,
            "mechanism_id": leaf.mechanism_id,
            "digits": digits,
            "root_seal_accepted": True,
            "branch_identity_preserved": True,
            "domega_excludes_zero": True,
            "cheap_derivative_refinement_agrees": True,
            "bounded_response_disk": bounded,
            "response": (
                {"real": 1.0e-3, "imaginary": -2.0e-3}
                if bounded
                else None
            ),
            "survey_promotion_required": promotion_required,
            "survey_required_precision_digits": (
                80 if promotion_required else None
            ),
            "survey_failure_code": failure_code,
        }
        radius = 1.0e-7
        return StageOutcome(
            digits=digits,
            numerical_state=("CONVERGED" if bounded else "DERIVATIVE_UNRESOLVED"),
            component_result=payload,
            local_disk_radius_abs=radius,
            signed_error_channels=synthetic_stage_signed_error_channels(
                payload,
                radius,
                precision_ladder_applicable=False,
            ),
        )

    @staticmethod
    def assert_policy(policy):
        if not isinstance(policy, CampaignExecutionPolicy):
            raise AssertionError("survey backend did not receive typed policy")
        if policy.profile is not ExecutionProfile.SURVEY:
            raise AssertionError("survey backend received the wrong profile")
        forbidden = (
            policy.allow_truncation_root_solve,
            policy.allow_resolution_root_solve,
            policy.allow_seed_path_root_solve,
            policy.allow_expanded_derivative_ladder,
            policy.allow_full_complex_root_ladder,
            policy.allow_independent_validation,
        )
        if any(forbidden):
            raise AssertionError("survey policy enabled heavy work")


class CampaignSurveyOrchestrationTests(unittest.TestCase):
    def _run(self, backend, plan, selection):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return run_campaign_selection(
            plan,
            selection,
            backend,
            Path(temporary.name) / "checkpoint.json",
            resume=False,
            execution_profile=ExecutionProfile.SURVEY,
        )

    def test_every_exterior_mechanism_uses_one_survey_policy(self):
        plan = _plan()
        selection = build_campaign_selection(plan, role="all")
        backend = RecordingSurveyBackend()

        summary = self._run(backend, plan, selection)

        selected_mechanisms = {
            leaf.mechanism_id
            for leaf in plan.leaves
            if leaf.leaf_id in selection.leaf_ids
            and leaf.mechanism_id != "horizon-admittance"
        }
        executed_mechanisms = {
            next(
                leaf.mechanism_id
                for leaf in plan.leaves
                if leaf.leaf_id == leaf_id
            )
            for _, leaf_id, _ in backend.operations
            if next(
                leaf.mechanism_id
                for leaf in plan.leaves
                if leaf.leaf_id == leaf_id
            ) != "horizon-admittance"
        }
        self.assertEqual(executed_mechanisms, selected_mechanisms)
        self.assertEqual(len(selected_mechanisms), 5)
        self.assertTrue(all(record.state == "PRODUCED" for record in summary.records))
        self.assertTrue(all(
            record.evidence is not None
            and record.evidence.evidence_level is EvidenceLevel.SCREENED
            and record.evidence.execution_profile is ExecutionProfile.SURVEY
            for record in summary.records
        ))
        self.assertEqual(
            {operation for operation, _, _ in backend.operations},
            {"SURVEY_FIXED_ROOT_RESPONSE"},
        )

    def test_survey_uses_80_only_after_binary64_is_unbounded(self):
        plan = _plan()
        selection = _matching_exterior_selection(plan)
        leaf_id = selection.leaf_ids[0]
        backend = RecordingSurveyBackend(promote_leaf_id=leaf_id)

        summary = self._run(backend, plan, selection)

        digits = [
            digits
            for _, executed_leaf_id, digits in backend.operations
            if executed_leaf_id == leaf_id
        ]
        self.assertEqual(digits, [64, 80])
        self.assertNotIn(120, digits)
        record = next(item for item in summary.records if item.leaf_id == leaf_id)
        self.assertEqual(record.state, "PRODUCED")
        self.assertEqual(tuple(stage.outcome.digits for stage in record.stages), (64, 80))

    def test_unresolved_survey_leaf_is_recorded_and_campaign_advances(self):
        plan = _plan()
        selection = _matching_exterior_selection(plan)
        failed_id, next_id = selection.leaf_ids[:2]
        backend = RecordingSurveyBackend(fail_leaf_id=failed_id)

        summary = self._run(backend, plan, selection)

        records = {record.leaf_id: record for record in summary.records}
        self.assertEqual(records[failed_id].state, "UNRESOLVED")
        self.assertIsNone(records[failed_id].evidence)
        self.assertEqual(records[next_id].state, "PRODUCED")
        self.assertIn(next_id, [leaf_id for _, leaf_id, _ in backend.operations])

    def test_contained_resource_failure_is_failed_and_campaign_advances(self):
        plan = _plan()
        selection = _matching_exterior_selection(plan)
        failed_id, next_id = selection.leaf_ids[:2]

        class ResourceFailureBackend(RecordingSurveyBackend):
            def execute_profile_stage(self, leaf, digits, policy, survey_cache):
                if leaf.leaf_id == failed_id:
                    self.operations.append(("RESOURCE_FAILURE", leaf.leaf_id, digits))
                    raise NativeResourceUnavailableError(
                        "synthetic survey resource unavailable"
                    )
                return super().execute_profile_stage(
                    leaf, digits, policy, survey_cache
                )

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        checkpoint = Path(temporary.name) / "checkpoint.json"
        summary = run_campaign_selection(
            plan,
            selection,
            ResourceFailureBackend(),
            checkpoint,
            resume=False,
            execution_profile=ExecutionProfile.SURVEY,
        )
        records = {record.leaf_id: record for record in summary.records}

        self.assertEqual(records[failed_id].state, "FAILED")
        self.assertEqual(records[next_id].state, "PRODUCED")
        self.assertEqual(summary.evidence_counts["FAILED"], 1)
        restored = validate_campaign_checkpoint(plan, checkpoint)
        self.assertEqual(restored.state, "COMPLETE")
        self.assertEqual(restored.evidence_counts["FAILED"], 1)

    def test_execution_order_accepts_a_future_mode_without_a_mode_table(self):
        plan = _plan()
        selected = tuple(
            leaf for leaf in plan.leaves
            if leaf.role == "primary"
        )[:2]
        future = replace(
            selected[0],
            leaf=replace(selected[0].leaf, mode_label="332"),
        )
        changed = replace(
            plan,
            leaves=(future, *plan.leaves[1:]),
        )
        selection = build_campaign_selection(
            changed,
            role="primary",
            leaf_ids=tuple(item.leaf_id for item in selected),
        )

        ordered = _survey_execution_leaf_ids(changed, selection)

        self.assertEqual(set(ordered), set(selection.leaf_ids))

    def test_resume_reuses_screened_work_and_starts_at_first_missing_leaf(self):
        plan = _plan()
        selection = _matching_exterior_selection(plan)

        class InterruptedBackend(RecordingSurveyBackend):
            def execute_profile_stage(self, leaf, digits, policy, survey_cache):
                if len(self.operations) == 1:
                    raise RuntimeError("synthetic operator interruption")
                return super().execute_profile_stage(
                    leaf, digits, policy, survey_cache
                )

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        checkpoint = Path(temporary.name) / "checkpoint.json"
        first = InterruptedBackend()
        with self.assertRaisesRegex(RuntimeError, "operator interruption"):
            run_campaign_selection(
                plan,
                selection,
                first,
                checkpoint,
                resume=False,
                execution_profile=ExecutionProfile.SURVEY,
            )

        resumed = RecordingSurveyBackend()
        summary = run_campaign_selection(
            plan,
            selection,
            resumed,
            checkpoint,
            resume=True,
            execution_profile=ExecutionProfile.SURVEY,
        )

        self.assertEqual(summary.state, "COMPLETE")
        self.assertEqual(summary.reused_stage_count, 1)
        self.assertNotIn(
            first.operations[0][1],
            [leaf_id for _, leaf_id, _ in resumed.operations],
        )


if __name__ == "__main__":
    unittest.main()
