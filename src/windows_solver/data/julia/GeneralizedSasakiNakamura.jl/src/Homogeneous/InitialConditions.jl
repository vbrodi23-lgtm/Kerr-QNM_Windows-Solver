module InitialConditions

using ..Kerr
using ..Coordinates
using ..FactoredSolutions
using ..AsymptoticExpansionCoefficients

export Xup_initialconditions, Xin_initialconditions
export fansatz, gansatz, dfansatz_dr, dgansatz_dr
export RemainderRegularityEvidence, FactoredInitialCondition
export factored_infinity_outgoing_initialconditions
export factored_horizon_ingoing_initialconditions
export factored_horizon_outgoing_initialconditions
export legacy_raw_infinity_outgoing_rho_initialconditions
export legacy_raw_horizon_ingoing_rho_initialconditions
export legacy_raw_horizon_outgoing_rho_initialconditions

const I = 1im # Mathematica being Mathematica
_DEFAULTDATATYPE = AsymptoticExpansionCoefficients._DEFAULTDATATYPE

struct RemainderRegularityEvidence{T<:AbstractFloat}
    branch::CarrierKind
    rho_endpoint::T
    r_endpoint::Complex{T}
    finite::Bool
    remainder_norm::T
    remainder_derivative_norm::T
    carrier_magnitude::T
    relative_X_reconstruction_error::T
    relative_Xrho_reconstruction_error::T
    Xrho_backward_residual::T
    carrier_operation_scale::T
    reconstruction_tolerance::T
end

struct FactoredInitialCondition{T<:AbstractFloat}
    state::FactoredEndpointState{T}
    carrier::PlaneWaveCarrier{T}
    evaluation::SeriesEvaluation{T}
    regularity::RemainderRegularityEvidence{T}
    contract::RegularRemainderContract
end

function _endpoint_error(
    reason::AsymptoticFailureReason,
    key::SeriesKey,
    message::AbstractString;
    order::Int=key.max_order,
)
    return AsymptoticConstructionError(
        reason,
        key.family,
        order,
        key.precision_bits,
        String(message),
    )
end

function _translate_endpoint_argument_error(
    operation::F,
    key::SeriesKey,
    context::AbstractString;
    argument_error_reason::AsymptoticFailureReason,
    order::Int=key.max_order,
) where {F}
    (argument_error_reason == INVALID_ASYMPTOTIC_INPUT ||
     argument_error_reason == ALGEBRAIC_REPRESENTATION_SINGULAR) ||
        throw(ArgumentError(
            "endpoint ArgumentError reason must classify the callback operation"
        ))
    try
        return operation()
    catch error
        error isa ArgumentError || rethrow()
        detail = sprint(showerror, error)
        throw(_endpoint_error(
            argument_error_reason,
            key,
            "$context failed: $detail";
            order=order,
        ))
    end
end

function _with_endpoint_precision(
    operation::F, ::Type{BigFloat}, precision_bits::Int
) where {F}
    return setprecision(BigFloat, precision_bits) do
        operation()
    end
end

function _with_endpoint_precision(
    operation::F, ::Type{T}, precision_bits::Int
) where {F,T<:AbstractFloat}
    precision(T) == precision_bits || throw(ArgumentError(
        "fixed-width endpoint type disagrees with the originating precision"
    ))
    return operation()
end

function _finite_complex(value::Complex)
    return isfinite(real(value)) && isfinite(imag(value))
end

function _assert_endpoint_real(
    key::SeriesKey{T},
    value::T,
    name::AbstractString;
    order::Int=key.max_order,
) where {T<:AbstractFloat}
    isfinite(value) || throw(_endpoint_error(
        NONFINITE_ASYMPTOTIC_DATA,
        key,
        "$name is nonfinite";
        order=order,
    ))
    precision(value) == key.precision_bits || throw(_endpoint_error(
        PRECISION_MISMATCH,
        key,
        "$name precision differs from the originating series";
        order=order,
    ))
    return value
end

