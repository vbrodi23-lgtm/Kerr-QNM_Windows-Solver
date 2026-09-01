module M03Core

using LinearAlgebra
using DifferentialEquations
using SciMLBase
using GeneralizedSasakiNakamura

const GSN = GeneralizedSasakiNakamura
const CF = GeneralizedSasakiNakamura.ComplexFrequencies
const Kerr = GeneralizedSasakiNakamura.Kerr
const Potentials = GeneralizedSasakiNakamura.Potentials

const CORE_SCHEMA = "windows-solver.m03-core/1"
const CORE_VERSION = "m03-core-v1"

# ---------------------------------------------------------------------------
# Typed inputs
# ---------------------------------------------------------------------------

struct RootSeed{T<:AbstractFloat}
    node_identity_sha256::String
    root_identity_sha256::String
    background_identity_sha256::String
    handoff_identity_sha256::String

    s::Int
    ell::Int
    m::Int
    n::Int
    branch_identity::String
    chain_position::Int

    spin_text::String
    spin::T

    omega_real_text::String
    omega_imag_text::String
    omega::Complex{T}

    angular_A_real_text::String
    angular_A_imag_text::String
    angular_A::Complex{T}

    precision_tier::String
end

struct DomegaStencil{T<:AbstractFloat}
    request_sha256::String
    root_identity_sha256::String
    determinant_family::String
    determinant_convention::String
    determinant_normalisation::String
    scientific_operation_identity::String

    source_precision_tier::String
    source_precision_bits::Int

    h::T
    D0::Complex{T}
    D_plus_h::Complex{T}
    D_minus_h::Complex{T}
    D_plus_half_h::Complex{T}
    D_minus_half_h::Complex{T}

    coarse_derivative::Complex{T}
    fine_derivative::Complex{T}
    disagreement_abs::T
end

struct NumericalPolicy{T<:AbstractFloat}
    policy_identity_sha256::String
    precision_tier::String
    working_precision_bits::Int

    readout_radius::T
    rho_inner::T
    rho_outer::T
    endpoint_order::Int
    angular_pad::Int
    ode_reltol::T
    ode_abstol::T
    angular_derivative_step::T
    frequency_audit_step::T
    quadrature_panels::Int

    angular_right_residual_max::T
    angular_transpose_residual_max::T
    angular_symmetry_residual_max::T
    angular_c_product_min::T
    lambda_derivative_disagreement_max::T

    radial_wronskian_max::T
    matching_right_null_max::T
    matching_left_null_max::T
    transpose_endpoint_residual_max::T
    transpose_readout_residual_max::T
    dual_projective_disagreement_max::T
    bilinear_conservation_max::T

    domega_stencil_relative_disagreement_max::T
    local_domega_to_m02_relative_max::T
    contour_to_readout_denominator_relative_max::T
    bridge_closure_relative_max::T

    residue_rescaling_relative_max::T
    projector_rescaling_relative_max::T
    projector_idempotence_relative_max::T
    projector_action_relative_max::T
    local_resolvent_residue_relative_max::T
    local_resolvent_projector_relative_max::T
    adjugate_residue_relative_max::T

    retained_rho_grid::Vector{T}
end

struct RetainedPredecessor{T<:AbstractFloat}
    node_identity_sha256::String
    root_identity_sha256::String
    branch_identity::String
    chain_position::Int
    angular_right::Vector{Complex{T}}
    radial_right_samples::Matrix{Complex{T}}
    radial_dual_samples::Matrix{Complex{T}}
end

# ---------------------------------------------------------------------------
# Typed outputs
# ---------------------------------------------------------------------------

struct SpectralStateResult{T<:AbstractFloat}
    disposition::String
    reason::Union{Nothing,String}

    node_identity_sha256::String
    root_identity_sha256::String
    precision_tier::String

    root_solves::Int
    base_angular_eigenvalue_solves::Int
    m02_response_solves::Int

    angular_right::Union{Nothing,Vector{Complex{T}}}
    angular_transpose::Union{Nothing,Vector{Complex{T}}}
    angular_c_product::Union{Nothing,Complex{T}}
    Ac_prime::Union{Nothing,Complex{T}}
    Aomega_prime::Union{Nothing,Complex{T}}
    lambda_prime::Union{Nothing,Complex{T}}
    angular_matrix::Union{Nothing,Matrix{Complex{T}}}
    angular_matrix_derivative::Union{Nothing,Matrix{Complex{T}}}

    lambda::Union{Nothing,Complex{T}}
    matching_matrix::Union{Nothing,Matrix{Complex{T}}}
    matching_determinant::Union{Nothing,Complex{T}}
    matching_derivative::Union{Nothing,Matrix{Complex{T}}}
    adjugate_matrix::Union{Nothing,Matrix{Complex{T}}}
    coefficient_right::Union{Nothing,Vector{Complex{T}}}
    coefficient_left::Union{Nothing,Vector{Complex{T}}}
    adjugate_factor_error::Union{Nothing,T}

    eta_horizon::Union{Nothing,Complex{T}}
    eta_infinity::Union{Nothing,Complex{T}}
    dual_z_match::Union{Nothing,Vector{Complex{T}}}

    denominator_bulk::Union{Nothing,Complex{T}}
    denominator_horizon_trace::Union{Nothing,Complex{T}}
    denominator_infinity_trace::Union{Nothing,Complex{T}}
    denominator_raw::Union{Nothing,Complex{T}}
    denominator_readout::Union{Nothing,Complex{T}}

    m02_Domega_fine::Union{Nothing,Complex{T}}
    m02_Domega_coarse::Union{Nothing,Complex{T}}
    m02_stencil_disagreement::Union{Nothing,T}
    local_determinant_derivative::Union{Nothing,Complex{T}}

    bridge::Union{Nothing,Complex{T}}

    residue::Union{Nothing,Matrix{Complex{T}}}
    projector::Union{Nothing,Matrix{Complex{T}}}

    retained_rho_grid::Union{Nothing,Vector{T}}
    retained_right_samples::Union{Nothing,Matrix{Complex{T}}}
    retained_dual_samples::Union{Nothing,Matrix{Complex{T}}}

    gates::Dict{String,Any}
end

struct ContinuationEdge{T<:AbstractFloat}
    predecessor_sha256::String
    successor_sha256::String
    angular_overlap_raw::Complex{T}
    angular_overlap_aligned::T
    angular_phase_factor::Complex{T}
    radial_right_overlap_raw::Complex{T}
    radial_right_overlap_aligned::T
    radial_right_phase_factor::Complex{T}
    radial_dual_overlap_raw::Complex{T}
    radial_dual_overlap_aligned::T
    radial_dual_phase_factor::Complex{T}
end

struct BranchResult{T<:AbstractFloat}
    branch_identity::String
    node_identities::Vector{String}
    edges::Vector{ContinuationEdge{T}}
    precision_history::Vector{String}
    unresolved_gaps::Vector{Tuple{Int,Int}}
    # Processing-completion status only (COMPLETE / UNRESOLVED). This is NOT the
    # scientific branch classification (DM / ZDM / ambiguous), which is assigned
    # downstream from the reduced evidence, not here.
    completion_status::String
    completion_evidence::Dict{String,Any}
