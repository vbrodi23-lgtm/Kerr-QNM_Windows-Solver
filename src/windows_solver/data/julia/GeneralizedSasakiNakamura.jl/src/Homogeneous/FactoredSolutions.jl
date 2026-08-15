module FactoredSolutions

using ..Coordinates:
    GSNBranchConvention,
    assert_no_branch_crossing,
    assert_wave_number_matches_leg

export CarrierKind, INFINITY_OUTGOING, HORIZON_INGOING, HORIZON_OUTGOING
export RegularRemainderContract
export regular_remainder_contract
export scattering_column_convention, radial_derivative_convention
export determinant_convention, factored_remainder_state_convention
export PlaneWaveCarrier, FactoredEndpointState, RawEndpointState
export CarrierChangeDiagnostics
export carrier_log, carrier_value, carrier_log_derivative
export carrier_log_derivative_derivative
export reconstruct_state, factor_state, change_carrier
export carrier_change_diagnostics
export horizon_carrier_with_explicit_tangent, factor_physical_match_state
export real_inner_horizon_contour_id
export horizon_basis_at_match_extraction_id
export human_math_review_receipt_status, human_math_review_receipt_sha256
export independent_reference_fixture_receipt_status
export independent_reference_fixture_receipt_sha256
export assert_human_math_review_receipt_available
export assert_independent_reference_fixture_available
export assert_regularised_gsn_production_ready

const REGULAR_REMAINDER_CONTRACT_ID =
    "known-carrier-times-regular-remainder/v1"
const REAL_INNER_HORIZON_CONTOUR_ID = "real-inner-tortoise-contour/v1"
const real_inner_horizon_contour_id = REAL_INNER_HORIZON_CONTOUR_ID
const HORIZON_BASIS_AT_MATCH_EXTRACTION_ID =
    "scaled-horizon-basis-at-match/v1"
const horizon_basis_at_match_extraction_id =
    HORIZON_BASIS_AT_MATCH_EXTRACTION_ID
const regular_remainder_contract = REGULAR_REMAINDER_CONTRACT_ID
const scattering_column_convention =
    "column1=horizon-ingoing-Cref;column2=horizon-outgoing-Cinc/v1"
const radial_derivative_convention = "state2=dX/drho/v1"
const determinant_convention = "cinc-over-cref-minus-R/v1"
const factored_remainder_state_convention = "state1=Y;state2=dY/drho/v1"
const human_math_review_receipt_status = "absent-unapproved/v1"
const human_math_review_receipt_sha256 = nothing
const independent_reference_fixture_receipt_status = "absent-unreviewed/v1"
const independent_reference_fixture_receipt_sha256 = nothing

struct RegularRemainderContract
    identity::String
    scattering_columns::String
    radial_derivative::String
    determinant::String
    factored_state::String
end

RegularRemainderContract() = RegularRemainderContract(
    REGULAR_REMAINDER_CONTRACT_ID,
    scattering_column_convention,
    radial_derivative_convention,
    determinant_convention,
    factored_remainder_state_convention,
)

@enum CarrierKind begin
    INFINITY_OUTGOING = 1
    HORIZON_INGOING = 2
    HORIZON_OUTGOING = 3
end

struct PlaneWaveCarrier{T<:AbstractFloat}
    kind::CarrierKind
    wave_number::Complex{T}
    rstar_match::T
    log_at_match::Complex{T}
    q::Complex{T}
    convention::GSNBranchConvention{T}
end

function _finite_complex(value::Complex)
    return isfinite(real(value)) && isfinite(imag(value))
end

function _convert_convention(
    ::Type{T},
    convention::GSNBranchConvention,
) where {T<:AbstractFloat}
    return GSNBranchConvention{T}(
        T(convention.infinity_contour_angle),
        T(convention.horizon_contour_angle),
        convention.infinity_sign,
        convention.horizon_sign,
        T(convention.omega_argument),
        T(convention.p_horizon_argument),
        convention.tortoise_branch_id,
        convention.infinity_carrier_id,
        convention.horizon_ingoing_carrier_id,
        convention.horizon_outgoing_carrier_id,
    )