function _assert_endpoint_complex(
    key::SeriesKey{T},
    value::Complex{T},
    name::AbstractString;
    order::Int=key.max_order,
) where {T<:AbstractFloat}
    _finite_complex(value) || throw(_endpoint_error(
        NONFINITE_ASYMPTOTIC_DATA,
        key,
        "$name is nonfinite";
        order=order,
    ))
    (precision(real(value)) == key.precision_bits &&
     precision(imag(value)) == key.precision_bits) || throw(_endpoint_error(
        PRECISION_MISMATCH,
        key,
        "$name precision differs from the originating series";
        order=order,
    ))
    return value
end

function _assert_endpoint_convention(
    key::SeriesKey{T},
    convention::GSNBranchConvention{T};
    order::Int=key.max_order,
) where {T<:AbstractFloat}
    for (name, value) in (
        ("infinity contour angle", convention.infinity_contour_angle),
        ("horizon contour angle", convention.horizon_contour_angle),
        ("omega argument", convention.omega_argument),
        ("horizon-wave-number argument", convention.p_horizon_argument),
    )
        _assert_endpoint_real(key, value, name; order=order)
    end
    convention.tortoise_branch_id == GSN_TORTOISE_BRANCH_ID ||
        throw(_endpoint_error(
            INVALID_ASYMPTOTIC_INPUT,
            key,
            "tortoise branch identity differs from the canonical convention";
            order=order,
        ))
    convention.infinity_carrier_id == GSN_INFINITY_CARRIER_ID ||
        throw(_endpoint_error(
            INVALID_ASYMPTOTIC_INPUT,
            key,
            "infinity carrier identity differs from the canonical convention";
            order=order,
        ))
    convention.horizon_ingoing_carrier_id ==
        GSN_HORIZON_INGOING_CARRIER_ID || throw(_endpoint_error(
            INVALID_ASYMPTOTIC_INPUT,
            key,
            "horizon-ingoing carrier identity differs from the canonical convention";
            order=order,
        ))
    convention.horizon_outgoing_carrier_id ==
        GSN_HORIZON_OUTGOING_CARRIER_ID || throw(_endpoint_error(
            INVALID_ASYMPTOTIC_INPUT,
            key,
            "horizon-outgoing carrier identity differs from the canonical convention";
            order=order,
        ))
    p_horizon = _assert_endpoint_complex(
        key,
        Complex{T}(_endpoint_wave_number(key, HORIZON_INGOING)),
        "convention horizon wave number";
        order=order,
    )
    _translate_endpoint_argument_error(
        () -> assert_wave_number_matches_leg(
            key.omega, convention, :infinity
        ),
        key,
        "infinity convention wave-number validation";
        argument_error_reason=INVALID_ASYMPTOTIC_INPUT,
        order=order,
    )
    _translate_endpoint_argument_error(
        () -> assert_wave_number_matches_leg(
            p_horizon, convention, :horizon
        ),
        key,
        "horizon convention wave-number validation";
        argument_error_reason=INVALID_ASYMPTOTIC_INPUT,
        order=order,
    )
    return convention
end

function _assert_regular_remainder_contract(
    key::SeriesKey,
    contract::RegularRemainderContract;
    order::Int=key.max_order,
)
    valid = contract.identity == regular_remainder_contract &&
        contract.scattering_columns == scattering_column_convention &&
        contract.radial_derivative == radial_derivative_convention &&
        contract.determinant == determinant_convention &&
        contract.factored_state == factored_remainder_state_convention
    valid || throw(_endpoint_error(
        INVALID_ASYMPTOTIC_INPUT,
        key,
        "regular-remainder contract identities do not match the canonical contract";
        order=order,
    ))
    return contract
end

function _expected_family(kind::CarrierKind)
    if kind === INFINITY_OUTGOING
        return INFINITY_OUTGOING_SERIES
    elseif kind === HORIZON_INGOING
        return HORIZON_INGOING_SERIES
    elseif kind === HORIZON_OUTGOING
        return HORIZON_OUTGOING_SERIES
    end
    throw(ArgumentError("unsupported endpoint carrier kind"))
end