end

# ---------------------------------------------------------------------------
# Internal: bilinear pairing and helpers
# ---------------------------------------------------------------------------

bilinear(left, right) = sum(left .* right)

function finite_complex(z)
    isfinite(real(z)) && isfinite(imag(z))
end

function relative_error(value, reference)
    denom = max(abs(reference), eps(typeof(real(reference))))
    abs(value - reference) / denom
end

# Machine epsilon of the declared M02 source precision, expressed in the active
# arithmetic type T. Used to authenticate M02-sourced stencil reductions against
# the tolerance of the precision at which they were actually computed, rather
# than the (possibly finer) active M03 field precision.
function _source_epsilon(::Type{T}, source_bits::Int) where {T<:AbstractFloat}
    source_bits > 0 || error("invalid M02 source precision bits: $source_bits")
    return T(2)^T(1 - source_bits)
end

function relative_matrix_error(value, reference)
    denom = max(norm(reference), eps(typeof(real(reference[1]))))
    norm(value - reference) / denom
end

function annihilator(y)
    length(y) == 2 || error("annihilator expects a two-component Cauchy state")
    return [y[2], -y[1]]
end

function phase_normalize!(v)
    pivot = argmax(abs.(v))
    anchor = v[pivot]
    iszero(anchor) || (v .*= conj(anchor) / abs(anchor))
    return v
end

function adjugate_2x2(M)
    size(M) == (2,2) || error("adjugate requires a 2x2 matrix")
    return [M[2,2] -M[1,2]; -M[2,1] M[1,1]]
end

function factor_rank_one(adj)
    pivot = argmax(abs.(adj))
    i, j = Tuple(pivot)
    pv = adj[i, j]
    abs(pv) > 0 || error("adjugate is numerically zero")
    right = copy(adj[:, j])
    left = copy(adj[i, :]) ./ pv
    reconstructed = right * transpose(left)
    err = relative_matrix_error(reconstructed, adj)
    return right, left, err
end

function trapz_complex(f, a, b, panels::Int)
    panels >= 2 || error("quadrature panels must be >= 2")
    h = (b - a) / panels
    total = (f(a) + f(b)) / 2
    for j in 1:(panels-1)
        total += f(a + h * j)
    end
    return h * total
end

# ---------------------------------------------------------------------------
# Internal: angular matrix construction (typed BigFloat)
# ---------------------------------------------------------------------------

function _Fslm(::Type{T}, s::Int, ell::Int, m::Int) where {T<:AbstractFloat}
    ep = T(ell + 1)
    iszero(ep) && iszero(s) && return zero(T)
    return sqrt(
        ((ep^2 - T(m)^2) / (T(2ell + 3) * T(2ell + 1))) *
        ((ep^2 - T(s)^2) / ep^2)
    )
end

function _Gslm(::Type{T}, s::Int, ell::Int, m::Int) where {T<:AbstractFloat}
    ell == 0 && return zero(T)
    e = T(ell)
    return sqrt(
        ((e^2 - T(m)^2) / (T(4) * e^2 - one(T))) *
        ((e^2 - T(s)^2) / e^2)
    )
end

function _Hslm(::Type{T}, s::Int, ell::Int, m::Int) where {T<:AbstractFloat}
    (ell == 0 || s == 0) && return zero(T)
    return -T(m * s) / T(ell * (ell + 1))
end

function _angular_matrix_and_derivative(
    ::Type{T}, c::Complex{T}, s::Int, m::Int, count::Int
) where {T<:AbstractFloat}
    ell_min = max(abs(s), abs(m))
    matrix = zeros(Complex{T}, count, count)
    deriv = zeros(Complex{T}, count, count)

    for row in 1:count
        ell = ell_min + row - 1
        for col in max(1, row-2):min(count, row+2)
            ell_p = ell_min + col - 1
            val = zero(Complex{T})
            val_c = zero(Complex{T})

            if ell_p == ell - 2
                coeff = _Fslm(T, s, ell_p, m) * _Fslm(T, s, ell_p + 1, m)
                val = -c^2 * coeff
                val_c = -T(2) * c * coeff
            elseif ell_p == ell - 1
                quad = _Fslm(T, s, ell_p, m) *
                    (_Hslm(T, s, ell_p + 1, m) + _Hslm(T, s, ell_p, m))
                lin = T(s) * _Fslm(T, s, ell_p, m)
                val = -c^2 * quad + T(2) * c * lin
                val_c = -T(2) * c * quad + T(2) * lin
            elseif ell_p == ell
                diag = T(ell_p * (ell_p + 1) - s * (s + 1))
                quad = _Fslm(T, s, ell_p, m) * _Gslm(T, s, ell_p + 1, m) +
                       _Gslm(T, s, ell_p, m) * _Fslm(T, s, ell_p - 1, m) +
                       _Hslm(T, s, ell_p, m)^2
                lin = T(s) * _Hslm(T, s, ell_p, m)
                val = diag - c^2 * quad + T(2) * c * lin
                val_c = -T(2) * c * quad + T(2) * lin
            elseif ell_p == ell + 1
                quad = _Gslm(T, s, ell_p, m) *
                    (_Hslm(T, s, ell_p - 1, m) + _Hslm(T, s, ell_p, m))
                lin = T(s) * _Gslm(T, s, ell_p, m)
                val = -c^2 * quad + T(2) * c * lin
                val_c = -T(2) * c * quad + T(2) * lin
            elseif ell_p == ell + 2
                coeff = _Gslm(T, s, ell_p, m) * _Gslm(T, s, ell_p - 1, m)
                val = -c^2 * coeff
                val_c = -T(2) * c * coeff
            end

            matrix[row, col] = val
            deriv[row, col] = val_c
        end
    end
    return matrix, deriv
end

# ---------------------------------------------------------------------------
# Internal: angular right state, transpose covector, A_c'
# ---------------------------------------------------------------------------

function _angular_state(
    ::Type{T}, c::Complex{T}, A::Complex{T},
    s::Int, ell::Int, m::Int, pad::Int
) where {T<:AbstractFloat}
    ell_min = max(abs(s), abs(m))
    count = ell + pad - ell_min + 1
    target = ell - ell_min + 1

    Mth, dMc = _angular_matrix_and_derivative(T, c, s, m, count)
    K = Mth - A * I

    symmetry_residual = norm(Mth - transpose(Mth)) / max(norm(Mth), eps(T))

    keep = [i for i in 1:count if i != target]
    q = zeros(Complex{T}, count)
    q[target] = one(T)
    q[keep] = K[keep, keep] \ (-K[keep, target])

    # This Euclidean normalization fixes only the presentation of the right
    # state.  The canonical dual below is still formed exclusively with the
    # complex-bilinear c-product.
    q ./= norm(q)
    phase_normalize!(q)
    right_residual = norm(K * q) / (max(norm(Mth), eps(T)) * max(norm(q), eps(T)))

    c_product = bilinear(q, q)

    if abs(c_product) < eps(T)
        return (
            coefficients=q,
            transpose_covector=nothing,
            c_product=c_product,
            Ac_prime=nothing,
            matrix=Mth,
            matrix_derivative=dMc,
            right_residual=right_residual,
            transpose_residual=nothing,
            symmetry_residual=symmetry_residual,
            count=count,
            target_index=target,
            self_orthogonal=true,
        )
    end

    eta = q / c_product
    transpose_residual = norm(transpose(K) * eta) / (max(norm(K), eps(T)) * max(norm(eta), eps(T)))

    Ac_prime = bilinear(eta, dMc * q)

    return (
        coefficients=q,
        transpose_covector=eta,
        c_product=c_product,
        Ac_prime=Ac_prime,
        matrix=Mth,
        matrix_derivative=dMc,
        right_residual=right_residual,
        transpose_residual=transpose_residual,
        symmetry_residual=symmetry_residual,
        count=count,
        target_index=target,
        self_orthogonal=false,
    )
