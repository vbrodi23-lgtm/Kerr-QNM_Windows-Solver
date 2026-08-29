Warning: truncated output (original token count: 100097)
Total output lines: 9787

#!/usr/bin/env julia

using LinearAlgebra
using DifferentialEquations
using JSON
using SHA
using SciMLBase
using GeneralizedSasakiNakamura
using SpinWeightedSpheroidalHarmonics

const GSN = GeneralizedSasakiNakamura
const CF = GeneralizedSasakiNakamura.ComplexFrequencies
const Kerr = GeneralizedSasakiNakamura.Kerr
const Potentials = GeneralizedSasakiNakamura.Potentials
const Solutions = GeneralizedSasakiNakamura.Solutions
const GSNBranchConvention = GSN.GSNBranchConvention
const PROGRESS_PREFIX = "@@KERR_QNM_PROGRESS@@"
const PROGRESS_SCHEMA = "windows-solver.progress/3"
const CONDITIONING_SCHEMA = "windows-solver.m02-conditioning/3"
const FIXED_ROOT_SURVEY_BATCH_OPERATION = "fixed-root-survey-batch"
const FIXED_ROOT_SURVEY_BATCH_SCHEMA =
    "windows-solver.fixed-root-survey-batch/3"
const FIXED_ROOT_SURVEY_BATCH_RESPONSE_SCHEMA =
    "windows-solver.fixed-root-survey-batch-response/3"
const FIXED_ROOT_SURVEY_IDENTITY = "exterior-fixed-root-survey-raw/v1"
const CANONICAL_EXTERIOR_BACKGROUND_IDENTITY =
    "canonical-exterior-background-wronskian/v1"
const FIXED_ROOT_SURVEY_CONDITIONING_SCHEMA =
    "windows-solver.fixed-root-survey-conditioning/3"
const FIXED_ROOT_ENDPOINT_RECOVERY_POLICY_SCHEMA =
    "windows-solver.fixed-root-endpoint-recovery-policy/1"
const FIXED_ROOT_ENDPOINT_RECOVERY_POLICY_IDENTITY =
    "cause-aware-fixed-root-exterior-endpoint-recovery/v1"
const FIXED_ROOT_ENDPOINT_ORDER_RULE = "bounded-doubling-prefix/v1"
const FIXED_ROOT_HORIZON_GEOMETRY_RULE = "bounded-negative-rho-depth/v1"
const FIXED_ROOT_INFINITY_GEOMETRY_RULE = "bounded-positive-rho-depth/v1"
const OPERATION_EXECUTION_IDENTITY_SCHEMA =
    "windows-solver.operation-execution-identity/1"
const OPERATION_CONTROL_RECEIPT_SCHEMA =
    "windows-solver.operation-control-receipt/1"
const CANONICAL_REQUEST_BINDING_SCHEMA =
    "windows-solver.canonical-request-binding/1"
const FIXED_ROOT_RELIABILITY_PROJECTION_SCHEMA =
    "windows-solver.fixed-root-reliability-projection/2"
const FIXED_ROOT_RELIABILITY_PROJECTION_AUTHORITY_SCHEMA =
    "windows-solver.fixed-root-reliability-projection-authority/1"
const FIXED_ROOT_RELIABILITY_PROJECTION_AUTHORITY_IDENTITY =
    "fixed-root-reliability-projection-authority/v1"
const FIXED_ROOT_POLICY_CONTROL_FIELDS = (
    "coordinate_ode_absolute_tolerance",
    "coordinate_ode_relative_tolerance",
    "homogeneous_ode_absolute_tolerance",
    "homogeneous_ode_relative_tolerance",
    "ode_absolute_tolerance",
    "ode_relative_tolerance",
)
const FIXED_ROOT_RELIABILITY_TARGET_CONTROL_FIELD =
    "root_correction_tolerance"
const FIXED_ROOT_RELIABILITY_PROJECTION_AUTHORITY_PATH = normpath(joinpath(
    @__DIR__, "..", "fixed_root_reliability_projection_authority_v1.json"
))
const PROMOTED_CONTROL_CALIBRATION_RECEIPT_SCHEMA =
    "windows-solver.promoted-control-empirical-calibration-receipt/1"
const PROMOTED_CONTROL_CALIBRATION_IDENTITY =
    "promoted-control-empirical-calibration/v1"
const PROMOTED_CONTROL_CALIBRATION_RECEIPT_PATH = normpath(joinpath(
    @__DIR__, "..", "promoted_control_empirical_calibration_v1.json"
))
const OPERATION_EXECUTION_COMMON_FIELDS = Set((
    "schema",
    "scope",
    "operation",
    "request_schema",
    "request_sha256",
    "leaf_id",
    "job_id",
    "backend_identity_sha256",
    "precision_digits",
    "working_precision_bits",
    "semantic_precision_tier",
    "effective_policy_identity",
    "execution_resource_policy_identity",
))
const ROOT_EXECUTION_REQUIRED_FIELDS = Set((
    "role", "job_policy_sha256", "refinement_level",
))
const ROOT_EXECUTION_OPTIONAL_FIELDS = Set((
    "root_phase", "newton_index",
))
const FIXED_ROOT_DETERMINANT_EXECUTION_FIELDS = Set((
    "fixed_omega", "branch_identity", "readout_role",
))
const FIXED_ROOT_EXECUTION_FIELDS = Set((
    "plan",
    "scientific_operation_identity",
    "root_reference_id",
    "root_seal_sha256",
    "branch_identity",
    "sample_roles",
))
const FIXED_ROOT_SAMPLE_EXECUTION_FIELDS = Set((
    "sample_index", "sample_role",
))
const FIXED_ROOT_SURVEY_ROLES = [
    "D0",
    "DOMEGA_REAL_PLUS_H",
    "DOMEGA_REAL_MINUS_H",
    "DOMEGA_REAL_PLUS_HALF_H",
    "DOMEGA_REAL_MINUS_HALF_H",
    "DC_PLUS_EPSILON",
    "DC_MINUS_EPSILON",
    "DC_PLUS_HALF_EPSILON",
    "DC_MINUS_HALF_EPSILON",
]
const FIXED_ROOT_SURVEY_BACKGROUND_ROLES = FIXED_ROOT_SURVEY_ROLES[1:5]
const FIXED_ROOT_SURVEY_COORDINATE_ROLES = FIXED_ROOT_SURVEY_ROLES[6:9]
const FIXED_ROOT_SURVEY_POLICY_FIELDS = Set((
    "readout_radius",
    "ode_relative_tolerance",
    "ode_absolute_tolerance",
    "homogeneous_ode_relative_tolerance",
    "homogeneous_ode_absolute_tolerance",
    "coordinate_ode_relative_tolerance",
    "coordinate_ode_absolute_tolerance",
    "endpoint_series_order",
    "support_subinterval_count",
    "angular_pad",
    "rho_in",
    "rho_out",
    "rho_out_candidate_schedule",
    "horizon_rho_inner_min",
    "horizon_endpoint_rho_floor",
    "horizon_endpoint_rho_candidates",
    "horizon_maximum_endpoint_distance",
    "homogeneous_representation",
    "asymptotic_series_evaluation",
    "conditioning_diagnostics",
    "branch_convention",
    "radial_derivative_convention",
    "regular_remainder_contract",
    "factored_remainder_state_convention",
    "reliable_digit_safety_margin",
    "determinant_family",
    "scattering_diagnostics_applicable",
    "scattering_coefficient_extraction",
    "horizon_determinant_chart",
    "scattering_chart_safety_factor",
    "scattering_column_convention",
    "determinant_convention",
    "determinant_normalisation",
    "determinant_error_model",
    "determinant_error_channel_schema",
    "determinant_error_required_channels",
    "determinant_error_calibration_status",
    "determinant_error_missing_evidence_outcome",
    "determinant_error_preceding_precision_tier",
))
const FIXED_ROOT_ENDPOINT_RECOVERY_POLICY_FIELDS = Set((
    "schema",
    "identity",
    "endpoint_order_rule",
    "base_endpoint_order",
    "generated_maximum_order",
    "endpoint_order_schedule",
    "horizon_geometry_rule",
    "horizon_geometry_schedule",
    "infinity_geometry_rule",
    "infinity_geometry_schedule",
    "fixed_root_reliability_target_abs",
    "fixed_root_reliability_rule",
    "required_digit_guard",
    "precision_digits",
    "semantic_precision_tier",
    "policy_sha256",
))
const PROMOTED_ROOT_READOUT_POLICY_ID =
    "binary64-parity-primary-fixed-root-diagnostics-frequency-disk/v2"
const PROMOTED_ROOT_ACCEPTANCE_METRIC_ID =
    "abs-determinant-over-abs-complex-derivative/v1"
const HOMOGENEOUS_REPRESENTATION_ID = "factored-plane-wave-gsn/v1"
# The horizon determinant no longer propagates one solution through a mixed
# match-to-inner leg; it builds an actual solution basis from three independent
# legs, so it carries its own representation identity.
const HORIZON_HOMOGENEOUS_REPRESENTATION_ID =
    "factored-three-leg-horizon-basis-at-match-gsn/v1"
const REAL_INNER_HORIZON_CONTOUR_ID = "real-inner-tortoise-contour/v1"
const HORIZON_BASIS_AT_MATCH_EXTRACTION_ID =
    "scaled-horizon-basis-at-match/v1"
const FACTORED_HOMOGENEOUS_ODE_SCOPE_ID =
    "factored-homogeneous-gsn/v1"
const ASYMPTOTIC_SERIES_EVALUATION_ID =
    "typed-batch-horner-compensated/v1"
const CONDITIONING_DIAGNOSTICS_ID = "series-recurrence-basis-fd/v1"
const BRANCH_CONVENTION_ID = "gsn-complex-rho/v1"
const SCATTERING_EXTRACTION_ID = "scaled-factored-horizon-basis/v1"
const SCATTERING_COLUMN_CONVENTION_ID =
    "column1=horizon-ingoing-Cref;column2=horizon-outgoing-Cinc/v1"
const RADIAL_DERIVATIVE_CONVENTION_ID = "state2=dX/drho/v1"
const HORIZON_DETERMINANT_CONVENTION_ID = "cinc-over-cref-minus-R/v1"
const HORIZON_DETERMINANT_NORMALISATION_ID =
    "cinc-over-cref-minus-reflectivity/v1"
const EXTERIOR_DETERMINANT_CONVENTION_ID =
    "wronskian-perturbed-Xin-with-Xup/v1"
const EXTERIOR_DETERMINANT_NORMALISATION_ID =
    "unit-asymptotic-branch-wronskian/v1"
const REGULAR_REMAINDER_CONTRACT_ID =
    "known-carrier-times-regular-remainder/v1"
const FACTORED_REMAINDER_STATE_CONVENTION_ID =
    "state1=Y;state2=dY/drho/v1"
const HORIZON_DETERMINANT_FAMILY_ID = "horizon-scattering/v1"
const EXTERIOR_DETERMINANT_FAMILY_ID = "exterior-wronskian/v1"
const EXTERIOR_EMPIRICAL_ERROR_MODEL_ID =
    "exterior-determinant-absolute-error-certificate/empirical-v1"
const EXTERIOR_EMPIRICAL_ERROR_STATEMENT =
    "conservative empirical certificate; not a formal interval enclosure"
const EXTERIOR_EMPIRICAL_ERROR_MISSING_OUTCOME =
    "EXTERIOR_DETERMINANT_CERTIFICATE_UNAVAILABLE"
const EXTERIOR_EMPIRICAL_ERROR_TERM_CLASSES = [
    "delta_same_point",
    "delta_cross_precision",
    "delta_endpoint_series",
]
const EXTERIOR_EMPIRICAL_ERROR_SAFETY_FACTOR = 64
const EXTERIOR_ADDITIVE_CHANNEL_SCHEMA_ID =
    "exterior-determinant-additive-channels/provisional-v1"
const EXTERIOR_ADDITIVE_CHANNELS = [
    "precision",
    "ode_controls",
    "endpoint_order",
    "match_readout",
    "angular_data",
    "arithmetic_rounding",
]
const EXTERIOR_ADDITIVE_CALIBRATION_STATUS =
    "MISSING_AUTHENTICATED_CALIBRATION"
const EXTERIOR_ADDITIVE_MISSING_OUTCOME =
    "BLOCKED_BY_REVIEWED_ERROR_EVIDENCE"
const RELIABLE_DIGIT_SAFETY_MARGIN = 8
# This guard belongs only to the legacy root-readout request contract.  Fixed-
# root survey authority is loaded from the committed projection authority.
const ROOT_READOUT_REQUIRED_DIGIT_GUARD = 6
const SCATTERING_CHART_SAFETY_FACTOR = 64
const HUMAN_MATH_REVIEW_RECEIPT_STATUS = "absent-unapproved/v1"
const HUMAN_MATH_REVIEW_RECEIPT_SHA256 = nothing
const INDEPENDENT_REFERENCE_FIXTURE_RECEIPT_STATUS = "absent-unreviewed/v1"
const INDEPENDENT_REFERENCE_FIXTURE_RECEIPT_SHA256 = nothing
const ACTIVE_PROGRESS_CONTEXT = Ref(Dict{String,Any}())
const ODE_PROGRESS_INTERVAL_SECONDS = 15.0
const ODE_ALGORITHM_CONFIGURED = "AutoVern9(Rosenbrock23(autodiff=false))"
const NEXT_ODE_SOLVE_ID = Ref(0)
const REQUEST_STARTED_NS = Ref(UInt64(0))
const ACTIVE_PHASE_STARTED_NS = Ref(UInt64(0))
const ACTIVE_PHASE = Ref{Union{Nothing,String}}(nothing)
const ACTIVE_NEWTON_INDEX = Ref(0)
const DETERMINANT_INDEX_REQUEST = Ref(0)
const DETERMINANT_INDEX_PHASE = Ref(0)
const AUTHENTICATED_EVIDENCE_REUSE_COUNT_PHASE = Ref(0)
const LAST_DETERMINANT_PURPOSE = Ref{Union{Nothing,String}}(nothing)
const LAST_DETERMINANT_SECONDS = Ref(0.0)
const LAST_ODE_SNAPSHOT = Ref{Union{Nothing,Dict{String,Any}}}(nothing)
const ALLOWED_MECHANISMS = Set([
    "horizon-admittance",
    "exterior-fixed-r3",
    "exterior-light-ring",
    "exterior-throat-kappa",
    "exterior-alpha-zero",
    "exterior-alpha-half",
    "exterior-alpha-one",
])

@enum RootSolveRole begin
    FULL_AUTHENTICATION
    DIAGNOSTIC_CONSISTENCY
    BINARY64_PARITY_PRIMARY
    FIXED_ROOT_DIAGNOSTIC
end

function root_solve_role_text(role::RootSolveRole)
    role === FULL_AUTHENTICATION && return "FULL_AUTHENTICATION"
    role === DIAGNOSTIC_CONSISTENCY &&
        return "DIAGNOSTIC_CONSISTENCY"
    role === BINARY64_PARITY_PRIMARY &&
        return "BINARY64_PARITY_PRIMARY"
    role === FIXED_ROOT_DIAGNOSTIC &&
        return "FIXED_ROOT_DIAGNOSTIC"
    error("unknown root solve role")
end

@enum RootAuthenticationMode begin
    STAGED_FULL_AUTHENTICATION
    DIAGNOSTIC_CONSISTENCY_AUTHENTICATION
    FULL_AUTHENTICATION_ESCALATION
    LEGACY_FULL_AUTHENTICATION
end

function authentication_mode_text(mode::RootAuthenticationMode)
    mode === STAGED_FULL_AUTHENTICATION &&
        return "STAGED_FULL_AUTHENTICATION"
    mode === DIAGNOSTIC_CONSISTENCY_AUTHENTICATION &&
        return "DIAGNOSTIC_CONSISTENCY"
    mode === FULL_AUTHENTICATION_ESCALATION &&
        return "FULL_AUTHENTICATION_ESCALATION"
    mode === LEGACY_FULL_AUTHENTICATION &&
        return "FULL_AUTHENTICATION"
    error("unknown root authentication mode")
end

const STAGED_REAL_AXIS_AUTHENTICATION_STRATEGY_ID =
    "staged-real-axis-h-h2/v1"
const FULL_DERIVATIVE_LADDER_AUTHENTICATION_STRATEGY_ID =
    "full-h-h2-2h-ih-ladder/v1"

abstract type WorkerControlFailure <: Exception end
abstract type ODEControlFailure <: WorkerControlFailure end

struct ODEResourceLimit <: ODEControlFailure
    message::String
    details::Dict{String,Any}
end

struct ODESolverFailure <: ODEControlFailure
    message::String
    details::Dict{String,Any}
end

struct CoordinateInversionStalled <: ODEControlFailure
    message::String
    details::Dict{String,Any}
end

struct RootReadoutResourceLimit <: WorkerControlFailure
    message::String
    details::Dict{String,Any}
end

struct NumericalControlFailure <: WorkerControlFailure
    message::String
    details::Dict{String,Any}
end

Base.showerror(io::IO, failure::ODEResourceLimit) = print(io, failure.message)
Base.showerror(io::IO, failure::ODESolverFailure) = print(io, failure.message)
Base.showerror(io::IO, failure::CoordinateInversionStalled) =
    print(io, failure.message)
Base.showerror(io::IO, failure::RootReadoutResourceLimit) = print(io, failure.message)
Base.showerror(io::IO, failure::NumericalControlFailure) = print(io, failure.message)
failure_details(failure::WorkerControlFailure) = failure.details

mutable struct ODEObservationState
    solve_id::Int
    leg::String
    t_start
    t_end
    started_ns::UInt64
    next_report_ns::UInt64
    last_accepted_step
    minimum_accepted_step
    request
end

struct ODEObservationCallback
    state::ODEObservationState
end

progress_active() = get(ENV, "KERR_QNM_PROGRESS", "0") == "1"
progress_complex(value) = Dict(
    "real" => string(real(value)),
    "imaginary" => string(imag(value)),
)

function progress_emit(kind; context=Dict{String,Any}(), payload=Dict{String,Any}())
    progress_active() || return
    document = Dict(
        "schema" => PROGRESS_SCHEMA,
        "kind" => kind,
        "context" => merge(ACTIVE_PROGRESS_CONTEXT[], context),
        "payload" => payload,
    )
    println(PROGRESS_PREFIX * JSON.json(document))
    flush(stdout)
end

function progress_scope(operation::Function, context::Dict{String,Any})
    previous = ACTIVE_PROGRESS_CONTEXT[]
    ACTIVE_PROGRESS_CONTEXT[] = merge(previous, context)
    try
        return operation()
    finally
        ACTIVE_PROGRESS_CONTEXT[] = previous
    end
end

function ode_base_payload(state::ODEObservationState)
    return Dict{String,Any}(
        "ode_solve_id" => state.solve_id,
        "ode_leg" => state.leg,
        "ode_stats_scope" => "leg",
        "ode_t_start" => string(state.t_start),
        "ode_t_end" => string(state.t_end),
        "ode_algorithm_configured" => ODE_ALGORITHM_CONFIGURED,
    )
end

function ode_snapshot_payload(
    state::ODEObservationState, stats, t_current; proposed_step=nothing
)
    return merge(ode_base_payload(state), Dict{String,Any}(
        "ode_t_current" => string(t_current),
        "ode_rhs_evaluations" => Int(stats.nf),
        "ode_accepted_steps" => Int(stats.naccept),
        "ode_rejected_steps" => Int(stats.nreject),
        "ode_jacobian_evaluations" => Int(stats.njacs),
        "ode_linear_solves" => Int(stats.nsolve),
        "ode_nonlinear_iterations" => Int(stats.nnonliniter),
        "ode_nonlinear_convergence_failures" => Int(stats.nnonlinconvfail),
        "ode_last_accepted_step_abs" => state.last_accepted_step === nothing ?
            nothing : string(state.last_accepted_step),
        "ode_min_accepted_step_abs" => state.minimum_accepted_step === nothing ?
            nothing : string(state.minimum_accepted_step),
        "ode_proposed_step_abs" => proposed_step === nothing ?
            nothing : string(proposed_step),
        "elapsed_seconds" => (time_ns() - state.started_ns) / 1.0e9,
        "request_elapsed_seconds" =>
            (time_ns() - REQUEST_STARTED_NS[]) / 1.0e9,
    ))
end

function resource_policy_identity(request)
    return Dict{String,Any}(
        "schema" => string(required(request, "resource_policy_schema")),
        "version" => parse_integer(request, "resource_policy_version"),
        "sha256" => string(required(request, "resource_policy_sha256")),
    )
end

function canonical_json(value)
    if value isa AbstractDict
        names = sort!(String[string(key) for key in keys(value)])
        return "{" * join(
            (JSON.json(name) * ":" * canonical_json(value[name]) for name in names),
            ",",
        ) * "}"
    elseif value isa AbstractVector || value isa Tuple
        return "[" * join((canonical_json(item) for item in value), ",") * "]"
    elseif value === nothing || value isa Bool || value isa Number || value isa AbstractString
        return JSON.json(value)
    end
    error("control receipt contains a non-JSON value")
end

canonical_sha256(value) = bytes2hex(SHA.sha256(codeunits(canonical_json(value))))

function fixed_root_reliability_projection_authority()
    raw_authority = read(FIXED_ROOT_RELIABILITY_PROJECTION_AUTHORITY_PATH)
    authority_text = String(raw_authority)
    authority = JSON.parse(authority_text)
    authority isa AbstractDict ||
        error("fixed-root reliability projection authority is invalid")
    Set(string(key) for key in keys(authority)) == Set((
        "schema",
        "identity",
        "calibration_receipt_schema",
        "calibration_receipt_identity",
        "fixed_root_policy_control_fields",
        "fixed_root_reliability_rule",
        "fixed_root_reliability_target_control_field",
        "required_digit_guard",
        "authority_sha256",
    )) || error("fixed-root reliability projection authority fields are invalid")
    authority_text == canonical_json(authority) * "\n" ||
        error("fixed-root reliability projection authority is not canonical")
    string(required(authority, "schema")) ==
        FIXED_ROOT_RELIABILITY_PROJECTION_AUTHORITY_SCHEMA ||
        error("fixed-root reliability projection authority schema is invalid")
    string(required(authority, "identity")) ==
        FIXED_ROOT_RELIABILITY_PROJECTION_AUTHORITY_IDENTITY ||
        error("fixed-root reliability projection authority identity is invalid")
    string(required(authority, "calibration_receipt_schema")) ==
        PROMOTED_CONTROL_CALIBRATION_RECEIPT_SCHEMA ||
        error("fixed-root reliability authority calibration schema is invalid")
    string(required(authority, "calibration_receipt_identity")) ==
        PROMOTED_CONTROL_CALIBRATION_IDENTITY ||
        error("fixed-root reliability authority calibration identity is invalid")
    rule = required(authority, "fixed_root_reliability_rule")
    rule isa AbstractString && !isempty(rule) ||
        error("fixed-root reliability authority rule is invalid")
    policy_control_fields = required(
        authority, "fixed_root_policy_control_fields"
    )
    policy_control_fields isa Vector &&
        Tuple(string(field) for field in policy_control_fields) ==
            FIXED_ROOT_POLICY_CONTROL_FIELDS ||
        error("fixed-root reliability authority policy controls are invalid")
    string(required(
        authority, "fixed_root_reliability_target_control_field"
    )) == FIXED_ROOT_RELIABILITY_TARGET_CONTROL_FIELD ||
        error("fixed-root reliability authority target control is invalid")
    guard = required(authority, "required_digit_guard")
    guard isa Integer && !(guard isa Bool) && guard > 0 ||
        error("fixed-root reliability authority digit guard is invalid")
    authority_sha256 = string(required(authority, "authority_sha256"))
    occursin(r"^[0-9a-f]{64}$", authority_sha256) ||
        error("fixed-root reliability projection authority digest is invalid")
    binding = Dict{String,Any}(
        string(key) => value for (key, value) in authority
        if string(key) != "authority_sha256"
    )
    canonical_sha256(binding) == authority_sha256 ||
        error("fixed-root reliability projection authority digest disagrees")
    return authority
