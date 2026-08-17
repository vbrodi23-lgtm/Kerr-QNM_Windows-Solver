from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, localcontext
import math
import unittest
from unittest.mock import patch

from tests.fixtures import valid_numerical_conditioning
from windows_solver.progress import (
    ProgressEventKind,
    activate_progress,
)
from windows_solver.response_batches import (
    NativeCampaignStageBackend,
    PrecisionCapabilities,
    StageOutcome,
    build_campaign_plan,
    synthetic_stage_signed_error_channels,
)
import windows_solver.response_engine as response_engine
from windows_solver.response_engine import (
    ComponentResult,
    ComponentStatus,
    DecimalComplex,
    DiagnosticRootReadout,
    FixedRootDiagnosticEvidence,
    NumericalConditioningEvidence,
    NumericalPolicy,
    PrimaryRootAcceptanceEvidence,
    PROMOTED_ROOT_ACCEPTANCE_METRIC,
    PROMOTED_ROOT_READOUT_POLICY,
    RootReadout,
    VettedNativeDeterminantKernel,
)
from windows_solver.gsn_cache_producer import GeneratedGsnCache, GsnParameterPair
from windows_solver.response_engine import NativeDeterminantAdapter, RootReadout
from pathlib import Path
from types import SimpleNamespace


OPERATOR_OMEGA = complex(
    0.74458247210582695,
    -0.15968680213420339,
)
OPERATOR_DPRIME = DecimalComplex(
    Decimal("570.4114861939139931414749273123887"),
    Decimal("-421.5503889743617041025545703333967"),
)
OPERATOR_ANALYTIC_RESPONSE = complex(
    0.003825402144452362,
    0.002129401848381991,
)
OPERATOR_LADDER_RESPONSE = complex(
    0.003825402141848881,
    0.002129401849330452,
)
OPERATOR_LADDER_RADIUS = 2.84e-11


class RecordingObserver:
    def __init__(self) -> None:
        self.events = []

    def publish(self, event) -> None:
        self.events.append(event)


def _primary_horizon_leaf():
    plan = build_campaign_plan(
        policy=NumericalPolicy(),
        backend_identity=VettedNativeDeterminantKernel.identity,
        precision_capabilities=PrecisionCapabilities((64, 80, 120)),
    )
    return next(
        leaf
        for leaf in plan.leaves
        if (
            leaf.role == "primary"
            and leaf.mechanism_id == "horizon-admittance"
            and leaf.leaf.mode_label == "221"
            and math.isclose(leaf.job.spin, 0.95)
        )
    )


