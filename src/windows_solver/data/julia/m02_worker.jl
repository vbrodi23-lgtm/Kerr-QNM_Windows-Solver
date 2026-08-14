#!/usr/bin/env julia

using LinearAlgebra
using DifferentialEquations
using JSON
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
const PROGRESS_SCHEMA = "windows-solver.progress/1"
const CONDITIONING_SCHEMA = "windows-solver.m02-conditioning/3"
const HOMOGENEOUS_REPRESENTATION_ID = "factored-plane-wave-gsn/v1"
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

function control_failure_context(request)
    now = time_ns()
    return Dict{String,Any}(
        "retryable" => true,
        "precision_digits" => parse_integer(request, "precision_digits"),
        "request_sha256" => required(request, "request_sha256"),
        "job_id" => required(request, "job_id"),
        "leaf_id" => required(request, "leaf_id"),
        "role" => required(request, "role"),
        "job_policy_sha256" => required(request, "job_policy_sha256"),
        "backend_identity_sha256" =>
            required(request, "backend_identity_sha256"),
        "refinement_level" => required(request, "refinement_level"),
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
        "request_sha256" => required(document, "request_sha256"),
        "readout_radius" => required(policy, "readout_radius"),
        "ode_relative_tolerance" => required(policy, "ode_relative_tolerance"),
        "ode_absolute_tolerance" => required(policy, "ode_absolute_tolerance"),
        "endpoint_series_order" => required(policy, "endpoint_series_order"),
        "support_subinterval_count" => required(policy, "support_subinterval_count"),
        "angular_pad" => required(policy, "angular_pad"),
        "rho_in" => required(policy, "rho_in"),
        "rho_out" => required(policy, "rho_out"),
        "frequency_step" => required(policy, "frequency_step"),
        "root_correction_tolerance" => required(
            policy, "root_correction_tolerance"
        ),
        "branch_enclosure_radius_abs" => required(
            policy, "branch_enclosure_radius_abs"
        ),
        "max_newton_iterations" => required(policy, "max_newton_iterations"),
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
    )
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
    if mechanism != "horizon-admittance"
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
    return flattened
end

function validate_regularised_gsn_policy(request)
    expected_common = Dict{String,Any}(
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
    )
    for (key, expected) in expected_common
        required(request, key) == expected ||
            error("regularised GSN policy identity $(key) is invalid")
    end

    horizon = string(required(request, "mechanism_id")) ==
        "horizon-admittance"
    expected_mechanism = if horizon
        Dict{String,Any}(
            "determinant_family" => HORIZON_DETERMINANT_FAMILY_ID,
            "scattering_diagnostics_applicable" => true,
            "scattering_coefficient_extraction" => SCATTERING_EXTRACTION_ID,
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
        )
    else
        Dict{String,Any}(
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
    end
    for (key, expected) in expected_mechanism
        isequal(required(request, key), expected) ||
            error("regularised GSN mechanism policy $(key) is invalid")
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

struct DeterminantEvaluation{T<:AbstractFloat}
    value::Complex{T}
    diagnostics::DeterminantDiagnostics{T}
end

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
        0,
    )
end

struct DeterminantRequestContext{T<:AbstractFloat}
    frozen_convention::GSNBranchConvention{T}
    frozen_branch_cell::GSN.GSNBranchCell
    conditioning::ConditioningAccumulator{T}
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
    )
end

function required_reliable_digits(::Type{T}, request) where {T<:AbstractFloat}
    tolerance = parse_real(T, request, "root_correction_tolerance")
    zero(T) < tolerance < one(T) ||
        error("root correction tolerance must lie strictly between zero and one")
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
    spectral = CF.build_homogeneous_spectral_context(
        s,
        m,
        a,
        omega,
        lambda,
        digits,
        bits,
        parse_integer(request, "endpoint_series_order"),
        context.frozen_convention,
    )
    spectral.frozen_branch_cell == context.frozen_branch_cell ||
        error("sample spectral context changed the request branch cell")
    spectral.frozen_branch_cell.version == BRANCH_CONVENTION_ID ||
        error("sample spectral context changed the branch convention identity")
    return spectral
