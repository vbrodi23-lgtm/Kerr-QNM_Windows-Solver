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
const PROGRESS_PREFIX = "@@KERR_QNM_PROGRESS@@"
const PROGRESS_SCHEMA = "windows-solver.progress/1"
const ACTIVE_PROGRESS_CONTEXT = Ref(Dict{String,Any}())
const ODE_PROGRESS_INTERVAL_SECONDS = 15.0
const ODE_ALGORITHM_CONFIGURED = "AutoVern9(Rosenbrock23(autodiff=false))"
const NEXT_ODE_SOLVE_ID = Ref(0)
const ALLOWED_MECHANISMS = Set([
    "horizon-admittance",
    "exterior-fixed-r3",
    "exterior-light-ring",
    "exterior-throat-kappa",
    "exterior-alpha-zero",
    "exterior-alpha-half",
    "exterior-alpha-one",
])

abstract type ODEControlFailure <: Exception end

struct ODEResourceLimit <: ODEControlFailure
    message::String
    details::Dict{String,Any}
end

struct ODESolverFailure <: ODEControlFailure
    message::String
    details::Dict{String,Any}
end

Base.showerror(io::IO, failure::ODEResourceLimit) = print(io, failure.message)
Base.showerror(io::IO, failure::ODESolverFailure) = print(io, failure.message)
failure_details(failure::ODEControlFailure) = failure.details

mutable struct ODEObservationState
    solve_id::Int
    leg::String
    t_start
    t_end
    started_ns::UInt64
    next_report_ns::UInt64
    last_accepted_step
    minimum_accepted_step
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
    ))
end

function ode_observation_factory(leg, tspan, _algorithm)
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
    )
    progress_emit("ode_solve_started"; payload=ode_base_payload(state))
    progress_active() || return nothing, ODEObservationCallback(state)

    condition = (_u, _t, _integrator) -> true
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
            if sampled_at >= state.next_report_ns
                state.next_report_ns = sampled_at + interval
                proposed_step = try
                    abs(SciMLBase.get_proposed_dt(integrator))
                catch
                    nothing
                end
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

    if solution.retcode === SciMLBase.ReturnCode.MaxIters
        details = Dict{String,Any}(
            "failure_code" => "ODE_RESOURCE_LIMIT",
            "failure_class" => "CONTROL",
            "limit_kind" => "ode_solver_iterations",
            "ode_snapshot" => snapshot,
        )
        progress_emit("ode_resource_limit"; payload=merge(snapshot, Dict{String,Any}(
            "failure_code" => "ODE_RESOURCE_LIMIT",
            "failure_class" => "CONTROL",
            "limit_kind" => "ode_solver_iterations",
        )))
        throw(ODEResourceLimit(
            "$(state.leg) reached the existing ODE solver iteration limit",
            details,
        ))
    end

    if !SciMLBase.successful_retcode(solution) || !endpoint_reached
        details = Dict{String,Any}(
            "failure_code" => "ODE_SOLVER_FAILURE",
            "failure_class" => "CONTROL",
            "ode_snapshot" => snapshot,
        )
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
    mechanism = string(required(document, "mechanism_id"))
    mechanism in ALLOWED_MECHANISMS ||
        error("unsupported mechanism_id $(repr(mechanism))")
    flattened = Dict{String,Any}(
        "schema_version" => required(document, "schema_version"),
        "operation" => required(document, "operation"),
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
    )
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

function homogeneous_rho_rhs!(du, state, parameters, rho)
    radius = parameters.radius_from_rho(rho)
    F = parameters.sign * exp(im * parameters.beta) * Potentials.sF(
        parameters.s,
        parameters.m,
        parameters.a,
        parameters.omega,
        parameters.lambda,
        radius,
    )
    U = exp(T(2) * im * parameters.beta) * Potentials.sU(
        parameters.s,
        parameters.m,
        parameters.a,
        parameters.omega,
        parameters.lambda,
        radius,
    )
    du[1] = state[2]
    du[2] = F * state[2] + U * state[1]
    return nothing
end

