# Cross-language no-solver request-boundary contract.
# Python generates every document through JuliaPrecisionRootBackend production
# request builders and canonical JSON. This spec only parses, flattens, and
# validates those bytes.

using Test

include("m02_worker.jl")

length(ARGS) == 1 || error(
    "usage: m02_worker_request_contract_spec.jl PYTHON_FIXTURE_JSON"
)
fixture = JSON.parsefile(ARGS[1])
Set(keys(fixture)) == Set((
    "schema_version",
    "operation",
    "requests",
    "invalid_exterior_cases",
    "empirical_safety_factor_invalid_cases",
    "exterior_policy_field_cases",
    "exterior_policy_injection_cases",
    "golden_contracts",
)) || error("Python request-contract fixture fields are invalid")
fixture["schema_version"] == 1 ||
    error("Python request-contract fixture schema is invalid")
fixture["operation"] == "promoted-request-contract-fixture" ||
    error("Python request-contract fixture operation is invalid")
requests = fixture["requests"]
invalid_exterior_cases = fixture["invalid_exterior_cases"]
empirical_safety_factor_invalid_cases =
    fixture["empirical_safety_factor_invalid_cases"]
exterior_policy_field_cases = fixture["exterior_policy_field_cases"]
exterior_policy_injection_cases = fixture["exterior_policy_injection_cases"]
golden_contracts = fixture["golden_contracts"]

# Field taxonomy shared by both exterior diagnostic models. COMMON fields
# describe what happens when reviewed evidence is missing and the preceding
# precision tier; they are not empirical-certificate claims. Provisional-only
# fields describe the additive-channel schema; empirical-only fields describe
# the certificate and its calibration bindings. The two modes are disjoint
# and explicit — a policy that mixes them is invalid.
const COMMON_EXTERIOR_FIELDS = (
    "determinant_error_model",
    "determinant_error_missing_evidence_outcome",
    "determinant_error_preceding_precision_tier",
)
const PROVISIONAL_ONLY_EXTERIOR_FIELDS = (
    "determinant_error_channel_schema",
    "determinant_error_required_channels",
    "determinant_error_calibration_status",
)
const EMPIRICAL_ONLY_EXTERIOR_FIELDS = (
    "determinant_error_required_term_classes",
    "determinant_error_certificate_statement",
    "determinant_error_safety_factor",
    "promoted_control_calibration_receipt_sha256",
    "empirical_control_profile_sha256",
)

function flatten_validation_result(document)
    try
        flattened = flatten_request(document)
        validate_regularised_gsn_policy(flattened)
        return flattened, nothing
    catch failure
        return nothing, sprint(showerror, failure)
    end
end

function fixed_root_flatten_validation_result(document)
    try
        request = flatten_fixed_root_survey_request(document)
        validate_fixed_root_survey_request(request)
        return request, nothing
    catch failure
        return nothing, sprint(showerror, failure)
    end
end

@testset "Python production promoted-request matrix passes Julia schema gate" begin
    @test length(requests) == 16
    for document in requests
        if document["operation"] == FIXED_ROOT_SURVEY_BATCH_OPERATION
            _, failure = fixed_root_flatten_validation_result(document)
            @test failure === nothing
        else
            flattened, failure = flatten_validation_result(document)
            @test failure === nothing
            if flattened !== nothing
                @test validate_worker_request_contract(flattened) !== nothing
            end
        end
    end

    batch = Dict(
        "schema_version" => 1,
        "operation" => "promoted-request-preflight",
        "request_set_sha256" => repeat("0", 64),
        "requests" => requests,
    )
    response = validate_request_batch(batch)
    @test response["status"] == "ok"
    @test response["request_count"] == 16
end

