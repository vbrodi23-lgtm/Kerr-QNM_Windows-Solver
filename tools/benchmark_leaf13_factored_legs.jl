#!/usr/bin/env julia

# Temporary performance-only diagnostic for PR #44.
#
# This intentionally bypasses only the production-readiness assertion. It uses
# the package's existing post-readiness executor, authentic preparations,
# production ODE algorithm/tolerances, carrier transition, and ODE telemetry.
# It does not evaluate a determinant or support a mathematical-validity claim.

const REPOSITORY_ROOT = normpath(joinpath(@__DIR__, ".."))
include(joinpath(
    REPOSITORY_ROOT,
    "src",
    "windows_solver",
    "data",
    "julia",
    "m02_worker.jl",
))

const BENCHMARK_PREFIX = "@@LEAF13_FACTORED_BENCHMARK@@"
const HISTORICAL_ACTIVE_LEG_RHS_EVALUATIONS = 1_960_000

function emit_benchmark(kind::AbstractString; payload=Dict{String,Any}())
    println(BENCHMARK_PREFIX * JSON.json(Dict{String,Any}(
        "schema" => "windows-solver.leaf13-factored-benchmark/1",
        "kind" => String(kind),
        "evidence_scope" => "performance-only-not-math-validation",
        "payload" => payload,
    )))
    flush(stdout)
end

