# No-solver request-boundary contract for the promoted exterior worker path.
# It includes the worker to exercise its real flattening and policy validator,
# but never evaluates a determinant, Newton step, angular solve, coordinate map,
# or ODE.

using Test

include("m02_worker.jl")

const EXTERIOR_CERTIFICATE_FIELDS = (
    "determinant_error_model",
    "determinant_error_required_term_classes",
    "determinant_error_missing_evidence_outcome",
    "determinant_error_certificate_statement",
    "determinant_error_preceding_precision_tier",
)

function promoted_exterior_document()
    digest = repeat("0", 64)
    policy = Dict{String,Any}(
        "readout_radius" => "1e-6",
        "ode_relative_tolerance" => "1e-20",
        "ode_absolute_tolerance" => "1e-20",
        "homogeneous_ode_relative_tolerance" => "1e-20",
        "homogeneous_ode_absolute_tolerance" => "1e-20",
        "coordinate_ode_relative_tolerance" => "1e-20",
        "coordinate_ode_absolute_tolerance" => "1e-20",
        "endpoint_series_order" => 28,
        "support_subinterval_count" => 8,
        "angular_pad" => 18,
        "rho_in" => "-5000",
        "rho_out" => "5000",
        "rho_out_candidate_schedule" => ["100", "5000"],
        "horizon_rho_inner_min" => "-400",
        "horizon_endpoint_rho_floor" => "-400",
        "horizon_endpoint_rho_candidates" => ["-10", "-25"],
        "horizon_maximum_endpoint_distance" => "400",
        "determinant_error_safety_factor" =>
            EXTERIOR_EMPIRICAL_ERROR_SAFETY_FACTOR,
        "frequency_step" => "1e-6",
        "frequency_step_minimum" => "1e-12",
        "frequency_step_maximum" => "1e-3",
        "root_correction_tolerance" => "2e-11",
        "branch_enclosure_radius_abs" => "1e-6",
        "max_newton_iterations" => 16,
        "promoted_root_readout_policy" => PROMOTED_ROOT_READOUT_POLICY_ID,
        "homogeneous_representation" => HOMOGENEOUS_REPRESENTATION_ID,
        "asymptotic_series_evaluation" => ASYMPTOTIC_SERIES_EVALUATION_ID,
        "conditioning_diagnostics" => CONDITIONING_DIAGNOSTICS_ID,
        "branch_convention" => BRANCH_CONVENTION_ID,
        "radial_derivative_convention" => RADIAL_DERIVATIVE_CONVENTION_ID,
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
        "determinant_family" => EXTERIOR_DETERMINANT_FAMILY_ID,
        "scattering_diagnostics_applicable" => false,
        "scattering_coefficient_extraction" => nothing,
        "horizon_determinant_chart" => nothing,
        "scattering_chart_safety_factor" => nothing,
        "scattering_column_convention" => nothing,
        "determinant_convention" => EXTERIOR_DETERMINANT_CONVENTION_ID,
        "determinant_normalisation" =>
            EXTERIOR_DETERMINANT_NORMALISATION_ID,
        "determinant_error_model" => EXTERIOR_EMPIRICAL_ERROR_MODEL_ID,
        "determinant_error_required_term_classes" =>
            copy(EXTERIOR_EMPIRICAL_ERROR_TERM_CLASSES),
        "determinant_error_missing_evidence_outcome" =>
            EXTERIOR_EMPIRICAL_ERROR_MISSING_OUTCOME,
        "determinant_error_certificate_statement" =>
            EXTERIOR_EMPIRICAL_ERROR_STATEMENT,
        "determinant_error_preceding_precision_tier" => "bigfloat-40",
    )
    return Dict{String,Any}(
        "schema_version" => 1,
        "operation" => "root-readout",
        "job_id" => "exterior-flatten-contract",
        "leaf_id" => "exterior-flatten-contract-leaf",
        "role" => "specification",
        "job_policy_sha256" => digest,
        "backend_identity_sha256" => digest,
        "refinement_level" => 0,
        "mode" => Dict("s" => -2, "ell" => 2, "m" => 2, "n" => 1),
        "spin" => "0.95",
        "omega" => Dict("real" => "0.7", "imaginary" => "-0.16"),
        "angular_A" => Dict("real" => "1", "imaginary" => "0"),
        "mechanism_id" => "exterior-light-ring",
        "amplitude" => Dict("real" => "0", "imaginary" => "0"),
        "precision_digits" => 80,
        "working_precision_bits" => working_precision_bits_for(80),
        "semantic_precision_tier" => "bigfloat-80",
        "request_sha256" => digest,
        "policy" => policy,
        "execution_resource" => Dict(
            "schema" => "windows-solver.execution-resource-policy/1",
            "version" => 1,
            "sha256" => digest,
            "worker_request_wall_clock_seconds" => 7200,
            "cooperative_request_deadline_seconds" => 7080,
            "homogeneous_ode_maxiters" => 10_000_000,
            "max_accepted_steps_per_homogeneous_leg" => 1_000_000,
            "max_rhs_evaluations_per_homogeneous_leg" => 2_000_000,
            "homogeneous_leg_wall_clock_seconds" => nothing,
            "coordinate_stall_rhs_threshold" => 200_000,
            "coordinate_stall_minimum_span_fraction" => "1e-6",
            "coordinate_stall_minimum_step_fraction" => "1e-12",
        ),
        "support" => Dict(
            "lower" => "2",
            "upper" => "4",
            "centre" => "3",
            "half_width" => "1",
        ),
    )
end

function flatten_validation_result(document)
    try
        flattened = flatten_request(document)
        validate_regularised_gsn_policy(flattened)
        return flattened, nothing
    catch failure
        return nothing, sprint(showerror, failure)
    end
end

@testset "promoted exterior certificate survives worker flattening" begin
    document = promoted_exterior_document()
    flattened, failure = flatten_validation_result(document)
    @test failure === nothing
    if flattened !== nothing
        for field in EXTERIOR_CERTIFICATE_FIELDS
            @test flattened[field] == document["policy"][field]
        end
    end
end

@testset "promoted exterior certificate fields fail closed independently" begin
    document = promoted_exterior_document()
    for field in EXTERIOR_CERTIFICATE_FIELDS
        missing = deepcopy(document)
        delete!(missing["policy"], field)
        _, missing_failure = flatten_validation_result(missing)
        @test missing_failure !== nothing
        @test occursin(field, missing_failure)

        corrupt = deepcopy(document)
        corrupt["policy"][field] = "forged-$(field)"
        _, corrupt_failure = flatten_validation_result(corrupt)
        @test corrupt_failure !== nothing
        @test occursin(field, corrupt_failure)
    end
end