end

function validated_execution_identity(value)
    value isa AbstractDict || error("operation execution identity is invalid")
    string(required(value, "schema")) == OPERATION_EXECUTION_IDENTITY_SCHEMA ||
        error("operation execution identity schema is invalid")
    scope = string(required(value, "scope"))
    scope in ("REQUEST", "SAMPLE") ||
        error("operation execution identity scope is invalid")
    operation = string(required(value, "operation"))
    operation in (
        "root-readout",
        "fixed-root-determinant-sample",
        FIXED_ROOT_SURVEY_BATCH_OPERATION,
    ) || error("operation execution identity operation is invalid")
    expected_fields = copy(OPERATION_EXECUTION_COMMON_FIELDS)
    allowed_fields = copy(OPERATION_EXECUTION_COMMON_FIELDS)
    if operation == FIXED_ROOT_SURVEY_BATCH_OPERATION
        union!(expected_fields, FIXED_ROOT_EXECUTION_FIELDS)
        union!(allowed_fields, FIXED_ROOT_EXECUTION_FIELDS)
        if scope == "SAMPLE"
            union!(expected_fields, FIXED_ROOT_SAMPLE_EXECUTION_FIELDS)
            union!(allowed_fields, FIXED_ROOT_SAMPLE_EXECUTION_FIELDS)
        end
        Set(string(key) for key in keys(value)) == expected_fields ||
            error("fixed-root operation execution identity fields are invalid")
    else
        union!(expected_fields, ROOT_EXECUTION_REQUIRED_FIELDS)
        union!(allowed_fields, ROOT_EXECUTION_REQUIRED_FIELDS)
        union!(allowed_fields, ROOT_EXECUTION_OPTIONAL_FIELDS)
        if operation == "fixed-root-determinant-sample"
            union!(expected_fields, FIXED_ROOT_DETERMINANT_EXECUTION_FIELDS)
            union!(allowed_fields, FIXED_ROOT_DETERMINANT_EXECUTION_FIELDS)
        end
        observed_fields = Set(string(key) for key in keys(value))
        expected_fields ⊆ observed_fields ⊆ allowed_fields ||
            error("root operation execution identity fields are invalid")
    end
    for key in (
        "request_schema",
        "request_sha256",
        "leaf_id",
        "job_id",
        "backend_identity_sha256",
        "precision_digits",
        "working_precision_bits",
        "semantic_precision_tier",
        "effective_policy_identity",
        "execution_resource_policy_identity",
    )
        required(value, key)
    end
    occursin(r"^[0-9a-f]{64}$", string(required(value, "request_sha256"))) ||
        error("operation execution identity request digest is invalid")
    if operation == FIXED_ROOT_SURVEY_BATCH_OPERATION
        for key in (
            "plan",
            "scientific_operation_identity",
            "root_reference_id",
            "root_seal_sha256",
            "branch_identity",
            "sample_roles",
        )
            required(value, key)
        end
        if scope == "REQUEST"
            !haskey(value, "sample_index") && !haskey(value, "sample_role") ||
                error("fixed-root request identity selects a sample")
        else
            index = parse(Int, string(required(value, "sample_index")))
            roles = required(value, "sample_roles")
            0 <= index < length(roles) ||
                error("fixed-root sample identity index is invalid")
            string(required(value, "sample_role")) == string(roles[index + 1]) ||
                error("fixed-root sample identity role is invalid")
        end
    else
        scope == "REQUEST" || error("root execution identity scope is invalid")
        for key in ("role", "job_policy_sha256", "refinement_level")
            required(value, key)
        end
        if operation == "fixed-root-determinant-sample"
            fixed_omega = required(value, "fixed_omega")
            fixed_omega isa AbstractDict &&
                Set(string(key) for key in keys(fixed_omega)) ==
                    Set(("real", "imaginary")) ||
                error("fixed-root determinant frequency identity is invalid")
            for key in ("real", "imaginary")
                !isempty(string(required(fixed_omega, key))) ||
                    error("fixed-root determinant frequency identity is invalid")
            end
            for key in ("branch_identity", "readout_role")
                !isempty(string(required(value, key))) || error(
                    "fixed-root determinant $(key) identity is invalid"
                )
            end
        end
    end
    for key in ("backend_identity_sha256",)
        occursin(r"^[0-9a-f]{64}$", string(required(value, key))) ||
            error("operation execution identity $(key) is invalid")
    end
    policy_identity = required(value, "effective_policy_identity")
    if policy_identity isa AbstractDict
        occursin(r"^[0-9a-f]{64}$", string(required(policy_identity, "sha256"))) ||
            error("operation execution policy identity is invalid")
    else
        occursin(r"^[0-9a-f]{64}$", string(policy_identity)) ||
            error("operation execution policy identity is invalid")
    end
    resource_identity = required(value, "execution_resource_policy_identity")
    resource_identity isa AbstractDict &&
        Set(string(key) for key in keys(resource_identity)) ==
            Set(("schema", "version", "sha256")) &&
        occursin(r"^[0-9a-f]{64}$", string(required(resource_identity, "sha256"))) ||
        error("operation execution resource identity is invalid")
    return Dict{String,Any}(string(key) => item for (key, item) in value)
end

function request_execution_identity(request)
    return validated_execution_identity(required(request, "execution_identity"))
end

function validate_wire_execution_identity(document, default_request_schema::String)
    identity = validated_execution_identity(required(document, "execution_identity"))
    binding = Dict{String,Any}(
        string(key) => value for (key, value) in document
        if string(key) ∉ ("request_sha256", "execution_identity")
    )
    observed_request_sha256 = canonical_sha256(binding)
    observed_request_sha256 == string(required(document, "request_sha256")) ==
        string(required(identity, "request_sha256")) ||
        error("operation execution identity request digest mismatch")
    request_schema = haskey(document, "schema") ?
        string(document["schema"]) : default_request_schema
    string(required(identity, "request_schema")) == request_schema ||
        error("operation execution identity request schema mismatch")
    for key in (
        "operation",
        "leaf_id",
        "job_id",
        "backend_identity_sha256",
        "precision_digits",
        "working_precision_bits",
        "semantic_precision_tier",
    )
        isequal(required(identity, key), required(document, key)) ||
            error("operation execution identity $(key) mismatch")
    end
    policy = required(document, "policy")
    string(required(identity, "effective_policy_identity")) ==
        canonical_sha256(policy) ||
        error("operation execution identity policy mismatch")
    resource = required(document, "execution_resource")
    resource_identity = required(identity, "execution_resource_policy_identity")
    for key in ("schema", "version", "sha256")
        isequal(required(resource_identity, key), required(resource, key)) ||
            error("operation execution identity resource policy mismatch")
    end
    if string(required(identity, "operation")) ==
            FIXED_ROOT_SURVEY_BATCH_OPERATION
        for key in (
            "plan",
            "scientific_operation_identity",
            "root_reference_id",
            "root_seal_sha256",
            "branch_identity",
            "sample_roles",
        )
            isequal(required(identity, key), required(document, key)) ||
                error("fixed-root operation execution identity $(key) mismatch")
        end
    else
        for key in ("role", "job_policy_sha256", "refinement_level")
            isequal(required(identity, key), required(document, key)) ||
                error("root operation execution identity $(key) mismatch")
        end
        for key in ROOT_EXECUTION_OPTIONAL_FIELDS
            if haskey(identity, key)
                isequal(required(identity, key), required(document, key)) ||
                    error("root operation execution identity $(key) mismatch")
            end
        end
        if string(required(identity, "operation")) ==
                "fixed-root-determinant-sample"
            isequal(
                required(identity, "fixed_omega"),
                required(document, "fixed_omega"),
            ) || error(
                "fixed-root determinant execution identity frequency mismatch"
            )
            string(required(identity, "branch_identity")) ==
                string(required(policy, "branch_convention")) || error(
                    "fixed-root determinant execution identity branch mismatch"
                )
            string(required(identity, "readout_role")) ==
                string(required(document, "readout_role")) || error(
                    "fixed-root determinant execution identity role mismatch"
                )
        end
    end
    return identity
end

function sample_execution_identity(request, sample_index::Int, sample_role::String)
    identity = request_execution_identity(request)
    string(required(identity, "operation")) == FIXED_ROOT_SURVEY_BATCH_OPERATION ||
        error("sample identity requires a fixed-root request")
    string(required(identity, "scope")) == "REQUEST" ||
        error("fixed-root outer identity is not REQUEST scope")
    roles = required(identity, "sample_roles")
    0 <= sample_index < length(roles) ||
        error("fixed-root sample index is invalid")
    string(roles[sample_index + 1]) == sample_role ||
        error("fixed-root sample role is invalid")
    identity["scope"] = "SAMPLE"
    identity["sample_index"] = sample_index
    identity["sample_role"] = sample_role
    return validated_execution_identity(identity)
end

function control_failure_context(request)
    now = time_ns()
    identity = request_execution_identity(request)
    failure_context = Dict{String,Any}(
        "retryable" => true,
        "precision_digits" => parse_integer(request, "precision_digits"),
        "request_sha256" => required(request, "request_sha256"),
        "job_id" => required(request, "job_id"),
        "leaf_id" => required(request, "leaf_id"),
        "operation" => required(identity, "operation"),
        "execution_identity" => identity,
        "root_phase" => ACTIVE_PHASE[],
        "newton_index" => ACTIVE_NEWTON_INDEX[],
        "determinant_index" => DETERMINANT_INDEX_REQUEST[],
        "phase_determinant_index" => DETERMINANT_INDEX_PHASE[],
        "determinant_purpose" => LAST_DETERMINANT_PURPOSE[],
        "diagnostics_skipped_reason" => ACTIVE_PHASE[] == "PRIMARY" ?
            "PRIMARY_RESOURCE_LIMIT" : nothing,
        "elapsed_request_seconds" =>
            (now - REQUEST_STARTED_NS[]) / 1.0e9,
        "elapsed_phase_seconds" => ACTIVE_PHASE_STARTED_NS[] == 0 ?
            nothing : (now - ACTIVE_PHASE_STARTED_NS[]) / 1.0e9,
        "execution_resource_policy" => resource_policy_identity(request),
    )
    if string(required(identity, "operation")) in (
        "root-readout", "fixed-root-determinant-sample"
    )
        failure_context["role"] = required(identity, "role")
        failure_context["job_policy_sha256"] = required(identity, "job_policy_sha256")
        failure_context["refinement_level"] = required(identity, "refinement_level")
    elseif string(required(identity, "scope")) == "SAMPLE"
        failure_context["sample_index"] = required(identity, "sample_index")
        failure_context["sample_role"] = required(identity, "sample_role")
    end
    return failure_context
end

const CONTROL_STAGE_BY_CODE = Dict(
    "ODE_RESOURCE_LIMIT" => "homogeneous-propagation",
    "ROOT_READOUT_RESOURCE_INFEASIBLE" => "request-policy",
    "ODE_SOLVER_FAILURE" => "homogeneous-propagation",
    "COORDINATE_INVERSION_STALLED" => "coordinate-inversion",
    "COORDINATE_IDENTITY_MISMATCH" => "coordinate-inversion",
)

function operation_control_receipt(request, details)
    code = string(required(details, "failure_code"))
    stage = haskey(details, "stage") ? string(details["stage"]) :
        get(CONTROL_STAGE_BY_CODE, code, "determinant-chart")
    identity = haskey(details, "execution_identity") ?
        validated_execution_identity(details["execution_identity"]) :
        request_execution_identity(request)
    diagnostics = if haskey(details, "diagnostics")
        Dict{String,Any}(details["diagnostics"])
    else
        excluded = Set((
            "failure_code", "failure_class", "retryable", "stage",
            "execution_identity", "request_sha256", "job_id", "leaf_id",
            "operation", "role", "job_policy_sha256", "refinement_level",
            "backend_identity_sha256", "execution_resource_policy",
        ))
        Dict{String,Any}(
            string(key) => value for (key, value) in details
            if !(string(key) in excluded)
        )
    end
    isempty(diagnostics) && (diagnostics["reason"] = code)
    retryable = Bool(get(details, "retryable", false))
    identity_sha256 = canonical_sha256(identity)
    binding = Dict{String,Any}(
        "schema" => CANONICAL_REQUEST_BINDING_SCHEMA,
        "operation" => string(required(identity, "operation")),
        "request_schema" => string(required(identity, "request_schema")),
        "request_sha256" => string(required(identity, "request_sha256")),
        "execution_identity_sha256" => identity_sha256,
    )
    content = Dict{String,Any}(
        "schema" => OPERATION_CONTROL_RECEIPT_SCHEMA,
        "origin" => "JULIA_WORKER",
        "failure_class" => "CONTROL",
        "failure_code" => code,
        "stage" => stage,
        "scope" => string(required(identity, "scope")),
        "execution_identity" => identity,
        "retryable_evidence" => Dict(
            "retryable" => retryable,
            "basis" => retryable ?
                "worker-declared bounded control continuation/v1" :
                "worker-declared non-retryable control outcome/v1",
        ),
        "diagnostics" => diagnostics,
        "canonical_request_binding" => binding,
    )
    content["receipt_sha256"] = canonical_sha256(content)
    return content
end

function throw_ode_resource_limit(
    state::ODEObservationState, stats, t_current, limit_kind::String,
    limiting_resource::String; proposed_step=nothing,
)
    snapshot = merge(
        ode_snapshot_payload(
            state, stats, t_current; proposed_step=proposed_step
        ),
        Dict{String,Any}(
            "ode_retcode" => "ResourceLimit",
            "ode_endpoint_reached" => false,
        ),
    )
    LAST_ODE_SNAPSHOT[] = snapshot
    details = merge(control_failure_context(state.request), Dict{String,Any}(
        "failure_code" => "ODE_RESOURCE_LIMIT",
        "failure_class" => "CONTROL",
        "limit_kind" => limit_kind,
        "limiting_resource" => limiting_resource,
        "elapsed_leg_seconds" => snapshot["elapsed_seconds"],
        "ode_leg" => state.leg,
        "ode_snapshot" => snapshot,
    ))
    progress_emit("ode_resource_limit"; payload=merge(snapshot, Dict{String,Any}(
        "failure_code" => "ODE_RESOURCE_LIMIT",
        "failure_class" => "CONTROL",
        "limit_kind" => limit_kind,
        "limiting_resource" => limiting_resource,
        "execution_resource_policy" => resource_policy_identity(state.request),
    )))
    throw(ODEResourceLimit(
        "$(state.leg) reached execution resource $(limiting_resource)",
        details,
    ))
end

const COORDINATE_ODE_LEG_PREFIX = "r_from_rho"

is_coordinate_ode_leg(leg::AbstractString) =
    startswith(String(leg), COORDINATE_ODE_LEG_PREFIX)

"""
    throw_coordinate_inversion_stalled(state, stats, t_current, ...)

Fail a coordinate-inversion leg that is making no progress.

Leaf 13 spent 87.8 s and 2,000,002 RHS evaluations covering 1.01e-11 of a 5000
span before hitting the generic RHS ceiling, with accepted steps pinned at
8.1e-17. That is a diagnosable condition -- an impossible local-error target
against the coordinate map -- but the generic resource limit reports it only as
"ran out of budget". This watchdog names it, and fires long before the hard
ceiling so the budget is not consumed proving the same point.
"""
function throw_coordinate_inversion_stalled(
    state::ODEObservationState, stats, t_current;
    proposed_step=nothing, span, span_fraction, current_radius,
    coordinate_identity_residual_abs, reason::String,
)
    snapshot = merge(
        ode_snapshot_payload(
            state, stats, t_current; proposed_step=proposed_step
        ),
        Dict{String,Any}(
            "ode_retcode" => "CoordinateInversionStalled",
            "ode_endpoint_reached" => false,
            "ode_span_abs" => string(span),
            "ode_span_fraction" => span_fraction === nothing ?
                nothing : string(span_fraction),
            "current_r_re" => string(real(current_radius)),
            "current_r_im" => string(imag(current_radius)),
            "coordinate_identity_residual_abs" =>
                string(coordinate_identity_residual_abs),
        ),
    )
    LAST_ODE_SNAPSHOT[] = snapshot
    details = merge(control_failure_context(state.request), Dict{String,Any}(
        "failure_code" => "COORDINATE_INVERSION_STALLED",
        "failure_class" => "CONTROL",
        "retryable" => true,
        "stage" => control_failure_stage("coordinate-inversion"),
        "stall_reason" => reason,
        "elapsed_leg_seconds" => snapshot["elapsed_seconds"],
        "ode_leg" => state.leg,
        "ode_snapshot" => snapshot,
        # A recognised CONTROL receipt only reaches the campaign as a typed
        # numerical-control failure when it carries a non-empty `diagnostics`
        # mapping. Without it this degrades to a generic backend error and the
        # named diagnosis the watchdog exists to produce is lost again.
        "diagnostics" => Dict{String,Any}(
            "reason" => "COORDINATE_INVERSION_STALLED",
            "range_status" => "coordinate-inversion-stalled/v1",
            "operation" => "coordinate-inversion/v1",
            "stall_reason" => reason,
            "ode_leg" => state.leg,
            "ode_t_current" => string(t_current),
            "ode_t_end" => string(state.t_end),
            "ode_span_abs" => string(span),
            "ode_span_fraction" => span_fraction === nothing ?
                nothing : string(span_fraction),
            "ode_rhs_evaluations" => Int(stats.nf),
            "ode_accepted_steps" => Int(stats.naccept),
            "ode_rejected_steps" => Int(stats.nreject),
            "ode_last_accepted_step_abs" =>
                state.last_accepted_step === nothing ?
                nothing : string(state.last_accepted_step),
            "ode_min_accepted_step_abs" =>
                state.minimum_accepted_step === nothing ?
                nothing : string(state.minimum_accepted_step),
            "current_r_re" => snapshot["current_r_re"],
            "current_r_im" => snapshot["current_r_im"],
            "coordinate_identity_residual_abs" =>
                snapshot["coordinate_identity_residual_abs"],
            "elapsed_leg_seconds" => snapshot["elapsed_seconds"],
        ),
    ))
    progress_emit(
        "coordinate_inversion_stalled";
        payload=merge(snapshot, Dict{String,Any}(
            "failure_code" => "COORDINATE_INVERSION_STALLED",
            "failure_class" => "CONTROL",
            "stall_reason" => reason,
            "execution_resource_policy" =>
                resource_policy_identity(state.request),
        )),
    )
    throw(CoordinateInversionStalled(
        "$(state.leg) stalled near rho=$(t_current) ($(reason))",
        details,
    ))
end

function ode_observation_factory(request, leg, tspan, _algorithm)
    NEXT_ODE_SOLVE_ID[] += 1
    started = time_ns()
    interval = round(UInt64, ODE_PROGRESS_INTERVAL_SECONDS * 1.0e9)
    state = ODEObservationState(
        NEXT_ODE_SOLVE_ID[],
        string(leg),
        tspan[1],
        tspan[2],
        started,
        started + interval,
        nothing,
        nothing,
        request,
    )
    progress_emit("ode_solve_started"; payload=ode_base_payload(state))

    condition = (_u, _t, integrator) -> integrator.stats.naccept > 0
    function observe_step!(integrator)
        try
            stats = integrator.stats
            if stats.naccept > 0
                accepted_step = abs(integrator.t - integrator.tprev)
                state.last_accepted_step = accepted_step
                if state.minimum_accepted_step === nothing ||
                   accepted_step < state.minimum_accepted_step
                    state.minimum_accepted_step = accepted_step
                end
            end
            sampled_at = time_ns()
            proposed_step = try
                abs(SciMLBase.get_proposed_dt(integrator))
            catch
                nothing
            end
            request_elapsed = (sampled_at - REQUEST_STARTED_NS[]) / 1.0e9
            leg_elapsed = (sampled_at - state.started_ns) / 1.0e9
            if request_elapsed >= parse_integer(
                request, "cooperative_request_deadline_seconds"
            )
                throw_ode_resource_limit(
                    state, stats, integrator.t,
                    "request_wall_clock", "cooperative_request_deadline";
                    proposed_step=proposed_step,
                )
            end
            leg_limit = required(request, "homogeneous_leg_wall_clock_seconds")
            if leg_limit !== nothing && leg_elapsed >= parse(Int, string(leg_limit))
                throw_ode_resource_limit(
                    state, stats, integrator.t,
                    "homogeneous_leg_wall_clock", "homogeneous_leg_wall_clock";
                    proposed_step=proposed_step,
                )
            end
            if Int(stats.naccept) >= parse_integer(
                request, "max_accepted_steps_per_homogeneous_leg"
            )
                throw_ode_resource_limit(
                    state, stats, integrator.t,
                    "accepted_steps", "accepted_steps";
                    proposed_step=proposed_step,
                )
            end
            if Int(stats.nf) >= parse_integer(
                request, "max_rhs_evaluations_per_homogeneous_leg"
            )
                throw_ode_resource_limit(
                    state, stats, integrator.t,
                    "rhs_evaluations", "rhs_evaluations";
                    proposed_step=proposed_step,
                )
            end
            if is_coordinate_ode_leg(state.leg)
                stall_threshold = parse_integer(
                    request, "coordinate_stall_rhs_threshold"
                )
                if Int(stats.nf) >= stall_threshold
                    span = abs(Float64(state.t_end) - Float64(state.t_start))
                    covered = abs(
                        Float64(real(integrator.t)) - Float64(state.t_start)
                    )
                    span_fraction = span > 0 ? covered / span : nothing
                    minimum_fraction = parse(
                        Float64,
                        string(required(
                            request, "coordinate_stall_minimum_span_fraction"
                        )),
                    )
                    minimum_step_fraction = parse(
                        Float64,
                        string(required(
                            request, "coordinate_stall_minimum_step_fraction"
                        )),
                    )
                    last_step = state.last_accepted_step === nothing ?
                        nothing : Float64(state.last_accepted_step)
                    stalled_span = span_fraction !== nothing &&
                        span_fraction < minimum_fraction
                    stalled_step = last_step !== nothing && span > 0 &&
                        last_step <= minimum_step_fraction * span
                    if stalled_span && stalled_step
                        current_radius = integrator.u[1]
                        tangent = integrator.p.sign *
                            exp(1im * integrator.p.beta)
                        expected_rstar = integrator.p.rs_mp +
                            tangent * integrator.t
                        observed_rstar = GSN.rstar_from_r(
                            integrator.p.a, current_radius
                        )
                        coordinate_identity_residual_abs = abs(
                            observed_rstar - expected_rstar
                        )
                        throw_coordinate_inversion_stalled(
                            state, stats, integrator.t;
                            proposed_step=proposed_step,
                            span=span,
                            span_fraction=span_fraction,
                            current_radius=current_radius,
                            coordinate_identity_residual_abs=
                                coordinate_identity_residual_abs,
                            reason="span fraction $(span_fraction) below " *
                                "$(minimum_fraction) with accepted step " *
                                "$(last_step) after $(Int(stats.nf)) RHS " *
                                "evaluations",
                        )
                    end
                end
            end
            if sampled_at >= state.next_report_ns
                state.next_report_ns = sampled_at + interval
                progress_emit("ode_solve_progress"; payload=ode_snapshot_payload(
                    state, stats, integrator.t; proposed_step=proposed_step
                ))
            end
        finally
            SciMLBase.u_modified!(integrator, false)
        end
    end
    callback = DiscreteCallback(
        condition, observe_step!; save_positions=(false, false)
    )
    return callback, ODEObservationCallback(state)
