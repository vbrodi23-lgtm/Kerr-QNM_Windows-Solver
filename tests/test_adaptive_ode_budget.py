from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from windows_solver.adaptive_controls import (
    ODE_CALIBRATION_BLOCKER,
    MissingODECalibrationError,
    ODEToleranceCalibration,
    derive_ode_error_budget,
)
from windows_solver.precision_tiers import PrecisionTier
from windows_solver.promoted_control_calibration import (
    load_default_calibration_receipt,
)
from windows_solver.julia_response_backend import (
    EXTERIOR_DETERMINANT_ABSOLUTE_ERROR_CERTIFICATE,
    JuliaPrecisionRootBackend,
    _adaptive_ode_request_controls,
    _precision_policy,
)
from windows_solver.contracts import canonical_json_bytes
from windows_solver.response_batches import (
    NativeCampaignStageBackend,
    PrecisionCapabilities,
    StageOutcome,
    _validate_current_promoted_runtime,
    build_campaign_plan,
    scientific_computation_identity_sha256,
    synthetic_stage_signed_error_channels,
)
from windows_solver.response_engine import (
    NumericalPolicy,
    VettedNativeDeterminantKernel,
    _journaled_promoted_exterior_backend,
    full_ladder_validation_policy,
    run_component,
)
from tests.fixtures import synthetic_ode_error_budget
from tests.test_julia_response_backend import FakeAdapter


CALIBRATION = ODEToleranceCalibration(
    identity="synthetic-calibration/v1",
    endpoint_series_fraction=0.10,
    coordinate_inversion_fraction=0.15,
    homogeneous_transport_fraction=0.35,
    angular_fraction=0.15,
    derivative_stencil_fraction=0.25,
    coordinate_relative_factor=0.5,
    coordinate_absolute_factor=0.25,
    homogeneous_relative_factor=0.4,
    homogeneous_absolute_factor=0.2,
)


