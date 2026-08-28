#!/usr/bin/env julia

using JSON

const REPOSITORY_ROOT = normpath(joinpath(@__DIR__, "..", ".."))
include(joinpath(
    REPOSITORY_ROOT,
    "src",
    "windows_solver",
    "data",
    "julia",
    "m02_worker.jl",
))

function deterministic_conditioning(::Type{T}, request, digits::Int) where {T<:AbstractFloat}
    required_digits = required_reliable_digits(T, request)
    return Dict{String,Any}(
        "schema" => FIXED_ROOT_SURVEY_CONDITIONING_SCHEMA,
        "fixed_root_reliability_target_abs" =>
            string(required(request, "fixed_root_reliability_target_abs")),
        "fixed_root_reliability_rule" =>
            string(required(request, "fixed_root_reliability_rule")),
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

function deterministic_success_sample(
    ::Type{T}, request, _fixed_root::Complex{T}, _omega::Complex{T},
    _amplitude::Complex{T}, _role::String, digits::Int,
) where {T<:AbstractFloat}
    index = parse_integer(request, "sample_index")
    return Dict{String,Any}(
        "determinant" => Dict(
            "real" => numeric_text(T(index + 1) + T(digits) / T(100)),
            "imaginary" => numeric_text(-T(index + 1) / T(10)),
        ),
        "numerical_conditioning" =>
            deterministic_conditioning(T, request, digits),
        "determinant_error_evidence" => nothing,
    )
end

function injected_insufficient_precision(::Type{T}, request, bits::Int) where {T<:AbstractFloat}
    required_digits = required_reliable_digits(T, request)
    assessment = CF.AsymptoticConditioningAssessment{T}(
        false,
        "INJECTED_INSUFFICIENT_ASYMPTOTIC_PRECISION",
        bits,
        T(parse_integer(request, "precision_digits")),
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
        "deterministic-no-solver/v1",
    )
    throw(CF.FactoredPropagationError{T}(
        CF.INSUFFICIENT_ASYMPTOTIC_PRECISION,
        assessment,
        bits,
        0,
        CF.FACTORED_HOMOGENEOUS_ODE_SCOPE_ID,
        "deterministic PR75 asymptotic insufficiency",
    ))
end

function evaluate_case(case)
    document = required(case, "request")
    request = flatten_fixed_root_survey_request(document)
    digits, bits, roles, samples = validate_fixed_root_survey_request(request)
    target = required(case, "failure_sample_index")
    DETERMINANT_INDEX_REQUEST[] = 0
    DETERMINANT_INDEX_PHASE[] = 0
    evaluator = function (
        ::Type{T}, sample_request, fixed_root::Complex{T}, omega::Complex{T},
        amplitude::Complex{T}, role::String, sample_digits::Int,
    ) where {T<:AbstractFloat}
        sample_index = parse_integer(sample_request, "sample_index")
        if target !== nothing && sample_index == Int(target)
            injected_insufficient_precision(T, sample_request, bits)
        end
        return deterministic_success_sample(
            T,
            sample_request,
            fixed_root,
            omega,
            amplitude,
            role,
            sample_digits,
        )
    end
    response = try
        setprecision(BigFloat, bits) do
            fixed_root_survey_batch_fields(
                request,
                digits,
                bits,
                roles,
                samples;
                sample_evaluator=evaluator,
            )
        end
    catch failure
        failure isa WorkerControlFailure || rethrow()
        Dict{String,Any}(
            "schema_version" => 1,
            "status" => "error",
            "error_type" => string(typeof(failure)),
            "message" => sprint(showerror, failure),
            "failure" => operation_control_receipt(
                request, failure_details(failure)
            ),
        )
    end
    DETERMINANT_INDEX_REQUEST[] == 0 ||
        error("PR75 deterministic evaluator reached the determinant kernel")
    return Dict{String,Any}(
        "case_id" => string(required(case, "case_id")),
        "determinant_kernel_calls" => DETERMINANT_INDEX_REQUEST[],
        "response" => response,
    )
end

function main()
    length(ARGS) == 2 || error(
        "usage: test_pr75_fixed_root_lifecycle.jl INPUT_JSON OUTPUT_JSON"
    )
    input = JSON.parsefile(abspath(ARGS[1]))
    Set(keys(input)) == Set(("schema", "cases")) ||
        error("PR75 lifecycle input fields are invalid")
    string(required(input, "schema")) ==
        "windows-solver.pr75-fixed-root-case-batch/1" ||
        error("PR75 lifecycle input schema is invalid")
    cases = required(input, "cases")
    cases isa Vector || error("PR75 lifecycle cases are invalid")
    results = [evaluate_case(case) for case in cases]
    output = Dict{String,Any}(
        "schema" => "windows-solver.pr75-fixed-root-result-batch/1",
        "results" => results,
    )
    output_path = abspath(ARGS[2])
    mkpath(dirname(output_path))
    write(output_path, JSON.json(output))
    return 0
end

if abspath(PROGRAM_FILE) == abspath(@__FILE__)
    exit(main())
end
