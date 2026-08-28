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
const PROGRESS_SCHEMA = "windows-solver.progress/2"
const CONDITIONING_SCHEMA = "windows-solver.m02-conditioning/3"
const FIXED_ROOT_SURVEY_BATCH_OPERATION = "fixed-root-survey-batch"
const FIXED_ROOT_SURVEY_BATCH_SCHEMA =
    "windows-solver.fixed-root-survey-batch/2"
const FIXED_ROOT_SURVEY_BATCH_RESPONSE_SCHEMA =
    "windows-solver.fixed-root-survey-batch-response/2"
const FIXED_ROOT_SURVEY_IDENTITY = "exterior-fixed-root-survey-raw/v1"
const CANONICAL_EXTERIOR_BACKGROUND_IDENTITY =
    "canonical-exterior-background-wronskian/v1"
const FIXED_ROOT_SURVEY_CONDITIONING_SCHEMA =
    "windows-solver.fixed-root-survey-conditioning/2"
const OPERATION_EXECUTION_IDENTITY_SCHEMA =
    "windows-solver.operation-execution-identity/1"
const OPERATION_CONTROL_RECEIPT_SCHEMA =
    "windows-solver.operation-control-receipt/1"
const CANONICAL_REQUEST_BINDING_SCHEMA =
    "windows-solver.canonical-request-binding/1"
const FIXED_ROOT_RELIABILITY_RULE =
    "minus-log10-target-plus-required-digit-guard/v1"
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
    "root_phase", "newton_index", "readout_role",
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
    "required_digit_guard",
    "determinant_family",
    "scattering_diagnostics_applicable",
    "scattering_coefficient_extraction",
    "horizon_determinant_chart",
    "scattering_chart_safety_factor",
    "scattering_column_convention",
    "determinant_convention",
    "determinant_normalisation",
    "promoted_control_calibration_receipt_sha256",
    "empirical_control_profile_sha256",
    "determinant_error_model",
    "determinant_error_channel_schema",
    "determinant_error_required_channels",
    "determinant_error_calibration_status",
    "determinant_error_missing_evidence_outcome",
    "determinant_error_preceding_precision_tier",
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
const REQUIRED_DIGIT_GUARD = 6
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
        "required_digit_guard" => string(REQUIRED_DIGIT_GUARD),
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

function required_reliable_digits(::Type{T}, request) where {T<:AbstractFloat}
    operation = string(required(request, "operation"))
    tolerance = if operation == FIXED_ROOT_SURVEY_BATCH_OPERATION
        string(required(request, "fixed_root_reliability_rule")) ==
            FIXED_ROOT_RELIABILITY_RULE ||
            error("fixed-root reliability rule is invalid")
        parse_real(T, request, "fixed_root_reliability_target_abs")
    elseif operation in ("root-readout", "fixed-root-determinant-sample")
        parse_real(T, request, "root_correction_tolerance")
    else
        error("reliable-digit policy is undefined for this operation")
    end
    zero(T) < tolerance < one(T) ||
        error("reliability target must lie strictly between zero and one")
    return -log10(tolerance) + T(REQUIRED_DIGIT_GUARD)
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
        base_endpoint_order
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
            sign_pos=spectral.convention.infinity_sign,
            dtype=Complex{T},
            odealgo=algorithm,
            reltol=tolerances.reltol,
            abstol=tolerances.abstol,
            ode_maxiters=parse_integer(request, "homogeneous_ode_maxiters"),
            ode_observation_factory=observation_factory,
            ode_solution_observer=observe_ode_solution,
            r_at_rho_zero=Complex{T}(match_radius),
        )
    end
    radius_from_rho = observed_radial_map(
        raw_radius_from_rho, label, rho_in, rho_out
    )
    return CF.build_contour_context(
        spectral,
        match_radius,
        rstar_match,
        rho_in,
        rho_out,
        radius_from_rho,
    )
end

"""
    assert_match_radius_identity(T, spectral, match_radius, rstar_match)

Fail unless `rstar_from_r(a, match_radius)` reproduces the supplied
`rstar_match`.

Production now seeds the coordinate ODE with `r(0) = match_radius` directly
rather than recovering it through `r_from_rstar`. That is exact when the two
coordinates agree, so the identity is checked explicitly instead of being
implicitly re-derived by a numerical inverse.
"""
function assert_match_radius_identity(
    ::Type{T},
    spectral::CF.HomogeneousSpectralContext{T},
    match_radius::T,
    rstar_match::T,
) where {T<:AbstractFloat}
    canonical = T(GSN.rstar_from_r(spectral.a, match_radius))
    canonical == rstar_match || error(
        "match radius identity failed: rstar_from_r(a, match_radius)=" *
        "$(canonical) does not equal rstar_match=$(rstar_match)"
    )
    return nothing
end

"""
    build_worker_outer_contour(T, request, spectral, match_radius, label)

Build the infinity-side contour on `0 -> +rho_out` only.
"""
function build_worker_outer_contour(
    ::Type{T},
    request,
    spectral::CF.HomogeneousSpectralContext{T},
    match_radius::T,
    label::String,
) where {T<:AbstractFloat}
    rho_out = parse_real(T, request, "rho_out")
    rstar_match = T(GSN.rstar_from_r(spectral.a, match_radius))
    assert_match_radius_identity(T, spectral, match_radius, rstar_match)
    algorithm = AutoVern9(Rosenbrock23(autodiff=false))
    tolerances = coordinate_ode_tolerances(T, request)
    observation_factory = (leg, tspan, ode_algorithm) ->
        ode_observation_factory(request, leg, tspan, ode_algorithm)
    raw_radius_from_rho = progress_operation("r-from-rho"; payload=Dict(
        "contour_label" => label,
    )) do
        CF.solve_r_from_rho(
            spectral.a,
            spectral.convention.infinity_contour_angle,
            rstar_match,
            rho_out;
            sign=spectral.convention.infinity_sign,
            dtype=Complex{T},
            odealgo=algorithm,
            reltol=tolerances.reltol,
            abstol=tolerances.abstol,
            ode_maxiters=parse_integer(request, "homogeneous_ode_maxiters"),
            ode_observation_factory=observation_factory,
            ode_solution_observer=observe_ode_solution,
            ode_leg="r_from_rho_positive",
            r_at_rho_zero=Complex{T}(match_radius),
            verbose=false,
        )
    end
    radius_from_rho = observed_radial_map(
        raw_radius_from_rho, label, zero(T), rho_out
    )
    assert_coordinate_identity(
        T, request, spectral, radius_from_rho, rstar_match,
        Complex{T}(spectral.convention.infinity_sign) *
            exp(complex(zero(T), spectral.convention.infinity_contour_angle)),
        range(zero(T), rho_out; length=9), label,
    )
    return CF.build_outer_contour_context(
        spectral, match_radius, rstar_match, rho_out, radius_from_rho
    )
end

"""
    select_worker_outer_endpoint(T, request, spectral, match_radius, label,
                                 required_digits)

Integrate the infinity coordinate map once to the declared cap, then reuse the
same authenticated geometry to test the full increasing endpoint schedule.
The first adequate endpoint is authoritative; every attempted candidate is
retained in the progress evidence.
"""
function select_worker_outer_endpoint(
    ::Type{T},
    request,
    spectral::CF.HomogeneousSpectralContext{T},
    match_radius::T,
    label::String,
    required_digits::T,
) where {T<:AbstractFloat}
    cap_contour = build_worker_outer_contour(
        T, request, spectral, match_radius, label
    )
    raw_schedule = required(request, "rho_out_candidate_schedule")
    raw_schedule isa AbstractVector || error(
        "rho_out_candidate_schedule must be an array"
    )
    candidate_schedule = T[parse(T, string(item)) for item in raw_schedule]
    candidate_schedule = sort(unique(candidate_schedule))
    isempty(candidate_schedule) && error(
        "rho_out_candidate_schedule must not be empty"
    )
    all(isfinite(candidate) && candidate > zero(T) for candidate in candidate_schedule) ||
        error("rho_out_candidate_schedule must contain positive finite values")
    candidate_schedule[end] == cap_contour.rho_out || error(
        "rho_out_candidate_schedule must end at the authenticated rho_out cap"
    )

    evidence = Dict{String,Any}[]
    selected_contour = nothing
    selected_preparation = nothing
    final_preparation = nothing
    for rho_out in candidate_schedule
        contour = rho_out == cap_contour.rho_out ? cap_contour :
            CF.build_outer_contour_context(
                spectral,
                match_radius,
                cap_contour.rstar_match,
                rho_out,
                cap_contour.radius_from_rho,
            )
        preparation = CF.prepare_factored_infinity_outgoing(
            spectral, contour, required_digits
        )
        final_preparation = preparation
        assessment = preparation.assessment
        push!(evidence, Dict(
            "rho_out" => string(rho_out),
            "adequate" => assessment.adequate,
            "reason" => assessment.reason,
            "predicted_reliable_digits" =>
                string(assessment.predicted_reliable_digits),
            "maximum_last_term_ratio" =>
                string(assessment.maximum_last_term_ratio),
            "maximum_series_evaluation_spread" =>
                string(assessment.maximum_series_evaluation_spread),
            "maximum_recurrence_cancellation_factor" =>
                string(assessment.maximum_recurrence_cancellation_factor),
            "endpoint_order" => preparation.endpoint_order,
        ))
        if selected_contour === nothing && assessment.adequate
            selected_contour = contour
            selected_preparation = preparation
        end
    end
    if selected_contour === nothing
        # Preserve the package-owned scientific failure classification at the
        # cap instead of inventing a weaker worker-side acceptance gate.
        CF.assert_factored_preflights_adequate(final_preparation)
        error("unreachable: inadequate outer endpoint schedule")
    end
    progress_emit("outer_endpoint_selected"; payload=Dict(
        "selected_rho_out" => string(selected_contour.rho_out),
        "rho_out_cap" => string(cap_contour.rho_out),
        "candidates" => evidence,
        "geometry_reused_from_cap" => true,
    ))
    return selected_contour, selected_preparation
end

"""
    select_worker_outer_endpoint_pair(T, request, spectral, match_radius,
                                      label, required_digits)

Choose the first two authenticated adequate infinity endpoints from the
declared schedule.  Their same-point Wronskian disagreement is mandatory
evidence for the promoted exterior empirical certificate; a single adequate
endpoint is deliberately insufficient and fails before homogeneous ODE work.
"""
function select_worker_outer_endpoint_pair(
    ::Type{T},
    request,
    spectral::CF.HomogeneousSpectralContext{T},
    match_radius::T,
    label::String,
    required_digits::T,
) where {T<:AbstractFloat}
    cap_contour = build_worker_outer_contour(
        T, request, spectral, match_radius, label
    )
    raw_schedule = required(request, "rho_out_candidate_schedule")
    raw_schedule isa AbstractVector || error(
        "rho_out_candidate_schedule must be an array"
    )
    candidate_schedule = T[parse(T, string(item)) for item in raw_schedule]
    candidate_schedule = sort(unique(candidate_schedule))
    isempty(candidate_schedule) && error(
        "rho_out_candidate_schedule must not be empty"
    )
    all(isfinite(candidate) && candidate > zero(T) for candidate in candidate_schedule) ||
        error("rho_out_candidate_schedule must contain positive finite values")
    candidate_schedule[end] == cap_contour.rho_out || error(
        "rho_out_candidate_schedule must end at the authenticated rho_out cap"
    )

    evidence = Dict{String,Any}[]
    adequate = Any[]
    final_preparation = nothing
    for rho_out in candidate_schedule
        contour = rho_out == cap_contour.rho_out ? cap_contour :
            CF.build_outer_contour_context(
                spectral,
                match_radius,
                cap_contour.rstar_match,
                rho_out,
                cap_contour.radius_from_rho,
            )
        preparation = CF.prepare_factored_infinity_outgoing(
            spectral, contour, required_digits
        )
        final_preparation = preparation
        assessment = preparation.assessment
        push!(evidence, Dict(
            "rho_out" => string(rho_out),
            "adequate" => assessment.adequate,
            "reason" => assessment.reason,
            "predicted_reliable_digits" =>
                string(assessment.predicted_reliable_digits),
            "maximum_last_term_ratio" =>
                string(assessment.maximum_last_term_ratio),
            "maximum_series_evaluation_spread" =>
                string(assessment.maximum_series_evaluation_spread),
            "maximum_recurrence_cancellation_factor" =>
                string(assessment.maximum_recurrence_cancellation_factor),
            "endpoint_order" => preparation.endpoint_order,
        ))
        assessment.adequate && push!(adequate, (contour, preparation))
    end
    if length(adequate) < 2
        throw(numerical_control_failure(
            request,
            EXTERIOR_EMPIRICAL_ERROR_MISSING_OUTCOME,
            "two adequate exterior endpoints are required for the empirical determinant certificate",
            Dict{String,Any}(
                "reason" => "TWO_AUTHENTICATED_EXTERIOR_ENDPOINTS_REQUIRED",
                "available_adequate_endpoint_count" => length(adequate),
                "candidates" => evidence,
                "factored_homogeneous_rhs_evaluations_before_pair" => 0,
            );
            stage="asymptotic-preflight",
        ))
    end
    selected_contour, selected_preparation = adequate[1]
    comparison_contour, comparison_preparation = adequate[2]
    progress_emit("outer_endpoint_pair_selected"; payload=Dict(
        "selected_rho_out" => string(selected_contour.rho_out),
        "comparison_rho_out" => string(comparison_contour.rho_out),
        "rho_out_cap" => string(cap_contour.rho_out),
        "candidates" => evidence,
        "geometry_reused_from_cap" => true,
    ))
    return (
        selected_contour,
        selected_preparation,
        comparison_contour,
        comparison_preparation,
    )
end

"""
    build_worker_real_inner_horizon_contour(T, request, spectral, match_radius,
                                            label)

Build the horizon-side contour on `0 -> rho_inner_min` with a unit real tangent.

`rho_inner_min` is the authenticated adaptive-search floor rather than the much
deeper exterior asymptotic coordinate bound.  Sharing the policy value keeps
every generated endpoint inside the contour that performs the inversion.
"""
function build_worker_real_inner_horizon_contour(
    ::Type{T},
    request,
    spectral::CF.HomogeneousSpectralContext{T},
    match_radius::T,
    label::String,
) where {T<:AbstractFloat}
    rho_inner_min = parse_real(T, request, "horizon_rho_inner_min")
    rho_inner_min < zero(T) || error(
        "horizon_rho_inner_min must be negative"
    )
    rstar_match = T(GSN.rstar_from_r(spectral.a, match_radius))
    assert_match_radius_identity(T, spectral, match_radius, rstar_match)
    algorithm = AutoVern9(Rosenbrock23(autodiff=false))
    tolerances = coordinate_ode_tolerances(T, request)
    observation_factory = (leg, tspan, ode_algorithm) ->
        ode_observation_factory(request, leg, tspan, ode_algorithm)
    raw_radius_from_rho = progress_operation("r-from-rho"; payload=Dict(
        "contour_label" => label,
    )) do
        # beta = 0, sign = +1: r_*(rho) = rstar_match + rho, so the map runs
        # along the real tortoise axis toward the horizon.
        CF.solve_r_from_rho(
            spectral.a,
            zero(T),
            rstar_match,
            rho_inner_min;
            sign=Int8(1),
            dtype=Complex{T},
            odealgo=algorithm,
            reltol=tolerances.reltol,
            abstol=tolerances.abstol,
            ode_maxiters=parse_integer(request, "homogeneous_ode_maxiters"),
            ode_observation_factory=observation_factory,
            ode_solution_observer=observe_ode_solution,
            ode_leg="r_from_rho_real_inner",
            r_at_rho_zero=Complex{T}(match_radius),
            verbose=false,
        )
    end
    radius_from_rho = observed_radial_map(
        raw_radius_from_rho, label, rho_inner_min, zero(T)
    )
    assert_coordinate_identity(
        T, request, spectral, radius_from_rho, rstar_match,
        complex(one(T), zero(T)),
        range(zero(T), rho_inner_min; length=9), label,
    )
    return CF.build_real_inner_horizon_contour(
        spectral, match_radius, rstar_match, rho_inner_min, radius_from_rho
    )
end

"""
    assert_coordinate_identity(T, request, spectral, radius_from_rho,
                               rstar_match, tangent, samples, label)

Validate and report the coordinate identity
`r_*(rho) = rstar_match + tangent*rho` at retained checkpoints.

This is the direct test that the coordinate solve produced the contour it was
asked for. It is what distinguishes "the horizon expansion is inadequate" from
"the map is not going where the expansion assumes". The admissible residual is
derived from the coordinate ODE's own absolute and relative controls, projected
to tortoise coordinates by `|dr_*/dr| = |(r^2+a^2)/Delta|`; working precision
does not define a second tolerance table.
"""
struct CoordinateIdentityEvidence{T<:AbstractFloat}
    maximum_absolute_residual::T
    maximum_relative_residual::T
    absolute_tolerance::T
    relative_tolerance::T
    maximum_absolute_residual_over_tolerance::T
    maximum_relative_residual_over_tolerance::T
    sample_count::Int
end

function coordinate_identity_diagnostics(
    evidence::CoordinateIdentityEvidence{T},
    tolerances,
    label::String;
    failure_reason=nothing,
    failing_rho=nothing,
) where {T<:AbstractFloat}
    return Dict{String,Any}(
        "contour_label" => label,
        "maximum_absolute_residual" =>
            string(evidence.maximum_absolute_residual),
        "maximum_relative_residual" =>
            string(evidence.maximum_relative_residual),
        "absolute_tolerance" => string(evidence.absolute_tolerance),
        "relative_tolerance" => string(evidence.relative_tolerance),
        "maximum_absolute_residual_over_tolerance" =>
            string(evidence.maximum_absolute_residual_over_tolerance),
        "maximum_relative_residual_over_tolerance" =>
            string(evidence.maximum_relative_residual_over_tolerance),
        "coordinate_ode_relative_tolerance" => string(tolerances.reltol),
        "coordinate_ode_absolute_tolerance" => string(tolerances.abstol),
        "sample_count" => evidence.sample_count,
        "failure_reason" => failure_reason,
        "failing_rho" => failing_rho === nothing ?
            nothing : string(failing_rho),
    )
end

function throw_coordinate_identity_mismatch(
    request,
    evidence::CoordinateIdentityEvidence,
    tolerances,
    label::String,
    reason::String;
    failing_rho=nothing,
)
    diagnostics = coordinate_identity_diagnostics(
        evidence,
        tolerances,
        label;
        failure_reason=reason,
        failing_rho=failing_rho,
    )
    progress_emit(
        "coordinate_identity_checked";
        payload=merge(diagnostics, Dict{String,Any}(
            "passed" => false,
            "failure_code" => "COORDINATE_IDENTITY_MISMATCH",
        )),
    )
    throw(numerical_control_failure(
        request,
        "COORDINATE_IDENTITY_MISMATCH",
        "$(label) failed the coordinate identity gate: $(reason)",
        diagnostics;
        retryable=true,
        stage="coordinate-inversion",
    ))
end


function assert_coordinate_identity(
    ::Type{T},
    request,
    spectral::CF.HomogeneousSpectralContext{T},
    radius_from_rho,
    rstar_match::T,
    tangent::Complex{T},
    samples,
    label::String,
) where {T<:AbstractFloat}
    tolerances = coordinate_ode_tolerances(T, request)
    all(isfinite, (tolerances.reltol, tolerances.abstol)) &&
        tolerances.reltol > zero(T) && tolerances.abstol > zero(T) ||
        error("coordinate ODE tolerances must be finite and positive")
    sample_count = length(samples)
    sample_count > 0 || error("coordinate identity requires retained samples")
    maximum_absolute = zero(T)
    maximum_relative = zero(T)
    absolute_tolerance = zero(T)
    relative_tolerance = zero(T)
    maximum_absolute_ratio = zero(T)
    maximum_relative_ratio = zero(T)
    evidence() = CoordinateIdentityEvidence{T}(
        maximum_absolute,
        maximum_relative,
        absolute_tolerance,
        relative_tolerance,
        maximum_absolute_ratio,
        maximum_relative_ratio,
        sample_count,
    )
    for rho in samples
        typed_rho = T(rho)
        radius = Complex{T}(radius_from_rho(typed_rho))
        if !(isfinite(typed_rho) && isfinite(real(radius)) &&
             isfinite(imag(radius)))
            throw_coordinate_identity_mismatch(
                request,
                evidence(),
                tolerances,
                label,
                "NONFINITE_COORDINATE_IDENTITY_SAMPLE";
                failing_rho=typed_rho,
            )
        end
        expected = complex(rstar_match, zero(T)) + tangent * typed_rho
        observed = Complex{T}(GSN.rstar_from_r(spectral.a, radius))
        delta = Complex{T}(Kerr.Delta(spectral.a, radius))
        radial_error_tolerance = tolerances.abstol +
            tolerances.reltol * max(abs(radius), one(T))
        tortoise_jacobian = abs(
            (radius^2 + complex(spectral.a^2, zero(T))) / delta
        )
        if !(isfinite(real(expected)) && isfinite(imag(expected)) &&
             isfinite(real(observed)) && isfinite(imag(observed)) &&
             isfinite(radial_error_tolerance) &&
             isfinite(tortoise_jacobian))
            throw_coordinate_identity_mismatch(
                request,
                evidence(),
                tolerances,
                label,
                "NONFINITE_COORDINATE_IDENTITY_PROJECTION";
                failing_rho=typed_rho,
            )
        end
        residual = abs(observed - expected)
        scale = max(abs(expected), one(T))
        relative_residual = residual / scale
        sample_absolute_tolerance =
            tortoise_jacobian * radial_error_tolerance
        sample_relative_tolerance = sample_absolute_tolerance / scale
        if !(isfinite(residual) && isfinite(relative_residual) &&
             isfinite(sample_absolute_tolerance) &&
             isfinite(sample_relative_tolerance) &&
             sample_absolute_tolerance > zero(T) &&
             sample_relative_tolerance > zero(T))
            throw_coordinate_identity_mismatch(
                request,
                evidence(),
                tolerances,
                label,
                "NONFINITE_COORDINATE_IDENTITY_RESIDUAL";
                failing_rho=typed_rho,
            )
        end
        maximum_absolute = max(maximum_absolute, residual)
        maximum_relative = max(maximum_relative, relative_residual)
        absolute_tolerance = max(
            absolute_tolerance, sample_absolute_tolerance
        )
        relative_tolerance = max(
            relative_tolerance, sample_relative_tolerance
        )
        maximum_absolute_ratio = max(
            maximum_absolute_ratio,
            residual / sample_absolute_tolerance,
        )
        maximum_relative_ratio = max(
            maximum_relative_ratio,
            relative_residual / sample_relative_tolerance,
        )
    end
    result = evidence()
    all(isfinite, (
        result.maximum_absolute_residual,
        result.maximum_relative_residual,
        result.absolute_tolerance,
        result.relative_tolerance,
        result.maximum_absolute_residual_over_tolerance,
        result.maximum_relative_residual_over_tolerance,
    )) || throw_coordinate_identity_mismatch(
        request,
        result,
        tolerances,
        label,
        "NONFINITE_COORDINATE_IDENTITY_EVIDENCE",
    )
    if result.maximum_absolute_residual_over_tolerance > one(T) ||
       result.maximum_relative_residual_over_tolerance > one(T)
        throw_coordinate_identity_mismatch(
            request,
            result,
            tolerances,
            label,
            "COORDINATE_IDENTITY_RESIDUAL_EXCEEDS_TOLERANCE",
        )
    end
    diagnostics = coordinate_identity_diagnostics(
        result, tolerances, label
    )
    progress_emit("coordinate_identity_checked"; payload=Dict{String,Any}(
        diagnostics...,
        "passed" => true,
    ))
    return result