end

# ---------------------------------------------------------------------------
# Internal: radial state construction
# ---------------------------------------------------------------------------

function _build_radial_state(
    ::Type{T}, s::Int, m_mode::Int, spin::T,
    omega::Complex{T}, A::Complex{T};
    readout::T, rho_in::T, rho_out::T, reltol::T, abstol::T, endpoint_order::Int
) where {T<:AbstractFloat}
    c = spin * omega
    lambda = A + c^2 - T(2 * m_mode) * c
    p_horizon = omega - T(m_mode) * Kerr.omega_horizon(spin)
    convention = GSN.gsn_branch_convention(omega, p_horizon)
    rsmp = T(GSN.rstar_from_r(spin, readout))
    algorithm = AutoVern9(Rosenbrock23(autodiff=false))
    dtype = Complex{T}

    horizon_tangent = Complex{T}(
        T(convention.horizon_sign) * exp(im * convention.horizon_contour_angle)
    )
    infinity_tangent = Complex{T}(
        T(convention.infinity_sign) * exp(im * convention.infinity_contour_angle)
    )

    r_from_rho = CF.solve_r_from_rho(
        spin,
        convention.horizon_contour_angle,
        convention.infinity_contour_angle,
        rsmp, rho_in, rho_out;
        sign_neg=convention.horizon_sign,
        sign_pos=convention.infinity_sign,
        dtype=dtype, odealgo=algorithm,
        reltol=reltol, abstol=abstol, verbose=false,
    )

    Xin, Xin_pos, Xin_neg = CF.solve_Xin(
        s, m_mode, spin,
        convention.infinity_contour_angle,
        convention.horizon_contour_angle,
        omega, lambda, r_from_rho, rsmp,
        rho_in, rho_out;
        initialconditions_order=endpoint_order,
        dtype=dtype, odealgo=algorithm,
        reltol=reltol, abstol=abstol,
    )

    Xup, Xup_pos, Xup_neg = CF.solve_Xup(
        s, m_mode, spin,
        convention.infinity_contour_angle,
        convention.horizon_contour_angle,
        omega, lambda, r_from_rho, rsmp,
        rho_in, rho_out;
        initialconditions_order=endpoint_order,
        dtype=dtype, odealgo=algorithm,
        reltol=reltol, abstol=abstol,
    )

    all_ok = all((
        SciMLBase.successful_retcode(Xin_pos),
        SciMLBase.successful_retcode(Xin_neg),
        SciMLBase.successful_retcode(Xup_pos),
        SciMLBase.successful_retcode(Xup_neg),
    ))

    yin_match = Complex{T}[Xin(zero(T))[1], Xin(zero(T))[2]]
    yup_match = Complex{T}[Xup(zero(T))[1], Xup(zero(T))[2]]
    matching = hcat(yin_match, yup_match)
    determinant = det(matching)

    yin_horizon = Complex{T}[Xin(rho_in)[1], Xin(rho_in)[2]]
    yup_infinity = Complex{T}[Xup(rho_out)[1], Xup(rho_out)[2]]
    b_horizon = annihilator(yin_horizon)
    b_infinity = annihilator(yup_infinity)

    function P_rho(rho, side::Symbol)
        r = r_from_rho(rho)
        tangent = side === :horizon ? horizon_tangent : infinity_tangent
        F = Potentials.sF(s, m_mode, spin, omega, lambda, r)
        U = Potentials.sU(s, m_mode, spin, omega, lambda, r)
        return tangent * Complex{T}[zero(T) one(T); U F]
    end

    return (
        omega=omega, A=A, lambda=lambda,
        convention=convention,
        horizon_tangent=horizon_tangent,
        infinity_tangent=infinity_tangent,
        r_from_rho=r_from_rho, rsmp=rsmp,
        Xin=Xin, Xup=Xup,
        all_ok=all_ok,
        matching=matching, determinant=determinant,
        yin_match=yin_match, yup_match=yup_match,
        yin_horizon=yin_horizon, yup_infinity=yup_infinity,
        b_horizon=b_horizon, b_infinity=b_infinity,
        P_rho=P_rho,
    )
end

# ---------------------------------------------------------------------------
# Internal: radial transpose Z' = -P^T Z with endpoint multipliers
# ---------------------------------------------------------------------------

function _solve_radial_transpose(
    ::Type{T}, state; rho_in::T, rho_out::T, reltol::T, abstol::T
) where {T<:AbstractFloat}
    algorithm = AutoVern9(Rosenbrock23(autodiff=false))

    rhs_horizon(z, _p, rho) = -(transpose(state.P_rho(rho, :horizon)) * z)
    problem_h = ODEProblem(rhs_horizon, state.b_horizon, (rho_in, zero(T)))
    sol_h = solve(problem_h, algorithm; reltol=reltol, abstol=abstol, maxiters=10^7)
    SciMLBase.successful_retcode(sol_h) || error("transpose horizon leg failed")

    z_match = Complex{T}.(sol_h(zero(T)))

    rhs_infinity(z, _p, rho) = -(transpose(state.P_rho(rho, :infinity)) * z)
    problem_i = ODEProblem(rhs_infinity, z_match, (zero(T), rho_out))
    sol_i = solve(problem_i, algorithm; reltol=reltol, abstol=abstol, maxiters=10^7)
    SciMLBase.successful_retcode(sol_i) || error("transpose infinity leg failed")

    z_out = Complex{T}.(sol_i(rho_out))

    anchor = argmax(abs.(state.b_infinity))
    abs(state.b_infinity[anchor]) > eps(T) || error("infinity boundary covector is zero")
    eta_horizon = one(Complex{T})
    eta_infinity = -z_out[anchor] / state.b_infinity[anchor]
    endpoint_target = -eta_infinity * state.b_infinity
    endpoint_residual = norm(z_out - endpoint_target) / max(norm(z_out), eps(T))

    z_of_rho(rho) = rho <= 0 ? Complex{T}.(sol_h(rho)) : Complex{T}.(sol_i(rho))

    readout_left = z_match
    readout_residual = let
        adj = adjugate_2x2(state.matching)
        _, left_from_adj, _ = factor_rank_one(adj)
        scale = abs(bilinear(left_from_adj, readout_left)) > eps(T) ?
            bilinear(left_from_adj, readout_left) : one(Complex{T})
        scaled = readout_left / scale
        norm(transpose(state.matching) * scaled) / max(norm(state.matching) * norm(scaled), eps(T))
    end

    return (
        eta_horizon=eta_horizon,
        eta_infinity=eta_infinity,
        z_match=z_match,
        z_out=z_out,
        endpoint_residual=endpoint_residual,
        readout_residual=readout_residual,
        z_of_rho=z_of_rho,
        sol_horizon=sol_h,
        sol_infinity=sol_i,
    )
