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

include(joinpath(@__DIR__, "pr76_fixed_root_endpoint_receipt_fixture.jl"))

function deterministic_conditioning(::Type{T}, request, digits::Int) where {T<:AbstractFloat}
    required_digits = required_reliable_digits(T, request)
    reliability_projection = required(
        request, "fixed_root_reliability_projection"
    )
    recovery_policy = required(request, "fixed_root_endpoint_recovery_policy")
    return Dict{String,Any}(
        "schema" => FIXED_ROOT_SURVEY_CONDITIONING_SCHEMA,
        "fixed_root_reliability_target_abs" =>
            string(required(
                reliability_projection, "fixed_root_reliability_target_abs"
            )),
        "fixed_root_reliability_rule" =>
            string(required(
                reliability_projection, "fixed_root_reliability_rule"
            )),
        "required_digit_guard" =>
            required(reliability_projection, "required_digit_guard"),
        "fixed_root_reliability_projection_sha256" =>
            string(required(reliability_projection, "projection_sha256")),
        "determinant_family" => EXTERIOR_DETERMINANT_FAMILY_ID,
        "homogeneous_representation" => HOMOGENEOUS_REPRESENTATION_ID,
        "branch_convention" => BRANCH_CONVENTION_ID,
        "determinant_convention" => EXTERIOR_DETERMINANT_CONVENTION_ID,
        "determinant_normalisation" =>
            EXTERIOR_DETERMINANT_NORMALISATION_ID,
        "maximum_series_digits_lost" => "1",
        "maximum_recurrence_digits_lost" => "1",
        "maximum_series_evaluation_digits_lost" => "1",
        "maximum_last_term_ratio" => "0.1",
        "maximum_truncation_digits_lost" => "2",
        "minimum_asymptotic_predicted_reliable_digits" =>
            numeric_text(required_digits + T(8)),
        "endpoint_remainders_regular" => true,
        "maximum_endpoint_reconstruction_error" => "1e-30",
        "maximum_contour_angle_deformation" => "0",
        "predicted_reliable_digits" => numeric_text(required_digits + T(5)),
        "required_reliable_digits" => numeric_text(required_digits),
        "precision_limited" => false,
        "endpoint_recovery_policy_identity" => required(recovery_policy, "identity"),
        "endpoint_recovery_policy_sha256" => required(recovery_policy, "policy_sha256"),
        "endpoint_receipts" => deterministic_endpoint_receipts(T, request, CF.ENDPOINT_ADEQUATE),
        "aggregate_limitation" => CF.ENDPOINT_ADEQUATE,
        "factored_homogeneous_rhs_evaluations_before_recovery_decision" => 0,
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

function injected_insufficient_precision(::Type{T}, request, _bits::Int) where {T<:AbstractFloat}
    code = "EXTERIOR_ENDPOINT_ARITHMETIC_INADEQUATE"
    policy = required(request, "fixed_root_endpoint_recovery_policy")
    throw(numerical_control_failure(
        request, code, "deterministic PR75 arithmetic insufficiency",
        Dict{String,Any}(
            "reason" => code,
            "aggregate_limitation" => CF.ENDPOINT_ARITHMETIC_LIMITED,
            "endpoint_recovery_policy_identity" => required(policy, "identity"),
            "endpoint_recovery_policy_sha256" => required(policy, "policy_sha256"),
            "endpoint_receipts" => deterministic_endpoint_receipts(
                T, request, CF.ENDPOINT_ARITHMETIC_LIMITED
            ),
            "selected_intervention" => "ARITHMETIC_PRECISION_PROMOTION",
            "result" => "ARITHMETIC_INADEQUATE",
            "factored_homogeneous_rhs_evaluations" => 0,
        ); retryable=true, stage="asymptotic-preflight",
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

function compatibility_control_details()
    return Dict{String,Any}(
        "failure_code" => "INSUFFICIENT_ASYMPTOTIC_PRECISION",
        "stage" => "asymptotic-preflight",
        "retryable" => true,
        "diagnostics" => Dict{String,Any}(
            "reason" => "INSUFFICIENT_ASYMPTOTIC_PRECISION",
            "precision_bits" => 298,
            "factored_homogeneous_rhs_evaluations" => 0,
            "avoided_ode_scope" => "factored-homogeneous-gsn/v1",
            "predicted_reliable_digits" => "10",
            "required_reliable_digits" => "20",
            "asymptotic_preflight_avoided_ode" => true,
            "asymptotic_preflight_reason" =>
                "INSUFFICIENT_ASYMPTOTIC_PRECISION",
            "maximum_series_digits_lost" => "30",
            "maximum_recurrence_digits_lost" => "5",
        ),
    )
end

function evaluate_compatibility_case(case)
    document = required(case, "request")
    request = flatten_request(document)
    operation, _, _ = validate_worker_request_contract(request)
    outcome = string(required(case, "outcome"))
    DETERMINANT_INDEX_REQUEST[] = 0
    response = if outcome == "success"
        fields = required(case, "success_fields")
        if operation == "root-readout"
            root_readout_response_fields(request, fields)
        elseif operation == "fixed-root-determinant-sample"
            fixed_root_determinant_sample_response_fields(request, fields)
        else
            error("PR75 compatibility operation is invalid")
        end
    elseif outcome == "control"
        Dict{String,Any}(
            "schema_version" => 1,
            "status" => "error",
            "error_type" => "DeterministicOperationControl",
            "message" => "deterministic PR75 compatibility control",
            "failure" => operation_control_receipt(
                request, compatibility_control_details()
            ),
        )
    else
        error("PR75 compatibility outcome is invalid")
    end
    DETERMINANT_INDEX_REQUEST[] == 0 ||
        error("PR75 compatibility case reached the determinant kernel")
    return Dict{String,Any}(
        "case_id" => string(required(case, "case_id")),
        "determinant_kernel_calls" => DETERMINANT_INDEX_REQUEST[],
        "response" => response,
    )
end

function reseal_fixed_root_document(document)
    resealed = deepcopy(document)
    binding = Dict{String,Any}(
        string(key) => value for (key, value) in resealed
        if string(key) ∉ ("request_sha256", "execution_identity")
    )
    request_sha256 = canonical_sha256(binding)
    identity = Dict{String,Any}(
        string(key) => value
        for (key, value) in required(resealed, "execution_identity")
    )
    identity["request_sha256"] = request_sha256
    resealed["request_sha256"] = request_sha256
    resealed["execution_identity"] = identity
    return resealed
end

function fixed_root_request_is_rejected(document)
    try
        request = flatten_fixed_root_survey_request(document)
        validate_fixed_root_survey_request(request)
    catch
        return true
    end
    return false
end

function reseal_fixed_root_projection(document)
    resealed = deepcopy(document)
    projection = required(resealed, "fixed_root_reliability_projection")
    binding = Dict{String,Any}(
        string(key) => value for (key, value) in projection
        if string(key) != "projection_sha256"
    )
    projection["projection_sha256"] = canonical_sha256(binding)
    return reseal_fixed_root_document(resealed)
end

function validate_reliability_negative_matrix(document)
    fixed_root_request_is_rejected(document) && error(
        "PR75 fixed-root reliability baseline was rejected"
    )
    !haskey(document, "root_correction_tolerance") ||
        error("fixed-root wire restored root_correction_tolerance")
    !haskey(required(document, "policy"), "root_correction_tolerance") ||
        error("fixed-root policy restored root_correction_tolerance")
    rejected = 0
    for (field, replacement, remove_projection, reseal_projection) in (
        ("fixed_root_reliability_projection", nothing, true, false),
        (
            "schema",
            "windows-solver.fixed-root-reliability-projection/1",
            false,
            true,
        ),
        (
            "source_reliability_projection_authority_schema",
            "windows-solver.fixed-root-reliability-projection-authority/2",
            false,
            true,
        ),
        (
            "source_reliability_projection_authority_identity",
            "forged-fixed-root-reliability-authority/v1",
            false,
            true,
        ),
        (
            "source_reliability_projection_authority_sha256",
            "0"^64,
            false,
            true,
        ),
        ("fixed_root_reliability_target_abs", "not-a-number", false, true),
        ("fixed_root_reliability_target_abs", "0", false, true),
        ("fixed_root_reliability_target_abs", "3e-11", false, true),
        ("fixed_root_reliability_rule", "forged-rule/v1", false, true),
        ("required_digit_guard", 7, false, true),
        ("source_calibration_receipt_sha256", "0"^64, false, true),
        ("source_empirical_control_profile_sha256", "0"^64, false, true),
        ("projection_sha256", "0"^64, false, false),
    )
        candidate = deepcopy(document)
        if remove_projection
            delete!(candidate, "fixed_root_reliability_projection")
        else
            projection = required(
                candidate, "fixed_root_reliability_projection"
            )
            projection[field] = replacement
        end
        candidate = reseal_projection ?
            reseal_fixed_root_projection(candidate) :
            reseal_fixed_root_document(candidate)
        fixed_root_request_is_rejected(candidate) || error(
            "PR75 fixed-root reliability negative was accepted: $(field)"
        )
        rejected += 1
    end

    legacy = deepcopy(document)
    legacy["schema_version"] = 1
    legacy["schema"] = "windows-solver.fixed-root-survey-batch/1"
    legacy_identity = deepcopy(required(legacy, "execution_identity"))
    legacy_identity["request_schema"] = legacy["schema"]
    legacy["execution_identity"] = legacy_identity
    legacy = reseal_fixed_root_document(legacy)
    fixed_root_request_is_rejected(legacy) ||
        error("PR75 executable fixed-root request /1 was accepted")
    rejected += 1
    return rejected
end

function main()
    length(ARGS) == 2 || error(
        "usage: test_pr75_fixed_root_lifecycle.jl INPUT_JSON OUTPUT_JSON"
    )
    input = JSON.parsefile(abspath(ARGS[1]))
    Set(keys(input)) == Set(("schema", "cases", "compatibility_cases")) ||
        error("PR75 lifecycle input fields are invalid")
    string(required(input, "schema")) ==
        "windows-solver.pr75-fixed-root-case-batch/2" ||
        error("PR75 lifecycle input schema is invalid")
    cases = required(input, "cases")
    cases isa Vector || error("PR75 lifecycle cases are invalid")
    compatibility_cases = required(input, "compatibility_cases")
    compatibility_cases isa Vector ||
        error("PR75 compatibility cases are invalid")
    results = [evaluate_case(case) for case in cases]
    compatibility_results = [
        evaluate_compatibility_case(case) for case in compatibility_cases
    ]
    isempty(cases) && error("PR75 lifecycle case matrix is empty")
    reliability_negative_count = validate_reliability_negative_matrix(
        required(first(cases), "request")
    )
    output = Dict{String,Any}(
        "schema" => "windows-solver.pr75-fixed-root-result-batch/2",
        "results" => results,
        "compatibility_results" => compatibility_results,
        "reliability_negative_count" => reliability_negative_count,
    )
    output_path = abspath(ARGS[2])
    mkpath(dirname(output_path))
    write(output_path, JSON.json(output))
    return 0
end

if abspath(PROGRAM_FILE) == abspath(@__FILE__)
    exit(main())
end