def _promoted_baseline(
    job,
    *,
    omega: complex = OPERATOR_OMEGA,
    derivative: DecimalComplex = OPERATOR_DPRIME,
    conditioning_mechanism: str = "horizon-admittance",
) -> RootReadout:
    conditioning = NumericalConditioningEvidence.from_mapping(
        valid_numerical_conditioning(conditioning_mechanism)
    )
    error_model_id = (
        "verified-endpoint-control-equivalence-absolute-error/v2"
        if conditioning.scattering_diagnostics_applicable
        else None
    )
    determinant = DecimalComplex(Decimal("1e-12"), Decimal(0))
    with localcontext() as context:
        context.prec = 180
        residual = determinant.magnitude()
        derivative_abs = derivative.magnitude()
        correction = residual / derivative_abs
    primary = PrimaryRootAcceptanceEvidence(
        policy_id=PROMOTED_ROOT_READOUT_POLICY,
        acceptance_metric=PROMOTED_ROOT_ACCEPTANCE_METRIC,
        determinant=determinant,
        derivative=derivative,
        correction_abs=correction,
        root_correction_tolerance=Decimal("2e-11"),
        accepted=True,
        newton_determinant_count=7,
        post_newton_determinant_count=0,
        determinant_error_abs=(
            Decimal("4.74e-13")
            if error_model_id is not None
            else Decimal(0)
        ),
        error_model_id=error_model_id,
    )
    diagnostics = {}
    for family, phase, value in (
        ("truncation", "TRUNCATION", Decimal("2e-12")),
        ("resolution", "RESOLUTION", Decimal("3e-12")),
    ):
        diagnostic_determinant = DecimalComplex(value, Decimal(0))
        with localcontext() as context:
            context.prec = 180
            diagnostic_residual = diagnostic_determinant.magnitude()
            diagnostic_correction = diagnostic_residual / derivative_abs
        fixed = FixedRootDiagnosticEvidence(
            policy_id=PROMOTED_ROOT_READOUT_POLICY,
            acceptance_metric=PROMOTED_ROOT_ACCEPTANCE_METRIC,
            root_phase=phase,
            determinant=diagnostic_determinant,
            primary_derivative=derivative,
            correction_abs=diagnostic_correction,
            root_correction_tolerance=Decimal("2e-11"),
            determinant_error_abs=(
                Decimal("4.74e-13")
                if error_model_id is not None
                else Decimal(0)
            ),
            error_model_id=error_model_id,
            control_identity=f"operator-{family}-controls/v1",
            branch_identity="gsn-complex-rho/v1",
            branch_authenticated=True,
            determinant_count=1,
            accepted=True,
            fixed_root=True,
            derivative_source="PRIMARY_COMPLEX",
        )
        diagnostics[family] = DiagnosticRootReadout(
            omega_delta_from_primary=0.0j,
            determinant_residual_abs=float(diagnostic_residual),
            determinant_derivative_abs=float(derivative_abs),
            converged=True,
            fixed_root_evidence=fixed,
        )
    raw_status = (
        "available/v1"
        if conditioning.scattering_diagnostics_applicable
        else "not-applicable/v1"
    )
    return RootReadout(
        omega=omega,
        determinant_residual_abs=float(residual),
        determinant_derivative_abs=float(derivative_abs),
        converged=True,
        root_reference_id=job.root.root_reference_id,
        branch_id=job.root.branch_id,
        equation_id=job.equation_id,
        truncation_radius=0.0,
        resolution_radius=0.0,
        seed_path_radius=None,
        diagnostic_readouts=diagnostics,
        numerical_conditioning=conditioning,
        normalised_determinant_abs=residual,
        raw_determinant_abs=(residual if raw_status == "available/v1" else None),
        raw_determinant_evidence_status=raw_status,
        promoted_root_readout_policy=PROMOTED_ROOT_READOUT_POLICY,
        primary_acceptance=primary,
        seed_path_required=False,
        seed_path_executed=False,
        seed_path_determinant_count=0,
    )


class FakePromotedBackend:
    def __init__(self, job, baseline: RootReadout) -> None:
        self.identity = job.backend_identity
        self.baseline = baseline
        self.bound_jobs = []
        self.calls = []

    def bind_job(self, job):
        self.bound_jobs.append(job)
        return job

    def read_root(self, job, amplitude, primary_predictor=None):
        self.calls.append((job, amplitude, primary_predictor))
        return self.baseline

    def closed_form_horizon_response(self, job):
        raise AssertionError("dedicated promoted runner called generic closed form")


class PromotedHorizonComponentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.leaf = _primary_horizon_leaf()
        self.job = self.leaf.job
        self.baseline = _promoted_baseline(self.job)

    def _runner(self):
        self.assertTrue(
            hasattr(response_engine, "run_promoted_horizon_component"),
            "dedicated promoted horizon runner is missing",
        )
        return response_engine.run_promoted_horizon_component

    def test_one_zero_amplitude_baseline_readout_and_no_epsilon_ladder(self):
        backend = FakePromotedBackend(self.job, self.baseline)
        predictor = complex(0.7445, -0.1597)
        observer = RecordingObserver()

        with activate_progress(observer):
            result = self._runner()(self.job, backend, predictor)

        self.assertEqual(backend.bound_jobs, [self.job])
        self.assertEqual(backend.calls, [(self.job, 0.0j, predictor)])
        self.assertEqual(result.raw_readouts, (self.baseline,))
        self.assertEqual(result.levels, ())
        starts = [
            event
            for event in observer.events
            if event.kind is ProgressEventKind.AMPLITUDE_READOUT_STARTED
        ]
        self.assertEqual(len(starts), 1)
        self.assertEqual(starts[0].context.readout_index, 1)
        self.assertEqual(starts[0].context.readout_role, "baseline")
        self.assertIsNone(starts[0].context.epsilon)
        self.assertEqual(
            starts[0].context.amplitude,
            {"real": 0.0, "imaginary": 0.0},
        )

    def test_operator_fixture_uses_complex_primary_derivative(self):
        result = self._runner()(
            self.job,
            FakePromotedBackend(self.job, self.baseline),
            self.job.root.omega,
        )

        self.assertEqual(result.status, ComponentStatus.CONVERGED)
        self.assertLess(abs(result.response - OPERATOR_ANALYTIC_RESPONSE), 1e-18)
        self.assertLess(
            abs(result.response - OPERATOR_LADDER_RESPONSE),
            OPERATOR_LADDER_RADIUS,
        )
        magnitude_only_wrong = 1.0 / (
            2.0j
            * (
                self.baseline.omega
                - self.job.mode.m
                * self.job.spin
                / (2.0 * (1.0 + math.sqrt(1.0 - self.job.spin**2)))
            )
            * float(self.baseline.primary_acceptance.derivative.magnitude())
        )
        self.assertGreater(abs(result.response - magnitude_only_wrong), 1e-4)

    def test_component_evidence_is_honest_and_round_trips(self):
        result = self._runner()(
            self.job,
            FakePromotedBackend(self.job, self.baseline),
            self.job.root.omega,
        )

        self.assertEqual(
            result.component_scientific_identity,
            "single-promoted-root-analytic-horizon-component/v1",
        )
        self.assertEqual(
            result.response_method,
            "analytic-horizon-from-promoted-primary-derivative/v1",
        )
        self.assertFalse(result.finite_amplitude_ladder_required)
        self.assertFalse(result.finite_amplitude_ladder_executed)
        self.assertEqual(result.finite_amplitude_readout_count, 0)
        self.assertIsNone(result.signed_root_crosscheck)
        self.assertEqual(result.closed_form_response, result.response)
        self.assertEqual(result.levels, ())
        self.assertEqual(
            result.response_uncertainty_status,
            "UNCALIBRATED_ANALYTIC_RESPONSE",
        )
        self.assertEqual(
            result.error_channel_applicability,
            {name: False for name in response_engine.ERROR_CHANNELS},
        )
        self.assertFalse(result.response_uncertainty_calibrated)
        self.assertEqual(result.error_channels, {
            name: 0.0 for name in response_engine.ERROR_CHANNELS
        })
        restored = ComponentResult.from_mapping(result.to_mapping())
        self.assertEqual(restored, result)
        self.assertEqual(restored.to_mapping(), result.to_mapping())

    def test_rejects_wrong_determinant_convention(self):
        baseline = _promoted_baseline(
            self.job,
            conditioning_mechanism="exterior-light-ring",
        )
        with self.assertRaisesRegex(ValueError, "determinant convention"):
            self._runner()(
                self.job,
                FakePromotedBackend(self.job, baseline),
                self.job.root.omega,
            )

    def test_rejects_zero_horizon_frequency(self):
        radius = 1.0 + math.sqrt(1.0 - self.job.spin**2)
        omega_h = self.job.spin / (2.0 * radius)
        zero_frequency = complex(self.job.mode.m * omega_h, 0.0)
        zero_job = replace(
            self.job,
            root=replace(self.job.root, omega=zero_frequency),
        )
        baseline = _promoted_baseline(zero_job, omega=zero_frequency)

        with self.assertRaisesRegex(ValueError, "horizon frequency"):
            self._runner()(
                zero_job,
                FakePromotedBackend(zero_job, baseline),
                zero_frequency,
            )

    def test_rejects_zero_or_nonfinite_retained_complex_derivative(self):
        for derivative, label in (
            (DecimalComplex(Decimal(0), Decimal(0)), "zero"),
            (DecimalComplex(Decimal("Infinity"), Decimal(0)), "nonfinite"),
        ):
            with self.subTest(label=label):
                baseline = _promoted_baseline(self.job)
                object.__setattr__(
                    baseline.primary_acceptance,
                    "derivative",
                    derivative,
                )
                with self.assertRaisesRegex(ValueError, "PRIMARY derivative"):
                    self._runner()(
                        self.job,
                        FakePromotedBackend(self.job, baseline),
                        self.job.root.omega,
                    )

    def test_rejects_missing_or_rejected_primary_evidence(self):
        missing = _promoted_baseline(self.job)
        object.__setattr__(missing, "primary_acceptance", None)
        rejected = _promoted_baseline(self.job)
        object.__setattr__(rejected.primary_acceptance, "accepted", False)

        for baseline, label in ((missing, "missing"), (rejected, "rejected")):
            with self.subTest(label=label):
                with self.assertRaisesRegex(ValueError, "PRIMARY"):
                    self._runner()(
                        self.job,
                        FakePromotedBackend(self.job, baseline),
                        self.job.root.omega,
                    )

    def test_rejects_wrong_policy_branch_or_determinant_budgets(self):
        wrong_policy = _promoted_baseline(self.job)
        object.__setattr__(
            wrong_policy,
            "promoted_root_readout_policy",
            "wrong-policy/v1",
        )
        wrong_branch = replace(
            _promoted_baseline(self.job),
            branch_id="wrong-branch",
        )
        wrong_primary_budget = _promoted_baseline(self.job)
        object.__setattr__(
            wrong_primary_budget.primary_acceptance,
            "post_newton_determinant_count",
            1,
        )
        wrong_truncation_budget = _promoted_baseline(self.job)
        object.__setattr__(
            wrong_truncation_budget.diagnostic_readouts[
                "truncation"
            ].fixed_root_evidence,
            "determinant_count",
            2,
        )
        wrong_seed_budget = _promoted_baseline(self.job)
        object.__setattr__(wrong_seed_budget, "seed_path_determinant_count", 1)

        cases = (
            (wrong_policy, "policy"),
            (wrong_primary_budget, "post-Newton"),
            (wrong_truncation_budget, "TRUNCATION"),
            (wrong_seed_budget, "SEED-PATH"),
        )
        for baseline, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    self._runner()(
                        self.job,
                        FakePromotedBackend(self.job, baseline),
                        self.job.root.omega,
                    )
        branch_result = self._runner()(
            self.job,
            FakePromotedBackend(self.job, wrong_branch),
            self.job.root.omega,
        )
        self.assertEqual(branch_result.status, ComponentStatus.BRANCH_LOSS)

    def test_rejects_non_primary_or_exterior_jobs(self):
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        exterior = next(
            leaf
            for leaf in plan.leaves
            if leaf.role == "primary"
            and leaf.mechanism_id == "exterior-light-ring"
        )
        control_job = replace(self.job, role="control")
        for job in (exterior.job, control_job):
            with self.subTest(role=job.role, mechanism=job.mechanism_id):
                baseline = _promoted_baseline(
                    job,
                    omega=job.root.omega,
                    conditioning_mechanism=job.mechanism_id,
                )
                with self.assertRaisesRegex(ValueError, "primary horizon"):
                    self._runner()(
                        job,
                        FakePromotedBackend(job, baseline),
                        job.root.omega,
                    )


