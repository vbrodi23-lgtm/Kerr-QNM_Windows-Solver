from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, localcontext
import hashlib
import math
import unittest
from unittest.mock import patch

from tests.fixtures import (
    valid_horizon_endpoint_search_evidence,
    valid_numerical_conditioning,
)
from windows_solver.cli import _validate_reduction_component_checkpoint_binding
from windows_solver.contracts import canonical_json_bytes
from windows_solver.progress import (
    ProgressEventKind,
    activate_progress,
)
from windows_solver.response_batches import (
    CampaignLeafRecord,
    CampaignStageRecord,
    NativeCampaignStageBackend,
    PrecisionCapabilities,
    STAGE_SIGNED_ERROR_FAMILIES,
    StageOutcome,
    build_campaign_plan,
    _is_single_promoted_horizon_stage,
    _primary_precision120_decision,
    _primary_precision120_terminal_state,
    _primary_requires_precision120,
    _stage_with_promotion_decision,
    _validate_record_semantics,
    _validate_current_promoted_runtime,
    _validate_single_promoted_horizon_predictor_binding,
    synthetic_stage_signed_error_channels,
)
import windows_solver.response_engine as response_engine
from windows_solver.response_engine import (
    ComponentResult,
    ComponentStatus,
    DecimalComplex,
    DerivativeAuthenticationEvidence,
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
from windows_solver.julia_response_backend import JuliaPrecisionRootBackend
from windows_solver.promoted_control_calibration import (
    load_default_calibration_receipt,
)
from tests.fixtures import synthetic_ode_error_budget
from windows_solver.response_engine import NativeDeterminantAdapter, RootReadout
from windows_solver.response_reduction import (
    ResolvedComponentEvidence,
    SignedErrorContribution,
)
from pathlib import Path
from types import SimpleNamespace
from tests.test_native_campaign_backend import _failed_preflight_attempt


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
        derivative_lower_bound = (
            derivative_abs - Decimal("1e-12") - Decimal("1e-12")
        )
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
        derivative_authentication=DerivativeAuthenticationEvidence(
            derivative_re=derivative.real,
            derivative_im=derivative.imaginary,
            propagated_error_abs=Decimal("1e-12"),
            step_disagreement_abs=Decimal("1e-12"),
            lower_bound_abs=derivative_lower_bound,
            selected_step=Decimal("5e-7"),
            axis="real",
        ),
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
            raw_determinant_evaluation_count=1,
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


def _with_worker_receipt(job, baseline, digits, primary_predictor):
    calibration_receipt = load_default_calibration_receipt()
    determinant_family = (
        "horizon-scattering/v1"
        if job.mechanism_id == "horizon-admittance"
        else "exterior-wronskian/v1"
    )
    adapter = SimpleNamespace(runtime_provenance={})
    backend = JuliaPrecisionRootBackend(
        job.backend_identity,
        adapter,
        digits,
        empirical_control_profile=calibration_receipt.budget_for(
            determinant_family, digits
        ),
        calibration_receipt=calibration_receipt,
    )
    runtime = backend.scientific_runtime_for(job)
    request = backend._request(
        job,
        0.0j,
        primary_predictor,
        None,
    )
    expected_raw_count = (
        1 if job.mechanism_id == "horizon-admittance" else 3
    )
    baseline = replace(
        baseline,
        diagnostic_readouts={
            family: replace(
                diagnostic,
                fixed_root_evidence=replace(
                    diagnostic.fixed_root_evidence,
                    raw_determinant_evaluation_count=expected_raw_count,
                ),
            )
            for family, diagnostic in baseline.diagnostic_readouts.items()
        },
    )
    material = {
        "schema": response_engine.WORKER_RESPONSE_RECEIPT_SCHEMA,
        "request_binding": request,
        "request_sha256": hashlib.sha256(
            canonical_json_bytes(request)
        ).hexdigest(),
        "scientific_runtime_sha256": hashlib.sha256(
            canonical_json_bytes(runtime)
        ).hexdigest(),
        "worker_response_schema_version": (
            response_engine.WORKER_RESPONSE_WIRE_SCHEMA
        ),
        "root_residual_abs_text": str(
            baseline.normalised_determinant_abs
        ),
        "raw_determinant_abs_text": (
            None
            if baseline.raw_determinant_abs is None
            else str(baseline.raw_determinant_abs)
        ),
        "raw_determinant_evidence_status": (
            baseline.raw_determinant_evidence_status
        ),
        "promoted_root_readout_policy": PROMOTED_ROOT_READOUT_POLICY,
        "primary_acceptance_sha256": hashlib.sha256(
            canonical_json_bytes(
                baseline.primary_acceptance.to_mapping()
            )
        ).hexdigest(),
        "horizon_endpoint_search_evidence": (
            valid_horizon_endpoint_search_evidence(request)
            if job.mechanism_id == "horizon-admittance"
            else None
        ),
    }
    receipt = {
        **material,
        "receipt_sha256": hashlib.sha256(
            canonical_json_bytes(material)
        ).hexdigest(),
    }
    return replace(baseline, worker_response_receipt=receipt)


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
            "single-promoted-root-bounded-analytic-horizon-component/v2",
        )
        self.assertEqual(
            result.response_method,
            "bounded-analytic-horizon-from-promoted-primary-derivative/v2",
        )
        self.assertFalse(result.finite_amplitude_ladder_required)
        self.assertFalse(result.finite_amplitude_ladder_executed)
        self.assertEqual(result.finite_amplitude_readout_count, 0)
        self.assertIsNone(result.signed_root_crosscheck)
        self.assertEqual(result.closed_form_response, result.response)
        self.assertEqual(result.levels, ())
        self.assertEqual(
            result.response_uncertainty_status,
            "BOUNDED_ANALYTIC_RESPONSE",
        )
        self.assertEqual(
            result.error_channel_applicability,
            {
                name: name == "resolution"
                for name in response_engine.ERROR_CHANNELS
            },
        )
        self.assertTrue(result.response_uncertainty_calibrated)
        self.assertGreater(sum(result.error_channels.values()), 0.0)
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

        result = self._runner()(
            zero_job,
            FakePromotedBackend(zero_job, baseline),
            zero_frequency,
        )
        self.assertEqual(result.status, ComponentStatus.DERIVATIVE_UNRESOLVED)
        self.assertFalse(result.usable)
        self.assertEqual(
            result.response_uncertainty_status,
            "UNBOUNDED_ANALYTIC_RESPONSE",
        )

    def test_near_extremal_spin_uses_horizon_radius_clamp(self):
        rounded_job = replace(
            self.job,
            spin=math.nextafter(1.0, 0.0),
        )
        baseline = _promoted_baseline(rounded_job)

        result = self._runner()(
            rounded_job,
            FakePromotedBackend(rounded_job, baseline),
            rounded_job.root.omega,
        )

        self.assertEqual(result.status, ComponentStatus.CONVERGED)
        self.assertIsNotNone(result.response)
        self.assertTrue(math.isfinite(result.response.real))
        self.assertTrue(math.isfinite(result.response.imag))

    def test_rejects_nonfinite_or_non_subextremal_spin(self):
        for spin, label in (
            (math.nan, "nan"),
            (math.inf, "positive infinity"),
            (-math.inf, "negative infinity"),
            (1.0, "positive extremal"),
            (-1.0, "negative extremal"),
            (math.nextafter(1.0, math.inf), "positive superextremal"),
            (math.nextafter(-1.0, -math.inf), "negative superextremal"),
        ):
            with self.subTest(label=label):
                invalid_job = replace(self.job, spin=spin)
                baseline = _promoted_baseline(invalid_job)

                with self.assertRaisesRegex(ValueError, "Kerr spin"):
                    self._runner()(
                        invalid_job,
                        FakePromotedBackend(invalid_job, baseline),
                        invalid_job.root.omega,
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
                with self.assertRaisesRegex(ValueError, "promoted horizon"):
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
        return self._production_request_backend(job).scientific_runtime_for(
            job
        )

    def _production_request_backend(self, job):
        calibration_receipt = load_default_calibration_receipt()
        determinant_family = (
            "horizon-scattering/v1"
            if job.mechanism_id == "horizon-admittance"
            else "exterior-wronskian/v1"
        )
        return JuliaPrecisionRootBackend(
            self.identity,
            SimpleNamespace(runtime_provenance={}),
            self.digits,
            empirical_control_profile=calibration_receipt.budget_for(
                determinant_family, self.digits
            ),
            calibration_receipt=calibration_receipt,
        )

    def _request(
        self,
        job,
        amplitude,
        primary_predictor=None,
        primary_predictor_kind=None,
    ):
        # Failed-preflight fixtures in this module deliberately exercise the
        # injected ODE-budget constructor used by their attempted request.
        return JuliaPrecisionRootBackend(
            self.identity,
            object(),
            self.digits,
            ode_error_budget=synthetic_ode_error_budget(self.digits),
        )._request(
            job,
            amplitude,
            primary_predictor,
            primary_predictor_kind,
        )


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
            ode_error_budgets={
                80: synthetic_ode_error_budget(80),
                120: synthetic_ode_error_budget(120),
            },
        )

    def _record_with_receipt_predictor(self, receipt_predictor):
        predictor = self.leaf.job.root.omega + complex(1.0e-4, -1.0e-4)
        previous = _stage_from_result(
            64,
            _binary64_nonconverged_result(self.leaf.job, predictor),
        )
        baseline = _with_worker_receipt(
            self.leaf.job,
            _promoted_baseline(self.leaf.job),
            80,
            receipt_predictor,
        )
        julia_backend = FakeJuliaPrecisionBackend(
            self.leaf.job,
            baseline,
            80,
        )
        with patch(
            "windows_solver.response_batches.JuliaPrecisionRootBackend",
            return_value=julia_backend,
        ):
            promoted = self.backend.execute_promoted_stage_with_predictor(
                self.leaf,
                80,
                (previous,),
                response_predictor=complex(99.0, 88.0),
            )
        promoted = _stage_with_promotion_decision(
            promoted,
            _primary_precision120_decision(promoted),
        )
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        provenance = {
            "precision_factory_identity": (
                plan.precision_factory_identity.to_mapping()
            ),
            "available_precision_digits": [64, 80, 120],
        }
        record = CampaignLeafRecord(
            leaf_id=self.leaf.leaf_id,
            role=self.leaf.role,
            state="PRODUCED",
            stages=(
                CampaignStageRecord(previous, provenance),
                CampaignStageRecord(promoted, provenance),
            ),
        )
        return plan, predictor, promoted, record

    def test_dedicated_routing_scope_is_mechanism_scoped(self):
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        exterior = next(
            leaf
            for leaf in plan.leaves
            if leaf.role == "primary"
            and leaf.mechanism_id != "horizon-admittance"
        )
        deep_horizon = next(
            leaf
            for leaf in plan.leaves
            if leaf.role == "deep"
            and leaf.mechanism_id == "horizon-admittance"
        )

        self.assertTrue(_is_single_promoted_horizon_stage(self.leaf, 80))
        self.assertTrue(_is_single_promoted_horizon_stage(self.leaf, 120))
        self.assertFalse(_is_single_promoted_horizon_stage(self.leaf, 64))
        self.assertFalse(_is_single_promoted_horizon_stage(exterior, 80))
        self.assertTrue(_is_single_promoted_horizon_stage(deep_horizon, 80))

    def test_current_horizon_runtime_rejects_fully_resealed_noncanonical_request(self):
        predictor = self.leaf.job.root.omega + complex(1.0e-4, -1.0e-4)
        baseline = _with_worker_receipt(
            self.leaf.job,
            _promoted_baseline(self.leaf.job),
            80,
            predictor,
        )
        backend = FakeJuliaPrecisionBackend(self.leaf.job, baseline, 80)
        result = response_engine.run_promoted_horizon_component(
            self.leaf.job, backend, predictor
        )
        runtime = backend.scientific_runtime_for(self.leaf.job)
        payload = {
            "evidence_kind": "package-owned-julia-single-promoted-horizon-component",
            "result": result.to_mapping(),
            "self_refinement_result": None,
            "self_refinement_skipped_reason": "NOT_REQUIRED_BY_V1_4_PROMOTED_ROOT_POLICY",
            "scientific_runtime": runtime,
            "primary_root_predictor_source": "PREVIOUS_STAGE_BASELINE_OMEGA",
            "precision_ladder_discrepancy_applicable": False,
            "precision_ladder_discrepancy_reason": "BINARY64_COMPONENT_RESPONSE_UNAVAILABLE",
        }
        outcome = StageOutcome(
            digits=80,
            numerical_state=result.status.value,
            component_result=payload,
            local_disk_radius_abs=sum(result.error_channels.values()),
            signed_error_channels=synthetic_stage_signed_error_channels(
                payload, sum(result.error_channels.values()),
                precision_ladder_applicable=False,
            ),
        )
        forged = result.to_mapping()
        receipt = forged["baseline"]["worker_response_receipt"]
        receipt["request_binding"]["policy"][
            "horizon_endpoint_recovery_policy_identity"
        ] = "forged-endpoint-policy/v1"
        receipt["horizon_endpoint_search_evidence"][0][
            "policy_identity"
        ] = "forged-endpoint-policy/v1"
        receipt["request_sha256"] = hashlib.sha256(
            canonical_json_bytes(receipt["request_binding"])
        ).hexdigest()
        receipt["receipt_sha256"] = hashlib.sha256(canonical_json_bytes({
            key: value for key, value in receipt.items()
            if key != "receipt_sha256"
        })).hexdigest()
        forged_result = ComponentResult.from_mapping(forged)
        with self.assertRaisesRegex(
            ValueError, "canonical.*request|worker response receipt identity"
        ):
            _validate_current_promoted_runtime(
                self.leaf, outcome, forged_result,
                allow_historical_conditioning_absence=False,
            )

    def test_deep_horizon_ordinary_and_failed_preflight_use_horizon_runner(self):
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        deep = next(
            leaf
            for leaf in plan.leaves
            if leaf.role == "deep"
            and leaf.mechanism_id == "horizon-admittance"
        )
        predictor = deep.job.root.omega + complex(2.0e-5, -1.0e-5)
        previous = _stage_from_result(
            64, _binary64_nonconverged_result(deep.job, predictor)
        )
        baseline80 = _promoted_baseline(deep.job)
        baseline120 = _promoted_baseline(deep.job)
        backends = {
            80: FakeJuliaPrecisionBackend(deep.job, baseline80, 80),
            120: FakeJuliaPrecisionBackend(deep.job, baseline120, 120),
        }
        predecessor = _failed_preflight_attempt(
            deep, primary_predictor=predictor
        )

        with patch(
            "windows_solver.response_batches.JuliaPrecisionRootBackend",
            side_effect=lambda _identity, _adapter, digits, **_kwargs: (
                backends[digits]
            ),
        ), patch(
            "windows_solver.response_batches.run_promoted_exterior_component"
        ) as exterior:
            ordinary = self.backend.execute_promoted_stage_with_predictor(
                deep, 80, (previous,), response_predictor=None
            )
            recovered = (
                self.backend
                .execute_promoted_stage_after_failed_preflight_with_predictor(
                    deep, 120, predecessor, response_predictor=None
                )
            )

        exterior.assert_not_called()
        self.assertEqual(ordinary.digits, 80)
        self.assertEqual(recovered.digits, 120)
        self.assertEqual(backends[80].calls, [(deep.job, 0.0j, predictor)])
        self.assertEqual(backends[120].calls, [(deep.job, 0.0j, predictor)])

    def test_horizon_mechanism_precedes_stale_selective_recovery_plan(self):
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        deep = next(
            leaf
            for leaf in plan.leaves
            if leaf.role == "deep"
            and leaf.mechanism_id == "horizon-admittance"
        )
        predictor = deep.job.root.omega + complex(2.0e-5, -1.0e-5)
        previous_result = replace(
            _binary64_nonconverged_result(deep.job, predictor),
            resolved_window={
                "readout_specific_promotion_plan": [
                    {
                        "epsilon": deep.job.policy.epsilons[0],
                        "readout_roles": ["real-plus"],
                    }
                ],
                "next_precision_tier": "bigfloat-80",
            },
        )
        previous = _stage_from_result(64, previous_result)
        promoted_backend = FakeJuliaPrecisionBackend(
            deep.job, _promoted_baseline(deep.job), 80
        )

        with patch(
            "windows_solver.response_batches.JuliaPrecisionRootBackend",
            return_value=promoted_backend,
        ), patch(
            "windows_solver.response_batches.run_selective_readout_promotion"
        ) as selective:
            outcome = self.backend.execute_promoted_stage_with_predictor(
                deep, 80, (previous,), response_predictor=None
            )

        selective.assert_not_called()
        self.assertEqual(outcome.digits, 80)
        self.assertEqual(
            promoted_backend.calls, [(deep.job, 0.0j, predictor)]
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
            refinement=0,
            ode_error_budget=synthetic_ode_error_budget(80),
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

        def backend_factory(
            identity,
            adapter,
            digits,
            refinement=0,
            ode_error_budget=None,
        ):
            if digits == 120:
                return julia_backend
            return JuliaPrecisionRootBackend(
                identity,
                adapter,
                digits,
                refinement=refinement,
                ode_error_budget=ode_error_budget,
            )

        with patch(
            "windows_solver.response_batches.JuliaPrecisionRootBackend",
            side_effect=backend_factory,
        ) as backend_type:
            outcome = self.backend.execute_promoted_stage_with_predictor(
                self.leaf,
                120,
                (binary64, precision80),
                response_predictor=None,
            )

        self.assertEqual(
            [call.args[2] for call in backend_type.call_args_list].count(120),
            1,
        )
        self.assertFalse(
            any(
                len(call.args) >= 4 and call.args[3] == 1
                for call in backend_type.call_args_list
            )
        )
        self.assertEqual(
            julia_backend.calls,
            [(self.leaf.job, 0.0j, expected_predictor)],
        )
        self.assertIsNone(outcome.self_refinement_enclosed)
        self.assertIsNotNone(outcome.discrepancy_from_previous_abs)
        self.assertIsNotNone(outcome.discrepancy_enclosed)

    def test_failed_preflight_julia120_is_one_readout_without_refinement(self):
        predictor = complex(0.70001, -0.12002)
        predecessor = _failed_preflight_attempt(
            self.leaf,
            primary_predictor=predictor,
        )
        julia_backend = FakeJuliaPrecisionBackend(
            self.leaf.job,
            _promoted_baseline(self.leaf.job),
            120,
        )

        def backend_factory(
            identity,
            adapter,
            digits,
            refinement=0,
            ode_error_budget=None,
        ):
            if digits == 120:
                return julia_backend
            return JuliaPrecisionRootBackend(
                identity,
                adapter,
                digits,
                refinement=refinement,
                ode_error_budget=ode_error_budget,
            )

        with patch(
            "windows_solver.response_batches.JuliaPrecisionRootBackend",
            side_effect=backend_factory,
        ) as backend_type:
            outcome = (
                self.backend
                .execute_promoted_stage_after_failed_preflight_with_predictor(
                    self.leaf,
                    120,
                    predecessor,
                    response_predictor=complex(99.0, 88.0),
                )
            )

        self.assertEqual(
            [call.args[2] for call in backend_type.call_args_list].count(120),
            1,
        )
        self.assertFalse(
            any(
                len(call.args) >= 4 and call.args[3] == 1
                for call in backend_type.call_args_list
            )
        )
        self.assertEqual(
            julia_backend.calls,
            [(self.leaf.job, 0.0j, predictor)],
        )
        self.assertIsNone(outcome.self_refinement_enclosed)
        self.assertIsNone(outcome.discrepancy_from_previous_abs)
        self.assertIsNone(outcome.discrepancy_enclosed)
        self.assertIsNone(
            outcome.component_result["self_refinement_result"]
        )
        self.assertEqual(
            outcome.component_result["self_refinement_skipped_reason"],
            "NOT_REQUIRED_BY_V1_4_PROMOTED_ROOT_POLICY",
        )

    def test_80_to_120_gate_uses_root_and_conditioning_not_self_refinement(self):
        previous = _stage_from_result(
            64,
            _binary64_nonconverged_result(
                self.leaf.job,
                complex(0.70001, -0.12002),
            ),
        )

        def outcome_for(baseline):
            backend = FakeJuliaPrecisionBackend(self.leaf.job, baseline, 80)
            with patch(
                "windows_solver.response_batches.JuliaPrecisionRootBackend",
                return_value=backend,
            ):
                return self.backend.execute_promoted_stage_with_predictor(
                    self.leaf,
                    80,
                    (previous,),
                    response_predictor=None,
                )

        adequate = outcome_for(_promoted_baseline(self.leaf.job))
        self.assertFalse(_primary_requires_precision120(adequate))
        self.assertIsNone(adequate.self_refinement_enclosed)

        failed_root = _promoted_baseline(self.leaf.job)
        object.__setattr__(failed_root, "converged", False)
        self.assertTrue(_primary_requires_precision120(outcome_for(failed_root)))

        inadequate = _promoted_baseline(self.leaf.job)
        object.__setattr__(
            inadequate.numerical_conditioning,
            "predicted_reliable_digits",
            inadequate.numerical_conditioning.required_reliable_digits
            - Decimal(1),
        )
        object.__setattr__(
            inadequate.numerical_conditioning,
            "precision_limited",
            True,
        )
        self.assertTrue(_primary_requires_precision120(outcome_for(inadequate)))

    def test_julia120_terminal_gate_uses_root_and_conditioning(self):
        binary64 = _stage_from_result(
            64,
            _binary64_nonconverged_result(
                self.leaf.job,
                complex(0.70001, -0.12002),
            ),
        )
        precision80 = _stage_from_result(
            80,
            response_engine.run_promoted_horizon_component(
                self.leaf.job,
                FakePromotedBackend(
                    self.leaf.job,
                    _promoted_baseline(self.leaf.job),
                ),
                complex(0.70001, -0.12002),
            ),
        )

        def outcome_for(baseline):
            backend = FakeJuliaPrecisionBackend(self.leaf.job, baseline, 120)
            with patch(
                "windows_solver.response_batches.JuliaPrecisionRootBackend",
                return_value=backend,
            ):
                return self.backend.execute_promoted_stage_with_predictor(
                    self.leaf,
                    120,
                    (binary64, precision80),
                    response_predictor=None,
                )

        adequate = outcome_for(_promoted_baseline(self.leaf.job))
        self.assertEqual(
            _primary_precision120_terminal_state(
                adequate, predecessor=precision80
            ),
            "PRODUCED",
        )
        inadequate = _promoted_baseline(self.leaf.job)
        object.__setattr__(
            inadequate.numerical_conditioning,
            "predicted_reliable_digits",
            inadequate.numerical_conditioning.required_reliable_digits
            - Decimal(1),
        )
        object.__setattr__(
            inadequate.numerical_conditioning,
            "precision_limited",
            True,
        )
        self.assertEqual(
            _primary_precision120_terminal_state(
                outcome_for(inadequate), predecessor=precision80
            ),
            "UNRESOLVED",
        )

    def test_checkpoint_binds_promoted_predictor_to_previous_baseline(self):
        plan, predictor, _, valid = self._record_with_receipt_predictor(
            self.leaf.job.root.omega + complex(1.0e-4, -1.0e-4)
        )
        self.assertTrue(_validate_record_semantics(
            self.leaf,
            valid,
            plan.precision_factory_identity,
        ))

        for wrong_predictor, label in (
            (None, "missing"),
            (self.leaf.job.root.omega, "catalog root"),
            (complex(99.0, 88.0), "response predictor"),
        ):
            with self.subTest(label=label):
                plan, _, _, record = self._record_with_receipt_predictor(
                    wrong_predictor
                )
                with self.assertRaisesRegex(ValueError, "predictor binding"):
                    _validate_record_semantics(
                        self.leaf,
                        record,
                        plan.precision_factory_identity,
                    )
        self.assertNotEqual(predictor, self.leaf.job.root.omega)

    def test_checkpoint_binds_julia120_predictor_at_both_entry_paths(self):
        promoted80 = response_engine.run_promoted_horizon_component(
            self.leaf.job,
            FakePromotedBackend(
                self.leaf.job,
                _promoted_baseline(self.leaf.job),
            ),
            self.leaf.job.root.omega,
        )
        predecessors = (
            (
                "normal",
                _stage_from_result(80, promoted80),
                promoted80.baseline.omega,
            ),
            (
                "failed-preflight",
                _stage_from_result(
                    64,
                    _binary64_nonconverged_result(
                        self.leaf.job,
                        self.leaf.job.root.omega
                        + complex(1.0e-4, -1.0e-4),
                    ),
                ),
                self.leaf.job.root.omega
                + complex(1.0e-4, -1.0e-4),
            ),
        )
        for label, previous, expected in predecessors:
            with self.subTest(label=label):
                valid = _stage_from_result(
                    120,
                    response_engine.run_promoted_horizon_component(
                        self.leaf.job,
                        FakePromotedBackend(
                            self.leaf.job,
                            _with_worker_receipt(
                                self.leaf.job,
                                _promoted_baseline(self.leaf.job),
                                120,
                                expected,
                            ),
                        ),
                        expected,
                    ),
                )
                _validate_single_promoted_horizon_predictor_binding(
                    previous,
                    valid,
                )
                wrong = _stage_from_result(
                    120,
                    response_engine.run_promoted_horizon_component(
                        self.leaf.job,
                        FakePromotedBackend(
                            self.leaf.job,
                            _with_worker_receipt(
                                self.leaf.job,
                                _promoted_baseline(self.leaf.job),
                                120,
                                complex(99.0, 88.0),
                            ),
                        ),
                        expected,
                    ),
                )
                with self.assertRaisesRegex(ValueError, "predictor binding"):
                    _validate_single_promoted_horizon_predictor_binding(
                        previous,
                        wrong,
                    )

    def test_reduction_accepts_bounded_analytic_response(self):
        _, _, promoted, record = self._record_with_receipt_predictor(
            self.leaf.job.root.omega + complex(1.0e-4, -1.0e-4)
        )
        result = ComponentResult.from_mapping(
            promoted.component_result["result"]
        )
        source_receipt = "sha256:" + "1" * 64
        contributions = []
        for channel in promoted.signed_error_channels:
            scope = channel["scope"]
            channel_id = (
                f"local:{self.leaf.leaf_id}:{channel['family']}"
                if scope == "local"
                else channel["channel_id"]
            )
            shared_group = (
                self.leaf.leaf_id
                if scope == "local"
                else channel["shared_group"]
            )
            delta = channel["signed_delta"]
            contributions.append(SignedErrorContribution(
                channel_id=channel_id,
                family=channel["family"],
                shared_group=shared_group,
                delta=complex(delta["real"], delta["imaginary"]),
                units=channel["units"],
                source_receipt=source_receipt,
                scope=scope,
            ))
        component = ResolvedComponentEvidence(
            component_id=self.leaf.leaf_id,
            centre=result.response,
            units=contributions[0].units,
            contributions=tuple(contributions),
            recorded_discrepancies=(),
            required_families=STAGE_SIGNED_ERROR_FAMILIES,
            evidence_kind="authenticated-campaign",
        )

        _validate_reduction_component_checkpoint_binding(
            component,
            record,
            frozenset({source_receipt}),
        )


if __name__ == "__main__":
    unittest.main()