end

function PlaneWaveCarrier(
    kind::CarrierKind,
    wave_number::Number,
    rstar_match::Real,
    convention::GSNBranchConvention,
)
    T = promote_type(
        typeof(float(real(wave_number))),
        typeof(float(rstar_match)),
        typeof(convention.omega_argument),
    )
    T <: AbstractFloat || throw(ArgumentError("carrier inputs must promote to an AbstractFloat"))
    z = Complex{T}(wave_number)
    match_point = T(rstar_match)
    _finite_complex(z) || throw(ArgumentError("carrier wave number must be finite"))
    iszero(z) && throw(ArgumentError("carrier wave number must be nonzero"))
    isfinite(match_point) || throw(ArgumentError("rstar_match must be finite"))
    typed_convention = _convert_convention(T, convention)

    if kind === INFINITY_OUTGOING
        assert_wave_number_matches_leg(z, typed_convention, :infinity)
        direction = T(typed_convention.infinity_sign)
        log_at_match = complex(zero(T), one(T)) * z * match_point
        q = complex(zero(T), one(T)) * direction * abs(z)
    elseif kind === HORIZON_INGOING
        assert_wave_number_matches_leg(z, typed_convention, :horizon)
        direction = T(typed_convention.horizon_sign)
        log_at_match = -complex(zero(T), one(T)) * z * match_point
        q = -complex(zero(T), one(T)) * direction * abs(z)
    elseif kind === HORIZON_OUTGOING
        assert_wave_number_matches_leg(z, typed_convention, :horizon)
        direction = T(typed_convention.horizon_sign)
        log_at_match = complex(zero(T), one(T)) * z * match_point
        q = complex(zero(T), one(T)) * direction * abs(z)
    else
        throw(ArgumentError("unsupported carrier kind"))
    end

    # TODO: [HUMAN MATH REVIEW REQUIRED — verify the branch-specific plane-wave carriers, the transformed complex-contour GSN equation, the carrier change at ρ=0, the factored horizon basis, and the Cinc/Cref determinant chart against the current GSN amplitude and branch conventions.]
    return PlaneWaveCarrier{T}(
        kind, z, match_point, log_at_match, q, typed_convention
    )
end

function carrier_log(carrier::PlaneWaveCarrier{T}, rho::Real) where {T}
    typed_rho = T(rho)
    isfinite(typed_rho) || throw(ArgumentError("rho must be finite"))
    value = carrier.log_at_match + carrier.q * typed_rho
    _finite_complex(value) || throw(ArgumentError("carrier logarithm is nonfinite"))
    return value
end

function carrier_value(carrier::PlaneWaveCarrier, rho::Real)
    value = exp(carrier_log(carrier, rho))
    _finite_complex(value) || throw(ArgumentError("carrier value is nonfinite"))
    iszero(value) && throw(ArgumentError("carrier value underflowed to zero"))
    return value
end

carrier_log_derivative(carrier::PlaneWaveCarrier) = carrier.q
carrier_log_derivative_derivative(carrier::PlaneWaveCarrier{T}) where {T} =
    zero(Complex{T})

struct FactoredEndpointState{T<:AbstractFloat}
    Y::Complex{T}
    Yrho::Complex{T}
end

function FactoredEndpointState(Y::Number, Yrho::Number)
    T = promote_type(typeof(float(real(Y))), typeof(float(real(Yrho))))
    state = FactoredEndpointState{T}(Complex{T}(Y), Complex{T}(Yrho))
    _finite_complex(state.Y) && _finite_complex(state.Yrho) ||
        throw(ArgumentError("factored endpoint state must be finite"))
    return state
end