function benchmark_request()
    digest = repeat("0", 64)
    return Dict{String,Any}(
        "schema_version" => 1,
        "operation" => "leaf13-factored-leg-benchmark",
        "job_id" => "benchmark:221:0.95:horizon-admittance",
        "leaf_id" => "leaf-13-221-0.95-horizon-admittance",
        "role" => "primary",
        "job_policy_sha256" => digest,
        "backend_identity_sha256" => digest,
        "refinement_level" => 0,
        "s" => -2,
        "ell" => 2,
        "m" => 2,
        "n" => 1,
        "spin" => "0.95",
        "omega_re" => "0.744582472105827",
        "omega_im" => "-0.1596868021342034",
        "angular_A_re" => "1.7454647938369572",
        "angular_A_im" => "0.5746522102718097",
        "mechanism_id" => "horizon-admittance",
        "precision_digits" => 80,
        "working_precision_bits" => 298,
        "request_sha256" => digest,
        "readout_radius" => "6.0",
        "ode_relative_tolerance" => "1e-18",
        "ode_absolute_tolerance" => "1e-20",
        "homogeneous_ode_relative_tolerance" => "1e-18",
        "homogeneous_ode_absolute_tolerance" => "1e-20",
        "coordinate_ode_relative_tolerance" => "1e-18",
        "coordinate_ode_absolute_tolerance" => "1e-20",
        "endpoint_series_order" => 28,
        "support_subinterval_count" => 256,
        "angular_pad" => 18,
        "rho_in" => "-5000",
        "rho_out" => "5000",
        "horizon_rho_inner_min" => "-100",
        "horizon_endpoint_rho_candidates" =>
            ["-10", "-25", "-50", "-75", "-100"],
        "horizon_maximum_endpoint_distance" => "0.1",
        "determinant_error_safety_factor" => "64",
        "frequency_step" => "1e-6",
        "frequency_step_minimum" => "1e-12",
        "frequency_step_maximum" => "1e-3",
        "root_correction_tolerance" => "1e-18",
        "branch_enclosure_radius_abs" => "0.005",
        "max_newton_iterations" => 16,
        "resource_policy_schema" =>
            "windows-solver.execution-resource-policy/1",
        "resource_policy_version" => 1,
        "resource_policy_sha256" => digest,
        "worker_request_wall_clock_seconds" => 1800,
        "cooperative_request_deadline_seconds" => 1500,
        "homogeneous_ode_maxiters" => 10^7,
        "max_accepted_steps_per_homogeneous_leg" => 3_000_000,
        "max_rhs_evaluations_per_homogeneous_leg" => 3_000_000,
        "homogeneous_leg_wall_clock_seconds" => 1200,
        "coordinate_stall_rhs_threshold" => 200_000,
        "coordinate_stall_minimum_span_fraction" => "1e-6",
        "coordinate_stall_minimum_step_fraction" => "1e-12",
        "homogeneous_representation" =>
            HORIZON_HOMOGENEOUS_REPRESENTATION_ID,
        "asymptotic_series_evaluation" =>
            ASYMPTOTIC_SERIES_EVALUATION_ID,
        "conditioning_diagnostics" => CONDITIONING_DIAGNOSTICS_ID,
        "branch_convention" => BRANCH_CONVENTION_ID,
        "radial_derivative_convention" =>
            RADIAL_DERIVATIVE_CONVENTION_ID,
        "regular_remainder_contract" => REGULAR_REMAINDER_CONTRACT_ID,
        "factored_remainder_state_convention" =>
            FACTORED_REMAINDER_STATE_CONVENTION_ID,
        "reliable_digit_safety_margin" =>
            string(RELIABLE_DIGIT_SAFETY_MARGIN),
        "required_digit_guard" => string(REQUIRED_DIGIT_GUARD),
        "human_math_review_receipt_status" =>
            HUMAN_MATH_REVIEW_RECEIPT_STATUS,
        "human_math_review_receipt_sha256" =>
            HUMAN_MATH_REVIEW_RECEIPT_SHA256,
        "independent_reference_fixture_receipt_status" =>
            INDEPENDENT_REFERENCE_FIXTURE_RECEIPT_STATUS,
        "independent_reference_fixture_receipt_sha256" =>
            INDEPENDENT_REFERENCE_FIXTURE_RECEIPT_SHA256,
        "determinant_family" => HORIZON_DETERMINANT_FAMILY_ID,
        "scattering_diagnostics_applicable" => true,
        "scattering_coefficient_extraction" =>
            HORIZON_BASIS_AT_MATCH_EXTRACTION_ID,
        "horizon_determinant_chart" =>
            HORIZON_DETERMINANT_NORMALISATION_ID,
        "scattering_chart_safety_factor" =>
            string(SCATTERING_CHART_SAFETY_FACTOR),
        "scattering_column_convention" =>
            SCATTERING_COLUMN_CONVENTION_ID,
        "determinant_convention" => HORIZON_DETERMINANT_CONVENTION_ID,
        "determinant_normalisation" =>
            HORIZON_DETERMINANT_NORMALISATION_ID,
        "horizon_contour" => REAL_INNER_HORIZON_CONTOUR_ID,
        "determinant_error_model" => VERIFIED_ENDPOINT_ERROR_MODEL_ID,
    )
end

function preparation_payload(preparation)
    assessment = preparation.assessment
    regularity = preparation.initial_condition.regularity
    return Dict{String,Any}(
        "branch" => string(preparation.branch),
        "adequate" => assessment.adequate,
        "reason" => assessment.reason,
        "predicted_reliable_digits" =>
            string(assessment.predicted_reliable_digits),
        "required_reliable_digits" => string(assessment.required_digits),
        "maximum_series_evaluation_digits_lost" =>
            string(assessment.maximum_series_evaluation_digits_lost),
        "maximum_recurrence_digits_lost" =>
            string(assessment.maximum_recurrence_digits_lost),
        "maximum_last_term_ratio" =>
            string(assessment.maximum_last_term_ratio),
        "regular_remainder_finite" => regularity.finite,
        "regular_remainder_norm" => string(regularity.remainder_norm),
        "contour_angle_deformation_maximum_absolute" =>
            string(preparation.contour_deformation.maximum_absolute),
    )
end

