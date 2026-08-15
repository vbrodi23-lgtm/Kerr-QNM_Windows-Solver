module Leaf13HorizonHarnessCommon

using JSON
using SHA

const REPOSITORY_ROOT = normpath(joinpath(@__DIR__, ".."))
const WORKER_SOURCE = joinpath(
    REPOSITORY_ROOT,
    "src",
    "windows_solver",
    "data",
    "julia",
    "m02_worker.jl",
)

# Loading the worker inside this module makes its package-owned determinant API
# available to both harnesses without executing the worker entry point.
include(WORKER_SOURCE)

export CALIBRATION_STATUS
export CONTROL_PROFILE_LABEL
export DeterminantDiagnostics
export DeterminantErrorBreakdown
export DeterminantEvaluation
export calibration_payload
export determinant_evidence
export derivative_ladder_execution
export fixed_frequency_determinant_execution
export harness_policy_sha256
export leaf13_policy
export leaf13_request
export ode_statistics
export optional_text
export source_runtime_identity
export typed_failure_evidence
export write_receipt_event

const CONTROL_PROFILE_LABEL = "provisional promoted control profile"
const CALIBRATION_STATUS = "UNMEASURED"

const IDENTITY_SOURCE_PATHS = (
    WORKER_SOURCE,
    @__FILE__,
    joinpath(
        REPOSITORY_ROOT,
        "src",
        "windows_solver",
        "data",
        "julia",
        "GeneralizedSasakiNakamura.jl",
        "src",
        "Homogeneous",
        "ComplexFrequencies.jl",
    ),
    joinpath(
        REPOSITORY_ROOT,
        "src",
        "windows_solver",
        "data",
        "julia",
        "GeneralizedSasakiNakamura.jl",
        "src",
        "Homogeneous",
        "FactoredSolutions.jl",
    ),
    joinpath(
        REPOSITORY_ROOT,
        "src",
        "windows_solver",
        "data",
        "julia",
        "GeneralizedSasakiNakamura.jl",
        "src",
        "Homogeneous",
        "Solutions.jl",
    ),
)

optional_text(value) = value === nothing ? nothing : string(value)

function leaf13_policy(
    ; homogeneous_exponent::Int=18,
    coordinate_exponent::Int=18,
    frequency_step::AbstractString="1e-6",
    frequency_step_minimum::AbstractString="1e-12",
    frequency_step_maximum::AbstractString="1e-3",
)
    return Dict{String,Any}(
        "readout_radius" => "6.0",
        "ode_relative_tolerance" => "1e-$(homogeneous_exponent)",
        "ode_absolute_tolerance" => "1e-$(homogeneous_exponent + 2)",
        "homogeneous_ode_relative_tolerance" =>
            "1e-$(homogeneous_exponent)",
        "homogeneous_ode_absolute_tolerance" =>
            "1e-$(homogeneous_exponent + 2)",
        "coordinate_ode_relative_tolerance" =>
            "1e-$(coordinate_exponent)",
        "coordinate_ode_absolute_tolerance" =>
            "1e-$(coordinate_exponent + 2)",
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
        "frequency_step" => String(frequency_step),
        "frequency_step_minimum" => String(frequency_step_minimum),
        "frequency_step_maximum" => String(frequency_step_maximum),
        "root_correction_tolerance" => "1e-18",
        "branch_enclosure_radius_abs" => "0.005",
        "max_newton_iterations" => 16,
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
        "control_profile_label" => CONTROL_PROFILE_LABEL,
        "calibration_status" => CALIBRATION_STATUS,
    )
end

function leaf13_request(
    ; precision_digits::Int=80,
    homogeneous_exponent::Int=18,
    coordinate_exponent::Int=18,
    operation::AbstractString="leaf13-fixed-frequency-determinant",
)
    precision_digits in (80, 120) || throw(ArgumentError(
        "Leaf 13 harness precision must be 80 or 120 digits"
    ))
    digest = repeat("0", 64)
    request = Dict{String,Any}(
        "schema_version" => 1,
        "operation" => String(operation),
        "job_id" => "harness:221:0.95:horizon-admittance",
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
        "amplitude_re" => "0",
        "amplitude_im" => "0",
        "precision_digits" => precision_digits,
        "working_precision_bits" =>
            ceil(Int, precision_digits * log2(10)) + 32,
        "request_sha256" => digest,
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
    )
    merge!(request, leaf13_policy(
        homogeneous_exponent=homogeneous_exponent,
        coordinate_exponent=coordinate_exponent,
    ))
    return request
end

