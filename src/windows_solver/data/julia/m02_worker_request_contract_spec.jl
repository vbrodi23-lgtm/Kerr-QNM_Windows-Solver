# Cross-language no-solver request-boundary contract.
# Python generates every document through JuliaPrecisionRootBackend._request and
# canonical JSON. This spec only parses, flattens, and validates those bytes.

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
    "golden_contracts",
)) || error("Python request-contract fixture fields are invalid")
fixture["schema_version"] == 1 ||
    error("Python request-contract fixture schema is invalid")
fixture["operation"] == "promoted-request-contract-fixture" ||
    error("Python request-contract fixture operation is invalid")
requests = fixture["requests"]
invalid_exterior_cases = fixture["invalid_exterior_cases"]
golden_contracts = fixture["golden_contracts"]

const EXTERIOR_CERTIFICATE_FIELDS = (
    "determinant_error_model",
    "determinant_error_required_term_classes",
    "determinant_error_missing_evidence_outcome",
    "determinant_error_certificate_statement",
    "determinant_error_preceding_precision_tier",
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

@testset "Python production promoted-request matrix passes Julia schema gate" begin
    @test length(requests) == 10
    for document in requests
        flattened, failure = flatten_validation_result(document)
        @test failure === nothing
        if flattened !== nothing
            @test validate_worker_request_contract(flattened) !== nothing
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
    @test response["request_count"] == 10
end

@testset "default exterior request selects the provisional one-role contract" begin
    exterior = only(filter(requests) do document
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
        @test !haskey(flattened, "determinant_error_safety_factor")
        for field in EXTERIOR_CERTIFICATE_FIELDS[2:end]
            @test !haskey(flattened, field)
        end
    end

    horizon = only(filter(requests) do document
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
            @test response["schema_version"] === 11
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

@testset "exterior safety-factor type and value fail closed" begin
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

@testset "exterior certificate fields fail closed independently" begin
    exterior = only(filter(requests) do document
        document["mechanism_id"] == "exterior-light-ring" &&
            document["precision_digits"] == 80 &&
            document["refinement_level"] == 0
    end)
    for field in EXTERIOR_CERTIFICATE_FIELDS
        missing = deepcopy(exterior)
        delete!(missing["policy"], field)
        _, missing_failure = flatten_validation_result(missing)
        @test missing_failure !== nothing
        @test occursin(field, missing_failure)

        corrupt = deepcopy(exterior)
        corrupt["policy"][field] = "forged-$(field)"
        _, corrupt_failure = flatten_validation_result(corrupt)
        @test corrupt_failure !== nothing
        @test occursin(field, corrupt_failure)
    end
end