end

function observe_ode_solution(leg, solution, observation::ODEObservationCallback)
    state = observation.state
    string(leg) == state.leg || error("ODE observation leg mismatch")
    stats = solution.stats
    t_current = isempty(solution.t) ? state.t_start : solution.t[end]
    endpoint_reached = t_current == state.t_end
    retcode = string(solution.retcode)
    snapshot = merge(ode_snapshot_payload(state, stats, t_current), Dict{String,Any}(
        "ode_retcode" => retcode,
        "ode_endpoint_reached" => endpoint_reached,
    ))
    LAST_ODE_SNAPSHOT[] = snapshot

    if solution.retcode === SciMLBase.ReturnCode.MaxIters
        details = merge(control_failure_context(state.request), Dict{String,Any}(
            "failure_code" => "ODE_RESOURCE_LIMIT",
            "failure_class" => "CONTROL",
            "limit_kind" => "ode_solver_iterations",
            "limiting_resource" => "homogeneous_ode_maxiters",
            "elapsed_leg_seconds" => snapshot["elapsed_seconds"],
            "ode_leg" => state.leg,
            "ode_snapshot" => snapshot,
        ))
        progress_emit("ode_resource_limit"; payload=merge(snapshot, Dict{String,Any}(
            "failure_code" => "ODE_RESOURCE_LIMIT",
            "failure_class" => "CONTROL",
            "limit_kind" => "ode_solver_iterations",
            "limiting_resource" => "homogeneous_ode_maxiters",
            "execution_resource_policy" => resource_policy_identity(state.request),
        )))
        throw(ODEResourceLimit(
            "$(state.leg) reached the existing ODE solver iteration limit",
            details,
        ))
    end

    if !SciMLBase.successful_retcode(solution) || !endpoint_reached
        details = merge(control_failure_context(state.request), Dict{String,Any}(
            "failure_code" => "ODE_SOLVER_FAILURE",
            "failure_class" => "CONTROL",
            "retryable" => false,
            "elapsed_leg_seconds" => snapshot["elapsed_seconds"],
            "ode_leg" => state.leg,
            "ode_snapshot" => snapshot,
        ))
        progress_emit("ode_solve_failed"; payload=merge(snapshot, Dict{String,Any}(
            "failure_code" => "ODE_SOLVER_FAILURE",
            "failure_class" => "CONTROL",
        )))
        throw(ODESolverFailure(
            "$(state.leg) failed with ODE solver return code $(retcode)",
            details,
        ))
    end

    progress_emit("ode_solve_completed"; payload=snapshot)
    return solution
end

function progress_operation(operation::Function, name::String; payload=Dict{String,Any}())
    started = time_ns()
    context = Dict{String,Any}("suboperation" => name)
    return progress_scope(context) do
        progress_emit("suboperation_started"; context=context, payload=merge(
            Dict{String,Any}("suboperation" => name), payload
        ))
        try
            result = operation()
            progress_emit("suboperation_completed"; context=context, payload=merge(
                Dict{String,Any}(
                    "suboperation" => name,
                    "elapsed_seconds" => (time_ns() - started) / 1.0e9,
                ),
                payload,
            ))
            return result
        catch failure
            progress_emit("error"; context=context, payload=Dict{String,Any}(
                "suboperation" => name,
                "error_type" => string(typeof(failure)),
                "message" => sprint(showerror, failure),
                "elapsed_seconds" => (time_ns() - started) / 1.0e9,
            ))
            rethrow()
        end
    end
end

const RADIAL_PROGRESS_SAMPLE_STRIDE = 512
const RADIAL_PROGRESS_INTERVAL_SECONDS = 15.0

"""
    observed_radial_map(radial_map, name, rho_in, rho_out)

Wrap the ρ → r map so a long radial integration reports its interior progress.

The GSN right-hand side evaluates the supplied map once per call, so counting
those calls and tracking the furthest ρ reached separates an integration that is
advancing slowly from one whose step size has collapsed.  The wrapper forwards
the original argument and returns the original value, so the radial solution is
unchanged.
"""
function observed_radial_map(radial_map, name::String, rho_in, rho_out)
    progress_active() || return radial_map
    started = time_ns()
    interval = round(UInt64, RADIAL_PROGRESS_INTERVAL_SECONDS * 1.0e9)
    evaluations = Ref(0)
    lowest = Ref(Inf)
    highest = Ref(-Inf)
    next_report = Ref(started + interval)
    span = abs(Float64(rho_out) - Float64(rho_in))
    context = Dict{String,Any}("suboperation" => name)
    return function (rho)
        evaluations[] += 1
        position = Float64(real(rho))
        position < lowest[] && (lowest[] = position)
        position > highest[] && (highest[] = position)
        if evaluations[] % RADIAL_PROGRESS_SAMPLE_STRIDE == 0
            sampled_at = time_ns()
            if sampled_at >= next_report[] && isfinite(lowest[]) && isfinite(highest[])
                next_report[] = sampled_at + interval
                covered = highest[] - lowest[]
                progress_emit("suboperation_progress"; context=context, payload=Dict{String,Any}(
                    "suboperation" => name,
                    "rhs_evaluations" => evaluations[],
                    "rho_current" => position,
                    "rho_reached_min" => lowest[],
                    "rho_reached_max" => highest[],
                    "rho_span" => span,
                    "rho_span_covered" => covered,
                    "rho_span_fraction" => span > zero(span) ? covered / span : nothing,
                    "elapsed_seconds" => (sampled_at - started) / 1.0e9,
                ))
            end
        end
        return radial_map(rho)
    end
end

required(request, key) = haskey(request, key) ? request[key] : error("missing request key $key")

function flatten_request(document)
    operation = string(required(document, "operation"))
    default_request_schema = operation == "fixed-root-determinant-sample" ?
        "windows-solver.fixed-root-determinant-sample/1" :
        "windows-solver.root-readout/1"
    execution_identity = validate_wire_execution_identity(
        document, default_request_schema
    )
    mode = required(document, "mode")
    omega = required(document, "omega")
    angular = required(document, "angular_A")
    amplitude = required(document, "amplitude")
    policy = required(document, "policy")
    execution_resource = required(document, "execution_resource")
    mechanism = string(required(document, "mechanism_id"))
    mechanism in ALLOWED_MECHANISMS ||
        error("unsupported mechanism_id $(repr(mechanism))")
    flattened = Dict{String,Any}(
        "schema_version" => required(document, "schema_version"),
        "operation" => required(document, "operation"),
        "job_id" => required(document, "job_id"),
        "leaf_id" => required(document, "leaf_id"),
        "role" => required(document, "role"),
        "job_policy_sha256" => required(document, "job_policy_sha256"),
        "backend_identity_sha256" =>
            required(document, "backend_identity_sha256"),
        "refinement_level" => required(document, "refinement_level"),
        "s" => required(mode, "s"),
        "ell" => required(mode, "ell"),
        "m" => required(mode, "m"),
        "n" => required(mode, "n"),
        "spin" => required(document, "spin"),
        "omega_re" => required(omega, "real"),
        "omega_im" => required(omega, "imaginary"),
        "angular_A_re" => required(angular, "real"),
        "angular_A_im" => required(angular, "imaginary"),
        "mechanism_id" => mechanism,
        "amplitude_re" => required(amplitude, "real"),
        "amplitude_im" => required(amplitude, "imaginary"),
        "precision_digits" => required(document, "precision_digits"),
        "working_precision_bits" => required(document, "working_precision_bits"),
        "semantic_precision_tier" => required(
            document, "semantic_precision_tier"
        ),
        "request_sha256" => required(document, "request_sha256"),
        "execution_identity" => execution_identity,
        "readout_radius" => required(policy, "readout_radius"),
        "ode_relative_tolerance" => required(policy, "ode_relative_tolerance"),
        "ode_absolute_tolerance" => required(policy, "ode_absolute_tolerance"),
        "homogeneous_ode_relative_tolerance" => required(
            policy, "homogeneous_ode_relative_tolerance"
        ),
        "homogeneous_ode_absolute_tolerance" => required(
            policy, "homogeneous_ode_absolute_tolerance"
        ),
        "coordinate_ode_relative_tolerance" => required(
            policy, "coordinate_ode_relative_tolerance"
        ),
        "coordinate_ode_absolute_tolerance" => required(
            policy, "coordinate_ode_absolute_tolerance"
        ),
        "endpoint_series_order" => required(policy, "endpoint_series_order"),
        "support_subinterval_count" => required(policy, "support_subinterval_count"),
        "angular_pad" => required(policy, "angular_pad"),
        "rho_in" => required(policy, "rho_in"),
        "rho_out" => required(policy, "rho_out"),
        "rho_out_candidate_schedule" => required(
            policy, "rho_out_candidate_schedule"
        ),
        "horizon_rho_inner_min" => required(policy, "horizon_rho_inner_min"),
        "horizon_endpoint_rho_floor" => required(
            policy, "horizon_endpoint_rho_floor"
        ),
        "horizon_endpoint_rho_candidates" => required(
            policy, "horizon_endpoint_rho_candidates"
        ),
        "horizon_maximum_endpoint_distance" => required(
            policy, "horizon_maximum_endpoint_distance"
        ),
        "frequency_step" => required(policy, "frequency_step"),
        "frequency_step_minimum" => required(policy, "frequency_step_minimum"),
        "frequency_step_maximum" => required(policy, "frequency_step_maximum"),
        "root_correction_tolerance" => required(
            policy, "root_correction_tolerance"
        ),
        "branch_enclosure_radius_abs" => required(
            policy, "branch_enclosure_radius_abs"
        ),
        "max_newton_iterations" => required(policy, "max_newton_iterations"),
        "promoted_root_readout_policy" => required(
            policy, "promoted_root_readout_policy"
        ),
        "resource_policy_schema" => required(execution_resource, "schema"),
        "resource_policy_version" => required(execution_resource, "version"),
        "resource_policy_sha256" => required(execution_resource, "sha256"),
        "worker_request_wall_clock_seconds" => required(
            execution_resource, "worker_request_wall_clock_seconds"
        ),
        "cooperative_request_deadline_seconds" => required(
            execution_resource, "cooperative_request_deadline_seconds"
        ),
        "homogeneous_ode_maxiters" => required(
            execution_resource, "homogeneous_ode_maxiters"
        ),
        "max_accepted_steps_per_homogeneous_leg" => required(
            execution_resource, "max_accepted_steps_per_homogeneous_leg"
        ),
        "max_rhs_evaluations_per_homogeneous_leg" => required(
            execution_resource, "max_rhs_evaluations_per_homogeneous_leg"
        ),
        "homogeneous_leg_wall_clock_seconds" => required(
            execution_resource, "homogeneous_leg_wall_clock_seconds"
        ),
        "coordinate_stall_rhs_threshold" => required(
            execution_resource, "coordinate_stall_rhs_threshold"
        ),
        "coordinate_stall_minimum_span_fraction" => required(
            execution_resource, "coordinate_stall_minimum_span_fraction"
        ),
        "coordinate_stall_minimum_step_fraction" => required(
            execution_resource, "coordinate_stall_minimum_step_fraction"
        ),
    )
    if string(required(document, "operation")) in (
        "root-readout", "fixed-root-determinant-sample"
    )
        flattened["diagnostic_model_identity"] = required(
            document, "diagnostic_model_identity"
        )
        flattened["required_raw_determinant_roles"] = required(
            document, "required_raw_determinant_roles"
        )
        flattened["required_raw_determinant_count"] = required(
            document, "required_raw_determinant_count"
        )
    end
    for key in (
        "homogeneous_representation",
        "asymptotic_series_evaluation",
        "conditioning_diagnostics",
        "branch_convention",
        "radial_derivative_convention",
        "regular_remainder_contract",
        "factored_remainder_state_convention",
        "reliable_digit_safety_margin",
        "required_digit_guard",
        "human_math_review_receipt_status",
        "human_math_review_receipt_sha256",
        "independent_reference_fixture_receipt_status",
        "independent_reference_fixture_receipt_sha256",
        "determinant_family",
        "scattering_diagnostics_applicable",
        "scattering_coefficient_extraction",
        "horizon_determinant_chart",
        "scattering_chart_safety_factor",
        "scattering_column_convention",
        "determinant_convention",
        "determinant_normalisation",
    )
        flattened[key] = required(policy, key)
    end
    # Introduced by the horizon rewrite, and carried only under the mechanism
    # they describe. Receipt reuse is decided by exact equality against the
    # policy mapping, so adding them as nulls on the exterior side would retire
    # every exterior receipt main ever produced for a change that never touched
    # that path.
    if mechanism == "horizon-admittance"
        for key in (
            "horizon_endpoint_recovery_policy_identity",
            "horizon_endpoint_maximum_order",
            "horizon_endpoint_prefix_minimum_order",
            "horizon_endpoint_prefix_order_step",
            "horizon_contour",
            "determinant_error_model",
            "determinant_error_safety_factor",
            "control_profile_label",
            "calibration_status",
        )
            flattened[key] = required(policy, key)
        end
    end
    if mechanism != "horizon-admittance"
        model = string(required(policy, "determinant_error_model"))
        fields = if model == EXTERIOR_ADDITIVE_CHANNEL_SCHEMA_ID
            (
                "determinant_error_model",
                "determinant_error_channel_schema",
                "determinant_error_required_channels",
                "determinant_error_calibration_status",
                "determinant_error_missing_evidence_outcome",
                "determinant_error_preceding_precision_tier",
            )
        elseif model == EXTERIOR_EMPIRICAL_ERROR_MODEL_ID
            (
                "determinant_error_model",
                "determinant_error_required_term_classes",
                "determinant_error_missing_evidence_outcome",
                "determinant_error_certificate_statement",
                "determinant_error_preceding_precision_tier",
                "determinant_error_safety_factor",
                "promoted_control_calibration_receipt_sha256",
                "empirical_control_profile_sha256",
            )
        else
            error("exterior request carries an unknown diagnostic model")
        end
        for key in fields
            flattened[key] = required(policy, key)
        end
        for key in (
            "determinant_error_channel_schema",
            "determinant_error_required_channels",
            "determinant_error_calibration_status",
            "determinant_error_required_term_classes",
            "determinant_error_certificate_statement",
            "determinant_error_safety_factor",
            "promoted_control_calibration_receipt_sha256",
            "empirical_control_profile_sha256",
        )
            haskey(policy, key) && (flattened[key] = policy[key])
        end
        support = required(document, "support")
        for key in ("lower", "upper", "centre", "half_width")
            flattened["support_$key"] = required(support, key)
        end
    end
    if haskey(document, "primary_predictor")
        predictor = required(document, "primary_predictor")
        flattened["primary_predictor_re"] = required(predictor, "real")
        flattened["primary_predictor_im"] = required(predictor, "imaginary")
        flattened["primary_predictor_kind"] = if haskey(
            document, "primary_predictor_kind"
        )
            required(document, "primary_predictor_kind")
        else
            "EPSILON_CONTINUATION"
        end
    end
    if string(required(document, "operation")) ==
            "fixed-root-determinant-sample"
        fixed_omega = required(document, "fixed_omega")
        flattened["fixed_omega_re"] = required(fixed_omega, "real")
        flattened["fixed_omega_im"] = required(fixed_omega, "imaginary")
        flattened["readout_role"] = required(document, "readout_role")
    end
    return flattened
end

function validate_raw_determinant_contract(request)
    for key in (
        "diagnostic_model_identity",
        "required_raw_determinant_roles",
        "required_raw_determinant_count",
    )
        haskey(request, key) || error("raw determinant contract lacks $(key)")
    end
    model = string(required(request, "diagnostic_model_identity"))
    roles = required(request, "required_raw_determinant_roles")
    roles isa Vector && all(item -> item isa String, roles) ||
        error("raw determinant roles are invalid")
    length(unique(roles)) == length(roles) ||
        error("raw determinant roles contain duplicates")
    declared_count = required(request, "required_raw_determinant_count")
    declared_count isa Integer && !(declared_count isa Bool) ||
        error("raw determinant count is invalid")
    declared_count == length(roles) ||
        error("raw determinant role/count binding is invalid")

    expected_roles = if model == VERIFIED_ENDPOINT_ERROR_MODEL_ID
        ["PRIMARY"]
    elseif model == EXTERIOR_ADDITIVE_CHANNEL_SCHEMA_ID
        ["PRIMARY"]
    elseif model == EXTERIOR_EMPIRICAL_ERROR_MODEL_ID
        ["PRIMARY", "TRUNCATION", "RESOLUTION"]
    else
        error("unknown diagnostic model identity")
    end
    roles == expected_roles || error("raw determinant roles do not match model")
    mechanism = string(required(request, "mechanism_id"))
    if model == VERIFIED_ENDPOINT_ERROR_MODEL_ID
        mechanism == "horizon-admittance" ||
            error("horizon diagnostic model is bound to the wrong mechanism")
    else
        mechanism != "horizon-admittance" ||
            error("exterior diagnostic model is bound to the horizon mechanism")
    end
    string(required(request, "determinant_error_model")) == model ||
        error("diagnostic model identity is not policy-bound")
    if model == EXTERIOR_ADDITIVE_CHANNEL_SCHEMA_ID
        for key in (
            "determinant_error_required_term_classes",
            "determinant_error_certificate_statement",
            "determinant_error_safety_factor",
            "promoted_control_calibration_receipt_sha256",
            "empirical_control_profile_sha256",
        )
            !haskey(request, key) ||
                error("provisional diagnostic model carries empirical field $(key)")
        end
    end
    return nothing
end

function validate_regularised_gsn_policy(request)
    expected_common = Dict{String,Any}(
        "asymptotic_series_evaluation" => ASYMPTOTIC_SERIES_EVALUATION_ID,
        "conditioning_diagnostics" => CONDITIONING_DIAGNOSTICS_ID,
        "branch_convention" => BRANCH_CONVENTION_ID,
        "radial_derivative_convention" => RADIAL_DERIVATIVE_CONVENTION_ID,
        "regular_remainder_contract" => REGULAR_REMAINDER_CONTRACT_ID,
        "factored_remainder_state_convention" =>
            FACTORED_REMAINDER_STATE_CONVENTION_ID,
        "reliable_digit_safety_margin" =>
            string(RELIABLE_DIGIT_SAFETY_MARGIN),
        "required_digit_guard" => string(ROOT_READOUT_REQUIRED_DIGIT_GUARD),
        "human_math_review_receipt_status" =>
            HUMAN_MATH_REVIEW_RECEIPT_STATUS,
        "human_math_review_receipt_sha256" =>
            HUMAN_MATH_REVIEW_RECEIPT_SHA256,
        "independent_reference_fixture_receipt_status" =>
            INDEPENDENT_REFERENCE_FIXTURE_RECEIPT_STATUS,
        "independent_reference_fixture_receipt_sha256" =>
            INDEPENDENT_REFERENCE_FIXTURE_RECEIPT_SHA256,
        "promoted_root_readout_policy" =>
            PROMOTED_ROOT_READOUT_POLICY_ID,
    )
    for (key, expected) in expected_common
        required(request, key) == expected ||
            error("regularised GSN policy identity $(key) is invalid")
    end

    if haskey(request, "diagnostic_model_identity")
        validate_raw_determinant_contract(request)
    end

    horizon = string(required(request, "mechanism_id")) ==
        "horizon-admittance"
    expected_mechanism = if horizon
        Dict{String,Any}(
            # The horizon family builds a solution basis from three
            # independent legs on a verified real-inner contour, so it carries
            # its own representation, contour, extraction, and error-model
            # identities. Receipts written under the previous horizon
            # identities describe a different calculation.
            "homogeneous_representation" =>
                HORIZON_HOMOGENEOUS_REPRESENTATION_ID,
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
            "determinant_convention" =>
                HORIZON_DETERMINANT_CONVENTION_ID,
            "determinant_normalisation" =>
                HORIZON_DETERMINANT_NORMALISATION_ID,
            "horizon_contour" => REAL_INNER_HORIZON_CONTOUR_ID,
            "determinant_error_model" => VERIFIED_ENDPOINT_ERROR_MODEL_ID,
            "control_profile_label" => PROMOTED_CONTROL_PROFILE_LABEL,
            "calibration_status" =>
                PROMOTED_CONTROL_PROFILE_CALIBRATION_STATUS,
        )
    else
        exterior = Dict{String,Any}(
            "homogeneous_representation" => HOMOGENEOUS_REPRESENTATION_ID,
            "determinant_family" => EXTERIOR_DETERMINANT_FAMILY_ID,
            "scattering_diagnostics_applicable" => false,
            "scattering_coefficient_extraction" => nothing,
            "horizon_determinant_chart" => nothing,
            "scattering_chart_safety_factor" => nothing,
            "scattering_column_convention" => nothing,
            "determinant_convention" =>
                EXTERIOR_DETERMINANT_CONVENTION_ID,
            "determinant_normalisation" =>
                EXTERIOR_DETERMINANT_NORMALISATION_ID,
        )
        model = string(required(request, "determinant_error_model"))
        preceding_tier = Dict(
            40 => "binary64", 80 => "bigfloat-40", 120 => "bigfloat-80"
        )[parse_integer(request, "precision_digits")]
        if model == EXTERIOR_ADDITIVE_CHANNEL_SCHEMA_ID
            merge!(exterior, Dict{String,Any}(
                "determinant_error_model" => model,
                "determinant_error_channel_schema" => model,
                "determinant_error_required_channels" => EXTERIOR_ADDITIVE_CHANNELS,
                "determinant_error_calibration_status" =>
                    EXTERIOR_ADDITIVE_CALIBRATION_STATUS,
                "determinant_error_missing_evidence_outcome" =>
                    EXTERIOR_ADDITIVE_MISSING_OUTCOME,
                "determinant_error_preceding_precision_tier" => preceding_tier,
            ))
        elseif model == EXTERIOR_EMPIRICAL_ERROR_MODEL_ID
            merge!(exterior, Dict{String,Any}(
                "determinant_error_model" => model,
                "determinant_error_required_term_classes" =>
                    EXTERIOR_EMPIRICAL_ERROR_TERM_CLASSES,
                "determinant_error_missing_evidence_outcome" =>
                    EXTERIOR_EMPIRICAL_ERROR_MISSING_OUTCOME,
                "determinant_error_certificate_statement" =>
                    EXTERIOR_EMPIRICAL_ERROR_STATEMENT,
                "determinant_error_preceding_precision_tier" => preceding_tier,
                "determinant_error_safety_factor" =>
                    EXTERIOR_EMPIRICAL_ERROR_SAFETY_FACTOR,
                "promoted_control_calibration_receipt_sha256" =>
                    required(request, "promoted_control_calibration_receipt_sha256"),
                "empirical_control_profile_sha256" =>
                    required(request, "empirical_control_profile_sha256"),
            ))
        else
            error("exterior request carries an unknown diagnostic model")
        end
        exterior
    end
    for (key, expected) in expected_mechanism
        isequal(required(request, key), expected) ||
            error("regularised GSN mechanism policy $(key) is invalid")
    end
    if !horizon &&
       string(required(request, "determinant_error_model")) ==
       EXTERIOR_EMPIRICAL_ERROR_MODEL_ID
        safety = required(request, "determinant_error_safety_factor")
        safety isa Integer && !(safety isa Bool) &&
            safety == EXTERIOR_EMPIRICAL_ERROR_SAFETY_FACTOR ||
            error(
                "exterior empirical determinant_error_safety_factor is invalid"
            )
        for key in (
            "promoted_control_calibration_receipt_sha256",
            "empirical_control_profile_sha256",
        )
            value = string(required(request, key))
            occursin(r"^[0-9a-f]{64}$", value) ||
                error("exterior empirical receipt hash is invalid")
        end
    end
    # The horizon-only identities must be absent from an exterior request, not
    # merely null. A null would still change the exterior policy mapping, and
    # receipt reuse is decided by exact equality against it.
    if !horizon
        for key in (
            "horizon_contour",
            "control_profile_label",
            "calibration_status",
        )
            haskey(request, key) &&
                error("exterior request carries horizon-only policy $(key)")
        end
    end
    return nothing