end

"""
    endpoint_regularity(preparation)

Return the remainder-regularity evidence for an endpoint preparation.

Series-seeded preparations carry it under their initial condition; real-inner
horizon endpoints are built from an explicit-tangent carrier rather than a
`FactoredInitialCondition`, so they carry it directly.
"""
endpoint_regularity(preparation::CF.FactoredEndpointPreparation) =
    preparation.initial_condition.regularity
endpoint_regularity(endpoint::CF.RealInnerHorizonEndpoint) =
    endpoint.regularity

function endpoint_conditioning_summary(preparations...)
    isempty(preparations) && error("at least one endpoint preparation is required")
    maximum_series_digits_lost = maximum(
        preparation.assessment.maximum_series_evaluation_digits_lost
        for preparation in preparations
    )
    maximum_recurrence_digits_lost = maximum(
        preparation.assessment.maximum_recurrence_digits_lost
        for preparation in preparations
    )
    maximum_series_evaluation_spread = maximum(
        preparation.assessment.maximum_series_evaluation_spread
        for preparation in preparations
    )
    maximum_last_term_ratio = maximum(
        preparation.assessment.maximum_last_term_ratio
        for preparation in preparations
    )
    minimum_asymptotic_predicted_reliable_digits = minimum(
        preparation.assessment.predicted_reliable_digits
        for preparation in preparations
    )
    endpoint_remainders_regular = all(
        endpoint_regularity(preparation).finite
        for preparation in preparations
    )
    maximum_endpoint_reconstruction_error = maximum(
        max(
            endpoint_regularity(preparation).relative_X_reconstruction_error,
            endpoint_regularity(preparation).relative_Xrho_reconstruction_error,
            endpoint_regularity(preparation).Xrho_backward_residual,
        )
        for preparation in preparations
    )
    return (
        maximum_series_digits_lost=maximum_series_digits_lost,
        maximum_recurrence_digits_lost=maximum_recurrence_digits_lost,
        maximum_series_evaluation_spread=maximum_series_evaluation_spread,
        maximum_last_term_ratio=maximum_last_term_ratio,
        minimum_asymptotic_predicted_reliable_digits=
            minimum_asymptotic_predicted_reliable_digits,
        endpoint_remainders_regular=endpoint_remainders_regular,
        maximum_endpoint_reconstruction_error=
            maximum_endpoint_reconstruction_error,
    )
end

function emit_asymptotic_preparation(preparation)
    assessment = preparation.assessment
    progress_emit("asymptotic_series_evaluated"; payload=Dict(
        "branch" => string(preparation.branch),
        "adequate" => assessment.adequate,
        "maximum_series_digits_lost" =>
            string(assessment.maximum_series_evaluation_digits_lost),
        "maximum_recurrence_digits_lost" =>
            string(assessment.maximum_recurrence_digits_lost),
        "maximum_series_evaluation_spread" =>
            string(assessment.maximum_series_evaluation_spread),
        "maximum_last_term_ratio" =>
            string(assessment.maximum_last_term_ratio),
        "predicted_reliable_digits" =>
            string(assessment.predicted_reliable_digits),
        "required_reliable_digits" => string(assessment.required_digits),
    ))
    return nothing
end

function emit_factored_solution(solution)
    diagnostics = solution.diagnostics
    diagnostics.representation_id == HOMOGENEOUS_REPRESENTATION_ID ||
        error("package factored representation identity changed")
    diagnostics.ode_scope_id == FACTORED_HOMOGENEOUS_ODE_SCOPE_ID ||
        error("package factored ODE scope identity changed")
    progress_emit("factored_ode_completed"; payload=Dict(
        "branch" => string(diagnostics.branch),
        "ode_leg" => diagnostics.ode_leg,
        "representation_id" => diagnostics.representation_id,
        "ode_scope_id" => diagnostics.ode_scope_id,
        "factored_homogeneous_rhs_evaluations" =>
            diagnostics.factored_homogeneous_rhs_evaluations,
        "maximum_remainder_state_norm" =>
            string(diagnostics.maximum_remainder_state_norm),
        "minimum_remainder_state_norm" =>
            string(diagnostics.minimum_remainder_state_norm),
        "maximum_absolute_real_carrier_log" =>
            string(diagnostics.maximum_absolute_real_carrier_log),
        "endpoint_only_saved_points" =>
            diagnostics.endpoint_only_saved_points,
        "maximum_contour_angle_deformation" => string(
            diagnostics.contour_deformation.maximum_absolute
        ),
    ))
    return nothing
end

function record_determinant!(
    accumulator::ConditioningAccumulator{T},
    diagnostics::DeterminantDiagnostics{T},
) where {T<:AbstractFloat}
    accumulator.maximum_series_digits_lost = max(
        accumulator.maximum_series_digits_lost,
        diagnostics.maximum_series_digits_lost,
    )
    accumulator.maximum_recurrence_digits_lost = max(
        accumulator.maximum_recurrence_digits_lost,
        diagnostics.maximum_recurrence_digits_lost,
    )
    accumulator.maximum_series_evaluation_spread = max(
        accumulator.maximum_series_evaluation_spread,
        diagnostics.maximum_series_evaluation_spread,
    )
    accumulator.maximum_last_term_ratio = max(
        accumulator.maximum_last_term_ratio,
        diagnostics.maximum_last_term_ratio,
    )
    accumulator.minimum_asymptotic_predicted_reliable_digits =
        accumulator.minimum_asymptotic_predicted_reliable_digits === nothing ?
            diagnostics.minimum_asymptotic_predicted_reliable_digits :
            min(
                accumulator.minimum_asymptotic_predicted_reliable_digits,
                diagnostics.minimum_asymptotic_predicted_reliable_digits,
            )
    accumulator.endpoint_remainders_regular &=
        diagnostics.endpoint_remainders_regular
    accumulator.maximum_endpoint_reconstruction_error = max(
        accumulator.maximum_endpoint_reconstruction_error,
        diagnostics.maximum_endpoint_reconstruction_error,
    )
    accumulator.maximum_contour_angle_deformation = max(
        accumulator.maximum_contour_angle_deformation,
        diagnostics.maximum_contour_angle_deformation,
    )
    if diagnostics.scattering_diagnostics_applicable
        for (field, value) in (
            (:maximum_basis_condition, diagnostics.maximum_basis_condition),
            (:maximum_basis_backward_error,
                diagnostics.maximum_basis_backward_error),
            (:maximum_matching_reconstruction_residual,
                diagnostics.maximum_matching_reconstruction_residual),
            (:maximum_carrier_change_error,
                diagnostics.maximum_carrier_change_error),
        )
            value === nothing && error("missing horizon scattering diagnostic")
            previous = getfield(accumulator, field)
            setfield!(
                accumulator,
                field,
                previous === nothing ? value : max(previous, value),
            )
        end
        diagnostics.minimum_cref_chart_margin === nothing &&
            error("missing horizon Cref chart margin")
        accumulator.minimum_cref_chart_margin =
            accumulator.minimum_cref_chart_margin === nothing ?
                diagnostics.minimum_cref_chart_margin :
                min(
                    accumulator.minimum_cref_chart_margin,
                    diagnostics.minimum_cref_chart_margin,
                )
    end
    accumulator.determinant_count += 1
    return accumulator
end

function record_finite_difference!(
    accumulator::ConditioningAccumulator{T},
    diagnostics::FiniteDifferenceDiagnostics{T},
) where {T<:AbstractFloat}
    accumulator.maximum_fd_digits_lost = max(
        accumulator.maximum_fd_digits_lost,
        diagnostics.finite_difference_digits_lost,
    )
    accumulator.finite_difference_saturation_observed |=
        diagnostics.saturation_observed
    accumulator.finite_difference_underflow_observed |=
        diagnostics.underflow_observed
    return accumulator
end

"""
    CONTROL_FAILURE_STAGES

The pipeline stages a typed control failure can be attributed to.

A failure code says *what* went wrong; the stage says *where*. Without it a
campaign reading a receipt cannot tell an endpoint geometry rejection from a
coordinate stall from a derivative that never resolved, because several codes
can arise at more than one point in the pipeline.
"""
const CONTROL_FAILURE_STAGES = Set([
    "request-policy",
    "coordinate-inversion",
    "horizon-endpoint-geometry",
    "asymptotic-preflight",
    "homogeneous-propagation",
    "scattering-extraction",
    "determinant-chart",
    "finite-difference",
    "root-authentication",
])

function control_failure_stage(stage::String)
    stage in CONTROL_FAILURE_STAGES ||
        error("unknown control failure stage $(repr(stage))")
    return stage
end

function numerical_control_failure(
    request,
    failure_code::String,
    message::String,
    diagnostics::Dict{String,Any};
    retryable::Bool=false,
    stage::String="determinant-chart",
)
    details = merge(control_failure_context(request), Dict{String,Any}(
        "failure_code" => failure_code,
        "failure_class" => "CONTROL",
        "retryable" => retryable,
        "stage" => control_failure_stage(stage),
        "diagnostics" => diagnostics,
    ))
    return NumericalControlFailure(message, details)
end

function horizon_endpoint_recovery_failure(request, outcome, evidence)
    outcome_to_failure = Dict(
        CF.NO_GEOMETRY_VALID_CANDIDATE => "HORIZON_GEOMETRY_EXHAUSTED",
        CF.MAX_SERIES_ORDER_INADEQUATE => "HORIZON_MAXIMUM_ORDER_INADEQUATE",
        CF.ARITHMETIC_PRECISION_INADEQUATE => "HORIZON_ARITHMETIC_INADEQUATE",
        CF.COORDINATE_INVERSION_FAILURE => "HORIZON_COORDINATE_INVERSION_FAILED",
        CF.FEWER_THAN_TWO_VERIFIED_ENDPOINTS => "HORIZON_ONLY_ONE_ENDPOINT",
    )
    haskey(outcome_to_failure, outcome) || error(
        "unknown horizon endpoint recovery outcome $(repr(outcome))"
    )
    diagnostics = Dict{String,Any}(
        "recovery_outcome" => outcome,
        "recovery_evidence" => evidence,
        "next_precision_tier_allowed" =>
            outcome == CF.ARITHMETIC_PRECISION_INADEQUATE,
    )
    return numerical_control_failure(
        request,
        outcome_to_failure[outcome],
        "horizon endpoint recovery failed: $(outcome)",
        diagnostics;
        retryable=outcome == CF.ARITHMETIC_PRECISION_INADEQUATE,
        stage=outcome == CF.COORDINATE_INVERSION_FAILURE ?
            "coordinate-inversion" : "horizon-endpoint-geometry",
    )
end

function canonical_horizon_coordinate_failure_evidence(request)
    endpoint_base_order = parse_integer(request, "endpoint_series_order")
    endpoint_orders = CF.horizon_endpoint_order_ladder(
        endpoint_base_order;
        maximum_order=horizon_endpoint_maximum_order(
            request, endpoint_base_order
        ),
    )
    return Dict{String,Any}(
        "outcome" => CF.COORDINATE_INVERSION_FAILURE,
        "policy_identity" => string(required(
            request, "horizon_endpoint_recovery_policy_identity"
        )),
        "selected_pair" => Any[],
        "rejected_candidates" => Any[],
        "endpoint_orders" => endpoint_orders,
        "homogeneous_rhs_evaluations_before_pair" => 0,
    )
end

function translate_numerical_control_failure(
    request,
    failure;
    finite_difference_axis=nothing,
    finite_difference_h=nothing,
)
    failure isa WorkerControlFailure && return failure
    if failure isa FiniteDifferenceRangeError
        finite_difference_axis in ("real", "imaginary") || return failure
        finite_difference_h isa AbstractFloat || return failure
        isfinite(finite_difference_h) && finite_difference_h > 0 ||
            return failure
        diagnostics = Dict{String,Any}(
            "reason" => failure.status,
            "range_status" => failure.status,
            "operation" => "finite-difference-derivative/v1",
            "axis" => finite_difference_axis,
            "h" => string(finite_difference_h),
        )
        return numerical_control_failure(
            request,
            "ALGEBRAIC_REPRESENTATION_SINGULAR",
            sprint(showerror, failure),
            diagnostics;
            retryable=false,
            stage="finite-difference",
        )
    end
    if failure isa CF.FactoredPropagationError
        raw_code = string(failure.reason)
        failure_code = if raw_code in (
            "INVALID_ASYMPTOTIC_INPUT",
            "PRECISION_MISMATCH",
            "NONFINITE_ASYMPTOTIC_DATA",
        )
            "ASYMPTOTIC_SERIES_INVALID"
        else
            raw_code
        end
        recognized = failure_code in (
            "ASYMPTOTIC_SERIES_INVALID",
            "INSUFFICIENT_ASYMPTOTIC_PRECISION",
            "PHYSICAL_SINGULAR_LIMIT",
            "ALGEBRAIC_REPRESENTATION_SINGULAR",
            "CARRIER_CHANGE_INCONSISTENT",
            "INVALID_FACTORED_PROPAGATION_INPUT",
            "FACTORED_PROPAGATION_PRECISION_MISMATCH",
            "NONFINITE_FACTORED_PROPAGATION_DATA",
            "FACTORED_ODE_FAILURE",
            "NO_VERIFIED_HORIZON_ENDPOINT",
            "COORDINATE_INVERSION_STALLED",
        )
        recognized || return failure
        diagnostics = Dict{String,Any}(
            "reason" => raw_code,
            "precision_bits" => failure.precision_bits,
            "factored_homogeneous_rhs_evaluations" =>
                failure.factored_homogeneous_rhs_evaluations,
            "avoided_ode_scope" => failure.avoided_ode_scope,
        )
        retryable = false
        if failure_code == "INSUFFICIENT_ASYMPTOTIC_PRECISION"
            assessment = failure.assessment
            assessment === nothing && return failure
            failure.avoided_ode_scope ==
                FACTORED_HOMOGENEOUS_ODE_SCOPE_ID ||
                error("inadequate preflight reported an unexpected ODE scope")
            factored_homogeneous_rhs_evaluations =
                failure.factored_homogeneous_rhs_evaluations
            factored_homogeneous_rhs_evaluations == 0 ||
                error("inadequate asymptotic preflight followed factored RHS work")
            diagnostics = merge(diagnostics, Dict{String,Any}(
                "predicted_reliable_digits" =>
                    string(assessment.predicted_reliable_digits),
                "required_reliable_digits" =>
                    string(assessment.required_digits),
                "asymptotic_preflight_avoided_ode" => true,
                "asymptotic_preflight_reason" => failure_code,
                "maximum_series_digits_lost" =>
                    string(assessment.maximum_series_evaluation_digits_lost),
                "maximum_recurrence_digits_lost" =>
                    string(assessment.maximum_recurrence_digits_lost),
            ))
            retryable = true
        end
        stage = if failure_code == "NO_VERIFIED_HORIZON_ENDPOINT"
            "horizon-endpoint-geometry"
        elseif failure_code == "COORDINATE_INVERSION_STALLED"
            "coordinate-inversion"
        elseif failure_code in (
            "ASYMPTOTIC_SERIES_INVALID",
            "INSUFFICIENT_ASYMPTOTIC_PRECISION",
        )
            "asymptotic-preflight"
        else
            "homogeneous-propagation"
        end
        return numerical_control_failure(
            request,
            failure_code,
            sprint(showerror, failure),
            diagnostics;
            retryable=retryable,
            stage=stage,
        )
    end
    if failure isa Solutions.ScatteringExtractionError
        failure_code = string(failure.reason)
        failure_code in (
            "SCATTERING_BASIS_ILL_CONDITIONED",
            "SCATTERING_CHART_ILL_CONDITIONED",
        ) || return failure
        diagnostics = Dict{String,Any}(
            "reason" => failure_code,
            "precision_bits" => failure.precision_bits,
        )
        return numerical_control_failure(
            request,
            failure_code,
            sprint(showerror, failure),
            diagnostics;
            stage=failure_code == "SCATTERING_CHART_ILL_CONDITIONED" ?
                "determinant-chart" : "scattering-extraction",
        )
    end
    return failure
end

wronskian(left, right) = left[1] * right[2] - left[2] * right[1]

function compact_profile(radius, centre, half_width, amplitude)
    scaled = (radius - centre) / half_width
    abs(scaled) >= one(scaled) && return zero(amplitude)
    return amplitude * exp(one(scaled) - inv(one(scaled) - scaled^2))
end

function exterior_support_contract(::Type{T}, request, a::T, readout::T) where {T<:AbstractFloat}
    lower = parse_real(T, request, "support_lower")
    upper = parse_real(T, request, "support_upper")
    centre = parse_real(T, request, "support_centre")
    half_width = parse_real(T, request, "support_half_width")
    half_width > zero(T) || error("support half_width must be positive")
    lower < upper || error("support lower bound must be below upper bound")
    geometry_tolerance = parse(T, "1e-14") * max(
        one(T), abs(lower), abs(upper), abs(centre), abs(half_width)
    )
    isapprox(
        lower, centre - half_width;
        atol=geometry_tolerance,
        rtol=zero(T),
    ) || error("support lower bound is inconsistent with centre and half_width")
    isapprox(
        upper, centre + half_width;
        atol=geometry_tolerance,
        rtol=zero(T),
    ) || error("support upper bound is inconsistent with centre and half_width")
    lower > Kerr.r_plus(a) || error("exterior support is not outside the horizon")
    upper < readout || error("exterior support must lie below the readout radius")
    parse_integer(request, "support_subinterval_count") > 0 ||
        error("support_subinterval_count must be positive")
    return lower, upper
end

function radial_rhs!(du, state, parameters, radius)
    w = Kerr.Delta(parameters.a, radius) / (radius^2 + parameters.a^2)
    F = Potentials.sF(
        parameters.s,
        parameters.m,
        parameters.a,
        parameters.omega,
        parameters.lambda,
        radius,
    )
    U = Potentials.sU(
        parameters.s,
        parameters.m,
        parameters.a,
        parameters.omega,
        parameters.lambda,
        radius,
    )
    profile = compact_profile(
        radius,
        parameters.centre,
        parameters.half_width,
        parameters.amplitude,
    )
    du[1] = state[2] / w
    du[2] = (F * state[2] + U * state[1]) / w - w * profile * state[1]
    return nothing
end

function solve_radial_endpoint(
    ::Type{T},
    request,
    omega::Complex{T},
    lambda::Complex{T},
    start_radius::T,
    stop_radius::T,
    seed,
    amplitude::Complex{T},
    dtmax::T;
    ode_leg::String,
) where {T<:AbstractFloat}
    parameters = (
        s=parse_integer(request, "s"),
        m=parse_integer(request, "m"),
        a=parse_real(T, request, "spin"),
        omega=omega,
        lambda=lambda,
        centre=parse_real(T, request, "support_centre"),
        half_width=parse_real(T, request, "support_half_width"),
        amplitude=amplitude,
    )
    initial = Complex{T}[seed[1], seed[2]]
    problem = ODEProblem(
        radial_rhs!,
        initial,
        (start_radius, stop_radius),
        parameters,
    )
    algorithm = AutoVern9(Rosenbrock23(autodiff=false))
    observation_callback, observation = ode_observation_factory(
        request, ode_leg, (start_radius, stop_radius), algorithm
    )
    solve_arguments = observation_callback === nothing ?
        NamedTuple() : (; callback=observation_callback)
    ode_maxiters = parse_integer(request, "homogeneous_ode_maxiters")
    solution = solve(
        problem,
        algorithm;
        reltol=parse_real(T, request, "ode_relative_tolerance"),
        abstol=parse_real(T, request, "ode_absolute_tolerance"),
        dtmax=dtmax,
        maxiters=ode_maxiters,
        tstops=[stop_radius],
        save_everystep=false,
        save_start=false,
        save_end=true,
        dense=false,
        solve_arguments...
    )
    observe_ode_solution(ode_leg, solution, observation)
    endpoint = solution.u[end]
    return Complex{T}[endpoint[1], endpoint[2]]
end

function integrate_real_branch(
    ::Type{T},
    request,
    omega::Complex{T},
    lambda::Complex{T},
    start_radius::T,
    stop_radius::T,
    seed,
    amplitude::Complex{T};
    ode_leg="perturbed_Xin",
) where {T<:AbstractFloat}
    lower = parse_real(T, request, "support_lower")
    upper = parse_real(T, request, "support_upper")
    half_width = parse_real(T, request, "support_half_width")
    support_count = parse_integer(request, "support_subinterval_count")
    start_radius == lower ||
        error("perturbed integration must start at the compact support boundary")
    stop_radius >= upper ||
        error("perturbed integration must reach the compact support boundary")

    fine_dtmax = min(T(0.2), T(2) * half_width / T(support_count))
    support_endpoint = solve_radial_endpoint(
        T,
        request,
        omega,
        lambda,
        lower,
        upper,
        seed,
        amplitude,
        fine_dtmax;
        ode_leg="$(ode_leg)_compact_support",
    )
    stop_radius == upper && return support_endpoint

    vacuum_tail_dtmax = T(0.2)
    return solve_radial_endpoint(
        T,
        request,
        omega,
        lambda,
        upper,
        stop_radius,
        support_endpoint,
        zero(amplitude),
        vacuum_tail_dtmax;
        ode_leg="$(ode_leg)_vacuum_tail",
    )
end