function _assert_branch_family(
    key::SeriesKey,
    kind::CarrierKind;
    order::Int=key.max_order,
)
    key.family == _expected_family(kind) || throw(_endpoint_error(
        INVALID_ASYMPTOTIC_INPUT,
        key,
        "asymptotic series family does not match the requested endpoint branch";
        order=order,
    ))
    return key
end

function _assert_endpoint_location(
    key::SeriesKey{T},
    r::Complex{T},
    rho::T,
    kind::CarrierKind;
    order::Int=key.max_order,
) where {T<:AbstractFloat}
    if kind !== INFINITY_OUTGOING && isfinite(rho)
        geometry = stable_horizon_geometry(key.a)
        horizon_radius = complex(geometry.rplus, zero(T))
        iszero(r - horizon_radius) && throw(_endpoint_error(
            INVALID_ASYMPTOTIC_INPUT,
            key,
            "exact horizon radius r=r_plus is incompatible with a finite rho endpoint";
            order=order,
        ))
    end
    return r
end

function _endpoint_radius_from_witness(
    key::SeriesKey{T},
    rho::T,
    radius_from_rho;
    order::Int=key.max_order,
) where {T<:AbstractFloat}
    applicable(radius_from_rho, rho) || throw(_endpoint_error(
        INVALID_ASYMPTOTIC_INPUT,
        key,
        "radius_from_rho must be callable with the typed endpoint rho";
        order=order,
    ))
    radius = _translate_endpoint_argument_error(
        () -> radius_from_rho(rho),
        key,
        "radius witness";
        argument_error_reason=INVALID_ASYMPTOTIC_INPUT,
        order=order,
    )
    (radius isa T || radius isa Complex{T}) || throw(_endpoint_error(
        PRECISION_MISMATCH,
        key,
        "radius witness result does not share the originating series precision";
        order=order,
    ))
    return _assert_endpoint_complex(
        key,
        Complex{T}(radius),
        "radius witness result";
        order=order,
    )
end

function _endpoint_tangent(
    convention::GSNBranchConvention,
    kind::CarrierKind,
)
    return kind === INFINITY_OUTGOING ?
        infinity_contour_tangent(convention) :
        horizon_contour_tangent(convention)
end

function _endpoint_wave_number(
    key::SeriesKey{T}, kind::CarrierKind
) where {T<:AbstractFloat}
    if kind === INFINITY_OUTGOING
        return key.omega
    end
    geometry = stable_horizon_geometry(key.a)
    return key.omega - T(key.m) * geometry.omega_horizon
end

function _endpoint_carrier_sign(::Type{T}, kind::CarrierKind) where {T}
    return kind === HORIZON_INGOING ? -one(T) : one(T)
end

function _endpoint_radial_factor(
    key::SeriesKey{T},
    r::Complex{T},
    kind::CarrierKind;
    order::Int=key.max_order,
) where {T<:AbstractFloat}
    denominator = _assert_endpoint_complex(
        key,
        r^2 + complex(key.a^2, zero(T)),
        "endpoint radial derivative denominator";
        order=order,
    )
    iszero(denominator) && throw(_endpoint_error(
        ALGEBRAIC_REPRESENTATION_SINGULAR,
        key,
        "endpoint radial derivative denominator r^2+a^2 is zero";
        order=order,
    ))
    delta_value = if kind === INFINITY_OUTGOING
        _assert_endpoint_complex(
            key,
            Complex{T}(Delta(key.a, r)),
            "infinity Delta";
            order=order,
        )
    else
        geometry = stable_horizon_geometry(key.a)
        rplus_real = _assert_endpoint_real(
            key, geometry.rplus, "stable horizon rplus"; order=order
        )
        rminus_real = _assert_endpoint_real(
            key, geometry.rminus, "stable horizon rminus"; order=order
        )
        rplus = complex(rplus_real, zero(T))
        rminus = complex(rminus_real, zero(T))
        _assert_endpoint_complex(
            key,
            Complex{T}((r - rplus) * (r - rminus)),
            "stable horizon Delta product";
            order=order,
        )
    end
    return _assert_endpoint_complex(
        key,
        Complex{T}(delta_value / denominator),
        "endpoint radial derivative factor";
        order=order,
    )