end

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
            reltol=parse_real(T, request, "ode_relative_tolerance"),
            abstol=parse_real(T, request, "ode_absolute_tolerance"),
            ode_maxiters=parse_integer(request, "homogeneous_ode_maxiters"),
            ode_observation_factory=observation_factory,
            ode_solution_observer=observe_ode_solution,
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
        preparation.initial_condition.regularity.finite
        for preparation in preparations
    )
    maximum_endpoint_reconstruction_error = maximum(
        max(
            preparation.initial_condition.regularity.relative_X_reconstruction_error,
            preparation.initial_condition.regularity.relative_Xrho_reconstruction_error,
            preparation.initial_condition.regularity.Xrho_backward_residual,
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

function numerical_control_failure(
    request,
    failure_code::String,
    message::String,
    diagnostics::Dict{String,Any};
    retryable::Bool=false,
)
    details = merge(control_failure_context(request), Dict{String,Any}(
        "failure_code" => failure_code,
        "failure_class" => "CONTROL",
        "retryable" => retryable,
        "diagnostics" => diagnostics,
    ))
    return NumericalControlFailure(message, details)
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
        return numerical_control_failure(
            request,
            failure_code,
            sprint(showerror, failure),
            diagnostics;
            retryable=retryable,
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
            diagnostics,
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

function evaluate_horizon_determinant(
    ::Type{T},
    request,
    context::DeterminantRequestContext{T},
    omega::Complex{T},
    amplitude::Complex{T},
) where {T<:AbstractFloat}
    readout = parse_real(T, request, "readout_radius")
    spectral = build_sample_spectral_context(T, request, omega, context)
    contour = build_worker_contour_context(
        T, request, spectral, readout, "Xup"
    )
    required_digits = required_reliable_digits(T, request)
    preparations = CF.prepare_factored_horizon_determinant_branches(
        spectral, contour, required_digits
    )
    for preparation in (
        preparations.infinity_outgoing,
        preparations.horizon_ingoing,
        preparations.horizon_outgoing,
    )
        emit_asymptotic_preparation(preparation)
    end
    factored_homogeneous_rhs_counter = Ref(0)
    observation_factory = (leg, tspan, algorithm) ->
        ode_observation_factory(request, leg, tspan, algorithm)
    propagation = progress_operation("Xup") do
        CF.solve_factored_xup_scattering_endpoint(
            spectral,
            contour,
            preparations;
            odealgo=AutoVern9(Rosenbrock23(autodiff=false)),
            reltol=parse_real(T, request, "ode_relative_tolerance"),
            abstol=parse_real(T, request, "ode_absolute_tolerance"),
            ode_maxiters=parse_integer(request, "homogeneous_ode_maxiters"),
            ode_observation_factory=observation_factory,
            ode_solution_observer=observe_ode_solution,
            ode_exception_passthrough=error ->
                error isa ODEResourceLimit || error isa ODESolverFailure,
            factored_homogeneous_rhs_counter=
                factored_homogeneous_rhs_counter,
        )
    end
    emit_factored_solution(propagation.infinity_outer_to_match)
    emit_factored_solution(propagation.horizon_match_to_inner)
    transition_diagnostics = propagation.carrier_transition.diagnostics
    transition_error = max(
        transition_diagnostics.X_reconstruction_error,
        transition_diagnostics.Xrho_reconstruction_error,
    )
    progress_emit("carrier_changed"; payload=Dict(
        "source_carrier" =>
            string(propagation.carrier_transition.source_carrier.kind),
        "target_carrier" =>
            string(propagation.carrier_transition.target_carrier.kind),
        "X_reconstruction_error" =>
            string(transition_diagnostics.X_reconstruction_error),
        "Xrho_reconstruction_error" =>
            string(transition_diagnostics.Xrho_reconstruction_error),
    ))

    basis = Solutions.build_common_horizon_basis(
        preparations.horizon_ingoing.initial_condition,
        preparations.horizon_outgoing.initial_condition,
    )
    coefficients = Solutions.solve_scaled_factored_scattering(
        propagation.horizon_match_to_inner.endpoint,
        propagation.horizon_match_to_inner.carrier,
        basis,
    )
    coefficient_diagnostics = coefficients.diagnostics
    coefficient_diagnostics.extraction_id == SCATTERING_EXTRACTION_ID ||
        error("package scattering extraction identity changed")
    coefficient_diagnostics.column_convention ==
        SCATTERING_COLUMN_CONVENTION_ID ||
        error("package scattering column convention changed")
    coefficient_diagnostics.factored_state_convention ==
        FACTORED_REMAINDER_STATE_CONVENTION_ID ||
        error("package factored scattering state convention changed")
    progress_emit("scattering_coefficients_extracted"; payload=Dict(
        "Cref" => progress_complex(coefficients.Cref),
        "Cinc" => progress_complex(coefficients.Cinc),
        "basis_condition" =>
            string(coefficient_diagnostics.condition_frobenius),
        "basis_backward_error" =>
            string(coefficient_diagnostics.backward_error),
        "matching_reconstruction_residual" => string(
            coefficient_diagnostics.matching_reconstruction_residual
        ),
        "column_norm_1" => string(coefficient_diagnostics.column_norm_1),
        "column_norm_2" => string(coefficient_diagnostics.column_norm_2),
    ))

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
    endpoint_summary = endpoint_conditioning_summary(
        preparations.infinity_outgoing,
        preparations.horizon_ingoing,
        preparations.horizon_outgoing,
    )
    coefficient_scale = max(
        abs(coefficients.Cref), abs(coefficients.Cinc), floatmin(T)
    )
    chart_inputs = Solutions.ScatteringChartErrorInputs{T}(
        coefficient_scale,
        endpoint_summary.maximum_series_evaluation_spread,
        parse_real(T, request, "ode_relative_tolerance"),
    )
    chart = Solutions.evaluate_normalised_horizon_determinant(
        coefficients, reflectivity, chart_inputs
    )
    chart_assessment = chart.assessment
    for (field, expected) in (
        (:homogeneous_representation, HOMOGENEOUS_REPRESENTATION_ID),
        (:branch_convention, BRANCH_CONVENTION_ID),
        (:scattering_coefficient_extraction, SCATTERING_EXTRACTION_ID),
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
        getfield(chart_assessment, field) == expected || error(
            "package horizon chart $(String(field)) identity changed"
        )
    end
    normalised_determinant_abs =
        chart_assessment.normalised_determinant_abs
    normalised_determinant_abs === nothing &&
        error("safe horizon chart omitted its normalised determinant")
    carrier_change_error = max(
        transition_error, coefficient_diagnostics.carrier_change_error
    )
    diagnostics = DeterminantDiagnostics{T}(
        HOMOGENEOUS_REPRESENTATION_ID,
        HORIZON_DETERMINANT_FAMILY_ID,
        true,
        endpoint_summary.maximum_series_digits_lost,
        endpoint_summary.maximum_recurrence_digits_lost,
        endpoint_summary.maximum_series_evaluation_spread,
        endpoint_summary.maximum_last_term_ratio,
        endpoint_summary.minimum_asymptotic_predicted_reliable_digits,
        coefficient_diagnostics.condition_frobenius,
        coefficient_diagnostics.backward_error,
        coefficient_diagnostics.matching_reconstruction_residual,
        endpoint_summary.endpoint_remainders_regular,
        endpoint_summary.maximum_endpoint_reconstruction_error,
        chart_assessment.raw_determinant_abs,
        chart_assessment.raw_determinant_evidence_status,
        normalised_determinant_abs,
        chart_assessment.cref_chart_margin,
        carrier_change_error,
        spectral.contour_deformation.maximum_absolute,
    )
    record_determinant!(context.conditioning, diagnostics)
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
            string(normalised_determinant_abs),
        "cref_chart_margin" =>
            string(chart_assessment.cref_chart_margin),
    ))
    progress_emit("determinant_chart_evaluated"; payload=Dict(
        "determinant_family" => HORIZON_DETERMINANT_FAMILY_ID,
        "determinant_convention" =>
            HORIZON_DETERMINANT_CONVENTION_ID,
        "determinant_normalisation" =>
            HORIZON_DETERMINANT_NORMALISATION_ID,
        "normalised_determinant_abs" =>
            string(normalised_determinant_abs),
    ))
    return DeterminantEvaluation{T}(chart.value, diagnostics)
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
    lower, _ = exterior_support_contract(T, request, a, readout)
    spectral = build_sample_spectral_context(T, request, omega, context)
    lower_contour = build_worker_contour_context(
        T, request, spectral, lower, "Xin"
    )
    readout_contour = build_worker_contour_context(
        T, request, spectral, readout, "Xup"
    )
    required_digits = required_reliable_digits(T, request)
    horizon_ingoing = CF.prepare_factored_horizon_ingoing(
        spectral, lower_contour, required_digits
    )
    infinity_outgoing = CF.prepare_factored_infinity_outgoing(
        spectral, readout_contour, required_digits
    )
    emit_asymptotic_preparation(horizon_ingoing)
    emit_asymptotic_preparation(infinity_outgoing)
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
    emit_factored_solution(xin_propagated)
    emit_factored_solution(xup_propagated)
    xin_match = CF.reconstruct_factored_match_state(
        xin_propagated, spectral, lower_contour
    )
    xup_match = CF.reconstruct_factored_match_state(
        xup_propagated, spectral, readout_contour
    )
    xin_match.radial_derivative_convention ==
        CF.MATCH_RADIAL_DERIVATIVE_CONVENTION_ID ||
        error("package returned an unexpected Xin match derivative convention")
    xup_match.radial_derivative_convention ==
        CF.MATCH_RADIAL_DERIVATIVE_CONVENTION_ID ||
        error("package returned an unexpected Xup match derivative convention")
    perturbed_in = progress_operation("perturbed integration"; payload=Dict(
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
    value = progress_operation("Wronskian") do
        wronskian(
            perturbed_in,
            Complex{T}[xup_match.X, xup_match.dX_drstar],
        )
    end
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

function determinant_progress(
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

function enforce_root_readout_feasibility(request)
    measured_seconds = LAST_DETERMINANT_SECONDS[]
    minimum_remaining_determinant_count = 8
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
        "minimum_remaining_determinant_count" => 8,
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

function validated_frequency_step(
    ::Type{T}, request
) where {T<:AbstractFloat}
    frequency_step = parse_real(T, request, "frequency_step")
    isfinite(frequency_step) && frequency_step > zero(T) &&
        return frequency_step
    throw(numerical_control_failure(
        request,
        "ALGEBRAIC_REPRESENTATION_SINGULAR",
        "finite-difference frequency_step must be positive and finite",
        Dict{String,Any}(
            "reason" => "INVALID_FREQUENCY_STEP",
            "range_status" => "invalid-frequency-step/v1",
            "operation" => "finite-difference-request-policy/v1",
            "axis" => "request-policy",
            "h" => string(frequency_step),
        );
        retryable=false,
    ))
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
    )) || throw(ArgumentError("finite-difference inputs must be finite"))
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
) where {T<:AbstractFloat}
    # Reject malformed stencils before either expensive determinant/ODE sample.
    h = validate_finite_difference_offset(offset; axis=axis)
    d_plus = determinant_progress(
        T,
        request,
        evaluation_context,
        omega + offset,
        amplitude,
        "$(label) +",
        current,
    )
    d_minus = determinant_progress(
        T,
        request,
        evaluation_context,
        omega - offset,
        amplitude,
        "$(label) -",
        current,
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
    ))
    return derivative, diagnostics
end

function bounded_newton(
    ::Type{T},
    request,
    evaluation_context::DeterminantRequestContext{T},
    initial::Complex{T},
    amplitude::Complex{T},
) where {T<:AbstractFloat}
    frequency_step = validated_frequency_step(T, request)
    tolerance = parse_real(T, request, "root_correction_tolerance")
    maximum_iterations = parse_integer(request, "max_newton_iterations")
    value = initial
    best_value = value
    ACTIVE_NEWTON_INDEX[] = 1
    initial_determinant = determinant_progress(
        T,
        request,
        evaluation_context,
        value,
        amplitude,
        "initial best",
        value,
    )
    enforce_root_readout_feasibility(request)
    best_residual = abs(initial_determinant.value)
    best_evaluation = initial_determinant
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
            determinant_progress(
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
        if magnitude < best_residual
            best_value, best_residual = value, magnitude
            best_evaluation = residual
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
            "acceptance_metric" => "newton_correction_estimate_abs",
            "acceptance_threshold" => string(tolerance),
        ))
        h = frequency_step * (one(T) + abs(value))
        derivative, _ = finite_difference_pair(
            T,
            request,
            evaluation_context,
            value,
            amplitude,
            Complex{T}(h, zero(T)),
            "derivative h",
            value;
            axis="real",
        )
        derivative_abs = abs(derivative)
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
        raw_step = residual.value / derivative
        correction_abs = magnitude / derivative_abs
        if correction_abs <= tolerance
            progress_emit("newton_iteration_completed"; context=newton_context, payload=Dict(
                "derivative_abs" => string(derivative_abs),
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
            ))
            return value, magnitude, derivative, true, residual
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
            candidate_residual = determinant_progress(
                T,
                request,
                evaluation_context,
                candidate,
                amplitude,
                "damping $(damping)",
                value,
            )
            candidate_abs = abs(candidate_residual.value)
            decision_context = merge(
                newton_context,
                Dict{String,Any}("candidate_omega" => progress_complex(candidate)),
            )
            progress_emit("damping_decided"; context=decision_context, payload=Dict(
                "damping" => string(damping),
                "candidate_omega" => progress_complex(candidate),
                "candidate_determinant_abs" => string(candidate_abs),
                "accepted" => candidate_abs < magnitude,
            ))
            if candidate_abs < magnitude
                value = candidate
                carried_value = candidate
                carried_residual = candidate_residual
                carried_available = true
                accepted = true
                selected_damping = damping
                resulting_abs = candidate_abs
                if candidate_abs < best_residual
                    best_value, best_residual = candidate, candidate_abs
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
    return best_value, best_residual, nothing, false, best_evaluation