"""
    evaluate_horizon_chart(T, request, spectral, amplitude, xup_match,
                           outer_contour, inner_contour, basis_solution, role)

Extract Cref/Cinc at the matching point from one verified horizon basis and
evaluate the reflectivity chart.

`xup_match` is the infinity-outgoing solution already propagated to `rho = 0`;
it is reconstructed to a physical `(X, dX/dr_*)` pair and re-factored into the
horizon-ingoing carrier so that all three solutions are expressed in one
carrier before the 2x2 solve. The two horizon columns come from independent
homogeneous legs seeded at a verified real-inner endpoint, so they form an
actual solution basis rather than one solution carried into horizon
coordinates.
"""
function evaluate_horizon_chart(
    ::Type{T},
    request,
    spectral::CF.HomogeneousSpectralContext{T},
    amplitude::Complex{T},
    xup_match::CF.FactoredODESolution{T},
    outer_contour,
    inner_contour::CF.RealInnerHorizonContour{T},
    basis_solution::CF.VerifiedHorizonBasisSolution{T},
    role::String,
) where {T<:AbstractFloat}
    outer_raw = reconstruct_state(
        xup_match.endpoint, xup_match.carrier, zero(T)
    )
    # The infinity leg stores dX/drho along its own contour; convert back to
    # the tortoise derivative before re-factoring against the horizon tangent.
    outer_dX_drstar = outer_raw.Xrho / outer_contour.infinity_tangent
    ingoing = basis_solution.ingoing
    outgoing = basis_solution.outgoing
    target = GSN.FactoredSolutions.factor_physical_match_state(
        outer_raw.X,
        outer_dX_drstar,
        ingoing.carrier,
        inner_contour.tangent,
    )
    basis = Solutions.build_match_horizon_basis(
        ingoing.endpoint,
        ingoing.carrier,
        outgoing.endpoint,
        outgoing.carrier,
        inner_contour.tangent,
        Complex{T}(inner_contour.match_radius),
        spectral.precision_bits,
    )
    coefficients = Solutions.solve_scaled_horizon_basis_at_match(
        target, ingoing.carrier, basis
    )
    coefficient_diagnostics = coefficients.diagnostics
    coefficient_diagnostics.extraction_id ==
        HORIZON_BASIS_AT_MATCH_EXTRACTION_ID ||
        error("package horizon match-basis extraction identity changed")
    coefficient_diagnostics.column_convention ==
        SCATTERING_COLUMN_CONVENTION_ID ||
        error("package scattering column convention changed")
    coefficient_diagnostics.factored_state_convention ==
        FACTORED_REMAINDER_STATE_CONVENTION_ID ||
        error("package factored scattering state convention changed")
    cref_abs = abs(coefficients.Cref)
    cinc_abs = abs(coefficients.Cinc)
    cref_fraction = cref_abs / max(hypot(cref_abs, cinc_abs), floatmin(T))
    progress_emit("scattering_coefficients_extracted"; payload=Dict(
        "basis_role" => role,
        "endpoint_rho" => string(basis_solution.rho_endpoint),
        "horizon_distance" => string(basis_solution.horizon_distance),
        "Cref" => progress_complex(coefficients.Cref),
        "Cinc" => progress_complex(coefficients.Cinc),
        "cref_fraction" => string(cref_fraction),
        "basis_condition" =>
            string(coefficient_diagnostics.condition_frobenius),
        "basis_backward_error" =>
            string(coefficient_diagnostics.backward_error),
        "matching_reconstruction_residual" => string(
            coefficient_diagnostics.matching_reconstruction_residual
        ),
        "scaled_basis_determinant_abs" => string(
            coefficient_diagnostics.scaled_basis_determinant_abs
        ),
        "column_norm_1" => string(coefficient_diagnostics.column_norm_1),
        "column_norm_2" => string(coefficient_diagnostics.column_norm_2),
        "carrier_change_error" =>
            string(coefficient_diagnostics.carrier_change_error),
    ))
    chart = evaluate_horizon_reflectivity_chart(
        T, request, spectral, amplitude, coefficients, basis_solution
    )
    return (
        value=chart.value,
        assessment=chart.assessment,
        coefficients=coefficients,
        coefficient_diagnostics=coefficient_diagnostics,
        cref_fraction=cref_fraction,
        basis_solution=basis_solution,
        role=role,
    )
end

function determinant_error_breakdown(
    ::Type{T},
    request,
    endpoint_disagreement_abs::T;
    control_disagreement_abs::Union{Nothing,T}=nothing,
    equivalence_disagreement_abs::Union{Nothing,T}=nothing,
    precision_disagreement_abs::Union{Nothing,T}=nothing,
) where {T<:AbstractFloat}
    safety_factor = parse_real(T, request, "determinant_error_safety_factor")
    available_components = T[endpoint_disagreement_abs]
    for component in (
        control_disagreement_abs,
        equivalence_disagreement_abs,
        precision_disagreement_abs,
    )
        component === nothing || push!(available_components, component)
    end
    numerical_error_abs = safety_factor * maximum(available_components)
    return DeterminantErrorBreakdown{T}(
        endpoint_disagreement_abs,
        control_disagreement_abs,
        equivalence_disagreement_abs,
        precision_disagreement_abs,
        safety_factor,
        numerical_error_abs,
    )
end

function maximum_optional_discrepancy(
    ::Type{T}, values...
) where {T<:AbstractFloat}
    available = T[T(value) for value in values if value !== nothing]
    isempty(available) && return nothing
    all(value -> isfinite(value) && value >= zero(T), available) ||
        throw(ArgumentError(
            "optional determinant discrepancies must be finite and nonnegative"
        ))
    return maximum(available)
end

const HORIZON_CHART_IDENTITY_EXPECTATIONS = (
    (:homogeneous_representation, HOMOGENEOUS_REPRESENTATION_ID),
    (:branch_convention, BRANCH_CONVENTION_ID),
    (:scattering_coefficient_extraction,
        HORIZON_BASIS_AT_MATCH_EXTRACTION_ID),
    (:scattering_column_convention,
        SCATTERING_COLUMN_CONVENTION_ID),
    (:radial_derivative_convention,
        RADIAL_DERIVATIVE_CONVENTION_ID),
    (:determinant_convention,
        HORIZON_DETERMINANT_CONVENTION_ID),
    (:regular_remainder_contract, REGULAR_REMAINDER_CONTRACT_ID),
    (:factored_remainder_state_convention,
        FACTORED_REMAINDER_STATE_CONVENTION_ID),
    (:horizon_determinant_chart,
        HORIZON_DETERMINANT_NORMALISATION_ID),
)

function assert_horizon_chart_identities(chart_assessment)
    for (field, expected) in HORIZON_CHART_IDENTITY_EXPECTATIONS
        getfield(chart_assessment, field) == expected || error(
            "package horizon chart $(String(field)) identity changed"
        )
    end
    return nothing
end

function evaluate_horizon_reflectivity_chart(
    ::Type{T},
    request,
    spectral::CF.HomogeneousSpectralContext{T},
    amplitude::Complex{T},
    coefficients,
    basis_solution,
) where {T<:AbstractFloat}
    chart_denominator = T(2) * im * spectral.p_horizon - amplitude
    chart_scale = max(T(2) * abs(spectral.p_horizon), abs(amplitude))
    if iszero(chart_denominator)
        throw(numerical_control_failure(
            request,
            "ALGEBRAIC_REPRESENTATION_SINGULAR",
            "horizon reflectivity chart denominator is exactly zero",
            Dict{String,Any}(
                "chart_denominator_abs" => string(abs(chart_denominator)),
                "chart_scale_abs" => string(chart_scale),
            ),
        ))
    end
    chart_relative_margin = abs(chart_denominator) /
        max(chart_scale, floatmin(T))
    chart_relative_margin > sqrt(eps(T)) || throw(
        numerical_control_failure(
            request,
            "SCATTERING_CHART_ILL_CONDITIONED",
            "horizon reflectivity chart denominator is numerically unresolved",
            Dict{String,Any}(
                "chart_denominator_abs" => string(abs(chart_denominator)),
                "chart_scale_abs" => string(chart_scale),
                "chart_relative_margin" => string(chart_relative_margin),
            ),
        )
    )
    reflectivity = amplitude / (T(2) * im * spectral.p_horizon - amplitude)
    series_spread = max(
        basis_solution.ingoing_endpoint.assessment.maximum_series_evaluation_spread,
        basis_solution.outgoing_endpoint.assessment.maximum_series_evaluation_spread,
    )
    coefficient_scale = max(
        abs(coefficients.Cref), abs(coefficients.Cinc), floatmin(T)
    )
    chart_inputs = Solutions.ScatteringChartErrorInputs{T}(
        coefficient_scale,
        series_spread,
        parse_real(T, request, "homogeneous_ode_relative_tolerance"),
    )
    chart = Solutions.evaluate_normalised_horizon_determinant(
        coefficients, reflectivity, chart_inputs
    )
    chart_assessment = chart.assessment
    assert_horizon_chart_identities(chart_assessment)
    chart_assessment.normalised_determinant_abs === nothing &&
        error("safe horizon chart omitted its normalised determinant")
    progress_emit("horizon_chart_evaluated"; payload=Dict(
        "Cinc_abs" => string(chart_assessment.cinc_abs),
        "Cref_abs" => string(chart_assessment.cref_abs),
        "reflectivity_abs" => string(abs(reflectivity)),
        "raw_determinant_abs" =>
            chart_assessment.raw_determinant_abs === nothing ?
                nothing : string(chart_assessment.raw_determinant_abs),
        "raw_determinant_evidence_status" =>
            chart_assessment.raw_determinant_evidence_status,
        "normalised_determinant_abs" =>
            string(chart_assessment.normalised_determinant_abs),
        "cref_chart_margin" =>
            string(chart_assessment.cref_chart_margin),
        "equivalence_disagreement_abs" =>
            chart_assessment.equivalence_disagreement_abs === nothing ?
                nothing :
                string(chart_assessment.equivalence_disagreement_abs),
    ))
    return (value=chart.value, assessment=chart_assessment)
end

"""
    evaluate_horizon_determinant(T, request, context, omega, amplitude)

Evaluate the horizon determinant on the three-leg verified horizon-basis graph.

    infinity outgoing:  outer endpoint  -> match
    horizon ingoing:    real-inner endpoint -> match
    horizon outgoing:   real-inner endpoint -> match

The two horizon legs are independent homogeneous solutions seeded from their
own expansions at a verified real-inner endpoint, so at the matching point they
form an actual solution basis. That replaces the previous mixed leg, which
carried the propagated infinity solution from the match point down to the inner
endpoint in horizon coordinates and cost ~1.96M RHS evaluations against 10,820
for the horizon pair.

Both horizon legs are repeated from the verification endpoint. The outer leg is
computed once and reused, since it does not depend on the horizon endpoint. The
disagreement between the two determinant values is the endpoint contribution to
the absolute determinant error.
"""
function evaluate_horizon_determinant(
    ::Type{T},
    request,
    context::DeterminantRequestContext{T},
    omega::Complex{T},
    amplitude::Complex{T},
) where {T<:AbstractFloat}
    readout = parse_real(T, request, "readout_radius")
    spectral = build_sample_spectral_context(T, request, omega, context)
    required_digits = required_reliable_digits(T, request)
    factored_homogeneous_rhs_counter = Ref(0)
    observation_factory = (leg, tspan, algorithm) ->
        ode_observation_factory(request, leg, tspan, algorithm)
    passthrough = error ->
        error isa ODEResourceLimit || error isa ODESolverFailure ||
            error isa CoordinateInversionStalled
    leg_controls = (
        odealgo=AutoVern9(Rosenbrock23(autodiff=false)),
        reltol=parse_real(T, request, "homogeneous_ode_relative_tolerance"),
        abstol=parse_real(T, request, "homogeneous_ode_absolute_tolerance"),
        ode_maxiters=parse_integer(request, "homogeneous_ode_maxiters"),
        ode_observation_factory=observation_factory,
        ode_solution_observer=observe_ode_solution,
        ode_exception_passthrough=passthrough,
        factored_homogeneous_rhs_counter=factored_homogeneous_rhs_counter,
    )

    maximum_horizon_distance = parse_real(
        T, request, "horizon_maximum_endpoint_distance"
    )
    inner_contour = try
        build_worker_real_inner_horizon_contour(
            T, request, spectral, readout, "horizon-real-inner"
        )
    catch failure
        failure isa CoordinateInversionStalled || rethrow()
        throw(horizon_endpoint_recovery_failure(
            request,
            CF.COORDINATE_INVERSION_FAILURE,
            canonical_horizon_coordinate_failure_evidence(request),
        ))
    end
    rho_candidates = horizon_endpoint_rho_candidates(T, request)
    rho_floor = horizon_endpoint_rho_floor(T, request)
    endpoint_base_order = parse_integer(request, "endpoint_series_order")
    endpoint_orders = CF.horizon_endpoint_order_ladder(
        endpoint_base_order;
        maximum_order=horizon_endpoint_maximum_order(
            request, endpoint_base_order
        ),
    )
    # Materialise the complete deterministic depth schedule first. The package
    # recovery routine then exhausts this schedule at each order and caches the
    # order-independent geometry, so an invalid radius is never retried.
    while true
        deeper = CF.deepen_horizon_endpoint_rho_candidates(
            rho_candidates, rho_floor
        )
        deeper === nothing && break
        rho_candidates = deeper
    end
    geometry_candidates = CF.horizon_endpoint_geometry_candidates(
        spectral,
        inner_contour;
        rho_candidates=rho_candidates,
        maximum_horizon_distance=maximum_horizon_distance,
    )
    homogeneous_rhs_evaluations_before_pair =
        factored_homogeneous_rhs_counter[]
    homogeneous_rhs_evaluations_before_pair == 0 || error(
        "horizon endpoint recovery began after homogeneous RHS work"
    )
    endpoint_recovery = CF.recover_verified_horizon_endpoint_pair(
        spectral,
        inner_contour,
        geometry_candidates,
        required_digits;
        maximum_horizon_distance=maximum_horizon_distance,
        endpoint_orders=endpoint_orders,
        prefix_minimum_order=parse_integer(
            request, "horizon_endpoint_prefix_minimum_order"
        ),
        prefix_order_step=parse_integer(
            request, "horizon_endpoint_prefix_order_step"
        ),
        policy_identity=string(required(
            request, "horizon_endpoint_recovery_policy_identity"
        )),
    )
    candidates = endpoint_recovery.candidates
    progress_emit("horizon_endpoint_search_completed"; payload=Dict(
        "outcome" => endpoint_recovery.outcome,
        "policy_identity" => endpoint_recovery.policy_identity,
        "endpoint_order_ladder" => endpoint_orders,
        "candidate_count" => length(candidates),
        "homogeneous_rhs_evaluations_before_pair" =>
            homogeneous_rhs_evaluations_before_pair,
        "canonical_evidence" =>
            CF.canonical_horizon_endpoint_search_evidence(endpoint_recovery),
    ))
    for candidate in candidates
        emit_horizon_endpoint_candidate(candidate)
    end
    if length(endpoint_recovery.selected_pair) != 2
        throw(horizon_endpoint_recovery_failure(
            request,
            endpoint_recovery.outcome,
            CF.canonical_horizon_endpoint_search_evidence(endpoint_recovery),
        ))
    end
    endpoints = CF.verified_horizon_endpoints_from_recovery(
        endpoint_recovery, maximum_horizon_distance
    )
    push!(
        context.conditioning.horizon_endpoint_search_evidence,
        CF.canonical_horizon_endpoint_search_evidence(endpoint_recovery),
    )
    progress_emit("horizon_endpoints_verified"; payload=Dict(
        "reference_rho" => string(endpoints.reference.geometry.rho),
        "reference_horizon_distance" =>
            string(endpoints.reference.geometry.horizon_distance),
        "verification_rho" =>
            string(endpoints.verification.geometry.rho),
        "verification_horizon_distance" =>
            string(endpoints.verification.geometry.horizon_distance),
        "horizon_contour_id" => endpoints.contour_id,
        "candidate_count" => length(candidates),
    ))

    # No homogeneous ODE is permitted before the verified endpoint pair
    # exists. The outer coordinate map and infinity preparation begin only
    # after that gate, so invalid horizon geometry has zero homogeneous cost.
    outer_contour, outer_preparation = select_worker_outer_endpoint(
        T, request, spectral, readout, "Xup-outer", required_digits
    )
    emit_asymptotic_preparation(outer_preparation)
    CF.assert_factored_preflights_adequate(outer_preparation)
    xup_match = progress_operation("Xup") do
        CF.solve_factored_xup_to_match(
            spectral,
            outer_contour,
            outer_preparation;
            ode_leg="Xup_outer_to_match",
            leg_controls...,
        )
    end
    emit_factored_solution(xup_match)

    reference_basis = progress_operation("horizon-reference") do
        CF.solve_verified_horizon_basis_to_match(
            spectral,
            inner_contour,
            endpoints.reference,
            required_digits;
            ode_leg_prefix="horizon_reference",
            leg_controls...,
        )
    end
    emit_factored_solution(reference_basis.ingoing)
    emit_factored_solution(reference_basis.outgoing)
    verification_basis = progress_operation("horizon-verification") do
        CF.solve_verified_horizon_basis_to_match(
            spectral,
            inner_contour,
            endpoints.verification,
            required_digits;
            ode_leg_prefix="horizon_verification",
            leg_controls...,
        )
    end
    emit_factored_solution(verification_basis.ingoing)
    emit_factored_solution(verification_basis.outgoing)

    reference = evaluate_horizon_chart(
        T, request, spectral, amplitude, xup_match,
        outer_contour, inner_contour, reference_basis, "reference",
    )
    verification = evaluate_horizon_chart(
        T, request, spectral, amplitude, xup_match,
        outer_contour, inner_contour, verification_basis, "verification",
    )
    endpoint_disagreement_abs = abs(
        reference.value - verification.value
    )
    equivalence_disagreement_abs = maximum_optional_discrepancy(
        T,
        reference.assessment.equivalence_disagreement_abs,
        verification.assessment.equivalence_disagreement_abs,
    )
    error_breakdown = determinant_error_breakdown(
        T,
        request,
        endpoint_disagreement_abs;
        equivalence_disagreement_abs=equivalence_disagreement_abs,
    )
    progress_emit("determinant_error_estimated"; payload=Dict(
        "error_model_id" => VERIFIED_ENDPOINT_ERROR_MODEL_ID,
        "endpoint_disagreement_abs" => string(endpoint_disagreement_abs),
        "control_disagreement_abs" => nothing,
        "equivalence_disagreement_abs" =>
            equivalence_disagreement_abs === nothing ? nothing :
            string(equivalence_disagreement_abs),
        "precision_disagreement_abs" => nothing,
        "safety_factor" => string(error_breakdown.safety_factor),
        "numerical_error_abs" =>
            string(error_breakdown.numerical_error_abs),
        "determinant_abs" => string(abs(reference.value)),
        "reference_cref_fraction" => string(reference.cref_fraction),
        "verification_cref_fraction" => string(verification.cref_fraction),
    ))

    chart_assessment = reference.assessment
    coefficient_diagnostics = reference.coefficient_diagnostics
    endpoint_summary = endpoint_conditioning_summary(
        outer_preparation,
        reference_basis.ingoing_endpoint,
        reference_basis.outgoing_endpoint,
    )
    diagnostics = DeterminantDiagnostics{T}(
        HORIZON_HOMOGENEOUS_REPRESENTATION_ID,
        HORIZON_DETERMINANT_FAMILY_ID,
        true,
        endpoint_summary.maximum_series_digits_lost,
        endpoint_summary.maximum_recurrence_digits_lost,
        endpoint_summary.maximum_series_evaluation_spread,
        endpoint_summary.maximum_last_term_ratio,
        endpoint_summary.minimum_asymptotic_predicted_reliable_digits,
        max(
            coefficient_diagnostics.condition_frobenius,
            verification.coefficient_diagnostics.condition_frobenius,
        ),
        max(
            coefficient_diagnostics.backward_error,
            verification.coefficient_diagnostics.backward_error,
        ),
        max(
            coefficient_diagnostics.matching_reconstruction_residual,
            verification.coefficient_diagnostics.matching_reconstruction_residual,
        ),
        endpoint_summary.endpoint_remainders_regular,
        endpoint_summary.maximum_endpoint_reconstruction_error,
        chart_assessment.raw_determinant_abs,
        chart_assessment.raw_determinant_evidence_status,
        chart_assessment.normalised_determinant_abs,
        chart_assessment.cref_chart_margin,
        max(
            coefficient_diagnostics.carrier_change_error,
            verification.coefficient_diagnostics.carrier_change_error,
        ),
        spectral.contour_deformation.maximum_absolute,
    )
    record_determinant!(context.conditioning, diagnostics)
    progress_emit("determinant_chart_evaluated"; payload=Dict(
        "determinant_family" => HORIZON_DETERMINANT_FAMILY_ID,
        "determinant_convention" =>
            HORIZON_DETERMINANT_CONVENTION_ID,
        "determinant_normalisation" =>
            HORIZON_DETERMINANT_NORMALISATION_ID,
        "horizon_contour_id" => endpoints.contour_id,
        "normalised_determinant_abs" =>
            string(chart_assessment.normalised_determinant_abs),
        "numerical_error_abs" =>
            string(error_breakdown.numerical_error_abs),
        "error_model_id" => VERIFIED_ENDPOINT_ERROR_MODEL_ID,
    ))
    return DeterminantEvaluation{T}(
        reference.value,
        error_breakdown,
        VERIFIED_ENDPOINT_ERROR_MODEL_ID,
        diagnostics,
    )
end

function horizon_endpoint_rho_candidates(::Type{T}, request) where {T<:AbstractFloat}
    raw = required(request, "horizon_endpoint_rho_candidates")
    raw isa AbstractVector || error(
        "horizon_endpoint_rho_candidates must be a list"
    )
    isempty(raw) && error(
        "horizon_endpoint_rho_candidates must be nonempty"
    )
    return T[parse(T, string(value)) for value in raw]
end

# The declared floor on how deep the endpoint search may go, and the ceiling on
# how many series orders one radius may be tried at. Both are request
# overridable so a leaf can be given more room without recompiling the worker.
const HORIZON_ENDPOINT_RHO_FLOOR_DEFAULT = -400
const HORIZON_ENDPOINT_MAXIMUM_ORDER_FACTOR = 4

function horizon_endpoint_rho_floor(::Type{T}, request) where {T<:AbstractFloat}
    haskey(request, "horizon_endpoint_rho_floor") || return T(
        HORIZON_ENDPOINT_RHO_FLOOR_DEFAULT
    )
    return parse_real(T, request, "horizon_endpoint_rho_floor")
end

function horizon_endpoint_maximum_order(request, base_order::Integer)
    haskey(request, "horizon_endpoint_maximum_order") || return (
        HORIZON_ENDPOINT_MAXIMUM_ORDER_FACTOR * Int(base_order)
    )
    return parse_integer(request, "horizon_endpoint_maximum_order")
end