end

function _legacy_endpoint_phase(
    key::SeriesKey{T},
    wave_number::Complex{T},
    rho::T,
    rstar_match::T,
    convention::GSNBranchConvention{T},
    kind::CarrierKind;
    order::Int=key.max_order,
) where {T<:AbstractFloat}
    imaginary_unit = complex(zero(T), one(T))
    carrier_sign = _endpoint_carrier_sign(T, kind)
    contour_sign = kind === INFINITY_OUTGOING ?
        T(convention.infinity_sign) : T(convention.horizon_sign)
    phase = exp(
        carrier_sign * imaginary_unit * contour_sign *
        abs(wave_number) * rho
    ) * exp(
        carrier_sign * imaginary_unit * wave_number * rstar_match
    )
    return _assert_endpoint_complex(
        key, Complex{T}(phase), "legacy raw endpoint phase"; order=order
    )
end

function _legacy_raw_rho_initialconditions(
    series::AsymptoticSeries{T},
    evaluation::SeriesEvaluation{T},
    r::Complex{T},
    rho::T,
    rstar_match::T,
    convention::GSNBranchConvention{T},
    kind::CarrierKind,
) where {T<:AbstractFloat}
    key = AsymptoticExpansionCoefficients._assert_evaluation_matches_series(
        series, evaluation
    )
    _assert_branch_family(key, kind; order=evaluation.order)
    _assert_endpoint_complex(key, r, "legacy raw endpoint radius";
        order=evaluation.order)
    _assert_endpoint_real(key, rho, "legacy raw endpoint rho";
        order=evaluation.order)
    _assert_endpoint_real(key, rstar_match, "legacy raw rstar match";
        order=evaluation.order)
    _assert_endpoint_convention(key, convention; order=evaluation.order)
    _assert_endpoint_location(
        key, r, rho, kind; order=evaluation.order
    )
    tangent = _assert_endpoint_complex(
        key,
        Complex{T}(_endpoint_tangent(convention, kind)),
        "legacy raw contour tangent";
        order=evaluation.order,
    )
    radial_factor = _endpoint_radial_factor(
        key, r, kind; order=evaluation.order
    )
    wave_number = _assert_endpoint_complex(
        key,
        Complex{T}(_endpoint_wave_number(key, kind)),
        "legacy raw wave number";
        order=evaluation.order,
    )
    carrier_sign = _endpoint_carrier_sign(T, kind)
    imaginary_unit = complex(zero(T), one(T))
    legacy_phase = _legacy_endpoint_phase(
        key,
        wave_number,
        rho,
        rstar_match,
        convention,
        kind;
        order=evaluation.order,
    )
    X = _assert_endpoint_complex(
        key,
        Complex{T}(legacy_phase * evaluation.series_eval_horner),
        "legacy raw endpoint X";
        order=evaluation.order,
    )
    Xrho = _assert_endpoint_complex(
        key,
        Complex{T}(
            tangent * legacy_phase * (
                carrier_sign * imaginary_unit * wave_number *
                evaluation.series_eval_horner +
                radial_factor * evaluation.series_derivative_horner
            )
        ),
        "legacy raw endpoint Xrho";
        order=evaluation.order,
    )
    return RawEndpointState{T}(X, Xrho)
end

function _relative_reconstruction_error(
    ::Type{T}, reconstructed::Complex{T}, legacy::Complex{T}
) where {T<:AbstractFloat}
    scale = max(abs(reconstructed), abs(legacy), floatmin(T))
    return abs(reconstructed - legacy) / scale
end