function solve_homogeneous_endpoint(
    ::Type{T},
    request,
    omega::Complex{T},
    lambda::Complex{T},
    radius_from_rho,
    beta,
    sign,
    start_rho::T,
    stop_rho::T,
    seed;
    ode_leg::String,
) where {T<:AbstractFloat}
    parameters = (
        s=parse_integer(request, "s"),
        m=parse_integer(request, "m"),
        a=parse_real(T, request, "spin"),
        omega=omega,
        lambda=lambda,
        radius_from_rho=radius_from_rho,
        beta=beta,
        sign=sign,
    )
    initial = Complex{T}[seed[1], seed[2]]
    problem = ODEProblem(
        homogeneous_rho_rhs!,
        initial,
        (start_rho, stop_rho),
        parameters,
    )
    algorithm = AutoVern9(Rosenbrock23(autodiff=false))
    observation_callback, observation = ode_observation_factory(
        ode_leg, (start_rho, stop_rho), algorithm
    )
    solve_arguments = observation_callback === nothing ?
        NamedTuple() : (; callback=observation_callback)
    solution = solve(
        problem,
        algorithm;
        reltol=parse_real(T, request, "ode_relative_tolerance"),
        abstol=parse_real(T, request, "ode_absolute_tolerance"),
        maxiters=Inf,
        tstops=[stop_rho],
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

function solve_xin_at_match(
    ::Type{T},
    request,
    omega::Complex{T},
    lambda::Complex{T},
    radius_from_rho,
    beta_negative,
    sign_negative,
    rs_match,
    rho_in::T,
) where {T<:AbstractFloat}
    seed = CF.Xin_initialconditions(
        parse_integer(request, "s"),
        parse_integer(request, "m"),
        parse_real(T, request, "spin"),
        beta_negative,
        omega,
        lambda,
        radius_from_rho,
        rs_match,
        rho_in;
        order=parse_integer(request, "endpoint_series_order"),
        dtype=Complex{T},
    )
    raw = solve_homogeneous_endpoint(
        T,
        request,
        omega,
        lambda,
        radius_from_rho,
        beta_negative,
        sign_negative,
        rho_in,
        zero(T),
        seed;
        ode_leg="Xin_inner_to_match",
    )
    return Complex{T}[
        raw[1],
        sign_negative * exp(-im * beta_negative) * raw[2],
    ]
end

function xup_outer_to_match_raw(
    ::Type{T},
    request,
    omega::Complex{T},
    lambda::Complex{T},
    radius_from_rho,
    beta_positive,
    sign_positive,
    rs_match,
    rho_out::T,
) where {T<:AbstractFloat}
    seed = CF.Xup_initialconditions(
        parse_integer(request, "s"),
        parse_integer(request, "m"),
        parse_real(T, request, "spin"),
        beta_positive,
        omega,
        lambda,
        radius_from_rho,
        rs_match,
        rho_out;
        order=parse_integer(request, "endpoint_series_order"),
        dtype=Complex{T},
    )
    return solve_homogeneous_endpoint(
        T,
        request,
        omega,
        lambda,
        radius_from_rho,
        beta_positive,
        sign_positive,
        rho_out,
        zero(T),
        seed;
        ode_leg="Xup_outer_to_match",
    )
end

function solve_xup_at_match(
    ::Type{T},
    request,
    omega::Complex{T},
    lambda::Complex{T},
    radius_from_rho,
    beta_positive,
    sign_positive,
    rs_match,
    rho_out::T,
) where {T<:AbstractFloat}
    raw = xup_outer_to_match_raw(
        T,
        request,
        omega,
        lambda,
        radius_from_rho,
        beta_positive,
        sign_positive,
        rs_match,
        rho_out,
    )
    return Complex{T}[
        raw[1],
        sign_positive * exp(-im * beta_positive) * raw[2],
    ]
end

function solve_xup_scattering_coefficients(
    ::Type{T},
    request,
    omega::Complex{T},
    lambda::Complex{T},
    radius_from_rho,
    beta_negative,
    beta_positive,
    sign_negative,
    sign_positive,
    rs_match,
    rho_in::T,
    rho_out::T,
) where {T<:AbstractFloat}
    outer_at_match = xup_outer_to_match_raw(
        T,
        request,
        omega,
        lambda,
        radius_from_rho,
        beta_positive,
        sign_positive,
        rs_match,
        rho_out,
    )
    inner_seed = Complex{T}[
        outer_at_match[1],
        sign_negative * exp(im * beta_negative) *
            sign_positive * exp(-im * beta_positive) *
            outer_at_match[2],
    ]
    raw_inner = solve_homogeneous_endpoint(
        T,
        request,
        omega,
        lambda,
        radius_from_rho,
        beta_negative,
        sign_negative,
        zero(T),
        rho_in,
        inner_seed;
        ode_leg="Xup_match_to_inner",
    )
    xup_inner = Complex{T}[
        raw_inner[1],
        sign_negative * exp(-im * beta_negative) * raw_inner[2],
    ]
    xup_endpoint(_rho) = xup_inner
    return CF.CrefCinc_SN_from_Xup(
        parse_integer(request, "s"),
        parse_integer(request, "m"),
        parse_real(T, request, "spin"),
        beta_negative,
        omega,
        lambda,
        xup_endpoint,
        radius_from_rho,
        rs_match,
        rho_in;
        order=parse_integer(request, "endpoint_series_order"),
        dtype=Complex{T},
    )
end

function branch_values(
    ::Type{T}, request, omega::Complex{T}, match_radius::T, branch::Symbol
) where {T<:AbstractFloat}
    branch in (:xin, :xup, :xup_scattering) ||
        error("unsupported homogeneous branch request")
    s = parse_integer(request, "s")
    ell = parse_integer(request, "ell")
    m = parse_integer(request, "m")
    digits = parse_integer(request, "precision_digits")
    pad = parse_integer(request, "angular_pad")
    a = parse_real(T, request, "spin")
    seed_A = parse_complex(T, request, "angular_A_re", "angular_A_im")
    _, lambda = progress_operation("angular") do
        angular_constants(T, s, ell, m, a, omega, seed_A, pad, digits)
    end
    relative_tolerance = parse_real(T, request, "ode_relative_tolerance")
    absolute_tolerance = parse_real(T, request, "ode_absolute_tolerance")
    rho_in = parse_real(T, request, "rho_in")
    rho_out = parse_real(T, request, "rho_out")
    rs_match = GSN.rstar_from_r(a, match_radius)
    p_h = omega - T(m) * Kerr.omega_horizon(a)
    beta_negative = -angle(p_h)
    beta_positive = -angle(omega)
    sign_negative = CF.determine_sign(p_h)
    sign_positive = CF.determine_sign(omega)
    dtype = Complex{T}
    radius_from_rho = progress_operation("r-from-rho") do
        CF.solve_r_from_rho(
            a, beta_negative, beta_positive, rs_match, rho_in, rho_out;
            sign_neg=sign_negative,
            sign_pos=sign_positive,
            dtype=dtype,
            reltol=relative_tolerance,
            abstol=absolute_tolerance,
            ode_observation_factory=ode_observation_factory,
            ode_solution_observer=observe_ode_solution,
        )
    end

    xin_match = nothing
    xup_match = nothing
    Cref = nothing
    Cinc = nothing
    if branch == :xin
        xin_match = progress_operation("Xin") do
            solve_xin_at_match(
                T,
                request,
                omega,
                lambda,
                radius_from_rho,
                beta_negative,
                sign_negative,
                rs_match,
                rho_in,
            )
        end
    elseif branch == :xup
        xup_match = progress_operation("Xup") do
            solve_xup_at_match(
                T,
                request,
                omega,
                lambda,
                radius_from_rho,
                beta_positive,
                sign_positive,
                rs_match,
                rho_out,
            )
        end
    else
        Cref, Cinc = progress_operation("Xup") do
            solve_xup_scattering_coefficients(
                T,
                request,
                omega,
                lambda,
                radius_from_rho,
                beta_negative,
                beta_positive,
                sign_negative,
                sign_positive,
                rs_match,
                rho_in,
                rho_out,
            )
        end
    end

    return (
        xin=xin_match,
        xup=xup_match,
        Cref=Cref,
        Cinc=Cinc,
        lambda=lambda,
    )
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
        ode_leg, (start_radius, stop_radius), algorithm
    )
    solve_arguments = observation_callback === nothing ?
        NamedTuple() : (; callback=observation_callback)
    solution = solve(
        problem,
        algorithm;
        reltol=parse_real(T, request, "ode_relative_tolerance"),
        abstol=parse_real(T, request, "ode_absolute_tolerance"),
        dtmax=dtmax,
        maxiters=10^7,
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

function determinant(::Type{T}, request, omega::Complex{T}, amplitude::Complex{T}) where {T<:AbstractFloat}
    mechanism = string(required(request, "mechanism_id"))
    mechanism in ALLOWED_MECHANISMS ||
        error("unsupported mechanism_id $(repr(mechanism))")
    readout = parse_real(T, request, "readout_radius")
    a = parse_real(T, request, "spin")
    m = parse_integer(request, "m")

    if mechanism == "horizon-admittance"
        branches = branch_values(T, request, omega, readout, :xup_scattering)
        p_h = omega - T(m) * Kerr.omega_horizon(a)
        denominator = T(2) * im * p_h - amplitude
        iszero(denominator) && error("zero horizon chart denominator")
        reflectivity = amplitude / denominator
        chart_ratio = iszero(p_h) ? T(Inf) : abs(amplitude) / (T(2) * abs(p_h))
        progress_emit("horizon_chart_evaluated"; payload=Dict(
            "Cinc_abs" => string(abs(branches.Cinc)),
            "Cref_abs" => string(abs(branches.Cref)),
            "horizon_frequency_abs" => string(abs(p_h)),
            "reflectivity_abs" => string(abs(reflectivity)),
            "chart_denominator_abs" => string(abs(denominator)),
            "chart_ratio" => string(chart_ratio),
        ))
        return branches.Cinc - reflectivity * branches.Cref
    end

    lower, _ = exterior_support_contract(T, request, a, readout)
    lower_branches = branch_values(T, request, omega, lower, :xin)
    readout_branches = branch_values(T, request, omega, readout, :xup)
    perturbed_in = progress_operation("perturbed integration"; payload=Dict(
        "branch" => "Xin",
    )) do
        integrate_real_branch(
            T,
            request,
            omega,
            lower_branches.lambda,
            lower,
            readout,
            lower_branches.xin,
            amplitude;
            ode_leg="perturbed_Xin",
        )
    end
    return progress_operation("Wronskian") do
        wronskian(perturbed_in, readout_branches.xup)
    end
end

function determinant_progress(
    ::Type{T}, request, omega::Complex{T}, amplitude::Complex{T},
    purpose::String, current::Complex{T},
) where {T<:AbstractFloat}
    started = time_ns()
    context = Dict{String,Any}(
        "determinant_purpose" => purpose,
        "current_omega" => progress_complex(current),
        "candidate_omega" => progress_complex(omega),
    )
    return progress_scope(context) do
        progress_emit("determinant_started"; context=context, payload=Dict(
            "purpose" => purpose,
            "omega" => progress_complex(omega),
        ))
        value = determinant(T, request, omega, amplitude)
        progress_emit("determinant_completed"; context=context, payload=Dict(
            "purpose" => purpose,
            "omega" => progress_complex(omega),
            "determinant_real" => string(real(value)),
            "determinant_imag" => string(imag(value)),
            "determinant_abs" => string(abs(value)),
            "elapsed_seconds" => (time_ns() - started) / 1.0e9,
        ))
        return value
    end
end

function bounded_newton(::Type{T}, request, initial::Complex{T}, amplitude::Complex{T}) where {T<:AbstractFloat}
    frequency_step = parse_real(T, request, "frequency_step")
    tolerance = parse_real(T, request, "root_correction_tolerance")
    maximum_iterations = parse_integer(request, "max_newton_iterations")
    value = initial
    best_value = value
    initial_determinant = determinant_progress(
        T, request, value, amplitude, "initial best", value
    )
    best_residual = abs(initial_determinant)
    # The first iteration evaluates the determinant at the initial frequency,
    # which is exactly the value just computed above.  The determinant is a
    # deterministic function of the frequency and the request controls, so carry
    # that result into the first iteration instead of repeating the solve; at
    # promoted precision one determinant is several radial integrations.
    carried_value = value
    carried_residual = initial_determinant
    carried_available = true
    for iteration in 1:maximum_iterations
        iteration_started = time_ns()
        residual = if carried_available && carried_value == value
            carried_available = false
            carried_residual
        else
            determinant_progress(T, request, value, amplitude, "residual", value)
        end
        magnitude = abs(residual)
        if magnitude < best_residual
            best_value, best_residual = value, magnitude
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
        derivative = (
            determinant_progress(T, request, value + h, amplitude, "derivative +h", value) -
            determinant_progress(T, request, value - h, amplitude, "derivative -h", value)
        ) / (T(2) * h)
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
        raw_step = residual / derivative
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
            return value, magnitude, derivative, true
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
                T, request, candidate, amplitude, "damping $(damping)", value
            )
            candidate_abs = abs(candidate_residual)
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
    return best_value, best_residual, nothing, false