function emit_horizon_endpoint_candidate(candidate)
    geometry = candidate.geometry
    progress_emit("horizon_endpoint_candidate"; payload=Dict(
        "rho" => string(geometry.rho),
        "radius" => progress_complex(geometry.radius),
        "horizon_distance" => string(geometry.horizon_distance),
        "imaginary_radius_abs" => string(geometry.imaginary_radius_abs),
        "exterior" => geometry.exterior,
        "on_real_axis" => geometry.on_real_axis,
        "approaches_horizon" => geometry.approaches_horizon,
        "within_maximum_distance" => geometry.within_maximum_distance,
        "horizon_contour_id" => geometry.contour_id,
        "ingoing_adequate" => candidate.ingoing_adequate,
        "outgoing_adequate" => candidate.outgoing_adequate,
        "attempted_endpoint_order" => candidate.attempted_endpoint_order,
        "endpoint_order" => candidate.endpoint_order,
        "ingoing_best_prefix_order" =>
            candidate.ingoing_evaluation === nothing ? nothing :
            candidate.ingoing_evaluation.order,
        "outgoing_best_prefix_order" =>
            candidate.outgoing_evaluation === nothing ? nothing :
            candidate.outgoing_evaluation.order,
        "ingoing_predicted_reliable_digits" =>
            candidate.ingoing_assessment === nothing ? nothing :
            string(candidate.ingoing_assessment.predicted_reliable_digits),
        "outgoing_predicted_reliable_digits" =>
            candidate.outgoing_assessment === nothing ? nothing :
            string(candidate.outgoing_assessment.predicted_reliable_digits),
    ))
end

function evaluate_exterior_determinant(
    ::Type{T},
    request,
    context::DeterminantRequestContext{T},
    omega::Complex{T},
    amplitude::Complex{T},
) where {T<:AbstractFloat}
    readout = parse_real(T, request, "readout_radius")
    a = parse_real(T, request, "spin")
    survey_background = get(request, "operation", nothing) ==
        FIXED_ROOT_SURVEY_BATCH_OPERATION &&
        string(required(request, "readout_role")) in
            FIXED_ROOT_SURVEY_BACKGROUND_ROLES
    lower = if survey_background
        readout
    else
        exterior_support_contract(T, request, a, readout)[1]
    end
    spectral = build_sample_spectral_context(T, request, omega, context)
    lower_contour = build_worker_contour_context(
        T, request, spectral, lower, "Xin"
    )
    required_digits = required_reliable_digits(T, request)
    horizon_ingoing = CF.prepare_factored_horizon_ingoing(
        spectral, lower_contour, required_digits
    )
    exterior_certificate_required =
        exterior_empirical_certificate_required(request)
    readout_contour, infinity_outgoing, comparison_contour,
        comparison_outgoing = if get(request, "operation", nothing) ==
            FIXED_ROOT_SURVEY_BATCH_OPERATION
        contour, preparation = select_worker_outer_endpoint(
            T,
            request,
            spectral,
            readout,
            "Xup",
            required_digits,
        )
        contour, preparation, nothing, nothing
    elseif exterior_certificate_required
        select_worker_outer_endpoint_pair(
            T,
            request,
            spectral,
            readout,
            "Xup",
            required_digits,
        )
    else
        contour = build_worker_contour_context(
            T, request, spectral, readout, "Xup"
        )
        preparation = CF.prepare_factored_infinity_outgoing(
            spectral, contour, required_digits
        )
        contour, preparation, nothing, nothing
    end
    emit_asymptotic_preparation(horizon_ingoing)
    emit_asymptotic_preparation(infinity_outgoing)
    comparison_outgoing === nothing ||
        emit_asymptotic_preparation(comparison_outgoing)
    # Authenticate both distinct match-radius preparations before testing
    # either assessment. An inadequate branch exits before readiness,
    # observers, or any factored homogeneous RHS evaluation.
    CF.assert_factored_exterior_preparations_ready(
        spectral,
        lower_contour,
        horizon_ingoing,
        readout_contour,
        infinity_outgoing,
    )

    factored_homogeneous_rhs_counter = Ref(0)
    observation_factory = (leg, tspan, algorithm) ->
        ode_observation_factory(request, leg, tspan, algorithm)
    common_solve_options = (
        odealgo=AutoVern9(Rosenbrock23(autodiff=false)),
        reltol=parse_real(T, request, "ode_relative_tolerance"),
        abstol=parse_real(T, request, "ode_absolute_tolerance"),
        ode_maxiters=parse_integer(request, "homogeneous_ode_maxiters"),
        ode_observation_factory=observation_factory,
        ode_solution_observer=observe_ode_solution,
        ode_exception_passthrough=error ->
            error isa ODEResourceLimit || error isa ODESolverFailure,
        factored_homogeneous_rhs_counter=factored_homogeneous_rhs_counter,
    )
    xin_propagated = progress_operation("Xin") do
        CF.solve_factored_xin_to_match(
            spectral,
            lower_contour,
            horizon_ingoing;
            common_solve_options...,
        )
    end
    xup_propagated = progress_operation("Xup") do
        CF.solve_factored_xup_to_match(
            spectral,
            readout_contour,
            infinity_outgoing;
            common_solve_options...,
        )
    end
    comparison_xup_propagated = if comparison_contour === nothing
        nothing
    else
        progress_operation("Xup comparison endpoint") do
            CF.solve_factored_xup_to_match(
                spectral,
                comparison_contour,
                comparison_outgoing;
                common_solve_options...,
            )
        end
    end
    emit_factored_solution(xin_propagated)
    emit_factored_solution(xup_propagated)
    comparison_xup_propagated === nothing ||
        emit_factored_solution(comparison_xup_propagated)
    xin_match = CF.reconstruct_factored_match_state(
        xin_propagated, spectral, lower_contour
    )
    xup_match = CF.reconstruct_factored_match_state(
        xup_propagated, spectral, readout_contour
    )
    comparison_xup_match = comparison_xup_propagated === nothing ? nothing :
        CF.reconstruct_factored_match_state(
            comparison_xup_propagated, spectral, comparison_contour
        )
    xin_match.radial_derivative_convention ==
        CF.MATCH_RADIAL_DERIVATIVE_CONVENTION_ID ||
        error("package returned an unexpected Xin match derivative convention")
    xup_match.radial_derivative_convention ==
        CF.MATCH_RADIAL_DERIVATIVE_CONVENTION_ID ||
        error("package returned an unexpected Xup match derivative convention")
    comparison_xup_match === nothing ||
        comparison_xup_match.radial_derivative_convention ==
            CF.MATCH_RADIAL_DERIVATIVE_CONVENTION_ID ||
        error("package returned an unexpected comparison Xup match derivative convention")
    perturbed_in = if survey_background
        Complex{T}[xin_match.X, xin_match.dX_drstar]
    else
        progress_operation("perturbed integration"; payload=Dict(
            "branch" => "Xin",
        )) do
            integrate_real_branch(
                T,
                request,
                omega,
                spectral.lambda,
                lower,
                readout,
                Complex{T}[xin_match.X, xin_match.dX_drstar],
                amplitude;
                ode_leg="perturbed_Xin",
            )
        end
    end
    value = progress_operation("Wronskian") do
        wronskian(
            perturbed_in,
            Complex{T}[xup_match.X, xup_match.dX_drstar],
        )
    end
    comparison_value = comparison_xup_match === nothing ? nothing :
        progress_operation("Wronskian comparison endpoint") do
            wronskian(
                perturbed_in,
                Complex{T}[
                    comparison_xup_match.X,
                    comparison_xup_match.dX_drstar,
                ],
            )
        end
    endpoint_series_disagreement_abs = comparison_value === nothing ? nothing :
        abs(value - comparison_value)
    exterior_certificate_required && (
        endpoint_series_disagreement_abs === nothing ||
        !isfinite(endpoint_series_disagreement_abs)
    ) && throw(numerical_control_failure(
        request,
        EXTERIOR_EMPIRICAL_ERROR_MISSING_OUTCOME,
        "exterior endpoint-series disagreement is unavailable",
        Dict{String,Any}(
            "reason" => "ENDPOINT_SERIES_DISAGREEMENT_UNAVAILABLE",
        );
        stage="determinant-chart",
    ))
    endpoint_summary = endpoint_conditioning_summary(
        horizon_ingoing, infinity_outgoing
    )
    diagnostics = DeterminantDiagnostics{T}(
        HOMOGENEOUS_REPRESENTATION_ID,
        EXTERIOR_DETERMINANT_FAMILY_ID,
        false,
        endpoint_summary.maximum_series_digits_lost,
        endpoint_summary.maximum_recurrence_digits_lost,
        endpoint_summary.maximum_series_evaluation_spread,
        endpoint_summary.maximum_last_term_ratio,
        endpoint_summary.minimum_asymptotic_predicted_reliable_digits,
        nothing,
        nothing,
        nothing,
        endpoint_summary.endpoint_remainders_regular,
        endpoint_summary.maximum_endpoint_reconstruction_error,
        nothing,
        "not-applicable/v1",
        abs(value),
        nothing,
        nothing,
        spectral.contour_deformation.maximum_absolute,
    )
    record_determinant!(context.conditioning, diagnostics)
    progress_emit("determinant_chart_evaluated"; payload=Dict(
        "determinant_family" => EXTERIOR_DETERMINANT_FAMILY_ID,
        "determinant_convention" =>
            EXTERIOR_DETERMINANT_CONVENTION_ID,
        "determinant_normalisation" =>
            EXTERIOR_DETERMINANT_NORMALISATION_ID,
        "normalised_determinant_abs" => string(abs(value)),
    ))
    if exterior_certificate_required
        endpoint_series_disagreement_abs === nothing && error(
            "unreachable: exterior certificate endpoint disagreement is absent"
        )
        preliminary_breakdown = DeterminantErrorBreakdown{T}(
            endpoint_series_disagreement_abs,
            nothing,
            nothing,
            nothing,
            one(T),
            endpoint_series_disagreement_abs,
        )
        return DeterminantEvaluation{T}(
            value,
            preliminary_breakdown,
            EXTERIOR_EMPIRICAL_ERROR_MODEL_ID,
            diagnostics,
        )
    end
    return DeterminantEvaluation{T}(value, diagnostics)
end

function determinant(
    ::Type{T},
    request,
    context::DeterminantRequestContext{T},
    omega::Complex{T},
    amplitude::Complex{T},
) where {T<:AbstractFloat}
    mechanism = string(required(request, "mechanism_id"))
    mechanism in ALLOWED_MECHANISMS ||
        error("unsupported mechanism_id $(repr(mechanism))")
    try
        if mechanism == "horizon-admittance"
            return evaluate_horizon_determinant(
                T, request, context, omega, amplitude
            )
        end
        return evaluate_exterior_determinant(
            T, request, context, omega, amplitude
        )
    catch failure
        translated = translate_numerical_control_failure(request, failure)
        translated === failure && rethrow()
        throw(translated)
    end
end

function raw_determinant_progress(
    ::Type{T}, request, evaluation_context::DeterminantRequestContext{T},
    omega::Complex{T}, amplitude::Complex{T},
    purpose::String, current::Complex{T},
) where {T<:AbstractFloat}
    started = time_ns()
    DETERMINANT_INDEX_REQUEST[] += 1
    DETERMINANT_INDEX_PHASE[] += 1
    LAST_DETERMINANT_PURPOSE[] = purpose
    context = Dict{String,Any}(
        "determinant_purpose" => purpose,
        "determinant_index" => DETERMINANT_INDEX_REQUEST[],
        "determinant_index_phase" => DETERMINANT_INDEX_PHASE[],
        "current_omega" => progress_complex(current),
        "candidate_omega" => progress_complex(omega),
    )
    return progress_scope(context) do
        progress_emit("determinant_started"; context=context, payload=Dict(
            "purpose" => purpose,
            "omega" => progress_complex(omega),
        ))
        evaluation = determinant(
            T, request, evaluation_context, omega, amplitude
        )
        elapsed_seconds = (time_ns() - started) / 1.0e9
        LAST_DETERMINANT_SECONDS[] = elapsed_seconds
        progress_emit("determinant_completed"; context=context, payload=Dict(
            "purpose" => purpose,
            "omega" => progress_complex(omega),
            "determinant_real" => string(real(evaluation.value)),
            "determinant_imag" => string(imag(evaluation.value)),
            "determinant_abs" => string(abs(evaluation.value)),
            "determinant_family" =>
                evaluation.diagnostics.determinant_family,
            "elapsed_seconds" => elapsed_seconds,
        ))
        return evaluation
    end
end

function exterior_empirical_certificate_required(request)
    string(required(request, "mechanism_id")) == "horizon-admittance" &&
        return false
    model = string(required(
        request,
        haskey(request, "diagnostic_model_identity") ?
            "diagnostic_model_identity" : "determinant_error_model",
    ))
    model == EXTERIOR_ADDITIVE_CHANNEL_SCHEMA_ID && return false
    model == EXTERIOR_EMPIRICAL_ERROR_MODEL_ID && return true
    error("exterior determinant request carries an unsupported error model")
end

"""Route every promoted exterior determinant through its mandatory receipt."""
function determinant_progress(
    ::Type{T}, request, evaluation_context::DeterminantRequestContext{T},
    omega::Complex{T}, amplitude::Complex{T},
    purpose::String, current::Complex{T},
) where {T<:AbstractFloat}
    if exterior_empirical_certificate_required(request)
        started = time_ns()
        authenticated = authenticated_determinant_progress(
            T,
            request,
            evaluation_context,
            omega,
            amplitude,
            purpose,
            current,
        )
        # A resource-feasibility estimate must charge one full certificate,
        # not only its final preceding-tier raw evaluation.
        LAST_DETERMINANT_SECONDS[] = (time_ns() - started) / 1.0e9
        LAST_DETERMINANT_PURPOSE[] = purpose
        return authenticated
    end
    return raw_determinant_progress(
        T, request, evaluation_context, omega, amplitude, purpose, current
    )
end

function enforce_root_readout_feasibility(
    request,
    minimum_remaining_determinant_count::Int=8,
)
    minimum_remaining_determinant_count >= 0 ||
        throw(ArgumentError(
            "minimum remaining determinant count must be nonnegative"
        ))
    measured_seconds = LAST_DETERMINANT_SECONDS[]
    request_elapsed_seconds = (time_ns() - REQUEST_STARTED_NS[]) / 1.0e9
    remaining_wall_time_seconds = max(
        0.0,
        parse_integer(request, "cooperative_request_deadline_seconds") -
            request_elapsed_seconds,
    )
    estimated_mandatory_seconds =
        measured_seconds * minimum_remaining_determinant_count
    estimated_mandatory_seconds < remaining_wall_time_seconds && return
    estimator = "first-determinant-linear-lower-bound/v1"
    details = merge(control_failure_context(request), Dict{String,Any}(
        "failure_code" => "ROOT_READOUT_RESOURCE_INFEASIBLE",
        "failure_class" => "CONTROL",
        "limiting_resource" => "cooperative_request_deadline",
        "measured_determinant_seconds" => measured_seconds,
        "minimum_remaining_determinant_count" =>
            minimum_remaining_determinant_count,
        "remaining_wall_time_seconds" => remaining_wall_time_seconds,
        "estimated_mandatory_seconds" => estimated_mandatory_seconds,
        "estimator" => "first-determinant-linear-lower-bound/v1",
    ))
    progress_emit("root_readout_resource_infeasible"; payload=Dict{String,Any}(
        "failure_code" => "ROOT_READOUT_RESOURCE_INFEASIBLE",
        "failure_class" => "CONTROL",
        "limiting_resource" => "cooperative_request_deadline",
        "measured_determinant_seconds" => measured_seconds,
        "minimum_remaining_determinant_count" => minimum_remaining_determinant_count,
        "remaining_wall_time_seconds" => remaining_wall_time_seconds,
        "estimated_mandatory_seconds" => estimated_mandatory_seconds,
        "estimator" => estimator,
        "execution_resource_policy" => resource_policy_identity(request),
    ))
    throw(RootReadoutResourceLimit(
        "mandatory determinant work cannot fit before the cooperative deadline",
        details,
    ))
end

function validate_finite_difference_offset(
    offset::Complex{T}; axis::String
) where {T<:AbstractFloat}
    axis in ("real", "imaginary") ||
        throw(ArgumentError("finite-difference axis must be real or imaginary"))
    all(isfinite, (real(offset), imag(offset))) ||
        throw(ArgumentError("finite-difference offset must be finite"))
    axis == "real" && !iszero(imag(offset)) &&
        throw(ArgumentError("real finite-difference offset must be real"))
    axis == "imaginary" && !iszero(real(offset)) &&
        throw(ArgumentError("imaginary finite-difference offset must be imaginary"))
    h = axis == "real" ? abs(real(offset)) : abs(imag(offset))
    iszero(h) && throw(ArgumentError("finite-difference offset must be nonzero"))
    isfinite(h) || throw(ArgumentError("finite-difference step must be finite"))
    return h
end

const MAXIMUM_FREQUENCY_STEP_RUNGS = 64

function validated_frequency_steps(
    ::Type{T}, request
) where {T<:AbstractFloat}
    nominal_step = parse_real(T, request, "frequency_step")
    minimum_step = parse_real(T, request, "frequency_step_minimum")
    maximum_step = parse_real(T, request, "frequency_step_maximum")
    valid_values = all(
        value -> isfinite(value) && value > zero(T),
        (nominal_step, minimum_step, maximum_step),
    )
    valid_order = minimum_step <= nominal_step <= maximum_step
    # A range narrower than a factor of four cannot hold any rung whose h/2 and
    # 2h samples both stay inside it, so the ladder could never honour the
    # policy it was given. Reject that here rather than deep inside the search.
    valid_width = valid_values &&
        maximum_step >= T(4) * minimum_step
    valid_values && valid_order && valid_width &&
        return nominal_step, minimum_step, maximum_step
    throw(numerical_control_failure(
        request,
        "ALGEBRAIC_REPRESENTATION_SINGULAR",
        "finite-difference frequency steps must be finite, positive, ordered, " *
        "and at least a factor of four wide",
        Dict{String,Any}(
            "reason" => "INVALID_FREQUENCY_STEP",
            "range_status" => "invalid-frequency-step/v1",
            "operation" => "finite-difference-request-policy/v1",
            "axis" => "request-policy",
            "h" => string(nominal_step),
            "frequency_step" => string(nominal_step),
            "frequency_step_minimum" => string(minimum_step),
            "frequency_step_maximum" => string(maximum_step),
        );
        retryable=false,
        stage="request-policy",
    ))
end

"""
    validated_frequency_step(T, request)

Validate the nominal derivative step alone.

This is the historical contract and it deliberately does not require the
minimum/maximum pair to be four-fold wide. Only the authenticated rung search
samples `h/2` and `2h` around a rung and therefore needs that width; the Newton
loop and the unauthenticated derivative control use the nominal step directly,
and must not start failing on a policy that has always been usable for them.
"""
function validated_frequency_step(
    ::Type{T}, request
) where {T<:AbstractFloat}
    nominal_step = parse_real(T, request, "frequency_step")
    isfinite(nominal_step) && nominal_step > zero(T) &&
        return nominal_step
    throw(numerical_control_failure(
        request,
        "ALGEBRAIC_REPRESENTATION_SINGULAR",
        "finite-difference frequency step must be finite and positive",
        Dict{String,Any}(
            "reason" => "INVALID_FREQUENCY_STEP",
            "range_status" => "invalid-frequency-step/v1",
            "operation" => "finite-difference-request-policy/v1",
            "axis" => "request-policy",
            "h" => string(nominal_step),
            "frequency_step" => string(nominal_step),
        );
        retryable=false,
    ))
end

"""
    admissible_frequency_step_interval(minimum_step, maximum_step)

Return the interval of rungs whose every sample stays inside policy.

Each rung `h` evaluates the stencil at `h/2`, `h`, `2h` and `ih`, and the
accepted derivative is the `h/2` estimate -- so `h/2` is also the step the
authentication record reports. Bounding only `h` therefore leaves the finest
sample below `minimum_step` and the coarsest above `maximum_step`, which means
the configured range would not actually be the range that was evaluated.

Admissibility is consequently `2*minimum_step <= h <= maximum_step/2`, which is
non-empty only when `maximum_step >= 4*minimum_step`.
"""
function admissible_frequency_step_interval(
    minimum_step::T, maximum_step::T
) where {T<:AbstractFloat}
    return T(2) * minimum_step, maximum_step / T(2)
end

function frequency_step_rungs(
    nominal_step::T, minimum_step::T, maximum_step::T
) where {T<:AbstractFloat}
    minimum_step <= nominal_step <= maximum_step || throw(ArgumentError(
        "frequency step bounds do not enclose the nominal step"
    ))
    all(
        value -> isfinite(value) && value > zero(T),
        (nominal_step, minimum_step, maximum_step),
    ) || throw(ArgumentError(
        "frequency step rungs require finite positive bounds"
    ))
    finest, coarsest = admissible_frequency_step_interval(
        minimum_step, maximum_step
    )
    finest <= coarsest || throw(ArgumentError(
        "frequency step bounds are too narrow to sample h/2, h, and 2h " *
        "inside the configured range"
    ))
    # The nominal step is a preference for where to begin searching; the hard
    # contract is that no evaluated sample escapes policy. Anchoring inside the
    # admissible interval honours both.
    anchor = min(max(nominal_step, finest), coarsest)
    rungs = T[anchor]
    step = anchor
    for _ in 1:(MAXIMUM_FREQUENCY_STEP_RUNGS - 1)
        step >= coarsest && break
        candidate = min(coarsest, step * T(4))
        candidate == step && break
        push!(rungs, candidate)
        step = candidate
    end
    step = anchor
    for _ in 1:(MAXIMUM_FREQUENCY_STEP_RUNGS - length(rungs))
        step <= finest && break
        candidate = max(finest, step / T(4))
        candidate == step && break
        push!(rungs, candidate)
        step = candidate
    end
    unique!(rungs)
    # Assert the property the interval exists to guarantee: every sample the
    # ladder will actually evaluate, and the step it will actually report, lie
    # within the configured policy range.
    all(
        step -> minimum_step <= step / T(2) &&
            T(2) * step <= maximum_step,
        rungs,
    ) || error("frequency step rung samples escaped their bounds")
    length(rungs) <= MAXIMUM_FREQUENCY_STEP_RUNGS || error(
        "frequency step rung construction exceeded its bound"
    )
    return rungs
end

function validate_finite_difference_inputs(
    d_plus_value::Complex{T},
    d_minus_value::Complex{T},
    offset::Complex{T};
    axis::String,
) where {T<:AbstractFloat}
    all(isfinite, (
        real(d_plus_value),
        imag(d_plus_value),
        real(d_minus_value),
        imag(d_minus_value),
    )) || throw(FiniteDifferenceRangeError(
        "finite-difference stencil values must be finite",
        "nonfinite-stencil/v1",
    ))
    return validate_finite_difference_offset(offset; axis=axis)
end

struct _FDScaledValue{T<:AbstractFloat}
    fraction::T
    exponent::BigInt
end

