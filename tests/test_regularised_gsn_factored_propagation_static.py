from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
COMPLEX_FREQUENCIES_SOURCE = REPO_ROOT / (
    "src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/src/"
    "Homogeneous/ComplexFrequencies.jl"
)
SOLUTIONS_SOURCE = REPO_ROOT / (
    "src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/src/"
    "Homogeneous/Solutions.jl"
)
JULIA_SPEC = REPO_ROOT / (
    "src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/test/"
    "factored_propagation_spec.jl"
)
REAL_INNER_HORIZON_SPEC = REPO_ROOT / (
    "src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/test/"
    "real_inner_horizon_spec.jl"
)
WORKER_SOURCE = REPO_ROOT / "src/windows_solver/data/julia/m02_worker.jl"
CI_WORKFLOW = REPO_ROOT / ".github/workflows/ci.yml"
M02_MANIFEST_SEED = REPO_ROOT / (
    "src/windows_solver/data/julia/m02_project/Manifest.seed.toml"
)


class RegularisedGsnFactoredPropagationSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = COMPLEX_FREQUENCIES_SOURCE.read_text(encoding="utf-8")
        cls.solutions = SOLUTIONS_SOURCE.read_text(encoding="utf-8")
        cls.spec = JULIA_SPEC.read_text(encoding="utf-8")
        cls.real_inner_spec = REAL_INNER_HORIZON_SPEC.read_text(
            encoding="utf-8"
        )
        cls.worker = WORKER_SOURCE.read_text(encoding="utf-8")
        cls.workflow = CI_WORKFLOW.read_text(encoding="utf-8")
        cls.manifest_seed = M02_MANIFEST_SEED.read_text(encoding="utf-8")

    def test_ci_runs_the_complete_vendored_suite_from_the_pinned_project(
        self,
    ) -> None:
        self.assertIn(
            "M02_PROJECT_SEED: src/windows_solver/data/julia/m02_project",
            self.workflow,
        )
        self.assertIn(
            'read(joinpath(seed_project, "Manifest.seed.toml"), String)',
            self.workflow,
        )
        self.assertIn("let manifest = read", self.workflow)
        self.assertIn(
            'manifest = replace(manifest, seed_path => pinned_path)',
            self.workflow,
        )
        self.assertIn('--project="$M02_PROJECT"', self.workflow)
        self.assertNotIn("Pkg.develop(", self.workflow)
        self.assertNotIn("Pkg.resolve()", self.workflow)
        self.assertIn(
            'include(joinpath(ENV["GSN_PROJECT"], "test", '
            '"runtests.jl"))',
            self.workflow,
        )
        self.assertNotIn("Pkg.test()", self.workflow)

        gsn_entry = re.search(
            r"\[\[deps\.GeneralizedSasakiNakamura\]\]\n"
            r"(?P<body>.*?)(?=\n\[\[deps\.)",
            self.manifest_seed,
            re.DOTALL,
        )
        self.assertIsNotNone(gsn_entry)
        gsn_body = gsn_entry.group("body")
        for dependency in ("HDF5", "LsqFit", "Printf", "Serialization"):
            self.assertIn(f'"{dependency}"', gsn_body)
        self.assertIn('version = "0.9.0"', gsn_body)
        self.assertIn(
            'path = "../vendor/GeneralizedSasakiNakamura.jl"',
            gsn_body,
        )
        for package in ("HDF5", "LsqFit"):
            self.assertIn(f"[[deps.{package}]]", self.manifest_seed)

    def test_contexts_are_typed_and_bind_frozen_cell_to_sample_deformation(
        self,
    ) -> None:
        for contract in (
            "struct ContourAngleDeformation{T<:AbstractFloat}",
            "struct HomogeneousSpectralContext{T<:AbstractFloat}",
            "precision_digits::Int",
            "precision_bits::Int",
            "endpoint_order::Int",
            "series::AsymptoticSeriesBundle{T}",
            "contract::RegularRemainderContract",
            "convention::GSNBranchConvention{T}",
            "frozen_convention::GSNBranchConvention{T}",
            "frozen_branch_cell::GSNBranchCell",
            "struct ComplexContourContext{T<:AbstractFloat,F}",
            "infinity_tangent::Complex{T}",
            "horizon_tangent::Complex{T}",
            "radius_from_rho::F",
            "convention::GSNBranchConvention{T}",
            "build_homogeneous_spectral_context",
            "build_contour_context",
            "stable_horizon_geometry",
            "gsn_branch_convention",
            "assert_no_branch_crossing",
            "contour_angle_deformation",
        ):
            self.assertIn(contract, self.source)

        contour_builder = self._function("build_contour_context")
        self.assertIn("_with_factored_precision(", contour_builder)
        self.assertIn("rstar_from_r(", contour_builder)
        self.assertIn("canonical_rstar_match", contour_builder)
        for precision_witness in (
            "typed_match_radius, spectral.precision_bits",
            "infinity_tangent, spectral.precision_bits",
            "horizon_tangent, spectral.precision_bits",
        ):
            self.assertIn(precision_witness, contour_builder)

    def test_prepare_records_own_whole_b3_initial_condition_and_assessment(
        self,
    ) -> None:
        for contract in (
            "struct FactoredEndpointPreparation{T<:AbstractFloat}",
            "initial_condition::FactoredInitialCondition{T}",
            "assessment::AsymptoticConditioningAssessment{T}",
            "required_digits::T",
            "prepare_factored_infinity_outgoing",
            "prepare_factored_horizon_ingoing",
            "prepare_factored_horizon_outgoing",
            "struct HorizonDeterminantPreparation{T<:AbstractFloat}",
            "prepare_factored_horizon_determinant_branches",
            "struct ExteriorDeterminantPreparation{T<:AbstractFloat}",
            "prepare_factored_exterior_determinant_branches",
            "assert_factored_preflights_adequate",
        ):
            self.assertIn(contract, self.source)

        preparation = self._function("_prepare_factored_endpoint")
        initial_condition_builder = self._function(
            "_build_factored_initial_condition"
        )
        for batch_api in (
            "factored_infinity_outgoing_initialconditions(",
            "factored_horizon_ingoing_initialconditions(",
            "factored_horizon_outgoing_initialconditions(",
            "assess_asymptotic_preflight(",
        ):
            target = preparation if batch_api == "assess_asymptotic_preflight(" else initial_condition_builder
            self.assertIn(batch_api, target)
        for legacy_hot_path in (
            "outgoing_coefficient_at_inf(",
            "ingoing_coefficient_at_hor(",
            "outgoing_coefficient_at_hor(",
            "fansatz(",
            "gansatz(",
        ):
            self.assertNotIn(legacy_hot_path, preparation)

    def test_single_canonical_factored_rhs_has_exact_transformation(self) -> None:
        definitions = re.findall(
            r"(?m)^function factored_GSN_linear_eqn!\(", self.source
        )
        self.assertEqual(len(definitions), 1)
        rhs = self._function("factored_GSN_linear_eqn!")
        for formula in (
            "F_rho = parameters.tangent *",
            "U_rho = parameters.tangent^2 *",
            "q = carrier_log_derivative(parameters.carrier)",
            "q_rho = carrier_log_derivative_derivative(parameters.carrier)",
            "du[1] = state[2]",
            "_factored_transformed_rhs_second(",
            "factored_homogeneous_rhs_evaluations[] += 1",
        ):
            self.assertIn(formula, rhs)
        self.assertNotRegex(rhs, r"(?:maximum|abs)\s*\(\s*state")

        algebra = self._function("_factored_transformed_rhs_second")
        self.assertIn("(F_rho - 2 * q) * Yrho", algebra)
        self.assertIn("U_rho + F_rho * q - q_rho - q^2", algebra)
        self.assertIn("synthetic nonzero q_rho transformed algebra", self.spec)

    def test_inadequate_preflight_precedes_observers_and_rhs(self) -> None:
        solve_endpoint = self._function("solve_factored_endpoint")
        provenance = solve_endpoint.index("_assert_preparation_provenance(")
        preflight = solve_endpoint.index("_assert_factored_preflight_adequate(")
        execute = solve_endpoint.index(
            "_execute_factored_endpoint_after_readiness("
        )
        self.assertLess(provenance, preflight)
        self.assertLess(preflight, execute)
        self.assertNotIn(
            "assert_regularised_gsn_production_ready()", solve_endpoint
        )
        match_to_inner = self._function(
            "solve_factored_horizon_match_to_inner"
        )
        self.assertNotIn(
            "assert_regularised_gsn_production_ready()", match_to_inner
        )
        self.assertIn("INSUFFICIENT_ASYMPTOTIC_PRECISION", self.source)
        self.assertIn(
            'FACTORED_HOMOGENEOUS_ODE_SCOPE_ID = "factored-homogeneous-gsn/v1"',
            self.source,
        )
        self.assertIn(
            "factored_homogeneous_rhs_evaluations::Int", self.source
        )
        self.assertNotIn("readiness_gate", solve_endpoint)

        failure_translation = self._function(
            "_translate_factored_failure"
        )
        self.assertIn("error.reason", failure_translation)
        self.assertNotIn(
            "error.reason == PHYSICAL_SINGULAR_LIMIT",
            failure_translation,
        )
        self.assertNotIn(
            "error.reason == ALGEBRAIC_REPRESENTATION_SINGULAR",
            failure_translation,
        )

        provenance_body = self._function("_assert_preparation_provenance")
        self.assertIn("_factored_initial_conditions_match_exactly(", provenance_body)
        self.assertIn("_assessments_match_exactly(", provenance_body)
        self.assertNotIn("isequal(refreshed, preparation.assessment)", provenance_body)

        execute_body = self._function(
            "_execute_factored_endpoint_after_readiness"
        )
        self.assertIn("_begin_ode_observation(", execute_body)
        self.assertIn("ODEProblem(factored_GSN_linear_eqn!", execute_body)
        self.assertIn("solve(", execute_body)

    def test_exact_solver_controls_and_external_first_callback_composition(
        self,
    ) -> None:
        self.assertIn(
            "AutoVern9(Rosenbrock23(autodiff=false))", self.source
        )
        execute = self._function("_execute_factored_endpoint_after_readiness")
        for control in (
            "maxiters=ode_maxiters",
            "reltol=reltol",
            "abstol=abstol",
            "tstops=[stop_rho]",
            "save_everystep=false",
            "save_start=false",
            "save_end=true",
            "dense=false",
        ):
            self.assertIn(control, execute)
        composition = self._function("_combine_factored_callbacks")
        self.assertIn(
            "CallbackSet(external_callback, internal_callback)", composition
        )
        self.assertIn("ode_solution_observer", execute)
        self.assertNotIn("return solution", execute)

    def test_external_ode_control_exceptions_have_typed_passthrough(self) -> None:
        execute = self._function("_execute_factored_endpoint_after_readiness")
        self.assertIn("ode_exception_passthrough", execute)
        self.assertIn("_throw_or_wrap_factored_ode_failure(", execute)

        policy = self._function("_factored_ode_exception_disposition")
        self.assertIn("ode_exception_passthrough(error)", policy)
        self.assertIn("passthrough isa Bool", policy)
        self.assertIn("PASSTHROUGH_ODE_EXCEPTION", policy)
        self.assertIn("WRAP_ODE_EXCEPTION", policy)

        translator = self._function("_throw_or_wrap_factored_ode_failure")
        passthrough = translator.index("PASSTHROUGH_ODE_EXCEPTION")
        original = translator.index("throw(error)")
        wrapped = translator.index("FACTORED_ODE_FAILURE")
        self.assertLess(passthrough, original)
        self.assertLess(original, wrapped)

        for name in (
            "solve_factored_endpoint",
            "solve_factored_horizon_match_to_inner",
            "solve_factored_xup_scattering_endpoint",
            "solve_factored_exterior_matches",
        ):
            body = self._function(name)
            self.assertIn("ode_exception_passthrough", body)
        self.assertIn(
            "external ODE control exceptions preserve their typed receipt",
            self.spec,
        )

    def test_canonical_paths_and_match_conversion_are_package_owned(self) -> None:
        for public_api in (
            "solve_factored_infinity_outer_to_match",
            "change_factored_infinity_to_horizon_at_match",
            "solve_factored_horizon_match_to_inner",
            "solve_factored_xup_scattering_endpoint",
            "solve_factored_xin_to_match",
            "solve_factored_xup_to_match",
            "solve_factored_exterior_matches",
            "reconstruct_factored_match_state",
        ):
            self.assertIn(f"function {public_api}(", self.source)

        conversion = self._function("reconstruct_factored_match_state")
        self.assertIn("spectral::HomogeneousSpectralContext", conversion)
        self.assertIn("_assert_carrier_provenance(", conversion)
        self.assertIn("raw = reconstruct_state(", conversion)
        self.assertIn("dX_drstar = raw.Xrho / tangent", conversion)
        self.assertIn("raw.Xrho", conversion)
        self.assertIn("radial_derivative_convention", conversion)

        change = self._function(
            "change_factored_infinity_to_horizon_at_match"
        )
        self.assertIn("change_carrier(", change)
        self.assertIn("carrier_change_diagnostics(", change)
        self.assertIn("zero(T)", change)

    def test_horizon_geometry_screening_is_separate_from_series_preflight(
        self,
    ) -> None:
        for contract in (
            "HorizonEndpointGeometryCandidate",
            "horizon_endpoint_geometry_candidates",
        ):
            self.assertIn(f"export {contract}", self.source)

        geometry_struct = self.source[
            self.source.index("struct HorizonEndpointGeometryCandidate") :
            self.source.index("struct HorizonEndpointCandidate")
        ]
        for forbidden in (
            "SeriesEvaluation",
            "AsymptoticConditioningAssessment",
            "ingoing",
            "outgoing",
        ):
            self.assertNotIn(forbidden, geometry_struct)

        geometry = self._function("horizon_endpoint_geometry_candidates")
        self.assertIn("within_maximum_distance", geometry)
        self.assertNotIn("evaluate_horizon_asymptotic_series(", geometry)
        self.assertNotIn("assess_asymptotic_preflight(", geometry)

        series = self._function("horizon_endpoint_candidates")
        self.assertIn(
            "geometry_candidates::Vector{HorizonEndpointGeometryCandidate{T}}",
            series,
        )
        # Series evaluation has exactly one owner. The order ladder evaluates a
        # series per candidate radius per order, so the candidate loop must
        # reach it only through the prefix search rather than calling the
        # evaluator itself; two call sites would let one of them escape the
        # radial gate below.
        self.assertNotIn("evaluate_horizon_asymptotic_series(", series)
        prefix_search = self._function(
            "select_horizon_endpoint_best_prefix"
        )
        self.assertIn(
            "evaluate_horizon_asymptotic_series(", prefix_search
        )
        self.assertIn("assess_asymptotic_preflight(", prefix_search)

        radial_gate = series.index("_geometry_candidate_adequate(")
        ingoing_series = series.index("_best_prefix_assessment(")
        self.assertLess(radial_gate, ingoing_series)
        # The gate has to abandon the candidate, not merely precede the series.
        # Recording an inadequate geometry and falling through would evaluate
        # both series at a radius the geometry already rejected.
        short_circuit = series.index("continue", radial_gate)
        self.assertLess(short_circuit, ingoing_series)

        selector = self._function("select_verified_horizon_endpoints")
        self.assertIn(
            "candidate.geometry.horizon_distance <= "
            "maximum_horizon_distance",
            selector,
        )

        for behavior in (
            "invalid geometry does not evaluate either horizon series",
            "selector revalidates the configured maximum horizon distance",
            "coordinate identity rejects nonfinite and excessive residuals",
        ):
            self.assertIn(behavior, self.real_inner_spec)

    def test_match_basis_validates_the_declared_real_inner_carrier_tangent(
        self,
    ) -> None:
        basis_struct = self.solutions[
            self.solutions.index("struct CommonCarrierHorizonBasis") :
            self.solutions.index("function build_common_horizon_basis")
        ]
        self.assertIn(
            "carrier_tangent::Union{Nothing,Complex{T}}", basis_struct
        )

        validator_start = self.solutions.index(
            "function _assert_scattering_carrier("
        )
        validator_end = self.solutions.index(
            "struct CommonCarrierHorizonBasis", validator_start
        )
        validator = self.solutions[validator_start:validator_end]
        self.assertIn("carrier_tangent", validator)
        self.assertIn("if carrier_tangent === nothing", validator)
        self.assertIn("PlaneWaveCarrier(", validator)
        self.assertIn(
            "horizon_carrier_with_explicit_tangent(", validator
        )
        self.assertNotRegex(
            validator,
            r"carrier\.q\s*/|/\s*carrier\.wave_number",
        )

        match_builder_start = self.solutions.index(
            "function build_match_horizon_basis("
        )
        match_builder_end = self.solutions.index(
            "function solve_scaled_horizon_basis_at_match(",
            match_builder_start,
        )
        match_builder = self.solutions[
            match_builder_start:match_builder_end
        ]
        self.assertIn("carrier_tangent::Complex{T}", match_builder)
        self.assertIn(
            "carrier_tangent=carrier_tangent", match_builder
        )

        chart_start = self.worker.index("function evaluate_horizon_chart(")
        chart_end = self.worker.index(
            "function determinant_error_breakdown", chart_start
        )
        chart = self.worker[chart_start:chart_end]
        basis_call = chart.index("Solutions.build_match_horizon_basis(")
        tangent_argument = chart.index("inner_contour.tangent", basis_call)
        precision_argument = chart.index("spectral.precision_bits", basis_call)
        self.assertLess(tangent_argument, precision_argument)

        self.assertIn(
            "match-basis column scaling does not move the coefficients",
            self.real_inner_spec,
        )

    def test_all_determinant_branches_are_authenticated_before_adequacy(self) -> None:
        for name, provenance_call, first_solve_call in (
            (
                "solve_factored_xup_scattering_endpoint",
                "_assert_horizon_preparation_provenance(",
                "outer = solve_factored_infinity_outer_to_match(",
            ),
            (
                "solve_factored_exterior_matches",
                "_assert_exterior_preparation_provenance(",
                "xin = solve_factored_xin_to_match(",
            ),
        ):
            body = self._function(name)
            self.assertIn(provenance_call, body)
            provenance = body.index(provenance_call)
            adequacy = body.index("assert_factored_preflights_adequate(")
            first_solve = body.index(first_solve_call)
            self.assertLess(provenance, adequacy)
            self.assertLess(adequacy, first_solve)

        distinct_contours = self._function(
            "assert_factored_exterior_preparations_ready"
        )
        first_provenance = distinct_contours.index(
            "spectral, horizon_contour, horizon_ingoing"
        )
        second_provenance = distinct_contours.index(
            "spectral, infinity_contour, infinity_outgoing"
        )
        adequacy = distinct_contours.index(
            "assert_factored_preflights_adequate("
        )
        self.assertLess(first_provenance, second_provenance)
        self.assertLess(second_provenance, adequacy)

    def test_canonical_carrier_and_typed_failure_provenance_are_load_bearing(
        self,
    ) -> None:
        carrier = self._function("_assert_carrier_provenance")
        carrier_comparison = self._function("_carriers_match_exactly")
        self.assertIn("_canonical_carrier(", carrier)
        for marker in (
            "wave_number",
            "rstar_match",
            "log_at_match",
            ".q",
            "_conventions_match_exactly(",
        ):
            self.assertIn(marker, carrier_comparison)

        build = self._function("build_homogeneous_spectral_context")
        self.assertGreaterEqual(build.count("PHYSICAL_SINGULAR_LIMIT"), 2)
        self.assertIn("iszero(omega)", build)
        self.assertIn("iszero(p_horizon)", build)

        preparation = self._function("_prepare_factored_endpoint")
        precision_check = preparation.index(
            "required_digits, spectral.precision_bits"
        )
        initial_condition = preparation.index("_build_factored_initial_condition(")
        self.assertLess(precision_check, initial_condition)

        for name in (
            "change_factored_infinity_to_horizon_at_match",
            "reconstruct_factored_match_state",
        ):
            body = self._function(name)
            self.assertIn("_translate_factored_failure(", body)

    def test_rhs_and_ode_result_fail_loud_with_exact_diagnostics(self) -> None:
        parameters = self.source[
            self.source.index("struct FactoredGSNParameters") :
            self.source.index("mutable struct _FactoredDiagnosticAccumulator")
        ]
        self.assertIn("precision_bits::Int", parameters)
        self.assertIn("rhs_evaluations_at_start::Int", parameters)

        rhs = self._function("factored_GSN_linear_eqn!")
        for marker in (
            "iszero(q_rho)",
            "_finite_factored_complex(F_rho)",
            "_finite_factored_complex(U_rho)",
            "_finite_factored_complex(du[1])",
            "_finite_factored_complex(du[2])",
            "_factored_rhs_evaluation_count(parameters)",
        ):
            self.assertIn(marker, rhs)
        self.assertNotIn("factored_homogeneous_rhs_evaluations=1", rhs)

        execute = self._function("_execute_factored_endpoint_after_readiness")
        self.assertIn("_assert_successful_factored_ode_result(", execute)
        result_check = self._function(
            "_assert_successful_factored_ode_result"
        )
        self.assertIn("successful_retcode(odesoln)", result_check)
        self.assertIn("hypot(abs(initial_state.Y), abs(initial_state.Yrho))", execute)
        self.assertIn("initial_carrier_log = T(abs(real(carrier_log(", execute)
        self.assertIn("initial_carrier, start_rho", execute)
        self.assertIn("spectral.convention", execute)

        callback = self._function("_factored_internal_callback")
        self.assertIn("hypot(abs(integrator.u[1]), abs(integrator.u[2]))", callback)
        self.assertIn("absolute_real_carrier_log = abs(real(carrier_log(", callback)
        self.assertIn("carrier, integrator.t", callback)

    def test_julia_specs_cover_provenance_precision_and_callback_behavior(self) -> None:
        for marker in (
            "BigFloat provenance is structural and ambient-precision independent",
            "inconsistent match radius and tortoise coordinate are rejected",
            "inadequate evidence is authenticated before promotion",
            "forged carrier fields are rejected",
            "all determinant branches are authenticated before the first ODE",
            "external callback executes before internal diagnostics",
            "nonfinite RHS and unsuccessful retcodes fail loudly",
            "physical zero-frequency limits retain their taxonomy",
        ):
            self.assertIn(marker, self.spec)

    def test_legacy_raw_rhs_is_comparator_only_and_worker_does_not_duplicate_it(
        self,
    ) -> None:
        self.assertIn("Legacy raw-comparator equation", self.source)
        production_start = self.source.index(
            "const HOMOGENEOUS_REPRESENTATION_ID"
        )
        legacy_start = self.source.index("# Legacy raw-comparator equation")
        production = self.source[production_start:legacy_start]
        self.assertNotIn("GSN_linear_eqn(", production)
        self.assertNotRegex(production, r"(?:state|endpoint)\s*\./?=")
        self.assertNotIn("function factored_GSN_linear_eqn!", self.worker)
        self.assertNotRegex(
            self.worker,
            r"(?m)^function\s+solve_factored_endpoint\(",
        )

    def test_exact_math_review_todos_and_derivative_kink_blocker_remain(self) -> None:
        self.assertIn(
            "TODO: [HUMAN MATH REVIEW REQUIRED — verify the branch-specific "
            "plane-wave carriers, the transformed complex-contour GSN equation, "
            "the carrier change at ρ=0, the factored horizon basis, and the "
            "Cinc/Cref determinant chart against the current GSN amplitude and "
            "branch conventions.]",
            self.source,
        )
        self.assertIn(
            "TODO: [HUMAN MATH REVIEW REQUIRED — decide whether derivative "
            "stencils freeze only the GSN branch cell while allowing "
            "frequency-local contour angles, or freeze the full contour tangent "
            "and use q=±i z t_frozen; verify contour-deformation invariance "
            "before production activation.]",
            self.source,
        )

    def test_julia_spec_covers_algebraic_and_blocked_production_contracts(
        self,
    ) -> None:
        for marker in (
            "transformed factored RHS identity",
            "production carriers have q_rho zero",
            "inadequate preflight performs zero factored homogeneous RHS evaluations",
            "adequate preflight executes the public numerical solver",
            "carrier transition executes the public match-to-inner solver",
            "compatible contour deformation and branch crossing rejection",
            "carrier change preserves X and Xrho at rho zero",
            "Float64 and BigFloat branch preparation",
            "external callback is retained before internal diagnostics",
            "endpoint-only result contract",
            "infinity and horizon match derivative conversion",
        ):
            self.assertIn(marker, self.spec)

    def test_legacy_solve_x_signature_has_no_duplicate_keywords(self) -> None:
        match = re.search(
            r"function solve_X_in_rho\((?P<signature>.*?)\n\)",
            self.source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(match)
        signature = match.group("signature")
        keyword_part = signature.split(";", 1)[1]
        names = re.findall(r"\b([A-Za-z_]\w*)\s*=", keyword_part)
        self.assertEqual(names, list(dict.fromkeys(names)))

    def _function(self, name: str) -> str:
        match = re.search(
            rf"(?m)^function {re.escape(name)}(?!\w)(?P<body>.*?)"
            rf"(?=^function |^# Legacy raw-comparator equation|\Z)",
            self.source,
            flags=re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(match, f"missing function {name}")
        return match.group(0)


if __name__ == "__main__":
    unittest.main()