@testset "fixed-root survey matrix passes the real Julia parser" begin
    fixed_root_requests = filter(requests) do document
        document["operation"] == FIXED_ROOT_SURVEY_BATCH_OPERATION
    end
    @test length(fixed_root_requests) == 6
    observed = Set{Tuple{Int,String,String}}()
    for document in fixed_root_requests
        request, failure = fixed_root_flatten_validation_result(document)
        @test failure === nothing
        if request !== nothing
            push!(observed, (
                parse_integer(request, "precision_digits"),
                string(required(request, "scientific_operation_identity")),
                join(required(request, "sample_roles"), "|"),
            ))
        end
    end
    expected = Set{Tuple{Int,String,String}}()
    for digits in (40, 80)
        push!(expected, (
            digits,
            FIXED_ROOT_SURVEY_IDENTITY,
            join(FIXED_ROOT_SURVEY_ROLES, "|"),
        ))
        push!(expected, (
            digits,
            CANONICAL_EXTERIOR_BACKGROUND_IDENTITY,
            join(FIXED_ROOT_SURVEY_BACKGROUND_ROLES, "|"),
        ))
        push!(expected, (
            digits,
            FIXED_ROOT_SURVEY_IDENTITY,
            join(FIXED_ROOT_SURVEY_COORDINATE_ROLES, "|"),
        ))
    end
    @test observed == expected
end

@testset "default exterior request selects the provisional one-role contract" begin
    exterior = only(filter(requests) do document
        document["operation"] == "root-readout" &&
            document["mechanism_id"] == "exterior-light-ring" &&
            document["precision_digits"] == 80 &&
            document["refinement_level"] == 0
    end)
    flattened, failure = flatten_validation_result(exterior)
    @test failure === nothing
    if flattened !== nothing
        @test flattened["diagnostic_model_identity"] ==
            "exterior-determinant-additive-channels/provisional-v1"
        @test flattened["required_raw_determinant_roles"] == ["PRIMARY"]
        @test flattened["required_raw_determinant_count"] === 1
        @test flattened["determinant_error_model"] ==
            "exterior-determinant-additive-channels/provisional-v1"
        # COMMON fields are present on both exterior modes.
        for field in COMMON_EXTERIOR_FIELDS
            @test haskey(flattened, field)
        end
        # PROVISIONAL-ONLY fields are present on provisional.
        for field in PROVISIONAL_ONLY_EXTERIOR_FIELDS
            @test haskey(flattened, field)
        end
        # EMPIRICAL-ONLY fields are absent from provisional; the two modes
        # stay disjoint at the wire level.
        for field in EMPIRICAL_ONLY_EXTERIOR_FIELDS
            @test !haskey(flattened, field)
        end
    end

    horizon = only(filter(requests) do document
        document["operation"] == "root-readout" &&
            document["mechanism_id"] == "horizon-admittance" &&
            document["precision_digits"] == 80 &&
            document["refinement_level"] == 0
    end)
    horizon_flattened, horizon_failure = flatten_validation_result(horizon)
    @test horizon_failure === nothing
    if horizon_flattened !== nothing
        @test horizon_flattened["determinant_error_safety_factor"] == "64"
    end
end

@testset "canonical three-mode request/response golden contracts agree" begin
    @test length(golden_contracts) == 3
    expected = Dict(
        "horizon-analytic" => (
            "horizon-admittance",
            "verified-endpoint-control-equivalence-absolute-error/v2",
            ["PRIMARY"], 1, "not-applicable", "HORIZON_V3_ANALYTIC",
        ),
        "exterior-provisional-additive" => (
            "exterior-light-ring",
            "exterior-determinant-additive-channels/provisional-v1",
            ["PRIMARY"], 1, "forbidden",
            "PROVISIONAL_NOT_SCREENED_WITHOUT_CALIBRATION",
        ),
        "exterior-empirical-certificate" => (
            "exterior-light-ring",
            "exterior-determinant-absolute-error-certificate/empirical-v1",
            ["PRIMARY", "TRUNCATION", "RESOLUTION"], 3, "required",
            "EMPIRICAL_CERTIFICATE_REQUIRED",
        ),
    )
    for case in golden_contracts
        label = string(case["label"])
        @test haskey(expected, label)
        if haskey(expected, label)
            mechanism, model, roles, count, certificate, disposition =
                expected[label]
            request = case["request"]
            response = case["response"]
            @test request["mechanism_id"] == mechanism
            @test request["diagnostic_model_identity"] == model
            @test request["required_raw_determinant_roles"] == roles
            @test request["required_raw_determinant_count"] === count
            @test response["schema_version"] === 12
            @test response["operation"] == "root-readout"
            @test response["diagnostic_model_identity"] == model
            @test response["required_raw_determinant_roles"] == roles
            @test response["required_raw_determinant_count"] === count
            @test response["certificate_requirement"] == certificate
            @test response["provisional_stage"] == (
                label == "exterior-provisional-additive" ?
                "persisted-authenticated" : "not-applicable"
            )
            @test response["evidence_disposition"] == disposition
        end
    end