end

numeric_text(value) = string(value)

function final_derivative(
    ::Type{T}, request, root::Complex{T}, amplitude::Complex{T},
    offset::Complex{T}, label::String,
) where {T<:AbstractFloat}
    return (
        determinant_progress(
            T, request, root + offset, amplitude, "$(label) +", root
        ) -
        determinant_progress(
            T, request, root - offset, amplitude, "$(label) -", root
        )
    ) / (T(2) * offset)
end

function solve_once(::Type{T}, request, initial::Complex{T}, amplitude::Complex{T}) where {T<:AbstractFloat}
    root, residual, accepted_derivative, newton_converged =
        bounded_newton(T, request, initial, amplitude)
    h = parse_real(T, request, "frequency_step") * (one(T) + abs(root))
    real_offset = Complex{T}(h, zero(T))
    derivative_real_base = isnothing(accepted_derivative) ?
        final_derivative(
            T, request, root, amplitude, real_offset, "final derivative h"
        ) : accepted_derivative
    derivative_real_half = final_derivative(
        T, request, root, amplitude, real_offset / T(2), "final derivative h/2"
    )
    derivative_real_double = final_derivative(
        T, request, root, amplitude, T(2) * real_offset, "final derivative 2h"
    )
    derivative_imaginary = final_derivative(
        T,
        request,
        root,
        amplitude,
        Complex{T}(zero(T), h),
        "final derivative ih",
    )
    derivative_uncertainty_abs = maximum((
        abs(derivative_real_base - derivative_real_half),
        abs(derivative_real_double - derivative_real_half),
        abs(derivative_imaginary - derivative_real_half),
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
        "derivative_uncertainty_abs" => string(derivative_uncertainty_abs),
        "derivative_lower_bound_abs" => string(derivative_lower_bound_abs),
        "correction_upper_bound" => string(correction_upper_bound),
        "accepted" => converged,
    ))
    return root, residual, derivative_abs, converged