struct RawEndpointState{T<:AbstractFloat}
    X::Complex{T}
    Xrho::Complex{T}
end

function _raw_endpoint_state(X::Number, Xrho::Number)
    T = promote_type(typeof(float(real(X))), typeof(float(real(Xrho))))
    state = RawEndpointState{T}(Complex{T}(X), Complex{T}(Xrho))
    _finite_complex(state.X) && _finite_complex(state.Xrho) ||
        throw(ArgumentError("raw endpoint state must be finite"))
    return state
end

function reconstruct_state(
    state::FactoredEndpointState,
    carrier::PlaneWaveCarrier,
    rho::Real,
)
    A = carrier_value(carrier, rho)
    q = carrier_log_derivative(carrier)
    X = A * state.Y
    Xrho = A * (state.Yrho + q * state.Y)
    return _raw_endpoint_state(X, Xrho)
end

function factor_state(
    X::Number,
    Xrho::Number,
    carrier::PlaneWaveCarrier,
    rho::Real,
)
    raw = _raw_endpoint_state(X, Xrho)
    A = carrier_value(carrier, rho)
    q = carrier_log_derivative(carrier)
    Y = raw.X / A
    Yrho = raw.Xrho / A - q * Y
    return FactoredEndpointState(Y, Yrho)
end

"""
    horizon_carrier_with_explicit_tangent(kind, wave_number, rstar_match,
                                          convention, tangent)

Return the horizon plane-wave carrier whose exponent derivative follows an
explicitly supplied tortoise tangent instead of the frequency-aligned contour
tangent implied by `convention`.

The real-inner horizon contour advances `r_*` along the positive real axis, so
its tangent is `1 + 0im` rather than the deformed infinity tangent. The carrier
logarithm at the matching point is unchanged; only the exponent derivative

    q = ∓ i * p_horizon * tangent

is rebound, with the minus sign taken for `HORIZON_INGOING` and the plus sign
for `HORIZON_OUTGOING`. Keeping `log_at_match` canonical means a state factored
against this carrier remains directly comparable with the canonical horizon
carriers at `rho = 0`.
"""
function horizon_carrier_with_explicit_tangent(
    kind::CarrierKind,
    wave_number::Number,
    rstar_match::Real,
    convention::GSNBranchConvention,
    tangent::Number,
)
    (kind === HORIZON_INGOING || kind === HORIZON_OUTGOING) ||
        throw(ArgumentError(
            "explicit-tangent carrier must be a horizon branch"
        ))
    canonical = PlaneWaveCarrier(
        kind, wave_number, rstar_match, convention
    )
    T = typeof(canonical.rstar_match)
    typed_tangent = Complex{T}(tangent)
    _finite_complex(typed_tangent) ||
        throw(ArgumentError("explicit carrier tangent must be finite"))
    iszero(typed_tangent) &&
        throw(ArgumentError("explicit carrier tangent must be nonzero"))
    carrier_sign = kind === HORIZON_INGOING ? -one(T) : one(T)
    q = carrier_sign * complex(zero(T), one(T)) *
        canonical.wave_number * typed_tangent
    _finite_complex(q) ||
        throw(ArgumentError("explicit-tangent carrier q is nonfinite"))
    return PlaneWaveCarrier{T}(
        canonical.kind,
        canonical.wave_number,
        canonical.rstar_match,
        canonical.log_at_match,
        q,
        canonical.convention,
    )
end