function _carrier_operation_scale(
    key::SeriesKey{T},
    carrier::PlaneWaveCarrier{T},
    rho::T;
    order::Int=key.max_order,
) where {T<:AbstractFloat}
    endpoint_log = _translate_endpoint_argument_error(
        () -> carrier_log(carrier, rho),
        key,
        "carrier logarithm";
        argument_error_reason=ALGEBRAIC_REPRESENTATION_SINGULAR,
        order=order,
    )
    scale = max(
        one(T),
        abs(carrier.log_at_match),
        abs(carrier.q * rho),
        abs(endpoint_log),
    )
    return _assert_endpoint_real(
        key, scale, "carrier operation scale"; order=order
    )
end

function _scale_aware_reconstruction_tolerance(
    ::Type{T}, carrier_operation_scale::T
) where {T<:AbstractFloat}
    # This is an algebraic-equivalence allowance for carrier exponent and
    # argument-reduction operations, not an ODE/truncation tolerance. The cap
    # keeps branch-sign and tangent defects load-bearing at long contour legs.
    return min(sqrt(eps(T)), T(256) * eps(T) * carrier_operation_scale)
end

function _Xrho_backward_residual(
    ::Type{T},
    A::Complex{T},
    q::Complex{T},
    state::FactoredEndpointState{T},
    legacy::RawEndpointState{T},
) where {T<:AbstractFloat}
    residual = A * state.Yrho + A * q * state.Y - legacy.Xrho
    component_scale = abs(A * state.Yrho) + abs(A * q * state.Y) +
        abs(legacy.Xrho) + floatmin(T)
    return abs(residual) / component_scale
end

function _assert_reconstruction_within_tolerance(
    key::SeriesKey{T},
    relative_X_error::T,
    Xrho_backward_residual::T,
    tolerance::T;
    order::Int=key.max_order,
) where {T<:AbstractFloat}
    maximum_error = max(relative_X_error, Xrho_backward_residual)
    maximum_error <= tolerance || throw(_endpoint_error(
        ALGEBRAIC_REPRESENTATION_SINGULAR,
        key,
        "raw/factored endpoint reconstruction exceeds the typed algebraic tolerance";
        order=order,
    ))
    return nothing
end

function _regularity_evidence(
    key::SeriesKey{T},
    state::FactoredEndpointState{T},
    carrier::PlaneWaveCarrier{T},
    legacy::RawEndpointState{T},
    r::Complex{T},
    rho::T;
    order::Int=key.max_order,
) where {T<:AbstractFloat}
    reconstructed = _translate_endpoint_argument_error(
        () -> reconstruct_state(state, carrier, rho),
        key,
        "raw endpoint reconstruction";
        argument_error_reason=ALGEBRAIC_REPRESENTATION_SINGULAR,
        order=order,
    )
    A = _translate_endpoint_argument_error(
        () -> carrier_value(carrier, rho),
        key,
        "carrier value";
        argument_error_reason=ALGEBRAIC_REPRESENTATION_SINGULAR,
        order=order,
    )
    carrier_magnitude = abs(A)
    relative_X_reconstruction_error = _relative_reconstruction_error(
        T, reconstructed.X, legacy.X
    )
    relative_Xrho_reconstruction_error = _relative_reconstruction_error(
        T, reconstructed.Xrho, legacy.Xrho
    )
    Xrho_backward_residual = _Xrho_backward_residual(
        T, A, carrier_log_derivative(carrier), state, legacy
    )
    carrier_operation_scale = _carrier_operation_scale(
        key, carrier, rho; order=order
    )
    reconstruction_tolerance = _scale_aware_reconstruction_tolerance(
        T, carrier_operation_scale
    )
    remainder_norm = abs(state.Y)
    remainder_derivative_norm = abs(state.Yrho)
    finite = _finite_complex(r) && isfinite(rho) &&
        _finite_complex(state.Y) && _finite_complex(state.Yrho) &&
        isfinite(remainder_norm) && isfinite(remainder_derivative_norm) &&
        isfinite(carrier_magnitude) &&
        isfinite(relative_X_reconstruction_error) &&
        isfinite(relative_Xrho_reconstruction_error) &&
        isfinite(Xrho_backward_residual) &&
        isfinite(carrier_operation_scale) &&
        isfinite(reconstruction_tolerance)
    finite || throw(_endpoint_error(
        NONFINITE_ASYMPTOTIC_DATA,
        key,
        "regular-remainder endpoint evidence is nonfinite";
        order=order,
    ))
    for (name, value) in (
        ("remainder norm", remainder_norm),
        ("remainder derivative norm", remainder_derivative_norm),
        ("carrier magnitude", carrier_magnitude),
        ("relative X reconstruction error", relative_X_reconstruction_error),
        ("relative Xrho reconstruction error", relative_Xrho_reconstruction_error),
        ("Xrho backward residual", Xrho_backward_residual),
        ("carrier operation scale", carrier_operation_scale),
        ("reconstruction tolerance", reconstruction_tolerance),
    )
        _assert_endpoint_real(key, value, name; order=order)
    end
    return RemainderRegularityEvidence{T}(
        carrier.kind,
        rho,
        r,
        finite,
        remainder_norm,
        remainder_derivative_norm,
        carrier_magnitude,
        relative_X_reconstruction_error,
        relative_Xrho_reconstruction_error,
        Xrho_backward_residual,
        carrier_operation_scale,
        reconstruction_tolerance,
    )