function solution_payload(solution, elapsed_seconds::Float64)
    diagnostics = solution.diagnostics
    return Dict{String,Any}(
        "ode_leg" => diagnostics.ode_leg,
        "rhs_evaluations" =>
            diagnostics.factored_homogeneous_rhs_evaluations,
        "accepted_steps" => diagnostics.accepted_steps,
        "rejected_steps" => diagnostics.rejected_steps,
        "elapsed_seconds" => elapsed_seconds,
        "maximum_remainder_state_norm" =>
            string(diagnostics.maximum_remainder_state_norm),
        "minimum_remainder_state_norm" =>
            string(diagnostics.minimum_remainder_state_norm),
        "maximum_absolute_real_carrier_log" =>
            string(diagnostics.maximum_absolute_real_carrier_log),
        "endpoint_Y_abs" => string(abs(solution.endpoint.Y)),
        "endpoint_Yrho_abs" => string(abs(solution.endpoint.Yrho)),
        "endpoint_only_saved_points" =>
            diagnostics.endpoint_only_saved_points,
        "contour_angle_deformation_maximum_absolute" =>
            string(diagnostics.contour_deformation.maximum_absolute),
    )
end

function execute_leg(
    request,
    spectral,
    contour,
    preparation,
    start_rho,
    stop_rho,
    counter;
    initial_state=preparation.initial_condition.state,
    initial_carrier=preparation.initial_condition.carrier,
    ode_leg,
)
    observation_factory = (leg, tspan, algorithm) ->
        ode_observation_factory(request, leg, tspan, algorithm)
    started = time_ns()
    solution = CF._execute_factored_endpoint_after_readiness(
        spectral,
        contour,
        preparation,
        start_rho,
        stop_rho;
        initial_state=initial_state,
        initial_carrier=initial_carrier,
        odealgo=AutoVern9(Rosenbrock23(autodiff=false)),
        reltol=parse_real(BigFloat, request, "ode_relative_tolerance"),
        abstol=parse_real(BigFloat, request, "ode_absolute_tolerance"),
        ode_maxiters=parse_integer(request, "homogeneous_ode_maxiters"),
        ode_observation_factory=observation_factory,
        ode_solution_observer=observe_ode_solution,
        ode_exception_passthrough=error ->
            error isa ODEResourceLimit || error isa ODESolverFailure,
        ode_leg=ode_leg,
        factored_homogeneous_rhs_counter=counter,
    )
    elapsed_seconds = (time_ns() - started) / 1.0e9
    emit_benchmark("leg_completed"; payload=solution_payload(
        solution, elapsed_seconds
    ))
    return solution
end