end

numeric_text(value) = string(value)

function final_derivative(
    ::Type{T}, request,
    evaluation_context::DeterminantRequestContext{T},
    root::Complex{T}, amplitude::Complex{T},
    offset::Complex{T}, label::String,
) where {T<:AbstractFloat}
    axis = iszero(imag(offset)) ? "real" : "imaginary"
    derivative, _ = finite_difference_pair(
        T,
        request,
        evaluation_context,
        root,
        amplitude,
        offset,
        label,
        root;
        axis=axis,
    )
    return derivative
end

function solve_once(
    ::Type{T},
    request,
    evaluation_context::DeterminantRequestContext{T},
    initial::Complex{T},
    amplitude::Complex{T},
) where {T<:AbstractFloat}
    root, residual, accepted_derivative, newton_converged, root_evaluation =
        bounded_newton(T, request, evaluation_context, initial, amplitude)
    h = parse_real(T, request, "frequency_step") * (one(T) + abs(root))
    real_offset = Complex{T}(h, zero(T))
    derivative_real_base = isnothing(accepted_derivative) ?
        final_derivative(
            T,
            request,
            evaluation_context,
            root,
            amplitude,
            real_offset,
            "final derivative h",
        ) : accepted_derivative
    derivative_real_half = final_derivative(
        T,
        request,
        evaluation_context,
        root,
        amplitude,
        real_offset / T(2),
        "final derivative h/2",
    )
    derivative_real_double = final_derivative(
        T,
        request,
        evaluation_context,
        root,
        amplitude,
        T(2) * real_offset,
        "final derivative 2h",
    )
    derivative_imaginary = final_derivative(
        T,
        request,
        evaluation_context,
        root,
        amplitude,
        Complex{T}(zero(T), h),
        "final derivative ih",
    )
    fine_step_difference_abs = abs(
        derivative_real_half - derivative_real_base
    )
    coarse_step_difference_abs = abs(
        derivative_real_base - derivative_real_double
    )
    complex_axis_difference_abs = abs(
        derivative_imaginary - derivative_real_half
    )
    real_step_convergent =
        fine_step_difference_abs <= coarse_step_difference_abs
    complex_axis_consistent =
        complex_axis_difference_abs <= coarse_step_difference_abs
    real_step_convergent && complex_axis_consistent ||
        error("determinant frequency derivative estimates do not agree")
    derivative_uncertainty_abs = maximum((
        fine_step_difference_abs,
        abs(derivative_real_double - derivative_real_half),
        complex_axis_difference_abs,
    ))
    derivative_abs = abs(derivative_real_half)
    derivative_lower_bound_abs = derivative_abs - derivative_uncertainty_abs
    isfinite(derivative_abs) && isfinite(derivative_uncertainty_abs) &&
        derivative_lower_bound_abs > zero(T) ||
        error("determinant frequency derivative controls are unusable")
    correction_upper_bound = residual / derivative_lower_bound_abs
    tolerance = parse_real(T, request, "root_correction_tolerance")
    converged = newton_converged && correction_upper_bound <= tolerance
    progress_emit("derivative_control_completed"; payload=Dict(
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
        "derivative_lower_bound_abs" => string(derivative_lower_bound_abs),
        "correction_upper_bound" => string(correction_upper_bound),
        "accepted" => converged,
    ))
    return root, residual, derivative_lower_bound_abs, converged, root_evaluation