end

# ---------------------------------------------------------------------------
# Internal: bilinear conservation diagnostic
# ---------------------------------------------------------------------------

function _bilinear_conservation(
    ::Type{T}, state, dual, coeff_right, rho_in::T, rho_out::T
) where {T<:AbstractFloat}
    uin, uup = coeff_right[1], coeff_right[2]
    inner(rho) = uin * Complex{T}[state.Xin(rho)[1], state.Xin(rho)[2]]
    outer(rho) = -uup * Complex{T}[state.Xup(rho)[1], state.Xup(rho)[2]]

    horizon_points = T[rho_in, rho_in/T(2), -T(10), zero(T)]
    infinity_points = T[zero(T), T(10), rho_out/T(2), rho_out]

    ref_val = bilinear(dual.z_of_rho(zero(T)), inner(zero(T)))
    scale = max(abs(ref_val), one(T))

    horizon_vals = Complex{T}[]
    for rho in horizon_points
        push!(horizon_vals, bilinear(dual.z_of_rho(rho), inner(rho)))
    end
    horizon_drift = maximum(abs.(horizon_vals .- ref_val)) / scale

    infinity_vals = Complex{T}[]
    for rho in infinity_points
        right_val = rho <= 0 ? inner(rho) : outer(rho)
        push!(infinity_vals, bilinear(dual.z_of_rho(rho), right_val))
    end
    infinity_drift = maximum(abs.(infinity_vals .- ref_val)) / scale

    return (horizon=horizon_drift, infinity=infinity_drift)
end

# ---------------------------------------------------------------------------
# Internal: raw contour-plus-endpoint Keldysh denominator
# ---------------------------------------------------------------------------

function _raw_denominator(
    ::Type{T}, base, plus, minus, dual, coeff_right,
    epsilon::T, rho_in::T, rho_out::T, panels::Int
) where {T<:AbstractFloat}
    uin, uup = coeff_right[1], coeff_right[2]
    inner_right(rho) = uin * Complex{T}[base.Xin(rho)[1], base.Xin(rho)[2]]
    outer_right(rho) = -uup * Complex{T}[base.Xup(rho)[1], base.Xup(rho)[2]]

    Pprime(rho, side) = (plus.P_rho(rho, side) - minus.P_rho(rho, side)) / (T(2) * epsilon)

    bulk_inner_f(rho) = -bilinear(dual.z_of_rho(rho), Pprime(rho, :horizon) * inner_right(rho))
    bulk_outer_f(rho) = -bilinear(dual.z_of_rho(rho), Pprime(rho, :infinity) * outer_right(rho))

    bulk_inner = trapz_complex(bulk_inner_f, rho_in, zero(T), panels)
    bulk_outer = trapz_complex(bulk_outer_f, zero(T), rho_out, panels)
    bulk = bulk_inner + bulk_outer

    b_h_prime = (plus.b_horizon - minus.b_horizon) / (T(2) * epsilon)
    b_i_prime = (plus.b_infinity - minus.b_infinity) / (T(2) * epsilon)
    y_h = coeff_right[1] * base.yin_horizon
    y_i = -coeff_right[2] * base.yup_infinity

    horizon_trace = dual.eta_horizon * bilinear(b_h_prime, y_h)
    infinity_trace = dual.eta_infinity * bilinear(b_i_prime, y_i)
    total = bulk + horizon_trace + infinity_trace

    return (
        bulk_inner=bulk_inner,
        bulk_outer=bulk_outer,
        bulk=bulk,
        horizon_trace=horizon_trace,
        infinity_trace=infinity_trace,
        total=total,
    )
end

# ---------------------------------------------------------------------------
# Internal: residue / projector / rescaling / resolvent
# ---------------------------------------------------------------------------

function _residue_and_projector(right, left, Fprime)
    denom = bilinear(left, Fprime * right)
    abs(denom) > eps(typeof(real(denom))) || error("Keldysh denominator is zero")
    residue = right * transpose(left) / denom
    projector = residue * Fprime
    return denom, residue, projector
end

function _resolvent_audit(plus, minus, epsilon, residue, projector, Fprime)
    Rplus = epsilon * inv(plus.matching)
    Rminus = -epsilon * inv(minus.matching)
    sym_residue = (Rplus + Rminus) / 2
    sym_projector = (Rplus * Fprime + Rminus * Fprime) / 2

    return (
        residue_error=relative_matrix_error(sym_residue, residue),
        projector_error=relative_matrix_error(sym_projector, projector),
    )
end

function _adjugate_residue_audit(adj, m02_Domega, residue)
    adj_residue = adj / m02_Domega
    return relative_matrix_error(adj_residue, residue)
end

# ---------------------------------------------------------------------------
# Internal: retained field sampling
# ---------------------------------------------------------------------------

function _sample_fields(state, dual, coeff_right, grid::Vector{T}) where {T}
    uin, uup = coeff_right[1], coeff_right[2]
    n = length(grid)
    right_samples = Matrix{Complex{T}}(undef, 2, n)
    dual_samples = Matrix{Complex{T}}(undef, 2, n)

    for (j, rho) in enumerate(grid)
        if rho <= 0
            right_samples[:, j] = uin * Complex{T}[state.Xin(rho)[1], state.Xin(rho)[2]]
        else
            right_samples[:, j] = -uup * Complex{T}[state.Xup(rho)[1], state.Xup(rho)[2]]
        end
        dual_samples[:, j] = dual.z_of_rho(rho)
    end
    return right_samples, dual_samples
end

# ---------------------------------------------------------------------------
# Internal: early-return builder
# ---------------------------------------------------------------------------

# Numerical-sufficiency failures (ODE legs, zero denominator) are promotable
# at BF40: a higher-precision retry may resolve them. At BF80 they are terminal.
_numerical_disposition(seed::RootSeed) =
    seed.precision_tier == "bigfloat-40" ? "PROMOTION_REQUIRED" : "UNRESOLVED"

