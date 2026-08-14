module Coordinates

using ..Kerr
using Roots
using Interpolations

export rstar_from_r, r_from_rstar
export GSNBranchConvention, GSNBranchCell
export GSN_BRANCH_CONVENTION_ID, GSN_TORTOISE_BRANCH_ID
export GSN_LOG_BRANCH_CELL_ID
export GSN_INFINITY_CARRIER_ID, GSN_HORIZON_INGOING_CARRIER_ID
export GSN_HORIZON_OUTGOING_CARRIER_ID
export contour_argument, contour_angle, contour_half_plane_sign
export gsn_branch_convention, branch_cell
export full_convention_equal, branch_cell_compatible, assert_no_branch_crossing
export infinity_contour_tangent, horizon_contour_tangent
export contour_angle_deformation, assert_wave_number_matches_leg

const GSN_BRANCH_CONVENTION_ID = "gsn-complex-rho/v1"
const GSN_TORTOISE_BRANCH_ID = "analytic-continuation-from-real-rstar-match/v1"
const GSN_LOG_BRANCH_CELL_ID = "principal-frequency-argument-cut/v1"
const GSN_INFINITY_CARRIER_ID = "infinity-outgoing-plane-wave/v1"
const GSN_HORIZON_INGOING_CARRIER_ID = "horizon-ingoing-plane-wave/v1"
const GSN_HORIZON_OUTGOING_CARRIER_ID = "horizon-outgoing-plane-wave/v1"

struct GSNBranchConvention{T<:AbstractFloat}
    infinity_contour_angle::T
    horizon_contour_angle::T
    infinity_sign::Int8
    horizon_sign::Int8
    omega_argument::T
    p_horizon_argument::T
    tortoise_branch_id::String
    infinity_carrier_id::String
    horizon_ingoing_carrier_id::String
    horizon_outgoing_carrier_id::String
end

struct GSNBranchCell
    version::String
    tortoise_branch_id::String
    log_branch_cell_id::String
    infinity_carrier_id::String
    horizon_ingoing_carrier_id::String
    horizon_outgoing_carrier_id::String
    infinity_sign::Int8
    horizon_sign::Int8
end

function _real_component_type(z::Number)
    T = typeof(float(real(z)))
    T <: AbstractFloat || throw(ArgumentError("wave number must use a real floating component type"))
    return T
end

function _assert_finite_wave_number(z::Number, name::AbstractString)
    isfinite(real(z)) && isfinite(imag(z)) ||
        throw(ArgumentError("$name must have finite real and imaginary parts"))
    iszero(z) && throw(ArgumentError("$name must be nonzero so its branch carrier is defined"))
    return z
end

function contour_argument(z::Number)
    _assert_finite_wave_number(z, "wave number")
    return angle(z)
end

contour_angle(z::Number) = -contour_argument(z)

function contour_half_plane_sign(z::Number)::Int8
    _assert_finite_wave_number(z, "wave number")
    zero_real = zero(real(z))
    return real(z) >= zero_real ? Int8(1) : Int8(-1)
end

function gsn_branch_convention(omega::Number, p_horizon::Number)
    _assert_finite_wave_number(omega, "omega")
    _assert_finite_wave_number(p_horizon, "p_horizon")
    T = promote_type(_real_component_type(omega), _real_component_type(p_horizon))
    omega_value = Complex{T}(omega)
    p_horizon_value = Complex{T}(p_horizon)
    omega_argument = T(contour_argument(omega_value))
    p_horizon_argument = T(contour_argument(p_horizon_value))

    # TODO: [HUMAN MATH REVIEW REQUIRED — decide whether derivative stencils freeze only the GSN branch cell while allowing frequency-local contour angles, or freeze the full contour tangent and use q=±i z t_frozen; verify contour-deformation invariance before production activation.]
    return GSNBranchConvention{T}(
        -omega_argument,
        -p_horizon_argument,
        contour_half_plane_sign(omega_value),
        contour_half_plane_sign(p_horizon_value),
        omega_argument,
        p_horizon_argument,
        GSN_TORTOISE_BRANCH_ID,
        GSN_INFINITY_CARRIER_ID,
        GSN_HORIZON_INGOING_CARRIER_ID,
        GSN_HORIZON_OUTGOING_CARRIER_ID,
    )
end

function branch_cell(convention::GSNBranchConvention)
    return GSNBranchCell(
        GSN_BRANCH_CONVENTION_ID,
        convention.tortoise_branch_id,
        GSN_LOG_BRANCH_CELL_ID,
        convention.infinity_carrier_id,
        convention.horizon_ingoing_carrier_id,
        convention.horizon_outgoing_carrier_id,
        convention.infinity_sign,
        convention.horizon_sign,
    )
end

full_convention_equal(left::GSNBranchConvention, right::GSNBranchConvention) =
    left == right

branch_cell_compatible(left::GSNBranchConvention, right::GSNBranchConvention) =
    branch_cell(left) == branch_cell(right)

function _crosses_principal_cut(left_argument, right_argument)
    zero_angle = zero(promote_type(typeof(left_argument), typeof(right_argument)))
    return signbit(left_argument) != signbit(right_argument) &&
        cos(left_argument) < zero_angle && cos(right_argument) < zero_angle
end