end

function solve_phase(
    ::Type{T}, request,
    evaluation_context::DeterminantRequestContext{T},
    phase::String, initial::Complex{T}, amplitude::Complex{T};
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
    LAST_DETERMINANT_PURPOSE[] = nothing
    context = Dict{String,Any}(
        "phase" => phase,
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
            progress_emit("root_seed_selected"; payload=Dict(
                "requested_seed_kind" => requested_seed_kind,
                "seed_kind" => selected_kind,
                "seed_omega" => progress_complex(selected_initial),
                "fallback_used" => used,
                "fallback_reason" => reason,
                "fallback_error_type" => error_type,
            ))
            solve_once(
                T, request, evaluation_context, selected_initial, amplitude
            )
        end
    end

    return progress_scope(context) do
        progress_emit("root_phase_started"; payload=Dict(
            "seed_omega" => progress_complex(initial),
            "current_omega" => progress_complex(initial),
        ))
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
        if actual_kind != "FALLBACK_BACKGROUND" && fallback_initial !== nothing
            if !result[4] || abs(result[1] - fallback_initial) > parse_real(T, request, "branch_enclosure_radius_abs")
                if !result[4]
                    fallback_reason = "PREDICTOR_NEWTON_FAILED"
                else
                    fallback_reason = "PREDICTOR_BRANCH_ESCAPE"
                end
                fallback_used = true
                actual_initial = fallback_initial
                actual_kind = "FALLBACK_BACKGROUND"
                result = solve_with_seed(
                    actual_initial, actual_kind, fallback_used, fallback_reason
                )
            end
        end
        completion_context = Dict{String,Any}(
            "seed_omega" => progress_complex(actual_initial),
            "current_omega" => progress_complex(result[1]),
            "seed_kind" => actual_kind,
            "fallback_used" => fallback_used,
        )
        progress_scope(completion_context) do
            progress_emit("root_phase_completed"; payload=Dict(
                "resulting_omega" => progress_complex(result[1]),
                "resulting_determinant_abs" => string(result[2]),
                "derivative_abs" => string(result[3]),
                "converged" => result[4],
                "elapsed_seconds" => (time_ns() - started) / 1.0e9,
            ))
        end
        result
    end
end

function refined_request(::Type{T}, request, kind::Symbol) where {T<:AbstractFloat}
    output = copy(request)
    if kind == :truncation
        output["endpoint_series_order"] = parse_integer(request, "endpoint_series_order") + 8
    elseif kind == :resolution
        output["ode_relative_tolerance"] = numeric_text(
            parse_real(T, request, "ode_relative_tolerance") / T(2)
        )
        output["ode_absolute_tolerance"] = numeric_text(
            parse_real(T, request, "ode_absolute_tolerance") / T(2)
        )
        output["support_subinterval_count"] =
            2 * parse_integer(request, "support_subinterval_count")
        output["angular_pad"] = parse_integer(request, "angular_pad") + 8
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
        "homogeneous_representation" => HOMOGENEOUS_REPRESENTATION_ID,
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
    root, residual, derivative_abs, primary_converged, root_evaluation =
        solve_phase(
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
        )
    branch_tolerance = parse_real(T, request, "branch_enclosure_radius_abs")
    raw_determinant_abs = root_evaluation.diagnostics.raw_determinant_abs
    raw_determinant_evidence_status =
        root_evaluation.diagnostics.raw_determinant_evidence_status
    horizon = string(required(request, "mechanism_id")) ==
        "horizon-admittance"
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
        branch_valid = abs(root - omega) <= branch_tolerance
        return [
            "schema_version" => 3,
            "status" => "ok",
            "adapter" => "package-owned-julia-gsn-root-readout",
            "request_sha256" => string(required(request, "request_sha256")),
            "precision_digits" => digits,
            "working_precision_bits" => bits,
            "root_omega_re" => numeric_text(real(root)),
            "root_omega_im" => numeric_text(imag(root)),
            "root_residual_abs" => numeric_text(residual),
            "raw_determinant_abs" => raw_determinant_abs === nothing ?
                nothing : numeric_text(raw_determinant_abs),
            "raw_determinant_evidence_status" =>
                raw_determinant_evidence_status,
            "root_derivative_abs" => numeric_text(derivative_abs),
            "root_converged" => false,
            "branch_authentication_contract_version" => 3,
            "root_branch_continuation_valid" => branch_valid,
            "branch_tolerance_abs" => numeric_text(branch_tolerance),
            "root_displacement_abs" => numeric_text(abs(root - omega)),
            "truncation_radius_abs" => nothing,
            "resolution_radius_abs" => nothing,
            "seed_path_radius_abs" => nothing,
            "diagnostic_roots" => Dict{String,Any}(),
            "diagnostics_skipped_reason" => "PRIMARY_NOT_CONVERGED",
            "numerical_conditioning" => numerical_conditioning,
        ]
    end
    truncation_root, truncation_residual, truncation_derivative,
        truncation_converged, _ = solve_phase(
        T,
        refined_request(T, request, :truncation),
        evaluation_context,
        "TRUNCATION",
        root,
        amplitude;
        seed_kind="ACCEPTED_PRIMARY",
    )
    resolution_root, resolution_residual, resolution_derivative,
        resolution_converged, _ = solve_phase(
        T,
        refined_request(T, request, :resolution),
        evaluation_context,
        "RESOLUTION",
        root,
        amplitude;
        seed_kind="ACCEPTED_PRIMARY",
    )
    alternate = omega + Complex{T}(T("0.00025"), T("0.000125")) *
        (one(T) + abs(omega))
    seed_path_root, seed_path_residual, seed_path_derivative,
        seed_path_converged, _ =
        solve_phase(
            T,
            request,
            evaluation_context,
            "SEED-PATH",
            alternate,
            amplitude;
            seed_kind="INDEPENDENT_SEED_PATH",
        )
    branch_valid = abs(root - omega) <= branch_tolerance && all(
        abs(candidate - root) <= branch_tolerance
        for candidate in (truncation_root, resolution_root, seed_path_root)
    )
    converged = all((
        primary_converged,
        truncation_converged,
        resolution_converged,
        seed_path_converged,
        branch_valid,
    ))
    numerical_conditioning = conditioning_response(
        T, request, evaluation_context, digits
    )

    return [
        "schema_version" => 3,
        "status" => "ok",
        "adapter" => "package-owned-julia-gsn-root-readout",
        "request_sha256" => string(required(request, "request_sha256")),
        "precision_digits" => digits,
        "working_precision_bits" => bits,
        "root_omega_re" => numeric_text(real(root)),
        "root_omega_im" => numeric_text(imag(root)),
        "root_residual_abs" => numeric_text(residual),
        "raw_determinant_abs" => raw_determinant_abs === nothing ?
            nothing : numeric_text(raw_determinant_abs),
        "raw_determinant_evidence_status" =>
            raw_determinant_evidence_status,
        "root_derivative_abs" => numeric_text(derivative_abs),
        "root_converged" => converged,
        "branch_authentication_contract_version" => 3,
        "root_branch_continuation_valid" => branch_valid,
        "branch_tolerance_abs" => numeric_text(branch_tolerance),
        "root_displacement_abs" => numeric_text(abs(root - omega)),
        "truncation_radius_abs" => numeric_text(abs(truncation_root - root)),
        "resolution_radius_abs" => numeric_text(abs(resolution_root - root)),
        "seed_path_radius_abs" => numeric_text(abs(seed_path_root - root)),
        "diagnostic_roots" => Dict(
            "truncation" => Dict(
                "root_omega_re" => numeric_text(real(truncation_root)),
                "root_omega_im" => numeric_text(imag(truncation_root)),
                "root_residual_abs" => numeric_text(truncation_residual),
                "root_derivative_abs" => numeric_text(truncation_derivative),
                "root_converged" => truncation_converged,
            ),
            "resolution" => Dict(
                "root_omega_re" => numeric_text(real(resolution_root)),
                "root_omega_im" => numeric_text(imag(resolution_root)),
                "root_residual_abs" => numeric_text(resolution_residual),
                "root_derivative_abs" => numeric_text(resolution_derivative),
                "root_converged" => resolution_converged,
            ),
            "seed-path" => Dict(
                "root_omega_re" => numeric_text(real(seed_path_root)),
                "root_omega_im" => numeric_text(imag(seed_path_root)),
                "root_residual_abs" => numeric_text(seed_path_residual),
                "root_derivative_abs" => numeric_text(seed_path_derivative),
                "root_converged" => seed_path_converged,
            ),
        ),
        "diagnostics_skipped_reason" => nothing,
        "numerical_conditioning" => numerical_conditioning,
    ]
end

function evaluate_request(request)
    parse_integer(request, "schema_version") == 1 || error("unsupported schema_version")
    string(required(request, "operation")) == "root-readout" || error("unsupported operation")
    parse_integer(request, "s") == -2 || error("M02 worker requires spin weight s=-2")
    digits = parse_integer(request, "precision_digits")
    digits in (80, 120) || error("precision_digits must be 80 or 120")
    bits = ceil(Int, digits * log2(10)) + 32
    parse_integer(request, "working_precision_bits") == bits ||
        error("working precision bits do not match decimal precision policy")
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
    return setprecision(BigFloat, bits) do
        result_fields(BigFloat, request, digits, bits)
    end
end

function main()
    if "--probe" in ARGS
        println("M02 Julia precision worker: packages loaded")
        return 0
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
    LAST_DETERMINANT_PURPOSE[] = nothing
    LAST_DETERMINANT_SECONDS[] = 0.0
    LAST_ODE_SNAPSHOT[] = nothing
    document = JSON.parsefile(request_path)
    request = flatten_request(document)
    try
        progress_emit("request_started"; payload=Dict(
            "request_sha256" => string(required(request, "request_sha256")),
            "execution_resource_policy" => resource_policy_identity(request),
        ))
        progress_emit("request_validated"; payload=Dict(
            "request_sha256" => string(required(request, "request_sha256")),
            "execution_resource_policy" => resource_policy_identity(request),
        ))
        result = Dict(evaluate_request(request))
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
                "failure" => failure_details(failure),
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