def _binary64_nonconverged_result(job, omega: complex) -> ComponentResult:
    baseline = RootReadout(
        omega=omega,
        determinant_residual_abs=1.0e-10,
        determinant_derivative_abs=2.0,
        converged=False,
        root_reference_id=job.root.root_reference_id,
        branch_id=job.root.branch_id,
        equation_id=job.equation_id,
        truncation_radius=None,
        resolution_radius=None,
        seed_path_radius=None,
        diagnostics_skipped_reason="PRIMARY_NOT_CONVERGED",
    )
    return ComponentResult(
        job_id=job.job_id,
        leaf_id=job.leaf_id,
        mechanism_id=job.mechanism_id,
        status=ComponentStatus.NOT_CONVERGED,
        convergence_basis="UNRESOLVED",
        response=None,
        signed_root_crosscheck=None,
        closed_form_response=None,
        error_channels={name: 0.0 for name in response_engine.ERROR_CHANNELS},
        baseline=baseline,
        levels=(),
        lineage=response_engine._result_lineage(job),
    )


def _stage_from_result(digits: int, result: ComponentResult) -> StageOutcome:
    component = {"result": result.to_mapping()}
    return StageOutcome(
        digits=digits,
        numerical_state=result.status.value,
        component_result=component,
        local_disk_radius_abs=0.0,
        signed_error_channels=synthetic_stage_signed_error_channels(
            component,
            0.0,
            precision_ladder_applicable=False,
        ),
    )