function _fd_normalized_scaled(
    value::T, exponent::BigInt
) where {T<:AbstractFloat}
    iszero(value) && return _FDScaledValue{T}(zero(T), BigInt(0))
    isfinite(value) || error("finite-difference scaled value is nonfinite")
    fraction, adjustment = frexp(value)
    return _FDScaledValue{T}(
        fraction,
        exponent + BigInt(adjustment),
    )
end

function _fd_scaled_value(value::T) where {T<:AbstractFloat}
    return _fd_normalized_scaled(value, BigInt(0))
end

function _fd_component_difference(
    left::T, right::T
) where {T<:AbstractFloat}
    difference = left - right
    if isfinite(difference)
        return _fd_scaled_value(difference)
    end
    # An overflow here can only arise from subtracting finite, oppositely
    # signed values.  Halving both operands is exact in binary arithmetic for
    # this large-value case and retains the one missing power of two explicitly.
    half_difference = left / T(2) - right / T(2)
    isfinite(half_difference) ||
        error("finite-difference component difference cannot be represented")
    return _fd_normalized_scaled(half_difference, BigInt(1))
end

function _fd_scale_fraction_down(
    value::_FDScaledValue{T}, common_exponent::BigInt
) where {T<:AbstractFloat}
    iszero(value.fraction) && return zero(T)
    shift = value.exponent - common_exponent
    shift > 0 && error("finite-difference scaling direction is invalid")
    # Terms this far below the common exponent cannot affect a rounded T norm
    # or positive sum.  Avoid passing an extreme BigFloat exponent through Int.
    shift < -BigInt(precision(T) + 4) && return zero(T)
    return ldexp(value.fraction, Int(shift))
end


function _fd_scaled_norm(
    real_value::_FDScaledValue{T},
    imaginary_value::_FDScaledValue{T},
) where {T<:AbstractFloat}
    iszero(real_value.fraction) && iszero(imaginary_value.fraction) &&
        return _FDScaledValue{T}(zero(T), BigInt(0))
    common_exponent = if iszero(real_value.fraction)
        imaginary_value.exponent
    elseif iszero(imaginary_value.fraction)
        real_value.exponent
    else
        max(real_value.exponent, imaginary_value.exponent)
    end
    scaled_real = _fd_scale_fraction_down(real_value, common_exponent)
    scaled_imaginary = _fd_scale_fraction_down(
        imaginary_value, common_exponent
    )
    return _fd_normalized_scaled(
        hypot(scaled_real, scaled_imaginary),
        common_exponent,
    )
end

function _fd_scaled_norm(value::Complex{T}) where {T<:AbstractFloat}
    return _fd_scaled_norm(
        _fd_scaled_value(real(value)),
        _fd_scaled_value(imag(value)),
    )
end

function _fd_scaled_sum(
    left::_FDScaledValue{T}, right::_FDScaledValue{T}
) where {T<:AbstractFloat}
    iszero(left.fraction) && return right
    iszero(right.fraction) && return left
    common_exponent = max(left.exponent, right.exponent)
    return _fd_normalized_scaled(
        _fd_scale_fraction_down(left, common_exponent) +
            _fd_scale_fraction_down(right, common_exponent),
        common_exponent,
    )
end

function _fd_scaled_ratio(
    numerator::_FDScaledValue{T}, denominator::_FDScaledValue{T}
) where {T<:AbstractFloat}
    iszero(denominator.fraction) &&
        throw(ArgumentError("finite-difference scaled denominator is zero"))
    return _fd_normalized_scaled(
        numerator.fraction / denominator.fraction,
        numerator.exponent - denominator.exponent,
    )
end

function _fd_materialize_clamped(
    value::_FDScaledValue{T}
) where {T<:AbstractFloat}
    iszero(value.fraction) && return zero(T), false, false
    maximum_fraction, maximum_exponent = frexp(floatmax(T))
    magnitude_fraction = abs(value.fraction)
    maximum_exponent_big = BigInt(maximum_exponent)
    if value.exponent > maximum_exponent_big ||
            (value.exponent == maximum_exponent_big &&
             magnitude_fraction > maximum_fraction)
        clamped = signbit(value.fraction) ? -floatmax(T) : floatmax(T)
        return clamped, true, false
    end
    value.exponent < BigInt(typemin(Int)) && return zero(T), false, true
    materialized = ldexp(value.fraction, Int(value.exponent))
    isfinite(materialized) ||
        error("finite-difference scaled materialization is nonfinite")
    underflowed = iszero(materialized) && !iszero(value.fraction)
    return materialized, false, underflowed
end

function _fd_materialize_derivative(
    value::_FDScaledValue{T}
) where {T<:AbstractFloat}
    materialized, saturated, underflowed = _fd_materialize_clamped(value)
    saturated && throw(FiniteDifferenceRangeError(
        "finite-difference derivative exceeds the arithmetic range",
        "derivative-overflow/v1",
    ))
    underflowed && throw(FiniteDifferenceRangeError(
        "finite-difference derivative underflows the arithmetic range",
        "derivative-underflow/v1",
    ))
    return materialized
end

function _fd_derivative_component(
    difference::_FDScaledValue{T},
    orientation::T,
    h::_FDScaledValue{T},
) where {T<:AbstractFloat}
    iszero(difference.fraction) && return zero(T)
    scaled = _fd_normalized_scaled(
        difference.fraction * orientation / (T(2) * h.fraction),
        difference.exponent - h.exponent,
    )
    return _fd_materialize_derivative(scaled)
end

function build_finite_difference_diagnostics(
    d_plus_value::Complex{T},
    d_minus_value::Complex{T},
    offset::Complex{T};
    axis::String,
) where {T<:AbstractFloat}
    h = validate_finite_difference_inputs(
        d_plus_value, d_minus_value, offset; axis=axis
    )

    plus_norm = _fd_scaled_norm(d_plus_value)
    minus_norm = _fd_scaled_norm(d_minus_value)
    real_difference = _fd_component_difference(
        real(d_plus_value), real(d_minus_value)
    )
    imaginary_difference = _fd_component_difference(
        imag(d_plus_value), imag(d_minus_value)
    )
    difference_norm = _fd_scaled_norm(
        real_difference, imaginary_difference
    )
    numerator_norm = _fd_scaled_sum(plus_norm, minus_norm)

    d_plus_abs, d_plus_abs_saturated, d_plus_abs_underflowed =
        _fd_materialize_clamped(plus_norm)
    d_minus_abs, d_minus_abs_saturated, d_minus_abs_underflowed =
        _fd_materialize_clamped(minus_norm)
    difference_abs, difference_abs_saturated, difference_abs_underflowed =
        _fd_materialize_clamped(difference_norm)

    kappa_is_infinite = iszero(difference_norm.fraction) &&
        !iszero(numerator_norm.fraction)
    kappa_is_indeterminate = iszero(difference_norm.fraction) &&
        iszero(numerator_norm.fraction)
    kappa, kappa_saturated, kappa_underflowed = if (
        kappa_is_infinite || kappa_is_indeterminate
    )
        floatmax(T), true, false
    else
        value, saturated, underflowed = _fd_materialize_clamped(
            _fd_scaled_ratio(numerator_norm, difference_norm)
        )
        max(one(T), value), saturated, underflowed
    end
    kappa_underflowed && error(
        "finite-difference cancellation ratio underflowed below its unit lower bound"
    )
    finite_difference_digits_lost = log10(kappa)

    offset_sign = axis == "real" ? sign(real(offset)) : sign(imag(offset))
    derivative_real_difference = axis == "real" ?
        real_difference : imaginary_difference
    derivative_imaginary_difference = axis == "real" ?
        imaginary_difference : real_difference
    derivative_real_orientation = offset_sign
    derivative_imaginary_orientation = axis == "real" ?
        offset_sign : -offset_sign
    h_scaled = _fd_scaled_value(h)
    derivative = complex(
        _fd_derivative_component(
            derivative_real_difference,
            derivative_real_orientation,
            h_scaled,
        ),
        _fd_derivative_component(
            derivative_imaginary_difference,
            derivative_imaginary_orientation,
            h_scaled,
        ),
    )
    all(isfinite, (real(derivative), imag(derivative))) ||
        error("finite-difference derivative is nonfinite")
    derivative_abs, derivative_abs_saturated, derivative_abs_underflowed =
        _fd_materialize_clamped(
            _fd_scaled_norm(derivative)
        )

    underflow_observed = any((
        d_plus_abs_underflowed,
        d_minus_abs_underflowed,
        difference_abs_underflowed,
        kappa_underflowed,
        derivative_abs_underflowed,
    ))
    saturation_observed = any((
        d_plus_abs_saturated,
        d_minus_abs_saturated,
        difference_abs_saturated,
        kappa_saturated,
        derivative_abs_saturated,
    )) || underflow_observed
    saturation_status = if kappa_is_infinite
        "kappa-infinite-lower-bound/v1"
    elseif kappa_is_indeterminate
        "kappa-indeterminate-lower-bound/v1"
    elseif kappa_saturated
        "kappa-clamped-lower-bound/v1"
    elseif underflow_observed
        "magnitude-underflowed/v1"
    elseif saturation_observed
        "magnitude-clamped/v1"
    else
        "none/v1"
    end
    diagnostics = FiniteDifferenceDiagnostics{T}(
        d_plus_abs,
        d_minus_abs,
        difference_abs,
        kappa,
        finite_difference_digits_lost,
        derivative_abs,
        h,
        axis,
        d_plus_abs_saturated,
        d_plus_abs_underflowed,
        d_minus_abs_saturated,
        d_minus_abs_underflowed,
        difference_abs_saturated,
        difference_abs_underflowed,
        kappa_saturated,
        kappa_underflowed,
        kappa_is_infinite,
        kappa_is_indeterminate,
        derivative_abs_saturated,
        derivative_abs_underflowed,
        underflow_observed,
        saturation_observed,
        saturation_status,
    )
    all(isfinite, (
        diagnostics.d_plus_abs,
        diagnostics.d_minus_abs,
        diagnostics.difference_abs,
        diagnostics.kappa,
        diagnostics.finite_difference_digits_lost,
        diagnostics.derivative_abs,
        diagnostics.h,
    )) || error("finite-difference conditioning evidence is nonfinite")
    return derivative, diagnostics
end

function propagated_centered_difference_error(
    eta_plus::T, eta_minus::T, h::T
) where {T<:AbstractFloat}
    all(value -> isfinite(value) && value >= zero(T), (eta_plus, eta_minus)) ||
        throw(ArgumentError(
            "finite-difference determinant errors must be finite and nonnegative"
        ))
    isfinite(h) && !iszero(h) || throw(ArgumentError(
        "finite-difference error propagation requires a finite nonzero step"
    ))
    propagated = (eta_plus + eta_minus) / (T(2) * abs(h))
    isfinite(propagated) || throw(ArgumentError(
        "propagated finite-difference error is nonfinite"
    ))
    return propagated
end

function finite_difference_pair(
    ::Type{T},
    request,
    evaluation_context::DeterminantRequestContext{T},
    omega::Complex{T},
    amplitude::Complex{T},
    offset::Complex{T},
    label::String,
    current::Complex{T};
    axis::String,
    authenticate_controls::Bool=false,
    determinant_evaluator=nothing,
) where {T<:AbstractFloat}
    # Reject malformed stencils before either expensive determinant/ODE sample.
    h = validate_finite_difference_offset(offset; axis=axis)
    # `determinant_evaluator` exists so specifications and production policies
    # can select the exact determinant work performed by this stencil. The
    # promoted binary64-parity path passes the plain evaluator explicitly;
    # historical callers use the authenticated/plain selection below.
    evaluator = determinant_evaluator !== nothing ? determinant_evaluator :
        (authenticate_controls ?
            authenticated_determinant_progress : determinant_progress)
    d_plus = evaluator(
        T, request, evaluation_context, omega + offset, amplitude,
        "$(label) +", current,
    )
    d_minus = evaluator(
        T, request, evaluation_context, omega - offset, amplitude,
        "$(label) -", current,
    )
    derivative, diagnostics = try
        build_finite_difference_diagnostics(
            d_plus.value,
            d_minus.value,
            offset;
            axis=axis,
        )
    catch failure
        failure isa FiniteDifferenceRangeError || rethrow()
        translated = translate_numerical_control_failure(
            request,
            failure;
            finite_difference_axis=axis,
            finite_difference_h=h,
        )
        translated === failure && rethrow()
        throw(translated)
    end
    # Propagate the endpoint determinant errors through the centred stencil:
    #     eta_D' = (eta_D(w+h) + eta_D(w-h)) / (2|h|)
    # This is the term that says how much of the derivative magnitude is
    # attributable to determinant noise rather than to real slope.
    derivative_error_abs = authenticate_controls ?
        propagated_centered_difference_error(
            determinant_error_abs(T, d_plus),
            determinant_error_abs(T, d_minus),
            h,
        ) : zero(T)
    record_finite_difference!(evaluation_context.conditioning, diagnostics)
    progress_emit("conditioning_evaluated"; payload=Dict(
        "estimate_kind" => "finite-difference-cancellation/not-a-bound/v1",
        "axis" => diagnostics.axis,
        "h" => string(diagnostics.h),
        "d_plus_abs" => string(diagnostics.d_plus_abs),
        "d_minus_abs" => string(diagnostics.d_minus_abs),
        "difference_abs" => string(diagnostics.difference_abs),
        "kappa_fd" => string(diagnostics.kappa),
        "finite_difference_digits_lost" =>
            string(diagnostics.finite_difference_digits_lost),
        "derivative_abs" => string(diagnostics.derivative_abs),
        "d_plus_abs_saturated" => diagnostics.d_plus_abs_saturated,
        "d_plus_abs_underflowed" => diagnostics.d_plus_abs_underflowed,
        "d_minus_abs_saturated" => diagnostics.d_minus_abs_saturated,
        "d_minus_abs_underflowed" => diagnostics.d_minus_abs_underflowed,
        "difference_abs_saturated" => diagnostics.difference_abs_saturated,
        "difference_abs_underflowed" =>
            diagnostics.difference_abs_underflowed,
        "kappa_saturated" => diagnostics.kappa_saturated,
        "kappa_underflowed" => diagnostics.kappa_underflowed,
        "kappa_is_infinite" => diagnostics.kappa_is_infinite,
        "kappa_is_indeterminate" => diagnostics.kappa_is_indeterminate,
        "derivative_abs_saturated" => diagnostics.derivative_abs_saturated,
        "derivative_abs_underflowed" =>
            diagnostics.derivative_abs_underflowed,
        "underflow_observed" => diagnostics.underflow_observed,
        "saturation_observed" => diagnostics.saturation_observed,
        "saturation_status" => diagnostics.saturation_status,
        "derivative_error_abs" => string(derivative_error_abs),
    ))
    return derivative, diagnostics, derivative_error_abs
end

"""
    determinant_error_abs(T, evaluation)

Return the absolute numerical error carried by a determinant evaluation.

Families that do not yet publish an error model return zero, which reduces the
acceptance test below to its historical form. The horizon family always
publishes one.
"""
function determinant_error_abs(::Type{T}, evaluation) where {T<:AbstractFloat}
    breakdown = evaluation.error_breakdown
    breakdown === nothing && return zero(T)
    error_abs = breakdown.numerical_error_abs
    isfinite(error_abs) && error_abs >= zero(T) ||
        error("determinant numerical error must be finite and nonnegative")
    return T(error_abs)
end

"""
    determinant_upper_bound_abs(T, evaluation)

Return `|D| + eta_D`, the quantity historical authenticated Newton acceptance
and damping compare. The promoted binary64-parity path deliberately compares
raw `|D|` and retains this upper bound only as telemetry.

Using `|D|` alone treats a determinant that is small only because its own noise
happens to cancel as though the root were located. Near a QNM the determinant is
small by construction, so the magnitude on its own carries no information about
whether the frequency is resolved -- only the magnitude measured against its own
error does.
"""
function determinant_upper_bound_abs(
    ::Type{T}, evaluation
) where {T<:AbstractFloat}
    return abs(evaluation.value) + determinant_error_abs(T, evaluation)
end

function determinant_is_better(
    ::Type{T}, candidate, incumbent
) where {T<:AbstractFloat}
    return determinant_upper_bound_abs(T, candidate) <
        determinant_upper_bound_abs(T, incumbent)
end

function tight_control_request(
    ::Type{T}, request
) where {T<:AbstractFloat}
    get(request, "tight_control_request_depth", 0) == 0 || error(
        "tight-control determinant evaluation must not recursively tighten"
    )
    output = copy(request)
    for key in (
        "ode_relative_tolerance",
        "ode_absolute_tolerance",
        "homogeneous_ode_relative_tolerance",
        "homogeneous_ode_absolute_tolerance",
        "coordinate_ode_relative_tolerance",
        "coordinate_ode_absolute_tolerance",
    )
        haskey(request, key) || continue
        output[key] = numeric_text(parse_real(T, request, key) / T(2))
    end
    haskey(request, "support_subinterval_count") &&
        (output["support_subinterval_count"] =
            2 * parse_integer(request, "support_subinterval_count"))
    haskey(request, "angular_pad") &&
        (output["angular_pad"] = parse_integer(request, "angular_pad") + 8)
    output["tight_control_request_depth"] = 1
    return output
end

"""
    working_precision_bits_for(digits)

Return the BigFloat mantissa width the precision policy assigns to `digits`.

One definition, used both by request validation and by the precision guard, so
the guard cannot drift into a mantissa width the policy would reject.
"""
working_precision_bits_for(digits::Integer) =
    ceil(Int, digits * log2(10)) + 32

const PRECISION_GUARD_DIGITS = 80

"""
    precision_guard_request(T, request)

Return the request restated at the lower stored-precision rung with every
numerical control left exactly as it is.

`tight_control_request` answers "is the determinant limited by its ODE and
series controls". It cannot answer "is the determinant limited by the width of
the arithmetic carrying it", because tightening the controls at a fixed
mantissa moves both at once. Reducing the mantissa while holding the controls
fixed separates the two: whatever changes is attributable to precision alone.

Only the stored-precision fields move. If this also relaxed the tolerances it
would re-measure the control disagreement under a second name, and the maximum
that feeds the error budget would double-count one effect while still missing
the other.
"""
function precision_guard_request(::Type{T}, request) where {T<:AbstractFloat}
    get(request, "precision_guard_request_depth", 0) == 0 || error(
        "precision-guard determinant evaluation must not recursively reduce"
    )
    output = copy(request)
    output["precision_digits"] = PRECISION_GUARD_DIGITS
    output["working_precision_bits"] =
        working_precision_bits_for(PRECISION_GUARD_DIGITS)
    output["precision_guard_request_depth"] = 1
    return output
end

"""
    run_at_working_precision(body, T, bits)

Run `body` with `T`'s working precision set to `bits`.

`BigFloat` carries its precision globally, so the guard evaluation has to be
scoped rather than requested. Fixed-width element types have no dial to turn,
so they run the body unchanged -- which is what the finite-difference specs
exercise.
"""
run_at_working_precision(body, ::Type{BigFloat}, bits::Integer) =
    setprecision(BigFloat, bits) do
        body()
    end

run_at_working_precision(body, ::Type{<:AbstractFloat}, ::Integer) = body()

precision_context_value(::Type{T}, value) where {T<:AbstractFloat} = T(value)
precision_context_value(::Type{BigFloat}, value) = BigFloat(
    value, precision=precision(BigFloat)
)

"""
    precision_guard_context(T, evaluation_context)

Return the reported evaluation context restated at the ambient working
precision, and prove it still names the same branch.

The frozen convention is not a label: `infinity_contour_angle` and its
companions enter the contour geometry numerically, and they are derived from
the frequency the request opened with -- which is not the frequency being
authenticated. Recomputing the convention from the authenticated frequency
would tilt the contour, so the guard would be measuring a contour deformation
and reporting it as a precision effect. Rounding the existing convention keeps
the geometry and moves only the mantissa, which is the one variable the guard
is allowed to change.

`GSNBranchCell` holds only identity strings and half-plane signs, so a correct
rounding leaves it identical. If it does not, the reduced mantissa moved a
half-plane sign across its boundary and the two evaluations are no longer the
same determinant -- an error, not a disagreement to average in.

The guard gets a fresh conditioning accumulator. The reported conditioning
envelope describes the solve whose value is reported; folding a measurement
instrument's own conditioning into it would widen the envelope around a number
that was never returned.

Must be called inside the guard precision scope: `T(...)` reads the ambient
precision, which is the entire point.
"""
function precision_guard_context(
    ::Type{T}, evaluation_context::DeterminantRequestContext{S}
) where {T<:AbstractFloat,S<:AbstractFloat}
    frozen = evaluation_context.frozen_convention
    guard_convention = GSNBranchConvention{T}(
        precision_context_value(T, frozen.infinity_contour_angle),
        precision_context_value(T, frozen.horizon_contour_angle),
        frozen.infinity_sign,
        frozen.horizon_sign,
        precision_context_value(T, frozen.omega_argument),
        precision_context_value(T, frozen.p_horizon_argument),
        frozen.tortoise_branch_id,
        frozen.infinity_carrier_id,
        frozen.horizon_ingoing_carrier_id,
        frozen.horizon_outgoing_carrier_id,
    )
    guard_cell = GSN.branch_cell(guard_convention)
    guard_cell == evaluation_context.frozen_branch_cell || error(
        "precision guard moved the frozen branch cell"
    )
    return DeterminantRequestContext{T}(
        guard_convention,
        guard_cell,
        ConditioningAccumulator(T),
        AuthenticatedDeterminantEvidenceStore(),
    )
end

"""
    round_to_working_precision(T, value)

Return `value` carried at the ambient working precision.

The package refuses spectral inputs whose mantissa width disagrees with the
declared precision, and it is right to: silently mixing widths is how a
"120-digit" result ends up resting on an 80-digit intermediate. The guard
therefore has to state the reduction explicitly. Rounding the frequency is not
a distortion of the comparison -- at 80 digits the frequency genuinely is not
known past 80 digits, and the determinant's sensitivity to that is part of what
the guard is measuring.
"""
round_to_working_precision(::Type{T}, value::Complex) where {T<:AbstractFloat} =
    Complex{T}(T(real(value)), T(imag(value)))

"""Return the immediately preceding authenticated arithmetic tier."""
function exterior_preceding_precision_policy(request)
    digits = parse_integer(request, "precision_digits")
    expected = Dict(
        40 => "binary64",
        80 => "bigfloat-40",
        120 => "bigfloat-80",
    )
    haskey(expected, digits) || error(
        "exterior empirical certificate has no preceding precision tier"
    )
    string(required(request, "determinant_error_preceding_precision_tier")) ==
        expected[digits] || error(
        "exterior empirical certificate preceding tier disagrees with request"
    )
    preceding_digits = Dict(40 => 64, 80 => 40, 120 => 80)[digits]
    preceding_type = digits == 40 ? Float64 : BigFloat
    preceding_bits = Dict(
        40 => 53,
        80 => working_precision_bits_for(40),
        120 => working_precision_bits_for(80),
    )[digits]
    return (
        tier=expected[digits],
        digits=preceding_digits,
        dtype=preceding_type,
        bits=preceding_bits,
    )