function determinant_evidence(
    ::Type{T}, evaluation::DeterminantEvaluation{T}
) where {T<:AbstractFloat}
    breakdown = evaluation.error_breakdown
    breakdown === nothing && throw(ArgumentError(
        "horizon calibration requires determinant-error evidence"
    ))
    evaluation.error_model_id == VERIFIED_ENDPOINT_ERROR_MODEL_ID ||
        throw(ArgumentError(
            "horizon calibration determinant-error model is invalid"
        ))
    error_abs = determinant_error_abs(T, evaluation)
    return Dict{String,Any}(
        "central_determinant_re" => string(real(evaluation.value)),
        "central_determinant_im" => string(imag(evaluation.value)),
        "endpoint_disagreement_abs" =>
            string(breakdown.endpoint_disagreement_abs),
        "control_disagreement_abs" =>
            optional_text(breakdown.control_disagreement_abs),
        "equivalence_disagreement_abs" =>
            optional_text(breakdown.equivalence_disagreement_abs),
        "precision_disagreement_abs" =>
            optional_text(breakdown.precision_disagreement_abs),
        "safety_factor" => string(breakdown.safety_factor),
        "numerical_error_abs" => string(error_abs),
        "error_model_id" => evaluation.error_model_id,
    )
end

calibration_payload(::Type{T}, evaluation::DeterminantEvaluation{T}) where
    {T<:AbstractFloat} = determinant_evidence(T, evaluation)

function ode_statistics()
    snapshot = LAST_ODE_SNAPSHOT[]
    snapshot === nothing && return nothing
    return Dict{String,Any}(
        "scope" => "last-completed-leg/v1",
        "snapshot" => copy(snapshot),
    )
end

function fixed_frequency_determinant_execution(request)
    validate_regularised_gsn_policy(request)
    bits = parse_integer(request, "working_precision_bits")
    return setprecision(BigFloat, bits) do
        REQUEST_STARTED_NS[] = time_ns()
        ACTIVE_PHASE_STARTED_NS[] = REQUEST_STARTED_NS[]
        ACTIVE_PHASE[] = "HORIZON_HARNESS_FIXED_FREQUENCY"
        ACTIVE_NEWTON_INDEX[] = 0
        DETERMINANT_INDEX_REQUEST[] = 0
        DETERMINANT_INDEX_PHASE[] = 0
        LAST_DETERMINANT_PURPOSE[] = "harness-fixed-frequency"
        LAST_ODE_SNAPSHOT[] = nothing
        omega = parse_complex(BigFloat, request, "omega_re", "omega_im")
        amplitude = parse_complex(
            BigFloat, request, "amplitude_re", "amplitude_im"
        )
        context = build_determinant_request_context(
            BigFloat, request, omega
        )
        started = time_ns()
        evaluation = evaluate_horizon_determinant(
            BigFloat, request, context, omega, amplitude
        )
        return (
            evaluation=evaluation,
            elapsed_seconds=(time_ns() - started) / 1.0e9,
            determinant_evidence=determinant_evidence(
                BigFloat, evaluation
            ),
            ode_statistics=ode_statistics(),
        )
    end
end