end

function solve_phase(
    ::Type{T}, request, phase::String, initial::Complex{T}, amplitude::Complex{T};
    seed_kind="AUTHENTICATED_BACKGROUND",
    requested_seed_kind=seed_kind,
    fallback_initial=nothing,
    fallback_used=false,
    fallback_reason=nothing,
) where {T<:AbstractFloat}
    started = time_ns()
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
            solve_once(T, request, selected_initial, amplitude)
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

function result_fields(::Type{T}, request, digits::Int, bits::Int) where {T<:AbstractFloat}
    omega = parse_complex(T, request, "omega_re", "omega_im")
    amplitude = parse_complex(T, request, "amplitude_re", "amplitude_im")

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
    root, residual, derivative_abs, primary_converged =
        solve_phase(
            T, request, "PRIMARY", primary_initial, amplitude;
            seed_kind=primary_seed_kind,
            requested_seed_kind=primary_requested_seed_kind,
            fallback_initial=fallback_initial,
            fallback_used=primary_fallback_used,
            fallback_reason=primary_fallback_reason,
        )
    truncation_root, truncation_residual, truncation_derivative, truncation_converged = solve_phase(
        T, refined_request(T, request, :truncation), "TRUNCATION", root, amplitude;
        seed_kind="ACCEPTED_PRIMARY",
    )
    resolution_root, resolution_residual, resolution_derivative, resolution_converged = solve_phase(
        T, refined_request(T, request, :resolution), "RESOLUTION", root, amplitude;
        seed_kind="ACCEPTED_PRIMARY",
    )
    alternate = omega + Complex{T}(T("0.00025"), T("0.000125")) *
        (one(T) + abs(omega))
    seed_path_root, seed_path_residual, seed_path_derivative, seed_path_converged =
        solve_phase(
            T, request, "SEED-PATH", alternate, amplitude;
            seed_kind="INDEPENDENT_SEED_PATH",
        )
    branch_tolerance = parse_real(T, request, "branch_enclosure_radius_abs")
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

    return [
        "schema_version" => 1,
        "status" => "ok",
        "adapter" => "package-owned-julia-gsn-root-readout",
        "request_sha256" => string(required(request, "request_sha256")),
        "precision_digits" => digits,
        "working_precision_bits" => bits,
        "root_omega_re" => numeric_text(real(root)),
        "root_omega_im" => numeric_text(imag(root)),
        "root_residual_abs" => numeric_text(residual),
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
    document = JSON.parsefile(request_path)
    request = flatten_request(document)
    try
        progress_emit("request_started"; payload=Dict(
            "request_sha256" => string(required(request, "request_sha256")),
        ))
        progress_emit("request_validated"; payload=Dict(
            "request_sha256" => string(required(request, "request_sha256")),
        ))
        result = Dict(evaluate_request(request))
        mkpath(dirname(response_path))
        write(response_path, JSON.json(result))
        progress_emit("request_completed"; payload=Dict(
            "request_sha256" => string(required(request, "request_sha256")),
        ))
        return 0
    catch failure
        result = if failure isa ODEControlFailure
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
        if failure isa ODEControlFailure
            request_failure["failure"] = failure_details(failure)
        end
        progress_emit("request_failed"; payload=request_failure)
        @error "M02 Julia precision worker failed" exception=(failure, catch_backtrace())
        return 21
    end
end

exit(main())