function _partial_result(
    ::Type{T}, disposition::String, reason::String,
    seed::RootSeed{T}, gates::Dict{String,Any};
    kwargs...
) where {T<:AbstractFloat}
    kw = Dict{Symbol,Any}(kwargs)
    g(sym, default) = get(kw, sym, default)

    return SpectralStateResult{T}(
        disposition, reason,
        seed.node_identity_sha256, seed.root_identity_sha256, seed.precision_tier,
        0, 0, 0,
        g(:angular_right, nothing), g(:angular_transpose, nothing),
        g(:angular_c_product, nothing), g(:Ac_prime, nothing),
        g(:Aomega_prime, nothing), g(:lambda_prime, nothing),
        g(:angular_matrix, nothing), g(:angular_matrix_derivative, nothing),
        g(:lambda, nothing),
        g(:matching_matrix, nothing), g(:matching_determinant, nothing),
        g(:matching_derivative, nothing), g(:adjugate_matrix, nothing),
        g(:coefficient_right, nothing), g(:coefficient_left, nothing),
        g(:adjugate_factor_error, nothing),
        g(:eta_horizon, nothing), g(:eta_infinity, nothing),
        g(:dual_z_match, nothing),
        g(:denominator_bulk, nothing), g(:denominator_horizon_trace, nothing),
        g(:denominator_infinity_trace, nothing), g(:denominator_raw, nothing),
        g(:denominator_readout, nothing),
        g(:m02_Domega_fine, nothing), g(:m02_Domega_coarse, nothing),
        g(:m02_stencil_disagreement, nothing),
        g(:local_determinant_derivative, nothing),
        g(:bridge, nothing),
        g(:residue, nothing), g(:projector, nothing),
        g(:retained_rho_grid, nothing),
        g(:retained_right_samples, nothing), g(:retained_dual_samples, nothing),
        gates,
    )
end

# ---------------------------------------------------------------------------
# Public: solve_node
# ---------------------------------------------------------------------------

