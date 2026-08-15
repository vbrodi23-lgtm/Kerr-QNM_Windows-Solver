from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKER_SOURCE = REPO_ROOT / "src/windows_solver/data/julia/m02_worker.jl"
FD_SPEC_SOURCE = (
    REPO_ROOT
    / "src/windows_solver/data/julia/m02_worker_finite_difference_spec.jl"
)


class RegularisedGsnWorkerSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.worker = WORKER_SOURCE.read_text(encoding="utf-8")
        cls.fd_spec = FD_SPEC_SOURCE.read_text(encoding="utf-8")

    def test_worker_no_longer_owns_raw_homogeneous_production_path(self) -> None:
        for retired in (
            "homogeneous_rho_rhs!",
            "solve_homogeneous_endpoint",
            "solve_xin_at_match",
            "xup_outer_to_match_raw",
            "solve_xup_at_match",
            "solve_xup_scattering_coefficients",
        ):
            self.assertNotRegex(
                self.worker,
                rf"(?m)^function\s+{re.escape(retired)}\(",
            )

        self.assertRegex(self.worker, r"(?m)^function radial_rhs!\(")
        self.assertRegex(self.worker, r"(?m)^function solve_radial_endpoint\(")
        self.assertIn("AutoVern9(Rosenbrock23(autodiff=false))", self.worker)
        self.assertIn(
            'rho_in = parse_real(T, request, "rho_in")', self.worker
        )
        self.assertIn(
            'rho_out = parse_real(T, request, "rho_out")', self.worker
        )

    def test_request_local_context_freezes_one_branch_cell(self) -> None:
        for contract in (
            "struct DeterminantRequestContext{T<:AbstractFloat}",
            "frozen_convention::GSNBranchConvention{T}",
            "conditioning::ConditioningAccumulator{T}",
            "build_determinant_request_context",
            "GSN.gsn_branch_convention",
            "Kerr.stable_horizon_geometry",
            "CF.build_homogeneous_spectral_context",
            "context.frozen_convention",
            "maximum_contour_angle_deformation",
        ):
            self.assertIn(contract, self.worker)
        self.assertNotIn("const ACTIVE_CONDITIONING", self.worker)

    def test_all_needed_preflights_precede_factored_homogeneous_solves(self) -> None:
        horizon = self._function_slice(
            "evaluate_horizon_determinant", "horizon_endpoint_rho_candidates"
        )
        # Outer leg: preparation and its adequacy gate precede the solve.
        outer_prepare = horizon.index("CF.prepare_factored_infinity_outgoing(")
        outer_gate = horizon.index("CF.assert_factored_preflights_adequate(")
        outer_solve = horizon.index("CF.solve_factored_xup_to_match(")
        self.assertLess(outer_prepare, outer_gate)
        self.assertLess(outer_gate, outer_solve)

        # Horizon legs: the geometry gate and endpoint verification precede
        # any horizon propagation, so an escaping contour is rejected before
        # a homogeneous ODE is ever started.
        candidates = horizon.index("CF.horizon_endpoint_candidates(")
        verified = horizon.index("CF.select_verified_horizon_endpoints(")
        horizon_solve = horizon.index(
            "CF.solve_verified_horizon_basis_to_match("
        )
        self.assertLess(candidates, verified)
        self.assertLess(verified, horizon_solve)

    def test_horizon_determinant_cannot_use_the_mixed_inner_leg(self) -> None:
        """The removed graph must not come back through any production path.

        The mixed match-to-inner leg propagated the infinity solution into
        horizon coordinates instead of building an independent basis, and did
        it on a contour that escapes toward complex infinity. It is not slow
        for want of tuning; it is the wrong calculation.
        """

        horizon = self._function_slice(
            "evaluate_horizon_determinant", "horizon_endpoint_rho_candidates"
        )
        chart = self._function_slice(
            "evaluate_horizon_chart", "estimate_horizon_determinant_error"
        )
        for forbidden in (
            "solve_factored_xup_scattering_endpoint",
            "Xup_match_to_inner",
            "horizon_match_to_inner",
            "solve_factored_horizon_match_to_inner",
            "build_common_horizon_basis",
        ):
            self.assertNotIn(forbidden, horizon)
            self.assertNotIn(forbidden, chart)

    def test_horizon_determinant_carries_an_absolute_error(self) -> None:
        for contract in (
            "numerical_error_abs::Union{Nothing,T}",
            "error_model_id::Union{Nothing,String}",
            "VERIFIED_ENDPOINT_ERROR_MODEL_ID",
            "function estimate_horizon_determinant_error(",
        ):
            self.assertIn(contract, self.worker)
        estimate = self._function_slice(
            "estimate_horizon_determinant_error",
            "evaluate_horizon_reflectivity_chart",
        )
        # The endpoint disagreement is an absolute quantity. Dividing it by
        # |D| would report catastrophic error precisely at a root, where the
        # determinant is small by construction.
        self.assertIn("abs(reference_value - verification_value)", estimate)
        self.assertNotIn("/ abs(", estimate)

    def test_coordinate_controls_are_separate_from_homogeneous_controls(
        self,
    ) -> None:
        for contract in (
            "function coordinate_ode_tolerances(",
            '"coordinate_ode_relative_tolerance"',
            '"coordinate_ode_absolute_tolerance"',
            '"homogeneous_ode_relative_tolerance"',
            '"homogeneous_ode_absolute_tolerance"',
            "COORDINATE_INVERSION_STALLED",
            "function throw_coordinate_inversion_stalled(",
        ):
            self.assertIn(contract, self.worker)
        outer = self._function_slice(
            "build_worker_outer_contour",
            "build_worker_real_inner_horizon_contour",
        )
        inner = self._function_slice(
            "build_worker_real_inner_horizon_contour",
            "emit_coordinate_identity",
        )
        for slice_text in (outer, inner):
            self.assertIn("coordinate_ode_tolerances(T, request)", slice_text)
            self.assertIn("r_at_rho_zero=Complex{T}(match_radius)", slice_text)
            self.assertNotIn('"ode_relative_tolerance"', slice_text)

    def test_exterior_determinant_preflight_ordering_is_unchanged(self) -> None:

        exterior = self._function_slice(
            "evaluate_exterior_determinant", "determinant"
        )
        lower_prepare = exterior.index("CF.prepare_factored_horizon_ingoing(")
        outer_prepare = exterior.index("CF.prepare_factored_infinity_outgoing(")
        authenticated_gate = exterior.index(
            "CF.assert_factored_exterior_preparations_ready("
        )
        first_solve = min(
            exterior.index("CF.solve_factored_xin_to_match("),
            exterior.index("CF.solve_factored_xup_to_match("),
        )
        self.assertLess(lower_prepare, authenticated_gate)
        self.assertLess(outer_prepare, authenticated_gate)
        self.assertLess(authenticated_gate, first_solve)
        self.assertNotIn("CF.assert_factored_preflights_adequate(", exterior)

    def test_package_owns_factored_propagation_and_scattering_math(self) -> None:
        for call in (
            "CF.build_real_inner_horizon_contour(",
            "CF.horizon_endpoint_candidates(",
            "CF.select_verified_horizon_endpoints(",
            "CF.solve_verified_horizon_basis_to_match(",
            "CF.solve_factored_xin_to_match(",
            "CF.solve_factored_xup_to_match(",
            "CF.reconstruct_factored_match_state(",
            "Solutions.build_match_horizon_basis(",
            "Solutions.solve_scaled_horizon_basis_at_match(",
            "Solutions.evaluate_normalised_horizon_determinant(",
        ):
            self.assertIn(call, self.worker)
        # The inner-endpoint extraction pair had the mixed inner leg as its
        # only consumer. The package still exports both -- the exterior family
        # and the package test suite use them -- but the worker must not.
        for retired in (
            "Solutions.build_common_horizon_basis(",
            "Solutions.solve_scaled_factored_scattering(",
        ):
            self.assertNotIn(retired, self.worker)
        self.assertIn(
            "reflectivity = amplitude / (T(2) * im * spectral.p_horizon - amplitude)",
            self.worker,
        )
        self.assertNotRegex(
            self.worker,
            r"(?:state|endpoint|solution)\s*(?:\./|/)=\s*(?:maximum|abs)\(",
        )

    def test_determinants_are_typed_and_fd_consumes_values_with_evidence(self) -> None:
        for contract in (
            "struct DeterminantDiagnostics{T<:AbstractFloat}",
            "struct DeterminantEvaluation{T<:AbstractFloat}",
            "value::Complex{T}",
            "diagnostics::DeterminantDiagnostics{T}",
            "struct FiniteDifferenceDiagnostics{T<:AbstractFloat}",
            "build_finite_difference_diagnostics",
            "finite_difference_pair",
            "finite_difference_digits_lost",
            "record_finite_difference!",
        ):
            self.assertIn(contract, self.worker)
        determinant_progress = self._function_slice(
            "determinant_progress", "enforce_root_readout_feasibility"
        )
        self.assertIn("evaluation = determinant(", determinant_progress)
        self.assertIn("evaluation.value", determinant_progress)
        self.assertIn("return evaluation", determinant_progress)

    def test_holomorphic_finite_difference_spec_exercises_production_helper(
        self,
    ) -> None:
        helper = self._function_slice(
            "validate_finite_difference_inputs", "finite_difference_pair"
        )
        pair = self._function_slice("finite_difference_pair", "bounded_newton")

        self.assertIn("d_plus_value::Complex{T}", helper)
        self.assertIn("d_minus_value::Complex{T}", helper)
        self.assertIn("offset::Complex{T}", helper)
        self.assertIn("floatmax(T)", helper)
        self.assertIn("_fd_component_difference", helper)
        self.assertIn("_fd_scaled_norm", helper)
        self.assertIn("_fd_scaled_ratio", helper)
        self.assertIn("BigInt", helper)
        self.assertIn("frexp", helper)
        self.assertIn("ldexp", helper)
        self.assertNotIn("scaled_plus =", helper)
        self.assertNotIn("scaled_minus =", helper)
        self.assertIn("kappa_saturated", helper)
        self.assertIn("saturation_status", helper)
        self.assertIn("FiniteDifferenceDiagnostics{T}(", helper)
        self.assertIn(
            "build_finite_difference_diagnostics(",
            pair,
        )
        self.assertIn("d_plus.value", pair)
        self.assertIn("d_minus.value", pair)
        self.assertNotIn("difference = d_plus.value - d_minus.value", pair)
        validation = pair.index("validate_finite_difference_offset(")
        first_evaluation = pair.index("d_plus = determinant_progress(")
        self.assertLess(validation, first_evaluation)

        self.assertIn("build_finite_difference_diagnostics(", self.fd_spec)
        self.assertIn("axis=axis", self.fd_spec)
        self.assertIn('"real"', self.fd_spec)
        self.assertIn('"imaginary"', self.fd_spec)
        self.assertIn("diff(kappas)", self.fd_spec)
        self.assertIn("diff(digits_lost)", self.fd_spec)
        self.assertIn("floatmax(Float64)", self.fd_spec)
        self.assertIn("nextfloat(0.0)", self.fd_spec)
        self.assertIn("0.0 + 0.5im", self.fd_spec)
        self.assertIn('"derivative-underflow/v1"', self.fd_spec)
        self.assertIn("_fd_materialize_clamped(", self.fd_spec)
        self.assertIn("exact_kappa", self.fd_spec)
        self.assertIn("negative", self.fd_spec)
        self.assertIn("@test_throws ArgumentError", self.fd_spec)
        self.assertNotIn("T(4096) * eps(T)", self.fd_spec)

    def test_finite_difference_saturation_is_typed_and_accumulated(self) -> None:
        diagnostics = self.worker[
            self.worker.index("struct FiniteDifferenceDiagnostics") :
            self.worker.index("struct DeterminantRequestContext")
        ]
        record = self._function_slice(
            "record_finite_difference!", "numerical_control_failure"
        )
        pair = self._function_slice("finite_difference_pair", "bounded_newton")

        for field in (
            "d_plus_abs_saturated::Bool",
            "d_plus_abs_underflowed::Bool",
            "d_minus_abs_saturated::Bool",
            "d_minus_abs_underflowed::Bool",
            "difference_abs_saturated::Bool",
            "difference_abs_underflowed::Bool",
            "kappa_saturated::Bool",
            "kappa_underflowed::Bool",
            "kappa_is_infinite::Bool",
            "kappa_is_indeterminate::Bool",
            "derivative_abs_saturated::Bool",
            "derivative_abs_underflowed::Bool",
            "underflow_observed::Bool",
            "saturation_observed::Bool",
            "saturation_status::String",
            "finite_difference_saturation_observed::Bool",
            "finite_difference_underflow_observed::Bool",
        ):
            self.assertIn(field, diagnostics)
        self.assertIn("diagnostics.saturation_observed", record)
        self.assertIn("diagnostics.underflow_observed", record)
        self.assertIn('"saturation_observed"', pair)
        self.assertIn('"underflow_observed"', pair)
        self.assertIn('"saturation_status"', pair)

    def test_finite_difference_range_failure_is_typed_before_seed_fallback(
        self,
    ) -> None:
        translation = self._function_slice(
            "translate_numerical_control_failure", "compact_profile"
        )
        pair = self._function_slice("finite_difference_pair", "bounded_newton")
        bounded = self._function_slice("bounded_newton", "final_derivative")
        phase = self._function_slice("solve_phase", "refined_request")

        range_branch = translation[
            translation.index("failure isa FiniteDifferenceRangeError") :
            translation.index("failure isa CF.FactoredPropagationError")
        ]
        for contract in (
            '"ALGEBRAIC_REPRESENTATION_SINGULAR"',
            '"range_status"',
            '"axis"',
            '"h"',
            "retryable=false",
        ):
            self.assertIn(contract, range_branch)
        self.assertNotIn("factored_homogeneous_rhs_evaluations", range_branch)
        self.assertNotIn("avoided_ode_scope", range_branch)
        self.assertNotIn("asymptotic_preflight_avoided_ode", range_branch)

        self.assertIn("catch failure", pair)
        self.assertIn("failure isa FiniteDifferenceRangeError", pair)
        self.assertIn("translate_numerical_control_failure(", pair)
        self.assertIn("throw(translated)", pair)

        validation = bounded.index("validated_frequency_step(")
        first_determinant = bounded.index("initial_determinant =")
        self.assertLess(validation, first_determinant)
        self.assertIn("failure isa WorkerControlFailure && rethrow()", phase)

        for contract in (
            '"derivative-overflow/v1"',
            '"derivative-underflow/v1"',
            '"ALGEBRAIC_REPRESENTATION_SINGULAR"',
            '"range_status"',
            '"factored_homogeneous_rhs_evaluations"',
        ):
            self.assertIn(contract, self.fd_spec)

    def test_worker_main_is_guarded_so_pure_julia_spec_can_include_it(self) -> None:
        self.assertIn(
            'abspath(PROGRAM_FILE) == abspath(@__FILE__)', self.worker
        )
        self.assertIn('include("m02_worker.jl")', self.fd_spec)

    def test_every_factored_failure_reason_has_typed_worker_translation(self):
        translation = self.worker[
            self.worker.index("function translate_numerical_control_failure(") :
            self.worker.index("function compact_profile", self.worker.index(
                "function translate_numerical_control_failure("
            ))
        ]
        for reason in (
            "INVALID_FACTORED_PROPAGATION_INPUT",
            "FACTORED_PROPAGATION_PRECISION_MISMATCH",
            "NONFINITE_FACTORED_PROPAGATION_DATA",
            "FACTORED_ODE_FAILURE",
        ):
            self.assertIn(f'"{reason}"', translation)

    def test_nonfinite_stencil_values_use_the_caught_range_error(self):
        validation = self.worker[
            self.worker.index("function validate_finite_difference_inputs(") :
            self.worker.index("struct _FDScaledValue")
        ]
        self.assertIn("FiniteDifferenceRangeError(", validation)
        self.assertIn('"nonfinite-stencil/v1"', validation)
        self.assertNotIn(
            'ArgumentError("finite-difference inputs must be finite")',
            validation,
        )

    def test_worker_emits_exact_mechanism_honest_conditioning_contract(self) -> None:
        conditioning = self.worker[
            self.worker.index("function conditioning_response(") :
            self.worker.index("function result_fields(")
        ]
        for identity in (
            '"windows-solver.m02-conditioning/3"',
            '"horizon-scattering/v1"',
            '"exterior-wronskian/v1"',
            '"factored-plane-wave-gsn/v1"',
            '"gsn-complex-rho/v1"',
            '"column1=horizon-ingoing-Cref;column2=horizon-outgoing-Cinc/v1"',
            '"state2=dX/drho/v1"',
            '"cinc-over-cref-minus-R/v1"',
            '"cinc-over-cref-minus-reflectivity/v1"',
            '"wronskian-perturbed-Xin-with-Xup/v1"',
            '"unit-asymptotic-branch-wronskian/v1"',
            '"known-carrier-times-regular-remainder/v1"',
            '"state1=Y;state2=dY/drho/v1"',
        ):
            self.assertIn(identity, self.worker)
        for field in (
            "determinant_family",
            "scattering_diagnostics_applicable",
            "maximum_basis_condition",
            "maximum_basis_backward_error",
            "human_math_review_receipt_status",
            "human_math_review_receipt_sha256",
            "independent_reference_fixture_receipt_status",
            "independent_reference_fixture_receipt_sha256",
            "maximum_matching_reconstruction_residual",
            "minimum_cref_chart_margin",
            "maximum_carrier_change_error",
        ):
            self.assertIn(f'"{field}"', conditioning)
        self.assertIn('"raw_determinant_abs"', self.worker)
        self.assertIn("horizon ?", self.worker)
        self.assertIn(": nothing", self.worker)

    def test_preflight_failure_is_typed_and_proves_no_factored_rhs_work(self) -> None:
        for contract in (
            "struct NumericalControlFailure <: WorkerControlFailure",
            '"INSUFFICIENT_ASYMPTOTIC_PRECISION"',
            '"asymptotic_preflight_avoided_ode" => true',
            '"asymptotic_preflight_reason" => failure_code',
            "factored_homogeneous_rhs_evaluations == 0",
            '"factored-homogeneous-gsn/v1"',
        ):
            self.assertIn(contract, self.worker)

    def test_registered_conditioning_progress_is_literal(self) -> None:
        for event in (
            "asymptotic_series_evaluated",
            "factored_ode_completed",
            "scattering_coefficients_extracted",
            "determinant_chart_evaluated",
            "conditioning_evaluated",
            # Geometry gate and error-model evidence.
            "horizon_endpoint_candidate",
            "horizon_endpoints_verified",
            "coordinate_identity_checked",
            "determinant_error_estimated",
        ):
            self.assertIn(f'progress_emit("{event}"', self.worker)
        # carrier_changed belonged to the removed mixed inner leg. The carrier
        # change still happens inside the match-basis build, and its
        # reconstruction error is reported with the extracted coefficients.
        self.assertNotIn('progress_emit("carrier_changed"', self.worker)
        self.assertIn("carrier_change_error", self.worker)

    def test_error_envelope_stays_on_operational_schema_one(self) -> None:
        main = self.worker[self.worker.index("function main()") :]
        catch_block = main[main.index("catch failure") :]
        self.assertEqual(catch_block.count('"schema_version" => 1'), 2)
        self.assertNotIn('"schema_version" => 2', catch_block)

    def test_factored_solver_preserves_typed_resource_callback_failures(
        self,
    ) -> None:
        passthrough = re.compile(
            r"error isa ODEResourceLimit\s*\|\|\s*"
            r"error isa ODESolverFailure"
        )
        horizon = self._function_slice(
            "evaluate_horizon_determinant", "horizon_endpoint_rho_candidates"
        )
        exterior = self._function_slice(
            "evaluate_exterior_determinant", "determinant"
        )
        self.assertRegex(horizon, passthrough)
        self.assertRegex(exterior, passthrough)
        # A stalled coordinate map is a typed control failure too: it must
        # reach the campaign as COORDINATE_INVERSION_STALLED rather than being
        # wrapped as a generic propagation error.
        self.assertIn("error isa CoordinateInversionStalled", horizon)
        self.assertIn("function throw_ode_resource_limit(", self.worker)
        self.assertIn(
            "function throw_coordinate_inversion_stalled(", self.worker
        )

    def _function_slice(self, name: str, next_name: str) -> str:
        start = self.worker.index(f"function {name}(")
        end = self.worker.index(f"function {next_name}(", start + 1)
        return self.worker[start:end]


if __name__ == "__main__":
    unittest.main()
