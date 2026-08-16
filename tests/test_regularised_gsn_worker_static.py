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
HARNESS_COMMON_SOURCE = REPO_ROOT / "tools/leaf13_horizon_harness_common.jl"
CALIBRATION_SOURCE = REPO_ROOT / "tools/calibrate_leaf13_horizon_controls.jl"
BENCHMARK_SOURCE = REPO_ROOT / "tools/benchmark_leaf13_factored_legs.jl"


class RegularisedGsnWorkerSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.worker = WORKER_SOURCE.read_text(encoding="utf-8")
        cls.fd_spec = FD_SPEC_SOURCE.read_text(encoding="utf-8")
        cls.harness_common = HARNESS_COMMON_SOURCE.read_text(encoding="utf-8")
        cls.calibration = CALIBRATION_SOURCE.read_text(encoding="utf-8")
        cls.benchmark = BENCHMARK_SOURCE.read_text(encoding="utf-8")

    def test_leaf13_harnesses_share_the_canonical_determinant_api(self) -> None:
        self.assertIn("module Leaf13HorizonHarnessCommon", self.harness_common)
        self.assertIn("determinant_error_abs(T, evaluation)", self.harness_common)
        self.assertIn(
            "derivative_authentication_candidate(", self.harness_common
        )
        self.assertIn(
            "authentication.lower_bound_abs", self.harness_common
        )
        self.assertNotIn(
            "lower_bound_abs = abs(derivative) -", self.harness_common
        )
        self.assertNotIn("evaluation.numerical_error_abs", self.calibration)
        self.assertNotIn("evaluation.numerical_error_abs", self.benchmark)
        self.assertNotIn("include_string", self.calibration)
        self.assertNotIn("split(", self.calibration)
        for source in (self.calibration, self.benchmark):
            self.assertIn(
                'include(joinpath(@__DIR__, "leaf13_horizon_harness_common.jl"))',
                source,
            )
            self.assertIn("if abspath(PROGRAM_FILE) == @__FILE__", source)

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
        # The complete inner geometry and dual-series gate must pass before
        # even preparing the outer leg.  Otherwise invalid horizon geometry
        # can still consume the expensive Xup homogeneous solve.
        self.assertIn(
            "CF.horizon_endpoint_geometry_candidates(", horizon
        )
        geometry = horizon.index(
            "CF.horizon_endpoint_geometry_candidates("
        )
        candidates = horizon.index("CF.horizon_endpoint_candidates(")
        verified = horizon.index("CF.select_verified_horizon_endpoints(")
        outer_contour = horizon.index("build_worker_outer_contour(")
        outer_prepare = horizon.index("CF.prepare_factored_infinity_outgoing(")
        outer_gate = horizon.index("CF.assert_factored_preflights_adequate(")
        outer_solve = horizon.index("CF.solve_factored_xup_to_match(")
        self.assertLess(geometry, candidates)
        self.assertLess(candidates, verified)
        self.assertLess(verified, outer_contour)
        self.assertLess(verified, outer_prepare)
        self.assertLess(outer_prepare, outer_gate)
        self.assertLess(outer_gate, outer_solve)

        # The verified endpoint pair also precedes both horizon propagations.
        horizon_solve = horizon.index(
            "CF.solve_verified_horizon_basis_to_match("
        )
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
            "evaluate_horizon_chart", "determinant_error_breakdown"
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
            "struct DeterminantErrorBreakdown{T<:AbstractFloat}",
            "error_breakdown::Union{Nothing,DeterminantErrorBreakdown{T}}",
            "error_model_id::Union{Nothing,String}",
            "VERIFIED_ENDPOINT_ERROR_MODEL_ID",
            "function determinant_error_breakdown(",
        ):
            self.assertIn(contract, self.worker)
        estimate = self._function_slice(
            "determinant_error_breakdown",
            "evaluate_horizon_reflectivity_chart",
        )
        # The endpoint disagreement is an absolute quantity. Dividing it by
        # |D| would report catastrophic error precisely at a root, where the
        # determinant is small by construction.
        self.assertIn("safety_factor * maximum(available_components)", estimate)
        self.assertNotIn("/ abs(", estimate)

    def test_unauthenticated_families_keep_the_single_step_control(self) -> None:
        """Catches the rung search silently changing exterior results.

        The exterior scientific identity is deliberately unchanged by this
        work, so exterior receipts written before it stay valid and reusable.
        If exterior derivative selection changed, two runs under one identity
        could disagree and the identity would stop meaning what it claims.
        """

        self.assertIn(
            "function evaluate_single_derivative_step(", self.worker
        )
        ladder = self._function_slice(
            "evaluate_derivative_step_ladder", "root_authentication_text"
        )
        # The unauthenticated path returns before any rung construction or
        # frequency-range validation happens.
        gate = ladder.index(
            "authenticate_controls || return evaluate_single_derivative_step("
        )
        for rung_only in (
            "validated_frequency_steps(",
            "frequency_step_rungs(",
            "finite_difference_noise_limit(",
        ):
            self.assertIn(rung_only, ladder)
            self.assertLess(gate, ladder.index(rung_only))

        single = self._function_slice(
            "evaluate_single_derivative_step", "evaluate_derivative_step_ladder"
        )
        # It uses the nominal step alone and never consults the rung bounds.
        self.assertIn("validated_frequency_step(T, request)", single)
        for rung_only in (
            "validated_frequency_steps(",
            "frequency_step_rungs(",
            "MAXIMUM_FREQUENCY_STEP_RUNGS",
        ):
            self.assertNotIn(rung_only, single)
        # It keeps the historical accept-or-fail contract rather than stepping
        # to another rung.
        self.assertIn(
            "determinant frequency derivative estimates do not agree", single
        )
        # The four-fold width requirement belongs to the rung search alone, so
        # the Newton loop's step validation must not import it.
        nominal_validator = self._function_slice(
            "validated_frequency_step", "frequency_step_rungs"
        )
        self.assertNotIn("validated_frequency_steps(", nominal_validator)

    def test_every_finite_difference_sample_stays_inside_policy(self) -> None:
        for contract in (
            "function admissible_frequency_step_interval(",
            "frequency step rung samples escaped their bounds",
        ):
            self.assertIn(contract, self.worker)
        rungs = self._function_slice(
            "frequency_step_rungs", "validate_finite_difference_inputs"
        )
        # Admissibility is stated over the samples, not merely over the rung.
        self.assertIn("admissible_frequency_step_interval(", rungs)
        self.assertIn("minimum_step <= step / T(2)", rungs)
        self.assertIn("T(2) * step <= maximum_step", rungs)

    def test_finite_difference_chain_is_executable_against_a_fake(self) -> None:
        """Source-grep assertions cannot prove error propagation; execute it."""

        self.assertIn("determinant_evaluator=nothing", self.worker)
        self.assertIn(
            "evaluator = determinant_evaluator !== nothing ? "
            "determinant_evaluator :",
            self.worker,
        )
        for executed in (
            "sample errors reach the accepted bound through the real chain",
            "unresolved noise exhausts the range with a typed failure",
            "unauthenticated control keeps the single-step historical path",
            "a narrow range cannot silently sample outside policy",
        ):
            self.assertIn(executed, self.fd_spec)
        # The executed testsets must drive the ladder, not just the helper.
        self.assertIn("evaluate_derivative_step_ladder(", self.fd_spec)
        self.assertIn("determinant_evaluator=evaluator", self.fd_spec)

    def test_horizon_error_breakdown_is_complete_and_absolute(self) -> None:
        for field in (
            "endpoint_disagreement_abs::T",
            "control_disagreement_abs::Union{Nothing,T}",
            "equivalence_disagreement_abs::Union{Nothing,T}",
            "precision_disagreement_abs::Union{Nothing,T}",
            "safety_factor::T",
            "numerical_error_abs::T",
        ):
            self.assertIn(field, self.worker)
        horizon = self._function_slice(
            "evaluate_horizon_determinant", "horizon_endpoint_rho_candidates"
        )
        self.assertIn("reference.assessment.equivalence_disagreement_abs", horizon)
        self.assertIn("verification.assessment.equivalence_disagreement_abs", horizon)
        self.assertIn("endpoint_disagreement_abs", horizon)
        self.assertIn("equivalence_disagreement_abs", horizon)

    def test_the_precision_term_is_populated_rather_than_declared(self) -> None:
        """A component that is always ``nothing`` is a field, not a measurement.

        ``precision_disagreement_abs`` shipped declared and permanently unset.
        Asserting the struct field alone would have passed throughout, so these
        assertions target the path that gives it a value.
        """

        for contract in (
            "working_precision_bits_for(digits::Integer) =",
            "const PRECISION_GUARD_DIGITS",
            "function precision_guard_request(",
            "function precision_guard_context(",
            "function precision_guard_disagreement(",
            "round_to_working_precision(::Type{T}, value::Complex)",
            "run_at_working_precision(body, ::Type{BigFloat}",
        ):
            self.assertIn(contract, self.worker)

        # The mantissa policy has exactly one definition. A second one is how a
        # guard ends up asking for a width the request validator would reject.
        self.assertEqual(
            self.worker.count("ceil(Int, digits * log2(10)) + 32"), 1
        )

        start = self.worker.index("function precision_guard_request(")
        guard = self.worker[
            start:self.worker.index("run_at_working_precision(body", start)
        ]
        # Only the stored precision moves. Relaxing a control here would
        # re-measure the control disagreement and double-count it in the budget.
        for control in (
            "ode_relative_tolerance",
            "ode_absolute_tolerance",
            "frequency_step",
            "determinant_error_safety_factor",
        ):
            self.assertNotIn(control, guard)

        authenticated = self._function_slice(
            "authenticated_determinant_progress", "bounded_newton"
        )
        self.assertIn(
            "precision_disagreement_abs=precision_disagreement_abs",
            authenticated,
        )
        self.assertNotIn("precision_disagreement_abs=nothing", authenticated)

        for executed in (
            "the precision guard restates only the stored precision",
            "the precision guard keeps the branch and drops the conditioning",
            "the lowest stored-precision rung has nothing to compare against",
        ):
            self.assertIn(executed, self.fd_spec)

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
            '"ode_rejected_steps" => Int(stats.nreject)',
            '"current_r_re" => string(real(current_radius))',
            '"current_r_im" => string(imag(current_radius))',
            '"coordinate_identity_residual_abs" =>',
        ):
            self.assertIn(contract, self.worker)
        outer = self._function_slice(
            "build_worker_outer_contour",
            "build_worker_real_inner_horizon_contour",
        )
        inner = self._function_slice(
            "build_worker_real_inner_horizon_contour",
            "coordinate_identity_diagnostics",
        )
        for slice_text in (outer, inner):
            self.assertIn("coordinate_ode_tolerances(T, request)", slice_text)
            self.assertIn("r_at_rho_zero=Complex{T}(match_radius)", slice_text)
            self.assertNotIn('"ode_relative_tolerance"', slice_text)

    def test_coordinate_identity_is_a_typed_tolerance_gate(self) -> None:
        for contract in (
            "struct CoordinateIdentityEvidence{T<:AbstractFloat}",
            "maximum_absolute_residual::T",
            "maximum_relative_residual::T",
            "absolute_tolerance::T",
            "relative_tolerance::T",
            "function assert_coordinate_identity(",
            "coordinate_ode_tolerances(T, request)",
            '"COORDINATE_IDENTITY_MISMATCH"',
        ):
            self.assertIn(contract, self.worker)

        identity = self._function_slice(
            "throw_coordinate_identity_mismatch",
            "endpoint_conditioning_summary",
        )
        self.assertIn("Kerr.Delta(", identity)
        self.assertIn("numerical_control_failure(", identity)
        self.assertIn('"coordinate_identity_checked"', identity)
        self.assertNotIn("|| continue", identity)

        outer = self._function_slice(
            "build_worker_outer_contour",
            "build_worker_real_inner_horizon_contour",
        )
        inner = self._function_slice(
            "build_worker_real_inner_horizon_contour",
            "coordinate_identity_diagnostics",
        )
        for body in (outer, inner):
            self.assertIn("assert_coordinate_identity(", body)
            self.assertNotIn("emit_coordinate_identity(", body)

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

    def test_horizon_chart_identity_assertion_remains_fail_closed(self) -> None:
        expectations = self.worker[
            self.worker.index("const HORIZON_CHART_IDENTITY_EXPECTATIONS") :
            self.worker.index("function assert_horizon_chart_identities")
        ]
        self.assertIn(
            "HORIZON_BASIS_AT_MATCH_EXTRACTION_ID",
            expectations,
        )
        assertion = self._function_slice(
            "assert_horizon_chart_identities",
            "evaluate_horizon_reflectivity_chart",
        )
        self.assertIn(
            "getfield(chart_assessment, field) == expected || error(",
            assertion,
        )
        chart = self._function_slice(
            "evaluate_horizon_reflectivity_chart",
            "evaluate_horizon_determinant",
        )
        self.assertIn(
            "assert_horizon_chart_identities(chart_assessment)",
            chart,
        )
        self.assertIn(
            "worker accepts the horizon-at-match chart identity",
            self.fd_spec,
        )
        self.assertIn(
            "worker rejects a forged coefficient extraction identity",
            self.fd_spec,
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
        first_evaluation = pair.index("d_plus = evaluator(")
        self.assertLess(validation, first_evaluation)
        self.assertIn(
            "authenticated_determinant_progress : determinant_progress",
            pair,
        )

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

    def test_final_derivatives_preserve_each_stencil_error(self) -> None:
        pair = self._function_slice("finite_difference_pair", "bounded_newton")
        final = self._function_slice(
            "final_derivative", "evaluate_derivative_step_ladder"
        )
        ladder = self._function_slice(
            "evaluate_derivative_step_ladder", "solve_once"
        )
        self.assertIn("propagated_centered_difference_error(", pair)
        self.assertIn("return derivative, diagnostics, derivative_error_abs", final)
        for name in ("base_error_abs", "half_error_abs", "double_error_abs", "imaginary_error_abs"):
            self.assertIn(name, ladder)
        self.assertIn("derivative_error_abs=half_error_abs", ladder)
        self.assertNotIn("root_error_abs / abs(h / T(2))", ladder)

    def test_derivative_authentication_derives_one_lower_bound(self) -> None:
        authentication = self.worker[
            self.worker.index("struct DerivativeAuthentication") :
            self.worker.index("struct RootAuthentication")
        ]
        self.assertIn(
            "lower_bound_abs = abs(value) - step_disagreement_abs -",
            authentication,
        )
        self.assertNotIn(
            "step_disagreement_abs::T,\n        lower_bound_abs::T,",
            authentication,
        )
        ladder = self._function_slice(
            "evaluate_derivative_step_ladder", "root_authentication_text"
        )
        self.assertNotIn(
            "derivative_abs - uncertainty - derivative_error_abs", ladder
        )

    def test_frequency_step_ladder_is_validated_bounded_and_unique(self) -> None:
        for contract in (
            "const MAXIMUM_FREQUENCY_STEP_RUNGS",
            "function validated_frequency_steps(",
            "minimum_step <= nominal_step <= maximum_step",
            "function frequency_step_rungs(",
            "unique!(rungs)",
        ):
            self.assertIn(contract, self.worker)
        self.assertIn("length(rungs) <= MAXIMUM_FREQUENCY_STEP_RUNGS", self.fd_spec)
        self.assertIn("length(rungs) == length(unique(rungs))", self.fd_spec)


    def test_promoted_root_roles_separate_primary_authentication_from_diagnostics(
        self,
    ) -> None:
        for contract in (
            "@enum RootSolveRole",
            "FULL_AUTHENTICATION",
            "DIAGNOSTIC_CONSISTENCY",
            "function solve_full_authentication(",
            "function solve_diagnostic_consistency(",
        ):
            self.assertIn(contract, self.worker)

        diagnostic = self._function_slice(
            "solve_diagnostic_consistency", "solve_phase"
        )
        self.assertIn("diagnostic_consistency_newton", diagnostic)
        self.assertIn("solve_full_authentication", diagnostic)
        self.assertNotIn("evaluate_derivative_step_ladder(", diagnostic)
        self.assertNotIn('"final derivative h/2"', diagnostic)
        self.assertNotIn('"final derivative 2h"', diagnostic)
        self.assertNotIn('"final derivative ih"', diagnostic)
        diagnostic_newton = self._function_slice(
            "diagnostic_consistency_newton", "solve_full_authentication"
        )
        self.assertIn("bounded_newton(", diagnostic_newton)
        self.assertIn("propagate_derivative_error=true", diagnostic_newton)
        self.assertNotIn("evaluate_derivative_step_ladder(", diagnostic_newton)

        phase = self._function_slice("solve_phase", "refined_request")
        self.assertIn("solve_role::RootSolveRole", phase)
        self.assertNotIn('authenticate_controls=(phase == "PRIMARY")', phase)

    def test_diagnostic_reuse_is_exact_and_phase_telemetry_is_complete(
        self,
    ) -> None:
        for contract in (
            "function remember_authenticated_determinant!(",
            "function reuse_authenticated_determinant(",
            "isequal(evidence.request, request)",
            "GSN.full_convention_equal(",
            "evidence.frozen_branch_cell == context.frozen_branch_cell",
            '"solve_role"',
            '"full_authentication_escalated"',
            '"escalation_reason"',
            '"authenticated_evidence_reused"',
            '"determinant_count"',
            '"control_identity"',
            '"correction_upper_bound"',
            '"branch_authenticated"',
        ):
            self.assertIn(contract, self.worker)
        for executed in (
            "resolved diagnostic correction stops before the final derivative ladder",
            "truncation and resolution reject a materially displaced root",
            "seed path keeps its independent seed and rejects a wrong root",
            "insufficient diagnostic evidence escalates fail closed",
            "authenticated determinant reuse requires exact scientific inputs",
        ):
            self.assertIn(executed, self.fd_spec)

    def test_seed_path_keeps_its_independent_seed_and_diagnostic_role(
        self,
    ) -> None:
        result_fields = self._function_slice("result_fields", "evaluate_request")
        alternate = result_fields.index(
            'alternate = omega + Complex{T}(T("0.00025"), T("0.000125"))'
        )
        seed_phase = result_fields.index('"SEED-PATH"', alternate)
        independent = result_fields.index(
            'seed_kind="INDEPENDENT_SEED_PATH"', seed_phase
        )
        diagnostic_role = result_fields.index(
            "solve_role=DIAGNOSTIC_CONSISTENCY", seed_phase
        )
        self.assertLess(alternate, seed_phase)
        self.assertLess(seed_phase, independent)
        self.assertLess(seed_phase, diagnostic_role)

    def test_primary_stages_h_and_authenticated_h_over_two_before_full_escalation(
        self,
    ) -> None:
        for contract in (
            "@enum RootAuthenticationMode",
            "STAGED_FULL_AUTHENTICATION",
            "FULL_AUTHENTICATION_ESCALATION",
            "DIAGNOSTIC_CONSISTENCY_AUTHENTICATION",
            "function solve_staged_primary_authentication(",
            "function solve_full_authentication(",
            "STAGED_NEWTON_NOT_CONVERGED",
            "STAGED_NEWTON_DERIVATIVE_MISSING",
            "STAGED_DETERMINANT_ERROR_MODEL_UNAVAILABLE",
            "STAGED_NEWTON_DERIVATIVE_INVALID",
            "STAGED_DERIVATIVE_LOWER_BOUND_UNRESOLVED",
            "STAGED_CORRECTION_UPPER_BOUND_ABOVE_TOLERANCE",
        ):
            self.assertIn(contract, self.worker)

        staged = self._function_slice(
            "solve_staged_primary_authentication", "solve_diagnostic_consistency"
        )
        self.assertIn("bounded_newton", staged)
        self.assertIn("authenticated_determinant_progress", staged)
        self.assertIn('"staged derivative h/2"', staged)
        self.assertNotIn('"final derivative 2h"', staged)
        self.assertNotIn('"final derivative ih"', staged)
        self.assertIn("raw_step_disagreement_abs", staged)
        self.assertIn("guarded_step_disagreement_abs", staged)
        self.assertIn(
            "TODO: [HUMAN MATH REVIEW REQUIRED - justify the staged "
            "derivative-disagreement safety multiplier before final merge]",
            staged,
        )

        full = self._function_slice(
            "solve_full_authentication", "solve_staged_primary_authentication"
        )
        self.assertIn("solve_once(", full)
        self.assertIn("authenticate_controls=true", full)
        solve_once = self._function_slice("solve_once", "solve_full_authentication")
        self.assertIn("evaluate_derivative_step_ladder(", solve_once)
        for retained in (
            '"final derivative h/2"',
            '"final derivative 2h"',
            '"final derivative ih"',
        ):
            self.assertIn(retained, self.worker)

    def test_staged_and_diagnostic_progress_events_are_literal_and_registered(
        self,
    ) -> None:
        for event in (
            "primary_staged_authentication_started",
            "primary_staged_derivative_accepted",
            "primary_staged_derivative_rejected",
            "primary_staged_authentication_completed",
            "primary_full_authentication_escalated",
            "primary_full_authentication_completed",
            "diagnostic_consistency_started",
            "diagnostic_consistency_completed",
            "diagnostic_full_authentication_escalated",
            "diagnostic_full_authentication_completed",
        ):
            self.assertIn(f'progress_emit("{event}"', self.worker)

    def test_staged_evidence_never_fabricates_unexecuted_directions(self) -> None:
        authentication = self._function_slice(
            "root_authentication_text", "solve_once"
        )
        self.assertIn('"authentication_strategy"', authentication)
        self.assertIn('"derivative_evidence"', authentication)
        self.assertIn('"real_double"', authentication)
        self.assertIn('"imaginary"', authentication)
        staged = self._function_slice(
            "solve_staged_primary_authentication", "solve_diagnostic_consistency"
        )
        constructor_start = staged.index(
            "root_authentication = RootAuthentication{T}("
        )
        constructor_end = staged.index("result = (", constructor_start)
        constructor = staged[constructor_start:constructor_end]
        self.assertIn(
            "STAGED_REAL_AXIS_AUTHENTICATION_STRATEGY_ID",
            constructor,
        )
        self.assertRegex(
            constructor,
            r"derivative_real_half,\s+nothing,\s+nothing,",
        )
        self.assertIn('"derivative_real_double" => nothing', staged)
        self.assertIn('"derivative_imaginary" => nothing', staged)

    def test_primary_authentication_tightens_only_exact_frequencies(self) -> None:
        for contract in (
            "function tight_control_request(",
            "function authenticated_determinant_progress(",
            "base_frequency == tight_frequency",
            "abs(base.value - tight.value)",
            "solve_role=FULL_AUTHENTICATION",
            "remember_authenticated_determinant!(",
        ):
            self.assertIn(contract, self.worker)
        refined = self._function_slice("refined_request", "conditioning_response")
        self.assertNotIn("authenticated_determinant_progress(", refined)
        self.assertIn("return tight_control_request(T, request)", refined)

    def test_final_authentication_leaves_exterior_derivative_path_unchanged(
        self,
    ) -> None:
        solve_once = self._function_slice("solve_once", "solve_phase")
        self.assertIn(
            "horizon_authentication = authenticate_controls &&", solve_once
        )
        self.assertIn("root_evaluation.error_breakdown !== nothing", solve_once)
        self.assertIn(
            "authenticate_controls=horizon_authentication", solve_once
        )

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
        coordinate_solver = (
            REPO_ROOT
            / "src/windows_solver/data/julia"
            / "GeneralizedSasakiNakamura.jl/src/Homogeneous"
            / "ComplexFrequencies.jl"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "p = (a=a, beta=beta, sign=sign, rs_mp=rs_mp)",
            coordinate_solver,
        )

    def _function_slice(self, name: str, next_name: str) -> str:
        start = self.worker.index(f"function {name}(")
        end = self.worker.index(f"function {next_name}(", start + 1)
        return self.worker[start:end]


if __name__ == "__main__":
    unittest.main()