end

"""
    precision_guard_disagreement(T, request, ...)

Return `|D_full - D_guard|` at one frequency, or `nothing` when the request is
already at the lowest stored-precision rung.

At 80 digits there is no lower rung the policy defines, so there is nothing to
compare against and the term is absent rather than zero -- absent says "not
measured", zero would claim "measured and identical".
"""
function precision_guard_disagreement(
    ::Type{T},
    request,
    evaluation_context::DeterminantRequestContext{T},
    omega::Complex{T},
    amplitude::Complex{T},
    purpose::String,
    current::Complex{T},
    base,
) where {T<:AbstractFloat}
    parse_integer(request, "precision_digits") > PRECISION_GUARD_DIGITS ||
        return nothing
    guard_request = precision_guard_request(T, request)
    guard_bits = parse_integer(guard_request, "working_precision_bits")
    guard = run_at_working_precision(T, guard_bits) do
        determinant_progress(
            T,
            guard_request,
            precision_guard_context(T, evaluation_context),
            round_to_working_precision(T, omega),
            round_to_working_precision(T, amplitude),
            "$(purpose) precision guard",
            current,
        )
    end
    guard.diagnostics.determinant_family ==
        base.diagnostics.determinant_family || error(
        "precision-guard determinant changed the determinant family"
    )
    disagreement = abs(base.value - guard.value)
    isfinite(disagreement) || throw(numerical_control_failure(
        request,
        "ALGEBRAIC_REPRESENTATION_SINGULAR",
        "cross-precision determinant disagreement is nonfinite",
        Dict{String,Any}(
            "guard_precision_digits" => PRECISION_GUARD_DIGITS,
            "guard_working_precision_bits" => guard_bits,
            "determinant_abs" => string(abs(base.value)),
            "guard_determinant_abs" => string(abs(guard.value)),
        );
        stage="determinant-chart",
    ))
    return T(disagreement)
end

function exterior_cross_precision_disagreement(
    ::Type{T},
    request,
    evaluation_context::DeterminantRequestContext{T},
    omega::Complex{T},
    amplitude::Complex{T},
    purpose::String,
    current::Complex{T},
    base,
) where {T<:AbstractFloat}
    preceding = exterior_preceding_precision_policy(request)
    cross_request = copy(request)
    cross_request["precision_digits"] = preceding.digits
    cross_request["working_precision_bits"] = preceding.bits
    cross_request["semantic_precision_tier"] = preceding.tier
    cross_request["exterior_cross_precision_request_depth"] =
        get(request, "exterior_cross_precision_request_depth", 0) + 1
    cross = try
        if preceding.dtype === Float64
            raw_determinant_progress(
                Float64,
                cross_request,
                precision_guard_context(Float64, evaluation_context),
                round_to_working_precision(Float64, omega),
                round_to_working_precision(Float64, amplitude),
                "$(purpose) exterior cross precision",
                round_to_working_precision(Float64, current),
            )
        else
            run_at_working_precision(BigFloat, preceding.bits) do
                raw_determinant_progress(
                    BigFloat,
                    cross_request,
                    precision_guard_context(BigFloat, evaluation_context),
                    round_to_working_precision(BigFloat, omega),
                    round_to_working_precision(BigFloat, amplitude),
                    "$(purpose) exterior cross precision",
                    round_to_working_precision(BigFloat, current),
                )
            end
        end
    catch failure
        failure isa InterruptException && rethrow()
        throw(numerical_control_failure(
            request,
            EXTERIOR_EMPIRICAL_ERROR_MISSING_OUTCOME,
            "exterior cross-precision determinant comparison is unavailable",
            Dict{String,Any}(
                "reason" => "CROSS_PRECISION_DISAGREEMENT_UNAVAILABLE",
                "preceding_precision_tier" => preceding.tier,
                "cause_type" => string(typeof(failure)),
            );
            stage="determinant-chart",
        ))
    end
    cross.diagnostics.determinant_family ==
        base.diagnostics.determinant_family || throw(
        numerical_control_failure(
            request,
            EXTERIOR_EMPIRICAL_ERROR_MISSING_OUTCOME,
            "exterior cross-precision comparison changed determinant family",
            Dict{String,Any}(
                "reason" => "CROSS_PRECISION_FAMILY_MISMATCH",
                "preceding_precision_tier" => preceding.tier,
            );
            stage="determinant-chart",
        )
    )
    cross_value = Complex{T}(T(real(cross.value)), T(imag(cross.value)))
    disagreement = abs(base.value - cross_value)
    isfinite(disagreement) || throw(numerical_control_failure(
        request,
        EXTERIOR_EMPIRICAL_ERROR_MISSING_OUTCOME,
        "exterior cross-precision determinant disagreement is nonfinite",
        Dict{String,Any}(
            "reason" => "CROSS_PRECISION_DISAGREEMENT_NONFINITE",
            "preceding_precision_tier" => preceding.tier,
        );
        stage="determinant-chart",
    ))
    return T(disagreement)
end

function authenticated_determinant_progress(
    ::Type{T},
    request,
    evaluation_context::DeterminantRequestContext{T},
    omega::Complex{T},
    amplitude::Complex{T},
    purpose::String,
    current::Complex{T};
    base_evaluation=nothing,
) where {T<:AbstractFloat}
    base_frequency = omega
    tight_frequency = omega
    exterior_certificate_unavailable =
        "EXTERIOR_DETERMINANT_CERTIFICATE_UNAVAILABLE"
    base_frequency == tight_frequency || error(
        "tight-control determinant comparison changed frequency"
    )
    base = base_evaluation === nothing ? raw_determinant_progress(
        T,
        request,
        evaluation_context,
        base_frequency,
        amplitude,
        "$(purpose) base controls",
        current,
    ) : base_evaluation
    exterior_certificate_required =
        exterior_empirical_certificate_required(request)
    if base.error_breakdown === nothing
        exterior_certificate_required && throw(numerical_control_failure(
            request,
            exterior_certificate_unavailable,
            "base exterior determinant omitted endpoint-series evidence",
            Dict{String,Any}(
                "reason" => "BASE_ENDPOINT_SERIES_EVIDENCE_UNAVAILABLE",
            );
            stage="determinant-chart",
        ))
        return base
    end
    tight_request = tight_control_request(T, request)
    tight = try
        raw_determinant_progress(
            T,
            tight_request,
            evaluation_context,
            tight_frequency,
            amplitude,
            "$(purpose) tight controls",
            current,
        )
    catch failure
        failure isa InterruptException && rethrow()
        exterior_certificate_required || rethrow()
        throw(numerical_control_failure(
            request,
            exterior_certificate_unavailable,
            "tight-control exterior determinant comparison is unavailable",
            Dict{String,Any}(
                "reason" => "SAME_POINT_DISAGREEMENT_UNAVAILABLE",
                "cause_type" => string(typeof(failure)),
            );
            stage="determinant-chart",
        ))
    end
    if tight.error_breakdown === nothing
        exterior_certificate_required && throw(numerical_control_failure(
            request,
            exterior_certificate_unavailable,
            "tight exterior determinant omitted endpoint-series evidence",
            Dict{String,Any}(
                "reason" => "TIGHT_ENDPOINT_SERIES_EVIDENCE_UNAVAILABLE",
            );
            stage="determinant-chart",
        ))
        error("tight horizon determinant omitted its error breakdown")
    end
    if exterior_certificate_required
        delta_same_point = abs(base.value - tight.value)
        delta_endpoint_series = max(
            base.error_breakdown.endpoint_disagreement_abs,
            tight.error_breakdown.endpoint_disagreement_abs,
        )
        delta_cross_precision = exterior_cross_precision_disagreement(
            T,
            request,
            evaluation_context,
            base_frequency,
            amplitude,
            purpose,
            current,
            base,
        )
        all(isfinite, (
            delta_same_point,
            delta_cross_precision,
            delta_endpoint_series,
        )) || throw(numerical_control_failure(
            request,
            exterior_certificate_unavailable,
            "exterior empirical determinant certificate has a nonfinite term",
            Dict{String,Any}(
                "reason" => "EXTERIOR_CERTIFICATE_TERM_NONFINITE",
            );
            stage="determinant-chart",
        ))
        error_breakdown = determinant_error_breakdown(
            T,
            request,
            delta_endpoint_series;
            control_disagreement_abs=delta_same_point,
            precision_disagreement_abs=delta_cross_precision,
        )
        progress_emit("determinant_error_estimated"; payload=Dict(
            "error_model_id" => EXTERIOR_EMPIRICAL_ERROR_MODEL_ID,
            "certificate_statement" => EXTERIOR_EMPIRICAL_ERROR_STATEMENT,
            "delta_same_point" => string(delta_same_point),
            "delta_cross_precision" => string(delta_cross_precision),
            "delta_endpoint_series" => string(delta_endpoint_series),
            "safety_factor" => string(error_breakdown.safety_factor),
            "numerical_error_abs" => string(error_breakdown.numerical_error_abs),
            "determinant_abs" => string(abs(base.value)),
        ))
        authenticated = DeterminantEvaluation{T}(
            base.value,
            error_breakdown,
            EXTERIOR_EMPIRICAL_ERROR_MODEL_ID,
            base.diagnostics,
        )
        source_phase = ACTIVE_PHASE[] === nothing ?
            "UNSCOPED" : ACTIVE_PHASE[]
        remember_authenticated_determinant!(
            evaluation_context,
            request,
            base_frequency,
            amplitude,
            authenticated,
            source_phase,
        )
        remember_authenticated_determinant!(
            evaluation_context,
            tight_request,
            tight_frequency,
            amplitude,
            tight,
            source_phase,
        )
        return authenticated
    end
    endpoint_disagreement_abs = max(
        base.error_breakdown.endpoint_disagreement_abs,
        tight.error_breakdown.endpoint_disagreement_abs,
    )
    equivalence_disagreement_abs = maximum_optional_discrepancy(
        T,
        base.error_breakdown.equivalence_disagreement_abs,
        tight.error_breakdown.equivalence_disagreement_abs,
    )
    control_disagreement_abs = abs(base.value - tight.value)
    precision_disagreement_abs = precision_guard_disagreement(
        T,
        request,
        evaluation_context,
        base_frequency,
        amplitude,
        purpose,
        current,
        base,
    )
    error_breakdown = determinant_error_breakdown(
        T,
        request,
        endpoint_disagreement_abs;
        control_disagreement_abs=control_disagreement_abs,
        equivalence_disagreement_abs=equivalence_disagreement_abs,
        precision_disagreement_abs=precision_disagreement_abs,
    )
    progress_emit("determinant_error_estimated"; payload=Dict(
        "error_model_id" => VERIFIED_ENDPOINT_ERROR_MODEL_ID,
        "endpoint_disagreement_abs" => string(endpoint_disagreement_abs),
        "control_disagreement_abs" => string(control_disagreement_abs),
        "equivalence_disagreement_abs" =>
            equivalence_disagreement_abs === nothing ? nothing :
            string(equivalence_disagreement_abs),
        "precision_disagreement_abs" =>
            precision_disagreement_abs === nothing ? nothing :
            string(precision_disagreement_abs),
        "guard_precision_digits" =>
            precision_disagreement_abs === nothing ? nothing :
            PRECISION_GUARD_DIGITS,
        "safety_factor" => string(error_breakdown.safety_factor),
        "numerical_error_abs" =>
            string(error_breakdown.numerical_error_abs),
        "determinant_abs" => string(abs(base.value)),
    ))
    authenticated = DeterminantEvaluation{T}(
        base.value,
        error_breakdown,
        VERIFIED_ENDPOINT_ERROR_MODEL_ID,
        base.diagnostics,
    )
    source_phase = ACTIVE_PHASE[] === nothing ?
        "UNSCOPED" : ACTIVE_PHASE[]
    # These samples become reusable only after the full comparison and error
    # aggregation above succeeded. The tight sample is the exact calculation
    # requested by RESOLUTION at the accepted PRIMARY frequency.
    remember_authenticated_determinant!(
        evaluation_context,
        request,
        base_frequency,
        amplitude,
        authenticated,
        source_phase,
    )
    remember_authenticated_determinant!(
        evaluation_context,
        tight_request,
        tight_frequency,
        amplitude,
        tight,
        source_phase,
    )
    return authenticated
end

function diagnostic_determinant_progress(
    ::Type{T},
    request,
    evaluation_context::DeterminantRequestContext{T},
    omega::Complex{T},
    amplitude::Complex{T},
    purpose::String,
    current::Complex{T},
) where {T<:AbstractFloat}
    evidence = matching_authenticated_determinant(
        evaluation_context, request, omega, amplitude
    )
    if evidence !== nothing
        AUTHENTICATED_EVIDENCE_REUSE_COUNT_PHASE[] += 1
        progress_emit("determinant_evidence_reused"; payload=Dict(
            "purpose" => purpose,
            "omega" => progress_complex(omega),
            "source_phase" => evidence.source_phase,
            "control_identity" => phase_control_identity(request),
            "authenticated_evidence_reuse_count_phase" =>
                AUTHENTICATED_EVIDENCE_REUSE_COUNT_PHASE[],
        ))
        return evidence.evaluation
    end
    return determinant_progress(
        T,
        request,
        evaluation_context,
        omega,
        amplitude,
        purpose,
        current,
    )
end

function diagnostic_newton_remaining_determinant_count(
    ::Type{T},
    request,
    evaluation_context::DeterminantRequestContext{T},
    initial::Complex{T},
    amplitude::Complex{T},
) where {T<:AbstractFloat}
    h = validated_frequency_step(T, request) * (one(T) + abs(initial))
    offset = Complex{T}(h, zero(T))
    return count(
        sample -> matching_authenticated_determinant(
            evaluation_context,
            request,
            sample,
            amplitude,
        ) === nothing,
        (initial + offset, initial - offset),
    )
end

function bounded_newton(
    ::Type{T},
    request,
    evaluation_context::DeterminantRequestContext{T},
    initial::Complex{T},
    amplitude::Complex{T},
    ; determinant_evaluator=determinant_progress,
    minimum_remaining_determinant_count::Int=8,
    propagate_derivative_error::Bool=false,
    acceptance_policy=nothing,
) where {T<:AbstractFloat}
    binary64_parity = acceptance_policy ==
        PROMOTED_ROOT_READOUT_POLICY_ID
    (acceptance_policy === nothing || binary64_parity) || error(
        "unknown promoted root acceptance policy"
    )
    frequency_step = validated_frequency_step(T, request)
    tolerance = parse_real(T, request, "root_correction_tolerance")
    maximum_iterations = parse_integer(request, "max_newton_iterations")
    value = initial
    best_value = value
    ACTIVE_NEWTON_INDEX[] = 1
    initial_determinant = determinant_evaluator(
        T,
        request,
        evaluation_context,
        value,
        amplitude,
        "initial best",
        value,
    )
    enforce_root_readout_feasibility(
        request, minimum_remaining_determinant_count
    )
    best_residual = abs(initial_determinant.value)
    best_upper_bound = determinant_upper_bound_abs(
        T, initial_determinant
    )
    best_evaluation = initial_determinant
    best_derivative = nothing
    best_derivative_authentication = nothing
    # The first iteration evaluates the determinant at the initial frequency,
    # which is exactly the value just computed above.  The determinant is a
    # deterministic function of the frequency and the request controls, so carry
    # that result into the first iteration instead of repeating the solve; at
    # promoted precision one determinant is several radial integrations.
    carried_value = value
    carried_residual = initial_determinant
    carried_available = true
    for iteration in 1:maximum_iterations
        ACTIVE_NEWTON_INDEX[] = iteration
        iteration_started = time_ns()
        residual = if carried_available && carried_value == value
            carried_available = false
            carried_residual
        else
            determinant_evaluator(
                T,
                request,
                evaluation_context,
                value,
                amplitude,
                "residual",
                value,
            )
        end
        magnitude = abs(residual.value)
        residual_is_better = binary64_parity ?
            magnitude < best_residual :
            determinant_is_better(T, residual, best_evaluation)
        if residual_is_better
            best_value, best_residual = value, magnitude
            best_upper_bound = determinant_upper_bound_abs(T, residual)
            best_evaluation = residual
            best_derivative = nothing
            best_derivative_authentication = nothing
        end
        newton_context = Dict{String,Any}(
            "newton_index" => iteration,
            "newton_limit" => maximum_iterations,
            "current_omega" => progress_complex(value),
        )
        progress_emit("newton_iteration_started"; context=newton_context, payload=Dict(
            "current_omega" => progress_complex(value),
            "determinant_abs" => string(magnitude),
            "best_determinant_abs" => string(best_residual),
            "best_determinant_upper_bound_abs" =>
                string(best_upper_bound),
            "acceptance_metric" => binary64_parity ?
                PROMOTED_ROOT_ACCEPTANCE_METRIC_ID :
                "newton_correction_estimate_abs",
            "acceptance_threshold" => string(tolerance),
        ))
        h = frequency_step * (one(T) + abs(value))
        derivative, _, derivative_error_abs = finite_difference_pair(
            T,
            request,
            evaluation_context,
            value,
            amplitude,
            Complex{T}(h, zero(T)),
            "derivative h",
            value;
            axis="real",
            authenticate_controls=propagate_derivative_error,
            determinant_evaluator=determinant_evaluator,
        )
        derivative_abs = abs(derivative)
        residual_error_abs = determinant_error_abs(T, residual)
        residual_upper_bound = magnitude + residual_error_abs
        if !isfinite(derivative_abs) || iszero(derivative)
            progress_emit("newton_iteration_completed"; context=newton_context, payload=Dict(
                "derivative_abs" => string(derivative_abs),
                "raw_step" => nothing,
                "applied_step" => nothing,
                "step_abs" => "0",
                "clipped" => false,
                "damping" => "0",
                "accepted" => false,
                "resulting_omega" => progress_complex(value),
                "resulting_determinant_abs" => string(magnitude),
                "elapsed_seconds" => (time_ns() - iteration_started) / 1.0e9,
            ))
            break
        end
        derivative_authentication = nothing
        derivative_lower_bound = derivative_abs
        if binary64_parity
            derivative_half, _, derivative_half_error_abs =
                finite_difference_pair(
                    T,
                    request,
                    evaluation_context,
                    value,
                    amplitude,
                    Complex{T}(h / 2, zero(T)),
                    "derivative h/2",
                    value;
                    axis="real",
                    authenticate_controls=propagate_derivative_error,
                    determinant_evaluator=determinant_evaluator,
                )
            derivative_candidate = derivative_authentication_candidate(
                derivative,
                derivative_error_abs + derivative_half_error_abs,
                abs(derivative_half - derivative),
                h,
                "real",
            )
            derivative_authentication = derivative_candidate.authentication
        else
            derivative_candidate = derivative_authentication_candidate(
                derivative,
                derivative_error_abs,
                zero(T),
                h,
                "real",
            )
            if derivative_candidate.authentication === nothing
                progress_emit("newton_iteration_completed"; context=newton_context, payload=Dict(
                    "derivative_abs" => string(derivative_abs),
                    "derivative_error_abs" => string(derivative_error_abs),
                    "derivative_lower_bound_abs" =>
                        string(derivative_candidate.lower_bound_abs),
                    "raw_step" => nothing,
                    "applied_step" => nothing,
                    "step_abs" => "0",
                    "clipped" => false,
                    "damping" => "0",
                    "accepted" => false,
                    "resulting_omega" => progress_complex(value),
                    "resulting_determinant_abs" => string(magnitude),
                    "elapsed_seconds" =>
                        (time_ns() - iteration_started) / 1.0e9,
                ))
                break
            end
            derivative_authentication = derivative_candidate.authentication
            derivative_lower_bound = derivative_authentication.lower_bound_abs
        end
        if value == best_value
            best_derivative = derivative
            best_derivative_authentication = derivative_authentication
        end
        raw_step = residual.value / derivative
        correction_abs = binary64_parity ?
            magnitude / derivative_abs :
            residual_upper_bound / derivative_lower_bound
        if correction_abs <= tolerance
            completion_payload = Dict{String,Any}(
                "derivative_abs" => string(derivative_abs),
                "derivative_error_abs" => string(derivative_error_abs),
                "determinant_error_abs" => string(residual_error_abs),
                "raw_step" => progress_complex(raw_step),
                "correction_abs" => string(correction_abs),
                "applied_step" => progress_complex(zero(Complex{T})),
                "step_abs" => "0",
                "clipped" => false,
                "damping" => "0",
                "accepted" => true,
                "resulting_omega" => progress_complex(value),
                "resulting_determinant_abs" => string(magnitude),
                "elapsed_seconds" => (time_ns() - iteration_started) / 1.0e9,
            )
            if !binary64_parity
                completion_payload["derivative_lower_bound_abs"] =
                    string(derivative_lower_bound)
            end
            progress_emit(
                "newton_iteration_completed";
                context=newton_context,
                payload=completion_payload,
            )
            return value, magnitude, derivative, true, residual,
                derivative_authentication
        end
        step = raw_step
        maximum_step = parse(T, "0.006")
        clipped = abs(step) > maximum_step
        clipped && (step *= maximum_step / abs(step))
        accepted = false
        selected_damping = parse(T, "0.125")
        resulting_abs = magnitude
        for damping in (
            one(T), parse(T, "0.5"), parse(T, "0.25"), parse(T, "0.125")
        )
            candidate = value - damping * step
            candidate_residual = determinant_evaluator(
                T,
                request,
                evaluation_context,
                candidate,
                amplitude,
                "damping $(damping)",
                value,
            )
            candidate_abs = abs(candidate_residual.value)
            candidate_upper_bound = determinant_upper_bound_abs(
                T, candidate_residual
            )
            candidate_improves = binary64_parity ?
                candidate_abs < magnitude :
                candidate_upper_bound < residual_upper_bound
            decision_context = merge(
                newton_context,
                Dict{String,Any}("candidate_omega" => progress_complex(candidate)),
            )
            progress_emit("damping_decided"; context=decision_context, payload=Dict(
                "damping" => string(damping),
                "candidate_omega" => progress_complex(candidate),
                "candidate_determinant_abs" => string(candidate_abs),
                "candidate_determinant_error_abs" =>
                    string(determinant_error_abs(T, candidate_residual)),
                "candidate_upper_bound_abs" => string(candidate_upper_bound),
                "current_upper_bound_abs" => string(residual_upper_bound),
                "comparison_metric" => binary64_parity ?
                    "raw_determinant_abs" :
                    "determinant_upper_bound_abs",
                "accepted" => candidate_improves,
            ))
            if candidate_improves
                value = candidate
                carried_value = candidate
                carried_residual = candidate_residual
                carried_available = true
                accepted = true
                selected_damping = damping
                resulting_abs = candidate_abs
                if !binary64_parity && determinant_is_better(
                        T, candidate_residual, best_evaluation
                    )
                    best_value, best_residual = candidate, candidate_abs
                    best_upper_bound = candidate_upper_bound
                    best_evaluation = candidate_residual
                end
                break
            end
        end
        applied_step = if accepted
            selected_damping * step
        else
            selected_damping = zero(T)
            zero(Complex{T})
        end
        progress_emit("newton_iteration_completed"; context=newton_context, payload=Dict(
            "derivative_abs" => string(derivative_abs),
            "raw_step" => progress_complex(raw_step),
            "applied_step" => progress_complex(applied_step),
            "step_abs" => string(abs(applied_step)),
            "clipped" => clipped,
            "damping" => string(selected_damping),
            "accepted" => accepted,
            "resulting_omega" => progress_complex(value),
            "resulting_determinant_abs" => string(resulting_abs),
            "elapsed_seconds" => (time_ns() - iteration_started) / 1.0e9,
        ))
        !accepted && break
    end
    if binary64_parity
        best_derivative === nothing && error(
            "binary64-parity Newton did not retain a finite derivative"
        )
        return best_value, best_residual, best_derivative, false,
            best_evaluation, best_derivative_authentication
    end
    return best_value, best_residual, nothing, false, best_evaluation, nothing