function solve_node(
    seed::RootSeed{T},
    domega::DomegaStencil{T},
    policy::NumericalPolicy{T},
)::SpectralStateResult{T} where {T<:AbstractFloat}

    gates = Dict{String,Any}()

    # --- 10.1 Input conservation ---

    seed.precision_tier == policy.precision_tier ||
        error("precision tier mismatch between seed and policy")
    seed.precision_tier in ("bigfloat-40", "bigfloat-80") ||
        error("unsupported precision tier: $(seed.precision_tier)")
    all(finite_complex, (seed.omega, seed.angular_A)) ||
        error("non-finite seed inputs")
    all(finite_complex, (domega.D0, domega.D_plus_h, domega.D_minus_h,
                         domega.D_plus_half_h, domega.D_minus_half_h)) ||
        error("non-finite Domega stencil inputs")
    seed.root_identity_sha256 == domega.root_identity_sha256 ||
        error("root identity mismatch between seed and Domega stencil")
    domega.determinant_family == "exterior-wronskian/v1" ||
        error("wrong determinant family: $(domega.determinant_family)")
    domega.determinant_convention == "wronskian-perturbed-Xin-with-Xup/v1" ||
        error("wrong determinant convention")
    domega.determinant_normalisation == "unit-asymptotic-branch-wronskian/v1" ||
        error("wrong determinant normalisation")
    domega.scientific_operation_identity == "canonical-exterior-background-wronskian/v1" ||
        error("wrong scientific operation identity")

    gates["1_root_identity_conserved"] = true
    gates["2_root_solves"] = 0
    gates["3_base_angular_eigenvalue_solves"] = 0

    # --- 10.2 Angular right state ---

    omega = seed.omega
    A = seed.angular_A
    a = seed.spin
    c = a * omega

    ang = _angular_state(T, c, A, seed.s, seed.ell, seed.m, policy.angular_pad)

    gates["4_angular_right_residual"] = ang.right_residual
    g4 = ang.right_residual <= policy.angular_right_residual_max

    # --- 10.3 Angular transpose covector ---

    if ang.self_orthogonal
        gates["7_angular_c_product_abs"] = abs(ang.c_product)
        return _partial_result(T, "UNRESOLVED",
            "angular transpose state self-orthogonal or numerically unresolved",
            seed, gates;
            angular_right=ang.coefficients, angular_c_product=ang.c_product,
            angular_matrix=ang.matrix, angular_matrix_derivative=ang.matrix_derivative)
    end

    gates["5_angular_transpose_residual"] = ang.transpose_residual
    g5 = ang.transpose_residual <= policy.angular_transpose_residual_max

    gates["6_angular_symmetry_residual"] = ang.symmetry_residual
    g6 = ang.symmetry_residual <= policy.angular_symmetry_residual_max

    gates["7_angular_c_product_abs"] = abs(ang.c_product)
    g7 = abs(ang.c_product) >= policy.angular_c_product_min

    if !g7
        return _partial_result(T, "UNRESOLVED", "angular c-product below minimum threshold",
            seed, gates;
            angular_right=ang.coefficients, angular_transpose=ang.transpose_covector,
            angular_c_product=ang.c_product,
            angular_matrix=ang.matrix, angular_matrix_derivative=ang.matrix_derivative)
    end

    # --- 10.4 Angular derivative transport ---

    Aomega_prime = a * ang.Ac_prime
    lambda_prime = Aomega_prime + T(2) * a^2 * omega - T(2 * seed.m) * a

    epsilon_fd = policy.angular_derivative_step
    c_plus = a * (omega + epsilon_fd)
    c_minus = a * (omega - epsilon_fd)
    M_plus, _ = _angular_matrix_and_derivative(T, c_plus, seed.s, seed.m, ang.count)
    M_minus, _ = _angular_matrix_and_derivative(T, c_minus, seed.s, seed.m, ang.count)
    A_plus_fd = bilinear(ang.transpose_covector, M_plus * ang.coefficients)
    A_minus_fd = bilinear(ang.transpose_covector, M_minus * ang.coefficients)
    Aomega_fd = (A_plus_fd - A_minus_fd) / (T(2) * epsilon_fd)
    lambda_fd = Aomega_fd + T(2) * a^2 * omega - T(2 * seed.m) * a
    lambda_disagreement = relative_error(lambda_fd, lambda_prime)
    gates["8_lambda_derivative_audit"] = lambda_disagreement
    g8 = lambda_disagreement <= policy.lambda_derivative_disagreement_max

    # --- 10.5 Base radial right state ---

    lam = A + c^2 - T(2 * seed.m) * c
    base = _build_radial_state(T, seed.s, seed.m, a, omega, A;
        readout=policy.readout_radius, rho_in=policy.rho_inner, rho_out=policy.rho_outer,
        reltol=policy.ode_reltol, abstol=policy.ode_abstol, endpoint_order=policy.endpoint_order)

    gates["9_radial_ode_success"] = base.all_ok
    g9 = base.all_ok

    if !g9
        return _partial_result(T, _numerical_disposition(seed), "base radial ODE legs failed",
            seed, gates;
            angular_right=ang.coefficients, angular_transpose=ang.transpose_covector,
            angular_c_product=ang.c_product, Ac_prime=ang.Ac_prime,
            Aomega_prime=Aomega_prime, lambda_prime=lambda_prime,
            lambda=lam,
            angular_matrix=ang.matrix, angular_matrix_derivative=ang.matrix_derivative)
    end

    adj = adjugate_2x2(base.matching)
    u_right, beta_left, adj_err = factor_rank_one(adj)

    right_null = norm(base.matching * u_right) /
        max(norm(base.matching) * norm(u_right), eps(T))
    left_null = norm(transpose(base.matching) * beta_left) /
        max(norm(base.matching) * norm(beta_left), eps(T))

    normalized_wronsk = abs(base.determinant) /
        max(norm(base.yin_match) * norm(base.yup_match), eps(T))

    gates["10_radial_wronskian"] = normalized_wronsk
    g10 = normalized_wronsk <= policy.radial_wronskian_max

    gates["11_matching_right_null"] = right_null
    g11 = right_null <= policy.matching_right_null_max

    gates["12_matching_left_null"] = left_null
    g12 = left_null <= policy.matching_left_null_max

    gates["13_adjugate_rank_one"] = adj_err
    g13 = adj_err <= policy.matching_right_null_max

    # --- 10.6 Shifted audit states ---

    eps_audit = policy.frequency_audit_step
    A_plus = A + Aomega_prime * eps_audit
    A_minus = A - Aomega_prime * eps_audit

    plus = _build_radial_state(T, seed.s, seed.m, a, omega + eps_audit, A_plus;
        readout=policy.readout_radius, rho_in=policy.rho_inner, rho_out=policy.rho_outer,
        reltol=policy.ode_reltol, abstol=policy.ode_abstol, endpoint_order=policy.endpoint_order)
    minus = _build_radial_state(T, seed.s, seed.m, a, omega - eps_audit, A_minus;
        readout=policy.readout_radius, rho_in=policy.rho_inner, rho_out=policy.rho_outer,
        reltol=policy.ode_reltol, abstol=policy.ode_abstol, endpoint_order=policy.endpoint_order)

    gates["14_shifted_ode_success"] = plus.all_ok && minus.all_ok
    g14 = plus.all_ok && minus.all_ok

    if !g14
        return _partial_result(T, _numerical_disposition(seed), "shifted radial ODE legs failed",
            seed, gates;
            angular_right=ang.coefficients, angular_transpose=ang.transpose_covector,
            angular_c_product=ang.c_product, Ac_prime=ang.Ac_prime,
            Aomega_prime=Aomega_prime, lambda_prime=lambda_prime,
            lambda=lam,
            matching_matrix=base.matching, matching_determinant=base.determinant,
            adjugate_matrix=adj, coefficient_right=u_right, coefficient_left=beta_left,
            adjugate_factor_error=adj_err,
            angular_matrix=ang.matrix, angular_matrix_derivative=ang.matrix_derivative)
    end

    Fprime = (plus.matching - minus.matching) / (T(2) * eps_audit)
    local_Domega = (plus.determinant - minus.determinant) / (T(2) * eps_audit)

    # --- 10.7 Radial transpose state ---

    dual = _solve_radial_transpose(T, base;
        rho_in=policy.rho_inner, rho_out=policy.rho_outer, reltol=policy.ode_reltol, abstol=policy.ode_abstol)

    gates["15_transpose_endpoint_residual"] = dual.endpoint_residual
    g15 = dual.endpoint_residual <= policy.transpose_endpoint_residual_max

    gates["16_transpose_readout_residual"] = dual.readout_residual
    g16 = dual.readout_residual <= policy.transpose_readout_residual_max

    _, left_from_adj, _ = factor_rank_one(adj)
    z_projective = dual.z_match
    proj_disagree = let
        dn = norm(left_from_adj) * norm(z_projective)
        iszero(dn) ? T(Inf) :
            abs(
                left_from_adj[1] * z_projective[2] -
                left_from_adj[2] * z_projective[1]
            ) / dn
    end
    gates["17_comode_projective_agreement"] = proj_disagree
    g17 = proj_disagree <= policy.dual_projective_disagreement_max

    conservation = _bilinear_conservation(T, base, dual, u_right,
        policy.rho_inner, policy.rho_outer)
    gates["18_horizon_bilinear_conservation"] = conservation.horizon
    gates["19_infinity_bilinear_conservation"] = conservation.infinity
    g18 = conservation.horizon <= policy.bilinear_conservation_max
    g19 = conservation.infinity <= policy.bilinear_conservation_max

    # --- 10.8 Full Keldysh denominator ---

    raw = _raw_denominator(T, base, plus, minus, dual, u_right,
        eps_audit, policy.rho_inner, policy.rho_outer, policy.quadrature_panels)

    d_readout = bilinear(dual.z_match, Fprime * u_right)
    contour_readout_rel = relative_error(raw.total, d_readout)
    gates["19b_contour_readout_consistency"] = contour_readout_rel
    g19b = contour_readout_rel <= policy.contour_to_readout_denominator_relative_max

    # --- 10.9 M02 derivative validation ---
    #
    # The M02 stencil samples were computed and serialized at the M02 source
    # precision (source_precision_bits), which may be coarser than the active
    # M03 field precision T (e.g. a BF40-sourced stencil consumed by a BF80 or
    # Deep node). Reconstructing BF40-rounded samples at BF80 differs from the
    # stored BF40-rounded derivative by ~a BF40 rounding unit, which vastly
    # exceeds eps(BF80). Authenticate the reduction against the DECLARED SOURCE
    # precision tolerance, then promote the authenticated value into active T.

    source_eps = _source_epsilon(T, domega.source_precision_bits)
    auth_tol = source_eps * T(100)

    coarse_recomputed = (domega.D_plus_h - domega.D_minus_h) / (T(2) * domega.h)
    fine_recomputed = (domega.D_plus_half_h - domega.D_minus_half_h) / domega.h
    disagreement_recomputed = abs(fine_recomputed - coarse_recomputed)

    relative_error(coarse_recomputed, domega.coarse_derivative) < auth_tol ||
        error("supplied coarse_derivative does not match independent reduction from raw stencil at source precision")
    relative_error(fine_recomputed, domega.fine_derivative) < auth_tol ||
        error("supplied fine_derivative does not match independent reduction from raw stencil at source precision")
    abs(disagreement_recomputed - domega.disagreement_abs) /
        max(domega.disagreement_abs, source_eps) < auth_tol ||
        error("supplied disagreement_abs does not match independent reduction from raw stencil at source precision")

    gates["20_m02_domega_disk_excludes_zero"] = abs(domega.fine_derivative) > domega.disagreement_abs
    g20 = abs(domega.fine_derivative) > domega.disagreement_abs

    stencil_disagree_rel = domega.disagreement_abs / max(abs(domega.fine_derivative), eps(T))
    gates["21_m02_stencil_stability"] = stencil_disagree_rel
    g21 = stencil_disagree_rel <= policy.domega_stencil_relative_disagreement_max

    local_vs_m02 = relative_error(local_Domega, domega.fine_derivative)
    gates["22_local_vs_m02_domega"] = local_vs_m02
    g22 = local_vs_m02 <= policy.local_domega_to_m02_relative_max

    # --- 10.10 Evans↔Keldysh bridge ---

    abs(raw.total) > eps(T) || return _partial_result(T, "UNRESOLVED",
        "raw Keldysh denominator is zero", seed, gates;
        angular_right=ang.coefficients, angular_transpose=ang.transpose_covector,
        angular_c_product=ang.c_product, Ac_prime=ang.Ac_prime,
        Aomega_prime=Aomega_prime, lambda_prime=lambda_prime, lambda=lam,
        matching_matrix=base.matching, matching_determinant=base.determinant,
        matching_derivative=Fprime, adjugate_matrix=adj,
        coefficient_right=u_right, coefficient_left=beta_left,
        adjugate_factor_error=adj_err,
        eta_horizon=dual.eta_horizon, eta_infinity=dual.eta_infinity,
        dual_z_match=dual.z_match,
        denominator_bulk=raw.bulk, denominator_horizon_trace=raw.horizon_trace,
        denominator_infinity_trace=raw.infinity_trace, denominator_raw=raw.total,
        denominator_readout=d_readout,
        m02_Domega_fine=domega.fine_derivative, m02_Domega_coarse=domega.coarse_derivative,
        m02_stencil_disagreement=stencil_disagree_rel,
        local_determinant_derivative=local_Domega,
        angular_matrix=ang.matrix, angular_matrix_derivative=ang.matrix_derivative)

    bridge = domega.fine_derivative / raw.total
    bridged_denom = bridge * raw.total
    bridge_closure = relative_error(bridged_denom, domega.fine_derivative)
    gates["23_bridge_closure"] = bridge_closure
    g23 = bridge_closure <= policy.bridge_closure_relative_max

    eta_horizon_canonical = bridge * dual.eta_horizon
    eta_infinity_canonical = bridge * dual.eta_infinity
    z_match_canonical = bridge .* dual.z_match

    # --- 10.11 Residue and projector ---

    _, residue, projector = _residue_and_projector(u_right, z_match_canonical, Fprime)

    # --- 10.12 Rescaling invariance ---

    cscale = Complex{T}(T(17)/T(10), -T(4)/T(10))
    dscale = Complex{T}(-T(8)/T(10), T(13)/T(10))

    _, res_right, proj_right = _residue_and_projector(cscale * u_right, z_match_canonical, Fprime)
    _, res_left, proj_left = _residue_and_projector(u_right, dscale * z_match_canonical, Fprime)
    _, res_both, proj_both = _residue_and_projector(cscale * u_right, dscale * z_match_canonical, Fprime)

    res_right_err = relative_matrix_error(res_right, residue)
    res_left_err = relative_matrix_error(res_left, residue)
    res_both_err = relative_matrix_error(res_both, residue)
    proj_right_err = relative_matrix_error(proj_right, projector)
    proj_left_err = relative_matrix_error(proj_left, projector)
    proj_both_err = relative_matrix_error(proj_both, projector)

    max_res_rescale = max(res_right_err, res_left_err, res_both_err)
    max_proj_rescale = max(proj_right_err, proj_left_err, proj_both_err)
    gates["24_residue_rescaling_invariance"] = max_res_rescale
    gates["24_projector_rescaling_invariance"] = max_proj_rescale
    g24 = max_res_rescale <= policy.residue_rescaling_relative_max &&
          max_proj_rescale <= policy.projector_rescaling_relative_max

    idempotence = relative_matrix_error(projector * projector, projector)
    action = let
        Pu = projector * u_right
        norm_u = max(norm(u_right), eps(T))
        scale = Pu[argmax(abs.(u_right))] / u_right[argmax(abs.(u_right))]
        norm(Pu - scale * u_right) / norm_u
    end
    gates["25_projector_idempotence"] = idempotence
    gates["25_projector_action"] = action
    g25 = idempotence <= policy.projector_idempotence_relative_max &&
          action <= policy.projector_action_relative_max

    # --- 10.13 Local resolvent audit ---

    audit = _resolvent_audit(plus, minus, eps_audit, residue, projector, Fprime)
    adj_res_err = _adjugate_residue_audit(adj, domega.fine_derivative, residue)

    gates["26_local_resolvent_residue"] = audit.residue_error
    gates["26_local_resolvent_projector"] = audit.projector_error
    gates["26_adjugate_residue"] = adj_res_err
    g26 = audit.residue_error <= policy.local_resolvent_residue_relative_max &&
          audit.projector_error <= policy.local_resolvent_projector_relative_max &&
          adj_res_err <= policy.adjugate_residue_relative_max

    # --- 10.14 Retained state ---

    retained_right, retained_dual_raw = _sample_fields(
        base, dual, u_right, policy.retained_rho_grid)
    retained_dual = bridge .* retained_dual_raw

    # --- Disposition ---

    all_pass = g4 && g5 && g6 && g7 && g8 && g9 && g10 &&
               g11 && g12 && g13 && g14 && g15 && g16 && g17 &&
               g18 && g19 && g19b && g20 && g21 && g22 && g23 && g24 && g25 && g26

    if all_pass
        disposition = "PRODUCED"
        reason = nothing
    else
        failed = String[]
        !g4 && push!(failed, "angular_right_residual")
        !g5 && push!(failed, "angular_transpose_residual")
        !g6 && push!(failed, "angular_symmetry")
        !g8 && push!(failed, "lambda_derivative_audit")
        !g10 && push!(failed, "radial_wronskian")
        !g11 && push!(failed, "matching_right_null")
        !g12 && push!(failed, "matching_left_null")
        !g13 && push!(failed, "adjugate_rank_one")
        !g15 && push!(failed, "transpose_endpoint")
        !g16 && push!(failed, "transpose_readout")
        !g17 && push!(failed, "comode_projective")
        !g18 && push!(failed, "horizon_bilinear_conservation")
        !g19 && push!(failed, "infinity_bilinear_conservation")
        !g19b && push!(failed, "contour_readout_consistency")
        !g20 && push!(failed, "m02_domega_disk")
        !g21 && push!(failed, "m02_stencil_stability")
        !g22 && push!(failed, "local_vs_m02_domega")
        !g23 && push!(failed, "bridge_closure")
        !g24 && push!(failed, "rescaling_invariance")
        !g25 && push!(failed, "projector_idempotence_action")
        !g26 && push!(failed, "local_resolvent")

        eligible_for_promotion = seed.precision_tier == "bigfloat-40" &&
            any(f -> f in ("angular_right_residual", "angular_transpose_residual",
                           "radial_wronskian", "matching_right_null", "matching_left_null",
                           "transpose_endpoint", "transpose_readout",
                           "horizon_bilinear_conservation", "infinity_bilinear_conservation",
                           "contour_readout_consistency", "rescaling_invariance",
                           "projector_idempotence_action", "local_resolvent",
                           "bridge_closure", "local_vs_m02_domega",
                           "m02_stencil_stability"), failed)

        disposition = eligible_for_promotion ? "PROMOTION_REQUIRED" : "UNRESOLVED"
        reason = join(failed, ", ")
    end

    return SpectralStateResult{T}(
        disposition, reason,
        seed.node_identity_sha256, seed.root_identity_sha256, seed.precision_tier,
        0, 0, 0,
        ang.coefficients, ang.transpose_covector, ang.c_product,
        ang.Ac_prime, Aomega_prime, lambda_prime,
        ang.matrix, ang.matrix_derivative,
        lam,
        base.matching, base.determinant, Fprime, adj,
        u_right, beta_left, adj_err,
        eta_horizon_canonical, eta_infinity_canonical, z_match_canonical,
        raw.bulk, raw.horizon_trace, raw.infinity_trace, raw.total, d_readout,
        domega.fine_derivative, domega.coarse_derivative, stencil_disagree_rel,
        local_Domega,
        bridge,
        residue, projector,
        policy.retained_rho_grid, retained_right, retained_dual,
        gates,
    )