end

@testset "provisional exterior policy forbids empirical safety-factor field" begin
    # These cases inject determinant_error_safety_factor into a
    # PROVISIONAL exterior policy. The raw-determinant contract must
    # reject it as a disjointness violation regardless of the JSON
    # value's type — the mode boundary itself is under test.
    @test [case["label"] for case in invalid_exterior_cases] == [
        "string",
        "floating-point",
        "boolean",
        "wrong-integer",
        "null",
    ]
    for case in invalid_exterior_cases
        _, failure = flatten_validation_result(case["document"])
        @test failure !== nothing
        @test occursin("determinant_error_safety_factor", failure)
    end
end

@testset "empirical exterior safety-factor JSON type and value fail closed" begin
    # These cases start from the EMPIRICAL golden request and mutate
    # only its determinant_error_safety_factor. The empirical validator
    # requires an exact integer 64; every alternative type and every
    # wrong integer value must fail closed with the field named in the
    # failure message.
    @test [case["label"] for case in empirical_safety_factor_invalid_cases] == [
        "string",
        "floating-point",
        "boolean",
        "wrong-integer",
        "null",
    ]
    for case in empirical_safety_factor_invalid_cases
        _, failure = flatten_validation_result(case["document"])
        @test failure !== nothing
        @test occursin("determinant_error_safety_factor", failure)
    end
end

@testset "exterior policy fields fail closed independently" begin
    # COMMON and PROVISIONAL-ONLY fields are required on a provisional
    # exterior policy: deleting any of them must fail closed with the
    # field named, and forging its value must also fail closed at flatten
    # or validation. Python owns the request and identity projection, so
    # every negative document is rebound there after mutation. This lets
    # the test reach the intended policy gate without weakening the
    # request-digest gate. The forge message for determinant_error_model
    # is intentionally "exterior request carries an unknown diagnostic
    # model" rather than the raw field literal.
    @test Set(string(case["field"]) for case in exterior_policy_field_cases) ==
        Set((COMMON_EXTERIOR_FIELDS..., PROVISIONAL_ONLY_EXTERIOR_FIELDS...))
    for case in exterior_policy_field_cases
        field = string(case["field"])
        _, missing_failure =
            flatten_validation_result(case["missing_document"])
        @test missing_failure !== nothing
        @test occursin(field, missing_failure)

        _, corrupt_failure =
            flatten_validation_result(case["corrupt_document"])
        @test corrupt_failure !== nothing
        if field != "determinant_error_model"
            @test occursin(field, corrupt_failure)
        end
    end
    # EMPIRICAL-ONLY fields must never appear on a provisional policy.
    # Injecting one keeps the diagnostic model provisional but adds a
    # certificate-shaped field — the raw-determinant contract must reject
    # it explicitly so the two modes remain disjoint at the wire level.
    @test Set(
        string(case["field"]) for case in exterior_policy_injection_cases
    ) == Set(EMPIRICAL_ONLY_EXTERIOR_FIELDS)
    for case in exterior_policy_injection_cases
        field = string(case["field"])
        _, injected_failure = flatten_validation_result(case["document"])
        @test injected_failure !== nothing
        @test occursin(field, injected_failure)
    end
end
