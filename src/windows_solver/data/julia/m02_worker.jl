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
    _, lambda = angular_constants(T, s, ell, m, a, omega, seed_A, pad, digits)
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
    xin, _, _ = CF.solve_Xin(
        s, m, a, beta_positive, beta_negative, omega, lambda,
        radius_from_rho, rs_match, rho_in, rho_out;
        initialconditions_order=order,
        dtype=dtype,
        reltol=tolerance,
        abstol=tolerance,
    )
    xup, _, _ = CF.solve_Xup(
        s, m, a, beta_positive, beta_negative, omega, lambda,
        radius_from_rho, rs_match, rho_in, rho_out;
        initialconditions_order=order,
        dtype=dtype,
        reltol=tolerance,
        abstol=tolerance,
    )
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
        return wronskian(horizon, branches.xup)
    end

    lower = parse_real(T, request, "support_lower")
    upper = parse_real(T, request, "support_upper")
    lower > Kerr.r_plus(a) || error("exterior support is not outside the horizon")
    upper < readout || error("exterior support must lie below the readout radius")
    branches = branch_values(T, request, omega, lower)
    perturbed_in = integrate_real_branch(
        T, request, omega, branches.lambda, lower, readout, branches.xin, amplitude
    )
    perturbed_up = integrate_real_branch(
        T, request, omega, branches.lambda, lower, readout, branches.xup, amplitude
    )
    return wronskian(perturbed_in, perturbed_up)
end

function bounded_newton(::Type{T}, request, initial::Complex{T}, amplitude::Complex{T}) where {T<:AbstractFloat}
    frequency_step = parse_real(T, request, "frequency_step")
    tolerance = parse_real(T, request, "root_tolerance")
    maximum_iterations = parse_integer(request, "max_newton_iterations")
    value = initial
    best_value = value
    best_residual = abs(determinant(T, request, value, amplitude))
    for _ in 1:maximum_iterations
        residual = determinant(T, request, value, amplitude)
        magnitude = abs(residual)
        if magnitude < best_residual
            best_value, best_residual = value, magnitude
        end
        magnitude <= tolerance && return value, magnitude, true
        h = frequency_step * (one(T) + abs(value))
        derivative = (
            determinant(T, request, value + h, amplitude) -
            determinant(T, request, value - h, amplitude)
        ) / (T(2) * h)
        iszero(derivative) && break
        step = residual / derivative
        maximum_step = parse(T, "0.006")
        abs(step) > maximum_step && (step *= maximum_step / abs(step))
        accepted = false
        for damping in (
            one(T), parse(T, "0.5"), parse(T, "0.25"), parse(T, "0.125")
        )
            candidate = value - damping * step
            if abs(determinant(T, request, candidate, amplitude)) < magnitude
                value = candidate
                accepted = true
                break
            end
        end
        accepted || (value -= parse(T, "0.125") * step)
    end
    return best_value, best_residual, best_residual <= tolerance
end

numeric_text(value) = string(value)

function solve_once(::Type{T}, request, initial::Complex{T}, amplitude::Complex{T}) where {T<:AbstractFloat}
    root, residual, converged = bounded_newton(T, request, initial, amplitude)
    root_step = parse_real(T, request, "frequency_step") * (one(T) + abs(root))
    root_derivative = (
        determinant(T, request, root + root_step, amplitude) -
        determinant(T, request, root - root_step, amplitude)
    ) / (T(2) * root_step)
    derivative_abs = abs(root_derivative)
    isfinite(derivative_abs) && derivative_abs > zero(T) ||
        error("determinant frequency derivative is unusable")
    return root, residual, derivative_abs, converged
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

    root, residual, derivative_abs, primary_converged =
        solve_once(T, request, omega, amplitude)
    truncation_root, _, _, truncation_converged = solve_once(
        T, refined_request(T, request, :truncation), root, amplitude
    )
    resolution_root, _, _, resolution_converged = solve_once(
        T, refined_request(T, request, :resolution), root, amplitude
    )
    alternate = omega + Complex{T}(T("0.00025"), T("0.000125")) *
        (one(T) + abs(omega))
    seed_path_root, _, _, seed_path_converged =
        solve_once(T, request, alternate, amplitude)
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
        result = Dict(evaluate_request(request))
        mkpath(dirname(response_path))
        write(response_path, JSON.json(result))
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
        @error "M02 Julia precision worker failed" exception=(failure, catch_backtrace())
        return 21
    end
end

exit(main())
