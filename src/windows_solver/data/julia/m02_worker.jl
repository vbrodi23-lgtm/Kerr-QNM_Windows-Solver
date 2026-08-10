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

function progress_operation(operation::Function, name::String; payload=Dict{String,Any}())
    started = time_ns()
    context = Dict{String,Any}("suboperation" => name)
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

required(request, key) = haskey(request, key) ? request[key] : error("missing request key $key")

function flatten_request(document)
    mode = required(document, "mode")
    omega = required(document, "omega")
    angular = required(document, "angular_A")
    amplitude = required(document, "amplitude")
    policy = required(document, "policy")
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
        "mechanism_id" => required(document, "mechanism_id"),
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
        "root_tolerance" => required(policy, "root_tolerance"),
        "max_newton_iterations" => required(policy, "max_newton_iterations"),
    )
    if string(flattened["mechanism_id"]) != "horizon-admittance"
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

function branch_values(::Type{T}, request, omega::Complex{T}, match_radius::T) where {T<:AbstractFloat}
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
    tolerance = min(
        parse_real(T, request, "ode_relative_tolerance"),
        parse_real(T, request, "ode_absolute_tolerance"),
    )
    order = parse_integer(request, "endpoint_series_order")
    rho_in = parse_real(T, request, "rho_in")
    rho_out = parse_real(T, request, "rho_out")
    rs_match = GSN.rstar_from_r(a, match_radius)
    p_h = omega - T(m) * Kerr.omega_horizon(a)
    beta_negative = -angle(p_h)
    beta_positive = -angle(omega)
    sign_negative = CF.determine_sign(p_h)
    sign_positive = CF.determine_sign(omega)
    dtype = Complex{T}
    radius_from_rho = CF.solve_r_from_rho(
        a, beta_negative, beta_positive, rs_match, rho_in, rho_out;
        sign_neg=sign_negative,
        sign_pos=sign_positive,
        dtype=dtype,
        reltol=tolerance,
        abstol=tolerance,
    )
    xin, _, _ = progress_operation("Xin") do
        CF.solve_Xin(
            s, m, a, beta_positive, beta_negative, omega, lambda,
            radius_from_rho, rs_match, rho_in, rho_out;
            initialconditions_order=order,
            dtype=dtype,
            reltol=tolerance,
            abstol=tolerance,
        )
    end
    xup, _, _ = progress_operation("Xup") do
        CF.solve_Xup(
            s, m, a, beta_positive, beta_negative, omega, lambda,
            radius_from_rho, rs_match, rho_in, rho_out;
            initialconditions_order=order,
            dtype=dtype,
            reltol=tolerance,
            abstol=tolerance,
        )
    end
    xin_match = xin(zero(T))
    xup_match = xup(zero(T))
    Cref, Cinc = CF.CrefCinc_SN_from_Xup(
        s, m, a, beta_negative, omega, lambda, xup,
        radius_from_rho, rs_match, rho_in;
        order=order,
        dtype=dtype,
    )
    iszero(Cinc) && error("outgoing-horizon normalization has zero Cinc")
    xout_match = (xup_match .- Cref .* xin_match) ./ Cinc
    return (
        xin=Complex{T}[xin_match[1], xin_match[2]],
        xup=Complex{T}[xup_match[1], xup_match[2]],
        xout=Complex{T}[xout_match[1], xout_match[2]],
        lambda=lambda,
    )
end

wronskian(left, right) = left[1] * right[2] - left[2] * right[1]

function compact_profile(radius, centre, half_width, amplitude)
    scaled = (radius - centre) / half_width
    abs(scaled) >= one(scaled) && return zero(amplitude)
    return amplitude * exp(one(scaled) - inv(one(scaled) - scaled^2))
end

function integrate_real_branch(::Type{T}, request, omega::Complex{T}, lambda::Complex{T},
                               start_radius::T, stop_radius::T, seed,
                               amplitude::Complex{T}) where {T<:AbstractFloat}
    s = parse_integer(request, "s")
    m = parse_integer(request, "m")
    a = parse_real(T, request, "spin")
    centre = parse_real(T, request, "support_centre")
    half_width = parse_real(T, request, "support_half_width")
    relative_tolerance = parse_real(T, request, "ode_relative_tolerance")
    absolute_tolerance = parse_real(T, request, "ode_absolute_tolerance")
    support_count = parse_integer(request, "support_subinterval_count")
    dtmax = min(T(0.2), T(2) * half_width / T(support_count))

    function equation(state, _, radius)
        w = Kerr.Delta(a, radius) / (radius^2 + a^2)
        F = Potentials.sF(s, m, a, omega, lambda, radius)
        U = Potentials.sU(s, m, a, omega, lambda, radius)
        profile = compact_profile(radius, centre, half_width, amplitude)
        X, Xstar = state
        return Complex{T}[
            Xstar / w,
            (F * Xstar + U * X) / w - w * profile * X,
        ]
    end

    initial = Complex{T}[seed[1], seed[2]]
    problem = ODEProblem(equation, initial, (start_radius, stop_radius))
    solution = solve(
        problem,
        AutoVern9(Rosenbrock23(autodiff=false));
        reltol=relative_tolerance,
        abstol=absolute_tolerance,
        dtmax=dtmax,
        maxiters=10^7,
    )
    SciMLBase.successful_retcode(solution) || error("real-radius GSN integration failed: $(solution.retcode)")
    final = solution(stop_radius)
    return Complex{T}[final[1], final[2]]
end