function run_benchmark()
    request = benchmark_request()
    validate_regularised_gsn_policy(request)
    bits = parse_integer(request, "working_precision_bits")
    return setprecision(BigFloat, bits) do
        REQUEST_STARTED_NS[] = time_ns()
        ACTIVE_PHASE_STARTED_NS[] = REQUEST_STARTED_NS[]
        ACTIVE_PHASE[] = "PERFORMANCE_ONLY"
        ACTIVE_NEWTON_INDEX[] = 0
        DETERMINANT_INDEX_REQUEST[] = 0
        DETERMINANT_INDEX_PHASE[] = 0
        LAST_DETERMINANT_PURPOSE[] = "none"
        LAST_ODE_SNAPSHOT[] = nothing

        omega = parse_complex(
            BigFloat, request, "omega_re", "omega_im"
        )
        emit_benchmark("benchmark_started"; payload=Dict{String,Any}(
            "mode" => "221",
            "spin" => request["spin"],
            "precision_digits" => request["precision_digits"],
            "working_precision_bits" => bits,
            "omega_re" => string(real(omega)),
            "omega_im" => string(imag(omega)),
            "historical_active_leg_rhs_evaluations" =>
                HISTORICAL_ACTIVE_LEG_RHS_EVALUATIONS,
            "production_readiness_assertion_bypassed" => true,
        ))

        context = build_determinant_request_context(BigFloat, request, omega)
        spectral = build_sample_spectral_context(
            BigFloat, request, omega, context
        )
        contour = build_worker_contour_context(
            BigFloat,
            request,
            spectral,
            parse_real(BigFloat, request, "readout_radius"),
            "Xup-benchmark",
        )
        required_digits = required_reliable_digits(BigFloat, request)
        preparations = CF.prepare_factored_horizon_determinant_branches(
            spectral, contour, required_digits
        )
        CF._assert_horizon_preparation_provenance(
            spectral, contour, preparations
        )
        for preparation in (
            preparations.infinity_outgoing,
            preparations.horizon_ingoing,
            preparations.horizon_outgoing,
        )
            emit_benchmark("preflight_completed"; payload=
                preparation_payload(preparation))
        end
        CF.assert_factored_preflights_adequate(
            preparations.infinity_outgoing,
        )
        emit_benchmark("transition_seeded_inner_authorised"; payload=
            Dict{String,Any}(
                "uses_horizon_endpoint_initial_state" => false,
                "horizon_endpoint_preflight_adequate" =>
                    preparations.horizon_ingoing.assessment.adequate,
                "horizon_endpoint_preflight_bypassed" =>
                    !preparations.horizon_ingoing.assessment.adequate,
                "claim_ceiling" => "performance-only",
            ))

        counter = Ref(0)
        outer = execute_leg(
            request,
            spectral,
            contour,
            preparations.infinity_outgoing,
            contour.rho_out,
            zero(contour.rho_out),
            counter;
            ode_leg="Xup_outer_to_match",
        )
        transition = CF.change_factored_infinity_to_horizon_at_match(
            spectral, contour, outer
        )
        CF._assert_carrier_transition_provenance(
            spectral, contour, transition
        )
        emit_benchmark("carrier_transition_completed"; payload=Dict{String,Any}(
            "X_reconstruction_error" =>
                string(transition.diagnostics.X_reconstruction_error),
            "Xrho_reconstruction_error" =>
                string(transition.diagnostics.Xrho_reconstruction_error),
            "reconstruction_tolerance" =>
                string(transition.reconstruction_tolerance),
        ))
        inner = execute_leg(
            request,
            spectral,
            contour,
            preparations.horizon_ingoing,
            zero(contour.rho_in),
            contour.rho_in,
            counter;
            initial_state=transition.state,
            initial_carrier=transition.target_carrier,
            ode_leg="Xup_match_to_inner",
        )

        inner_rhs = inner.diagnostics.factored_homogeneous_rhs_evaluations
        speedup = HISTORICAL_ACTIVE_LEG_RHS_EVALUATIONS / inner_rhs
        verdict = if speedup >= 10
            "decisive-cost-collapse"
        elseif speedup >= 2
            "material-but-not-decisive-improvement"
        else
            "performance-premise-not-supported"
        end
        emit_benchmark("benchmark_completed"; payload=Dict{String,Any}(
            "outer_rhs_evaluations" =>
                outer.diagnostics.factored_homogeneous_rhs_evaluations,
            "inner_rhs_evaluations" => inner_rhs,
            "total_rhs_evaluations" => counter[],
            "historical_active_leg_rhs_evaluations" =>
                HISTORICAL_ACTIVE_LEG_RHS_EVALUATIONS,
            "historical_to_factored_inner_rhs_ratio" => speedup,
            "performance_verdict" => verdict,
        ))
        return nothing
    end
end

try
    run_benchmark()
catch failure
    payload = Dict{String,Any}(
        "error_type" => string(typeof(failure)),
        "message" => sprint(showerror, failure),
    )
    LAST_ODE_SNAPSHOT[] === nothing ||
        (payload["last_ode_snapshot"] = LAST_ODE_SNAPSHOT[])
    emit_benchmark("benchmark_failed"; payload=payload)
    showerror(stderr, failure, catch_backtrace())
    println(stderr)
    exit(1)
end