end

numeric_text(value) = string(value)

function finite_difference_noise_limit(
    request,
    nominal_step,
    minimum_step,
    maximum_step,
    attempts,
)
    return numerical_control_failure(
        request,
        "FINITE_DIFFERENCE_NOISE_LIMIT",
        "no frequency step in the configured range resolves the determinant derivative",
        Dict{String,Any}(
            "nominal_step" => string(nominal_step),
            "minimum_step" => string(minimum_step),
            "maximum_step" => string(maximum_step),
            "attempts" => attempts,
        );
        stage="finite-difference",
    )
end

function final_derivative(
    ::Type{T}, request,
    evaluation_context::DeterminantRequestContext{T},
    root::Complex{T}, amplitude::Complex{T},
    offset::Complex{T}, label::String,
    ; authenticate_controls::Bool,
    determinant_evaluator=nothing,
) where {T<:AbstractFloat}
    axis = iszero(imag(offset)) ? "real" : "imaginary"
    derivative, diagnostics, derivative_error_abs = finite_difference_pair(
        T,
        request,
        evaluation_context,
        root,
        amplitude,
        offset,
        label,
        root;
        axis=axis,
        authenticate_controls=authenticate_controls,
        determinant_evaluator=determinant_evaluator,
    )
    return derivative, diagnostics, derivative_error_abs
end

"""
    evaluate_single_derivative_step(T, request, context, root, amplitude,
                                    accepted_derivative)

Evaluate the derivative controls at the nominal step only.

This is the historical path and it is used wherever horizon authentication does
not apply -- the exterior Wronskian family, including its legacy diagnostic
phases. Those paths publish no determinant error model, so there is no noise
term to balance a step against and nothing for a rung search to optimise.

Keeping them here is not merely conservatism. The exterior scientific identity
is deliberately unchanged by this work, which means exterior receipts written
before it remain valid and reusable. If exterior derivative selection changed,
two runs under one identity could disagree, and the identity would no longer
mean what it claims.
"""
function evaluate_single_derivative_step(
    ::Type{T},
    request,
    evaluation_context::DeterminantRequestContext{T},
    root::Complex{T},
    amplitude::Complex{T},
    accepted_derivative,
    ; determinant_evaluator=nothing,
) where {T<:AbstractFloat}
    h = validated_frequency_step(T, request) * (one(T) + abs(root))
    isfinite(h) && h > zero(T) ||
        error("scaled frequency step is nonfinite or nonpositive")
    real_offset = Complex{T}(h, zero(T))
    base, _, base_error_abs = isnothing(accepted_derivative) ?
        final_derivative(
            T, request, evaluation_context, root, amplitude,
            real_offset, "final derivative h";
            authenticate_controls=false,
            determinant_evaluator=determinant_evaluator,
        ) : (accepted_derivative, nothing, zero(T))
    half, _, half_error_abs = final_derivative(
        T, request, evaluation_context, root, amplitude,
        real_offset / T(2), "final derivative h/2";
        authenticate_controls=false,
        determinant_evaluator=determinant_evaluator,
    )
    double, _, double_error_abs = final_derivative(
        T, request, evaluation_context, root, amplitude,
        T(2) * real_offset, "final derivative 2h";
        authenticate_controls=false,
        determinant_evaluator=determinant_evaluator,
    )
    imaginary, _, imaginary_error_abs = final_derivative(
        T, request, evaluation_context, root, amplitude,
        Complex{T}(zero(T), h), "final derivative ih";
        authenticate_controls=false,
        determinant_evaluator=determinant_evaluator,
    )
    fine_difference = abs(half - base)
    coarse_difference = abs(base - double)
    axis_difference = abs(imaginary - half)
    real_step_convergent = fine_difference <= coarse_difference
    complex_axis_consistent = axis_difference <= coarse_difference
    real_step_convergent && complex_axis_consistent ||
        error("determinant frequency derivative estimates do not agree")
    uncertainty = maximum((
        fine_difference, abs(double - half), axis_difference
    ))
    candidate = derivative_authentication_candidate(
        half,
        zero(T),
        uncertainty,
        h / T(2),
        "real",
    )
    if candidate.authentication === nothing
        attempt = Dict{String,Any}(
            "h" => string(h),
            "real_step_convergent" => real_step_convergent,
            "complex_axis_consistent" => complex_axis_consistent,
            "noise_resolved" => false,
            "derivative_abs" => string(abs(half)),
            "derivative_uncertainty_abs" => string(uncertainty),
            "base_derivative_error_abs" => string(base_error_abs),
            "half_derivative_error_abs" => string(half_error_abs),
            "double_derivative_error_abs" => string(double_error_abs),
            "imaginary_derivative_error_abs" =>
                string(imaginary_error_abs),
            "derivative_error_abs" => string(zero(T)),
            "accepted" => false,
        )
        throw(finite_difference_noise_limit(
            request, h, h / T(2), T(2) * h, [attempt]
        ))
    end
    derivative_authentication = candidate.authentication
    return (
        h=h,
        derivative_real_base=base,
        derivative_real_half=half,
        derivative_real_double=double,
        derivative_imaginary=imaginary,
        fine_step_difference_abs=fine_difference,
        coarse_step_difference_abs=coarse_difference,
        complex_axis_difference_abs=axis_difference,
        real_step_convergent=real_step_convergent,
        complex_axis_consistent=complex_axis_consistent,
        derivative_uncertainty_abs=uncertainty,
        base_error_abs=base_error_abs,
        half_error_abs=half_error_abs,
        double_error_abs=double_error_abs,
        imaginary_error_abs=imaginary_error_abs,
        derivative_error_abs=zero(T),
        derivative_authentication=derivative_authentication,
        rung_index=1,
        rung_count=1,
    )
end

"""
    evaluate_derivative_step_ladder(T, request, context, root, amplitude,
                                    accepted_derivative;
                                    authenticate_controls)

Select a finite-difference step at which the derivative is actually resolved.

For a centred difference the derivative error behaves as

    delta_D' ~ |D'''| h^2 / 6  +  eta_D / h

so there is an interior optimum: too large a step and truncation dominates, too
small and determinant noise does. A single fixed step -- the digit-derived 1e-60
being the extreme case -- cannot be right across modes, because both terms
depend on quantities that are properties of the problem rather than of the
arithmetic.

Starting from the calibrated nominal step, each rung is tested on the existing
`h/2, h, 2h, ih` ladder and accepted only when the real-axis estimates converge,
the real and imaginary axes agree, and the propagated determinant noise leaves a
positive derivative bound. Otherwise the step moves to the next bounded rung
within `[frequency_step_minimum, frequency_step_maximum]`.

Exhausting the range is reported as `FINITE_DIFFERENCE_NOISE_LIMIT` -- a
specific numerical diagnosis -- rather than an indefinite precision escalation
or a bare "estimates do not agree".
"""
function evaluate_derivative_step_ladder(
    ::Type{T},
    request,
    evaluation_context::DeterminantRequestContext{T},
    root::Complex{T},
    amplitude::Complex{T},
    accepted_derivative,
    ; authenticate_controls::Bool,
    determinant_evaluator=nothing,
) where {T<:AbstractFloat}
    # Without an error model there is no noise term for a rung search to
    # balance, and changing selection for those families would change results
    # under an unchanged scientific identity.
    authenticate_controls || return evaluate_single_derivative_step(
        T, request, evaluation_context, root, amplitude, accepted_derivative;
        determinant_evaluator=determinant_evaluator,
    )
    scale = one(T) + abs(root)
    nominal_policy, minimum_policy, maximum_policy =
        validated_frequency_steps(T, request)
    nominal = nominal_policy * scale
    minimum_step = minimum_policy * scale
    maximum_step = maximum_policy * scale
    all(isfinite, (nominal, minimum_step, maximum_step)) ||
        error("scaled frequency steps are nonfinite")
    rungs = frequency_step_rungs(nominal, minimum_step, maximum_step)

    attempts = Dict{String,Any}[]
    for (index, h) in enumerate(rungs)
        real_offset = Complex{T}(h, zero(T))
        # The authenticated path never reuses the Newton derivative: that value
        # was computed without an authenticated error term, so reusing it would
        # put an unauthenticated estimate inside an authenticated bound. The
        # unauthenticated path, which does reuse it, is handled above by
        # evaluate_single_derivative_step.
        base, _, base_error_abs =
            final_derivative(
                T, request, evaluation_context, root, amplitude,
                real_offset, "final derivative h";
                authenticate_controls=authenticate_controls,
                determinant_evaluator=determinant_evaluator,
            )
        half, _, half_error_abs = final_derivative(
            T, request, evaluation_context, root, amplitude,
            real_offset / T(2), "final derivative h/2";
            authenticate_controls=authenticate_controls,
            determinant_evaluator=determinant_evaluator,
        )
        double, _, double_error_abs = final_derivative(
            T, request, evaluation_context, root, amplitude,
            T(2) * real_offset, "final derivative 2h";
            authenticate_controls=authenticate_controls,
            determinant_evaluator=determinant_evaluator,
        )
        imaginary, _, imaginary_error_abs = final_derivative(
            T, request, evaluation_context, root, amplitude,
            Complex{T}(zero(T), h), "final derivative ih";
            authenticate_controls=authenticate_controls,
            determinant_evaluator=determinant_evaluator,
        )
        fine_difference = abs(half - base)
        coarse_difference = abs(base - double)
        axis_difference = abs(imaginary - half)
        real_step_convergent = fine_difference <= coarse_difference
        complex_axis_consistent = axis_difference <= coarse_difference
        uncertainty = maximum((
            fine_difference, abs(double - half), axis_difference
        ))
        derivative_abs = abs(half)
        candidate = derivative_authentication_candidate(
            half,
            half_error_abs,
            uncertainty,
            h / T(2),
            "real",
        )
        derivative_error_abs = half_error_abs
        derivative_lower_bound_abs = candidate.lower_bound_abs
        noise_resolved = candidate.authentication !== nothing
        accepted = real_step_convergent && complex_axis_consistent &&
            noise_resolved
        push!(attempts, Dict{String,Any}(
            "h" => string(h),
            "real_step_convergent" => real_step_convergent,
            "complex_axis_consistent" => complex_axis_consistent,
            "noise_resolved" => noise_resolved,
            "derivative_abs" => string(derivative_abs),
            "derivative_uncertainty_abs" => string(uncertainty),
            "base_derivative_error_abs" => string(base_error_abs),
            "half_derivative_error_abs" => string(half_error_abs),
            "double_derivative_error_abs" => string(double_error_abs),
            "imaginary_derivative_error_abs" =>
                string(imaginary_error_abs),
            "derivative_error_abs" => string(derivative_error_abs),
            "accepted" => accepted,
        ))
        progress_emit("frequency_step_evaluated"; payload=last(attempts))
        if accepted
            derivative_authentication = candidate.authentication
            return (
                h=h,
                derivative_real_base=base,
                derivative_real_half=half,
                derivative_real_double=double,
                derivative_imaginary=imaginary,
                fine_step_difference_abs=fine_difference,
                coarse_step_difference_abs=coarse_difference,
                complex_axis_difference_abs=axis_difference,
                real_step_convergent=real_step_convergent,
                complex_axis_consistent=complex_axis_consistent,
                derivative_uncertainty_abs=uncertainty,
                base_error_abs=base_error_abs,
                half_error_abs=half_error_abs,
                double_error_abs=double_error_abs,
                imaginary_error_abs=imaginary_error_abs,
                derivative_error_abs=half_error_abs,
                derivative_authentication=derivative_authentication,
                rung_index=index,
                rung_count=length(rungs),
            )
        end
    end
    throw(finite_difference_noise_limit(
        request, nominal, minimum_step, maximum_step, attempts
    ))
end

function root_authentication_text(
    authentication::RootAuthentication;
    accepted::Bool=authentication.accepted,
)
    breakdown = authentication.error_breakdown
    strategy = authentication.authentication_strategy
    if strategy == STAGED_REAL_AXIS_AUTHENTICATION_STRATEGY_ID
        authentication.derivative_real_double === nothing || error(
            "staged root authentication fabricated a 2h derivative"
        )
        authentication.derivative_imaginary === nothing || error(
            "staged root authentication fabricated an ih derivative"
        )
    elseif strategy == FULL_DERIVATIVE_LADDER_AUTHENTICATION_STRATEGY_ID
        authentication.derivative_real_double === nothing && error(
            "full root authentication omitted its 2h derivative"
        )
        authentication.derivative_imaginary === nothing && error(
            "full root authentication omitted its ih derivative"
        )
    else
        error("root authentication strategy is invalid")
    end
    derivative_evidence(value) = value === nothing ? nothing :
        progress_complex(value)
    return Dict{String,Any}(
        "central_determinant_re" =>
            numeric_text(real(authentication.central_determinant)),
        "central_determinant_im" =>
            numeric_text(imag(authentication.central_determinant)),
        "determinant_error" => breakdown === nothing ? nothing :
            Dict{String,Any}(
                "endpoint_disagreement_abs" =>
                    numeric_text(breakdown.endpoint_disagreement_abs),
                "control_disagreement_abs" =>
                    breakdown.control_disagreement_abs === nothing ? nothing :
                    numeric_text(breakdown.control_disagreement_abs),
                "equivalence_disagreement_abs" =>
                    breakdown.equivalence_disagreement_abs === nothing ?
                    nothing :
                    numeric_text(breakdown.equivalence_disagreement_abs),
                "precision_disagreement_abs" =>
                    breakdown.precision_disagreement_abs === nothing ?
                    nothing :
                    numeric_text(breakdown.precision_disagreement_abs),
                "safety_factor" => numeric_text(breakdown.safety_factor),
                "numerical_error_abs" =>
                    numeric_text(breakdown.numerical_error_abs),
                "error_model_id" => authentication.error_model_id,
            ),
        "residual_upper_bound_abs" =>
            numeric_text(authentication.residual_upper_bound_abs),
        "derivative_authentication" => Dict{String,Any}(
            "derivative_re" =>
                numeric_text(real(authentication.derivative.value)),
            "derivative_im" =>
                numeric_text(imag(authentication.derivative.value)),
            "propagated_error_abs" => numeric_text(
                authentication.derivative.propagated_error_abs
            ),
            "step_disagreement_abs" => numeric_text(
                authentication.derivative.step_disagreement_abs
            ),
            "lower_bound_abs" =>
                numeric_text(authentication.derivative.lower_bound_abs),
            "selected_step" => numeric_text(authentication.derivative.step),
            "axis" => authentication.derivative.axis,
        ),
        "authentication_strategy" => strategy,
        "derivative_evidence" => Dict{String,Any}(
            "real_base" =>
                derivative_evidence(authentication.derivative_real_base),
            "real_half" =>
                derivative_evidence(authentication.derivative_real_half),
            "real_double" =>
                derivative_evidence(authentication.derivative_real_double),
            "imaginary" =>
                derivative_evidence(authentication.derivative_imaginary),
        ),
        "correction_upper_bound" =>
            numeric_text(authentication.correction_upper_bound),
        "root_correction_tolerance" =>
            numeric_text(authentication.root_correction_tolerance),
        "accepted" => accepted,
    )
end

function solve_once(
    ::Type{T},
    request,
    evaluation_context::DeterminantRequestContext{T},
    initial::Complex{T},
    amplitude::Complex{T},
    ; authenticate_controls::Bool,
) where {T<:AbstractFloat}
    root, residual, accepted_derivative, newton_converged, root_evaluation,
        _ = bounded_newton(
            T, request, evaluation_context, initial, amplitude
        )
    horizon_authentication = authenticate_controls &&
        root_evaluation.error_breakdown !== nothing
    if horizon_authentication
        root_evaluation = authenticated_determinant_progress(
            T,
            request,
            evaluation_context,
            root,
            amplitude,
            "final root authentication",
            root;
            base_evaluation=root_evaluation,
        )
        residual = abs(root_evaluation.value)
    end
    root_error_abs = determinant_error_abs(T, root_evaluation)
    ladder = evaluate_derivative_step_ladder(
        T,
        request,
        evaluation_context,
        root,
        amplitude,
        accepted_derivative;
        authenticate_controls=horizon_authentication,
    )
    h = ladder.h
    derivative_real_base = ladder.derivative_real_base
    derivative_real_half = ladder.derivative_real_half
    derivative_real_double = ladder.derivative_real_double
    derivative_imaginary = ladder.derivative_imaginary
    fine_step_difference_abs = ladder.fine_step_difference_abs
    coarse_step_difference_abs = ladder.coarse_step_difference_abs
    complex_axis_difference_abs = ladder.complex_axis_difference_abs
    real_step_convergent = ladder.real_step_convergent
    complex_axis_consistent = ladder.complex_axis_consistent
    derivative_uncertainty_abs = ladder.derivative_uncertainty_abs
    derivative_abs = abs(derivative_real_half)
    # Two independent contributions reduce the usable derivative: disagreement
    # between step sizes and axes, and the propagated determinant noise. Both
    # are subtracted -- the step ladder measures how the estimate moves, not
    # how far it sits from the truth.
    derivative_authentication = ladder.derivative_authentication
    derivative_error_abs = derivative_authentication.propagated_error_abs
    derivative_lower_bound_abs = derivative_authentication.lower_bound_abs
    isfinite(derivative_abs) && isfinite(derivative_uncertainty_abs) &&
        isfinite(derivative_error_abs) ||
        error("determinant frequency derivative controls are unusable")
    tolerance = parse_real(T, request, "root_correction_tolerance")
    residual_upper_bound = residual + root_error_abs
    correction_upper_bound = residual_upper_bound / derivative_lower_bound_abs
    converged = newton_converged && correction_upper_bound <= tolerance
    root_authentication = RootAuthentication{T}(
        root_evaluation.value,
        root_evaluation.error_breakdown,
        residual_upper_bound,
        derivative_authentication,
        correction_upper_bound,
        root_evaluation.error_model_id,
        tolerance,
        converged,
        FULL_DERIVATIVE_LADDER_AUTHENTICATION_STRATEGY_ID,
        derivative_real_base,
        derivative_real_half,
        derivative_real_double,
        derivative_imaginary,
    )
    if !converged && correction_upper_bound > tolerance &&
            residual / derivative_lower_bound_abs <= tolerance
        # The determinant itself is small enough, but its error is not. This is
        # not a converged root and must never be recorded as one; it is a
        # request for tighter controls or more guard precision.
        throw(numerical_control_failure(
            request,
            "DETERMINANT_UNCERTAINTY_TOO_LARGE",
            "root determinant is small but its absolute error exceeds the correction tolerance",
            Dict{String,Any}(
                "determinant_abs" => string(residual),
                "determinant_error_abs" => string(root_error_abs),
                "correction_upper_bound" => string(correction_upper_bound),
                "correction_without_error" =>
                    string(residual / derivative_lower_bound_abs),
                "root_correction_tolerance" => string(tolerance),
                "derivative_lower_bound_abs" =>
                    string(derivative_lower_bound_abs),
                "root_authentication" =>
                    root_authentication_text(root_authentication),
            );
            stage="root-authentication",
        ))
    end
    progress_emit("derivative_control_completed"; payload=Dict(
        "root_authentication" =>
            root_authentication_text(root_authentication),
        "authentication_strategy" =>
            FULL_DERIVATIVE_LADDER_AUTHENTICATION_STRATEGY_ID,
        "derivative_real_half" => progress_complex(derivative_real_half),
        "derivative_real_base" => progress_complex(derivative_real_base),
        "derivative_real_double" => progress_complex(derivative_real_double),
        "derivative_imaginary" => progress_complex(derivative_imaginary),
        "fine_step_difference_abs" => string(fine_step_difference_abs),
        "coarse_step_difference_abs" => string(coarse_step_difference_abs),
        "complex_axis_difference_abs" => string(complex_axis_difference_abs),
        "real_step_convergent" => real_step_convergent,
        "complex_axis_consistent" => complex_axis_consistent,
        "derivative_uncertainty_abs" => string(derivative_uncertainty_abs),
        "determinant_error_abs" => string(root_error_abs),
        "derivative_error_abs" => string(derivative_error_abs),
        "derivative_lower_bound_abs" => string(derivative_lower_bound_abs),
        "residual_upper_bound_abs" => string(residual_upper_bound),
        "correction_upper_bound" => string(correction_upper_bound),
        "accepted" => converged,
    ))
    return root, residual, derivative_lower_bound_abs, converged,
        root_evaluation, root_authentication
end

function diagnostic_consistency_newton(
    ::Type{T},
    request,
    evaluation_context::DeterminantRequestContext{T},
    initial::Complex{T},
    amplitude::Complex{T};
    determinant_evaluator=diagnostic_determinant_progress,
    minimum_remaining_determinant_count::Int,
) where {T<:AbstractFloat}
    # A diagnostic Newton step authenticates its one required h stencil against
    # the determinant-error evidence carried by the two endpoint samples. It
    # deliberately does not claim the h/2, 2h, and ih cross-step certificate
    # reserved for full authentication.
    return bounded_newton(
        T,
        request,
        evaluation_context,
        initial,
        amplitude;
        determinant_evaluator=determinant_evaluator,
        minimum_remaining_determinant_count=
            minimum_remaining_determinant_count,
        propagate_derivative_error=true,
    )
end