"""
    factor_physical_match_state(X, dX_drstar, carrier, tangent)

Factor a physical matching-point state given as `(X, dX/dr_*)` against
`carrier`, whose contour advances `r_*` with the supplied `tangent`.

The factored state convention stores `dY/dρ`, so the supplied tortoise
derivative is converted with `dX/dρ = tangent * dX/dr_*` before factoring at
`ρ = 0`. This is the conversion that lets an infinity-contour solution be
compared against horizon-contour columns that use a different tangent.
"""
function factor_physical_match_state(
    X::Number,
    dX_drstar::Number,
    carrier::PlaneWaveCarrier{T},
    tangent::Number,
) where {T<:AbstractFloat}
    typed_X = Complex{T}(X)
    typed_derivative = Complex{T}(dX_drstar)
    typed_tangent = Complex{T}(tangent)
    _finite_complex(typed_X) && _finite_complex(typed_derivative) ||
        throw(ArgumentError("physical match state must be finite"))
    _finite_complex(typed_tangent) ||
        throw(ArgumentError("physical match tangent must be finite"))
    iszero(typed_tangent) &&
        throw(ArgumentError("physical match tangent must be nonzero"))
    return factor_state(
        typed_X, typed_tangent * typed_derivative, carrier, zero(T)
    )
end

function _assert_carrier_change_compatible(
    source::PlaneWaveCarrier,
    target::PlaneWaveCarrier,
)
    assert_no_branch_crossing(source.convention, target.convention)
    return nothing
end

function _carrier_ratio(
    source::PlaneWaveCarrier,
    target::PlaneWaveCarrier,
    rho::Real,
)
    _assert_carrier_change_compatible(source, target)
    ratio = exp(carrier_log(source, rho) - carrier_log(target, rho))
    _finite_complex(ratio) || throw(ArgumentError("carrier ratio is nonfinite"))
    iszero(ratio) && throw(ArgumentError("carrier ratio underflowed to zero"))
    return ratio
end

function change_carrier(
    state::FactoredEndpointState,
    source::PlaneWaveCarrier,
    target::PlaneWaveCarrier,
    rho::Real,
)
    ratio = _carrier_ratio(source, target, rho)
    q_difference = (
        carrier_log_derivative(source) -
        carrier_log_derivative(target)
    )
    return FactoredEndpointState(
        ratio * state.Y,
        ratio * (state.Yrho + q_difference * state.Y),
    )
end

struct CarrierChangeDiagnostics{T<:AbstractFloat}
    X_reconstruction_error::T
    Xrho_reconstruction_error::T
    carrier_ratio_magnitude::T
    carrier_ratio_phase::T
end

function carrier_change_diagnostics(
    source_state::FactoredEndpointState,
    target_state::FactoredEndpointState,
    source::PlaneWaveCarrier,
    target::PlaneWaveCarrier,
    rho::Real,
)
    ratio = _carrier_ratio(source, target, rho)
    source_raw = reconstruct_state(source_state, source, rho)
    target_raw = reconstruct_state(target_state, target, rho)
    T = promote_type(
        typeof(real(source_raw.X)),
        typeof(real(target_raw.X)),
        typeof(real(ratio)),
    )
    magnitude = T(abs(ratio))
    phase = T(atan(imag(ratio), real(ratio)))
    all(isfinite, (magnitude, phase)) ||
        throw(ArgumentError("carrier-change diagnostics are nonfinite"))
    return CarrierChangeDiagnostics{T}(
        T(abs(target_raw.X - source_raw.X)),
        T(abs(target_raw.Xrho - source_raw.Xrho)),
        magnitude,
        phase,
    )
end

function assert_independent_reference_fixture_available()
    error(
        "production activation blocked: independent high-precision GSN " *
        "reference fixture has not been reviewed and frozen"
    )
end

function assert_human_math_review_receipt_available()
    error(
        "production activation blocked: human mathematical review receipt " *
        "has not been approved"
    )
end

"""
    assert_regularised_gsn_production_ready()

Fail unless every external reference required to admit regularised-GSN
mathematical claims is available. Evidence-generating numerical solvers do not
call this gate: their emitted receipt statuses remain explicitly unapproved, and
the scientific-claim/release boundary must call this gate before admission.
"""
function assert_regularised_gsn_production_ready()
    assert_human_math_review_receipt_available()
    assert_independent_reference_fixture_available()
    return nothing
end

end
