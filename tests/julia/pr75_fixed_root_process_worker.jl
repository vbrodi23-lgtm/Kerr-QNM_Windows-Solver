#!/usr/bin/env julia

const REPOSITORY_ROOT = normpath(joinpath(@__DIR__, "..", ".."))
const PROCESS_FIXTURE_OUTCOME = get(
    ENV, "PR75_PROCESS_FIXTURE_OUTCOME", "control"
)
include(joinpath(
    REPOSITORY_ROOT,
    "src",
    "windows_solver",
    "data",
    "julia",
    "m02_worker.jl",
))

# This test-only process shadows the evaluator method after including the
# production worker.  Production ``main()`` remains zero-argument and exposes
# no wire, CLI, environment, or callable evaluator selector.
function deterministic_process_conditioning(
    ::Type{T}, request, digits::Int
) where {T<:AbstractFloat}
    required_digits = required_reliable_digits(T, request)
    reliability_projection = required(
        request, "fixed_root_reliability_projection"
    )
    return Dict{String,Any}(
        "schema" => FIXED_ROOT_SURVEY_CONDITIONING_SCHEMA,
        "fixed_root_reliability_target_abs" => string(required(
            reliability_projection, "fixed_root_reliability_target_abs"
        )),
        "fixed_root_reliability_rule" => string(required(
            reliability_projection, "fixed_root_reliability_rule"
        )),
        "required_digit_guard" =>
            required(reliability_projection, "required_digit_guard"),
        "fixed_root_reliability_projection_sha256" => string(required(
            reliability_projection, "projection_sha256"
        )),
        "determinant_family" => EXTERIOR_DETERMINANT_FAMILY_ID,
        "homogeneous_representation" => HOMOGENEOUS_REPRESENTATION_ID,
        "branch_convention" => BRANCH_CONVENTION_ID,
        "determinant_convention" => EXTERIOR_DETERMINANT_CONVENTION_ID,
        "determinant_normalisation" =>
            EXTERIOR_DETERMINANT_NORMALISATION_ID,
        "maximum_series_digits_lost" => "1",
        "maximum_recurrence_digits_lost" => "1",
        "minimum_asymptotic_predicted_reliable_digits" =>
            numeric_text(required_digits + T(8)),
        "endpoint_remainders_regular" => true,
        "maximum_endpoint_reconstruction_error" => "1e-30",
        "maximum_contour_angle_deformation" => "0",
        "predicted_reliable_digits" => numeric_text(required_digits + T(5)),
        "required_reliable_digits" => numeric_text(required_digits),
        "precision_limited" => false,
        "determinant_count" => 1,
    )
end

function production_fixed_root_survey_sample_fields(
    ::Type{T}, request, _fixed_root::Complex{T}, _omega::Complex{T},
    _amplitude::Complex{T}, _role::String, digits::Int,
) where {T<:AbstractFloat}
    if PROCESS_FIXTURE_OUTCOME == "success"
        index = parse_integer(request, "sample_index")
        return Dict{String,Any}(
            "determinant" => Dict(
                "real" => numeric_text(T(index + 1)),
                "imaginary" => numeric_text(-T(index + 1)),
            ),
            "numerical_conditioning" =>
                deterministic_process_conditioning(T, request, digits),
            "determinant_error_evidence" => nothing,
        )
    end
    PROCESS_FIXTURE_OUTCOME == "control" ||
        error("unknown PR75 process fixture outcome")
    bits = working_precision_bits_for(digits)
    required_digits = required_reliable_digits(T, request)
    assessment = CF.AsymptoticConditioningAssessment{T}(
        false,
        "INJECTED_INSUFFICIENT_ASYMPTOTIC_PRECISION",
        bits,
        T(digits),
        required_digits,
        T(6),
        T(2),
        T(10),
        parse(T, "1e-30"),
        T(3),
        parse(T, "1e-20"),
        T(1),
        T(4),
        required_digits - one(T),
        "deterministic-no-solver-process/v1",
    )
    throw(CF.FactoredPropagationError{T}(
        CF.INSUFFICIENT_ASYMPTOTIC_PRECISION,
        assessment,
        bits,
        0,
        CF.FACTORED_HOMOGENEOUS_ODE_SCOPE_ID,
        "deterministic PR75 process-seam asymptotic insufficiency",
    ))
end

function process_fixture_main()
    worker_exit_codes = Int[]
    if length(ARGS) == 5 && ARGS[1] == "--no-solver-contract-cases"
        case_arguments = (
            (ARGS[2], ARGS[3]),
            (ARGS[4], ARGS[5]),
        )
        for (request_path, response_path) in case_arguments
            empty!(ARGS)
            append!(ARGS, (request_path, response_path))
            push!(worker_exit_codes, main())
        end
    else
        push!(worker_exit_codes, main())
    end
    DETERMINANT_INDEX_REQUEST[] == 0 ||
        error("PR75 process fixture reached the determinant kernel")
    LAST_ODE_SNAPSHOT[] === nothing ||
        error("PR75 process fixture reached an ODE scope")
    expected_exit = PROCESS_FIXTURE_OUTCOME == "success" ? 0 : 21
    all(==(expected_exit), worker_exit_codes) ||
        error("PR75 process fixture returned an unexpected worker exit code")
    return expected_exit
end

if abspath(PROGRAM_FILE) == abspath(@__FILE__)
    exit(process_fixture_main())
end