end

function _evaluate_endpoint_series(
    series::AsymptoticSeries,
    r::Number,
    kind::CarrierKind,
    order::Int,
)
    if kind === INFINITY_OUTGOING
        return evaluate_infinity_asymptotic_series(series, r; order=order)
    end
    return evaluate_horizon_asymptotic_series(series, r; order=order)
end

function _factored_endpoint_initialconditions(
    series::AsymptoticSeries{T},
    rho::T,
    rstar_match::T,
    radius_from_rho,
    convention::GSNBranchConvention{T},
    contract::RegularRemainderContract,
    kind::CarrierKind;
    order::Int=series.key.max_order,
) where {T<:AbstractFloat}
    return _with_endpoint_precision(T, series.key.precision_bits) do
        key = series.key
        _assert_endpoint_real(key, rho, "factored endpoint rho"; order=order)
        _assert_endpoint_real(
            key, rstar_match, "factored endpoint rstar match"; order=order
        )
        typed_r = _endpoint_radius_from_witness(
            key, rho, radius_from_rho; order=order
        )
        _assert_endpoint_convention(key, convention; order=order)
        _assert_regular_remainder_contract(key, contract; order=order)
        _assert_branch_family(key, kind; order=order)
        _assert_endpoint_location(key, typed_r, rho, kind; order=order)
        evaluation = _evaluate_endpoint_series(
            series, typed_r, kind, order
        )
        tangent = _assert_endpoint_complex(
            key,
            Complex{T}(_endpoint_tangent(convention, kind)),
            "factored endpoint contour tangent";
            order=order,
        )
        radial_factor = _endpoint_radial_factor(
            key, typed_r, kind; order=order
        )
        state = FactoredEndpointState{T}(
            evaluation.series_eval_horner,
            tangent * radial_factor *
                evaluation.series_derivative_horner,
        )
        _assert_endpoint_complex(key, state.Y, "factored endpoint Y";
            order=order)
        _assert_endpoint_complex(key, state.Yrho, "factored endpoint Yrho";
            order=order)
        wave_number = _assert_endpoint_complex(
            key,
            Complex{T}(_endpoint_wave_number(key, kind)),
            "factored endpoint carrier wave number";
            order=order,
        )
        carrier = _translate_endpoint_argument_error(
            () -> PlaneWaveCarrier(
                kind, wave_number, rstar_match, convention
            ),
            key,
            "plane-wave carrier construction";
            argument_error_reason=INVALID_ASYMPTOTIC_INPUT,
            order=order,
        )
        legacy = _legacy_raw_rho_initialconditions(
            series,
            evaluation,
            typed_r,
            rho,
            rstar_match,
            convention,
            kind,
        )
        regularity = _regularity_evidence(
            key,
            state,
            carrier,
            legacy,
            typed_r,
            rho;
            order=order,
        )
        _assert_reconstruction_within_tolerance(
            key,
            regularity.relative_X_reconstruction_error,
            regularity.Xrho_backward_residual,
            regularity.reconstruction_tolerance;
            order=order,
        )
        return FactoredInitialCondition{T}(
            state, carrier, evaluation, regularity, contract
        )
    end