end

function parse_real(::Type{T}, request, key) where {T<:AbstractFloat}
    return parse(T, string(required(request, key)))
end

parse_integer(request, key) = parse(Int, string(required(request, key)))

function parse_complex(::Type{T}, request, real_key, imaginary_key) where {T<:AbstractFloat}
    return Complex{T}(
        parse_real(T, request, real_key),
        parse_real(T, request, imaginary_key),
    )
end

function Fslm(::Type{T}, s::Int, ell::Int, m::Int) where {T<:AbstractFloat}
    ell + 1 == 0 && s == 0 && return zero(T)
    ep = T(ell + 1)
    return sqrt(((ep^2 - T(m)^2) / (T(2ell + 3) * T(2ell + 1))) *
                ((ep^2 - T(s)^2) / ep^2))
end

function Gslm(::Type{T}, s::Int, ell::Int, m::Int) where {T<:AbstractFloat}
    ell == 0 && return zero(T)
    e = T(ell)
    return sqrt(((e^2 - T(m)^2) / (T(4) * e^2 - one(T))) *
                ((e^2 - T(s)^2) / e^2))
end

function Hslm(::Type{T}, s::Int, ell::Int, m::Int) where {T<:AbstractFloat}
    (ell == 0 || s == 0) && return zero(T)
    return -T(m * s) / T(ell * (ell + 1))
end

function angular_matrix(::Type{T}, c::Complex{T}, s::Int, m::Int, count::Int) where {T<:AbstractFloat}
    ell_min = max(abs(s), abs(m))
    matrix = zeros(Complex{T}, count, count)
    for row in 1:count
        ell = ell_min + row - 1
        for column in max(1, row - 2):min(count, row + 2)
            ell_prime = ell_min + column - 1
            value = zero(Complex{T})
            if ell_prime == ell - 2
                value = -c^2 * Fslm(T, s, ell_prime, m) * Fslm(T, s, ell_prime + 1, m)
            elseif ell_prime == ell - 1
                value = -c^2 * Fslm(T, s, ell_prime, m) *
                    (Hslm(T, s, ell_prime + 1, m) + Hslm(T, s, ell_prime, m)) +
                    T(2) * c * T(s) * Fslm(T, s, ell_prime, m)
            elseif ell_prime == ell
                diagonal = T(ell_prime * (ell_prime + 1) - s * (s + 1))
                b = Fslm(T, s, ell_prime, m) * Gslm(T, s, ell_prime + 1, m) +
                    Gslm(T, s, ell_prime, m) * Fslm(T, s, ell_prime - 1, m) +
                    Hslm(T, s, ell_prime, m)^2
                value = diagonal - c^2 * b + T(2) * c * T(s) * Hslm(T, s, ell_prime, m)
            elseif ell_prime == ell + 1
                value = -c^2 * Gslm(T, s, ell_prime, m) *
                    (Hslm(T, s, ell_prime - 1, m) + Hslm(T, s, ell_prime, m)) +
                    T(2) * c * T(s) * Gslm(T, s, ell_prime, m)
            elseif ell_prime == ell + 2
                value = -c^2 * Gslm(T, s, ell_prime, m) * Gslm(T, s, ell_prime - 1, m)
            end
            matrix[row, column] = value
        end
    end
    return matrix
end

function bigfloat_angular_A(c::Complex{T}, s::Int, ell::Int, m::Int, count::Int,
                            seed::Complex{T}, digits::Int) where {T<:AbstractFloat}
    matrix = angular_matrix(T, c, s, m, count)
    value = seed
    h = Complex{T}(T(10)^(-max(18, digits ÷ 2)), zero(T))
    target = T(10)^(-max(30, digits - 12))
    characteristic(candidate) = det(matrix - candidate * I)
    for _ in 1:30
        residual = characteristic(value)
        abs(residual) <= target && return value
        derivative = (characteristic(value + h) - characteristic(value - h)) / (T(2) * h)
        iszero(derivative) && error("singular BigFloat angular characteristic derivative")
        step = residual / derivative
        value -= step
        abs(step) <= target * max(one(T), abs(value)) && return value
    end
    error("BigFloat angular eigenvalue continuation did not converge")
end

function angular_constants(::Type{Float64}, s, ell, m, a, omega, seed_A, pad, digits)
    c = a * omega
    ell_min = max(abs(s), abs(m))
    count = ell + pad - ell_min + 1
    lambda = SpinWeightedSpheroidalHarmonics.spin_weighted_spheroidal_eigenvalue(
        s, ell, m, c; N=count
    )
    A = lambda - c^2 + 2m * c
    return ComplexF64(A), ComplexF64(lambda)
end

function angular_constants(::Type{BigFloat}, s, ell, m, a, omega, seed_A, pad, digits)
    T = BigFloat
    c = a * omega
    ell_min = max(abs(s), abs(m))
    count = ell + pad - ell_min + 1
    A = bigfloat_angular_A(c, s, ell, m, count, seed_A, digits)
    return A, A + c^2 - T(2m) * c
end

struct DeterminantDiagnostics{T<:AbstractFloat}
    representation_id::String
    determinant_family::String
    scattering_diagnostics_applicable::Bool
    maximum_series_digits_lost::T
    maximum_recurrence_digits_lost::T
    maximum_series_evaluation_spread::T
    maximum_last_term_ratio::T
    minimum_asymptotic_predicted_reliable_digits::T
    maximum_basis_condition::Union{Nothing,T}
    maximum_basis_backward_error::Union{Nothing,T}
    maximum_matching_reconstruction_residual::Union{Nothing,T}
    endpoint_remainders_regular::Bool
    maximum_endpoint_reconstruction_error::T
    raw_determinant_abs::Union{Nothing,T}
    raw_determinant_evidence_status::String
    normalised_determinant_abs::T
    minimum_cref_chart_margin::Union{Nothing,T}
    maximum_carrier_change_error::Union{Nothing,T}
    maximum_contour_angle_deformation::T
end

const VERIFIED_ENDPOINT_ERROR_MODEL_ID =
    "verified-endpoint-control-equivalence-absolute-error/v2"
const PROMOTED_CONTROL_PROFILE_LABEL = "provisional promoted control profile"
const PROMOTED_CONTROL_PROFILE_CALIBRATION_STATUS = "UNMEASURED"

struct DeterminantErrorBreakdown{T<:AbstractFloat}
    endpoint_disagreement_abs::T
    control_disagreement_abs::Union{Nothing,T}
    equivalence_disagreement_abs::Union{Nothing,T}
    precision_disagreement_abs::Union{Nothing,T}
    safety_factor::T
    numerical_error_abs::T

    function DeterminantErrorBreakdown{T}(
        endpoint_disagreement_abs::T,
        control_disagreement_abs::Union{Nothing,T},
        equivalence_disagreement_abs::Union{Nothing,T},
        precision_disagreement_abs::Union{Nothing,T},
        safety_factor::T,
        numerical_error_abs::T,
    ) where {T<:AbstractFloat}
        available_components = T[endpoint_disagreement_abs]
        for component in (
            control_disagreement_abs,
            equivalence_disagreement_abs,
            precision_disagreement_abs,
        )
            component === nothing || push!(available_components, component)
        end
        all(value -> isfinite(value) && value >= zero(T), available_components) ||
            throw(ArgumentError(
                "determinant error components must be finite and nonnegative"
            ))
        isfinite(safety_factor) && safety_factor > zero(T) ||
            throw(ArgumentError(
                "determinant error safety factor must be finite and positive"
            ))
        expected_error_abs = safety_factor * maximum(available_components)
        isfinite(expected_error_abs) || throw(ArgumentError(
            "determinant numerical error is nonfinite"
        ))
        numerical_error_abs == expected_error_abs || throw(ArgumentError(
            "determinant numerical error does not match its component maximum"
        ))
        new{T}(
            endpoint_disagreement_abs,
            control_disagreement_abs,
            equivalence_disagreement_abs,
            precision_disagreement_abs,
            safety_factor,
            numerical_error_abs,
        )
    end
end

struct UnresolvedDerivativeAuthentication{T<:AbstractFloat} <: Exception
    lower_bound_abs::T
    message::String
end

Base.showerror(io::IO, failure::UnresolvedDerivativeAuthentication) =
    print(io, failure.message)

struct DerivativeAuthentication{T<:AbstractFloat}
    value::Complex{T}
    propagated_error_abs::T
    step_disagreement_abs::T
    lower_bound_abs::T
    step::T
    axis::String

    function DerivativeAuthentication{T}(
        value::Complex{T},
        propagated_error_abs::T,
        step_disagreement_abs::T,
        step::T,
        axis::String,
    ) where {T<:AbstractFloat}
        axis in ("real", "imaginary") || throw(ArgumentError(
            "authenticated derivative axis is invalid"
        ))
        lower_bound_abs = abs(value) - step_disagreement_abs -
            propagated_error_abs
        valid = all(isfinite, (
            real(value),
            imag(value),
            propagated_error_abs,
            step_disagreement_abs,
            lower_bound_abs,
            step,
        )) && propagated_error_abs >= zero(T) &&
            step_disagreement_abs >= zero(T) && step > zero(T) &&
            lower_bound_abs > zero(T)
        valid || throw(UnresolvedDerivativeAuthentication{T}(
            lower_bound_abs,
            "derivative authentication has no finite positive lower bound",
        ))
        new{T}(
            value,
            propagated_error_abs,
            step_disagreement_abs,
            lower_bound_abs,
            step,
            axis,
        )
    end
end

function derivative_authentication_candidate(
    value::Complex{T},
    propagated_error_abs::T,
    step_disagreement_abs::T,
    step::T,
    axis::String,
) where {T<:AbstractFloat}
    try
        authentication = DerivativeAuthentication{T}(
            value,
            propagated_error_abs,
            step_disagreement_abs,
            step,
            axis,
        )
        return (
            authentication=authentication,
            lower_bound_abs=authentication.lower_bound_abs,
        )
    catch failure
        failure isa UnresolvedDerivativeAuthentication || rethrow()
        return (
            authentication=nothing,
            lower_bound_abs=failure.lower_bound_abs,
        )
    end
end

struct RootAuthentication{T<:AbstractFloat}
    central_determinant::Complex{T}
    error_breakdown::Union{Nothing,DeterminantErrorBreakdown{T}}
    residual_upper_bound_abs::T
    derivative::DerivativeAuthentication{T}
    correction_upper_bound::T
    error_model_id::Union{Nothing,String}
    root_correction_tolerance::T
    accepted::Bool
    authentication_strategy::String
    derivative_real_base::Complex{T}
    derivative_real_half::Complex{T}
    derivative_real_double::Union{Nothing,Complex{T}}
    derivative_imaginary::Union{Nothing,Complex{T}}
end

"""
    DeterminantEvaluation

A determinant value together with a bound on its own numerical error.

`numerical_error_abs` is an *absolute* bound on |D|, never a relative one. The
QNM condition is Cinc = 0, so near a root the determinant is a small quantity
whose relative accuracy is necessarily poor; that is expected and is not
evidence of ill conditioning. What decides whether a root is resolved is the
absolute determinant error measured against the local |D'| scale, which is what
Newton acceptance consumes.

The horizon family must always populate it. The exterior family is unchanged in
this revision and may leave it `nothing`, in which case acceptance falls back to
the historical contract.
"""
struct DeterminantEvaluation{T<:AbstractFloat}
    value::Complex{T}
    error_breakdown::Union{Nothing,DeterminantErrorBreakdown{T}}
    error_model_id::Union{Nothing,String}
    diagnostics::DeterminantDiagnostics{T}
end

DeterminantEvaluation{T}(
    value::Complex{T}, diagnostics::DeterminantDiagnostics{T}
) where {T<:AbstractFloat} =
    DeterminantEvaluation{T}(value, nothing, nothing, diagnostics)

struct FiniteDifferenceDiagnostics{T<:AbstractFloat}
    d_plus_abs::T
    d_minus_abs::T
    difference_abs::T
    kappa::T
    finite_difference_digits_lost::T
    derivative_abs::T
    h::T
    axis::String
    d_plus_abs_saturated::Bool
    d_plus_abs_underflowed::Bool
    d_minus_abs_saturated::Bool
    d_minus_abs_underflowed::Bool
    difference_abs_saturated::Bool
    difference_abs_underflowed::Bool
    kappa_saturated::Bool
    kappa_underflowed::Bool
    kappa_is_infinite::Bool
    kappa_is_indeterminate::Bool
    derivative_abs_saturated::Bool
    derivative_abs_underflowed::Bool
    underflow_observed::Bool
    saturation_observed::Bool
    saturation_status::String
end

struct FiniteDifferenceRangeError <: Exception
    message::String
    status::String
end

Base.showerror(io::IO, failure::FiniteDifferenceRangeError) =
    print(io, failure.message)

mutable struct ConditioningAccumulator{T<:AbstractFloat}
    maximum_series_digits_lost::T
    maximum_recurrence_digits_lost::T
    maximum_series_evaluation_spread::T
    maximum_last_term_ratio::T
    minimum_asymptotic_predicted_reliable_digits::Union{Nothing,T}
    maximum_basis_condition::Union{Nothing,T}
    maximum_basis_backward_error::Union{Nothing,T}
    maximum_matching_reconstruction_residual::Union{Nothing,T}
    endpoint_remainders_regular::Bool
    maximum_endpoint_reconstruction_error::T
    maximum_fd_digits_lost::T
    finite_difference_saturation_observed::Bool
    finite_difference_underflow_observed::Bool
    minimum_cref_chart_margin::Union{Nothing,T}
    maximum_carrier_change_error::Union{Nothing,T}
    maximum_contour_angle_deformation::T
    horizon_endpoint_search_evidence::Vector{Any}
    exterior_endpoint_recovery_evidence::Vector{Any}
    determinant_count::Int
end

function ConditioningAccumulator(::Type{T}) where {T<:AbstractFloat}
    return ConditioningAccumulator{T}(
        zero(T),
        zero(T),
        zero(T),
        zero(T),
        nothing,
        nothing,
        nothing,
        nothing,
        true,
        zero(T),
        zero(T),
        false,
        false,
        nothing,
        nothing,
        zero(T),
        Any[],
        Any[],
        0,
    )
end

struct AuthenticatedDeterminantEvidence{T<:AbstractFloat}
    request::Dict{String,Any}
    frozen_convention::GSNBranchConvention{T}
    frozen_branch_cell::GSN.GSNBranchCell
    omega::Complex{T}
    amplitude::Complex{T}
    evaluation
    source_phase::String
end

mutable struct AuthenticatedDeterminantEvidenceStore
    entries::Vector{Any}
end

AuthenticatedDeterminantEvidenceStore() =
    AuthenticatedDeterminantEvidenceStore(Any[])

struct DeterminantRequestContext{T<:AbstractFloat}
    frozen_convention::GSNBranchConvention{T}
    frozen_branch_cell::GSN.GSNBranchCell
    conditioning::ConditioningAccumulator{T}
    authenticated_evidence::AuthenticatedDeterminantEvidenceStore
end

function build_determinant_request_context(
    ::Type{T}, request, reference_omega::Complex{T}
) where {T<:AbstractFloat}
    a = parse_real(T, request, "spin")
    m = parse_integer(request, "m")
    geometry = Kerr.stable_horizon_geometry(a)
    p_horizon = reference_omega - T(m) * geometry.omega_horizon
    frozen_convention = GSN.gsn_branch_convention(
        reference_omega, p_horizon
    )
    return DeterminantRequestContext{T}(
        frozen_convention,
        GSN.branch_cell(frozen_convention),
        ConditioningAccumulator(T),
        AuthenticatedDeterminantEvidenceStore(),
    )
end

function authenticated_determinant_inputs_match(
    evidence::AuthenticatedDeterminantEvidence{T},
    request,
    context::DeterminantRequestContext{T},
    omega::Complex{T},
    amplitude::Complex{T},
) where {T<:AbstractFloat}
    return isequal(evidence.request, request) &&
        evidence.omega == omega &&
        evidence.amplitude == amplitude &&
        GSN.full_convention_equal(
            evidence.frozen_convention, context.frozen_convention
        ) &&
        evidence.frozen_branch_cell == context.frozen_branch_cell
end

function remember_authenticated_determinant!(
    context::DeterminantRequestContext{T},
    request,
    omega::Complex{T},
    amplitude::Complex{T},
    evaluation,
    source_phase::String,
) where {T<:AbstractFloat}
    evidence = AuthenticatedDeterminantEvidence{T}(
        deepcopy(Dict{String,Any}(request)),
        context.frozen_convention,
        context.frozen_branch_cell,
        omega,
        amplitude,
        evaluation,
        source_phase,
    )
    push!(context.authenticated_evidence.entries, evidence)
    return evaluation
end

function matching_authenticated_determinant(
    context::DeterminantRequestContext{T},
    request,
    omega::Complex{T},
    amplitude::Complex{T},
) where {T<:AbstractFloat}
    for evidence in Iterators.reverse(
        context.authenticated_evidence.entries
    )
        evidence isa AuthenticatedDeterminantEvidence{T} || continue
        authenticated_determinant_inputs_match(
            evidence, request, context, omega, amplitude
        ) && return evidence
    end
    return nothing
end

function reuse_authenticated_determinant(
    context::DeterminantRequestContext{T},
    request,
    omega::Complex{T},
    amplitude::Complex{T},
) where {T<:AbstractFloat}
    evidence = matching_authenticated_determinant(
        context, request, omega, amplitude
    )
    return evidence === nothing ? nothing : evidence.evaluation
end

function phase_control_identity(request)
    # This is deliberately stricter than the minimum reuse contract: every
    # flattened request input is represented, so changing any numerical,
    # branch, endpoint, angular, extraction, or error-model control prevents
    # reuse. Operational differences may conservatively prevent reuse; they can
    # never permit reuse across different scientific calculations.
    keys_sorted = sort!(collect(keys(request)))
    return join(
        ("$(key)=$(repr(request[key]))" for key in keys_sorted),
        "|",
    )
end

function fixed_root_reliability_projection(request)
    projection = required(request, "fixed_root_reliability_projection")
    projection isa AbstractDict ||
        error("fixed-root reliability projection is invalid")
    Set(keys(projection)) == Set((
        "schema",
        "source_reliability_projection_authority_schema",
        "source_reliability_projection_authority_identity",
        "source_reliability_projection_authority_sha256",
        "source_calibration_receipt_sha256",
        "source_empirical_control_profile_sha256",
        "source_refinement_level",
        "fixed_root_reliability_target_abs",
        "fixed_root_reliability_rule",
        "required_digit_guard",
        "projection_sha256",
    )) || error("fixed-root reliability projection fields are invalid")
    string(required(projection, "schema")) ==
        FIXED_ROOT_RELIABILITY_PROJECTION_SCHEMA ||
        error("fixed-root reliability projection schema is invalid")

    authority = fixed_root_reliability_projection_authority()
    authority_schema = string(required(authority, "schema"))
    authority_identity = string(required(authority, "identity"))
    authority_sha256 = string(required(authority, "authority_sha256"))
    authority_rule = string(required(authority, "fixed_root_reliability_rule"))
    authority_guard = Int(required(authority, "required_digit_guard"))
    policy_control_fields = String[
        string(field) for field in
        required(authority, "fixed_root_policy_control_fields")
    ]
    target_control_field = string(required(
        authority, "fixed_root_reliability_target_control_field"
    ))

    raw_receipt = read(PROMOTED_CONTROL_CALIBRATION_RECEIPT_PATH)
    receipt_sha256 = bytes2hex(SHA.sha256(raw_receipt))
    receipt_sha256 ==
        string(required(projection, "source_calibration_receipt_sha256")) ||
        error("fixed-root reliability calibration authority is invalid")
    receipt_text = String(raw_receipt)
    receipt = JSON.parse(receipt_text)
    canonical_json(receipt) == receipt_text ||
        error("fixed-root reliability calibration receipt is not canonical")
    string(required(receipt, "schema")) ==
        string(required(authority, "calibration_receipt_schema")) ||
        error("fixed-root reliability calibration schema is invalid")
    string(required(receipt, "identity")) ==
        string(required(authority, "calibration_receipt_identity")) ||
        error("fixed-root reliability calibration identity is invalid")

    digits = parse_integer(request, "precision_digits")
    tier = string(required(request, "semantic_precision_tier"))
    determinant_family = string(required(request, "determinant_family"))
    entries = required(receipt, "budget_entries")
    entries isa Vector ||
        error("fixed-root reliability calibration budgets are invalid")
    profiles = [
        entry for entry in entries
        if entry isa AbstractDict &&
            string(required(entry, "determinant_family")) == determinant_family &&
            parse_integer(entry, "nominal_decimal_digits") == digits &&
            string(required(entry, "precision_tier")) == tier
    ]
    length(profiles) == 1 ||
        error("fixed-root reliability calibration profile is unavailable")
    profile = only(profiles)
    profile_sha256 = canonical_sha256(profile)
    profile_sha256 ==
        string(required(projection, "source_empirical_control_profile_sha256")) ||
        error("fixed-root reliability profile authority is invalid")

    refinement = required(projection, "source_refinement_level")
    refinement isa Integer && !(refinement isa Bool) && refinement in (0, 1) ||
        error("fixed-root reliability refinement is invalid")
    controls = required(
        profile, refinement == 0 ? "base_controls" : "refinement_controls"
    )
    controls isa AbstractDict ||
        error("fixed-root reliability calibration controls are invalid")
    for field in policy_control_fields
        isequal(required(request, field), required(controls, field)) ||
            error("fixed-root reliability calibration controls disagree")
    end
    target = string(required(controls, target_control_field))
    expected_binding = Dict{String,Any}(
        "schema" => FIXED_ROOT_RELIABILITY_PROJECTION_SCHEMA,
        "source_reliability_projection_authority_schema" => authority_schema,
        "source_reliability_projection_authority_identity" => authority_identity,
        "source_reliability_projection_authority_sha256" => authority_sha256,
        "source_calibration_receipt_sha256" => receipt_sha256,
        "source_empirical_control_profile_sha256" => profile_sha256,
        "source_refinement_level" => refinement,
        "fixed_root_reliability_target_abs" => target,
        "fixed_root_reliability_rule" => authority_rule,
        "required_digit_guard" => authority_guard,
    )
    observed_binding = Dict{String,Any}(
        string(key) => value for (key, value) in projection
        if string(key) != "projection_sha256"
    )
    observed_binding == expected_binding ||
        error("fixed-root reliability projection is unauthorised")
    canonical_sha256(expected_binding) ==
        string(required(projection, "projection_sha256")) ||
        error("fixed-root reliability projection digest is invalid")
    return projection
end