function assert_no_branch_crossing(
    left::GSNBranchConvention,
    right::GSNBranchConvention,
)
    branch_cell_compatible(left, right) ||
        throw(ArgumentError("GSN branch-cell mismatch: sign, cut, or cell crossing"))
    (_crosses_principal_cut(left.omega_argument, right.omega_argument) ||
     _crosses_principal_cut(
         left.p_horizon_argument, right.p_horizon_argument
     )) && throw(ArgumentError("GSN principal-cut crossing within branch cell"))
    return nothing
end

infinity_contour_tangent(convention::GSNBranchConvention) =
    convention.infinity_sign * cis(convention.infinity_contour_angle)

horizon_contour_tangent(convention::GSNBranchConvention) =
    convention.horizon_sign * cis(convention.horizon_contour_angle)

function contour_angle_deformation(
    reference::GSNBranchConvention,
    sample::GSNBranchConvention,
)
    assert_no_branch_crossing(reference, sample)
    return (
        infinity_delta=(
            sample.infinity_contour_angle -
            reference.infinity_contour_angle
        ),
        horizon_delta=(
            sample.horizon_contour_angle -
            reference.horizon_contour_angle
        ),
    )
end

function _typed_angle_tolerance(::Type{T}) where {T<:AbstractFloat}
    return T(32) * sqrt(eps(T))
end

function _angle_distance(left::T, right::T) where {T<:AbstractFloat}
    two_pi = T(2) * T(pi)
    return abs(mod(left - right + T(pi), two_pi) - T(pi))
end

function assert_wave_number_matches_leg(
    wave_number::Number,
    convention::GSNBranchConvention,
    leg::Symbol,
)
    _assert_finite_wave_number(wave_number, String(leg))
    T = promote_type(_real_component_type(wave_number), typeof(convention.omega_argument))
    argument = T(contour_argument(Complex{T}(wave_number)))
    if leg === :infinity
        expected_argument = T(convention.omega_argument)
        expected_sign = convention.infinity_sign
    elseif leg === :horizon
        expected_argument = T(convention.p_horizon_argument)
        expected_sign = convention.horizon_sign
    else
        throw(ArgumentError("leg must be :infinity or :horizon"))
    end
    contour_half_plane_sign(wave_number) == expected_sign ||
        throw(ArgumentError("wave-number half-plane sign disagrees with GSN branch convention"))
    _angle_distance(argument, expected_argument) <= _typed_angle_tolerance(T) ||
        throw(ArgumentError("wave-number argument disagrees with GSN branch convention"))
    return nothing
end

function rstar_from_rp(a, r_from_rp)
    rp = r_plus(a)
    rm = r_minus(a)

    if abs(a) < 1
        return rp + r_from_rp + (2*1*rp)/(rp-rm) * log(r_from_rp/(2*1)) - (2*1*rm)/(rp-rm) * log((r_from_rp+rp-rm)/(2*1))
    elseif abs(a) == 1
        return rp + r_from_rp - log(4 * one(r_from_rp)) +
            2 * (log(r_from_rp) - 1 / r_from_rp)
    else
        throw(ArgumentError("a must be in the range [-1, 1]"))
    end
end

@doc raw"""
    rstar_from_r(a, r)

Convert a Boyer-Lindquist coordinate `r` to the corresponding tortoise coordinate `rstar`.
"""
function rstar_from_r(a, r)
    rp = r_plus(a)
    return rstar_from_rp(a, r-rp)
end

@doc raw"""
    r_from_rstar(a, rstar)

Convert a tortoise coordinate `rstar` to the corresponding Boyer-Lindquist coordiante `r`. 
It uses a bisection method when `rstar <= 0`, and Newton method otherwise.

The function assumes that $r \geq r_{+}$ where $r_{+}$ is the outer event horizon.
"""
function r_from_rstar(a, rstar)
    coordinate_type = promote_type(typeof(float(a)), typeof(float(rstar)))
    typed_a = coordinate_type(a)
    typed_rstar = coordinate_type(rstar)
    rp = r_plus(typed_a)
    #=
    To find r' that solves the equation rstar_from_r(r') = rstar,
    we first write r' = rp + h' and instead solve for h', then add back rp
    i.e. we solve the equation rstar_from_rp(h') = rstar
    =#

    # The root-finding algorithm might try a negative x, which is not allowed
    # We rectify this by taking an absolute value, i.e. we solve for distance from rp
    f(x) = rstar_from_rp(typed_a, abs(x)) - typed_rstar
    if typed_rstar <= zero(coordinate_type)
        #=
        When rstar <= 0, it is more efficient to use bisection method,
        this is because in this case h' is bounded (weakly),
        h' cannot be smaller than 0 (since r=rp maps to rstar=-Inf),
        and suppose h'_u solves the equation
        rstar_from_rp(h'_u) = 0.0, in which h'_u is a function of |a|
        The maximum of h'_u occurs when |a| -> 1 with value ~ 1.328
        =#
        upper_offset = coordinate_type(7) / coordinate_type(5)
        return rp + find_zero(
            f,
            (zero(coordinate_type), upper_offset),
            Roots.Bisection(),
        )
    else
        # Use Newton method instead; for large rstar, rstar \approx r
        derivative(x) = sign(x) * ((rp + abs(x))^2 + typed_a^2) /
            Delta(typed_a, rp + abs(x))
        return rp + abs(find_zero(
            (f, derivative), typed_rstar, Roots.Newton()
        ))
    end
end

function build_r_from_rstar_interpolant(a, rsin, rsout; rsstep::Float64=0.01)
    rsgrid = collect(rsin:rsstep:rsout)
    return linear_interpolation(rsgrid, (x -> r_from_rstar(a, x)).(rsgrid))
end

end