function determinant(::Type{T}, request, omega::Complex{T}, amplitude::Complex{T}) where {T<:AbstractFloat}
    mechanism = string(required(request, "mechanism_id"))
    readout = parse_real(T, request, "readout_radius")
    a = parse_real(T, request, "spin")
    m = parse_integer(request, "m")

    if mechanism == "horizon-admittance"
        branches = branch_values(T, request, omega, readout)
        p_h = omega - T(m) * Kerr.omega_horizon(a)
        denominator = T(2) * im * p_h - amplitude
        iszero(denominator) && error("zero horizon chart denominator")
        reflectivity = amplitude / denominator
        horizon = branches.xin .+ reflectivity .* branches.xout
        return progress_operation("Wronskian") do
            wronskian(horizon, branches.xup)
        end
    end

    lower = parse_real(T, request, "support_lower")
    upper = parse_real(T, request, "support_upper")
    lower > Kerr.r_plus(a) || error("exterior support is not outside the horizon")
    upper < readout || error("exterior support must lie below the readout radius")
    branches = branch_values(T, request, omega, lower)
    perturbed_in = progress_operation("perturbed integration"; payload=Dict(
        "branch" => "Xin",
    )) do
        integrate_real_branch(
            T, request, omega, branches.lambda, lower, readout, branches.xin, amplitude
        )
    end
    perturbed_up = progress_operation("perturbed integration"; payload=Dict(
        "branch" => "Xup",
    )) do
        integrate_real_branch(
            T, request, omega, branches.lambda, lower, readout, branches.xup, amplitude
        )
    end
    return progress_operation("Wronskian") do
        wronskian(perturbed_in, perturbed_up)
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

function bounded_newton(::Type{T}, request, initial::Complex{T}, amplitude::Complex{T}) where {T<:AbstractFloat}
    frequency_step = parse_real(T, request, "frequency_step")
    tolerance = parse_real(T, request, "root_tolerance")
    maximum_iterations = parse_integer(request, "max_newton_iterations")
    value = initial
    best_value = value
    best_residual = abs(determinant_progress(
        T, request, value, amplitude, "initial best", value
    ))
    for iteration in 1:maximum_iterations
        iteration_started = time_ns()
        residual = determinant_progress(T, request, value, amplitude, "residual", value)
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
            "acceptance_threshold" => string(tolerance),
        ))
        if magnitude <= tolerance
            progress_emit("newton_iteration_completed"; context=newton_context, payload=Dict(
                "derivative_abs" => nothing,
                "raw_step" => nothing,
                "applied_step" => nothing,
                "step_abs" => "0",
                "clipped" => false,
                "damping" => "0",
                "accepted" => true,
                "resulting_omega" => progress_complex(value),
                "resulting_determinant_abs" => string(magnitude),
                "elapsed_seconds" => (time_ns() - iteration_started) / 1.0e9,
            ))
            return value, magnitude, true
        end
        h = frequency_step * (one(T) + abs(value))
        derivative = (
            determinant_progress(T, request, value + h, amplitude, "derivative +h", value) -
            determinant_progress(T, request, value - h, amplitude, "derivative -h", value)
        ) / (T(2) * h)
        derivative_abs = abs(derivative)
        if iszero(derivative)
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
                accepted = true
                selected_damping = damping
                resulting_abs = candidate_abs
                break
            end
        end
        if !accepted
            value -= parse(T, "0.125") * step
            resulting_abs = candidate_abs
        end
        applied_step = selected_damping * step
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
    end
    return best_value, best_residual, best_residual <= tolerance
end

numeric_text(value) = string(value)

function solve_once(::Type{T}, request, initial::Complex{T}, amplitude::Complex{T}) where {T<:AbstractFloat}
    root, residual, converged = bounded_newton(T, request, initial, amplitude)
    root_step = parse_real(T, request, "frequency_step") * (one(T) + abs(root))
    root_derivative = (
        determinant_progress(T, request, root + root_step, amplitude, "final derivative +h", root) -
        determinant_progress(T, request, root - root_step, amplitude, "final derivative -h", root)
    ) / (T(2) * root_step)
    derivative_abs = abs(root_derivative)
    isfinite(derivative_abs) && derivative_abs > zero(T) ||
        error("determinant frequency derivative is unusable")
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
            if !result[4] || abs(result[1] - fallback_initial) > T("0.005")
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
           abs(predictor - omega) <= T("0.005")
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
    truncation_root, _, _, truncation_converged = solve_phase(
        T, refined_request(T, request, :truncation), "TRUNCATION", root, amplitude;
        seed_kind="ACCEPTED_PRIMARY",
    )
    resolution_root, _, _, resolution_converged = solve_phase(
        T, refined_request(T, request, :resolution), "RESOLUTION", root, amplitude;
        seed_kind="ACCEPTED_PRIMARY",
    )
    alternate = omega + Complex{T}(T("0.00025"), T("0.000125")) *
        (one(T) + abs(omega))
    seed_path_root, _, _, seed_path_converged =
        solve_phase(
            T, request, "SEED-PATH", alternate, amplitude;
            seed_kind="INDEPENDENT_SEED_PATH",
        )
    branch_tolerance = T("0.005")
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
        "truncation_radius_abs" => numeric_text(abs(truncation_root - root)),
        "resolution_radius_abs" => numeric_text(abs(resolution_root - root)),
        "seed_path_radius_abs" => numeric_text(abs(seed_path_root - root)),
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
        result = Dict(
            "schema_version" => 1,
            "status" => "error",
            "error_type" => string(typeof(failure)),
            "message" => sprint(showerror, failure),
        )
        mkpath(dirname(response_path))
        write(response_path, JSON.json(result))
        progress_emit("request_failed"; payload=Dict(
            "error_type" => string(typeof(failure)),
            "message" => sprint(showerror, failure),
        ))
        @error "M02 Julia precision worker failed" exception=(failure, catch_backtrace())
        return 21
    end
end

exit(main())