function required_reliable_digits(::Type{T}, request) where {T<:AbstractFloat}
    operation = string(required(request, "operation"))
    tolerance, guard = if operation == FIXED_ROOT_SURVEY_BATCH_OPERATION
        projection = fixed_root_reliability_projection(request)
        authority = fixed_root_reliability_projection_authority()
        (
            parse_real(
                T, projection, "fixed_root_reliability_target_abs"
            ),
            Int(required(authority, "required_digit_guard")),
        )
    elseif operation in ("root-readout", "fixed-root-determinant-sample")
        (
            parse_real(T, request, "root_correction_tolerance"),
            ROOT_READOUT_REQUIRED_DIGIT_GUARD,
        )
    else
        error("reliable-digit policy is undefined for this operation")
    end
    zero(T) < tolerance < one(T) ||
        error("reliability target must lie strictly between zero and one")
    return -log10(tolerance) + T(guard)
end

function build_sample_spectral_context(
    ::Type{T},
    request,
    omega::Complex{T},
    context::DeterminantRequestContext{T},
) where {T<:AbstractFloat}
    s = parse_integer(request, "s")
    ell = parse_integer(request, "ell")
    m = parse_integer(request, "m")
    digits = parse_integer(request, "precision_digits")
    bits = parse_integer(request, "working_precision_bits")
    pad = parse_integer(request, "angular_pad")
    a = parse_real(T, request, "spin")
    seed_A = parse_complex(T, request, "angular_A_re", "angular_A_im")
    _, lambda = progress_operation("angular") do
        angular_constants(T, s, ell, m, a, omega, seed_A, pad, digits)
    end
    base_endpoint_order = parse_integer(request, "endpoint_series_order")
    generated_endpoint_order = string(required(request, "mechanism_id")) ==
        "horizon-admittance" ?
        horizon_endpoint_maximum_order(request, base_endpoint_order) :
        get(request, "operation", nothing) ==
            FIXED_ROOT_SURVEY_BATCH_OPERATION ?
            parse_integer(
                required(request, "fixed_root_endpoint_recovery_policy"),
                "generated_maximum_order",
            ) : base_endpoint_order
    spectral = CF.build_homogeneous_spectral_context(
        s,
        m,
        a,
        omega,
        lambda,
        digits,
        bits,
        generated_endpoint_order,
        context.frozen_convention,
    )
    spectral.frozen_branch_cell == context.frozen_branch_cell ||
        error("sample spectral context changed the request branch cell")
    spectral.frozen_branch_cell.version == BRANCH_CONVENTION_ID ||
        error("sample spectral context changed the branch convention identity")
    return spectral
end

"""
    coordinate_ode_tolerances(T, request)

Return the coordinate-map ODE tolerances.

The coordinate inversion is a scalar quadrature for r(rho); it is not the
homogeneous GSN solve and must not inherit its local-error target. Driving it
at the homogeneous tolerance is what pinned Leaf 13 at 8.1e-17 steps. The
coordinate map only has to be accurate enough not to dominate the determinant
error budget, which is what the calibration harness measures.
"""
function coordinate_ode_tolerances(::Type{T}, request) where {T<:AbstractFloat}
    return (
        reltol=parse_real(T, request, "coordinate_ode_relative_tolerance"),
        abstol=parse_real(T, request, "coordinate_ode_absolute_tolerance"),
    )
end

"""
    build_worker_contour_context(T, request, spectral, match_radius, label)

Build the joined contour context used by the exterior determinant family.

The horizon determinant no longer uses this: it builds an outer-only map and a
separate real-inner horizon map, so nothing constructs a -5000 -> +5000 joined
coordinate solve for a horizon calculation that reads at most ~100 units inside.
"""
function build_worker_contour_context(
    ::Type{T},
    request,
    spectral::CF.HomogeneousSpectralContext{T},
    match_radius::T,
    label::String,
) where {T<:AbstractFloat}
    rho_in = parse_real(T, request, "rho_in")
    rho_out = parse_real(T, request, "rho_out")
    rstar_match = T(GSN.rstar_from_r(spectral.a, match_radius))
    algorithm = AutoVern9(Rosenbrock23(autodiff=false))
    tolerances = coordinate_ode_tolerances(T, request)
    observation_factory = (leg, tspan, ode_algorithm) ->
        ode_observation_factory(request, leg, tspan, ode_algorithm)
    raw_radius_from_rho = progress_operation("r-from-rho"; payload=Dict(
        "contour_label" => label,
    )) do
        CF.solve_r_from_rho(
            spectral.a,
            spectral.convention.horizon_contour_angle,
            spectral.convention.infinity_contour_angle,
            rstar_match,
            rho_in,
            rho_out;
            sign_neg=spectral.convention.horizon_sign,
            sign_pos=spe…50097 tokens truncated…NANT_INDEX_PHASE[];
        residual_upper_bound_abs=residual_upper_bound_abs,
        derivative_lower_bound_abs=derivative_lower_bound_abs,
        required_derivative_lower_bound_abs=
            required_derivative_lower_bound_abs,
        correction_upper_bound=correction_upper_bound,
        root_correction_tolerance=tolerance,
        raw_step_disagreement_abs=raw_step_disagreement_abs,
        guarded_step_disagreement_abs=guarded_step_disagreement_abs,
        propagated_derivative_error_abs=
            propagated_derivative_error_abs,
    )
    progress_emit("primary_staged_derivative_rejected";
        payload=rejected_payload
    )
    progress_emit("primary_full_authentication_escalated";
        payload=merge(rejected_payload, Dict(
            "authentication_mode" =>
                authentication_mode_text(FULL_AUTHENTICATION_ESCALATION),
        ))
    )
    full = full_authenticator(
        T, request, evaluation_context, root, amplitude
    )
    full.root_authentication === nothing && error(
        "PRIMARY full-authentication escalation omitted its certificate"
    )
    result = merge(full, (
        authentication_mode=FULL_AUTHENTICATION_ESCALATION,
        authoritative=true,
        full_authentication_escalated=true,
        escalation_reason=escalation_reason,
        raw_step_disagreement_abs=raw_step_disagreement_abs,
        guarded_step_disagreement_abs=guarded_step_disagreement_abs,
    ))
    progress_emit("primary_full_authentication_completed";
        payload=authentication_progress_payload(phase, result)
    )
    return result
end

function solve_legacy_exterior_diagnostic_consistency(
    ::Type{T},
    request,
    evaluation_context::DeterminantRequestContext{T},
    initial::Complex{T},
    amplitude::Complex{T},
    authenticated_primary_root::Complex{T},
) where {T<:AbstractFloat}
    raw = solve_once(
        T,
        request,
        evaluation_context,
        initial,
        amplitude;
        authenticate_controls=false,
    )
    root, residual, derivative_lower_bound_abs, converged,
        root_evaluation, root_authentication = raw
    branch_identity = string(required(request, "branch_convention"))
    branch_authenticated =
        branch_identity == BRANCH_CONVENTION_ID &&
        abs(root - authenticated_primary_root) <=
            parse_real(T, request, "branch_enclosure_radius_abs")
    residual_upper_bound_abs =
        root_authentication.residual_upper_bound_abs
    tolerance = root_authentication.root_correction_tolerance
    return (
        root=root,
        residual=residual,
        derivative_lower_bound_abs=derivative_lower_bound_abs,
        converged=converged,
        root_evaluation=root_evaluation,
        # Diagnostics may consume a full certificate internally, but only
        # PRIMARY publishes the authoritative RootAuthentication.
        root_authentication=nothing,
        solve_role=DIAGNOSTIC_CONSISTENCY,
        authentication_mode=DIAGNOSTIC_CONSISTENCY_AUTHENTICATION,
        authoritative=false,
        full_authentication_escalated=false,
        escalation_reason=nothing,
        authenticated_evidence_reused=false,
        residual_upper_bound_abs=residual_upper_bound_abs,
        required_derivative_lower_bound_abs=
            residual_upper_bound_abs / tolerance,
        correction_upper_bound=root_authentication.correction_upper_bound,
        root_correction_tolerance=tolerance,
        raw_step_disagreement_abs=nothing,
        guarded_step_disagreement_abs=nothing,
        propagated_derivative_error_abs=
            root_authentication.derivative.propagated_error_abs,
        determinant_error_abs=
            determinant_error_abs(T, root_evaluation),
        error_model_id=root_evaluation.error_model_id,
        branch_identity=branch_identity,
        branch_authenticated=branch_authenticated,
        control_identity=phase_control_identity(request),
    )
end

function solve_diagnostic_consistency(
    ::Type{T},
    request,
    evaluation_context::DeterminantRequestContext{T},
    phase::String,
    initial::Complex{T},
    amplitude::Complex{T},
    authenticated_primary_root::Complex{T};
    newton_solver=diagnostic_consistency_newton,
    determinant_evaluator=diagnostic_determinant_progress,
    full_authenticator=solve_full_authentication,
) where {T<:AbstractFloat}
    tolerance = parse_real(T, request, "root_correction_tolerance")
    progress_emit("diagnostic_consistency_started"; payload=
        authentication_progress_payload(
            phase,
            DIAGNOSTIC_CONSISTENCY_AUTHENTICATION,
            false,
            false,
            nothing,
            DETERMINANT_INDEX_PHASE[];
            root_correction_tolerance=tolerance,
        )
    )
    reuse_count_before = AUTHENTICATED_EVIDENCE_REUSE_COUNT_PHASE[]
    remaining_determinants =
        diagnostic_newton_remaining_determinant_count(
            T, request, evaluation_context, initial, amplitude
        )
    root, residual, accepted_derivative, newton_converged,
        root_evaluation, accepted_derivative_authentication =
        newton_solver(
            T,
            request,
            evaluation_context,
            initial,
            amplitude;
            determinant_evaluator=determinant_evaluator,
            # At most one centred Newton stencil remains after the carried
            # initial determinant. Exact PRIMARY evidence can reduce the
            # number of actual determinant solves to zero. PRIMARY itself
            # retains its separate staged/full resource policy.
            minimum_remaining_determinant_count=remaining_determinants,
        )
    branch_identity = string(required(request, "branch_convention"))
    displacement = abs(root - authenticated_primary_root)
    branch_authenticated =
        branch_identity == BRANCH_CONVENTION_ID &&
        displacement <=
            parse_real(T, request, "branch_enclosure_radius_abs")
    reused = AUTHENTICATED_EVIDENCE_REUSE_COUNT_PHASE[] >
        reuse_count_before

    escalation_reason = nothing
    derivative_authentication = nothing
    derivative_lower_bound_abs = zero(T)
    residual_upper_bound_abs = nothing
    required_derivative_lower_bound_abs = nothing
    correction_upper_bound = T(Inf)
    root_error_abs = zero(T)

    if !newton_converged
        escalation_reason = "NEWTON_CORRECTION_UNRESOLVED"
    elseif accepted_derivative === nothing ||
            accepted_derivative_authentication === nothing ||
            !isequal(
                accepted_derivative_authentication.value,
                accepted_derivative,
            )
        escalation_reason = "DERIVATIVE_ESTIMATE_UNRESOLVED"
    elseif root_evaluation.error_breakdown === nothing
        escalation_reason = "DETERMINANT_ERROR_EVIDENCE_MISSING"
    elseif !isequal(
        root_evaluation.error_model_id,
        required(request, "determinant_error_model"),
    )
        escalation_reason = "DETERMINANT_ERROR_MODEL_MISMATCH"
    else
        # This is the ordinary one-stencil, error-aware Newton evidence. Its
        # lower bound includes propagated determinant noise, but it does not
        # claim the cross-step/axis ladder reserved for full authentication.
        derivative_authentication = accepted_derivative_authentication
        derivative_lower_bound_abs =
            derivative_authentication.lower_bound_abs
        root_error_abs = determinant_error_abs(T, root_evaluation)
        residual_upper_bound_abs = residual + root_error_abs
        required_derivative_lower_bound_abs =
            residual_upper_bound_abs / tolerance
        correction_upper_bound =
            residual_upper_bound_abs / derivative_lower_bound_abs
        if !isfinite(correction_upper_bound)
            escalation_reason = "CORRECTION_UPPER_BOUND_UNRESOLVED"
        elseif correction_upper_bound > tolerance
            escalation_reason =
                "CORRECTION_UPPER_BOUND_EXCEEDS_TOLERANCE"
        elseif branch_identity != BRANCH_CONVENTION_ID
            escalation_reason = "BRANCH_IDENTITY_UNAUTHENTICATED"
        elseif !branch_authenticated
            escalation_reason =
                "ROOT_DISPLACEMENT_EXCEEDS_PHASE_LIMIT"
        end
    end

    if escalation_reason === nothing
        result = (
            root=root,
            residual=residual,
            derivative_lower_bound_abs=derivative_lower_bound_abs,
            converged=true,
            root_evaluation=root_evaluation,
            root_authentication=nothing,
            solve_role=DIAGNOSTIC_CONSISTENCY,
            authentication_mode=DIAGNOSTIC_CONSISTENCY_AUTHENTICATION,
            authoritative=false,
            full_authentication_escalated=false,
            escalation_reason=nothing,
            authenticated_evidence_reused=reused,
            residual_upper_bound_abs=residual_upper_bound_abs,
            required_derivative_lower_bound_abs=
                required_derivative_lower_bound_abs,
            correction_upper_bound=correction_upper_bound,
            root_correction_tolerance=tolerance,
            raw_step_disagreement_abs=nothing,
            guarded_step_disagreement_abs=nothing,
            propagated_derivative_error_abs=
                derivative_authentication.propagated_error_abs,
            determinant_error_abs=root_error_abs,
            error_model_id=root_evaluation.error_model_id,
            branch_identity=branch_identity,
            branch_authenticated=true,
            control_identity=phase_control_identity(request),
        )
        progress_emit("diagnostic_consistency_completed";
            payload=authentication_progress_payload(phase, result)
        )
        return result
    end

    escalation_payload = authentication_progress_payload(
        phase,
        FULL_AUTHENTICATION_ESCALATION,
        false,
        true,
        escalation_reason,
        DETERMINANT_INDEX_PHASE[];
        residual_upper_bound_abs=residual_upper_bound_abs,
        derivative_lower_bound_abs=derivative_lower_bound_abs,
        required_derivative_lower_bound_abs=
            required_derivative_lower_bound_abs,
        correction_upper_bound=correction_upper_bound,
        root_correction_tolerance=tolerance,
        propagated_derivative_error_abs=
            derivative_authentication === nothing ? nothing :
            derivative_authentication.propagated_error_abs,
    )
    progress_emit("root_phase_authentication_escalated"; payload=merge(
        escalation_payload,
        Dict{String,Any}(
            "solve_role" =>
                root_solve_role_text(DIAGNOSTIC_CONSISTENCY),
            "authenticated_evidence_reused" => reused,
            "determinant_count" => DETERMINANT_INDEX_PHASE[],
            "control_identity" => phase_control_identity(request),
        ),
    ))
    progress_emit("diagnostic_full_authentication_escalated";
        payload=escalation_payload
    )
    # Escalation uses the complete PRIMARY machinery and propagates every typed
    # numerical-control failure. Missing evidence can never become success.
    full = full_authenticator(
        T, request, evaluation_context, root, amplitude
    )
    full.root_authentication === nothing &&
        error("full diagnostic authentication omitted its certificate")
    full_displacement = abs(full.root - authenticated_primary_root)
    full_branch_authenticated =
        full.branch_identity == BRANCH_CONVENTION_ID &&
        full_displacement <=
            parse_real(T, request, "branch_enclosure_radius_abs")
    result = (
        root=full.root,
        residual=full.residual,
        derivative_lower_bound_abs=full.derivative_lower_bound_abs,
        converged=full.converged && full_branch_authenticated,
        root_evaluation=full.root_evaluation,
        # The full ladder was used to decide this diagnostic, but the phase
        # remains non-authoritative and cannot publish RootAuthentication.
        root_authentication=nothing,
        solve_role=DIAGNOSTIC_CONSISTENCY,
        authentication_mode=FULL_AUTHENTICATION_ESCALATION,
        authoritative=false,
        full_authentication_escalated=true,
        escalation_reason=escalation_reason,
        authenticated_evidence_reused=
            reused || full.authenticated_evidence_reused,
        residual_upper_bound_abs=full.residual_upper_bound_abs,
        required_derivative_lower_bound_abs=
            full.required_derivative_lower_bound_abs,
        correction_upper_bound=full.correction_upper_bound,
        root_correction_tolerance=full.root_correction_tolerance,
        raw_step_disagreement_abs=full.raw_step_disagreement_abs,
        guarded_step_disagreement_abs=
            full.guarded_step_disagreement_abs,
        propagated_derivative_error_abs=
            full.propagated_derivative_error_abs,
        determinant_error_abs=full.determinant_error_abs,
        error_model_id=full.error_model_id,
        branch_identity=full.branch_identity,
        branch_authenticated=full_branch_authenticated,
        control_identity=phase_control_identity(request),
    )
    progress_emit("diagnostic_full_authentication_completed";
        payload=authentication_progress_payload(phase, result)
    )
    return result
end

function solve_phase(
    ::Type{T}, request,
    evaluation_context::DeterminantRequestContext{T},
    phase::String, initial::Complex{T}, amplitude::Complex{T};
    solve_role::RootSolveRole,
    authenticated_primary_root=nothing,
    primary_derivative=nothing,
    seed_kind="AUTHENTICATED_BACKGROUND",
    requested_seed_kind=seed_kind,
    fallback_initial=nothing,
    fallback_used=false,
    fallback_reason=nothing,
) where {T<:AbstractFloat}
    started = time_ns()
    ACTIVE_PHASE[] = phase
    ACTIVE_PHASE_STARTED_NS[] = started
    ACTIVE_NEWTON_INDEX[] = 0
    DETERMINANT_INDEX_PHASE[] = 0
    AUTHENTICATED_EVIDENCE_REUSE_COUNT_PHASE[] = 0
    LAST_DETERMINANT_PURPOSE[] = nothing
    context = Dict{String,Any}(
        "phase" => phase,
        "root_phase" => phase,
        "seed_omega" => progress_complex(initial),
        "current_omega" => progress_complex(initial),
    )

    function solve_with_seed(
        selected_initial, selected_kind, used, reason, error_type=nothing
    )
        seed_context = Dict{String,Any}(
            "seed_omega" => progress_complex(selected_initial),
            "current_omega" => progress_complex(selected_initial),
            "seed_kind" => selected_kind,
            "fallback_used" => used,
        )
        return progress_scope(seed_context) do
            selected_mode = if solve_role === FULL_AUTHENTICATION
                if string(required(request, "mechanism_id")) ==
                        "horizon-admittance"
                    STAGED_FULL_AUTHENTICATION
                else
                    LEGACY_FULL_AUTHENTICATION
                end
            elseif solve_role === DIAGNOSTIC_CONSISTENCY
                DIAGNOSTIC_CONSISTENCY_AUTHENTICATION
            else
                nothing
            end
            seed_payload = Dict{String,Any}(
                "requested_seed_kind" => requested_seed_kind,
                "seed_kind" => selected_kind,
                "seed_omega" => progress_complex(selected_initial),
                "fallback_used" => used,
                "fallback_reason" => reason,
                "fallback_error_type" => error_type,
                "root_phase" => phase,
                "solve_role" => root_solve_role_text(solve_role),
                "authoritative" => solve_role in (
                    FULL_AUTHENTICATION, BINARY64_PARITY_PRIMARY
                ),
            )
            if selected_mode !== nothing
                seed_payload["authentication_mode"] =
                    authentication_mode_text(selected_mode)
            else
                seed_payload["promoted_root_readout_policy"] =
                    PROMOTED_ROOT_READOUT_POLICY_ID
                seed_payload["acceptance_metric"] =
                    PROMOTED_ROOT_ACCEPTANCE_METRIC_ID
            end
            progress_emit("root_seed_selected"; payload=seed_payload)
            if solve_role === BINARY64_PARITY_PRIMARY
                return solve_binary64_parity_primary(
                    T,
                    request,
                    evaluation_context,
                    selected_initial,
                    amplitude,
                )
            elseif solve_role === FIXED_ROOT_DIAGNOSTIC
                authenticated_primary_root === nothing && error(
                    "fixed-root diagnostic requires the PRIMARY root"
                )
                primary_derivative === nothing && error(
                    "fixed-root diagnostic requires the complex PRIMARY derivative"
                )
                selected_initial == authenticated_primary_root || error(
                    "fixed-root diagnostic moved the PRIMARY frequency"
                )
                return solve_fixed_root_diagnostic(
                    T,
                    request,
                    evaluation_context,
                    phase,
                    authenticated_primary_root,
                    amplitude,
                    primary_derivative,
                )
            end
            if solve_role === FULL_AUTHENTICATION
                if string(required(request, "mechanism_id")) ==
                        "horizon-admittance"
                    return solve_staged_primary_authentication(
                        T,
                        request,
                        evaluation_context,
                        selected_initial,
                        amplitude,
                    )
                end
                return solve_full_authentication(
                    T,
                    request,
                    evaluation_context,
                    selected_initial,
                    amplitude,
                )
            end
            authenticated_primary_root === nothing && error(
                "diagnostic consistency requires an authenticated PRIMARY root"
            )
            if string(required(request, "mechanism_id")) ==
                    "horizon-admittance"
                return solve_diagnostic_consistency(
                    T,
                    request,
                    evaluation_context,
                    phase,
                    selected_initial,
                    amplitude,
                    authenticated_primary_root,
                )
            end
            return solve_legacy_exterior_diagnostic_consistency(
                T,
                request,
                evaluation_context,
                selected_initial,
                amplitude,
                authenticated_primary_root,
            )
        end
    end

    initial_mode = if solve_role === FULL_AUTHENTICATION
        if string(required(request, "mechanism_id")) ==
                "horizon-admittance"
            STAGED_FULL_AUTHENTICATION
        else
            LEGACY_FULL_AUTHENTICATION
        end
    elseif solve_role === DIAGNOSTIC_CONSISTENCY
        DIAGNOSTIC_CONSISTENCY_AUTHENTICATION
    else
        nothing
    end
    return progress_scope(context) do
        phase_started_payload = Dict{String,Any}(
            "phase" => phase,
            "root_phase" => phase,
            "seed_omega" => progress_complex(initial),
            "current_omega" => progress_complex(initial),
            "solve_role" => root_solve_role_text(solve_role),
            "control_identity" => phase_control_identity(request),
            "root_correction_tolerance" => string(
                parse_real(T, request, "root_correction_tolerance")
            ),
        )
        if initial_mode === nothing
            phase_started_payload["promoted_root_readout_policy"] =
                PROMOTED_ROOT_READOUT_POLICY_ID
            phase_started_payload["acceptance_metric"] =
                PROMOTED_ROOT_ACCEPTANCE_METRIC_ID
            phase_started_payload["authoritative"] =
                solve_role === BINARY64_PARITY_PRIMARY
        else
            merge!(phase_started_payload, authentication_progress_payload(
                phase,
                initial_mode,
                solve_role === FULL_AUTHENTICATION,
                false,
                nothing,
                0;
                root_correction_tolerance=
                    parse_real(T, request, "root_correction_tolerance"),
            ))
            phase_started_payload["authenticated_evidence_reused"] = false
        end
        progress_emit("root_phase_started"; payload=phase_started_payload)
        actual_initial = initial
        actual_kind = seed_kind
        fallback_error_type = nothing
        result = try
            solve_with_seed(
                actual_initial, actual_kind, fallback_used, fallback_reason
            )
        catch failure
            failure isa InterruptException && rethrow()
            failure isa ODEControlFailure && rethrow()
            failure isa WorkerControlFailure && rethrow()
            fallback_initial === nothing && rethrow()
            fallback_reason = "PREDICTOR_SOLVE_ERROR"
            fallback_error_type = string(typeof(failure))
            fallback_used = true
            actual_initial = fallback_initial
            actual_kind = "FALLBACK_BACKGROUND"
            solve_with_seed(
                actual_initial,
                actual_kind,
                fallback_used,
                fallback_reason,
                fallback_error_type,
            )
        end
        if actual_kind != "FALLBACK_BACKGROUND" &&
                fallback_initial !== nothing
            branch_radius = parse_real(
                T, request, "branch_enclosure_radius_abs"
            )
            if !result.converged ||
                    abs(result.root - fallback_initial) > branch_radius
                fallback_reason = result.converged ?
                    "PREDICTOR_BRANCH_ESCAPE" :
                    "PREDICTOR_NEWTON_FAILED"
                fallback_used = true
                actual_initial = fallback_initial
                actual_kind = "FALLBACK_BACKGROUND"
                result = solve_with_seed(
                    actual_initial,
                    actual_kind,
                    fallback_used,
                    fallback_reason,
                )
            end
        end
        logical_determinant_count = if solve_role === FIXED_ROOT_DIAGNOSTIC
            result.raw_determinant_evaluation_count ==
                    DETERMINANT_INDEX_PHASE[] || error(
                "fixed-root diagnostic raw determinant count is inconsistent"
            )
            result.logical_authenticated_determinant_count
        else
            DETERMINANT_INDEX_PHASE[]
        end
        result = merge(result, (
            root_phase=phase,
            determinant_count=logical_determinant_count,
            determinant_count_phase=DETERMINANT_INDEX_PHASE[],
        ))
        if solve_role === BINARY64_PARITY_PRIMARY
            result = merge(result, (
                newton_determinant_count=DETERMINANT_INDEX_PHASE[],
                post_newton_determinant_count=0,
            ))
        end
        completion_context = Dict{String,Any}(
            "seed_omega" => progress_complex(actual_initial),
            "current_omega" => progress_complex(result.root),
            "seed_kind" => actual_kind,
            "fallback_used" => fallback_used,
        )
        progress_scope(completion_context) do
            completed_payload = Dict{String,Any}(
                "phase" => phase,
                "root_phase" => phase,
                "resulting_omega" => progress_complex(result.root),
                "resulting_determinant_abs" => string(result.residual),
                "branch_identity" => result.branch_identity,
                "branch_authenticated" => result.branch_authenticated,
                "control_identity" => result.control_identity,
                "solve_role" => root_solve_role_text(result.solve_role),
                "determinant_count" => result.determinant_count,
                "converged" => result.converged,
                "elapsed_seconds" => (time_ns() - started) / 1.0e9,
            )
            if solve_role in (
                BINARY64_PARITY_PRIMARY, FIXED_ROOT_DIAGNOSTIC
            )
                merge!(completed_payload, Dict{String,Any}(
                    "promoted_root_readout_policy" =>
                        PROMOTED_ROOT_READOUT_POLICY_ID,
                    "acceptance_metric" => result.acceptance_metric,
                    "correction_abs" => string(result.correction_abs),
                    "root_correction_tolerance" =>
                        string(result.root_correction_tolerance),
                    "derivative_abs" => string(result.derivative_abs),
                    "derivative" => progress_complex(result.derivative),
                    "authoritative" => result.authoritative,
                    "determinant_error_abs" =>
                        string(result.determinant_error_abs),
                    "error_model_id" => result.error_model_id,
                ))
                if solve_role === BINARY64_PARITY_PRIMARY
                    completed_payload["post_newton_determinant_count"] =
                        result.post_newton_determinant_count
                else
                    completed_payload["fixed_root"] = result.fixed_root
                    completed_payload["derivative_source"] =
                        result.derivative_source
                    completed_payload[
                        "raw_determinant_evaluation_count"
                    ] = result.raw_determinant_evaluation_count
                end
            else
                merge!(completed_payload,
                    authentication_progress_payload(phase, result)
                )
                completed_payload["derivative_abs"] =
                    string(result.derivative_lower_bound_abs)
                completed_payload["authenticated_evidence_reused"] =
                    result.authenticated_evidence_reused
            end
            progress_emit("root_phase_completed"; payload=completed_payload)
        end
        result
    end