end

function legacy_raw_infinity_outgoing_rho_initialconditions(
    series::AsymptoticSeries{T},
    evaluation::SeriesEvaluation{T},
    r::Union{T,Complex{T}},
    rho::T,
    rstar_match::T,
    convention::GSNBranchConvention{T},
) where {T<:AbstractFloat}
    return _with_endpoint_precision(T, series.key.precision_bits) do
        _legacy_raw_rho_initialconditions(
            series,
            evaluation,
            Complex{T}(r),
            rho,
            rstar_match,
            convention,
            INFINITY_OUTGOING,
        )
    end
end

function legacy_raw_horizon_ingoing_rho_initialconditions(
    series::AsymptoticSeries{T},
    evaluation::SeriesEvaluation{T},
    r::Union{T,Complex{T}},
    rho::T,
    rstar_match::T,
    convention::GSNBranchConvention{T},
) where {T<:AbstractFloat}
    return _with_endpoint_precision(T, series.key.precision_bits) do
        _legacy_raw_rho_initialconditions(
            series,
            evaluation,
            Complex{T}(r),
            rho,
            rstar_match,
            convention,
            HORIZON_INGOING,
        )
    end
end

function legacy_raw_horizon_outgoing_rho_initialconditions(
    series::AsymptoticSeries{T},
    evaluation::SeriesEvaluation{T},
    r::Union{T,Complex{T}},
    rho::T,
    rstar_match::T,
    convention::GSNBranchConvention{T},
) where {T<:AbstractFloat}
    return _with_endpoint_precision(T, series.key.precision_bits) do
        _legacy_raw_rho_initialconditions(
            series,
            evaluation,
            Complex{T}(r),
            rho,
            rstar_match,
            convention,
            HORIZON_OUTGOING,
        )
    end
end

function factored_infinity_outgoing_initialconditions(
    series::AsymptoticSeries{T},
    rho::T,
    rstar_match::T,
    radius_from_rho,
    convention::GSNBranchConvention{T},
    contract::RegularRemainderContract;
    order::Int=series.key.max_order,
) where {T<:AbstractFloat}
    return _factored_endpoint_initialconditions(
        series,
        rho,
        rstar_match,
        radius_from_rho,
        convention,
        contract,
        INFINITY_OUTGOING;
        order=order,
    )
end

function factored_horizon_ingoing_initialconditions(
    series::AsymptoticSeries{T},
    rho::T,
    rstar_match::T,
    radius_from_rho,
    convention::GSNBranchConvention{T},
    contract::RegularRemainderContract;
    order::Int=series.key.max_order,
) where {T<:AbstractFloat}
    return _factored_endpoint_initialconditions(
        series,
        rho,
        rstar_match,
        radius_from_rho,
        convention,
        contract,
        HORIZON_INGOING;
        order=order,
    )
end

function factored_horizon_outgoing_initialconditions(
    series::AsymptoticSeries{T},
    rho::T,
    rstar_match::T,
    radius_from_rho,
    convention::GSNBranchConvention{T},
    contract::RegularRemainderContract;
    order::Int=series.key.max_order,
) where {T<:AbstractFloat}
    return _factored_endpoint_initialconditions(
        series,
        rho,
        rstar_match,
        radius_from_rho,
        convention,
        contract,
        HORIZON_OUTGOING;
        order=order,
    )
end

function _mixed_endpoint_precision_error(
    series::AsymptoticSeries, function_name::AbstractString
)
    throw(_endpoint_error(
        PRECISION_MISMATCH,
        series.key,
        "$function_name inputs do not share the originating series precision",
    ))
end

function factored_infinity_outgoing_initialconditions(
    series::AsymptoticSeries,
    rho::Real,
    rstar_match::Real,
    radius_from_rho,
    convention::GSNBranchConvention,
    contract::RegularRemainderContract;
    order::Int=series.key.max_order,
)
    return _mixed_endpoint_precision_error(
        series, "factored_infinity_outgoing_initialconditions"
    )