function derivative_ladder_execution(request, step_exponents)
    validate_regularised_gsn_policy(request)
    bits = parse_integer(request, "working_precision_bits")
    return setprecision(BigFloat, bits) do
        REQUEST_STARTED_NS[] = time_ns()
        ACTIVE_PHASE_STARTED_NS[] = REQUEST_STARTED_NS[]
        ACTIVE_PHASE[] = "HORIZON_HARNESS_DERIVATIVE"
        LAST_ODE_SNAPSHOT[] = nothing
        omega = parse_complex(BigFloat, request, "omega_re", "omega_im")
        amplitude = parse_complex(
            BigFloat, request, "amplitude_re", "amplitude_im"
        )
        context = build_determinant_request_context(
            BigFloat, request, omega
        )
        results = Dict{String,Any}[]
        for exponent in step_exponents
            h = parse(BigFloat, "1e-$(exponent)") *
                (one(BigFloat) + abs(omega))
            for (axis, offset) in (
                ("real", Complex{BigFloat}(h, zero(BigFloat))),
                ("imaginary", Complex{BigFloat}(zero(BigFloat), h)),
            )
                started = time_ns()
                try
                    derivative, diagnostics, propagated_error_abs =
                        finite_difference_pair(
                            BigFloat,
                            request,
                            context,
                            omega,
                            amplitude,
                            offset,
                            "calibration 1e-$(exponent) $(axis)",
                            omega;
                            axis=axis,
                            authenticate_controls=true,
                        )
                    candidate = derivative_authentication_candidate(
                        derivative,
                        propagated_error_abs,
                        zero(BigFloat),
                        h,
                        axis,
                    )
                    authentication = candidate.authentication
                    authentication === nothing && throw(
                        finite_difference_noise_limit(
                            request,
                            h,
                            h,
                            h,
                            [Dict{String,Any}(
                                "h" => string(h),
                                "axis" => axis,
                                "noise_resolved" => false,
                                "derivative_abs" => string(abs(derivative)),
                                "derivative_error_abs" =>
                                    string(propagated_error_abs),
                                "derivative_uncertainty_abs" => "0.0",
                                "accepted" => false,
                            )],
                        )
                    )
                    push!(results, Dict{String,Any}(
                        "step_exponent" => exponent,
                        "h" => string(h),
                        "axis" => axis,
                        "succeeded" => true,
                        "derivative_re" => string(real(derivative)),
                        "derivative_im" => string(imag(derivative)),
                        "derivative_abs" => string(abs(derivative)),
                        "propagated_error_abs" =>
                            string(propagated_error_abs),
                        "step_disagreement_abs" =>
                            string(authentication.step_disagreement_abs),
                        "derivative_lower_bound_abs" =>
                            string(authentication.lower_bound_abs),
                        "kappa_fd" => string(diagnostics.kappa),
                        "finite_difference_digits_lost" =>
                            string(diagnostics.finite_difference_digits_lost),
                        "saturation_status" =>
                            diagnostics.saturation_status,
                        "elapsed_seconds" =>
                            (time_ns() - started) / 1.0e9,
                        "ode_statistics" => ode_statistics(),
                    ))
                catch failure
                    evidence = typed_failure_evidence(request, failure)
                    push!(results, Dict{String,Any}(
                        "step_exponent" => exponent,
                        "h" => string(h),
                        "axis" => axis,
                        "succeeded" => false,
                        "failure" => evidence,
                        "elapsed_seconds" =>
                            (time_ns() - started) / 1.0e9,
                        "ode_statistics" => ode_statistics(),
                    ))
                end
            end
        end
        return results
    end
end

function typed_failure_evidence(request, failure)
    translated = translate_numerical_control_failure(request, failure)
    translated isa WorkerControlFailure || throw(failure)
    details = failure_details(translated)
    code = get(details, "failure_code", nothing)
    code isa AbstractString && !isempty(code) || throw(ArgumentError(
        "harness numerical failure omitted a typed failure code"
    ))
    return Dict{String,Any}(
        "failure_code" => String(code),
        "failure_class" => get(details, "failure_class", "CONTROL"),
        "stage" => get(details, "stage", nothing),
        "diagnostics" => get(details, "diagnostics", nothing),
        "message" => sprint(showerror, failure),
    )
end

function sha256_file(path::AbstractString)
    isfile(path) || throw(ArgumentError("identity source is missing: $(path)"))
    return bytes2hex(sha256(read(path)))
end

function harness_policy_sha256(request)
    policy_keys = sort(collect(keys(leaf13_policy())))
    material = join(
        ("$(key)=$(JSON.json(request[key]))" for key in policy_keys),
        "\n",
    ) * "\n"
    return bytes2hex(sha256(codeunits(material)))
end

function source_runtime_identity(request)
    source_material = IOBuffer()
    for path in IDENTITY_SOURCE_PATHS
        write(source_material, relpath(path, REPOSITORY_ROOT), UInt8('\n'))
        write(source_material, read(path), UInt8('\n'))
    end
    project = Base.active_project()
    manifest = project === nothing ? nothing :
        joinpath(dirname(project), "Manifest.toml")
    manifest !== nothing && isfile(manifest) || throw(ArgumentError(
        "active Julia project has no Manifest.toml"
    ))
    return Dict{String,Any}(
        "source_sha256" => bytes2hex(sha256(take!(source_material))),
        "manifest_sha256" => sha256_file(manifest),
        "policy_sha256" => harness_policy_sha256(request),
        "julia_version" => string(VERSION),
        "active_project" => project,
        "control_profile_label" => CONTROL_PROFILE_LABEL,
        "calibration_status" => CALIBRATION_STATUS,
    )
end

function write_receipt_event(
    prefix::AbstractString,
    schema::AbstractString,
    kind::AbstractString,
    identity,
    payload;
    claim_ceiling::AbstractString,
)
    println(String(prefix) * JSON.json(Dict{String,Any}(
        "schema" => String(schema),
        "kind" => String(kind),
        "claim_ceiling" => String(claim_ceiling),
        "identity" => identity,
        "payload" => payload,
    )))
    flush(stdout)
    return nothing
end

end # module