end

# ---------------------------------------------------------------------------
# Public: compare_continuation
# ---------------------------------------------------------------------------

function compare_continuation(
    predecessor::RetainedPredecessor{T},
    successor::SpectralStateResult{T},
    policy::NumericalPolicy{T},
) where {T<:AbstractFloat}
    successor.angular_right === nothing && error("successor has no angular right state")

    # Continuation overlaps are conditioning diagnostics only.  Spell out the
    # Hermitian overlap so it cannot be mistaken for the canonical bilinear
    # transpose pairing used by the spectral construction.
    ang_overlap = sum(conj.(predecessor.angular_right) .* successor.angular_right)
    ang_norm_pred = norm(predecessor.angular_right)
    ang_norm_succ = norm(successor.angular_right)
    ang_scale = max(ang_norm_pred * ang_norm_succ, eps(T))
    ang_normalized = ang_overlap / ang_scale
    ang_mag = abs(ang_normalized)
    ang_phase = ang_mag > eps(T) ? conj(ang_normalized) / ang_mag : one(Complex{T})
    ang_aligned = ang_mag

    rad_right_raw = zero(Complex{T})
    rad_right_norm_pred = zero(T)
    rad_right_norm_succ = zero(T)
    rad_dual_raw = zero(Complex{T})
    rad_dual_norm_pred = zero(T)
    rad_dual_norm_succ = zero(T)

    if successor.retained_right_samples !== nothing
        n = min(size(predecessor.radial_right_samples, 2),
                size(successor.retained_right_samples, 2))
        for j in 1:n
            rad_right_raw += sum(
                conj.(predecessor.radial_right_samples[:, j]) .*
                successor.retained_right_samples[:, j])
            rad_right_norm_pred += norm(predecessor.radial_right_samples[:, j])^2
            rad_right_norm_succ += norm(successor.retained_right_samples[:, j])^2
        end
    end
    if successor.retained_dual_samples !== nothing
        n = min(size(predecessor.radial_dual_samples, 2),
                size(successor.retained_dual_samples, 2))
        for j in 1:n
            rad_dual_raw += sum(
                conj.(predecessor.radial_dual_samples[:, j]) .*
                successor.retained_dual_samples[:, j])
            rad_dual_norm_pred += norm(predecessor.radial_dual_samples[:, j])^2
            rad_dual_norm_succ += norm(successor.retained_dual_samples[:, j])^2
        end
    end

    rad_right_scale = max(sqrt(rad_right_norm_pred) * sqrt(rad_right_norm_succ), eps(T))
    rad_dual_scale = max(sqrt(rad_dual_norm_pred) * sqrt(rad_dual_norm_succ), eps(T))
    rad_right_normalized = rad_right_raw / rad_right_scale
    rad_dual_normalized = rad_dual_raw / rad_dual_scale
    rad_right_aligned = abs(rad_right_normalized)
    rad_dual_aligned = abs(rad_dual_normalized)
    rad_right_phase = rad_right_aligned > eps(T) ?
        conj(rad_right_normalized) / rad_right_aligned : one(Complex{T})
    rad_dual_phase = rad_dual_aligned > eps(T) ?
        conj(rad_dual_normalized) / rad_dual_aligned : one(Complex{T})

    return ContinuationEdge{T}(
        predecessor.node_identity_sha256,
        successor.node_identity_sha256,
        ang_overlap, ang_aligned, ang_phase,
        rad_right_raw, rad_right_aligned, rad_right_phase,
        rad_dual_raw, rad_dual_aligned, rad_dual_phase,
    )