end

function factored_horizon_ingoing_initialconditions(
    series::AsymptoticSeries,
    rho::Real,
    rstar_match::Real,
    radius_from_rho,
    convention::GSNBranchConvention,
    contract::RegularRemainderContract;
    order::Int=series.key.max_order,
)
    return _mixed_endpoint_precision_error(
        series, "factored_horizon_ingoing_initialconditions"
    )
end

function factored_horizon_outgoing_initialconditions(
    series::AsymptoticSeries,
    rho::Real,
    rstar_match::Real,
    radius_from_rho,
    convention::GSNBranchConvention,
    contract::RegularRemainderContract;
    order::Int=series.key.max_order,
)
    return _mixed_endpoint_precision_error(
        series, "factored_horizon_outgoing_initialconditions"
    )
end

function fansatz(func, omega, r; order=3)
    # A template function that gives the asymptotic expansion at infinity
    ans = zero(omega * r)
    for i in 0:order
        ans += func(i)/((omega*r)^i)
    end
    return ans
end

function dfansatz_dr(func, omega, r; order=3)
    # A template function that gives the derivative of the asymptotic expansion at infinity
    ans = zero(omega * r)
    for i in 1:order
        ans += -i*func(i)/(omega^i * r^(i+1))
    end
    return ans
end

function gansatz(func, a, r; order=1)
    # A template function that gives the asymptotic expansion at horizon
    ans = zero(a + r)
    for i in 0:order
        ans += func(i)*(r-r_plus(a))^i
    end
    return ans
end

function dgansatz_dr(func, a, r; order=1)
    # A template function that gives the derivative of the asymptotic expansion at horizon
    ans = zero(a + r)
    for i in 1:order
        ans += i*func(i)*(r-r_plus(a))^(i-1)
    end
    return ans
end

function Xup_initialconditions(s::Int, m::Int, a, omega, lambda, rsout; order::Int=-1, dtype=_DEFAULTDATATYPE)
    #=
    We have derived/shown the explicit expression for
    different physically-relevant spin weight (s=0, \pm 1, \pm2)
    =#
    _default_order = 3
    order = (order == -1 ? _default_order : order)

    outgoing_coeff_func(ord) = outgoing_coefficient_at_inf(s, m, a, omega, lambda, ord; data_type=dtype)
    fout(r) = fansatz(outgoing_coeff_func, omega, r; order=order)
    dfout_dr(r) = dfansatz_dr(outgoing_coeff_func, omega, r; order=order)
    rout = r_from_rstar(a, rsout)

    _fansatz = fout(rout)
    _dfansatz_dr = dfout_dr(rout)
    phase = exp(1im * omega * rsout)

    return phase*_fansatz, phase*(1im*omega*_fansatz + (Delta(a, rout)/(rout^2 + a^2))*_dfansatz_dr)
end

function Xin_initialconditions(s::Int, m::Int, a, omega, lambda, rsin; order::Int=-1, dtype=_DEFAULTDATATYPE)
    #=
    For Xin, which we obtain by integrating from r_* -> -inf (or r -> r_+),

    Write Xin = \sum_j C^{H}_{-} (r - r_+)^j

    =#
    _default_order = 0
    order = (order == -1 ? _default_order : order)

    ingoing_coeff_func(ord) = ingoing_coefficient_at_hor(s, m, a, omega, lambda, ord; data_type=dtype)
    gin(r) = gansatz(ingoing_coeff_func, a, r; order=order)
    dgin_dr(r) = dgansatz_dr(ingoing_coeff_func, a, r; order=order)
    rin = r_from_rstar(a, rsin)

    _gansatz = gin(rin)
    _dgansatz_dr = dgin_dr(rin)
    p = omega - m*omega_horizon(a)
    phase = exp(-1im * p * rsin)

    return phase*_gansatz, phase*(-1im*p*_gansatz + (Delta(a, rin)/(rin^2 + a^2))*_dgansatz_dr)
end

end