end

function refined_request(::Type{T}, request, kind::Symbol) where {T<:AbstractFloat}
    output = copy(request)
    if kind == :truncation
        output["endpoint_series_order"] = parse_integer(request, "endpoint_series_order") + 8
    elseif kind == :resolution
        for key in (
            "homogeneous_ode_relative_tolerance",
            "homogeneous_ode_absolute_tolerance",
        )
            output[key] = numeric_text(parse_real(T, request, key) / T(2))
        end
    else
        error("unknown root diagnostic refinement")
    end
    return output
end

function conditioning_response(
    ::Type{T},
    request,
    context::DeterminantRequestContext{T},
    digits::Int,
) where {T<:AbstractFloat}
    accumulator = context.conditioning
    accumulator.determinant_count > 0 ||
        error("conditioning response requires at least one determinant")
    minimum_asymptotic =
        accumulator.minimum_asymptotic_predicted_reliable_digits
    minimum_asymptotic === nothing &&
        error("conditioning response lacks asymptotic preflight evidence")
    horizon = string(required(request, "mechanism_id")) ==
        "horizon-admittance"
    basis_digits_lost = if horizon
        basis_condition = accumulator.maximum_basis_condition
        basis_condition === nothing &&
            error("horizon conditioning lacks a basis condition")
        log10(max(one(T), basis_condition))
    else
        zero(T)
    end
    horizon_fields = (
        maximum_basis_condition=accumulator.maximum_basis_condition,
        maximum_basis_backward_error=
            accumulator.maximum_basis_backward_error,
        maximum_matching_reconstruction_residual=
            accumulator.maximum_matching_reconstruction_residual,
        minimum_cref_chart_margin=accumulator.minimum_cref_chart_margin,
        maximum_carrier_change_error=
            accumulator.maximum_carrier_change_error,
    )
    if horizon
        for (field, value) in pairs(horizon_fields)
            value === nothing && error(
                "horizon conditioning lacks $(String(field))"
            )
            isfinite(value) && value >= zero(T) || error(
                "horizon conditioning has invalid $(String(field))"
            )
        end
    else
        all(isnothing, values(horizon_fields)) || error(
            "exterior conditioning contains horizon-only evidence"
        )
    end
    effective_digits_lost = max(
        accumulator.maximum_series_digits_lost,
        accumulator.maximum_recurrence_digits_lost,
        accumulator.maximum_fd_digits_lost,
        basis_digits_lost,
    )
    predicted_reliable_digits = min(
        T(digits) - effective_digits_lost -
            T(RELIABLE_DIGIT_SAFETY_MARGIN),
        minimum_asymptotic,
    )
    required_digits = required_reliable_digits(T, request)
    precision_limited = predicted_reliable_digits < required_digits
    evidence = Dict{String,Any}(
        "schema" => CONDITIONING_SCHEMA,
        "determinant_family" => horizon ?
            HORIZON_DETERMINANT_FAMILY_ID :
            EXTERIOR_DETERMINANT_FAMILY_ID,
        "scattering_diagnostics_applicable" => horizon,
        "homogeneous_representation" => horizon ?
            HORIZON_HOMOGENEOUS_REPRESENTATION_ID :
            HOMOGENEOUS_REPRESENTATION_ID,
        "branch_convention" => BRANCH_CONVENTION_ID,
        "scattering_column_convention" => horizon ?
            SCATTERING_COLUMN_CONVENTION_ID : nothing,
        "radial_derivative_convention" =>
            RADIAL_DERIVATIVE_CONVENTION_ID,
        "determinant_convention" => horizon ?
            HORIZON_DETERMINANT_CONVENTION_ID :
            EXTERIOR_DETERMINANT_CONVENTION_ID,
        "determinant_normalisation" => horizon ?
            HORIZON_DETERMINANT_NORMALISATION_ID :
            EXTERIOR_DETERMINANT_NORMALISATION_ID,
        "regular_remainder_contract" => REGULAR_REMAINDER_CONTRACT_ID,
        "factored_remainder_state_convention" =>
            FACTORED_REMAINDER_STATE_CONVENTION_ID,
        "human_math_review_receipt_status" =>
            HUMAN_MATH_REVIEW_RECEIPT_STATUS,
        "human_math_review_receipt_sha256" =>
            HUMAN_MATH_REVIEW_RECEIPT_SHA256,
        "independent_reference_fixture_receipt_status" =>
            INDEPENDENT_REFERENCE_FIXTURE_RECEIPT_STATUS,
        "independent_reference_fixture_receipt_sha256" =>
            INDEPENDENT_REFERENCE_FIXTURE_RECEIPT_SHA256,
        "maximum_series_digits_lost" =>
            string(accumulator.maximum_series_digits_lost),
        "maximum_recurrence_digits_lost" =>
            string(accumulator.maximum_recurrence_digits_lost),
        "maximum_series_evaluation_spread" =>
            string(accumulator.maximum_series_evaluation_spread),
        "maximum_last_term_ratio" =>
            string(accumulator.maximum_last_term_ratio),
        "minimum_asymptotic_predicted_reliable_digits" =>
            string(minimum_asymptotic),
        "maximum_basis_condition" => horizon ?
            string(accumulator.maximum_basis_condition) : nothing,
        "maximum_basis_backward_error" => horizon ?
            string(accumulator.maximum_basis_backward_error) : nothing,
        "maximum_matching_reconstruction_residual" => horizon ?
            string(accumulator.maximum_matching_reconstruction_residual) :
            nothing,
        "endpoint_remainders_regular" =>
            accumulator.endpoint_remainders_regular,
        "maximum_endpoint_reconstruction_error" =>
            string(accumulator.maximum_endpoint_reconstruction_error),
        "maximum_fd_digits_lost" =>
            string(accumulator.maximum_fd_digits_lost),
        "predicted_reliable_digits" => string(predicted_reliable_digits),
        "required_reliable_digits" => string(required_digits),
        "precision_limited" => precision_limited,
        "asymptotic_preflight_avoided_ode" => false,
        "minimum_cref_chart_margin" => horizon ?
            string(accumulator.minimum_cref_chart_margin) : nothing,
        "maximum_carrier_change_error" => horizon ?
            string(accumulator.maximum_carrier_change_error) : nothing,
        "maximum_contour_angle_deformation" =>
            string(accumulator.maximum_contour_angle_deformation),
    )
    progress_emit("conditioning_evaluated"; payload=Dict(
        "estimate_kind" => "empirical-conditioning/not-a-bound/v1",
        "determinant_family" => evidence["determinant_family"],
        "maximum_series_digits_lost" =>
            evidence["maximum_series_digits_lost"],
        "maximum_recurrence_digits_lost" =>
            evidence["maximum_recurrence_digits_lost"],
        "maximum_fd_digits_lost" => evidence["maximum_fd_digits_lost"],
        "finite_difference_saturation_observed" =>
            accumulator.finite_difference_saturation_observed,
        "finite_difference_underflow_observed" =>
            accumulator.finite_difference_underflow_observed,
        "predicted_reliable_digits" =>
            evidence["predicted_reliable_digits"],
        "required_reliable_digits" =>
            evidence["required_reliable_digits"],
        "precision_limited" => precision_limited,
    ))
    return evidence
end

function primary_acceptance_text(result)
    derivative_authentication = result.derivative_authentication
    derivative_error_available =
        derivative_authentication !== nothing &&
        result.error_model_id !== nothing &&
        derivative_authentication.propagated_error_abs > zero(
            derivative_authentication.propagated_error_abs
        )
    return Dict{String,Any}(
        "policy_id" => PROMOTED_ROOT_READOUT_POLICY_ID,
        "acceptance_metric" => result.acceptance_metric,
        "determinant_re" => numeric_text(real(result.root_evaluation.value)),
        "determinant_im" => numeric_text(imag(result.root_evaluation.value)),
        "derivative_re" => numeric_text(real(result.derivative)),
        "derivative_im" => numeric_text(imag(result.derivative)),
        "correction_abs" => numeric_text(result.correction_abs),
        "root_correction_tolerance" =>
            numeric_text(result.root_correction_tolerance),
        "accepted" => result.converged,
        "newton_determinant_count" => result.newton_determinant_count,
        "post_newton_determinant_count" =>
            result.post_newton_determinant_count,
        "determinant_error_abs" =>
            numeric_text(result.determinant_error_abs),
        "error_model_id" => result.error_model_id,
        "derivative_authentication" =>
            derivative_authentication === nothing ? nothing :
            Dict{String,Any}(
                "derivative_re" => numeric_text(
                    real(derivative_authentication.value)
                ),
                "derivative_im" => numeric_text(
                    imag(derivative_authentication.value)
                ),
                "propagated_error_abs" => numeric_text(
                    derivative_authentication.propagated_error_abs
                ),
                "step_disagreement_abs" => numeric_text(
                    derivative_authentication.step_disagreement_abs
                ),
                "lower_bound_abs" => numeric_text(
                    derivative_authentication.lower_bound_abs
                ),
                "selected_step" => numeric_text(
                    derivative_authentication.step
                ),
                "axis" => derivative_authentication.axis,
                "determinant_error_status" => derivative_error_available ?
                    "available/v1" : "unavailable/v1",
                "determinant_error_model_id" => derivative_error_available ?
                    result.error_model_id : nothing,
            ),
    )
end

function fixed_root_diagnostic_text(result, authenticated_primary_root)
    result.root == authenticated_primary_root || error(
        "fixed-root diagnostic moved the accepted PRIMARY frequency"
    )
    return Dict{String,Any}(
        "policy_id" => PROMOTED_ROOT_READOUT_POLICY_ID,
        "root_phase" => result.root_phase,
        "fixed_root" => result.fixed_root,
        "root_omega_re" => numeric_text(real(result.root)),
        "root_omega_im" => numeric_text(imag(result.root)),
        "determinant_re" => numeric_text(real(result.root_evaluation.value)),
        "determinant_im" => numeric_text(imag(result.root_evaluation.value)),
        "root_residual_abs" => numeric_text(result.residual),
        "primary_derivative_re" => numeric_text(real(result.derivative)),
        "primary_derivative_im" => numeric_text(imag(result.derivative)),
        "derivative_source" => result.derivative_source,
        "acceptance_metric" => result.acceptance_metric,
        "correction_abs" => numeric_text(result.correction_abs),
        "root_correction_tolerance" =>
            numeric_text(result.root_correction_tolerance),
        "determinant_error_abs" =>
            numeric_text(result.determinant_error_abs),
        "error_model_id" => result.error_model_id,
        "displacement_from_primary_abs" =>
            numeric_text(abs(result.root - authenticated_primary_root)),
        "branch_identity" => result.branch_identity,
        "branch_authenticated" => result.branch_authenticated,
        "control_identity" => result.control_identity,
        "solve_role" => root_solve_role_text(result.solve_role),
        "authoritative" => result.authoritative,
        "determinant_count" => result.determinant_count,
        "raw_determinant_evaluation_count" =>
            result.raw_determinant_evaluation_count,
        "root_converged" => result.converged,
    )
end

function diagnostic_root_text(result, authenticated_primary_root)
    return Dict{String,Any}(
        "root_phase" => result.root_phase,
        "root_omega_re" => numeric_text(real(result.root)),
        "root_omega_im" => numeric_text(imag(result.root)),
        "root_residual_abs" => numeric_text(result.residual),
        "root_derivative_abs" =>
            numeric_text(result.derivative_lower_bound_abs),
        "determinant_error_abs" =>
            numeric_text(result.determinant_error_abs),
        "error_model_id" => result.error_model_id,
        "residual_upper_bound_abs" =>
            numeric_text(result.residual_upper_bound_abs),
        "derivative_lower_bound_abs" =>
            numeric_text(result.derivative_lower_bound_abs),
        "required_derivative_lower_bound_abs" =>
            numeric_text(result.required_derivative_lower_bound_abs),
        "correction_upper_bound" =>
            numeric_text(result.correction_upper_bound),
        "root_correction_tolerance" =>
            numeric_text(result.root_correction_tolerance),
        "raw_step_disagreement_abs" =>
            result.raw_step_disagreement_abs === nothing ? nothing :
            numeric_text(result.raw_step_disagreement_abs),
        "guarded_step_disagreement_abs" =>
            result.guarded_step_disagreement_abs === nothing ? nothing :
            numeric_text(result.guarded_step_disagreement_abs),
        "propagated_derivative_error_abs" =>
            numeric_text(result.propagated_derivative_error_abs),
        "displacement_from_primary_abs" =>
            numeric_text(abs(result.root - authenticated_primary_root)),
        "branch_identity" => result.branch_identity,
        "branch_authenticated" => result.branch_authenticated,
        "control_identity" => result.control_identity,
        "solve_role" => root_solve_role_text(result.solve_role),
        "authentication_mode" =>
            authentication_mode_text(result.authentication_mode),
        "authoritative" => result.authoritative,
        "full_authentication_escalated" =>
            result.full_authentication_escalated,
        "escalation_reason" => result.escalation_reason,
        "authenticated_evidence_reused" =>
            result.authenticated_evidence_reused,
        "determinant_count" => result.determinant_count,
        "determinant_count_phase" => result.determinant_count_phase,
        "root_converged" => result.converged,
    )
end

function root_readout_response_fields(request, fields)
    string(required(request, "operation")) == "root-readout" ||
        error("root-readout serializer received the wrong operation")
    response = Dict{String,Any}(string(key) => value for (key, value) in fields)
    response["schema_version"] = 12
    response["status"] = "ok"
    response["adapter"] = "package-owned-julia-gsn-root-readout"
    response["operation"] = "root-readout"
    response["request_sha256"] = string(required(request, "request_sha256"))
    response["execution_identity"] = request_execution_identity(request)
    return response
end

function result_fields(::Type{T}, request, digits::Int, bits::Int) where {T<:AbstractFloat}
    omega = parse_complex(T, request, "omega_re", "omega_im")
    amplitude = parse_complex(T, request, "amplitude_re", "amplitude_im")
    evaluation_context = build_determinant_request_context(
        T, request, omega
    )

    primary_initial = omega
    fallback_initial = nothing
    primary_seed_kind = "AUTHENTICATED_BACKGROUND"
    primary_requested_seed_kind = "AUTHENTICATED_BACKGROUND"
    primary_fallback_used = false
    primary_fallback_reason = nothing
    if haskey(request, "primary_predictor_re") && haskey(request, "primary_predictor_im")
        primary_requested_seed_kind = string(
            required(request, "primary_predictor_kind")
        )
        if !(primary_requested_seed_kind in (
            "EPSILON_CONTINUATION", "SPIN_CONTINUATION"
        ))
            error("primary predictor kind is invalid")
        end
        predictor = parse_complex(
            T, request, "primary_predictor_re", "primary_predictor_im"
        )
        if isfinite(real(predictor)) && isfinite(imag(predictor)) &&
           abs(predictor - omega) <= parse_real(T, request, "branch_enclosure_radius_abs")
            primary_initial = predictor
            fallback_initial = omega
            primary_seed_kind = primary_requested_seed_kind
        else
            primary_seed_kind = "FALLBACK_BACKGROUND"
            primary_fallback_used = true
            if !isfinite(real(predictor)) || !isfinite(imag(predictor))
                primary_fallback_reason = "PREDICTOR_INVALID"
            else
                primary_fallback_reason = "PREDICTOR_OUTSIDE_BRANCH"
            end
        end
    end
    primary = solve_phase(
        T,
        request,
        evaluation_context,
        "PRIMARY",
        primary_initial,
        amplitude;
        seed_kind=primary_seed_kind,
        requested_seed_kind=primary_requested_seed_kind,
        fallback_initial=fallback_initial,
        fallback_used=primary_fallback_used,
        fallback_reason=primary_fallback_reason,
        solve_role=BINARY64_PARITY_PRIMARY,
    )
    root = primary.root
    residual = primary.residual
    derivative = primary.derivative
    derivative_abs = primary.derivative_abs
    primary_converged = primary.converged
    root_evaluation = primary.root_evaluation
    branch_tolerance = parse_real(T, request, "branch_enclosure_radius_abs")
    raw_determinant_abs = root_evaluation.diagnostics.raw_determinant_abs
    raw_determinant_evidence_status =
        root_evaluation.diagnostics.raw_determinant_evidence_status
    horizon = string(required(request, "mechanism_id")) ==
        "horizon-admittance"
    horizon_endpoint_evidence = if horizon
        evaluation_context.conditioning.horizon_endpoint_search_evidence
    else
        nothing
    end
    if horizon
        raw_determinant_evidence_status in (
            "available/v1", "unavailable-overflow/v1"
        ) || error("root raw determinant evidence status is invalid")
        if raw_determinant_evidence_status == "available/v1"
            raw_determinant_abs === nothing && error(
                "available raw determinant evidence lacks its magnitude"
            )
        else
            raw_determinant_abs === nothing || error(
                "unavailable raw determinant evidence must not carry a magnitude"
            )
        end
    else
        raw_determinant_evidence_status == "not-applicable/v1" || error(
            "exterior determinant raw-evidence status is inconsistent"
        )
        raw_determinant_abs === nothing || error(
            "exterior determinant must not carry raw horizon evidence"
        )
    end
    raw_determinant_abs === nothing ||
        (isfinite(raw_determinant_abs) &&
         raw_determinant_abs >= zero(T)) ||
        error("root raw determinant magnitude is invalid")
    if !primary_converged
        numerical_conditioning = conditioning_response(
            T, request, evaluation_context, digits
        )
        branch_valid = primary.branch_authenticated
        return root_readout_response_fields(request, [
            "schema_version" => 12,
            "status" => "ok",
            "adapter" => "package-owned-julia-gsn-root-readout",
            "operation" => "root-readout",
            "request_sha256" => string(required(request, "request_sha256")),
            "execution_identity" => request_execution_identity(request),
            "diagnostic_model_identity" => string(required(
                request, "diagnostic_model_identity"
            )),
            "required_raw_determinant_roles" => required(
                request, "required_raw_determinant_roles"
            ),
            "required_raw_determinant_count" => required(
                request, "required_raw_determinant_count"
            ),
            "precision_digits" => digits,
            "working_precision_bits" => bits,
            "promoted_root_readout_policy" =>
                PROMOTED_ROOT_READOUT_POLICY_ID,
            "root_omega_re" => numeric_text(real(root)),
            "root_omega_im" => numeric_text(imag(root)),
            "root_residual_abs" => numeric_text(residual),
            "raw_determinant_abs" => raw_determinant_abs === nothing ?
                nothing : numeric_text(raw_determinant_abs),
            "raw_determinant_evidence_status" =>
                raw_determinant_evidence_status,
            "root_derivative_abs" => numeric_text(derivative_abs),
            "primary_acceptance" => primary_acceptance_text(primary),
            "root_converged" => false,
            "branch_authentication_contract_version" => 4,
            "root_branch_continuation_valid" => branch_valid,
            "branch_tolerance_abs" => numeric_text(branch_tolerance),
            "root_displacement_abs" => numeric_text(abs(root - omega)),
            "truncation_radius_abs" => nothing,
            "resolution_radius_abs" => nothing,
            "seed_path_radius_abs" => nothing,
            "seed_path_required" => false,
            "seed_path_executed" => false,
            "seed_path_determinant_count" => 0,
            "diagnostic_roots" => Dict{String,Any}(),
            "diagnostics_skipped_reason" => "PRIMARY_NOT_CONVERGED",
            "numerical_conditioning" => numerical_conditioning,
            "horizon_endpoint_search_evidence" =>
                horizon_endpoint_evidence,
        ])
    end
    truncation = solve_phase(
        T,
        refined_request(T, request, :truncation),
        evaluation_context,
        "TRUNCATION",
        root,
        amplitude;
        seed_kind="ACCEPTED_PRIMARY",
        solve_role=FIXED_ROOT_DIAGNOSTIC,
        authenticated_primary_root=root,
        primary_derivative=derivative,
    )
    resolution = solve_phase(
        T,
        refined_request(T, request, :resolution),
        evaluation_context,
        "RESOLUTION",
        root,
        amplitude;
        seed_kind="ACCEPTED_PRIMARY",
        solve_role=FIXED_ROOT_DIAGNOSTIC,
        authenticated_primary_root=root,
        primary_derivative=derivative,
    )
    branch_valid = primary.branch_authenticated && all(
        result.branch_authenticated
        for result in (truncation, resolution)
    )
    converged = all((
        primary_converged,
        truncation.converged,
        resolution.converged,
        branch_valid,
    ))
    numerical_conditioning = conditioning_response(
        T, request, evaluation_context, digits
    )

    return root_readout_response_fields(request, [
        "schema_version" => 12,
        "status" => "ok",
        "adapter" => "package-owned-julia-gsn-root-readout",
        "operation" => "root-readout",
        "request_sha256" => string(required(request, "request_sha256")),
        "execution_identity" => request_execution_identity(request),
        "diagnostic_model_identity" => string(required(
            request, "diagnostic_model_identity"
        )),
        "required_raw_determinant_roles" => required(
            request, "required_raw_determinant_roles"
        ),
        "required_raw_determinant_count" => required(
            request, "required_raw_determinant_count"
        ),
        "precision_digits" => digits,
        "working_precision_bits" => bits,
        "promoted_root_readout_policy" =>
            PROMOTED_ROOT_READOUT_POLICY_ID,
        "root_omega_re" => numeric_text(real(root)),
        "root_omega_im" => numeric_text(imag(root)),
        "root_residual_abs" => numeric_text(residual),
        "raw_determinant_abs" => raw_determinant_abs === nothing ?
            nothing : numeric_text(raw_determinant_abs),
        "raw_determinant_evidence_status" =>
            raw_determinant_evidence_status,
        "root_derivative_abs" => numeric_text(derivative_abs),
        "primary_acceptance" => primary_acceptance_text(primary),
        "root_converged" => converged,
        "branch_authentication_contract_version" => 4,
        "root_branch_continuation_valid" => branch_valid,
        "branch_tolerance_abs" => numeric_text(branch_tolerance),
        "root_displacement_abs" => numeric_text(abs(root - omega)),
        "truncation_radius_abs" =>
            numeric_text(abs(truncation.root - root)),
        "resolution_radius_abs" =>
            numeric_text(abs(resolution.root - root)),
        "seed_path_radius_abs" => nothing,
        "seed_path_required" => false,
        "seed_path_executed" => false,
        "seed_path_determinant_count" => 0,
        "diagnostic_roots" => Dict(
            "truncation" => fixed_root_diagnostic_text(truncation, root),
            "resolution" => fixed_root_diagnostic_text(resolution, root),
        ),
        "diagnostics_skipped_reason" => nothing,
        "numerical_conditioning" => numerical_conditioning,
        "horizon_endpoint_search_evidence" => horizon_endpoint_evidence,
    ])