class FakeJuliaPrecisionBackend(FakePromotedBackend):
    def __init__(self, job, baseline, digits) -> None:
        super().__init__(job, baseline)
        self.digits = digits

    def scientific_runtime_for(self, job):
        return {
            "precision_digits": self.digits,
            "working_precision_bits": math.ceil(self.digits * math.log2(10)) + 32,
            "refinement_level": 0,
            "regularised_gsn_precision_policy": dict(
                response_engine.regularised_gsn_precision_policy(
                    job.mechanism_id
                )
            ),
        }


class PromotedHorizonStageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.leaf = _primary_horizon_leaf()
        generated = GeneratedGsnCache(
            ("gsn-000001",),
            Path(".runtime/generated/gsn/gsn-selection-test.json"),
            "a" * 64,
            (GsnParameterPair(19, 20, self.leaf.job.mode.m),),
        )
        native = NativeDeterminantAdapter(
            identity=VettedNativeDeterminantKernel.identity,
            kernel=SimpleNamespace(),
        )
        self.backend = NativeCampaignStageBackend(
            native,
            PrecisionCapabilities((64, 80, 120)),
            generated,
            SimpleNamespace(),
        )

    def test_julia80_uses_binary64_baseline_as_single_root_predictor(self):
        predictor = complex(0.70001, -0.12002)
        previous_result = _binary64_nonconverged_result(
            self.leaf.job,
            predictor,
        )
        previous = _stage_from_result(64, previous_result)
        julia_backend = FakeJuliaPrecisionBackend(
            self.leaf.job,
            _promoted_baseline(self.leaf.job),
            80,
        )

        with patch(
            "windows_solver.response_batches.JuliaPrecisionRootBackend",
            return_value=julia_backend,
        ) as backend_type:
            outcome = self.backend.execute_promoted_stage_with_predictor(
                self.leaf,
                80,
                (previous,),
                response_predictor=complex(99.0, 88.0),
            )

        backend_type.assert_called_once_with(
            self.leaf.job.backend_identity,
            self.backend.julia_adapter,
            80,
        )
        self.assertEqual(
            julia_backend.calls,
            [(self.leaf.job, 0.0j, predictor)],
        )
        self.assertNotEqual(predictor, self.leaf.job.root.omega)
        self.assertIsNone(outcome.self_refinement_enclosed)
        self.assertIsNone(outcome.discrepancy_from_previous_abs)
        self.assertIsNone(outcome.discrepancy_enclosed)
        component = outcome.component_result
        self.assertIsNone(component["self_refinement_result"])
        self.assertEqual(
            component["self_refinement_skipped_reason"],
            "NOT_REQUIRED_BY_V1_4_PROMOTED_ROOT_POLICY",
        )
        self.assertIs(component["precision_ladder_discrepancy_applicable"], False)
        self.assertEqual(
            component["precision_ladder_discrepancy_reason"],
            "BINARY64_COMPONENT_RESPONSE_UNAVAILABLE",
        )

    def test_julia120_uses_same_single_readout_without_refinement(self):
        binary64 = _stage_from_result(
            64,
            _binary64_nonconverged_result(
                self.leaf.job,
                complex(0.70001, -0.12002),
            ),
        )
        prior_result = response_engine.run_promoted_horizon_component(
            self.leaf.job,
            FakePromotedBackend(
                self.leaf.job,
                _promoted_baseline(self.leaf.job),
            ),
            complex(0.70001, -0.12002),
        )
        precision80 = _stage_from_result(80, prior_result)
        expected_predictor = prior_result.baseline.omega
        julia_backend = FakeJuliaPrecisionBackend(
            self.leaf.job,
            _promoted_baseline(self.leaf.job),
            120,
        )

        with patch(
            "windows_solver.response_batches.JuliaPrecisionRootBackend",
            return_value=julia_backend,
        ) as backend_type:
            outcome = self.backend.execute_promoted_stage_with_predictor(
                self.leaf,
                120,
                (binary64, precision80),
                response_predictor=None,
            )

        backend_type.assert_called_once_with(
            self.leaf.job.backend_identity,
            self.backend.julia_adapter,
            120,
        )
        self.assertEqual(
            julia_backend.calls,
            [(self.leaf.job, 0.0j, expected_predictor)],
        )
        self.assertIsNone(outcome.self_refinement_enclosed)
        self.assertIsNotNone(outcome.discrepancy_from_previous_abs)
        self.assertIsNotNone(outcome.discrepancy_enclosed)


if __name__ == "__main__":
    unittest.main()
