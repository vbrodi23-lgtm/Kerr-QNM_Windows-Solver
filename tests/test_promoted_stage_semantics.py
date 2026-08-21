from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import tempfile
from unittest.mock import patch
import unittest

import tests.test_promoted_exterior_derivative as exterior_fixtures
import tests.test_promoted_exterior_campaign_flow as campaign_fixtures
import tests.test_promoted_horizon_component as horizon_fixtures
import tests.test_selective_readout_promotion as selective_fixtures
import tests.test_linear_response_precision as precision_fixtures
from windows_solver.response_batches import (
    CampaignLeafRecord,
    PrecisionCapabilities,
    STAGE_SIGNED_ERROR_FAMILIES,
    StageOutcome,
    _campaign_stage_record,
    _classify_promoted_stage,
    _component_stage_signed_error_channels,
    _deep_precision120_decision,
    _primary_precision120_decision,
    _promoted_stage_semantics,
    _validate_component_result,
    _validate_record_semantics,
    _validate_selective_stage,
    build_campaign_plan,
    build_campaign_selection,
    explicit_stage_signed_error_channels,
    run_campaign_selection,
    synthetic_stage_signed_error_channels,
)
from windows_solver.response_engine import (
    ComponentResult,
    ComponentStatus,
    NumericalPolicy,
    PromotedRootSeal,
    VettedNativeDeterminantKernel,
    run_promoted_exterior_response_from_seal,
)


_LEGACY_EVIDENCE_KIND = "package-owned-julia-promoted-component-engine"
_SELECTIVE_EVIDENCE_KIND = "package-owned-selective-readout-promotion"
_ANALYTIC_EVIDENCE_KIND = (
    "package-owned-julia-single-promoted-horizon-component"
)


class PromotedStageSemanticsRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixed_fixture = (
            campaign_fixtures.PromotedExteriorCampaignFlowCanary("runTest")
        )
        self.fixed_fixture.setUp()
        self.addCleanup(self.fixed_fixture.doCleanups)

    def _unbounded_fixed_root_stage(self) -> tuple[StageOutcome, StageOutcome]:
        fixture = self.fixed_fixture
        backend = fixture._native_backend()
        baseline = (
            exterior_fixtures.PromotedExteriorDerivativeTests
            ._baseline_with_derivative_evidence(fixture.leaf)
        )
        noisy = campaign_fixtures._NoisyScientificFixedRootBackend(
            fixture.leaf.job, baseline, 80
        )
        with patch(
            "windows_solver.response_batches.run_component",
            return_value=fixture._binary_result(),
        ), patch.object(
            backend,
            "_julia_precision_backend_for",
            return_value=noisy,
        ):
            binary = backend.execute_stage(fixture.leaf, 64)
            promoted = backend.execute_promoted_stage(
                fixture.leaf, 80, (binary,)
            )
        return binary, promoted

    def _run_identityless_analytic_campaign(
        self,
        *,
        bounded_120: bool,
    ):
        fixture = horizon_fixtures.PromotedHorizonStageTests("runTest")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        leaf = next(
            item for item in plan.leaves
            if item.leaf_id == fixture.leaf.leaf_id
        )
        selection = build_campaign_selection(
            plan, role="primary", leaf_ids=(leaf.leaf_id,)
        )
        binary_result = horizon_fixtures._binary64_nonconverged_result(
            leaf.job, leaf.job.root.omega
        )
        workers = {}
        for digits in (80, 120):
            baseline = horizon_fixtures._promoted_baseline(leaf.job)
            if digits == 80 or not bounded_120:
                baseline = replace(
                    baseline,
                    branch_id=f"{leaf.job.root.branch_id}-mismatch",
                )
            baseline = horizon_fixtures._with_worker_receipt(
                leaf.job,
                baseline,
                digits,
                leaf.job.root.omega,
            )
            workers[digits] = horizon_fixtures.FakeJuliaPrecisionBackend(
                leaf.job, baseline, digits
            )
        # Keep the live campaign execution contract on the same committed
        # empirical-calibration identity as the worker-boundary substitutes.
        fixture.backend.ode_error_budgets = None
        fixture.backend.calibration_receipt = (
            workers[80]._production_request_backend(
                leaf.job
            ).calibration_receipt
        )
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        with patch(
            "windows_solver.response_batches.run_component",
            return_value=binary_result,
        ), patch.object(
            fixture.backend,
            "_julia_precision_backend_for",
            side_effect=lambda job, digits, refinement=0: workers[digits],
        ):
            return run_campaign_selection(
                plan,
                selection,
                fixture.backend,
                Path(temporary.name) / "identityless-analytic.json",
                resume=False,
            )

    def _identityless_analytic_stage(self):
        fixture = horizon_fixtures.PromotedHorizonStageTests("runTest")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        leaf = fixture.leaf
        binary_result = horizon_fixtures._binary64_nonconverged_result(
            leaf.job, leaf.job.root.omega
        )
        predecessor = horizon_fixtures._stage_from_result(64, binary_result)
        baseline = replace(
            horizon_fixtures._promoted_baseline(leaf.job),
            branch_id=f"{leaf.job.root.branch_id}-mismatch",
        )
        baseline = horizon_fixtures._with_worker_receipt(
            leaf.job,
            baseline,
            80,
            leaf.job.root.omega,
        )
        worker = horizon_fixtures.FakeJuliaPrecisionBackend(
            leaf.job, baseline, 80
        )
        with patch.object(
            fixture.backend,
            "_julia_precision_backend_for",
            return_value=worker,
        ):
            outcome = fixture.backend.execute_promoted_stage_with_predictor(
                leaf,
                80,
                (predecessor,),
                response_predictor=None,
            )
        return leaf, predecessor, outcome

    @staticmethod
    def _identity_stripped_legacy_stage(
        promoted: StageOutcome,
        *,
        with_promotion_decision: bool,
    ) -> StageOutcome:
        raw_result = dict(promoted.component_result["result"])
        lineage = dict(raw_result["lineage"])
        lineage.pop("component_scientific_identity", None)
        raw_result["lineage"] = lineage
        for field in (
            "component_scientific_identity",
            "response_method",
            "finite_amplitude_ladder_required",
            "finite_amplitude_ladder_executed",
            "finite_amplitude_readout_count",
            "response_uncertainty_status",
            "error_channel_applicability",
        ):
            raw_result.pop(field, None)
        downgraded = ComponentResult.from_mapping(raw_result)
        if downgraded.to_mapping() != raw_result:
            raise AssertionError("downgraded component fixture is not canonical")

        component = {
            **promoted.component_result,
            "evidence_kind": _LEGACY_EVIDENCE_KIND,
            "result": raw_result,
        }
        if with_promotion_decision:
            component["promotion_decision"] = {
                "schema": "windows-solver.precision-promotion-decision/2",
                "from_precision_digits": 80,
                "to_precision_digits": 120,
                "state": "SUPPRESSED",
                "reason": "CONVERGED_PROMOTION_GATES_SATISFIED",
                "predicted_reliable_digits": "52.250",
                "required_reliable_digits": "24",
                "precision_limited": False,
                "asymptotic_preflight_avoided_ode": False,
            }
        radius = sum(downgraded.error_channels.values())
        return replace(
            promoted,
            component_result=component,
            local_disk_radius_abs=radius,
            signed_error_channels=_component_stage_signed_error_channels(
                component,
                downgraded,
                repeat_applicable=True,
                precision_ladder_applicable=True,
            ),
            self_refinement_enclosed=False,
            discrepancy_from_previous_abs=0.0,
            discrepancy_enclosed=False,
        )

    def test_component_validation_rejects_fixed_root_downgraded_to_legacy(
        self,
    ) -> None:
        _, promoted = self._unbounded_fixed_root_stage()
        forged = self._identity_stripped_legacy_stage(
            promoted, with_promotion_decision=False
        )

        with self.assertRaises(ValueError):
            _validate_component_result(
                self.fixed_fixture.leaf,
                forged,
                allow_historical_conditioning_absence=False,
            )

    def test_record_validation_rejects_fixed_root_downgraded_to_legacy(
        self,
    ) -> None:
        binary, promoted = self._unbounded_fixed_root_stage()
        forged = self._identity_stripped_legacy_stage(
            promoted, with_promotion_decision=True
        )
        fixture = self.fixed_fixture
        record = CampaignLeafRecord(
            leaf_id=fixture.leaf.leaf_id,
            role="primary",
            state="UNRESOLVED",
            stages=(
                _campaign_stage_record(
                    fixture.plan, fixture.capabilities, binary
                ),
                _campaign_stage_record(
                    fixture.plan, fixture.capabilities, forged
                ),
            ),
        )

        with self.assertRaises(ValueError):
            _validate_record_semantics(
                fixture.leaf,
                record,
                fixture.plan.precision_factory_identity,
            )

    def test_selective_validation_rejects_unknown_component_identity(
        self,
    ) -> None:
        selective_fixture = selective_fixtures.SelectiveReadoutPromotionTests(
            "runTest"
        )
        selective_fixture.setUp()
        self.addCleanup(selective_fixture.doCleanups)
        outcome, previous_result, *_ = (
            selective_fixture._run_semantic_tier_loop(resolve_at_120=True)
        )
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        leaf = next(
            item for item in plan.leaves
            if item.leaf_id == previous_result.leaf_id
        )
        predecessor_component = {
            "evidence_kind": "native-task-008-component-engine",
            "result": previous_result.to_mapping(),
            "scientific_runtime": {},
        }
        predecessor_radius = sum(previous_result.error_channels.values())
        predecessor = StageOutcome(
            digits=64,
            numerical_state=previous_result.status.value,
            component_result=predecessor_component,
            local_disk_radius_abs=predecessor_radius,
            signed_error_channels=synthetic_stage_signed_error_channels(
                predecessor_component, predecessor_radius
            ),
        )

        raw_result = dict(outcome.component_result["result"])
        parsed = ComponentResult.from_mapping(raw_result)
        raw_result.update({
            "component_scientific_identity": "attacker-unknown-component/v1",
            "response_method": None,
            "finite_amplitude_ladder_required": (
                parsed.finite_amplitude_ladder_required
            ),
            "finite_amplitude_ladder_executed": (
                parsed.finite_amplitude_ladder_executed
            ),
            "finite_amplitude_readout_count": (
                parsed.finite_amplitude_readout_count
            ),
            "response_uncertainty_status": parsed.response_uncertainty_status,
            "error_channel_applicability": dict(
                parsed.error_channel_applicability
            ),
        })
        component = {**outcome.component_result, "result": raw_result}
        forged = replace(
            outcome,
            component_result=component,
            signed_error_channels=synthetic_stage_signed_error_channels(
                component, outcome.local_disk_radius_abs
            ),
        )

        with self.assertRaises(ValueError):
            _validate_selective_stage(leaf, forged, predecessor)

    def test_selective_validation_rejects_identityless_derivative_claim(
        self,
    ) -> None:
        selective_fixture = selective_fixtures.SelectiveReadoutPromotionTests(
            "runTest"
        )
        selective_fixture.setUp()
        self.addCleanup(selective_fixture.doCleanups)
        outcome, previous_result, *_ = (
            selective_fixture._run_semantic_tier_loop(resolve_at_120=True)
        )
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        leaf = next(
            item for item in plan.leaves
            if item.leaf_id == previous_result.leaf_id
        )
        predecessor_component = {
            "evidence_kind": "native-task-008-component-engine",
            "result": previous_result.to_mapping(),
            "scientific_runtime": {},
        }
        predecessor_radius = sum(previous_result.error_channels.values())
        predecessor = StageOutcome(
            digits=64,
            numerical_state=previous_result.status.value,
            component_result=predecessor_component,
            local_disk_radius_abs=predecessor_radius,
            signed_error_channels=synthetic_stage_signed_error_channels(
                predecessor_component, predecessor_radius
            ),
        )
        _, fixed_root = self._unbounded_fixed_root_stage()
        raw_result = dict(outcome.component_result["result"])
        raw_result["derivative_evidence"] = fixed_root.component_result[
            "result"
        ]["derivative_evidence"]
        forged_result = ComponentResult.from_mapping(raw_result)
        self.assertEqual(forged_result.to_mapping(), raw_result)
        self.assertIsNone(forged_result.component_scientific_identity)
        self.assertIsNotNone(forged_result.derivative_evidence)
        component = {**outcome.component_result, "result": raw_result}
        forged = replace(
            outcome,
            component_result=component,
            signed_error_channels=_component_stage_signed_error_channels(
                component,
                forged_result,
                repeat_applicable=False,
                precision_ladder_applicable=False,
            ),
        )

        with self.assertRaises(ValueError):
            _validate_selective_stage(leaf, forged, predecessor)

    def test_legacy_deep_mixed_enclosure_preserves_suppressed_120(self) -> None:
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        leaf = next(item for item in plan.leaves if item.role == "deep")
        outcome = precision_fixtures._authenticated_primary_stage(
            leaf,
            80,
            ComponentStatus.CONVERGED,
            self_refinement_enclosed=True,
            discrepancy_from_previous_abs=1.0e-9,
            discrepancy_enclosed=False,
        )
        outcome = precision_fixtures._with_baseline_conditioning(
            outcome,
            predicted_reliable_digits="55.125",
            required_reliable_digits="24",
            precision_limited=False,
        )

        decision = _deep_precision120_decision(
            outcome, sentinel_false_negative=False
        )

        self.assertEqual(decision["state"], "SUPPRESSED")
        self.assertEqual(
            decision["reason"], "CONVERGED_PROMOTION_GATES_SATISFIED"
        )

    def test_root_promotion_decision_ignores_response_only_mutation(self) -> None:
        """N: sealed-root promotion is invariant under response replacement."""

        fixture = self.fixed_fixture
        baseline = (
            exterior_fixtures.PromotedExteriorDerivativeTests
            ._baseline_with_derivative_evidence(fixture.leaf)
        )
        baseline = replace(baseline, omega=fixture.leaf.job.root.omega)
        seal = PromotedRootSeal.derive(fixture.leaf.job, baseline)
        resolved = run_promoted_exterior_response_from_seal(
            fixture.leaf.job,
            exterior_fixtures.FixedRootOnlyBackend(fixture.leaf.job, baseline),
            seal,
            derivative_step=0.004,
        )
        unresolved = run_promoted_exterior_response_from_seal(
            fixture.leaf.job,
            campaign_fixtures._NoisyScientificFixedRootBackend(
                fixture.leaf.job, baseline, 80
            ),
            seal,
            derivative_step=0.004,
        )
        self.assertEqual(resolved.baseline.to_mapping(), unresolved.baseline.to_mapping())
        self.assertEqual(
            resolved.derivative_evidence["root_seal_sha256"],
            unresolved.derivative_evidence["root_seal_sha256"],
        )

        def stage(result: ComponentResult) -> StageOutcome:
            component = {
                "evidence_kind": (
                    "package-owned-julia-fixed-root-exterior-derivative-component"
                ),
                "result": result.to_mapping(),
                "precision_ladder_discrepancy_applicable": False,
                "precision_ladder_discrepancy_reason": (
                    "BINARY64_COMPONENT_RESPONSE_UNAVAILABLE"
                ),
            }
            return StageOutcome(
                digits=80,
                numerical_state=result.status.value,
                component_result=component,
                local_disk_radius_abs=sum(result.error_channels.values()),
                signed_error_channels=_component_stage_signed_error_channels(
                    component,
                    result,
                    repeat_applicable=False,
                    precision_ladder_applicable=False,
                ),
                self_refinement_enclosed=None,
                discrepancy_from_previous_abs=None,
                discrepancy_enclosed=None,
            )

        resolved_decision = _primary_precision120_decision(stage(resolved))
        unresolved_decision = _primary_precision120_decision(stage(unresolved))
        self.assertEqual(resolved_decision, unresolved_decision)
        self.assertEqual(unresolved_decision["state"], "SUPPRESSED")

    def test_root_conditioning_alone_changes_root_promotion_decision(self) -> None:
        """O: a genuine root precision flag remains the sole 120 authority."""

        fixture = self.fixed_fixture
        baseline = (
            exterior_fixtures.PromotedExteriorDerivativeTests
            ._baseline_with_derivative_evidence(fixture.leaf)
        )
        baseline = replace(baseline, omega=fixture.leaf.job.root.omega)
        conditioning = baseline.numerical_conditioning
        self.assertIsNotNone(conditioning)
        limited_baseline = replace(
            baseline,
            numerical_conditioning=replace(
                conditioning,
                predicted_reliable_digits=Decimal("11"),
                required_reliable_digits=Decimal("24"),
                precision_limited=True,
            ),
        )

        def typed_root_stage(root_baseline) -> StageOutcome:
            result = exterior_fixtures.response_engine._unresolved_result(
                fixture.leaf.job,
                ComponentStatus.NOT_CONVERGED,
                root_baseline,
                (),
            )
            component = {
                "evidence_kind": (
                    "package-owned-julia-fixed-root-exterior-derivative-component"
                ),
                "result": result.to_mapping(),
                "precision_ladder_discrepancy_applicable": False,
                "precision_ladder_discrepancy_reason": (
                    "BINARY64_COMPONENT_RESPONSE_UNAVAILABLE"
                ),
            }
            return StageOutcome(
                digits=80,
                numerical_state=result.status.value,
                component_result=component,
                local_disk_radius_abs=0.0,
                signed_error_channels=_component_stage_signed_error_channels(
                    component,
                    result,
                    repeat_applicable=False,
                    precision_ladder_applicable=False,
                ),
                self_refinement_enclosed=None,
                discrepancy_from_previous_abs=None,
                discrepancy_enclosed=None,
            )

        adequate = _primary_precision120_decision(typed_root_stage(baseline))
        limited = _primary_precision120_decision(
            typed_root_stage(limited_baseline)
        )
        self.assertEqual(adequate["state"], "SUPPRESSED")
        self.assertEqual(limited["state"], "REQUESTED")
        self.assertEqual(
            limited["reason"], "ROOT_CONDITIONING_PRECISION_LIMITED"
        )

    def test_fixed_readout_can_hold_a_sealed_unresolved_response(self) -> None:
        """P: root completion and response terminality are separate states."""

        binary, promoted = self._unbounded_fixed_root_stage()
        semantics = _promoted_stage_semantics(promoted, predecessor=binary)
        self.assertTrue(semantics.root_sealed)
        self.assertFalse(semantics.root_requires_precision120)
        self.assertFalse(semantics.response_terminal_admissible)

    def test_identityless_analytic_branch_loss_never_requests_root_precision(
        self,
    ) -> None:
        try:
            summary = self._run_identityless_analytic_campaign(
                bounded_120=False
            )
        except ValueError as error:
            self.fail(f"typed analytic failure crashed admission: {error}")

        record = summary.records[0]
        self.assertEqual(record.state, "UNRESOLVED")
        self.assertEqual(
            tuple(
                stage.outcome.numerical_state for stage in record.stages
            ),
            (
                ComponentStatus.NOT_CONVERGED.value,
                ComponentStatus.BRANCH_LOSS.value,
            ),
        )
        self.assertEqual(
            record.stages[1].outcome.component_result[
                "promotion_decision"
            ]["state"],
            "SUPPRESSED",
        )

    def test_identityless_analytic_branch_loss_stays_terminal_even_if_120_is_good(
        self,
    ) -> None:
        try:
            summary = self._run_identityless_analytic_campaign(
                bounded_120=True
            )
        except ValueError as error:
            self.fail(f"typed analytic failure crashed admission: {error}")

        record = summary.records[0]
        self.assertEqual(record.state, "UNRESOLVED")
        self.assertEqual(
            tuple(
                stage.outcome.numerical_state for stage in record.stages
            ),
            (
                ComponentStatus.NOT_CONVERGED.value,
                ComponentStatus.BRANCH_LOSS.value,
            ),
        )

    def test_identityless_analytic_rejects_arbitrary_precision_delta(
        self,
    ) -> None:
        leaf, _, outcome = self._identityless_analytic_stage()
        result = ComponentResult.from_mapping(
            outcome.component_result["result"]
        )
        self.assertIsNone(result.component_scientific_identity)
        self.assertIsNone(result.response)
        component = {
            **outcome.component_result,
            "precision_ladder_discrepancy_applicable": True,
            "precision_ladder_discrepancy_reason": None,
        }
        forged_delta = complex(1.0e-9, -2.0e-9)
        family_deltas = {
            family: 0.0j for family in STAGE_SIGNED_ERROR_FAMILIES
        }
        family_deltas["precision-ladder-discrepancy"] = forged_delta
        forged = replace(
            outcome,
            component_result=component,
            local_disk_radius_abs=abs(forged_delta),
            signed_error_channels=explicit_stage_signed_error_channels(
                component,
                family_deltas=family_deltas,
                source_kind="authenticated-component-error-channel",
                source_id=result.job_id,
                units="M-delta-omega-per-native-coordinate",
                not_applicable_families=frozenset(
                    set(STAGE_SIGNED_ERROR_FAMILIES)
                    - {"precision-ladder-discrepancy"}
                ),
            ),
            discrepancy_from_previous_abs=abs(forged_delta),
            discrepancy_enclosed=False,
        )

        with self.assertRaises(ValueError):
            _validate_component_result(
                leaf,
                forged,
                allow_historical_conditioning_absence=False,
            )

    def test_fixed_root_identity_rejects_every_other_promoted_wrapper(
        self,
    ) -> None:
        _, promoted = self._unbounded_fixed_root_stage()
        for evidence_kind in (
            _LEGACY_EVIDENCE_KIND,
            _SELECTIVE_EVIDENCE_KIND,
            _ANALYTIC_EVIDENCE_KIND,
            "attacker-unknown-promoted-wrapper/v1",
        ):
            with self.subTest(evidence_kind=evidence_kind):
                component = {
                    **promoted.component_result,
                    "evidence_kind": evidence_kind,
                }
                forged = replace(
                    promoted,
                    component_result=component,
                    signed_error_channels=(
                        _component_stage_signed_error_channels(
                            component,
                            ComponentResult.from_mapping(component["result"]),
                            repeat_applicable=False,
                            precision_ladder_applicable=False,
                        )
                    ),
                )
                with self.assertRaises(ValueError):
                    _classify_promoted_stage(forged)