end

function flatten_fixed_root_survey_request(document)
    expected_fields = Set((
        "schema_version",
        "schema",
        "operation",
        "identity",
        "plan",
        "execution_identity",
        "scientific_operation_identity",
        "leaf_id",
        "job_id",
        "root_reference_id",
        "root_seal_sha256",
        "branch_identity",
        "backend_identity_sha256",
        "mode",
        "spin",
        "angular_A",
        "mechanism_id",
        "fixed_root",
        "precision_digits",
        "working_precision_bits",
        "semantic_precision_tier",
        "fixed_root_reliability_projection",
        "fixed_root_endpoint_recovery_policy",
        "frequency_step",
        "coordinate_step",
        "sample_roles",
        "maximum_sample_count",
        "samples",
        "policy",
        "execution_resource",
        "request_sha256",
    ))
    Set(keys(document)) == expected_fields ||
        error("fixed-root survey request fields are invalid")
    execution_identity = validate_wire_execution_identity(
        document, FIXED_ROOT_SURVEY_BATCH_SCHEMA
    )
    mode = required(document, "mode")
    angular = required(document, "angular_A")
    fixed_root = required(document, "fixed_root")
    policy = required(document, "policy")
    policy isa AbstractDict && Set(keys(policy)) ==
        FIXED_ROOT_SURVEY_POLICY_FIELDS ||
        error("fixed-root survey policy fields are invalid")
    resource = required(document, "execution_resource")
    request = Dict{String,Any}(
        "schema_version" => required(document, "schema_version"),
        "schema" => required(document, "schema"),
        "operation" => required(document, "operation"),
        "identity" => required(document, "identity"),
        "plan" => required(document, "plan"),
        "execution_identity" => execution_identity,
        "scientific_operation_identity" =>
            required(document, "scientific_operation_identity"),
        "leaf_id" => required(document, "leaf_id"),
        "job_id" => required(document, "job_id"),
        "root_reference_id" => required(document, "root_reference_id"),
        "root_seal_sha256" => required(document, "root_seal_sha256"),
        "branch_identity" => required(document, "branch_identity"),
        "backend_identity_sha256" =>
            required(document, "backend_identity_sha256"),
        "s" => required(mode, "s"),
        "ell" => required(mode, "ell"),
        "m" => required(mode, "m"),
        "n" => required(mode, "n"),
        "spin" => required(document, "spin"),
        "angular_A_re" => required(angular, "real"),
        "angular_A_im" => required(angular, "imaginary"),
        "mechanism_id" => required(document, "mechanism_id"),
        "fixed_root_re" => required(fixed_root, "real"),
        "fixed_root_im" => required(fixed_root, "imaginary"),
        "precision_digits" => required(document, "precision_digits"),
        "working_precision_bits" => required(document, "working_precision_bits"),
        "semantic_precision_tier" =>
            required(document, "semantic_precision_tier"),
        "fixed_root_reliability_projection" =>
            required(document, "fixed_root_reliability_projection"),
        "fixed_root_endpoint_recovery_policy" =>
            required(document, "fixed_root_endpoint_recovery_policy"),
        "frequency_step" => required(document, "frequency_step"),
        "coordinate_step" => required(document, "coordinate_step"),
        "sample_roles" => required(document, "sample_roles"),
        "maximum_sample_count" => required(document, "maximum_sample_count"),
        "samples" => required(document, "samples"),
        "request_sha256" => required(document, "request_sha256"),
    )
    for (key, value) in policy
        request[string(key)] = value
    end
    for key in (
        "schema",
        "version",
        "sha256",
        "worker_request_wall_clock_seconds",
        "cooperative_request_deadline_seconds",
        "homogeneous_ode_maxiters",
        "max_accepted_steps_per_homogeneous_leg",
        "max_rhs_evaluations_per_homogeneous_leg",
        "homogeneous_leg_wall_clock_seconds",
        "coordinate_stall_rhs_threshold",
        "coordinate_stall_minimum_span_fraction",
        "coordinate_stall_minimum_step_fraction",
    )
        output_key = key == "schema" ? "resource_policy_schema" :
            key == "version" ? "resource_policy_version" :
            key == "sha256" ? "resource_policy_sha256" : key
        request[output_key] = required(resource, key)
    end
    return request
end

function validate_fixed_root_survey_policy(request)
    # The flattened request contains envelope and resource fields too. Require
    # every policy field above and reject every known certificate-only field.
    for key in FIXED_ROOT_SURVEY_POLICY_FIELDS
        haskey(request, key) || error("fixed-root survey policy lacks $(key)")
    end
    for key in (
        "human_math_review_receipt_status",
        "human_math_review_receipt_sha256",
        "independent_reference_fixture_receipt_status",
        "independent_reference_fixture_receipt_sha256",
        "promoted_root_readout_policy",
        "root_correction_tolerance",
        "max_newton_iterations",
        "branch_enclosure_radius_abs",
    )
        haskey(request, key) &&
            error("fixed-root survey request carries prohibited field $(key)")
    end
    digits = parse_integer(request, "precision_digits")
    expected_preceding_tier = Dict(40 => "binary64", 80 => "bigfloat-40")[digits]
    expected = Dict{String,Any}(
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
        "determinant_family" => EXTERIOR_DETERMINANT_FAMILY_ID,
        "scattering_diagnostics_applicable" => false,
        "scattering_coefficient_extraction" => nothing,
        "horizon_determinant_chart" => nothing,
        "scattering_chart_safety_factor" => nothing,
        "scattering_column_convention" => nothing,
        "determinant_convention" => EXTERIOR_DETERMINANT_CONVENTION_ID,
        "determinant_normalisation" =>
            EXTERIOR_DETERMINANT_NORMALISATION_ID,
        # Named channels remain provisional until a separate authenticated
        # calibration freezes their safety factors.  The survey returns raw
        # samples but may not manufacture a SCREENED determinant disk.
        "determinant_error_model" => EXTERIOR_ADDITIVE_CHANNEL_SCHEMA_ID,
        "determinant_error_channel_schema" =>
            EXTERIOR_ADDITIVE_CHANNEL_SCHEMA_ID,
        "determinant_error_required_channels" =>
            EXTERIOR_ADDITIVE_CHANNELS,
        "determinant_error_calibration_status" =>
            EXTERIOR_ADDITIVE_CALIBRATION_STATUS,
        "determinant_error_missing_evidence_outcome" =>
            EXTERIOR_ADDITIVE_MISSING_OUTCOME,
        "determinant_error_preceding_precision_tier" => expected_preceding_tier,
    )
    for (key, value) in expected
        isequal(required(request, key), value) ||
            error("fixed-root survey policy $(key) is invalid")
    end
    return nothing
end

function validate_fixed_root_endpoint_recovery_policy(request)
    recovery = required(request, "fixed_root_endpoint_recovery_policy")
    recovery isa AbstractDict && Set(keys(recovery)) ==
        FIXED_ROOT_ENDPOINT_RECOVERY_POLICY_FIELDS || error(
            "fixed-root endpoint recovery policy fields are invalid"
        )
    string(required(recovery, "schema")) ==
        FIXED_ROOT_ENDPOINT_RECOVERY_POLICY_SCHEMA || error(
            "fixed-root endpoint recovery policy schema is invalid"
        )
    string(required(recovery, "identity")) ==
        FIXED_ROOT_ENDPOINT_RECOVERY_POLICY_IDENTITY || error(
            "fixed-root endpoint recovery policy identity is invalid"
        )
    string(required(recovery, "endpoint_order_rule")) ==
        FIXED_ROOT_ENDPOINT_ORDER_RULE || error(
            "fixed-root endpoint order rule is invalid"
        )
    string(required(recovery, "horizon_geometry_rule")) ==
        FIXED_ROOT_HORIZON_GEOMETRY_RULE || error(
            "fixed-root horizon geometry rule is invalid"
        )
    string(required(recovery, "infinity_geometry_rule")) ==
        FIXED_ROOT_INFINITY_GEOMETRY_RULE || error(
            "fixed-root infinity geometry rule is invalid"
        )
    base_order = parse_integer(recovery, "base_endpoint_order")
    maximum_order = parse_integer(recovery, "generated_maximum_order")
    base_order == parse_integer(request, "endpoint_series_order") &&
        maximum_order == 4 * base_order || error(
            "fixed-root endpoint order bounds are invalid"
        )
    raw_orders = required(recovery, "endpoint_order_schedule")
    raw_orders isa AbstractVector || error(
        "fixed-root endpoint order schedule is invalid"
    )
    all(value -> value isa Integer && !(value isa Bool), raw_orders) ||
        error("fixed-root endpoint order schedule is invalid")
    orders = Int[Int(value) for value in raw_orders]
    !isempty(orders) && first(orders) == base_order &&
        last(orders) == maximum_order && issorted(orders) &&
        length(unique(orders)) == length(orders) || error(
            "fixed-root endpoint order schedule is invalid"
        )
    for index in 1:(length(orders) - 1)
        orders[index + 1] == min(2 * orders[index], maximum_order) ||
            error("fixed-root endpoint order schedule violates its rule")
    end
    horizon = required(recovery, "horizon_geometry_schedule")
    infinity = required(recovery, "infinity_geometry_schedule")
    horizon isa AbstractVector && infinity isa AbstractVector || error(
        "fixed-root endpoint geometry schedules are invalid"
    )
    horizon_values = BigFloat[parse(BigFloat, string(value)) for value in horizon]
    infinity_values = BigFloat[parse(BigFloat, string(value)) for value in infinity]
    !isempty(horizon_values) && all(value -> value < 0, horizon_values) &&
        issorted(abs.(horizon_values)) &&
        length(unique(horizon_values)) == length(horizon_values) &&
        last(horizon_values) == parse_real(BigFloat, request, "rho_in") ||
        error("fixed-root horizon geometry schedule is invalid")
    !isempty(infinity_values) && all(value -> value > 0, infinity_values) &&
        issorted(infinity_values) &&
        length(unique(infinity_values)) == length(infinity_values) &&
        last(infinity_values) == parse_real(BigFloat, request, "rho_out") ||
        error("fixed-root infinity geometry schedule is invalid")
    projection = required(request, "fixed_root_reliability_projection")
    for field in (
        "fixed_root_reliability_target_abs",
        "fixed_root_reliability_rule",
        "required_digit_guard",
    )
        isequal(required(recovery, field), required(projection, field)) ||
            error("fixed-root endpoint recovery reliability binding is invalid")
    end
    parse_integer(recovery, "precision_digits") ==
        parse_integer(request, "precision_digits") || error(
            "fixed-root endpoint recovery precision is invalid"
        )
    string(required(recovery, "semantic_precision_tier")) ==
        string(required(request, "semantic_precision_tier")) || error(
            "fixed-root endpoint recovery tier is invalid"
        )
    binding = Dict{String,Any}(
        string(key) => value for (key, value) in recovery
        if string(key) != "policy_sha256"
    )
    canonical_sha256(binding) == string(required(recovery, "policy_sha256")) ||
        error("fixed-root endpoint recovery policy digest is invalid")
    return recovery
end

function validate_fixed_root_survey_request(request)
    parse_integer(request, "schema_version") == 3 ||
        error("fixed-root survey schema version is invalid")
    string(required(request, "schema")) == FIXED_ROOT_SURVEY_BATCH_SCHEMA ||
        error("fixed-root survey schema is invalid")
    string(required(request, "operation")) ==
        FIXED_ROOT_SURVEY_BATCH_OPERATION ||
        error("fixed-root survey operation is invalid")
    string(required(request, "identity")) == FIXED_ROOT_SURVEY_IDENTITY ||
        error("fixed-root survey identity is invalid")
    identity = request_execution_identity(request)
    string(required(identity, "scope")) == "REQUEST" ||
        error("fixed-root outer execution identity is not REQUEST scope")
    string(required(identity, "request_sha256")) ==
        string(required(request, "request_sha256")) ||
        error("fixed-root execution identity request binding is invalid")
    mechanism = string(required(request, "mechanism_id"))
    mechanism in ALLOWED_MECHANISMS && mechanism != "horizon-admittance" ||
        error("fixed-root survey requires an exterior mechanism")
    parse_integer(request, "s") == -2 ||
        error("fixed-root survey requires spin weight s=-2")
    digits = parse_integer(request, "precision_digits")
    digits in (40, 80) || error("fixed-root survey permits BF40 or BF80 only")
    bits = working_precision_bits_for(digits)
    parse_integer(request, "working_precision_bits") == bits ||
        error("fixed-root survey working precision is invalid")
    string(required(request, "semantic_precision_tier")) ==
        "bigfloat-$(digits)" || error("fixed-root survey tier is invalid")
    fixed_root_reliability_projection(request)
    parse_integer(request, "maximum_sample_count") == 9 ||
        error("fixed-root survey sample budget is invalid")
    for key in (
        "leaf_id", "job_id", "root_reference_id", "branch_identity",
        "backend_identity_sha256", "request_sha256", "root_seal_sha256",
    )
        value = string(required(request, key))
        isempty(value) && error("fixed-root survey $(key) is invalid")
        if key in ("root_seal_sha256", "backend_identity_sha256", "request_sha256")
            occursin(r"^[0-9a-f]{64}$", value) ||
                error("fixed-root survey $(key) digest is invalid")
        end
    end
    validate_fixed_root_survey_policy(request)
    validate_fixed_root_endpoint_recovery_policy(request)
    string(required(request, "resource_policy_schema")) ==
        "windows-solver.execution-resource-policy/1" ||
        error("fixed-root survey resource policy is invalid")
    parse_integer(request, "resource_policy_version") == 1 ||
        error("fixed-root survey resource policy version is invalid")
    occursin(
        r"^[0-9a-f]{64}$",
        string(required(request, "resource_policy_sha256")),
    ) || error("fixed-root survey resource policy digest is invalid")
    for key in (
        "worker_request_wall_clock_seconds",
        "cooperative_request_deadline_seconds",
        "homogeneous_ode_maxiters",
        "max_accepted_steps_per_homogeneous_leg",
        "max_rhs_evaluations_per_homogeneous_leg",
        "coordinate_stall_rhs_threshold",
    )
        parse_integer(request, key) > 0 ||
            error("fixed-root survey resource control $(key) is invalid")
    end
    leg_timeout = required(request, "homogeneous_leg_wall_clock_seconds")
    if leg_timeout !== nothing
        parse_integer(request, "homogeneous_leg_wall_clock_seconds") > 0 ||
            error("fixed-root survey homogeneous leg timeout is invalid")
    end
    parse_integer(request, "cooperative_request_deadline_seconds") <
        parse_integer(request, "worker_request_wall_clock_seconds") ||
        error("fixed-root survey cooperative deadline is invalid")

    raw_roles = required(request, "sample_roles")
    raw_roles isa Vector || error("fixed-root survey roles are invalid")
    roles = String[string(role) for role in raw_roles]
    length(unique(roles)) == length(roles) ||
        error("fixed-root survey roles contain duplicates")
    all(role in FIXED_ROOT_SURVEY_ROLES for role in roles) ||
        error("fixed-root survey role is unknown")
    length(roles) <= parse_integer(request, "maximum_sample_count") ||
        error("fixed-root survey sample budget exceeded")
    scientific_identity = string(required(
        request, "scientific_operation_identity"
    ))
    plan = string(required(request, "plan"))
    valid_roles = if plan == "CANONICAL_BACKGROUND_FIVE"
        scientific_identity == CANONICAL_EXTERIOR_BACKGROUND_IDENTITY &&
            roles == FIXED_ROOT_SURVEY_BACKGROUND_ROLES
    elseif plan == "FULL_NINE"
        scientific_identity == FIXED_ROOT_SURVEY_IDENTITY &&
            roles == FIXED_ROOT_SURVEY_ROLES
    elseif plan == "MECHANISM_COMPONENT_FOUR"
        scientific_identity == FIXED_ROOT_SURVEY_IDENTITY &&
            roles == FIXED_ROOT_SURVEY_COORDINATE_ROLES
    else
        false
    end
    valid_roles || error("fixed-root survey roles are out of order")
    string(required(identity, "plan")) == plan &&
        string(required(identity, "scientific_operation_identity")) ==
            scientific_identity &&
        required(identity, "sample_roles") == roles ||
        error("fixed-root request execution identity is inconsistent")
    samples = required(request, "samples")
    samples isa Vector && length(samples) == length(roles) ||
        error("fixed-root survey samples are invalid")
    root = parse_complex(
        BigFloat, request, "fixed_root_re", "fixed_root_im"
    )
    frequency_step = parse_real(BigFloat, request, "frequency_step")
    coordinate_step = parse_real(BigFloat, request, "coordinate_step")
    frequency_step > 0 && coordinate_step > 0 ||
        error("fixed-root survey steps are invalid")
    expected_points = Dict(
        "D0" => (root, zero(Complex{BigFloat})),
        "DOMEGA_REAL_PLUS_H" => (root + frequency_step, zero(Complex{BigFloat})),
        "DOMEGA_REAL_MINUS_H" => (root - frequency_step, zero(Complex{BigFloat})),
        "DOMEGA_REAL_PLUS_HALF_H" =>
            (root + frequency_step / 2, zero(Complex{BigFloat})),
        "DOMEGA_REAL_MINUS_HALF_H" =>
            (root - frequency_step / 2, zero(Complex{BigFloat})),
        "DC_PLUS_EPSILON" => (root, complex(coordinate_step, zero(BigFloat))),
        "DC_MINUS_EPSILON" => (root, complex(-coordinate_step, zero(BigFloat))),
        "DC_PLUS_HALF_EPSILON" =>
            (root, complex(coordinate_step / 2, zero(BigFloat))),
        "DC_MINUS_HALF_EPSILON" =>
            (root, complex(-coordinate_step / 2, zero(BigFloat))),
    )
    for (index, sample) in enumerate(samples)
        sample isa AbstractDict || error("fixed-root survey sample is invalid")
        role = roles[index]
        coordinate_role = role in FIXED_ROOT_SURVEY_COORDINATE_ROLES
        expected_fields = coordinate_role ?
            Set(("sample_index", "sample_role", "omega", "amplitude", "support")) :
            Set(("sample_index", "sample_role", "omega", "amplitude"))
        Set(keys(sample)) == expected_fields ||
            error("fixed-root survey sample fields are invalid")
        parse_integer(sample, "sample_index") == index - 1 ||
            error("fixed-root survey sample index binding is invalid")
        string(required(sample, "sample_role")) == role ||
            error("fixed-root survey sample role binding is invalid")
        omega_mapping = required(sample, "omega")
        amplitude_mapping = required(sample, "amplitude")
        omega = Complex{BigFloat}(
            parse(BigFloat, string(required(omega_mapping, "real"))),
            parse(BigFloat, string(required(omega_mapping, "imaginary"))),
        )
        amplitude = Complex{BigFloat}(
            parse(BigFloat, string(required(amplitude_mapping, "real"))),
            parse(BigFloat, string(required(amplitude_mapping, "imaginary"))),
        )
        expected_omega, expected_amplitude = expected_points[role]
        coordinate_tolerance = BigFloat(8) * BigFloat(eps(Float64)) * max(
            one(BigFloat),
            abs(root),
            frequency_step,
            coordinate_step,
        )
        abs(omega - expected_omega) <= coordinate_tolerance &&
            abs(amplitude - expected_amplitude) <= coordinate_tolerance ||
            error("fixed-root survey sample coordinates are invalid")
        if coordinate_role
            support = required(sample, "support")
            Set(keys(support)) == Set(("lower", "upper", "centre", "half_width")) ||
                error("fixed-root survey support fields are invalid")
        end
    end
    return digits, bits, roles, samples
end