function solve_binary64_parity_primary(
    ::Type{T},
    request,
    evaluation_context::DeterminantRequestContext{T},
    initial::Complex{T},
    amplitude::Complex{T};
    newton_solver=bounded_newton,
) where {T<:AbstractFloat}
    determinant_count_before = DETERMINANT_INDEX_PHASE[]
    propagate_primary_derivative_error =
        haskey(request, "determinant_error_model")
    root, residual, newton_derivative, newton_converged,
        root_evaluation, derivative_authentication = newton_solver(
            T,
            request,
            evaluation_context,
            initial,
            amplitude;
            determinant_evaluator=determinant_progress,
            minimum_remaining_determinant_count=2,
            propagate_derivative_error=propagate_primary_derivative_error,
            acceptance_policy=PROMOTED_ROOT_READOUT_POLICY_ID,
        )
    newton_derivative === nothing && error(
        "binary64-parity PRIMARY omitted its complex Newton derivative"
    )
    derivative_abs = abs(newton_derivative)
    isfinite(derivative_abs) && derivative_abs > zero(T) || error(
        "binary64-parity PRIMARY derivative is invalid"
    )
    correction_abs = residual / derivative_abs
    tolerance = parse_real(T, request, "root_correction_tolerance")
    accepted = newton_converged && correction_abs <= tolerance
    branch_identity = string(required(request, "branch_convention"))
    reference_root = parse_complex(T, request, "omega_re", "omega_im")
    branch_authenticated =
        branch_identity == BRANCH_CONVENTION_ID &&
        abs(root - reference_root) <=
            parse_real(T, request, "branch_enclosure_radius_abs")
    determinant_count_after_newton = DETERMINANT_INDEX_PHASE[]
    determinant_count_after_newton >= determinant_count_before || error(
        "PRIMARY determinant counter moved backwards"
    )
    return (
        root=root,
        residual=residual,
        derivative=newton_derivative,
        derivative_abs=derivative_abs,
        correction_abs=correction_abs,
        converged=accepted,
        root_evaluation=root_evaluation,
        root_authentication=nothing,
        solve_role=BINARY64_PARITY_PRIMARY,
        authoritative=true,
        acceptance_metric=PROMOTED_ROOT_ACCEPTANCE_METRIC_ID,
        root_correction_tolerance=tolerance,
        newton_determinant_count=
            determinant_count_after_newton - determinant_count_before,
        post_newton_determinant_count=0,
        determinant_error_abs=determinant_error_abs(T, root_evaluation),
        error_model_id=root_evaluation.error_model_id,
        derivative_authentication=derivative_authentication,
        branch_identity=branch_identity,
        branch_authenticated=branch_authenticated,
        control_identity=phase_control_identity(request),
    )
end

function required_raw_determinant_evaluation_count(request)
    if haskey(request, "diagnostic_model_identity")
        validate_raw_determinant_contract(request)
        return parse_integer(request, "required_raw_determinant_count")
    end
    # Fixed-root survey/sample requests predate the promoted root-readout
    # role fields. They still select by their explicit error-model identity,
    # never by mechanism or by a returned raw count.
    model = string(required(request, "determinant_error_model"))
    model == EXTERIOR_EMPIRICAL_ERROR_MODEL_ID && return 3
    model == EXTERIOR_ADDITIVE_CHANNEL_SCHEMA_ID && return 1
    model == VERIFIED_ENDPOINT_ERROR_MODEL_ID && return 1
    error("request carries an unsupported raw determinant model")
end

function solve_fixed_root_diagnostic(
    ::Type{T},
    request,
    evaluation_context::DeterminantRequestContext{T},
    phase::String,
    omega_primary::Complex{T},
    amplitude::Complex{T},
    primary_derivative::Complex{T},
) where {T<:AbstractFloat}
    phase in ("TRUNCATION", "RESOLUTION") || error(
        "fixed-root diagnostic phase is invalid"
    )
    derivative_abs = abs(primary_derivative)
    isfinite(derivative_abs) && derivative_abs > zero(T) || error(
        "fixed-root diagnostic PRIMARY derivative is invalid"
    )
    raw_count_before = DETERMINANT_INDEX_PHASE[]
    raw_count_before == 0 || error(
        "fixed-root diagnostic began after an unexpected determinant evaluation"
    )
    root_evaluation = determinant_progress(
        T,
        request,
        evaluation_context,
        omega_primary,
        amplitude,
        "fixed PRIMARY root",
        omega_primary,
    )
    raw_determinant_evaluation_count =
        DETERMINANT_INDEX_PHASE[] - raw_count_before
    expected_raw_count =
        required_raw_determinant_evaluation_count(request)
    raw_determinant_evaluation_count == expected_raw_count || error(
        "fixed-root diagnostic did not complete its required determinant evaluations"
    )
    residual = abs(root_evaluation.value)
    correction_abs = residual / abs(primary_derivative)
    tolerance = parse_real(T, request, "root_correction_tolerance")
    branch_identity = string(required(request, "branch_convention"))
    branch_authenticated = branch_identity == BRANCH_CONVENTION_ID
    return (
        root=omega_primary,
        residual=residual,
        derivative=primary_derivative,
        derivative_abs=derivative_abs,
        correction_abs=correction_abs,
        converged=
            correction_abs <= tolerance && branch_authenticated,
        root_evaluation=root_evaluation,
        root_authentication=nothing,
        solve_role=FIXED_ROOT_DIAGNOSTIC,
        authoritative=false,
        fixed_root=true,
        derivative_source="PRIMARY_COMPLEX",
        acceptance_metric=PROMOTED_ROOT_ACCEPTANCE_METRIC_ID,
        root_correction_tolerance=tolerance,
        determinant_error_abs=determinant_error_abs(T, root_evaluation),
        error_model_id=root_evaluation.error_model_id,
        branch_identity=branch_identity,
        branch_authenticated=branch_authenticated,
        control_identity=phase_control_identity(request),
        logical_authenticated_determinant_count=1,
        raw_determinant_evaluation_count=
            raw_determinant_evaluation_count,
    )
end

function solve_full_authentication(
    ::Type{T},
    request,
    evaluation_context::DeterminantRequestContext{T},
    initial::Complex{T},
    amplitude::Complex{T},
) where {T<:AbstractFloat}
    raw = solve_once(
        T,
        request,
        evaluation_context,
        initial,
        amplitude;
        authenticate_controls=true,
    )
    root, residual, derivative_lower_bound_abs, converged,
        root_evaluation, root_authentication = raw
    reference_root = parse_complex(T, request, "omega_re", "omega_im")
    branch_identity = string(required(request, "branch_convention"))
    branch_authenticated =
        branch_identity == BRANCH_CONVENTION_ID &&
        abs(root - reference_root) <=
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
        root_authentication=root_authentication,
        solve_role=FULL_AUTHENTICATION,
        authentication_mode=LEGACY_FULL_AUTHENTICATION,
        authoritative=true,
        full_authentication_escalated=false,
        escalation_reason=nothing,
        authenticated_evidence_reused=
            AUTHENTICATED_EVIDENCE_REUSE_COUNT_PHASE[] > 0,
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

function authentication_progress_payload(
    phase::String,
    mode::RootAuthenticationMode,
    authoritative::Bool,
    full_authentication_escalated::Bool,
    escalation_reason,
    determinant_count_phase::Int;
    residual_upper_bound_abs=nothing,
    derivative_lower_bound_abs=nothing,
    required_derivative_lower_bound_abs=nothing,
    correction_upper_bound=nothing,
    root_correction_tolerance=nothing,
    raw_step_disagreement_abs=nothing,
    guarded_step_disagreement_abs=nothing,
    propagated_derivative_error_abs=nothing,
)
    encoded(value) = value === nothing ? nothing : string(value)
    return Dict{String,Any}(
        "phase" => phase,
        "root_phase" => phase,
        "authentication_mode" => authentication_mode_text(mode),
        "authoritative" => authoritative,
        "full_authentication_escalated" =>
            full_authentication_escalated,
        "escalation_reason" => escalation_reason,
        "determinant_count_phase" => determinant_count_phase,
        "residual_upper_bound_abs" => encoded(residual_upper_bound_abs),
        "derivative_lower_bound_abs" => encoded(derivative_lower_bound_abs),
        "required_derivative_lower_bound_abs" =>
            encoded(required_derivative_lower_bound_abs),
        "correction_upper_bound" => encoded(correction_upper_bound),
        "root_correction_tolerance" => encoded(root_correction_tolerance),
        "raw_step_disagreement_abs" => encoded(raw_step_disagreement_abs),
        "guarded_step_disagreement_abs" =>
            encoded(guarded_step_disagreement_abs),
        "propagated_derivative_error_abs" =>
            encoded(propagated_derivative_error_abs),
    )
end

function authentication_progress_payload(phase::String, result)
    return authentication_progress_payload(
        phase,
        result.authentication_mode,
        result.authoritative,
        result.full_authentication_escalated,
        result.escalation_reason,
        DETERMINANT_INDEX_PHASE[];
        residual_upper_bound_abs=result.residual_upper_bound_abs,
        derivative_lower_bound_abs=result.derivative_lower_bound_abs,
        required_derivative_lower_bound_abs=
            result.required_derivative_lower_bound_abs,
        correction_upper_bound=result.correction_upper_bound,
        root_correction_tolerance=result.root_correction_tolerance,
        raw_step_disagreement_abs=result.raw_step_disagreement_abs,
        guarded_step_disagreement_abs=result.guarded_step_disagreement_abs,
        propagated_derivative_error_abs=
            result.propagated_derivative_error_abs,
    )
end

function solve_staged_primary_authentication(
    ::Type{T},
    request,
    evaluation_context::DeterminantRequestContext{T},
    initial::Complex{T},
    amplitude::Complex{T};
    newton_solver=bounded_newton,
    central_authenticator=authenticated_determinant_progress,
    half_derivative_evaluator=final_derivative,
    full_authenticator=solve_full_authentication,
) where {T<:AbstractFloat}
    phase = "PRIMARY"
    tolerance = parse_real(T, request, "root_correction_tolerance")
    progress_emit("primary_staged_authentication_started"; payload=
        authentication_progress_payload(
            phase,
            STAGED_FULL_AUTHENTICATION,
            true,
            false,
            nothing,
            DETERMINANT_INDEX_PHASE[];
            root_correction_tolerance=tolerance,
        )
    )

    root, residual, newton_derivative, newton_converged,
        root_evaluation, _ = newton_solver(
            T,
            request,
            evaluation_context,
            initial,
            amplitude;
            determinant_evaluator=determinant_progress,
            minimum_remaining_determinant_count=7,
            propagate_derivative_error=false,
        )

    escalation_reason = nothing
    authenticated_root_evaluation = nothing
    derivative_real_half = nothing
    propagated_derivative_error_abs = nothing
    raw_step_disagreement_abs = nothing
    guarded_step_disagreement_abs = nothing
    derivative_lower_bound_abs = nothing
    residual_upper_bound_abs = nothing
    required_derivative_lower_bound_abs = nothing
    correction_upper_bound = nothing

    if !newton_converged
        escalation_reason = "STAGED_NEWTON_NOT_CONVERGED"
    elseif newton_derivative === nothing
        escalation_reason = "STAGED_NEWTON_DERIVATIVE_MISSING"
    elseif !all(isfinite, (
        real(newton_derivative), imag(newton_derivative),
        abs(newton_derivative),
    )) || iszero(newton_derivative)
        escalation_reason = "STAGED_NEWTON_DERIVATIVE_INVALID"
    elseif root_evaluation.error_breakdown === nothing ||
            root_evaluation.error_model_id === nothing ||
            !isequal(
                root_evaluation.error_model_id,
                required(request, "determinant_error_model"),
            )
        escalation_reason =
            "STAGED_DETERMINANT_ERROR_MODEL_UNAVAILABLE"
    else
        authenticated_root_evaluation = try
            central_authenticator(
                T,
                request,
                evaluation_context,
                root,
                amplitude,
                "staged primary central root",
                root;
                base_evaluation=root_evaluation,
            )
        catch failure
            failure isa InterruptException && rethrow()
            failure isa ODEControlFailure && rethrow()
            failure isa RootReadoutResourceLimit && rethrow()
            failure isa NumericalControlFailure || rethrow()
            nothing
        end
        if authenticated_root_evaluation === nothing ||
                authenticated_root_evaluation.error_breakdown === nothing ||
                authenticated_root_evaluation.error_model_id === nothing ||
                !isequal(
                    authenticated_root_evaluation.error_model_id,
                    required(request, "determinant_error_model"),
                )
            escalation_reason =
                "STAGED_DETERMINANT_ERROR_MODEL_UNAVAILABLE"
        end
    end

    if escalation_reason === nothing
        residual = abs(authenticated_root_evaluation.value)
        root_error_abs =
            determinant_error_abs(T, authenticated_root_evaluation)
        residual_upper_bound_abs = residual + root_error_abs
        required_derivative_lower_bound_abs =
            residual_upper_bound_abs / tolerance
        h = validated_frequency_step(T, request) * (one(T) + abs(root))
        derivative_sample = try
            half_derivative_evaluator(
                T,
                request,
                evaluation_context,
                root,
                amplitude,
                Complex{T}(h / T(2), zero(T)),
                "staged derivative h/2";
                authenticate_controls=true,
                determinant_evaluator=nothing,
            )
        catch failure
            failure isa InterruptException && rethrow()
            failure isa ODEControlFailure && rethrow()
            failure isa RootReadoutResourceLimit && rethrow()
            failure isa NumericalControlFailure || rethrow()
            nothing
        end
        if derivative_sample === nothing
            escalation_reason =
                "STAGED_DERIVATIVE_LOWER_BOUND_UNRESOLVED"
        else
            derivative_real_half, _, propagated_derivative_error_abs =
                derivative_sample
            if !all(isfinite, (
                real(derivative_real_half),
                imag(derivative_real_half),
                propagated_derivative_error_abs,
            )) || propagated_derivative_error_abs < zero(T)
                escalation_reason =
                    "STAGED_DERIVATIVE_LOWER_BOUND_UNRESOLVED"
            else
                raw_step_disagreement_abs =
                    abs(derivative_real_half - newton_derivative)
                safety_factor =
                    authenticated_root_evaluation.error_breakdown.safety_factor
                if !isfinite(safety_factor) ||
                        safety_factor <= zero(T)
                    escalation_reason =
                        "STAGED_DERIVATIVE_LOWER_BOUND_UNRESOLVED"
                else
                    # TODO: [HUMAN MATH REVIEW REQUIRED - justify the staged derivative-disagreement safety multiplier before final merge]
                    guarded_step_disagreement_abs =
                        safety_factor * raw_step_disagreement_abs
                    candidate = derivative_authentication_candidate(
                        derivative_real_half,
                        propagated_derivative_error_abs,
                        guarded_step_disagreement_abs,
                        h / T(2),
                        "real",
                    )
                    if candidate.authentication === nothing
                        derivative_lower_bound_abs =
                            candidate.lower_bound_abs
                        escalation_reason =
                            "STAGED_DERIVATIVE_LOWER_BOUND_UNRESOLVED"
                    else
                        derivative_authentication =
                            candidate.authentication
                        derivative_lower_bound_abs =
                            derivative_authentication.lower_bound_abs
                        correction_upper_bound =
                            residual_upper_bound_abs /
                            derivative_lower_bound_abs
                        if !isfinite(correction_upper_bound) ||
                                correction_upper_bound > tolerance
                            escalation_reason =
                                "STAGED_CORRECTION_UPPER_BOUND_ABOVE_TOLERANCE"
                        end
                    end
                end
            end
        end
    end

    reference_root = parse_complex(T, request, "omega_re", "omega_im")
    branch_identity = string(required(request, "branch_convention"))
    branch_authenticated =
        branch_identity == BRANCH_CONVENTION_ID &&
        abs(root - reference_root) <=
            parse_real(T, request, "branch_enclosure_radius_abs")
    if escalation_reason === nothing && !branch_authenticated
        escalation_reason =
            "STAGED_BRANCH_AUTHENTICATION_UNRESOLVED"
    end

    if escalation_reason === nothing
        derivative_authentication = DerivativeAuthentication{T}(
            derivative_real_half,
            propagated_derivative_error_abs,
            guarded_step_disagreement_abs,
            validated_frequency_step(T, request) *
                (one(T) + abs(root)) / T(2),
            "real",
        )
        root_authentication = RootAuthentication{T}(
            authenticated_root_evaluation.value,
            authenticated_root_evaluation.error_breakdown,
            residual_upper_bound_abs,
            derivative_authentication,
            correction_upper_bound,
            authenticated_root_evaluation.error_model_id,
            tolerance,
            true,
            STAGED_REAL_AXIS_AUTHENTICATION_STRATEGY_ID,
            newton_derivative,
            derivative_real_half,
            nothing,
            nothing,
        )
        result = (
            root=root,
            residual=residual,
            derivative_lower_bound_abs=derivative_lower_bound_abs,
            converged=true,
            root_evaluation=authenticated_root_evaluation,
            root_authentication=root_authentication,
            solve_role=FULL_AUTHENTICATION,
            authentication_mode=STAGED_FULL_AUTHENTICATION,
            authoritative=true,
            full_authentication_escalated=false,
            escalation_reason=nothing,
            authenticated_evidence_reused=
                AUTHENTICATED_EVIDENCE_REUSE_COUNT_PHASE[] > 0,
            residual_upper_bound_abs=residual_upper_bound_abs,
            required_derivative_lower_bound_abs=
                required_derivative_lower_bound_abs,
            correction_upper_bound=correction_upper_bound,
            root_correction_tolerance=tolerance,
            raw_step_disagreement_abs=raw_step_disagreement_abs,
            guarded_step_disagreement_abs=
                guarded_step_disagreement_abs,
            propagated_derivative_error_abs=
                propagated_derivative_error_abs,
            determinant_error_abs=
                determinant_error_abs(T, authenticated_root_evaluation),
            error_model_id=authenticated_root_evaluation.error_model_id,
            branch_identity=branch_identity,
            branch_authenticated=branch_authenticated,
            control_identity=phase_control_identity(request),
        )
        staged_payload = authentication_progress_payload(phase, result)
        progress_emit("primary_staged_derivative_accepted";
            payload=staged_payload
        )
        progress_emit("derivative_control_completed"; payload=merge(
            staged_payload,
            Dict{String,Any}(
                "root_authentication" =>
                    root_authentication_text(root_authentication),
                "authentication_strategy" =>
                    STAGED_REAL_AXIS_AUTHENTICATION_STRATEGY_ID,
                "derivative_real_half" =>
                    progress_complex(derivative_real_half),
                "derivative_real_base" =>
                    progress_complex(newton_derivative),
                "derivative_real_double" => nothing,
                "derivative_imaginary" => nothing,
                "fine_step_difference_abs" =>
                    string(raw_step_disagreement_abs),
                "coarse_step_difference_abs" => nothing,
                "complex_axis_difference_abs" => nothing,
                "real_step_convergent" => nothing,
                "complex_axis_consistent" => nothing,
                "derivative_uncertainty_abs" =>
                    string(guarded_step_disagreement_abs),
                "determinant_error_abs" =>
                    string(result.determinant_error_abs),
                "derivative_error_abs" =>
                    string(propagated_derivative_error_abs),
                "accepted" => true,
            ),
        ))
        progress_emit("primary_staged_authentication_completed";
            payload=staged_payload
        )
        return result
    end

    rejected_payload = authentication_progress_payload(
        phase,
        STAGED_FULL_AUTHENTICATION,
        true,
        true,
        escalation_reason,
        DETERMINANT_INDEX_PHASE[];
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
        return [
            "schema_version" => 11,
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
        ]
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

    return [
        "schema_version" => 11,
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
    ]
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
        "fixed_root_reliability_target_abs",
        "fixed_root_reliability_rule",
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
        "fixed_root_reliability_target_abs" =>
            required(document, "fixed_root_reliability_target_abs"),
        "fixed_root_reliability_rule" =>
            required(document, "fixed_root_reliability_rule"),
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
        "required_digit_guard" => string(REQUIRED_DIGIT_GUARD),
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
    for key in (
        "promoted_control_calibration_receipt_sha256",
        "empirical_control_profile_sha256",
    )
        length(string(required(request, key))) == 64 ||
            error("fixed-root survey control receipt is invalid")
    end
    return nothing
end

function validate_fixed_root_survey_request(request)
    parse_integer(request, "schema_version") == 2 ||
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
    string(required(request, "fixed_root_reliability_rule")) ==
        FIXED_ROOT_RELIABILITY_RULE ||
        error("fixed-root reliability rule is invalid")
    reliability_target = parse_real(
        BigFloat, request, "fixed_root_reliability_target_abs"
    )
    zero(BigFloat) < reliability_target < one(BigFloat) ||
        error("fixed-root reliability target is invalid")
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
        "maximum_series_digits_lost" =>
            numeric_text(accumulator.maximum_series_digits_lost),
        "maximum_recurrence_digits_lost" =>
            numeric_text(accumulator.maximum_recurrence_digits_lost),
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
        "schema_version" => 2,
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
    return [
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
    ]
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

function evaluate_request(request)
    operation, digits, bits = validate_worker_request_contract(request)
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
    document = JSON.parsefile(request_path)
    request = if string(required(document, "operation")) ==
            FIXED_ROOT_SURVEY_BATCH_OPERATION
        flatten_fixed_root_survey_request(document)
    else
        flatten_request(document)
    end
    try
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
        progress_emit("request_validated"; payload=Dict(
            "request_sha256" => string(required(request, "request_sha256")),
            "execution_resource_policy" => resource_policy_identity(request),
        ))
        result = if string(required(request, "operation")) ==
                FIXED_ROOT_SURVEY_BATCH_OPERATION
            digits, bits, roles, samples =
                validate_fixed_root_survey_request(request)
            setprecision(BigFloat, bits) do
                fixed_root_survey_batch_fields(
                    request, digits, bits, roles, samples
                )
            end
        else
            Dict(evaluate_request(request))
        end
        mkpath(dirname(response_path))
        write(response_path, JSON.json(result))
        progress_emit("request_completed"; payload=Dict(
            "request_sha256" => string(required(request, "request_sha256")),
        ))
        return 0
    catch failure
        result = if failure isa WorkerControlFailure
            Dict(
                "schema_version" => 1,
                "status" => "error",
                "error_type" => string(typeof(failure)),
                "message" => sprint(showerror, failure),
                "failure" => operation_control_receipt(
                    request, failure_details(failure)
                ),
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
        request_failure = Dict{String,Any}(
            "error_type" => string(typeof(failure)),
            "message" => sprint(showerror, failure),
        )
        if failure isa WorkerControlFailure
            request_failure["failure"] = failure_details(failure)
        end
        progress_emit("request_failed"; payload=request_failure)
        @error "M02 Julia precision worker failed" exception=(failure, catch_backtrace())
        return 21
    end
end

if abspath(PROGRAM_FILE) == abspath(@__FILE__)
    exit(main())
end