end

# ---------------------------------------------------------------------------
# Public: reduce_branch
# ---------------------------------------------------------------------------

function reduce_branch(
    branch_identity::String,
    ordered_nodes::Vector{SpectralStateResult{T}},
    policy::NumericalPolicy{T},
    chain_positions::Vector{Int}=collect(0:length(ordered_nodes)-1),
    declared_gaps=Set{Tuple{Int,Int}}(),
)::BranchResult{T} where {T<:AbstractFloat}

    isempty(ordered_nodes) && error("cannot reduce an empty branch")
    isempty(branch_identity) && error("branch identity must not be empty")
    length(chain_positions) == length(ordered_nodes) ||
        error("chain_positions length does not match ordered_nodes")

    node_ids = [n.node_identity_sha256 for n in ordered_nodes]
    precisions = [n.precision_tier for n in ordered_nodes]
    edges = ContinuationEdge{T}[]
    unresolved = Tuple{Int,Int}[]

    for i in 2:length(ordered_nodes)
        pred = ordered_nodes[i-1]
        succ = ordered_nodes[i]
        p_prev = chain_positions[i-1]
        p_cur = chain_positions[i]

        # A non-unit chain-position step is a declared unresolved gap: no
        # continuation edge spans it; record the break in chain-position space.
        if p_cur != p_prev + 1
            push!(unresolved, (p_prev, p_cur))
            continue
        end

        if pred.angular_right === nothing || succ.angular_right === nothing ||
           pred.retained_right_samples === nothing || succ.retained_right_samples === nothing ||
           pred.retained_dual_samples === nothing || succ.retained_dual_samples === nothing
            push!(unresolved, (p_prev, p_cur))
            continue
        end

        retained_pred = RetainedPredecessor{T}(
            pred.node_identity_sha256,
            pred.root_identity_sha256,
            branch_identity,
            p_prev,
            pred.angular_right,
            pred.retained_right_samples !== nothing ? pred.retained_right_samples : Matrix{Complex{T}}(undef,0,0),
            pred.retained_dual_samples !== nothing ? pred.retained_dual_samples : Matrix{Complex{T}}(undef,0,0),
        )
        push!(edges, compare_continuation(retained_pred, succ, policy))
    end

    all_produced = all(n -> n.disposition == "PRODUCED", ordered_nodes)
    completion_status = all_produced && isempty(unresolved) ? "COMPLETE" : "UNRESOLVED"

    return BranchResult{T}(
        branch_identity,
        node_ids,
        edges,
        precisions,
        unresolved,
        completion_status,
        Dict{String,Any}(
            "all_produced" => all_produced,
            "declared_gap_count" => length(declared_gaps),
        ),
    )
end

# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

export CORE_SCHEMA, CORE_VERSION
export RootSeed, DomegaStencil, NumericalPolicy, RetainedPredecessor
export SpectralStateResult, BranchResult, ContinuationEdge
export solve_node, compare_continuation, reduce_branch

end