function fixed_root_survey_conditioning_fields(
    ::Type{T}, request, context::DeterminantRequestContext{T}, digits::Int
) where {T<:AbstractFloat}
    accumulator = context.conditioning
    accumulator.determinant_count == 1 ||
        error("fixed-root survey sample must evaluate one determinant")
    minimum_asymptotic =
        accumulator.minimum_asymptotic_predicted_reliable_digits
    minimum_asymptotic === nothing &&
        error("fixed-root survey lacks asymptotic evidence")
    effective_digits_lost = max(
        accumulator.maximum_series_digits_lost,
        accumulator.maximum_recurrence_digits_lost,
    )
    predicted_reliable_digits = min(
        T(digits) - effective_digits_lost - T(RELIABLE_DIGIT_SAFETY_MARGIN),
        minimum_asymptotic,
    )
    required_digits = required_reliable_digits(T, request)
    reliability_projection = required(
        request, "fixed_root_reliability_projection"
    )
    recovery_policy = required(
        request, "fixed_root_endpoint_recovery_policy"
    )
    endpoint_receipts = accumulator.exterior_endpoint_recovery_evidence
    length(endpoint_receipts) == 2 || error(
        "fixed-root survey lacks its two endpoint recovery receipts"
    )
    all(
        receipt -> required(receipt, "aggregate_limitation") ==
            CF.ENDPOINT_ADEQUATE,
        endpoint_receipts,
    ) || error("fixed-root survey retained an inadequate endpoint")
    maximum_truncation_digits_lost = maximum(
        parse(T, string(required(
            receipt, "maximum_truncation_digits_lost"
        ))) for receipt in endpoint_receipts
    )
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
        "maximum_series_digits_lost" =>
            numeric_text(accumulator.maximum_series_digits_lost),
        "maximum_recurrence_digits_lost" =>
            numeric_text(accumulator.maximum_recurrence_digits_lost),
        "maximum_series_evaluation_digits_lost" =>
            numeric_text(accumulator.maximum_series_digits_lost),
        "maximum_last_term_ratio" =>
            numeric_text(accumulator.maximum_last_term_ratio),
        "maximum_truncation_digits_lost" =>
            numeric_text(maximum_truncation_digits_lost),
        "minimum_asymptotic_predicted_reliable_digits" =>
            numeric_text(minimum_asymptotic),
        "endpoint_remainders_regular" =>
            accumulator.endpoint_remainders_regular,
        "maximum_endpoint_reconstruction_error" =>
            numeric_text(accumulator.maximum_endpoint_reconstruction_error),
        "maximum_contour_angle_deformation" =>
            numeric_text(accumulator.maximum_contour_angle_deformation),
        "predicted_reliable_digits" => numeric_text(predicted_reliable_digits),
        "required_reliable_digits" => numeric_text(required_digits),
        "precision_limited" => predicted_reliable_digits < required_digits,
        "endpoint_recovery_policy_identity" => string(required(
            recovery_policy, "identity"
        )),
        "endpoint_recovery_policy_sha256" => string(required(
            recovery_policy, "policy_sha256"
        )),
        "endpoint_receipts" => endpoint_receipts,
        "aggregate_limitation" => CF.ENDPOINT_ADEQUATE,
        "factored_homogeneous_rhs_evaluations_before_recovery_decision" => 0,
        "determinant_count" => accumulator.determinant_count,
    )
end

function production_fixed_root_survey_sample_fields(
    ::Type{T}, sample_request, fixed_root::Complex{T},
    omega::Complex{T}, amplitude::Complex{T}, role::String, digits::Int,
) where {T<:AbstractFloat}
    evaluation_context = build_determinant_request_context(
        T, sample_request, fixed_root
    )
    before = DETERMINANT_INDEX_REQUEST[]
    evaluation = determinant_progress(
        T,
        sample_request,
        evaluation_context,
        omega,
        amplitude,
        "fixed-root survey $(role)",
        fixed_root,
    )
    certificate_required = exterior_empirical_certificate_required(sample_request)
    expected_determinant_calls = certificate_required ? 3 : 1
    DETERMINANT_INDEX_REQUEST[] == before + expected_determinant_calls ||
        error("fixed-root survey sample exceeded its raw determinant budget")
    breakdown = evaluation.error_breakdown
    if certificate_required && (
        breakdown === nothing || evaluation.error_model_id === nothing
    )
        error("fixed-root survey sample is missing its required certificate")
    end
    return Dict{String,Any}(
        "determinant" => Dict(
            "real" => numeric_text(real(evaluation.value)),
            "imaginary" => numeric_text(imag(evaluation.value)),
        ),
        "numerical_conditioning" => fixed_root_survey_conditioning_fields(
            T, sample_request, evaluation_context, digits
        ),
        "determinant_error_evidence" => breakdown === nothing ? nothing : Dict{String,Any}(
            "schema" => "windows-solver.exterior-determinant-error-evidence/1",
            "error_model_id" => evaluation.error_model_id,
            "delta_same_point" => numeric_text(breakdown.control_disagreement_abs),
            "delta_cross_precision" =>
                numeric_text(breakdown.precision_disagreement_abs),
            "delta_endpoint_series" =>
                numeric_text(breakdown.endpoint_disagreement_abs),
            "safety_factor" => numeric_text(breakdown.safety_factor),
            "numerical_error_abs" => numeric_text(breakdown.numerical_error_abs),
        ),
    )
end

function fixed_root_survey_batch_fields(
    request, digits::Int, bits::Int, roles, samples;
    sample_evaluator::Function=production_fixed_root_survey_sample_fields,
)
    fixed_root = parse_complex(
        BigFloat, request, "fixed_root_re", "fixed_root_im"
    )
    outputs = Any[]
    for (index, sample) in enumerate(samples)
        role = roles[index]
        zero_based_index = index - 1
        omega_mapping = required(sample, "omega")
        amplitude_mapping = required(sample, "amplitude")
        omega = Complex{BigFloat}(
            parse(BigFloat, string(required(omega_mapping, "real"))),
            parse(BigFloat, string(required(omega_mapping, "imaginary"))),
        )
        amplitude = Complex{BigFloat}(
            parse(BigFloat, string(required(amplitude_mapping, "real"))),
            parse(BigFloat, string(required(amplitude_mapping, "imaginary"))),
        )
        sample_request = copy(request)
        sample_request["omega_re"] = numeric_text(real(omega))
        sample_request["omega_im"] = numeric_text(imag(omega))
        sample_request["amplitude_re"] = numeric_text(real(amplitude))
        sample_request["amplitude_im"] = numeric_text(imag(amplitude))
        sample_request["readout_role"] = role
        sample_request["sample_index"] = zero_based_index
        sample_request["sample_role"] = role
        selected_identity = sample_execution_identity(
            request, zero_based_index, role
        )
        sample_request["execution_identity"] = selected_identity
        if role in FIXED_ROOT_SURVEY_COORDINATE_ROLES
            support = required(sample, "support")
            for key in ("lower", "upper", "centre", "half_width")
                sample_request["support_$(key)"] = required(support, key)
            end
        end
        sample_fields = try
            progress_scope(Dict{String,Any}(
                "operation" => FIXED_ROOT_SURVEY_BATCH_OPERATION,
                "scope" => "SAMPLE",
                "plan" => string(required(request, "plan")),
                "sample_index" => zero_based_index,
                "sample_role" => role,
                "execution_identity_sha256" =>
                    canonical_sha256(selected_identity),
                "request_sha256" => string(required(request, "request_sha256")),
            )) do
                sample_evaluator(
                    BigFloat,
                    sample_request,
                    fixed_root,
                    omega,
                    amplitude,
                    role,
                    digits,
                )
            end
        catch failure
            translated = translate_numerical_control_failure(
                sample_request, failure
            )
            if translated isa WorkerControlFailure
                translated.details["execution_identity"] = selected_identity
                translated.details["sample_index"] = zero_based_index
                translated.details["sample_role"] = role
            end
            translated === failure && rethrow()
            throw(translated)
        end
        sample_fields isa AbstractDict ||
            error("fixed-root survey sample evaluator returned invalid fields")
        Set(string(key) for key in keys(sample_fields)) == Set((
            "determinant",
            "numerical_conditioning",
            "determinant_error_evidence",
        )) || error("fixed-root survey sample evaluator fields are invalid")
        push!(outputs, merge(Dict{String,Any}(
            "sample_index" => zero_based_index,
            "sample_role" => role,
            "execution_identity" => selected_identity,
            "omega" => Dict(
                "real" => numeric_text(real(omega)),
                "imaginary" => numeric_text(imag(omega)),
            ),
            "amplitude" => Dict(
                "real" => numeric_text(real(amplitude)),
                "imaginary" => numeric_text(imag(amplitude)),
            ),
        ), Dict{String,Any}(sample_fields)))
    end
    length(outputs) == length(roles) ||
        error("fixed-root survey response count is invalid")
    return Dict{String,Any}(
        "schema_version" => 3,
        "schema" => FIXED_ROOT_SURVEY_BATCH_RESPONSE_SCHEMA,
        "status" => "ok",
        "operation" => FIXED_ROOT_SURVEY_BATCH_OPERATION,
        "identity" => FIXED_ROOT_SURVEY_IDENTITY,
        "plan" => string(required(request, "plan")),
        "execution_identity" => request_execution_identity(request),
        "scientific_operation_identity" =>
            string(required(request, "scientific_operation_identity")),
        "request_sha256" => string(required(request, "request_sha256")),
        "leaf_id" => string(required(request, "leaf_id")),
        "job_id" => string(required(request, "job_id")),
        "root_reference_id" => string(required(request, "root_reference_id")),
        "root_seal_sha256" => string(required(request, "root_seal_sha256")),
        "branch_identity" => string(required(request, "branch_identity")),
        "semantic_precision_tier" => "bigfloat-$(digits)",
        "working_precision_bits" => bits,
        "sample_roles" => roles,
        "maximum_sample_count" => 9,
        "sample_count" => length(outputs),
        "samples" => outputs,
    )
end

function fixed_root_determinant_sample_response_fields(request, fields)
    string(required(request, "operation")) ==
        "fixed-root-determinant-sample" || error(
            "fixed-root determinant serializer received the wrong operation"
        )
    response = Dict{String,Any}(string(key) => value for (key, value) in fields)
    response["schema_version"] = 2
    response["status"] = "ok"
    response["operation"] = "fixed-root-determinant-sample"
    response["execution_identity"] = request_execution_identity(request)
    response["request_sha256"] = string(required(request, "request_sha256"))
    return response
end

function fixed_root_determinant_sample_fields(
    ::Type{T}, request, digits::Int, bits::Int
) where {T<:AbstractFloat}
    fixed_omega = parse_complex(
        T, request, "fixed_omega_re", "fixed_omega_im"
    )
    amplitude = parse_complex(T, request, "amplitude_re", "amplitude_im")
    evaluation_context = build_determinant_request_context(
        T, request, fixed_omega
    )
    evaluation = determinant_progress(
        T,
        request,
        evaluation_context,
        fixed_omega,
        amplitude,
        "fixed-root determinant sample",
        fixed_omega,
    )
    expected_determinant_count =
        required_raw_determinant_evaluation_count(request)
    DETERMINANT_INDEX_REQUEST[] == expected_determinant_count || error(
        "fixed-root determinant sample did not complete its required certificate evaluations"
    )
    expected_tier = "bigfloat-$(digits)"
    string(required(request, "semantic_precision_tier")) == expected_tier ||
        error("fixed-root determinant semantic tier is invalid")
    branch_identity = string(required(request, "branch_convention"))
    error_available = evaluation.error_breakdown !== nothing &&
        evaluation.error_model_id !== nothing
    numerical_conditioning = conditioning_response(
        T, request, evaluation_context, digits
    )
    return fixed_root_determinant_sample_response_fields(request, [
        "schema_version" => 2,
        "status" => "ok",
        "operation" => "fixed-root-determinant-sample",
        "execution_identity" => request_execution_identity(request),
        "request_sha256" => string(required(request, "request_sha256")),
        "omega_re" => numeric_text(real(fixed_omega)),
        "omega_im" => numeric_text(imag(fixed_omega)),
        "amplitude_re" => numeric_text(real(amplitude)),
        "amplitude_im" => numeric_text(imag(amplitude)),
        "determinant_re" => numeric_text(real(evaluation.value)),
        "determinant_im" => numeric_text(imag(evaluation.value)),
        "determinant_error_abs" => numeric_text(
            determinant_error_abs(T, evaluation)
        ),
        "determinant_error_status" =>
            error_available ? "available/v1" : "unavailable/v1",
        "determinant_error_model_id" =>
            error_available ? evaluation.error_model_id : nothing,
        "determinant_family" => string(required(request, "determinant_family")),
        "determinant_normalisation" => string(
            required(request, "determinant_normalisation")
        ),
        "branch_identity" => branch_identity,
        "branch_authenticated" => branch_identity == BRANCH_CONVENTION_ID,
        "semantic_precision_tier" => expected_tier,
        "working_precision_bits" => bits,
        "readout_role" => string(required(request, "readout_role")),
        "numerical_conditioning" => numerical_conditioning,
    ])
end

function validate_worker_request_contract(request)
    parse_integer(request, "schema_version") == 1 || error("unsupported schema_version")
    operation = string(required(request, "operation"))
    operation in ("root-readout", "fixed-root-determinant-sample") ||
        error("unsupported operation")
    parse_integer(request, "s") == -2 || error("M02 worker requires spin weight s=-2")
    digits = parse_integer(request, "precision_digits")
    digits in (40, 80, 120) || error(
        "precision_digits must be 40, 80, or 120"
    )
    bits = working_precision_bits_for(digits)
    parse_integer(request, "working_precision_bits") == bits ||
        error("working precision bits do not match decimal precision policy")
    string(required(request, "semantic_precision_tier")) ==
        "bigfloat-$(digits)" || error("semantic precision tier is invalid")
    validate_regularised_gsn_policy(request)
    string(required(request, "resource_policy_schema")) ==
        "windows-solver.execution-resource-policy/1" ||
        error("execution resource policy schema is invalid")
    parse_integer(request, "resource_policy_version") == 1 ||
        error("execution resource policy version is invalid")
    length(string(required(request, "resource_policy_sha256"))) == 64 ||
        error("execution resource policy SHA-256 is invalid")
    for key in (
        "worker_request_wall_clock_seconds",
        "cooperative_request_deadline_seconds",
        "homogeneous_ode_maxiters",
        "max_accepted_steps_per_homogeneous_leg",
        "max_rhs_evaluations_per_homogeneous_leg",
    )
        parse_integer(request, key) > 0 ||
            error("execution resource policy $(key) is invalid")
    end
    parse_integer(request, "cooperative_request_deadline_seconds") <
        parse_integer(request, "worker_request_wall_clock_seconds") ||
        error("cooperative deadline must precede the outer worker deadline")
    return operation, digits, bits
end

function validate_request_batch(batch)
    Set(keys(batch)) == Set((
        "schema_version",
        "operation",
        "request_set_sha256",
        "requests",
    )) || error("promoted-request preflight batch fields are invalid")
    parse_integer(batch, "schema_version") == 1 ||
        error("promoted-request preflight schema is invalid")
    string(required(batch, "operation")) == "promoted-request-preflight" ||
        error("promoted-request preflight operation is invalid")
    request_set_sha256 = string(required(batch, "request_set_sha256"))
    length(request_set_sha256) == 64 ||
        error("promoted-request preflight digest is invalid")
    documents = required(batch, "requests")
    documents isa Vector ||
        error("promoted-request preflight requests are invalid")
    length(documents) == 16 ||
        error("promoted-request preflight request count is invalid")
    observed_promoted = Set{Tuple{String,Int,Int}}()
    observed_fixed_root = Set{Tuple{Int,String,String}}()
    request_sha256s = String[]
    for document in documents
        document isa AbstractDict ||
            error("promoted-request preflight document is invalid")
        operation = string(required(document, "operation"))
        request = if operation == FIXED_ROOT_SURVEY_BATCH_OPERATION
            fixed_root_request = flatten_fixed_root_survey_request(document)
            digits, _, roles, _ =
                validate_fixed_root_survey_request(fixed_root_request)
            push!(observed_fixed_root, (
                digits,
                string(required(
                    fixed_root_request, "scientific_operation_identity"
                )),
                join(roles, "|"),
            ))
            fixed_root_request
        elseif operation == "root-readout"
            promoted_request = flatten_request(document)
            validate_worker_request_contract(promoted_request)
            mechanism = string(required(promoted_request, "mechanism_id"))
            digits = parse_integer(promoted_request, "precision_digits")
            refinement = parse_integer(promoted_request, "refinement_level")
            push!(observed_promoted, (mechanism, digits, refinement))
            promoted_request
        else
            error("promoted-request preflight document operation is invalid")
        end
        push!(request_sha256s, string(required(request, "request_sha256")))
    end
    expected_promoted = Set{Tuple{String,Int,Int}}(
        ("exterior-light-ring", digits, refinement)
        for digits in (40, 80, 120) for refinement in (0, 1)
    )
    union!(expected_promoted, Set{Tuple{String,Int,Int}}(
        ("horizon-admittance", digits, refinement)
        for digits in (80, 120) for refinement in (0, 1)
    ))
    observed_promoted == expected_promoted ||
        error("promoted-request preflight matrix is invalid")
    expected_fixed_root = Set{Tuple{Int,String,String}}()
    for digits in (40, 80)
        push!(expected_fixed_root, (
            digits,
            FIXED_ROOT_SURVEY_IDENTITY,
            join(FIXED_ROOT_SURVEY_ROLES, "|"),
        ))
        push!(expected_fixed_root, (
            digits,
            CANONICAL_EXTERIOR_BACKGROUND_IDENTITY,
            join(FIXED_ROOT_SURVEY_BACKGROUND_ROLES, "|"),
        ))
        push!(expected_fixed_root, (
            digits,
            FIXED_ROOT_SURVEY_IDENTITY,
            join(FIXED_ROOT_SURVEY_COORDINATE_ROLES, "|"),
        ))
    end
    observed_fixed_root == expected_fixed_root ||
        error("fixed-root survey preflight matrix is invalid")
    return Dict(
        "schema_version" => 1,
        "status" => "ok",
        "operation" => "promoted-request-preflight",
        "request_count" => length(documents),
        "request_set_sha256" => request_set_sha256,
        "request_sha256s" => request_sha256s,
    )
end

function evaluate_request(request; validated=nothing)
    operation, digits, bits = validated === nothing ?
        validate_worker_request_contract(request) : validated
    return setprecision(BigFloat, bits) do
        if operation == "fixed-root-determinant-sample"
            return fixed_root_determinant_sample_fields(
                BigFloat, request, digits, bits
            )
        end
        return result_fields(BigFloat, request, digits, bits)
    end
end

function main()
    if "--probe" in ARGS
        println("M02 Julia precision worker: packages loaded")
        return 0
    end
    if length(ARGS) == 3 && ARGS[1] == "--validate-request-batch"
        request_path = abspath(ARGS[2])
        response_path = abspath(ARGS[3])
        try
            batch = JSON.parsefile(request_path)
            result = validate_request_batch(batch)
            mkpath(dirname(response_path))
            write(response_path, JSON.json(result))
            return 0
        catch failure
            result = Dict(
                "schema_version" => 1,
                "status" => "error",
                "operation" => "promoted-request-preflight",
                "error_type" => string(typeof(failure)),
                "message" => sprint(showerror, failure),
            )
            mkpath(dirname(response_path))
            write(response_path, JSON.json(result))
            @error "M02 promoted-request preflight failed" exception=(
                failure, catch_backtrace()
            )
            return 21
        end
    end
    length(ARGS) == 2 || error("usage: m02_worker.jl REQUEST_JSON RESPONSE_JSON")
    request_path = abspath(ARGS[1])
    response_path = abspath(ARGS[2])
    REQUEST_STARTED_NS[] = time_ns()
    ACTIVE_PHASE_STARTED_NS[] = UInt64(0)
    ACTIVE_PHASE[] = nothing
    ACTIVE_NEWTON_INDEX[] = 0
    DETERMINANT_INDEX_REQUEST[] = 0
    DETERMINANT_INDEX_PHASE[] = 0
    AUTHENTICATED_EVIDENCE_REUSE_COUNT_PHASE[] = 0
    LAST_DETERMINANT_PURPOSE[] = nothing
    LAST_DETERMINANT_SECONDS[] = 0.0
    LAST_ODE_SNAPSHOT[] = nothing
    ACTIVE_PROGRESS_CONTEXT[] = Dict{String,Any}()
    request = nothing
    try
        document = JSON.parsefile(request_path)
        request = if string(required(document, "operation")) ==
                FIXED_ROOT_SURVEY_BATCH_OPERATION
            flatten_fixed_root_survey_request(document)
        else
            flatten_request(document)
        end
        execution_identity = request_execution_identity(request)
        ACTIVE_PROGRESS_CONTEXT[] = merge(
            ACTIVE_PROGRESS_CONTEXT[],
            Dict{String,Any}(
                "operation" => string(required(execution_identity, "operation")),
                "scope" => string(required(execution_identity, "scope")),
                "execution_identity_sha256" =>
                    canonical_sha256(execution_identity),
                "request_sha256" => string(required(request, "request_sha256")),
            ),
        )
        if haskey(execution_identity, "plan")
            ACTIVE_PROGRESS_CONTEXT[]["plan"] = execution_identity["plan"]
        end
        progress_emit("request_started"; payload=Dict(
            "request_sha256" => string(required(request, "request_sha256")),
            "execution_resource_policy" => resource_policy_identity(request),
        ))
        operation = string(required(request, "operation"))
        validated = if operation == FIXED_ROOT_SURVEY_BATCH_OPERATION
            validate_fixed_root_survey_request(request)
        else
            validate_worker_request_contract(request)
        end
        progress_emit("request_validated"; payload=Dict(
            "request_sha256" => string(required(request, "request_sha256")),
            "execution_resource_policy" => resource_policy_identity(request),
        ))
        result = if operation == FIXED_ROOT_SURVEY_BATCH_OPERATION
            digits, bits, roles, samples = validated
            setprecision(BigFloat, bits) do
                fixed_root_survey_batch_fields(
                    request, digits, bits, roles, samples
                )
            end
        else
            Dict(evaluate_request(request; validated=validated))
        end
        mkpath(dirname(response_path))
        write(response_path, JSON.json(result))
        progress_emit("request_completed"; payload=Dict(
            "request_sha256" => string(required(request, "request_sha256")),
        ))
        return 0
    catch failure
        control_receipt = if failure isa WorkerControlFailure && request !== nothing
            operation_control_receipt(request, failure_details(failure))
        else
            nothing
        end
        result = if control_receipt !== nothing
            Dict(
                "schema_version" => 1,
                "status" => "error",
                "error_type" => string(typeof(failure)),
                "message" => sprint(showerror, failure),
                "failure" => control_receipt,
            )
        else
            Dict(
                "schema_version" => 1,
                "status" => "error",
                "error_type" => string(typeof(failure)),
                "message" => sprint(showerror, failure),
            )
        end
        mkpath(dirname(response_path))
        write(response_path, JSON.json(result))
        request_failure = if control_receipt === nothing
            Dict{String,Any}(
                "error_type" => string(typeof(failure)),
                "message" => sprint(showerror, failure),
            )
        else
            identity = required(control_receipt, "execution_identity")
            binding = required(
                control_receipt, "canonical_request_binding"
            )
            identifiers = Dict{String,Any}(
                "error_type" => string(typeof(failure)),
                "failure_class" => required(control_receipt, "failure_class"),
                "failure_code" => required(control_receipt, "failure_code"),
                "stage" => required(control_receipt, "stage"),
                "scope" => required(control_receipt, "scope"),
                "operation" => required(binding, "operation"),
                "request_sha256" => required(binding, "request_sha256"),
                "execution_identity_sha256" =>
                    required(binding, "execution_identity_sha256"),
                "control_receipt_sha256" =>
                    required(control_receipt, "receipt_sha256"),
            )
            for key in ("plan", "sample_index", "sample_role")
                haskey(identity, key) && (identifiers[key] = identity[key])
            end
            identifiers
        end
        progress_emit("request_failed"; payload=request_failure)
        @error "M02 Julia precision worker failed" exception=(failure, catch_backtrace())
        return 21
    end
end

if abspath(PROGRAM_FILE) == abspath(@__FILE__)
    exit(main())
end