class AdaptiveODEBudgetTests(unittest.TestCase):
    @staticmethod
    def _job():
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        return next(
            leaf.job for leaf in plan.leaves
            if leaf.role == "primary" and leaf.mechanism_id == "exterior-light-ring"
        )

    def test_changed_precision_policy_requires_budget_at_every_semantic_tier(self) -> None:
        job = self._job()
        for digits in (40, 80, 120):
            with self.subTest(digits=digits):
                with self.assertRaises(MissingODECalibrationError) as caught:
                    _precision_policy(job, digits, 0)
                self.assertEqual(str(caught.exception), ODE_CALIBRATION_BLOCKER)

    def test_changed_precision_policy_uses_only_recorded_budget_ode_controls(self) -> None:
        job = self._job()
        budget = derive_ode_error_budget(
            required_root_correction_abs=1.0e-10,
            determinant_derivative_lower_bound_abs=10.0,
            precision_tier=PrecisionTier.BIGFLOAT_80,
            calibration=CALIBRATION,
        )
        policy = _precision_policy(job, 80, 0, budget)
        self.assertEqual(
            float(policy["coordinate_ode_relative_tolerance"]),
            budget.coordinate_reltol,
        )
        self.assertEqual(
            float(policy["homogeneous_ode_relative_tolerance"]),
            budget.homogeneous_reltol,
        )
        self.assertEqual(policy["ode_error_budget"], budget.to_mapping())

    def test_production_request_controls_are_derived_from_recorded_budget(self) -> None:
        budget = derive_ode_error_budget(
            required_root_correction_abs=1.0e-10,
            determinant_derivative_lower_bound_abs=10.0,
            precision_tier=PrecisionTier.BIGFLOAT_80,
            calibration=CALIBRATION,
        )
        controls = _adaptive_ode_request_controls(80, budget)
        self.assertEqual(
            float(controls["coordinate_ode_relative_tolerance"]),
            budget.coordinate_reltol,
        )
        self.assertEqual(
            float(controls["homogeneous_ode_absolute_tolerance"]),
            budget.homogeneous_abstol,
        )
        self.assertEqual(controls["ode_error_budget"], budget.to_mapping())

    def test_changed_request_without_budget_fails_with_exact_blocker(self) -> None:
        with self.assertRaises(MissingODECalibrationError) as caught:
            _adaptive_ode_request_controls(80, None)
        self.assertEqual(str(caught.exception), ODE_CALIBRATION_BLOCKER)

    def test_preview_identity_is_exact_request_and_changes_with_ode_budget(self) -> None:
        job = self._job()
        budget = derive_ode_error_budget(
            required_root_correction_abs=1.0e-10,
            determinant_derivative_lower_bound_abs=10.0,
            precision_tier=PrecisionTier.BIGFLOAT_80,
            calibration=CALIBRATION,
        )
        changed = derive_ode_error_budget(
            required_root_correction_abs=5.0e-11,
            determinant_derivative_lower_bound_abs=10.0,
            precision_tier=PrecisionTier.BIGFLOAT_80,
            calibration=CALIBRATION,
        )
        backend = JuliaPrecisionRootBackend(
            job.backend_identity, object(), 80, ode_error_budget=budget
        )
        changed_backend = JuliaPrecisionRootBackend(
            job.backend_identity, object(), 80, ode_error_budget=changed
        )

        preview = backend.preview_root_request(
            job, 0.004j, job.root.omega, "SPIN_CONTINUATION", "imaginary-plus"
        )
        actual = backend._request(
            job, 0.004j, job.root.omega, "SPIN_CONTINUATION"
        )

        self.assertEqual(preview, actual)
        self.assertNotEqual(
            hashlib.sha256(canonical_json_bytes(preview)).hexdigest(),
            hashlib.sha256(canonical_json_bytes(changed_backend.preview_root_request(
                job, 0.004j, job.root.omega, "SPIN_CONTINUATION", "imaginary-plus"
            ))).hexdigest(),
        )

    def test_scientific_runtime_binds_exact_ode_budget_and_digest(self) -> None:
        job = self._job()
        budget = derive_ode_error_budget(
            required_root_correction_abs=1.0e-10,
            determinant_derivative_lower_bound_abs=10.0,
            precision_tier=PrecisionTier.BIGFLOAT_80,
            calibration=CALIBRATION,
        )
        changed = derive_ode_error_budget(
            required_root_correction_abs=5.0e-11,
            determinant_derivative_lower_bound_abs=10.0,
            precision_tier=PrecisionTier.BIGFLOAT_80,
            calibration=CALIBRATION,
        )

        adapter = SimpleNamespace(runtime_provenance={})
        runtime = JuliaPrecisionRootBackend(
            job.backend_identity, adapter, 80, ode_error_budget=budget
        ).scientific_runtime_for(job)
        changed_runtime = JuliaPrecisionRootBackend(
            job.backend_identity, adapter, 80, ode_error_budget=changed
        ).scientific_runtime_for(job)

        self.assertEqual(runtime["ode_error_budget"], budget.to_mapping())
        self.assertEqual(
            runtime["ode_error_budget_sha256"],
            hashlib.sha256(
                canonical_json_bytes(budget.to_mapping())
            ).hexdigest(),
        )
        self.assertNotEqual(
            runtime["ode_error_budget_sha256"],
            changed_runtime["ode_error_budget_sha256"],
        )

    def test_scientific_runtime_binds_empirical_receipt_and_family_profile(self) -> None:
        job = self._job()
        receipt = load_default_calibration_receipt()
        profile = receipt.budget_for("exterior-wronskian/v1", 80)

        runtime = JuliaPrecisionRootBackend(
            job.backend_identity,
            SimpleNamespace(runtime_provenance={}),
            80,
            empirical_control_profile=profile,
            calibration_receipt=receipt,
        ).scientific_runtime_for(job)

        self.assertNotIn("ode_error_budget", runtime)
        self.assertEqual(
            runtime["promoted_control_calibration"],
            {
                "schema": "windows-solver.promoted-control-calibration-binding/1",
                "receipt_identity": "promoted-control-empirical-calibration/v1",
                "receipt_sha256": (
                    "3353a1836e520f1e360cf30feb898e132c63db8ba5e691eb01b1ed01533243de"
                ),
                "execution_status": "EMPIRICAL_TEST_ONLY_NO_ARCHIVED_FLOOR",
                "source_audit_sha256": (
                    "a31a266c8488a7b19510a8d3fea4497cddcb2108eb9e424e27c396fa26ad6ae0"
                ),
                "determinant_family": "exterior-wronskian/v1",
                "determinant_certificate_identity": (
                    "exterior-determinant-absolute-error-certificate/empirical-v1"
                ),
                "determinant_certificate_safety_factor": 64,
                "derivative_floor_status": (
                    "ARCHIVED_AUTHENTICATED_LOWER_BOUND_UNAVAILABLE"
                ),
            },
        )
        self.assertEqual(runtime["empirical_control_profile"], profile.to_mapping())
        self.assertEqual(
            runtime["empirical_control_profile_sha256"],
            hashlib.sha256(
                canonical_json_bytes(profile.to_mapping())
            ).hexdigest(),
        )

    def test_empirical_request_uses_receipt_controls_without_ode_budget_claim(self) -> None:
        job = self._job()
        receipt = load_default_calibration_receipt()
        profile = receipt.budget_for("exterior-wronskian/v1", 80)
        # Empirical mode must be requested explicitly. Constructing a
        # default backend now selects the provisional additive-channel
        # contract; only the empirical certificate identity carries the
        # receipt-bound safety factor and calibration hashes on policy.
        backend = JuliaPrecisionRootBackend(
            job.backend_identity,
            SimpleNamespace(runtime_provenance={}),
            80,
            empirical_control_profile=profile,
            calibration_receipt=receipt,
            diagnostic_model_identity=(
                EXTERIOR_DETERMINANT_ABSOLUTE_ERROR_CERTIFICATE
            ),
        )

        policy = backend._request(job, 0.0j)["policy"]

        self.assertNotIn("ode_error_budget", policy)
        for name, expected in profile.base_controls.items():
            self.assertEqual(policy[name], expected)
        self.assertEqual(
            policy["promoted_control_calibration_receipt_sha256"],
            "3353a1836e520f1e360cf30feb898e132c63db8ba5e691eb01b1ed01533243de",
        )
        self.assertEqual(
            policy["empirical_control_profile_sha256"],
            hashlib.sha256(
                canonical_json_bytes(profile.to_mapping())
            ).hexdigest(),
        )

    def test_empirical_exterior_request_requires_certificate_identity(self) -> None:
        job = self._job()
        receipt = load_default_calibration_receipt()
        # Explicit empirical-certificate request — provisional is the
        # default now, so the certificate identity has to be asked for.
        policy = JuliaPrecisionRootBackend(
            job.backend_identity,
            SimpleNamespace(runtime_provenance={}),
            80,
            empirical_control_profile=receipt.budget_for(
                "exterior-wronskian/v1", 80
            ),
            calibration_receipt=receipt,
            diagnostic_model_identity=(
                EXTERIOR_DETERMINANT_ABSOLUTE_ERROR_CERTIFICATE
            ),
        )._request(job, 0.0j)["policy"]

        self.assertEqual(
            policy["determinant_error_model"],
            "exterior-determinant-absolute-error-certificate/empirical-v1",
        )
        self.assertIs(type(policy["determinant_error_safety_factor"]), int)
        self.assertEqual(policy["determinant_error_safety_factor"], 64)
        self.assertEqual(
            policy["determinant_error_required_term_classes"],
            [
                "delta_same_point",
                "delta_cross_precision",
                "delta_endpoint_series",
            ],
        )
        self.assertEqual(
            policy["determinant_error_missing_evidence_outcome"],
            "EXTERIOR_DETERMINANT_CERTIFICATE_UNAVAILABLE",
        )

    def test_current_promoted_runtime_accepts_empirical_receipt_request(self) -> None:
        """Catches requiring the superseded ODE-budget object at replay."""

        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        leaf = next(
            item for item in plan.leaves
            if item.role == "primary"
            and item.mechanism_id == "exterior-light-ring"
        )
        receipt = load_default_calibration_receipt()
        backend = JuliaPrecisionRootBackend(
            leaf.job.backend_identity,
            FakeAdapter(),
            80,
            empirical_control_profile=receipt.budget_for(
                "exterior-wronskian/v1", 80
            ),
            calibration_receipt=receipt,
        )
        result = run_component(
            leaf.job,
            backend,
            _promoted_validation_policy=full_ladder_validation_policy(
                "PUBLICATION_VALIDATION"
            ),
        )
        component = {
            "evidence_kind": "package-owned-julia-promoted-component-engine",
            "scientific_runtime": backend.scientific_runtime_for(leaf.job),
        }
        outcome = StageOutcome(
            digits=80,
            numerical_state=result.status.value,
            component_result=component,
            local_disk_radius_abs=sum(result.error_channels.values()),
            signed_error_channels=synthetic_stage_signed_error_channels(
                component, sum(result.error_channels.values())
            ),
        )

        _validate_current_promoted_runtime(
            leaf,
            outcome,
            result,
            allow_historical_conditioning_absence=False,
        )

    def test_native_execution_contract_binds_every_reachable_budget(self) -> None:
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        leaf = next(
            item for item in plan.leaves
            if item.role == "primary"
            and item.mechanism_id == "exterior-light-ring"
        )
        budgets = {
            digits: derive_ode_error_budget(
                required_root_correction_abs=10.0 ** (-digits // 4),
                determinant_derivative_lower_bound_abs=10.0,
                precision_tier=f"bigfloat-{digits}",
                calibration=CALIBRATION,
            )
            for digits in (40, 80, 120)
        }
        backend = NativeCampaignStageBackend(
            object(),
            plan.precision_capabilities,
            object(),
            julia_adapter=object(),
            ode_error_budgets=budgets,
        )

        contract = backend.scientific_execution_contract_for(leaf)

        self.assertEqual(
            contract["schema"],
            "windows-solver.m02-scientific-execution-contract/1",
        )
        self.assertEqual(
            contract["ode_error_budgets_by_nominal_decimal_digits"],
            {
                str(digits): budgets[digits].to_mapping()
                for digits in (40, 80, 120)
            },
        )

    def test_native_execution_contract_auto_loads_committed_empirical_receipt(self) -> None:
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        leaf = next(
            item for item in plan.leaves
            if item.role == "primary"
            and item.mechanism_id == "horizon-admittance"
        )
        backend = NativeCampaignStageBackend(
            object(),
            plan.precision_capabilities,
            object(),
            julia_adapter=object(),
        )

        contract = backend.scientific_execution_contract_for(leaf)

        self.assertEqual(
            contract,
            {
                "schema": "windows-solver.m02-scientific-execution-contract/2",
                "calibration_receipt": {
                    "identity": "promoted-control-empirical-calibration/v1",
                    "sha256": (
                        "3353a1836e520f1e360cf30feb898e132c63db8ba5e691eb01b1ed01533243de"
                    ),
                    "execution_status": "EMPIRICAL_TEST_ONLY_NO_ARCHIVED_FLOOR",
                    "source_audit_sha256": (
                        "a31a266c8488a7b19510a8d3fea4497cddcb2108eb9e424e27c396fa26ad6ae0"
                    ),
                },
                "determinant_certificate": {
                    "identity": (
                        "exterior-determinant-absolute-error-certificate/empirical-v1"
                    ),
                    "safety_factor": 64,
                },
                "determinant_family": "horizon-scattering/v1",
                "empirical_control_profiles_by_nominal_decimal_digits": {
                    str(digits): backend.calibration_receipt.budget_for(
                        "horizon-scattering/v1", digits
                    ).to_mapping()
                    for digits in (80, 120)
                },
            },
        )

    def test_control_leaf_contract_ignores_unreachable_promoted_budgets(self) -> None:
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        leaf = next(item for item in plan.leaves if item.role == "control")
        missing = NativeCampaignStageBackend(
            object(), plan.precision_capabilities, object(), julia_adapter=object()
        )
        changed = NativeCampaignStageBackend(
            object(),
            plan.precision_capabilities,
            object(),
            julia_adapter=object(),
            ode_error_budgets={
                80: synthetic_ode_error_budget(80),
                120: synthetic_ode_error_budget(120),
            },
        )

        self.assertIsNone(missing.scientific_execution_contract_for(leaf))
        self.assertIsNone(changed.scientific_execution_contract_for(leaf))
        self.assertEqual(
            scientific_computation_identity_sha256(
                plan,
                leaf,
                scientific_execution_contract=missing.scientific_execution_contract_for(leaf),
            ),
            scientific_computation_identity_sha256(
                plan,
                leaf,
                scientific_execution_contract=changed.scientific_execution_contract_for(leaf),
            ),
        )

    def test_changed_control_identity_starts_new_promoted_journal(self) -> None:
        """Catches stale promoted work blocking a new calibrated request."""

        job = self._job()
        budget = derive_ode_error_budget(
            required_root_correction_abs=1.0e-10,
            determinant_derivative_lower_bound_abs=10.0,
            precision_tier=PrecisionTier.BIGFLOAT_80,
            calibration=CALIBRATION,
        )
        changed = derive_ode_error_budget(
            required_root_correction_abs=5.0e-11,
            determinant_derivative_lower_bound_abs=10.0,
            precision_tier=PrecisionTier.BIGFLOAT_80,
            calibration=CALIBRATION,
        )
        first = JuliaPrecisionRootBackend(
            job.backend_identity, FakeAdapter(), 80, ode_error_budget=budget
        )
        second = JuliaPrecisionRootBackend(
            job.backend_identity, FakeAdapter(), 80, ode_error_budget=changed
        )
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            "os.environ",
            {"KERR_QNM_PARTIAL_COMPONENT_JOURNAL_ROOT": temporary},
        ):
            _journaled_promoted_exterior_backend(
                job,
                first,
                predictor=job.root.omega,
                derivative_step=0.004,
                validation_reason=None,
            )
            first_paths = tuple(Path(temporary).glob("*.json"))
            _journaled_promoted_exterior_backend(
                job,
                second,
                predictor=job.root.omega,
                derivative_step=0.004,
                validation_reason=None,
            )
            second_paths = tuple(Path(temporary).glob("*.json"))

        self.assertEqual(len(first_paths), 1)
        self.assertEqual(len(second_paths), 2)
        self.assertEqual(
            len({path.name for path in second_paths} - {first_paths[0].name}),
            1,
        )

    def test_tighter_root_request_never_produces_looser_controls(self) -> None:
        loose = derive_ode_error_budget(
            required_root_correction_abs=1.0e-8,
            determinant_derivative_lower_bound_abs=10.0,
            precision_tier=PrecisionTier.BIGFLOAT_40,
            calibration=CALIBRATION,
        )
        tight = derive_ode_error_budget(
            required_root_correction_abs=1.0e-10,
            determinant_derivative_lower_bound_abs=10.0,
            precision_tier=PrecisionTier.BIGFLOAT_120,
            calibration=CALIBRATION,
        )
        self.assertLessEqual(tight.coordinate_reltol, loose.coordinate_reltol)
        self.assertLessEqual(tight.coordinate_abstol, loose.coordinate_abstol)
        self.assertLessEqual(tight.homogeneous_reltol, loose.homogeneous_reltol)
        self.assertLessEqual(tight.homogeneous_abstol, loose.homogeneous_abstol)
        self.assertEqual(sum(tight.determinant_allocations.values()), tight.determinant_error_budget_abs)
        self.assertEqual(tight.calibration_identity, "synthetic-calibration/v1")
        self.assertEqual(tight.to_mapping()["nominal_decimal_digits"], 120)
        self.assertEqual(tight.to_mapping()["working_precision_bits"], 431)

    def test_budget_total_must_equal_root_correction_times_derivative_bound(self) -> None:
        budget = derive_ode_error_budget(
            required_root_correction_abs=1.0e-10,
            determinant_derivative_lower_bound_abs=10.0,
            precision_tier=PrecisionTier.BIGFLOAT_80,
            calibration=CALIBRATION,
        )
        doubled_total = 2.0 * budget.determinant_error_budget_abs
        doubled_allocations = {
            name: 2.0 * value
            for name, value in budget.determinant_allocations.items()
        }
        with self.assertRaisesRegex(
            ValueError, "root correction.*derivative lower bound"
        ):
            replace(
                budget,
                determinant_error_budget_abs=doubled_total,
                determinant_allocations=doubled_allocations,
            )

    def test_absent_calibration_fails_with_exact_human_math_blocker(self) -> None:
        with self.assertRaises(MissingODECalibrationError) as caught:
            derive_ode_error_budget(
                required_root_correction_abs=1.0e-10,
                determinant_derivative_lower_bound_abs=10.0,
                precision_tier=PrecisionTier.BIGFLOAT_80,
                calibration=None,
            )
        self.assertEqual(str(caught.exception), ODE_CALIBRATION_BLOCKER)
        self.assertEqual(
            ODE_CALIBRATION_BLOCKER,
            "TODO: [HUMAN MATH REVIEW REQUIRED - calibrated conversion from determinant/root error budget to ODE local tolerances is not yet established]",
        )

    def test_underflowed_or_overflowed_total_budget_fails_closed(self) -> None:
        for root_tolerance, derivative_bound in ((1.0e-300, 1.0e-300), (1.0e308, 1.0e308)):
            with self.subTest(root_tolerance=root_tolerance, derivative_bound=derivative_bound):
                with self.assertRaisesRegex(ValueError, "representable"):
                    derive_ode_error_budget(
                        required_root_correction_abs=root_tolerance,
                        determinant_derivative_lower_bound_abs=derivative_bound,
                        precision_tier=PrecisionTier.BIGFLOAT_80,
                        calibration=CALIBRATION,
                    )

    def test_underflowed_allocations_or_tolerances_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "representable"):
            derive_ode_error_budget(
                required_root_correction_abs=5.0e-324,
                determinant_derivative_lower_bound_abs=1.0,
                precision_tier=PrecisionTier.BIGFLOAT_80,
                calibration=CALIBRATION,
            )
        with self.assertRaisesRegex(ValueError, "representable"):
            derive_ode_error_budget(
                required_root_correction_abs=1.0e-8,
                determinant_derivative_lower_bound_abs=1.0,
                precision_tier=PrecisionTier.BIGFLOAT_80,
                calibration=replace(CALIBRATION, coordinate_relative_factor=5.0e-324),
            )


if __name__ == "__main__":
    unittest.main()
