module AsymptoticExpansionCoefficients

using TaylorSeries
using ..Kerr
using ..Coordinates

export outgoing_coefficient_at_inf, ingoing_coefficient_at_inf
export outgoing_coefficient_at_hor, ingoing_coefficient_at_hor
export AsymptoticFamily
export INFINITY_INGOING_SERIES, INFINITY_OUTGOING_SERIES
export HORIZON_INGOING_SERIES, HORIZON_OUTGOING_SERIES
export AsymptoticFailureReason, AsymptoticConstructionError
export INVALID_ASYMPTOTIC_INPUT, INVALID_ASYMPTOTIC_ORDER
export PRECISION_MISMATCH, NONFINITE_ASYMPTOTIC_DATA
export PHYSICAL_SINGULAR_LIMIT, ALGEBRAIC_REPRESENTATION_SINGULAR
export SeriesKey, TypedTaylorWorkspace, RecurrenceEvidence
export AsymptoticSeries, AsymptoticSeriesBundle
export build_asymptotic_series, build_asymptotic_series_bundle
export build_infinity_recurrence_from_zero
export SeriesEvaluation, AsymptoticConditioningAssessment
export ASYMPTOTIC_CONDITIONING_ESTIMATE_KIND
export evaluate_asymptotic_series
export evaluate_infinity_asymptotic_series, evaluate_horizon_asymptotic_series
export assess_asymptotic_preflight

const I = 1im # Mathematica being Mathematica
_DEFAULTDATATYPE = ComplexF64 # Double precision by default
const ASYMPTOTIC_CONDITIONING_ESTIMATE_KIND =
    "empirical-three-way-series-conditioning/not-a-bound/v1"

@enum AsymptoticFamily begin
    INFINITY_INGOING_SERIES = 1
    INFINITY_OUTGOING_SERIES = 2
    HORIZON_INGOING_SERIES = 3
    HORIZON_OUTGOING_SERIES = 4
end

@enum AsymptoticFailureReason begin
    INVALID_ASYMPTOTIC_INPUT = 1
    INVALID_ASYMPTOTIC_ORDER = 2
    PRECISION_MISMATCH = 3
    NONFINITE_ASYMPTOTIC_DATA = 4
    PHYSICAL_SINGULAR_LIMIT = 5
    ALGEBRAIC_REPRESENTATION_SINGULAR = 6
end

struct AsymptoticConstructionError <: Exception
    reason::AsymptoticFailureReason
    family::Union{Nothing,AsymptoticFamily}
    order::Int
    precision_bits::Int
    message::String
end

function Base.showerror(io::IO, error::AsymptoticConstructionError)
    print(
        io,
        string(error.reason),
        ": ",
        error.message,
        " (family=", error.family,
        ", order=", error.order,
        ", precision_bits=", error.precision_bits,
        ")",
    )
end

struct SeriesKey{T<:AbstractFloat}
    s::Int
    m::Int
    a::T
    omega::Complex{T}
    lambda::Complex{T}
    family::AsymptoticFamily
    max_order::Int
    precision_bits::Int

    # Suppress Julia's automatically generated unvalidated outer constructor.
    # All inferred-type construction must pass through the checked SeriesKey
    # method below before reaching this exact typed storage constructor.
    function SeriesKey{T}(
        s::Int,
        m::Int,
        a::T,
        omega::Complex{T},
        lambda::Complex{T},
        family::AsymptoticFamily,
        max_order::Int,
        precision_bits::Int,
    ) where {T<:AbstractFloat}
        return new{T}(
            s,
            m,
            a,
            omega,
            lambda,
            family,
            max_order,
            precision_bits,
        )
    end
end

struct TypedTaylorWorkspace{T<:AbstractFloat}
    center::Complex{T}
    coefficients::Vector{Complex{T}}
end

struct RecurrenceEvidence{T<:AbstractFloat}
    denominator_value::Complex{T}
    denominator_scale::T
    value_scale::T
    recurrence_term_abs_sum::T
    cancellation_factor::T
    cancellation_digits::T
    family::AsymptoticFamily
    order::Int
    precision_bits::Int
end

struct AsymptoticSeries{T<:AbstractFloat}
    key::SeriesKey{T}
    coefficients::Vector{Complex{T}}
    P::TypedTaylorWorkspace{T}
    Q::TypedTaylorWorkspace{T}
    evidence::Vector{RecurrenceEvidence{T}}
end

struct AsymptoticSeriesBundle{T<:AbstractFloat}
    infinity_ingoing::AsymptoticSeries{T}
    infinity_outgoing::AsymptoticSeries{T}
    horizon_ingoing::AsymptoticSeries{T}
    horizon_outgoing::AsymptoticSeries{T}
end

struct SeriesEvaluation{T<:AbstractFloat}
    key::SeriesKey{T}
    family::AsymptoticFamily
    order::Int
    precision_bits::Int
    series_eval_horner::Complex{T}
    series_eval_compensated::Complex{T}
    series_eval_alternate::Complex{T}
    series_evaluation_spread::T
    series_evaluation_digits_lost::T
    last_term_magnitude::T
    last_term_total_ratio::T
    series_derivative_horner::Complex{T}
    series_derivative_compensated::Complex{T}
    series_derivative_alternate::Complex{T}
    derivative_evaluation_spread::T
    derivative_evaluation_digits_lost::T
    derivative_last_term_magnitude::T
    derivative_last_term_total_ratio::T
    maximum_recurrence_cancellation_factor::T
    recurrence_digits_lost::T
    estimate_kind::String
end

function _series_keys_match_exactly(
    left::SeriesKey{T}, right::SeriesKey{T}
) where {T<:AbstractFloat}
    return left.s == right.s &&
        left.m == right.m &&
        isequal(left.a, right.a) &&
        isequal(left.omega, right.omega) &&
        isequal(left.lambda, right.lambda) &&
        left.family == right.family &&
        left.max_order == right.max_order &&
        left.precision_bits == right.precision_bits
end

struct AsymptoticConditioningAssessment{T<:AbstractFloat}
    adequate::Bool
    reason::Union{Nothing,String}
    precision_bits::Int
    arithmetic_decimal_digits::T
    required_digits::T
    safety_margin_digits::T
    maximum_recurrence_digits_lost::T
    maximum_recurrence_cancellation_factor::T
    maximum_series_evaluation_spread::T
    maximum_series_evaluation_digits_lost::T
    maximum_last_term_ratio::T
    maximum_truncation_digits_lost::T
    effective_digits_lost::T
    predicted_reliable_digits::T
    estimate_kind::String
end

typed_integer(::Type{T}, value::Integer) where {T<:AbstractFloat} = T(value)

function _construction_error(
    reason::AsymptoticFailureReason,
    key::SeriesKey,
    message::AbstractString;
    order::Int=key.max_order,
)
    return AsymptoticConstructionError(
        reason, key.family, order, key.precision_bits, String(message)
    )
end

function _finite_complex(value::Complex)
    return isfinite(real(value)) && isfinite(imag(value))
end

function _complex_precision_matches(value::Complex, precision_bits::Int)
    return precision(real(value)) == precision_bits &&
        precision(imag(value)) == precision_bits
end

function SeriesKey(
    s::Int,
    m::Int,
    a::T,
    omega::Union{T,Complex{T}},
    lambda::Union{T,Complex{T}},
    family::AsymptoticFamily,
    max_order::Int,
    precision_bits::Int,
) where {T<:AbstractFloat}
    typed_omega = Complex{T}(omega)
    typed_lambda = Complex{T}(lambda)
    provisional = SeriesKey{T}(
        s, m, a, typed_omega, typed_lambda, family, max_order, precision_bits
    )
    max_order >= 0 || throw(_construction_error(
        INVALID_ASYMPTOTIC_ORDER,
        provisional,
        "maximum expansion order must be nonnegative",
    ))
    precision_bits > 0 || throw(_construction_error(
        PRECISION_MISMATCH,
        provisional,
        "precision_bits must be positive and mandatory",
    ))
    input_precision_matches = precision(a) == precision_bits &&
        _complex_precision_matches(typed_omega, precision_bits) &&
        _complex_precision_matches(typed_lambda, precision_bits)
    input_precision_matches || throw(_construction_error(
        PRECISION_MISMATCH,
        provisional,
        "requested precision does not match every input component; Float64 " *
        "inputs cannot be promoted into purported high-precision evidence",
    ))
    isfinite(a) && _finite_complex(typed_omega) && _finite_complex(typed_lambda) ||
        throw(_construction_error(
            NONFINITE_ASYMPTOTIC_DATA,
            provisional,
            "asymptotic inputs must be finite",
        ))
    return provisional
end

function SeriesKey(
    s::Int,
    m::Int,
    a::Number,
    omega::Number,
    lambda::Number,
    family::AsymptoticFamily,
    max_order::Int,
    precision_bits::Int,
)
    throw(AsymptoticConstructionError(
        PRECISION_MISMATCH,
        family,
        max_order,
        precision_bits,
        "all floating input components must have one exact real type and " *
        "cannot be promoted into purported high-precision evidence",
    ))
end

function _with_request_precision(
    operation::F, ::Type{BigFloat}, precision_bits::Int
) where {F}
    return setprecision(BigFloat, precision_bits) do
        operation()
    end
end

function _with_request_precision(
    operation::F, ::Type{T}, precision_bits::Int
) where {F,T<:AbstractFloat}
    precision(T) == precision_bits || throw(ArgumentError(
        "fixed-width real type disagrees with requested precision"
    ))
    return operation()
end

_component_type(::Type{Complex{T}}) where {T<:AbstractFloat} = T
_component_type(::Type{T}) where {T<:AbstractFloat} = T

function _legacy_real_component(::Type{T}, value, name::AbstractString) where {T}
    if value isa Integer || value isa Rational
        return T(value)
    elseif value isa T
        return value
    end
    throw(AsymptoticConstructionError(
        PRECISION_MISMATCH,
        nothing,
        -1,
        precision(T),
        "$name cannot be promoted into purported high-precision evidence",
    ))
end

function _legacy_complex_component(
    ::Type{T}, value::Number, name::AbstractString
) where {T<:AbstractFloat}
    real_part = _legacy_real_component(T, real(value), "$name real component")
    imag_part = _legacy_real_component(T, imag(value), "$name imaginary component")
    return complex(real_part, imag_part)
end

function _legacy_series_key(
    s::Int,
    m::Int,
    a,
    omega,
    lambda,
    family::AsymptoticFamily,
    max_order::Int,
    data_type,
)
    T = _component_type(data_type)
    typed_a = _legacy_real_component(T, a, "a")
    typed_omega = _legacy_complex_component(T, omega, "omega")
    typed_lambda = _legacy_complex_component(T, lambda, "lambda")
    return SeriesKey(
        s,
        m,
        typed_a,
        typed_omega,
        typed_lambda,
        family,
        max_order,
        precision(typed_a),
    )
end

function _assert_value(key::SeriesKey{T}, value::Complex{T}, name::AbstractString) where {T}
    _finite_complex(value) || throw(_construction_error(
        NONFINITE_ASYMPTOTIC_DATA,
        key,
        "$name is nonfinite",
    ))
    _complex_precision_matches(value, key.precision_bits) || throw(_construction_error(
        PRECISION_MISMATCH,
        key,
        "$name precision differs from the request precision",
    ))
    return value
end

function _typed_taylor_workspace(
    key::SeriesKey{T}, function_to_expand::F, maximum_order::Int, name::AbstractString
) where {T<:AbstractFloat,F}
    center = zero(Complex{T})
    _complex_precision_matches(center, key.precision_bits) || throw(_construction_error(
        PRECISION_MISMATCH,
        key,
        "$name Taylor centre precision differs from the request precision",
    ))
    raw_workspace = taylor_expand(
        function_to_expand, center, order=maximum_order
    )
    coefficients = Vector{Complex{T}}(undef, maximum_order + 1)
    for order in 0:maximum_order
        coefficient = Complex{T}(getcoeff(raw_workspace, order))
        coefficients[order + 1] = _assert_value(
            key, coefficient, "$name Taylor coefficient $order"
        )
    end
    return TypedTaylorWorkspace{T}(center, coefficients)
end

function _chart_denominator(key::SeriesKey{T}) where {T}
    lambda = key.lambda
    omega = key.omega
    a = key.a
    mT = typed_integer(T, key.m)
    imaginary_unit = complex(zero(T), one(T))
    if key.s == 1
        denominator = lambda + typed_integer(T, 2)
        scale = abs(lambda) + typed_integer(T, 2)
    elseif key.s == -1
        denominator = lambda
        scale = abs(lambda)
    elseif key.s == 2
        Eplus = lambda^2 + typed_integer(T, 10) * lambda + typed_integer(T, 24) +
            typed_integer(T, 12) * (imaginary_unit + a * mT) * omega -
            typed_integer(T, 12) * a^2 * omega^2
        denominator = Eplus
        scale = abs(lambda^2) + abs(typed_integer(T, 10) * lambda) +
            typed_integer(T, 24) +
            abs(typed_integer(T, 12) * (imaginary_unit + a * mT) * omega) +
            abs(typed_integer(T, 12) * a^2 * omega^2)
    elseif key.s == -2
        Eminus = lambda * (lambda + typed_integer(T, 2)) -
            typed_integer(T, 12) * omega *
            (imaginary_unit - a * mT + a^2 * omega)
        denominator = Eminus
        scale = abs(lambda * (lambda + typed_integer(T, 2))) +
            abs(typed_integer(T, 12) * omega *
                (imaginary_unit - a * mT + a^2 * omega))
    elseif key.s == 0
        denominator = one(Complex{T})
        scale = one(T)
    else
        throw(_construction_error(
            INVALID_ASYMPTOTIC_INPUT,
            key,
            "only spin weights 0, +/-1, and +/-2 are supported",
        ))
    end
    _assert_value(key, Complex{T}(denominator), "GSN chart denominator")
    isfinite(scale) || throw(_construction_error(
        NONFINITE_ASYMPTOTIC_DATA,
        key,
        "GSN chart denominator scale is nonfinite",
    ))
    iszero(denominator) && throw(_construction_error(
        ALGEBRAIC_REPRESENTATION_SINGULAR,
        key,
        "unresolved exact low-order GSN chart denominator",
    ))
    return Complex{T}(denominator), T(scale)
end

function _cancellation_metrics(
    ::Type{T}, recurrence_term_abs_sum::T, value_scale::T, precision_bits::Int
) where {T<:AbstractFloat}
    arithmetic_digits = typed_integer(T, precision_bits) * log10(typed_integer(T, 2))
    if iszero(recurrence_term_abs_sum)
        cancellation_digits = zero(T)
    elseif iszero(value_scale)
        cancellation_digits = arithmetic_digits
    else
        cancellation_digits = min(
            arithmetic_digits,
            max(
                zero(T),
                log10(max(one(T), recurrence_term_abs_sum / value_scale)),
            ),
        )
    end
    cancellation_factor = typed_integer(T, 10)^cancellation_digits
    return cancellation_factor, cancellation_digits
end

function _chart_digits_lost(
    ::Type{T}, denominator::Complex{T}, scale::T, precision_bits::Int
) where {T}
    _, digits = _cancellation_metrics(T, scale, abs(denominator), precision_bits)
    return digits
end

function _recurrence_evidence(
    key::SeriesKey{T},
    order::Int,
    denominator::Complex{T},
    denominator_scale::T,
    value::Complex{T},
    recurrence_term_abs_sum::T,
    extra_digits_lost::T,
) where {T<:AbstractFloat}
    factor, digits = _cancellation_metrics(
        T, recurrence_term_abs_sum, abs(value * denominator), key.precision_bits
    )
    digits = max(digits, extra_digits_lost)
    factor = max(factor, typed_integer(T, 10)^digits)
    evidence = RecurrenceEvidence{T}(
        denominator,
        denominator_scale,
        abs(value),
        recurrence_term_abs_sum,
        factor,
        digits,
        key.family,
        order,
        key.precision_bits,
    )
    all(isfinite, (
        evidence.denominator_scale,
        evidence.value_scale,
        evidence.recurrence_term_abs_sum,
        evidence.cancellation_factor,
        evidence.cancellation_digits,
    )) || throw(_construction_error(
        NONFINITE_ASYMPTOTIC_DATA,
        key,
        "recurrence evidence is nonfinite",
        order=order,
    ))
    return evidence
end

function _potential_workspaces(key::SeriesKey{T}) where {T}
    if key.family == INFINITY_INGOING_SERIES
        P_function = z -> PminusInf_z(
            key.s, key.m, key.a, key.omega, key.lambda, z
        )
        Q_function = z -> QminusInf_z(
            key.s, key.m, key.a, key.omega, key.lambda, z
        )
        P = _typed_taylor_workspace(key, P_function, key.max_order, "PminusInf")
        Q = _typed_taylor_workspace(key, Q_function, key.max_order + 1, "QminusInf")
    elseif key.family == INFINITY_OUTGOING_SERIES
        P_function = z -> PplusInf_z(
            key.s, key.m, key.a, key.omega, key.lambda, z
        )
        Q_function = z -> QplusInf_z(
            key.s, key.m, key.a, key.omega, key.lambda, z
        )
        P = _typed_taylor_workspace(key, P_function, key.max_order, "PplusInf")
        Q = _typed_taylor_workspace(key, Q_function, key.max_order + 1, "QplusInf")
    elseif key.family == HORIZON_INGOING_SERIES
        P_function = x -> PminusH(
            key.s, key.m, key.a, key.omega, key.lambda, x
        )
        Q_function = x -> QminusH(
            key.s, key.m, key.a, key.omega, key.lambda, x
        )
        P = _typed_taylor_workspace(key, P_function, key.max_order, "PminusH")
        Q = _typed_taylor_workspace(key, Q_function, key.max_order, "QminusH")
    else
        P_function = x -> PplusH(
            key.s, key.m, key.a, key.omega, key.lambda, x
        )
        Q_function = x -> QplusH(
            key.s, key.m, key.a, key.omega, key.lambda, x
        )
        P = _typed_taylor_workspace(key, P_function, key.max_order, "PplusH")
        Q = _typed_taylor_workspace(key, Q_function, key.max_order, "QplusH")
    end
    return P, Q
end

function _infinity_recurrence_coefficient(
    key::SeriesKey{T},
    order::Int,
    coefficients::Vector{Complex{T}},
    Pcoeffs::Vector{Complex{T}},
    Qcoeffs::Vector{Complex{T}},
    chart_digits_lost::T,
) where {T<:AbstractFloat}
    sigma = key.family == INFINITY_INGOING_SERIES ? -one(T) : one(T)
    denominator = 2 * sigma * complex(zero(T), one(T)) * typed_integer(T, order)
    numerator = typed_integer(T, order) * typed_integer(T, order - 1) *
        coefficients[order]
    recurrence_term_abs_sum = abs(numerator)
    omega_power = one(Complex{T})
    for k in 1:order
        term = omega_power *
            (Qcoeffs[k + 2] - typed_integer(T, order - k) * Pcoeffs[k + 1]) *
            coefficients[order - k + 1]
        _assert_value(key, term, "infinity recurrence term")
        numerator += term
        recurrence_term_abs_sum += abs(term)
        omega_power *= key.omega
    end
    _assert_value(key, denominator, "infinity recurrence denominator")
    iszero(denominator) && throw(_construction_error(
        ALGEBRAIC_REPRESENTATION_SINGULAR,
        key,
        "infinity stored-coefficient recurrence denominator is zero",
        order=order,
    ))
    value = _assert_value(
        key, numerator / denominator, "infinity recurrence coefficient"
    )
    evidence = _recurrence_evidence(
        key,
        order,
        denominator,
        abs(denominator),
        value,
        recurrence_term_abs_sum,
        chart_digits_lost,
    )
    return value, evidence
end

function _explicit_infinity_coefficient(key::SeriesKey{T}, order::Int) where {T}
    value = if key.family == INFINITY_INGOING_SERIES
        _ingoing_coefficient_at_inf_legacy_impl(
            key.s,
            key.m,
            key.a,
            key.omega,
            key.lambda,
            order;
            data_type=Complex{T},
        )
    else
        _outgoing_coefficient_at_inf_legacy_impl(
            key.s,
            key.m,
            key.a,
            key.omega,
            key.lambda,
            order;
            data_type=Complex{T},
        )
    end
    return _assert_value(key, Complex{T}(value), "explicit infinity coefficient")
end

function _build_infinity_recurrence(
    key::SeriesKey{T}; use_explicit_low_orders::Bool
) where {T<:AbstractFloat}
    chart_denominator, chart_scale = _chart_denominator(key)
    chart_digits_lost = _chart_digits_lost(
        T, chart_denominator, chart_scale, key.precision_bits
    )
    P, Q = _potential_workspaces(key)
    coefficients = Vector{Complex{T}}(undef, key.max_order + 1)
    evidence = Vector{RecurrenceEvidence{T}}(undef, key.max_order + 1)
    coefficients[1] = one(Complex{T})
    evidence[1] = _recurrence_evidence(
        key,
        0,
        chart_denominator,
        chart_scale,
        coefficients[1],
        one(T),
        chart_digits_lost,
    )

    explicit_maximum = use_explicit_low_orders ? min(3, key.max_order) : 0
    for order in 1:explicit_maximum
        coefficients[order + 1] = _explicit_infinity_coefficient(key, order)
        evidence[order + 1] = _recurrence_evidence(
            key,
            order,
            chart_denominator,
            chart_scale,
            coefficients[order + 1],
            abs(coefficients[order + 1]),
            chart_digits_lost,
        )
    end
    for order in (explicit_maximum + 1):key.max_order
        value, order_evidence = _infinity_recurrence_coefficient(
            key, order, coefficients, P.coefficients, Q.coefficients,
            chart_digits_lost,
        )
        coefficients[order + 1] = value
        evidence[order + 1] = order_evidence
    end
    return AsymptoticSeries{T}(key, coefficients, P, Q, evidence)
end

function _horizon_geometry(key::SeriesKey{T}) where {T<:AbstractFloat}
    delta_squared = (one(T) - key.a) * (one(T) + key.a)
    delta_squared < zero(T) && throw(_construction_error(
        INVALID_ASYMPTOTIC_INPUT,
        key,
        "real Kerr spin must satisfy abs(a) <= 1",
    ))
    geometry = stable_horizon_geometry(key.a)
    delta = geometry.delta
    iszero(delta) && throw(_construction_error(
        PHYSICAL_SINGULAR_LIMIT,
        key,
        "extremal delta=0 requires an independently proved logarithm-free limit",
    ))
    rplus = geometry.rplus
    p_horizon = key.omega - typed_integer(T, key.m) *
        geometry.omega_horizon
    _assert_value(key, Complex{T}(p_horizon), "horizon wave number")
    iszero(p_horizon) && throw(_construction_error(
        PHYSICAL_SINGULAR_LIMIT,
        key,
        "pH=0 coalesces the horizon carrier and basis modes",
    ))
    return delta, rplus, Complex{T}(p_horizon)
end

function _horizon_denominator(
    key::SeriesKey{T}, order::Int, delta::T, rplus::T, p_horizon::Complex{T}
) where {T<:AbstractFloat}
    nT = typed_integer(T, order)
    imaginary_unit = complex(zero(T), one(T))
    carrier_coupling_term = _assert_value(
        key,
        Complex{T}(
            2 * imaginary_unit * nT * rplus * p_horizon / delta
        ),
        "horizon recurrence carrier coupling",
    )
    if key.family == HORIZON_OUTGOING_SERIES
        denominator = nT * (
            nT + 2 * imaginary_unit * rplus * p_horizon / delta
        )
    else
        denominator = nT * (
            nT - 2 * imaginary_unit * rplus * p_horizon / delta
        )
    end
    denominator = _assert_value(
        key, Complex{T}(denominator), "horizon recurrence denominator"
    )
    denominator_scale = abs(nT^2) + abs(carrier_coupling_term)
    isfinite(denominator_scale) || throw(_construction_error(
        NONFINITE_ASYMPTOTIC_DATA,
        key,
        "horizon recurrence denominator scale is nonfinite",
        order=order,
    ))
    iszero(denominator) && throw(_construction_error(
        PHYSICAL_SINGULAR_LIMIT,
        key,
        "exact horizon Frobenius resonance requires a separately proved limit",
        order=order,
    ))
    return denominator, denominator_scale
end

function _build_horizon_recurrence(key::SeriesKey{T}) where {T<:AbstractFloat}
    chart_denominator, chart_scale = _chart_denominator(key)
    chart_digits_lost = _chart_digits_lost(
        T, chart_denominator, chart_scale, key.precision_bits
    )
    delta, rplus, p_horizon = _horizon_geometry(key)
    P, Q = _potential_workspaces(key)
    coefficients = Vector{Complex{T}}(undef, key.max_order + 1)
    evidence = Vector{RecurrenceEvidence{T}}(undef, key.max_order + 1)
    coefficients[1] = one(Complex{T})
    evidence[1] = _recurrence_evidence(
        key,
        0,
        chart_denominator,
        chart_scale,
        coefficients[1],
        one(T),
        chart_digits_lost,
    )
    for order in 1:key.max_order
        recurrence_sum = zero(Complex{T})
        recurrence_term_abs_sum = zero(T)
        for previous_order in 0:(order - 1)
            term = coefficients[previous_order + 1] *
                (typed_integer(T, previous_order) *
                    P.coefficients[order - previous_order + 1] +
                 Q.coefficients[order - previous_order + 1])
            _assert_value(key, term, "horizon recurrence term")
            recurrence_sum += term
            recurrence_term_abs_sum += abs(term)
        end
        denominator, denominator_scale = _horizon_denominator(
            key, order, delta, rplus, p_horizon
        )
        _, denominator_cancellation_digits = _cancellation_metrics(
            T, denominator_scale, abs(denominator), key.precision_bits
        )
        value = _assert_value(
            key, -recurrence_sum / denominator, "horizon recurrence coefficient"
        )
        coefficients[order + 1] = value
        evidence[order + 1] = _recurrence_evidence(
            key,
            order,
            denominator,
            denominator_scale,
            value,
            recurrence_term_abs_sum,
            max(chart_digits_lost, denominator_cancellation_digits),
        )
    end
    return AsymptoticSeries{T}(key, coefficients, P, Q, evidence)
end

function build_asymptotic_series(key::SeriesKey{T}) where {T<:AbstractFloat}
    return _with_request_precision(T, key.precision_bits) do
        if key.family == INFINITY_INGOING_SERIES ||
           key.family == INFINITY_OUTGOING_SERIES
            _build_infinity_recurrence(key; use_explicit_low_orders=true)
        else
            _build_horizon_recurrence(key)
        end
    end
end

function build_infinity_recurrence_from_zero(
    key::SeriesKey{T}
) where {T<:AbstractFloat}
    (key.family == INFINITY_INGOING_SERIES ||
     key.family == INFINITY_OUTGOING_SERIES) || throw(_construction_error(
        INVALID_ASYMPTOTIC_INPUT,
        key,
        "recurrence-from-zero diagnostics are defined only at infinity",
    ))
    return _with_request_precision(T, key.precision_bits) do
        _build_infinity_recurrence(key; use_explicit_low_orders=false)
    end
end

function build_asymptotic_series_bundle(
    s::Int,
    m::Int,
    a::T,
    omega::Union{T,Complex{T}},
    lambda::Union{T,Complex{T}},
    max_order::Int;
    precision_bits::Int,
) where {T<:AbstractFloat}
    keys = (
        SeriesKey(s, m, a, omega, lambda, INFINITY_INGOING_SERIES,
            max_order, precision_bits),
        SeriesKey(s, m, a, omega, lambda, INFINITY_OUTGOING_SERIES,
            max_order, precision_bits),
        SeriesKey(s, m, a, omega, lambda, HORIZON_INGOING_SERIES,
            max_order, precision_bits),
        SeriesKey(s, m, a, omega, lambda, HORIZON_OUTGOING_SERIES,
            max_order, precision_bits),
    )
    return AsymptoticSeriesBundle{T}(
        build_asymptotic_series(keys[1]),
        build_asymptotic_series(keys[2]),
        build_asymptotic_series(keys[3]),
        build_asymptotic_series(keys[4]),
    )
end

function _assert_evaluation_real(
    key::SeriesKey{T}, value::T, name::AbstractString; order::Int=key.max_order
) where {T<:AbstractFloat}
    isfinite(value) || throw(_construction_error(
        NONFINITE_ASYMPTOTIC_DATA,
        key,
        "$name is nonfinite",
        order=order,
    ))
    precision(value) == key.precision_bits || throw(_construction_error(
        PRECISION_MISMATCH,
        key,
        "$name precision differs from the series key",
        order=order,
    ))
    return value
end

function _validate_series_for_evaluation(
    series::AsymptoticSeries{T}, order::Int
) where {T<:AbstractFloat}
    key = series.key
    0 <= order <= key.max_order || throw(_construction_error(
        INVALID_ASYMPTOTIC_ORDER,
        key,
        "evaluation order must lie within the constructed series",
        order=order,
    ))
    length(series.coefficients) == key.max_order + 1 || throw(_construction_error(
        INVALID_ASYMPTOTIC_INPUT,
        key,
        "coefficient count differs from the series key",
        order=order,
    ))
    length(series.evidence) == key.max_order + 1 || throw(_construction_error(
        INVALID_ASYMPTOTIC_INPUT,
        key,
        "recurrence evidence count differs from the series key",
        order=order,
    ))
    for (workspace_name, workspace) in (("P", series.P), ("Q", series.Q))
        _assert_value(key, workspace.center, "$workspace_name Taylor centre")
        isempty(workspace.coefficients) && throw(_construction_error(
            INVALID_ASYMPTOTIC_INPUT,
            key,
            "$workspace_name Taylor workspace is empty",
            order=order,
        ))
        for (index, coefficient) in enumerate(workspace.coefficients)
            _assert_value(
                key,
                coefficient,
                "$workspace_name Taylor workspace coefficient $(index - 1)",
            )
        end
    end
    for coefficient_order in 0:order
        _assert_value(
            key,
            series.coefficients[coefficient_order + 1],
            "series coefficient $coefficient_order",
        )
        evidence = series.evidence[coefficient_order + 1]
        evidence.family == key.family || throw(_construction_error(
            INVALID_ASYMPTOTIC_INPUT,
            key,
            "recurrence evidence family differs from the series key",
            order=coefficient_order,
        ))
        evidence.order == coefficient_order || throw(_construction_error(
            INVALID_ASYMPTOTIC_INPUT,
            key,
            "recurrence evidence order differs from the series key",
            order=coefficient_order,
        ))
        evidence.precision_bits == key.precision_bits || throw(_construction_error(
            PRECISION_MISMATCH,
            key,
            "recurrence evidence precision differs from the series key",
            order=coefficient_order,
        ))
        _assert_value(
            key,
            evidence.denominator_value,
            "recurrence evidence denominator",
        )
        for (name, value) in (
            ("denominator scale", evidence.denominator_scale),
            ("value scale", evidence.value_scale),
            ("recurrence term absolute sum", evidence.recurrence_term_abs_sum),
            ("cancellation factor", evidence.cancellation_factor),
            ("cancellation digits", evidence.cancellation_digits),
        )
            _assert_evaluation_real(
                key, value, "recurrence evidence $name"; order=coefficient_order
            )
            value >= zero(T) || throw(_construction_error(
                INVALID_ASYMPTOTIC_INPUT,
                key,
                "recurrence evidence $name must be nonnegative",
                order=coefficient_order,
            ))
        end
    end
    return key
end

function _horner_value_and_derivative(
    key::SeriesKey{T},
    coefficients::Vector{Complex{T}},
    z::Complex{T},
    dz_dr::Complex{T},
    order::Int,
) where {T<:AbstractFloat}
    value = coefficients[order + 1]
    derivative_z = zero(Complex{T})
    for coefficient_index in order:-1:1
        derivative_z = _assert_value(
            key,
            derivative_z * z + value,
            "Horner series derivative accumulator",
        )
        value = _assert_value(
            key,
            value * z + coefficients[coefficient_index],
            "Horner series value accumulator",
        )
    end
    derivative_r = _assert_value(
        key, derivative_z * dz_dr, "Horner radial derivative"
    )
    return value, derivative_r
end

function _neumaier_component(
    total::T, compensation::T, value::T
) where {T<:AbstractFloat}
    updated = total + value
    if abs(total) >= abs(value)
        compensation += (total - updated) + value
    else
        compensation += (value - updated) + total
    end
    return updated, compensation
end

function _componentwise_neumaier(
    terms::Vector{Complex{T}}
) where {T<:AbstractFloat}
    real_total = zero(T)
    real_compensation = zero(T)
    imaginary_total = zero(T)
    imaginary_compensation = zero(T)
    for term in terms
        real_total, real_compensation = _neumaier_component(
            real_total, real_compensation, real(term)
        )
        imaginary_total, imaginary_compensation = _neumaier_component(
            imaginary_total, imaginary_compensation, imag(term)
        )
    end
    return complex(
        real_total + real_compensation,
        imaginary_total + imaginary_compensation,
    )
end

function _direct_series_terms(
    key::SeriesKey{T},
    coefficients::Vector{Complex{T}},
    z::Complex{T},
    dz_dr::Complex{T},
    order::Int,
) where {T<:AbstractFloat}
    value_terms = Vector{Complex{T}}(undef, order + 1)
    derivative_terms = Vector{Complex{T}}(undef, order + 1)
    value_power = one(Complex{T})
    derivative_power = one(Complex{T})
    for coefficient_order in 0:order
        coefficient = coefficients[coefficient_order + 1]
        value_terms[coefficient_order + 1] = _assert_value(
            key,
            coefficient * value_power,
            "direct series value term $coefficient_order",
        )
        derivative_terms[coefficient_order + 1] = if coefficient_order == 0
            zero(Complex{T})
        else
            _assert_value(
                key,
                typed_integer(T, coefficient_order) * coefficient *
                    derivative_power * dz_dr,
                "direct series derivative term $coefficient_order",
            )
        end
        if coefficient_order < order
            value_power = _assert_value(
                key, value_power * z, "direct series value power"
            )
            if coefficient_order > 0
                derivative_power = _assert_value(
                    key,
                    derivative_power * z,
                    "direct series derivative power",
                )
            end
        end
    end
    return value_terms, derivative_terms
end

function _maximum_relative_spread(
    key::SeriesKey{T}, values::NTuple{3,Complex{T}}, name::AbstractString
) where {T<:AbstractFloat}
    maximum_magnitude = max(abs(values[1]), abs(values[2]), abs(values[3]))
    scale = max(maximum_magnitude, floatmin(T))
    pairwise_difference = max(
        abs(values[1] - values[2]),
        abs(values[1] - values[3]),
        abs(values[2] - values[3]),
    )
    return _assert_evaluation_real(
        key, pairwise_difference / scale, "$name maximum relative spread"
    )
end

function _empirical_digits_lost(
    key::SeriesKey{T}, relative_measure::T, arithmetic_digits::T,
    name::AbstractString
) where {T<:AbstractFloat}
    _assert_evaluation_real(key, relative_measure, "$name relative measure")
    relative_measure >= zero(T) || throw(_construction_error(
        INVALID_ASYMPTOTIC_INPUT,
        key,
        "$name relative measure must be nonnegative",
    ))
    digits_lost = if iszero(relative_measure)
        zero(T)
    else
        max(zero(T), arithmetic_digits + log10(relative_measure))
    end
    return _assert_evaluation_real(key, digits_lost, "$name digits lost")
end

function _finite_ratio(
    key::SeriesKey{T}, numerator::T, denominator::T, name::AbstractString
) where {T<:AbstractFloat}
    numerator >= zero(T) && denominator > zero(T) || throw(_construction_error(
        INVALID_ASYMPTOTIC_INPUT,
        key,
        "$name requires a nonnegative numerator and positive denominator",
    ))
    ratio = numerator / denominator
    if !isfinite(ratio) && !iszero(numerator)
        ratio = floatmax(T)
    end
    return _assert_evaluation_real(key, ratio, name)
end

function _maximum_recurrence_digits_lost(
    series::AsymptoticSeries{T}, order::Int
) where {T<:AbstractFloat}
    maximum_loss = zero(T)
    for coefficient_order in 0:order
        maximum_loss = max(
            maximum_loss,
            series.evidence[coefficient_order + 1].cancellation_digits,
        )
    end
    return _assert_evaluation_real(
        series.key, maximum_loss, "maximum recurrence digits lost"; order=order
    )
end

function _maximum_recurrence_cancellation_factor(
    series::AsymptoticSeries{T}, order::Int
) where {T<:AbstractFloat}
    maximum_factor = zero(T)
    for coefficient_order in 0:order
        maximum_factor = max(
            maximum_factor,
            series.evidence[coefficient_order + 1].cancellation_factor,
        )
    end
    return _assert_evaluation_real(
        series.key,
        maximum_factor,
        "maximum recurrence cancellation factor";
        order=order,
    )
end

function evaluate_asymptotic_series(
    series::AsymptoticSeries{T},
    z::Union{T,Complex{T}},
    dz_dr::Union{T,Complex{T}};
    order::Int=series.key.max_order,
)::SeriesEvaluation{T} where {T<:AbstractFloat}
    return _with_request_precision(T, series.key.precision_bits) do
        key = _validate_series_for_evaluation(series, order)
        if (key.family == INFINITY_INGOING_SERIES ||
            key.family == INFINITY_OUTGOING_SERIES) && iszero(key.omega)
            throw(_construction_error(
                PHYSICAL_SINGULAR_LIMIT,
                key,
                "omega=0 is a physical static limit for the infinity " *
                "plane-wave/(omega*r)^-n endpoint state",
                order=order,
            ))
        end
        typed_z = _assert_value(key, Complex{T}(z), "series variable z")
        typed_dz_dr = _assert_value(
            key, Complex{T}(dz_dr), "series variable derivative dz_dr"
        )
        horner_value, horner_derivative = _horner_value_and_derivative(
            key, series.coefficients, typed_z, typed_dz_dr, order
        )
        value_terms, derivative_terms = _direct_series_terms(
            key, series.coefficients, typed_z, typed_dz_dr, order
        )
        compensated_value = _assert_value(
            key,
            _componentwise_neumaier(value_terms),
            "forward compensated series value",
        )
        compensated_derivative = _assert_value(
            key,
            _componentwise_neumaier(derivative_terms),
            "forward compensated series derivative",
        )
        alternate_value_terms = copy(value_terms)
        alternate_derivative_terms = copy(derivative_terms)
        sort!(alternate_value_terms; by=abs)
        sort!(alternate_derivative_terms; by=abs)
        alternate_value = _assert_value(
            key,
            _componentwise_neumaier(alternate_value_terms),
            "magnitude-sorted compensated series value",
        )
        alternate_derivative = _assert_value(
            key,
            _componentwise_neumaier(alternate_derivative_terms),
            "magnitude-sorted compensated series derivative",
        )
        value_spread = _maximum_relative_spread(
            key,
            (horner_value, compensated_value, alternate_value),
            "series value",
        )
        derivative_spread = _maximum_relative_spread(
            key,
            (horner_derivative, compensated_derivative, alternate_derivative),
            "series derivative",
        )
        arithmetic_digits = typed_integer(T, key.precision_bits) *
            log10(typed_integer(T, 2))
        _assert_evaluation_real(
            key, arithmetic_digits, "arithmetic decimal digits"
        )
        value_digits_lost = _empirical_digits_lost(
            key, value_spread, arithmetic_digits, "series value evaluation"
        )
        derivative_digits_lost = _empirical_digits_lost(
            key,
            derivative_spread,
            arithmetic_digits,
            "series derivative evaluation",
        )
        last_term_magnitude = _assert_evaluation_real(
            key, abs(value_terms[end]), "last series term magnitude"
        )
        derivative_last_term_magnitude = _assert_evaluation_real(
            key,
            abs(derivative_terms[end]),
            "last derivative term magnitude",
        )
        last_term_total_ratio = _finite_ratio(
            key,
            last_term_magnitude,
            max(abs(horner_value), floatmin(T)),
            "last term to total series magnitude ratio",
        )
        derivative_last_term_total_ratio = _finite_ratio(
            key,
            derivative_last_term_magnitude,
            max(abs(horner_derivative), floatmin(T)),
            "last derivative term to total derivative magnitude ratio",
        )
        maximum_recurrence_cancellation_factor =
            _maximum_recurrence_cancellation_factor(series, order)
        recurrence_digits_lost = _maximum_recurrence_digits_lost(series, order)
        return SeriesEvaluation{T}(
            key,
            key.family,
            order,
            key.precision_bits,
            horner_value,
            compensated_value,
            alternate_value,
            value_spread,
            value_digits_lost,
            last_term_magnitude,
            last_term_total_ratio,
            horner_derivative,
            compensated_derivative,
            alternate_derivative,
            derivative_spread,
            derivative_digits_lost,
            derivative_last_term_magnitude,
            derivative_last_term_total_ratio,
            maximum_recurrence_cancellation_factor,
            recurrence_digits_lost,
            ASYMPTOTIC_CONDITIONING_ESTIMATE_KIND,
        )
    end
end

function evaluate_asymptotic_series(
    series::AsymptoticSeries,
    z::Number,
    dz_dr::Number;
    order::Int=series.key.max_order,
)
    throw(_construction_error(
        PRECISION_MISMATCH,
        series.key,
        "mixed-precision series evaluation inputs do not match the series key",
        order=order,
    ))
end

function evaluate_infinity_asymptotic_series(
    series::AsymptoticSeries{T},
    r::Union{T,Complex{T}};
    order::Int=series.key.max_order,
)::SeriesEvaluation{T} where {T<:AbstractFloat}
    key = series.key
    (key.family == INFINITY_INGOING_SERIES ||
     key.family == INFINITY_OUTGOING_SERIES) || throw(_construction_error(
        INVALID_ASYMPTOTIC_INPUT,
        key,
        "infinity evaluator family differs from the series key",
        order=order,
    ))
    iszero(series.key.omega) && throw(_construction_error(
        PHYSICAL_SINGULAR_LIMIT,
        key,
        "omega=0 is a physical static limit for the infinity " *
        "plane-wave/(omega*r)^-n endpoint state",
        order=order,
    ))
    return _with_request_precision(T, key.precision_bits) do
        typed_r = _assert_value(key, Complex{T}(r), "infinity evaluation radius")
        iszero(typed_r) && throw(_construction_error(
            INVALID_ASYMPTOTIC_INPUT,
            key,
            "infinity evaluation radius must be nonzero",
            order=order,
        ))
        omega_r = _assert_value(
            key, key.omega * typed_r, "infinity omega*r product"
        )
        iszero(omega_r) && throw(_construction_error(
            ALGEBRAIC_REPRESENTATION_SINGULAR,
            key,
            "infinity omega*r product underflowed to zero before inversion",
            order=order,
        ))
        z = _assert_value(key, inv(omega_r), "infinity series variable")
        dz_dr = _assert_value(
            key, -z / typed_r, "infinity series variable derivative"
        )
        evaluate_asymptotic_series(series, z, dz_dr; order=order)
    end
end

function evaluate_infinity_asymptotic_series(
    series::AsymptoticSeries, r::Number; order::Int=series.key.max_order
)
    throw(_construction_error(
        PRECISION_MISMATCH,
        series.key,
        "mixed-precision infinity evaluation radius does not match the series key",
        order=order,
    ))
end

function evaluate_horizon_asymptotic_series(
    series::AsymptoticSeries{T},
    r::Union{T,Complex{T}};
    order::Int=series.key.max_order,
)::SeriesEvaluation{T} where {T<:AbstractFloat}
    key = series.key
    (key.family == HORIZON_INGOING_SERIES ||
     key.family == HORIZON_OUTGOING_SERIES) || throw(_construction_error(
        INVALID_ASYMPTOTIC_INPUT,
        key,
        "horizon evaluator family differs from the series key",
        order=order,
    ))
    return _with_request_precision(T, key.precision_bits) do
        typed_r = _assert_value(key, Complex{T}(r), "horizon evaluation radius")
        _, rplus, _ = _horizon_geometry(key)
        z = _assert_value(
            key,
            typed_r - complex(rplus, zero(T)),
            "horizon series variable",
        )
        dz_dr = one(Complex{T})
        evaluate_asymptotic_series(series, z, dz_dr; order=order)
    end
end

function evaluate_horizon_asymptotic_series(
    series::AsymptoticSeries, r::Number; order::Int=series.key.max_order
)
    throw(_construction_error(
        PRECISION_MISMATCH,
        series.key,
        "mixed-precision horizon evaluation radius does not match the series key",
        order=order,
    ))
end

function _assert_evaluation_matches_series(
    series::AsymptoticSeries{T}, evaluation::SeriesEvaluation{T}
) where {T<:AbstractFloat}
    key = _validate_series_for_evaluation(series, evaluation.order)
    _series_keys_match_exactly(evaluation.key, key) || throw(_construction_error(
        INVALID_ASYMPTOTIC_INPUT,
        key,
        "evaluation spectral key differs from the requested series key",
        order=evaluation.order,
    ))
    evaluation.family == key.family || throw(_construction_error(
        INVALID_ASYMPTOTIC_INPUT,
        key,
        "evaluation family differs from the series key",
        order=evaluation.order,
    ))
    evaluation.precision_bits == key.precision_bits || throw(_construction_error(
        PRECISION_MISMATCH,
        key,
        "evaluation precision differs from the series key",
        order=evaluation.order,
    ))
    evaluation.estimate_kind == ASYMPTOTIC_CONDITIONING_ESTIMATE_KIND ||
        throw(_construction_error(
            INVALID_ASYMPTOTIC_INPUT,
            key,
            "evaluation estimate identity differs from the series key contract",
            order=evaluation.order,
        ))
    expected_recurrence_loss = _maximum_recurrence_digits_lost(
        series, evaluation.order
    )
    expected_recurrence_factor = _maximum_recurrence_cancellation_factor(
        series, evaluation.order
    )
    evaluation.maximum_recurrence_cancellation_factor ==
        expected_recurrence_factor || throw(_construction_error(
            INVALID_ASYMPTOTIC_INPUT,
            key,
            "evaluation recurrence cancellation factor differs from the series key",
            order=evaluation.order,
        ))
    evaluation.recurrence_digits_lost == expected_recurrence_loss ||
        throw(_construction_error(
            INVALID_ASYMPTOTIC_INPUT,
            key,
            "evaluation recurrence evidence differs from the series key",
            order=evaluation.order,
        ))
    for (name, value) in (
        ("Horner series value", evaluation.series_eval_horner),
        ("forward compensated series value", evaluation.series_eval_compensated),
        ("alternate compensated series value", evaluation.series_eval_alternate),
        ("Horner series derivative", evaluation.series_derivative_horner),
        ("forward compensated series derivative", evaluation.series_derivative_compensated),
        ("alternate compensated series derivative", evaluation.series_derivative_alternate),
    )
        _assert_value(key, value, name)
    end
    for (name, value) in (
        ("series evaluation spread", evaluation.series_evaluation_spread),
        ("series evaluation digits lost", evaluation.series_evaluation_digits_lost),
        ("last term magnitude", evaluation.last_term_magnitude),
        ("last term ratio", evaluation.last_term_total_ratio),
        ("derivative evaluation spread", evaluation.derivative_evaluation_spread),
        ("derivative evaluation digits lost", evaluation.derivative_evaluation_digits_lost),
        ("derivative last term magnitude", evaluation.derivative_last_term_magnitude),
        ("derivative last term ratio", evaluation.derivative_last_term_total_ratio),
        ("maximum recurrence cancellation factor", evaluation.maximum_recurrence_cancellation_factor),
        ("recurrence digits lost", evaluation.recurrence_digits_lost),
    )
        _assert_evaluation_real(key, value, name; order=evaluation.order)
        value >= zero(T) || throw(_construction_error(
            INVALID_ASYMPTOTIC_INPUT,
            key,
            "$name must be nonnegative",
            order=evaluation.order,
        ))
    end
    return key
end

# This empirical assessment is the mandatory preflight before any future RHS
# evaluation. It is diagnostic evidence, not interval arithmetic or a bound.
function assess_asymptotic_preflight(
    series::AsymptoticSeries{T},
    evaluation::SeriesEvaluation{T},
    required_digits::T,
)::AsymptoticConditioningAssessment{T} where {T<:AbstractFloat}
    return _with_request_precision(T, series.key.precision_bits) do
        key = _assert_evaluation_matches_series(series, evaluation)
        _assert_evaluation_real(
            key, required_digits, "required reliable digits";
            order=evaluation.order,
        )
        required_digits >= zero(T) || throw(_construction_error(
            INVALID_ASYMPTOTIC_INPUT,
            key,
            "required reliable digits must be nonnegative",
            order=evaluation.order,
        ))
        arithmetic_decimal_digits =
            typed_integer(T, series.key.precision_bits) *
            log10(typed_integer(T, 2))
        _assert_evaluation_real(
            key, arithmetic_decimal_digits, "arithmetic decimal digits";
            order=evaluation.order,
        )
        safety_margin_digits = typed_integer(T, 8)
        maximum_recurrence_digits_lost = evaluation.recurrence_digits_lost
        maximum_recurrence_cancellation_factor =
            evaluation.maximum_recurrence_cancellation_factor
        maximum_series_evaluation_spread = max(
            evaluation.series_evaluation_spread,
            evaluation.derivative_evaluation_spread,
        )
        maximum_series_evaluation_digits_lost = max(
            evaluation.series_evaluation_digits_lost,
            evaluation.derivative_evaluation_digits_lost,
        )
        maximum_last_term_ratio = max(
            evaluation.last_term_total_ratio,
            evaluation.derivative_last_term_total_ratio,
        )
        value_truncation_digits_lost = _empirical_digits_lost(
            key,
            evaluation.last_term_total_ratio,
            arithmetic_decimal_digits,
            "series truncation",
        )
        derivative_truncation_digits_lost = _empirical_digits_lost(
            key,
            evaluation.derivative_last_term_total_ratio,
            arithmetic_decimal_digits,
            "series derivative truncation",
        )
        maximum_truncation_digits_lost = max(
            value_truncation_digits_lost,
            derivative_truncation_digits_lost,
        )
        effective_digits_lost = max(
            maximum_recurrence_digits_lost,
            maximum_series_evaluation_digits_lost,
            maximum_truncation_digits_lost,
        )
        predicted_reliable_digits = arithmetic_decimal_digits -
            effective_digits_lost - safety_margin_digits
        _assert_evaluation_real(
            key,
            predicted_reliable_digits,
            "predicted reliable digits";
            order=evaluation.order,
        )
        adequate = predicted_reliable_digits >= required_digits
        reason = adequate ? nothing : "INSUFFICIENT_ASYMPTOTIC_PRECISION"
        return AsymptoticConditioningAssessment{T}(
            adequate,
            reason,
            key.precision_bits,
            arithmetic_decimal_digits,
            required_digits,
            safety_margin_digits,
            maximum_recurrence_digits_lost,
            maximum_recurrence_cancellation_factor,
            maximum_series_evaluation_spread,
            maximum_series_evaluation_digits_lost,
            maximum_last_term_ratio,
            maximum_truncation_digits_lost,
            effective_digits_lost,
            predicted_reliable_digits,
            ASYMPTOTIC_CONDITIONING_ESTIMATE_KIND,
        )
    end
end

function assess_asymptotic_preflight(
    series::AsymptoticSeries,
    evaluation::SeriesEvaluation,
    required_digits::Number,
)
    throw(_construction_error(
        PRECISION_MISMATCH,
        series.key,
        "mixed evaluation and series preflight inputs do not share one " *
        "exact key precision",
        order=evaluation.order,
    ))
end

function PminusInf_z(s::Int, m::Int, a, omega, lambda, z)
    if s == 0
        return begin
            -((2*I*(omega + a^2*z^4*(-I + a^2*omega) + z^2*(I + 2*a^2*omega)))/
            ((1 + a^2*z^2)*(1 - 2*z + a^2*z^2)))
        end
    elseif s == 1
        return begin
            ((1 + a^2*z^2)*(-((2*(-1 + z)*z)/(1 + a^2*z^2)) - (2*z*(1 - 2*z + a^2*z^2))/
            (1 + a^2*z^2)^2 + (2*a*z^2*(1 - 2*z + a^2*z^2)*((-I)*m*(1 + 3*a^2*z^2) + 
            a*z*(3 + 3*z + 2*lambda + 2*a^2*z^2*(1 + lambda))))/((1 + a^2*z^2)*
            (2 - 2*I*a*m*z - 2*I*a^3*m*z^3 + lambda + a^4*z^4*(1 + lambda) + 
            a^2*z^2*(3 + 2*z + 2*lambda))) - 2*I*omega))/(1 - 2*z + a^2*z^2)
        end
    elseif s == -1
        return begin
            (1/(1 - 2*z + a^2*z^2))*((1 + a^2*z^2)*(-((2*(-1 + z)*z)/(1 + a^2*z^2)) - 
            (2*z*(1 - 2*z + a^2*z^2))/(1 + a^2*z^2)^2 + 
            (2*a*z^2*(1 - 2*z + a^2*z^2)*(I*m*(1 + 3*a^2*z^2) + 
            a*z*(-1 + 3*z + 2*a^2*z^2*(-1 + lambda) + 2*lambda)))/
            ((1 + a^2*z^2)*(2*I*a*m*z + 2*I*a^3*m*z^3 + a^4*z^4*(-1 + lambda) + lambda + 
            a^2*z^2*(-1 + 2*z + 2*lambda))) - 2*I*omega))
        end
    elseif s == 2
        return begin
            (1/(1 - 2*z + a^2*z^2))*((1 + a^2*z^2)*(-((2*(-1 + z)*z)/(1 + a^2*z^2)) - 
            (2*z*(1 - 2*z + a^2*z^2))/(1 + a^2*z^2)^2 - 2*I*omega + 
            (8*a*z^2*(1 - 2*z + a^2*z^2)*(-6*a*m^2*z + I*m*(-4 + 9*a^2*z^2 - lambda + 
            z*(-6 - 12*I*a^2*omega)) + a*(6*a^2*z^3 + I*(1 + lambda)*omega + z^2*(-9 - 9*I*a^2*omega) + 
            z*(3 + 6*I*omega - 6*a^2*omega^2))))/((1 + a^2*z^2)*(24 + 10*lambda + lambda^2 - 
            4*I*a*m*(6*z^2 + 2*z*(4 + lambda) + 3*I*omega) + 12*I*omega + 24*a^3*m*z^2*(I*z + 2*omega) + 
            12*a^4*z^2*(z^2 - 2*I*z*omega - 2*omega^2) - 4*a^2*(6*z^3 + z^2*(-3 + 6*m^2 - 6*I*omega) - 
            2*I*z*(1 + lambda)*omega + 3*omega^2)))))
        end
    elseif s == -2
        return begin
            (1/(1 - 2*z + a^2*z^2))*((1 + a^2*z^2)*(-((2*(-1 + z)*z)/(1 + a^2*z^2)) - (2*z*(1 - 2*z + a^2*z^2))/(1 + a^2*z^2)^2 - 2*I*omega + 
            (8*a*z^2*(1 - 2*z + a^2*z^2)*(I*m*(6*z + lambda) + 3*a^2*m*z*(-3*I*z + 4*omega) - 
            a*(9*z^2 + z*(-3 + 6*m^2 + 6*I*omega) + I*(-3 + lambda)*omega) + 3*a^3*z*(2*z^2 + 3*I*z*omega - 2*omega^2)))/
            ((1 + a^2*z^2)*(2*lambda + lambda^2 - 12*I*omega + 24*a^3*m*z^2*((-I)*z + 2*omega) + 4*a*m*(6*I*z^2 + 2*I*z*lambda + 3*omega) + 
            12*a^4*z^2*(z^2 + 2*I*z*omega - 2*omega^2) - 4*a^2*(6*z^3 + z^2*(-3 + 6*m^2 + 6*I*omega) + 2*I*z*(-3 + lambda)*omega + 3*omega^2)))))
        end
    else
        throw(DomainError(s, "Currently only spin weight s of 0, +/-1, +/-2 are supported"))
    end
end

function QminusInf_z(s::Int, m::Int, a, omega, lambda, z)
    if s == 0
        return begin
            -((z^2*(-2*z*(-1 + lambda) + lambda - 4*a^2*z^3*(1 + lambda) - 2*a^4*z^5*(3 + lambda) + 2*a*m*omega + 
            a^6*z^6*(1 - m^2 + lambda + 2*a*m*omega) + a^2*z^4*(8 + a^2*(2 - 2*m^2 + 3*lambda) + 
            6*a^3*m*omega) + z^2*(-4 + a^2*(1 - m^2 + 3*lambda) + 6*a^3*m*omega)))/
            ((1 + a^2*z^2)^2*(1 - 2*z + a^2*z^2)^2))
        end
    elseif s == 1
        return begin
            (z^2*(-4 - lambda^2 + 2*a^12*z^12*(1 + lambda) - 8*a*m*omega - 4*I*a^10*z^11*(1 + lambda)*
            (-3*I + a^2*omega) - 2*lambda*(2 + a*m*omega) - a^4*z^6*(52 + 32*lambda + 2*I*a*m*(31 + 6*lambda) + 
            a^2*(71 + 10*lambda^2 - 3*m^2*(3 + 2*lambda) + 8*lambda*(7 - 6*I*omega)) + 
            4*a^3*m*(17 + 5*lambda)*omega) + 2*a^6*z^9*(8 - 6*I*a*m + 
            a^2*(-3 + 3*m^2 - 4*lambda + lambda^2 + 4*I*omega) + 2*I*a^4*(m^2 - 5*(1 + lambda))*omega + 
            a^3*m*(4*I - I*m^2 + I*lambda + 2*omega)) + 
            2*z*((2 + lambda)^2 + 2*I*a^2*(-1 + m^2 - lambda)*omega + a*m*(2*I + I*lambda + 4*omega)) + 
            2*a^3*z^5*(14*I*m + a*(69 - m^2 + 48*lambda + 6*lambda^2 + 28*I*omega) + 
            4*I*a^3*(3*m^2 - 5*(1 + lambda))*omega + 3*a^2*m*(6*I - I*m^2 + 2*I*lambda + 6*omega)) + 
            2*a^4*z^7*(-4 + 8*I*a*m + 4*a^2*(10 + m^2 + 7*lambda + lambda^2 + 5*I*omega) + 
            4*I*a^4*(2*m^2 - 5*(1 + lambda))*omega + a^3*m*(14*I - 3*I*m^2 + 4*I*lambda + 10*omega)) + 
            2*a^2*z^3*(36 - 2*m^2 + 26*lambda + 4*lambda^2 + 12*I*omega + 2*I*a^2*(4*m^2 - 5*(1 + lambda))*omega + 
            a*m*(10*I - I*m^2 + 4*I*lambda + 14*omega)) - 
            a^8*z^10*(-6*I*a*m - 8*(1 + 2*lambda) + 2*a^3*m*(3 + lambda)*omega + 
            a^2*(1 - m^2*(-1 + lambda) + lambda^2 - 4*I*omega - 8*I*lambda*omega)) - 
            a*z^2*(4*I*m*(2 + lambda) + 2*a^2*m*(19 + 5*lambda)*omega + 
            a*(28 + 24*lambda + 5*lambda^2 - m^2*(4 + lambda) + 4*I*omega - 8*I*lambda*omega)) - 
            a^2*z^4*(24*(2 + lambda) + 2*I*a*m*(23 + 6*lambda) + 4*a^3*m*(18 + 5*lambda)*omega + 
            a^2*(67 + 54*lambda + 10*lambda^2 - m^2*(11 + 4*lambda) + 8*I*omega - 32*I*lambda*omega)) + 
            a^6*z^8*(4 + 8*lambda - 2*I*a*m*(9 + 2*lambda) - 2*a^3*m*(16 + 5*lambda)*omega + 
            a^2*(-31 - 24*lambda - 5*lambda^2 + m^2*(1 + 4*lambda) + 8*I*omega + 32*I*lambda*omega))))/
            ((1 + a^2*z^2)^2*(1 - 2*z + a^2*z^2)^2*(2 - 2*I*a*m*z - 2*I*a^3*m*z^3 + lambda + 
            a^4*z^4*(1 + lambda) + a^2*z^2*(3 + 2*z + 2*lambda)))
        end
    elseif s == -1
        return begin
            (z^2*((-1 + 2*z)*lambda^2 + a^2*z*(m^2*(-4*z^2 + z*(2 + lambda) - 4*I*omega) + 
            lambda*(-24*z^3 + 4*z^2*(5 + 2*lambda) + z*(-4 - 5*lambda + 8*I*omega) - 4*I*omega)) + 
            2*I*a*m*lambda*(-z + 2*z^2 + I*omega) + 2*a^12*z^11*(-1 + lambda)*(z - 2*I*omega) - 
            2*a^11*m*z^10*(-5 + lambda)*omega + 2*a^9*m*z^8*(-3*I*z^2 + I*z*(-2 + m^2 - lambda + 10*I*omega) - 
            5*(-4 + lambda)*omega) + 2*I*a^7*m*z^6*(6*z^3 + z^2*(5 + 2*lambda) + 
            z*(-6 + 3*m^2 - 4*lambda + 30*I*omega) + 10*I*(-3 + lambda)*omega) + 
            2*I*a^5*m*z^4*(-8*z^3 + z^2*(19 + 6*lambda) + 3*z*(-2 + m^2 - 2*lambda + 10*I*omega) + 
            10*I*(-2 + lambda)*omega) + 2*I*a^3*m*z^2*(-14*z^3 + z^2*(11 + 6*lambda) + 
            z*(-2 + m^2 - 4*lambda + 10*I*omega) + 5*I*(-1 + lambda)*omega) - 
            a^10*z^9*(12*z^2*(-1 + lambda) + 4*I*(-4 + m^2 + 5*lambda)*omega + 
            z*(5 - m^2*(-3 + lambda) - 4*lambda + lambda^2 + 16*I*omega - 8*I*lambda*omega)) + 
            a^4*z^3*(-8*z^4 - 4*z^3*(-3 + 8*lambda) - 2*z^2*(3 + m^2 - 24*lambda - 6*lambda^2 - 8*I*omega) - 
            4*I*(-1 + 4*m^2 + 5*lambda)*omega + z*(1 - 14*lambda - 10*lambda^2 + m^2*(3 + 4*lambda) - 16*I*omega + 
            32*I*lambda*omega)) + a^8*z^7*(8*z^3*(-3 + 2*lambda) + 
            2*z^2*(9 + 3*m^2 - 8*lambda + lambda^2 + 8*I*omega) - 8*I*(-3 + 2*m^2 + 5*lambda)*omega + 
            z*(-3 - 4*lambda - 5*lambda^2 + m^2*(-7 + 4*lambda) - 48*I*omega + 32*I*lambda*omega)) + 
            a^6*z^5*(16*z^4 + 4*z^3*(-3 + 2*lambda) + 8*z^2*(m^2 + 3*lambda + lambda^2 + 4*I*omega) - 
            8*I*(-2 + 3*m^2 + 5*lambda)*omega + z*(1 - 16*lambda - 10*lambda^2 + m^2*(-3 + 6*lambda) - 48*I*omega + 
            48*I*lambda*omega))))/((1 + a^2*z^2)^2*(1 - 2*z + a^2*z^2)^2*
            (2*I*a*m*z + 2*I*a^3*m*z^3 + a^4*z^4*(-1 + lambda) + lambda + a^2*z^2*(-1 + 2*z + 2*lambda)))
        end
    elseif s == 2
        return begin
            (z^2*(24*a^12*z^12 - lambda^3 - 48*I*a^10*z^11*(-3*I + a^2*omega) - 2*lambda^2*(8 + a*m*omega) + 
            4*lambda*(-21 - 3*(I + 4*a*m)*omega + 7*a^2*omega^2) - 
            12*a^8*z^10*(-24 + 6*I*a*m - a^2*(5 + 3*m^2 + 20*I*omega) + 4*a^4*omega^2) + 
            8*I*a^6*z^9*(24*I + 18*a*m + 3*I*a^2*(9 + m^2 + 12*I*omega) + 
            a^3*m*(19 - 3*m^2 + 4*lambda + 18*I*omega) + a^4*(-31 + 15*m^2 - 4*lambda - 24*I*omega)*omega - 
            24*a^5*m*omega^2 + 12*a^6*omega^3) + 8*(-18 - (9*I + 23*a*m)*omega + 
            a*(-3*I*m + a*(11 - 3*m^2))*omega^2 + 3*a^3*m*omega^3) + 
            a^3*z^6*(384*I*m + 8*I*a^2*m*(-177 + 18*m^2 - 53*lambda - 2*lambda^2 + 24*I*omega) + 
            16*a*(-33 + 12*m^2 - 10*lambda - lambda^2 - 36*I*omega) + 
            a^3*(-756 - 48*m^4 - lambda^3 + lambda^2*(-41 + 16*I*omega) + lambda*(-334 + 364*I*omega) + 
            m^2*(564 + 106*lambda + lambda^2 - 756*I*omega) + 780*I*omega) + 
            2*a^4*m*(-506 + 126*m^2 - 132*lambda - lambda^2 + 588*I*omega)*omega + 
            4*a^5*(49 - 93*m^2 + 37*lambda - 144*I*omega)*omega^2 + 168*a^6*m*omega^3) + 
            a*z^4*(96*I*m + 8*I*a^2*m*(-202 + 9*m^2 - 65*lambda - 4*lambda^2) - 
            8*a*(120 + 50*lambda + 5*lambda^2 + 72*I*omega) + a^3*(-1068 - 24*m^4 - 3*lambda^3 + 
            lambda^2*(-74 + 32*I*omega) + 2*m^2*(246 + 58*lambda + lambda^2 - 288*I*omega) + 
            lambda*(-512 + 388*I*omega) + 488*I*omega) + 6*a^4*m*(-224 + 36*m^2 - 60*lambda - lambda^2 + 
            172*I*omega)*omega + 12*a^5*(38 - 34*m^2 + 17*lambda - 48*I*omega)*omega^2 + 216*a^6*m*omega^3) + 
            4*I*a*z^3*(12*m*(3 + lambda) + I*a*(-408 - 194*lambda - 27*lambda^2 - lambda^3 + 16*m^2*(4 + lambda) - 
            168*I*omega) - 12*a^4*m*(17 + lambda)*omega^2 + 96*a^5*omega^3 + 
            2*a^3*omega*(-53 - 26*lambda - 3*lambda^2 + m^2*(79 + 7*lambda) + 60*I*omega + 24*I*lambda*omega) - 
            2*a^2*m*(-98 - 35*lambda - 3*lambda^2 + m^2*(10 + lambda) + 128*I*omega + 32*I*lambda*omega)) + 
            2*I*a^3*z^5*(24*m*(9 + 4*lambda) - 24*a^4*m*(25 + lambda)*omega^2 + 288*a^5*omega^3 + 
            4*a^3*omega*(-89 - 35*lambda - 3*lambda^2 + m^2*(113 + 8*lambda) + 51*I*omega + 27*I*lambda*omega) - 
            4*a^2*m*(-143 - 44*lambda - 3*lambda^2 + m^2*(23 + 2*lambda) + 181*I*omega + 43*I*lambda*omega) + 
            I*a*(-924 - 394*lambda - 47*lambda^2 - lambda^3 + 4*m^2*(91 + 16*lambda) - 300*I*omega + 
            84*I*lambda*omega)) + 4*a^6*z^8*(36 - 24*m^2 + 6*a^3*m*(4*m^2 - 3*(4 + lambda - 6*I*omega))*
            omega - 2*a^4*(7 + 15*m^2 - 5*lambda + 24*I*omega)*omega^2 + 12*a^5*m*omega^3 + 
            2*a*m*(-44*I + 9*I*m^2 - 11*I*lambda + 36*omega) - 
            a^2*(39 + 6*m^4 + 20*lambda + 2*lambda^2 + m^2*(-65 - 8*lambda + 78*I*omega) - 142*I*omega - 
            22*I*lambda*omega + 48*omega^2)) + 8*I*a^4*z^7*(-12*I + 6*a*m*(-5 + lambda) + 
            I*a^2*(m^2*(62 + 8*lambda) - 3*(24 + lambda^2 + 2*lambda*(5 - I*omega) + 10*I*omega)) + 
            a^3*m*(88 + lambda^2 - m^2*(16 + lambda) + lambda*(23 - 18*I*omega) - 66*I*omega) - 
            2*a^5*m*(49 + lambda)*omega^2 + 48*a^6*omega^3 + a^4*omega*(-73 - lambda^2 + 3*m^2*(23 + lambda) - 
            14*I*omega + 10*I*lambda*(2*I + omega))) + 2*z*((9 + lambda)*(24 + 10*lambda + lambda^2 + 12*I*omega) - 
            8*I*a^3*m*(13 + lambda)*omega^2 + 48*I*a^4*omega^3 - 
            4*a^2*omega*(12*I + I*lambda^2 - 2*I*m^2*(10 + lambda) + 19*omega + 7*lambda*(I + omega)) + 
            4*a*m*(24*I + I*lambda^2 + 31*omega + lambda*(10*I + 7*omega))) + 
            z^2*(-8*I*a*m*(60 + 23*lambda + 2*lambda^2 + 6*I*omega) - 12*(24 + 10*lambda + lambda^2 + 12*I*omega) + 
            6*a^3*m*(-134 + 10*m^2 - 36*lambda - lambda^2 + 44*I*omega)*omega + 
            4*a^4*(85 - 45*m^2 + 31*lambda - 48*I*omega)*omega^2 + 120*a^5*m*omega^3 + 
            a^2*(-3*lambda^3 + lambda^2*(-57 + 16*I*omega) + lambda*(-342 + 100*I*omega) + 
            m^2*(152 + 42*lambda + lambda^2 - 132*I*omega) - 12*(54 + 3*I*omega + 4*omega^2)))))/
            ((1 + a^2*z^2)^2*(1 - 2*z + a^2*z^2)^2*(24 + 10*lambda + lambda^2 - 
            4*I*a*m*(6*z^2 + 2*z*(4 + lambda) + 3*I*omega) + 12*I*omega + 24*a^3*m*z^2*(I*z + 2*omega) + 
            12*a^4*z^2*(z^2 - 2*I*z*omega - 2*omega^2) - 4*a^2*(6*z^3 + z^2*(-3 + 6*m^2 - 6*I*omega) - 
            2*I*z*(1 + lambda)*omega + 3*omega^2)))
        end
    elseif s == -2
        return begin
            (z^2*(-((-1 + 2*z)*(-2 + 6*z - lambda)*(2*lambda + lambda^2 - 12*I*omega)) - 48*a^11*m*z^8*omega*(3*z^2 - omega^2) + 
            24*a^12*z^10*(z^2 - 2*I*z*omega + 4*omega^2) - 4*a^10*z^8*(36*z^3 - 3*z^2*(5 + 3*m^2 + 8*I*omega) + 6*(-17 + 5*m^2 - lambda)*omega^2 + 
            2*z*omega*(39*I + 3*I*m^2 - 4*I*lambda + 24*omega)) + 8*a^9*m*z^6*(9*I*z^4 + z^2*(-72 + 12*m^2 - 7*lambda - 6*I*omega)*omega + 
            2*I*z*(-3 + lambda)*omega^2 + 21*omega^3 + z^3*(-3*I + 3*I*m^2 - 4*I*lambda + 30*omega)) - 
            2*I*a^7*m*z^4*(72*z^5 + 4*z^4*(9*m^2 - 11*lambda + 12*I*omega) + I*z^2*(-426 + 126*m^2 - 92*lambda - lambda^2 - 12*I*omega)*omega - 
            24*z*(-3 + lambda)*omega^2 + 108*I*omega^3 + 4*z^3*(12 + 15*lambda + lambda^2 - m^2*(12 + lambda) + 150*I*omega + 14*I*lambda*omega)) - 
            2*I*a^3*m*(192*z^6 + 24*z^5*(-7 + 4*lambda) + 4*z^4*(-6 + 9*m^2 - 33*lambda - 4*lambda^2 - 72*I*omega) - 8*z*(-3 + lambda)*omega^2 + 12*I*omega^3 - 
            z^2*omega*(90*I - 30*I*m^2 + 52*I*lambda + 3*I*lambda^2 + 60*omega) + 4*z^3*(6 + 11*lambda + 3*lambda^2 - m^2*(6 + lambda) + 84*I*omega + 
            20*I*lambda*omega)) - 2*I*a^5*m*z^2*(24*z^5*(-9 + lambda) + 4*z^4*(3 + 18*m^2 - 37*lambda - 2*lambda^2 - 96*I*omega) + 
            3*I*z^2*(-96 + 36*m^2 - 36*lambda - lambda^2 + 20*I*omega)*omega - 24*z*(-3 + lambda)*omega^2 + 60*I*omega^3 + 
            4*z^3*(15 + 20*lambda + 3*lambda^2 - m^2*(15 + 2*lambda) + 189*I*omega + 31*I*lambda*omega)) + 
            4*a^8*z^6*(-6*(9 + m^2)*z^3 + 72*z^4 + z^2*(9 - 6*m^4 - 2*lambda^2 + lambda*(-4 - 22*I*omega) + m^2*(33 + 8*lambda + 30*I*omega) + 258*I*omega) + 
            3*(55 - 31*m^2 + 7*lambda)*omega^2 - 2*z*omega*(87*I - I*lambda^2 + 3*I*m^2*(3 + lambda) + 114*omega + 6*lambda*(-2*I + omega))) + 
            2*a*m*(-48*I*z^4 - 24*I*z^3*(-1 + lambda) + 4*I*z^2*(7*lambda + 2*lambda^2 + 18*I*omega) - (12 + 8*lambda + lambda^2 - 12*I*omega)*omega + 
            4*z*((-I)*lambda^2 + 15*omega + lambda*(-2*I + 3*omega))) - a^2*(8*z^4*(10*lambda + 5*lambda^2 - 72*I*omega) - 
            4*z^3*((26 - 16*m^2)*lambda + 15*lambda^2 + lambda^3 - 240*I*omega) + 12*(-2 + 2*m^2 - lambda)*omega^2 + 
            z^2*(3*lambda^3 + lambda^2*(21 - m^2 + 16*I*omega) + lambda*(30 - 34*m^2 - 28*I*omega) + 12*I*(-35 + 5*m^2 + 12*I*omega)*omega) + 
            8*z*omega*(6*I - I*lambda^2 + 15*omega + lambda*(I + 2*I*m^2 + 3*omega))) + 
            a^4*z^2*(96*z^5 + 16*z^4*(-9 + 12*m^2 - 2*lambda - lambda^2 + 36*I*omega) + 60*(3 - 3*m^2 + lambda)*omega^2 + 
            2*z^3*(36 + 66*lambda + 35*lambda^2 + lambda^3 - 4*m^2*(27 + 16*lambda) - 1068*I*omega + 84*I*lambda*omega) - 
            8*z*omega*(39*I - 3*I*lambda^2 + I*m^2*(3 + 7*lambda) + 84*omega + 2*lambda*(-I + 6*omega)) - 
            z^2*(24*m^4 + 3*lambda^3 - 2*m^2*(30 + 50*lambda + lambda^2) + lambda^2*(38 + 32*I*omega) + 4*lambda*(16 + 33*I*omega) - 
            12*(-1 + 134*I*omega + 48*omega^2))) - a^6*z^4*(48*(-3 + 2*m^2)*z^4 + 192*z^5 + 
            8*z^3*(m^2*(30 + 8*lambda) - 3*(lambda^2 + lambda*(2 + 2*I*omega) - 54*I*omega)) + 12*(-42 + 34*m^2 - 9*lambda)*omega^2 + 
            8*z*omega*(87*I - 3*I*lambda^2 + I*m^2*(9 + 8*lambda) + 159*omega + lambda*(-11*I + 15*omega)) + 
            z^2*(48*m^4 + lambda^3 + lambda^2*(29 + 16*I*omega) - m^2*(156 + 98*lambda + lambda^2 + 180*I*omega) + lambda*(54 + 236*I*omega) - 
            12*(-1 + 179*I*omega + 48*omega^2)))))/((1 + a^2*z^2)^2*(1 - 2*z + a^2*z^2)^2*
            (2*lambda + lambda^2 - 12*I*omega + 24*a^3*m*z^2*((-I)*z + 2*omega) + 4*a*m*(6*I*z^2 + 2*I*z*lambda + 3*omega) + 
            12*a^4*z^2*(z^2 + 2*I*z*omega - 2*omega^2) - 4*a^2*(6*z^3 + z^2*(-3 + 6*m^2 + 6*I*omega) + 2*I*z*(-3 + lambda)*omega + 3*omega^2)))
        end
    else
        throw(DomainError(s, "Currently only spin weight s of 0, +/-1, +/-2 are supported"))
    end
end

function _ingoing_coefficient_at_inf_legacy_impl(s::Int, m::Int, a, omega, lambda, order::Int; data_type=_DEFAULTDATATYPE)
    #=
    We have derived/shown the explicit expression for
    different physically-relevant spin weight (s=0, \pm 1, \pm2)
    for up to (1/r)^3, which is probably more than enough
    
    But we have also shown a recurrence relation where
    one can generate as higher an order as one pleases.
    However, the recurrence relation that we have
    actually depends *all* previous terms so this function
    is designed to be evaluated recursively to build
    the full list of coefficients
    =#
    if order < 0
        throw(DomainError(order, "Only positive expansion order is supported"))
    end

    if order == 0
        return one(data_type) # This is always 1.0
    elseif order == 1
        if s == 0
            return -(one(omega)/2)*I*(lambda + 2*a*m*omega)
        elseif s == +1
            return begin
                -((I*(4 + lambda^2 + 8*a*m*omega + 2*lambda*(2 + a*m*omega)))/
                (2*(2 + lambda)))
            end
        elseif s == -1
            return -(one(omega)/2)*I*(lambda + 2*a*m*omega)
        elseif s == +2
            return begin
                (I*(-lambda^3 - 2*lambda^2*(8 + a*m*omega) + 
                4*lambda*(-21 - 3*(I + 4*a*m)*omega + 7*a^2*omega^2) + 
                8*(-18 - (9*I + 23*a*m)*omega + 
                a*(11*a - 3*I*m - 3*a*m^2)*omega^2 + 
                3*a^3*m*omega^3)))/(2*(10*lambda + lambda^2 + 
                12*(2 + (I + a*m)*omega - a^2*omega^2)))
            end
        elseif s == -2
            return -(one(omega)/2)*I*(2 + lambda + 2*a*m*omega)
        else
            throw(DomainError(s, "Currently only spin weight s of 0, +/-1, +/-2 are supported"))
        end
    elseif order == 2
        if s == 0
            return begin
                (one(omega)/8)*(-((-2 + lambda)*lambda) - 4*(I + a*m*(-1 + lambda))*omega -
                4*a*m*(2*I + a*m)*omega^2)
            end
        elseif s == +1
            return begin
                -((lambda^3 + 4*lambda^2*(1 + a*m*omega) + 
                8*a*omega*(m*(2 + 2*I*omega) - a*omega + 3*a*m^2*omega) + 
                4*lambda*(1 + a*m*(5 + 2*I*omega)*omega + a^2*(-2 + m^2)*omega^2))/
                (8*(2 + lambda)))
            end
        elseif s == -1
            return begin
                (one(omega)/8)*(-lambda^2 + lambda*(2 - 4*a*m*omega) +
                4*a*omega*(m + 2*a*omega - m*(2*I + a*m)*omega))
            end
        elseif s == +2
            return begin
                -((lambda^4 + 4*lambda^3*(5 + a*m*omega) + 
                4*lambda^2*(37 + 2*a*m*(13 + I*omega)*omega + 
                a^2*(-11 + m^2)*omega^2) - 
                8*lambda*(-60 + 8*a*m*(-11 - 2*I*omega)*omega + 
                a^2*(39 - 19*m^2)*omega^2 + 14*a^3*m*omega^3) - 
                16*(a^2*(34 + m^2*(-49 - 9*I*omega) + 3*I*omega)*
                omega^2 + a^3*m*(43 - 3*m^2 + 6*I*omega)*omega^3 + 
                3*a^4*(-4 + m^2)*omega^4 - 9*(4 + omega^2) + 
                2*a*m*omega*(-44 - 15*I*omega + 3*omega^2)))/
                (8*(10*lambda + lambda^2 + 12*(2 + (I + a*m)*omega - 
                a^2*omega^2))))
            end
        elseif s == -2
            return begin
                (one(omega)/8)*((-lambda)*(2 + lambda) - 4*(-3*I + a*m*(1 + lambda))*omega -
                4*a*m*(2*I + a*m)*omega^2)
            end
        else
            throw(DomainError(s, "Currently only spin weight s of 0, +/-1, +/-2 are supported"))
        end
    elseif order == 3
        if s == 0
            return begin
                (one(omega)/48)*(I*(-6 + lambda)*(-2 + lambda)*lambda +
                2*(12 - 18*lambda + I*a*m*(12 + lambda*(-16 + 3*lambda)))*omega + 
                4*I*a*(3*a*m^2*(-2 + lambda) + 2*a*(-1 + lambda) + 
                6*I*m*(1 + lambda))*omega^2 + 
                8*I*a*m*(-8 + 6*I*a*m + a^2*(2 + m^2))*omega^3)
            end
        elseif s == +1
            return begin
                (1/(48*(2 + lambda)))*(I*(lambda^4 + 6*a*m*lambda^3*omega + 
                4*lambda^2*(-3 + (6*I + 4*a*m)*omega + 
                a*(-4*a + 6*I*m + 3*a*m^2)*omega^2) + 
                8*lambda*(-2 + (12*I - 5*a*m)*omega + 
                a*(12*I*m + a*(-4 + 9*m^2))*omega^2 + 
                a*m*(-8 + 6*I*a*m + a^2*(-4 + m^2))*omega^3) + 
                16*omega*(6*I + a^3*m*(-1 + 4*m^2)*omega^2 + 
                3*I*a^2*omega*(I - 2*omega + 4*m^2*omega) + 
                a*m*(-3 + 12*I*omega - 8*omega^2))))
            end
        elseif s == -1
            return begin
                (one(omega)/48)*I*(lambda^3 + lambda^2*(-8 + 6*a*m*omega) +
                8*a*omega*(a*omega + m*(2 - 3*a*m*omega + 
                (-8 + 6*I*a*m + a^2*(-4 + m^2))*omega^2)) + 
                4*lambda*(3 + omega*(6*I + a*(-4*a*omega + 
                m*(-8 + 3*(2*I + a*m)*omega)))))
            end
        elseif s == +2
            return begin
                -((I*(-lambda^5 - 2*lambda^4*(10 + 3*a*m*omega) - 
                4*lambda^3*(37 + 2*a*m*(20 + 3*I*omega)*omega + 
                a^2*(-13 + 3*m^2)*omega^2) - 
                8*lambda^2*(60 + 2*a^2*(-29 + 3*m^2*(9 + I*omega))*
                omega^2 + a^3*m*(-31 + m^2)*omega^3 + 
                a*m*omega*(157 + 48*I*omega - 8*omega^2)) + 
                16*lambda*(a^2*(91 + m^2*(-210 - 81*I*omega) + 9*I*omega)*
                omega^2 + 2*a^3*m*(73 - 13*m^2 + 21*I*omega)*
                omega^3 + 3*a^4*(-10 + 7*m^2)*omega^4 - 
                9*(4 + omega^2) + 2*a*m*omega*(-116 - 63*I*omega + 
                29*omega^2)) + 96*a*omega*((-a^3)*m^4*omega^3 + 
                a*omega*(18 + 9*I*omega - 11*a^2*omega^2) + 
                a^2*m^3*omega^2*(-28 - 7*I*omega + a^2*omega^2) + 
                a*m^2*omega*(-70 - 55*I*omega + 2*(7 + 15*a^2)*
                omega^2 + 6*I*a^2*omega^3) + 
                m*(-36 - 36*I*omega + (25 + 47*a^2)*omega^2 + 
                I*(8 + 23*a^2)*omega^3 - 2*a^2*(4 + 5*a^2)*
                omega^4))))/(48*(10*lambda + lambda^2 + 
                12*(2 + (I + a*m)*omega - a^2*omega^2))))
            end
        elseif s == -2
            return begin
                (one(omega)/48)*(I*(-4 + lambda)*lambda*(2 + lambda) +
                2*(6*(-4 + lambda) + I*a*m*(-24 + lambda*(-4 + 3*lambda)))*
                omega + 4*a*(-6*m*(-1 + lambda) + 
                I*a*(-6 + (2 + 3*m^2)*lambda))*omega^2 + 
                8*I*a*m*(-8 + 6*I*a*m + a^2*(2 + m^2))*omega^3)
            end
        else
            throw(DomainError(s, "Currently only spin weight s of 0, +/-1, +/-2 are supported"))
        end
    else
        throw(ArgumentError("explicit infinity bridge supports orders 0 through 3"))
    end
end

function ingoing_coefficient_at_inf(
    s::Int, m::Int, a, omega, lambda, order::Int;
    data_type=_DEFAULTDATATYPE,
)
    key = _legacy_series_key(
        s, m, a, omega, lambda, INFINITY_INGOING_SERIES, order, data_type
    )
    T = _component_type(data_type)
    return _with_request_precision(T, key.precision_bits) do
        _chart_denominator(key)
        if order <= 3
            value = _ingoing_coefficient_at_inf_legacy_impl(
                key.s, key.m, key.a, key.omega, key.lambda, order;
                data_type=Complex{T},
            )
            _assert_value(key, Complex{T}(value), "legacy ingoing infinity coefficient")
        else
            build_asymptotic_series(key).coefficients[order + 1]
        end
    end
end

function PplusInf_z(s::Int, m::Int, a, omega, lambda, z)
    if s == 0
        return begin
            (2*I*(omega + a^2*z^4*(I + a^2*omega) + z^2*(-I + 2*a^2*omega)))/
            ((1 + a^2*z^2)*(1 - 2*z + a^2*z^2))
        end
    elseif s == 1
        return begin
            ((1 + a^2*z^2)*(-((2*(-1 + z)*z)/(1 + a^2*z^2)) - (2*z*(1 - 2*z + a^2*z^2))/
            (1 + a^2*z^2)^2 + (2*a*z^2*(1 - 2*z + a^2*z^2)*((-I)*m*(1 + 3*a^2*z^2) + 
            a*z*(3 + 3*z + 2*lambda + 2*a^2*z^2*(1 + lambda))))/((1 + a^2*z^2)*
            (2 - 2*I*a*m*z - 2*I*a^3*m*z^3 + lambda + a^4*z^4*(1 + lambda) + 
            a^2*z^2*(3 + 2*z + 2*lambda))) + 2*I*omega))/(1 - 2*z + a^2*z^2)
        end
    elseif s == -1
        return begin
            (1/(1 - 2*z + a^2*z^2))*((1 + a^2*z^2)*(-((2*(-1 + z)*z)/(1 + a^2*z^2)) - 
            (2*z*(1 - 2*z + a^2*z^2))/(1 + a^2*z^2)^2 + 
            (2*a*z^2*(1 - 2*z + a^2*z^2)*(I*m*(1 + 3*a^2*z^2) + 
            a*z*(-1 + 3*z + 2*a^2*z^2*(-1 + lambda) + 2*lambda)))/
            ((1 + a^2*z^2)*(2*I*a*m*z + 2*I*a^3*m*z^3 + a^4*z^4*(-1 + lambda) + lambda + 
            a^2*z^2*(-1 + 2*z + 2*lambda))) + 2*I*omega))
        end
    elseif s == 2
        return begin
            (1/(1 - 2*z + a^2*z^2))*((1 + a^2*z^2)*(-((2*(-1 + z)*z)/(1 + a^2*z^2)) - 
            (2*z*(1 - 2*z + a^2*z^2))/(1 + a^2*z^2)^2 + 2*I*omega + 
            (8*a*z^2*(1 - 2*z + a^2*z^2)*(-6*a*m^2*z + I*m*(-4 + 9*a^2*z^2 - lambda + 
            z*(-6 - 12*I*a^2*omega)) + a*(6*a^2*z^3 + I*(1 + lambda)*omega + z^2*(-9 - 9*I*a^2*omega) + 
            z*(3 + 6*I*omega - 6*a^2*omega^2))))/((1 + a^2*z^2)*(24 + 10*lambda + lambda^2 - 
            4*I*a*m*(6*z^2 + 2*z*(4 + lambda) + 3*I*omega) + 12*I*omega + 24*a^3*m*z^2*(I*z + 2*omega) + 
            12*a^4*z^2*(z^2 - 2*I*z*omega - 2*omega^2) - 4*a^2*(6*z^3 + z^2*(-3 + 6*m^2 - 6*I*omega) - 
            2*I*z*(1 + lambda)*omega + 3*omega^2)))))
        end
    elseif s == -2
        return begin
            (1/(1 - 2*z + a^2*z^2))*((1 + a^2*z^2)*(-((2*(-1 + z)*z)/(1 + a^2*z^2)) - 
            (2*z*(1 + z*(-2 + a^2*z)))/(1 + a^2*z^2)^2 + 2*I*omega + 
            (8*a*z^2*(1 + z*(-2 + a^2*z))*(-3*a*z*(-1 + 2*m^2 + 3*z) + I*m*(6*z + lambda) - 
            I*a*(-3 + 6*z + lambda)*omega + 3*a^2*m*z*(-3*I*z + 4*omega) + 
            3*a^3*z*(2*z^2 + 3*I*z*omega - 2*omega^2)))/((1 + a^2*z^2)*(lambda*(2 + lambda) - 12*I*omega + 
            12*a^4*z^2*(z - (1 - I)*omega)*(z + (1 + I)*omega) + 24*a^3*m*z^2*((-I)*z + 2*omega) + 
            4*a*m*(2*I*z*(3*z + lambda) + 3*omega) + 4*a^2*(-3*z^2*(-1 + 2*m^2 + 2*z) - 
            2*I*z*(-3 + 3*z + lambda)*omega - 3*omega^2)))))
        end
    else
        throw(DomainError(s, "Currently only spin weight s of 0, +/-1, +/-2 are supported"))
    end
end

function QplusInf_z(s::Int, m::Int, a, omega, lambda, z)
    if s == 0
        return begin
            -((z^2*(-2*z*(-1 + lambda) + lambda - 4*a^2*z^3*(1 + lambda) - 2*a^4*z^5*(3 + lambda) + 2*a*m*omega + 
            a^6*z^6*(1 - m^2 + lambda + 2*a*m*omega) + a^2*z^4*(8 + a^2*(2 - 2*m^2 + 3*lambda) + 
            6*a^3*m*omega) + z^2*(-4 + a^2*(1 - m^2 + 3*lambda) + 6*a^3*m*omega)))/
            ((1 + a^2*z^2)^2*(1 - 2*z + a^2*z^2)^2))
        end
    elseif s == 1
        return begin
            (z^2*(2*a^12*z^12*(1 + lambda) + 4*I*a^10*z^11*(1 + lambda)*(3*I + a^2*omega) - 
            (2 + lambda)*(2 + lambda + 2*a*m*omega) - a^6*z^8*(-4 - 8*lambda + 2*I*a*m*(9 + 2*lambda) + 
            a^2*(31 + 5*lambda^2 - m^2*(1 + 4*lambda) + 8*lambda*(3 + 4*I*omega) + 16*I*omega) + 
            10*a^3*m*(-2 + lambda)*omega) - a^4*z^6*(52 + 32*lambda + 2*I*a*m*(31 + 6*lambda) + 
            a^2*(71 + 10*lambda^2 - 3*m^2*(3 + 2*lambda) + 8*lambda*(7 + 6*I*omega) + 48*I*omega) + 
            20*a^3*m*(-1 + lambda)*omega) - a*z^2*(4*I*m*(2 + lambda) - a*m^2*(4 + lambda) + 
            a*(2 + lambda)*(14 + 5*lambda + 8*I*omega) + 10*a^2*m*(1 + lambda)*omega) + 
            2*z*(I*a*m*(2 + lambda) + (2 + lambda)^2 + 2*I*a^2*(2 + m^2 + lambda)*omega) + 
            2*a^6*z^9*(8 - 6*I*a*m + a^2*(-3 + 3*m^2 - 4*lambda + lambda^2 - 8*I*omega) - 
            I*a^3*m*(-4 + m^2 - lambda - 10*I*omega) + 2*I*a^4*(6 + m^2 + 5*lambda)*omega) + 
            2*a^4*z^7*(-4 + 8*I*a*m + a^3*m*(14*I - 3*I*m^2 + 4*I*lambda - 30*omega) + 
            4*a^2*(10 + m^2 + 7*lambda + lambda^2 - 4*I*omega) + 4*I*a^4*(7 + 2*m^2 + 5*lambda)*omega) + 
            2*I*a^3*z^5*(14*m + a^2*(-3*m^3 + 6*m*(3 + lambda + 5*I*omega)) + 
            I*a*(-69 + m^2 - 48*lambda - 6*lambda^2 + 8*I*omega) + 4*a^3*(8 + 3*m^2 + 5*lambda)*omega) + 
            2*a^2*z^3*(36 - 2*m^2 + 26*lambda + 4*lambda^2 - I*a*(m^3 - 2*m*(5 + 2*lambda + 5*I*omega)) + 
            2*I*a^2*(9 + 4*m^2 + 5*lambda)*omega) - a^8*z^10*(-6*I*a*m - 8*(1 + 2*lambda) + 
            2*a^3*m*(-3 + lambda)*omega + a^2*(1 - m^2*(-1 + lambda) + lambda^2 + 8*I*lambda*omega)) - 
            a^2*z^4*(24*(2 + lambda) + 2*I*a*m*(23 + 6*lambda) + 20*a^3*m*lambda*omega + 
            a^2*(67 + 54*lambda + 10*lambda^2 - m^2*(11 + 4*lambda) + 48*I*omega + 32*I*lambda*omega))))/
            ((1 + a^2*z^2)^2*(1 - 2*z + a^2*z^2)^2*(2 - 2*I*a*m*z - 2*I*a^3*m*z^3 + lambda + 
            a^4*z^4*(1 + lambda) + a^2*z^2*(3 + 2*z + 2*lambda)))
        end
    elseif s == -1
        return begin
            (z^2*((-1 + 2*z)*lambda^2 + 2*a^12*z^11*(-1 + lambda)*(z + 2*I*omega) - 2*a^11*m*z^10*(1 + lambda)*omega + 
            2*a^9*m*z^8*(-3*I*z^2 + I*z*(-2 + m^2 - lambda - 2*I*omega) - (6 + 5*lambda)*omega) + 
            2*I*a^7*m*z^6*(3*m^2*z + 6*z^3 + z^2*(5 + 2*lambda) - 2*z*(3 + 2*lambda + 5*I*omega) + 
            2*I*(7 + 5*lambda)*omega) + 2*I*a^5*m*z^4*(-8*z^3 + z^2*(19 + 6*lambda) + 
            3*z*(m^2 - 2*(1 + lambda + 3*I*omega)) + 2*I*(8 + 5*lambda)*omega) + 
            2*I*a^3*m*z^2*(-14*z^3 + z^2*(11 + 6*lambda) + z*(m^2 - 2*(1 + 2*lambda + 7*I*omega)) + 
            I*(9 + 5*lambda)*omega) + 2*a*m*(2*I*z^2*lambda - (2 + lambda)*omega + z*((-I)*lambda + 4*omega)) - 
            a^10*z^9*(12*z^2*(-1 + lambda) + 4*I*(5 + m^2 - 5*lambda)*omega + 
            z*(5 - m^2*(-3 + lambda) - 4*lambda + lambda^2 - 12*I*omega + 8*I*lambda*omega)) + 
            a^2*z*(-24*z^3*lambda + m^2*(-4*z^2 + z*(2 + lambda) - 4*I*omega) + 
            4*z^2*(5*lambda + 2*lambda^2 - 6*I*omega) + 4*I*(-1 + lambda)*omega - 
            z*(4*lambda + 5*lambda^2 - 20*I*omega + 8*I*lambda*omega)) + 
            a^8*z^7*(8*z^3*(-3 + 2*lambda) + 2*z^2*(9 + 3*m^2 - 8*lambda + lambda^2 - 4*I*omega) - 
            8*I*(5 + 2*m^2 - 5*lambda)*omega + z*(-3 - 4*lambda - 5*lambda^2 + m^2*(-7 + 4*lambda) + 56*I*omega - 
            32*I*lambda*omega)) + a^4*z^3*(-8*z^4 - 4*z^3*(-3 + 8*lambda) - 
            2*z^2*(3 + m^2 - 24*lambda - 6*lambda^2 + 28*I*omega) - 4*I*(5 + 4*m^2 - 5*lambda)*omega + 
            z*(1 - 14*lambda - 10*lambda^2 + m^2*(3 + 4*lambda) + 72*I*omega - 32*I*lambda*omega)) + 
            a^6*z^5*(16*z^4 + 4*z^3*(-3 + 2*lambda) + 8*z^2*(m^2 + 3*lambda + lambda^2 - 5*I*omega) - 
            8*I*(5 + 3*m^2 - 5*lambda)*omega + z*(1 - 16*lambda - 10*lambda^2 + m^2*(-3 + 6*lambda) + 96*I*omega - 
            48*I*lambda*omega))))/((1 + a^2*z^2)^2*(1 - 2*z + a^2*z^2)^2*
            (2*I*a*m*z + 2*I*a^3*m*z^3 + a^4*z^4*(-1 + lambda) + lambda + a^2*z^2*(-1 + 2*z + 2*lambda)))
        end
    elseif s == 2
        return begin
            (z^2*(24*a^12*z^12 - lambda^3 + 48*I*a^10*z^11*(3*I + a^2*omega) - 2*lambda^2*(8 + a*m*omega) + 
            8*I*a^6*z^9*(24*I + 18*a*m + 3*I*a^2*(9 + m^2) + 
            a^3*m*(19 - 3*m^2 + 4*lambda - 30*I*omega) + a^4*(23 + 3*m^2 - 4*lambda + 24*I*omega)*omega) + 
            4*lambda*(-21 - (3*I + 8*a*m)*omega + 3*a^2*omega^2) + 
            12*a^8*z^10*(24 - 6*I*a*m + a^2*(5 + 3*m^2 - 8*I*omega) - 12*a^3*m*omega + 8*a^4*omega^2) - 
            2*I*a^3*z^5*(-24*m*(9 + 4*lambda) + a*(-4*I*m^2*(91 + 16*lambda) + 
            I*(924 + 47*lambda^2 + lambda^3 + lambda*(394 - 84*I*omega) + 732*I*omega)) + 
            4*a^2*m*(-143 - 3*lambda^2 + m^2*(23 + 2*lambda) + lambda*(-44 + 31*I*omega) + 313*I*omega) + 
            4*a^3*(5 + 3*lambda^2 - m^2*(41 + 8*lambda) + 5*lambda*(7 - 3*I*omega) - 219*I*omega)*omega + 
            24*a^4*m*(1 + lambda)*omega^2) + 24*(-6 - (3*I + 5*a*m)*omega - 
            a*(I*m + a*(-3 + m^2))*omega^2 + a^3*m*omega^3) - 
            4*I*a*z^3*(-12*m*(3 + lambda) + I*a*(408 + 194*lambda + 27*lambda^2 + lambda^3 - 16*m^2*(4 + lambda) + 
            240*I*omega) + 12*a^4*m*(1 + lambda)*omega^2 + 2*a^3*omega*(17 + 26*lambda + 3*lambda^2 - 
            m^2*(31 + 7*lambda) - 132*I*omega - 12*I*lambda*omega) + 
            2*a^2*m*(-98 - 35*lambda - 3*lambda^2 + m^2*(10 + lambda) + 164*I*omega + 20*I*lambda*omega)) + 
            4*a^6*z^8*(36 - 24*m^2 + 2*a^3*m*(-100 + 12*m^2 - 7*lambda + 6*I*omega)*omega + 
            6*a^4*(21 - 5*m^2 + lambda)*omega^2 + 12*a^5*m*omega^3 + 
            2*a*m*(-44*I + 9*I*m^2 - 11*I*lambda + 12*omega) - 
            a^2*(39 + 6*m^4 + 20*lambda + 2*lambda^2 + m^2*(-65 - 8*lambda + 30*I*omega) + 170*I*omega - 
            22*I*lambda*omega)) + 2*z*((9 + lambda)*(24 + 10*lambda + lambda^2 + 12*I*omega) - 
            8*I*a^3*m*(1 + lambda)*omega^2 + 4*a*m*(24*I + 10*I*lambda + I*lambda^2 + 27*omega + 3*lambda*omega) - 
            4*a^2*omega*(6*I + 7*I*lambda + I*lambda^2 - 2*I*m^2*(4 + lambda) + 27*omega + 3*lambda*omega)) + 
            a^3*z^6*(384*I*m + 16*a*(-33 + 12*m^2 - 10*lambda - lambda^2 - 36*I*omega) + 
            8*I*a^2*m*(-177 + 18*m^2 - 53*lambda - 2*lambda^2 + 96*I*omega) + 
            2*a^4*m*(-810 + 126*m^2 - 100*lambda - lambda^2 + 12*I*omega)*omega + 
            12*a^5*(83 - 31*m^2 + 7*lambda)*omega^2 + 168*a^6*m*omega^3 - 
            a^3*(756 + 48*m^4 + lambda^3 + lambda^2*(41 - 16*I*omega) - 
            m^2*(564 + 106*lambda + lambda^2 - 180*I*omega) + lambda*(334 - 364*I*omega) + 948*I*omega - 
            576*omega^2)) + a*z^4*(96*I*m + 8*I*a^2*m*(-202 + 9*m^2 - 65*lambda - 4*lambda^2 + 
            72*I*omega) - 8*a*(120 + 50*lambda + 5*lambda^2 + 72*I*omega) + 
            6*a^4*m*(-256 + 36*m^2 - 44*lambda - lambda^2 - 20*I*omega)*omega - 12*a^5*(-78 + 34*m^2 - 9*lambda)*
            omega^2 + 216*a^6*m*omega^3 + a^3*(-1068 - 24*m^4 - 3*lambda^3 + 
            2*m^2*(246 + 58*lambda + lambda^2) + lambda^2*(-74 + 32*I*omega) + lambda*(-512 + 388*I*omega) - 
            568*I*omega + 576*omega^2)) - 8*I*a^4*z^7*(12*I - 6*a*m*(-5 + lambda) + 
            2*a^5*m*(1 + lambda)*omega^2 + a^4*omega*(-23 + 20*lambda + lambda^2 - 3*m^2*(7 + lambda) - 138*I*omega - 
            6*I*lambda*omega) + a^3*m*(-88 - 23*lambda - lambda^2 + m^2*(16 + lambda) + 206*I*omega + 
            14*I*lambda*omega) + a^2*(-2*I*m^2*(31 + 4*lambda) + 3*I*(24 + 10*lambda + lambda^2 + 46*I*omega - 
            2*I*lambda*omega))) + z^2*(-12*(24 + 10*lambda + lambda^2 + 12*I*omega) - 
            8*I*a*m*(60 + 23*lambda + 2*lambda^2 - 18*I*omega) + 2*a^3*m*(-346 + 30*m^2 - 76*lambda - 
            3*lambda^2 - 60*I*omega)*omega - 60*a^4*(-7 + 3*m^2 - lambda)*omega^2 + 120*a^5*m*omega^3 + 
            a^2*(-3*lambda^3 + lambda^2*(-57 + 16*I*omega) + m^2*(152 + 42*lambda + lambda^2 + 60*I*omega) + 
            lambda*(-342 + 100*I*omega) + 12*(-54 - 23*I*omega + 12*omega^2)))))/
            ((1 + a^2*z^2)^2*(1 - 2*z + a^2*z^2)^2*(24 + 10*lambda + lambda^2 - 
            4*I*a*m*(6*z^2 + 2*z*(4 + lambda) + 3*I*omega) + 12*I*omega + 24*a^3*m*z^2*(I*z + 2*omega) + 
            12*a^4*z^2*(z^2 - 2*I*z*omega - 2*omega^2) - 4*a^2*(6*z^3 + z^2*(-3 + 6*m^2 - 6*I*omega) - 
            2*I*z*(1 + lambda)*omega + 3*omega^2)))
        end
    elseif s == -2
        return begin
            (z^2*(-((-1 + 2*z)*(-2 + 6*z - lambda)*(2*lambda + lambda^2 - 12*I*omega)) + 
            48*a^11*m*z^8*omega^2*(4*I*z + omega) + 24*a^12*z^9*(z^3 + 2*I*z^2*omega - 2*z*omega^2 - 
            4*I*omega^3) + 8*I*a^9*m*z^6*(9*z^4 + z^3*(-3 + 3*m^2 - 4*lambda + 18*I*omega) + 
            3*z^2*(-4*I*m^2 + 3*I*lambda - 18*omega)*omega + 2*z*(45 + lambda)*omega^2 - 21*I*omega^3) + 
            a^4*z*(96*z^6 + 16*z^5*(-9 + 12*m^2 - 2*lambda - lambda^2 + 36*I*omega) - 
            z^3*(12 + 24*m^4 + 3*lambda^3 + lambda^2*(38 + 32*I*omega) + 4*lambda*(16 + 33*I*omega) - 
            2*m^2*(30 + 50*lambda + lambda^2 + 288*I*omega) - 552*I*omega) + 
            2*z^4*(36 + 35*lambda^2 + lambda^3 - 4*m^2*(27 + 16*lambda) + lambda*(66 + 84*I*omega) - 636*I*omega) - 
            8*I*z^2*(3 - 3*lambda^2 + m^2*(51 + 7*lambda) + lambda*(-2 - 24*I*omega) + 36*I*omega)*omega + 
            4*z*(-39 - 45*m^2 + 31*lambda + 48*I*omega)*omega^2 - 96*I*omega^3) - 
            2*I*a^7*m*z^4*(72*z^5 + 4*z^3*(12 + lambda^2 - m^2*(12 + lambda) + 3*lambda*(5 + 6*I*omega) - 
            6*I*omega) + 4*z^4*(9*m^2 - 11*lambda + 36*I*omega) + 
            I*z^2*(6 + 126*m^2 - 124*lambda - lambda^2 - 588*I*omega)*omega - 24*z*(21 + lambda)*omega^2 + 
            108*I*omega^3) - a^6*z^3*(48*(-3 + 2*m^2)*z^5 + 192*z^6 + 
            8*z^4*(m^2*(30 + 8*lambda) - 3*(lambda^2 + lambda*(2 + 2*I*omega) - 18*I*omega)) + 
            z^3*(12 + 48*m^4 + lambda^3 + lambda^2*(29 + 16*I*omega) + lambda*(54 + 236*I*omega) - 
            m^2*(156 + 98*lambda + lambda^2 + 756*I*omega) - 420*I*omega) + 
            8*I*z^2*(3 - 3*lambda^2 + m^2*(81 + 8*lambda) + lambda*(-11 - 27*I*omega) + 57*I*omega)*omega + 
            12*z*(30 + 34*m^2 - 17*lambda - 48*I*omega)*omega^2 + 384*I*omega^3) - 
            4*a^10*z^7*(36*z^4 - 3*z^3*(5 + 3*m^2 - 20*I*omega) + 
            2*z*(27 + 15*m^2 - 5*lambda - 24*I*omega)*omega^2 + 96*I*omega^3 - 
            2*z^2*omega*(15*I - 15*I*m^2 + 4*I*lambda + 24*omega)) - 
            2*I*a^3*m*(192*z^6 + 24*z^5*(-7 + 4*lambda) + 4*z^4*(-6 + 9*m^2 - 33*lambda - 4*lambda^2) + 
            3*I*z^2*(-6 + 10*m^2 - 28*lambda - lambda^2 - 44*I*omega)*omega - 8*z*(9 + lambda)*omega^2 + 
            12*I*omega^3 - 4*z^3*(-6 - 11*lambda - 3*lambda^2 + m^2*(6 + lambda) - 32*I*lambda*omega)) - 
            2*I*a^5*m*z^2*(24*z^5*(-9 + lambda) + 4*z^4*(3 + 18*m^2 - 37*lambda - 2*lambda^2 - 24*I*omega) + 
            3*z^2*(36*I*m^2 - I*(52*lambda + lambda^2 + 172*I*omega))*omega - 24*z*(13 + lambda)*omega^2 + 
            60*I*omega^3 + 4*z^3*(15 + 20*lambda + 3*lambda^2 - m^2*(15 + 2*lambda) + 9*I*omega + 43*I*lambda*omega)) - 
            a^2*(8*z^4*(10*lambda + 5*lambda^2 - 72*I*omega) - 4*z^3*((26 - 16*m^2)*lambda + 15*lambda^2 + lambda^3 - 
            168*I*omega) + 4*(6 + 6*m^2 - 7*lambda)*omega^2 + 8*I*z*omega*(lambda - lambda^2 + 2*m^2*(6 + lambda) + 
            9*I*omega - 7*I*lambda*omega) + z^2*(3*lambda^3 + lambda^2*(21 - m^2 + 16*I*omega) + 
            lambda*(30 - 34*m^2 - 28*I*omega) - 12*I*(15 + 11*m^2 + 4*I*omega)*omega)) + 
            4*a^8*z^5*(72*z^5 - 6*z^4*(9 + m^2 - 12*I*omega) + z*(-99 - 93*m^2 + 37*lambda + 144*I*omega)*
            omega^2 - 144*I*omega^3 - 2*I*z^2*omega*(-9 - 12*lambda - lambda^2 + 3*m^2*(19 + lambda) + 54*I*omega - 
            10*I*lambda*omega) - z^3*(-9 + 6*m^4 + 4*lambda + 2*lambda^2 - m^2*(33 + 8*lambda + 78*I*omega) + 
            54*I*omega + 22*I*lambda*omega + 48*omega^2)) + 2*a*m*(-48*I*z^4 - 24*I*z^3*(-1 + lambda) - 
            (12 + 16*lambda + lambda^2 - 12*I*omega)*omega + 4*z^2*(7*I*lambda + 2*I*lambda^2 + 6*omega) + 
            4*z*((-I)*lambda^2 + 3*omega + lambda*(-2*I + 7*omega)))))/
            ((1 + a^2*z^2)^2*(1 - 2*z + a^2*z^2)^2*(2*lambda + lambda^2 - 12*I*omega + 
            24*a^3*m*z^2*((-I)*z + 2*omega) + 4*a*m*(6*I*z^2 + 2*I*z*lambda + 3*omega) + 
            12*a^4*z^2*(z^2 + 2*I*z*omega - 2*omega^2) - 4*a^2*(6*z^3 + z^2*(-3 + 6*m^2 + 6*I*omega) + 
            2*I*z*(-3 + lambda)*omega + 3*omega^2)))
        end
    else
        throw(DomainError(s, "Currently only spin weight s of 0, +/-1, +/-2 are supported"))
    end
end

function _outgoing_coefficient_at_inf_legacy_impl(s::Int, m::Int, a, omega, lambda, order::Int; data_type=_DEFAULTDATATYPE)
    #=
    We have derived/shown the explicit expression for
    different physically-relevant spin weight (s=0, \pm 1, \pm2)
    for up to (1/r)^3, which is probably more than enough
    
    But we have also shown a recurrence relation where
    one can generate as higher an order as one pleases.
    However, the recurrence relation that we have
    actually depends *all* previous terms so this function
    is designed to be evaluated recursively to build
    the full list of coefficients
    =#
    if order < 0
        throw(DomainError(order, "Only positive expansion order is supported"))
    end

    if order == 0
        return one(data_type) # This is always 1.0
    elseif order == 1
        if s == 0
            return (one(omega)/2)*I*(lambda + 2*a*m*omega)
        elseif s == +1
            return (one(omega)/2)*I*(2 + lambda + 2*a*m*omega)
        elseif s == -1
            return (I*(lambda^2 + 2*a*m*(2 + lambda)*omega))/(2*lambda)
        elseif s == +2
            return (one(omega)/2)*I*(6 + lambda + 2*a*m*omega)
        elseif s == -2
            return begin
                (one(omega)/6)*I*(-6 + 7*lambda) + I*a*m*omega +
                (2*I*(-3 + lambda)*lambda*(2 + lambda) + 
                24*(-3 - 3*I*a*m + lambda)*omega)/(-3*lambda*(2 + lambda) + 
                36*omega*(I - a*m + a^2*omega))
            end
        else
            throw(DomainError(s, "Currently only spin weight s of 0, +/-1, +/-2 are supported"))
        end
    elseif order == 2
        if s == 0
            return begin
                (one(omega)/8)*(-lambda^2 + lambda*(2 - 4*a*m*omega) +
                4*omega*(I + a*m + a*m*(2*I - a*m)*omega))
            end
        elseif s == +1
            return begin
                (one(omega)/8)*(-lambda^2 - 2*lambda*(1 + 2*a*m*omega) -
                4*a*omega*(m - 2*a*omega - 2*I*m*omega + a*m^2*omega))
            end
        elseif s == -1
            return begin
                -((1/(8*lambda))*((-2 + lambda)*lambda^2 + 4*a*m*(-2 + lambda + lambda^2)*omega + 
                4*a*(-2*I*m*lambda + a*(2 - 2*lambda + m^2*(4 + lambda)))*omega^2))
            end
        elseif s == +2
            return begin
                (one(omega)/8)*(-lambda^2 - 2*lambda*(5 + 2*a*m*omega) -
                4*(6 + (3*I + 5*a*m)*omega + a*m*(-2*I + a*m)*omega^2))
            end
        elseif s == -2
            return begin
                -((1/(8*lambda*(2 + lambda) - 96*omega*(I - a*m + a^2*omega)))*
                (lambda^2*(2 + lambda)^2 + 4*a*m*lambda*(16 + lambda*(14 + lambda))*
                omega + 4*(36 + a*(a*(10 - 11*lambda)*lambda - 
                2*I*m*(2 + lambda)*(6 + lambda) + 
                a*m^2*(60 + lambda*(30 + lambda))))*omega^2 + 
                16*a*(-6*m + a*(3*I - 9*I*m^2 + 
                a*m*(-15 + 3*m^2 - 7*lambda)))*omega^3 - 
                48*a^3*(-2*I*m + a*(-4 + m^2))*omega^4))
            end
        else
            throw(DomainError(s, "Currently only spin weight s of 0, +/-1, +/-2 are supported"))
        end
    elseif order == 3
        if s == 0
            return begin
                (one(omega)/2)*(1 - I*a*m)*omega - (one(omega)/48)*I*((-6 + lambda)*(-2 + lambda)*lambda +
                2*lambda*(-18*I + a*m*(-16 + 3*lambda))*omega + 
                4*a*(3*a*m^2*(-2 + lambda) + 2*a*(-1 + lambda) - 
                6*I*m*(1 + lambda))*omega^2 + 8*a*m*(-8 - 6*I*a*m + 
                a^2*(2 + m^2))*omega^3)
            end
        elseif s == +1
            return begin
                -(one(omega)/48)*I*(lambda^3 + lambda^2*(-2 + 6*a*m*omega) +
                4*lambda*(-2 - 2*(3*I + a*m)*omega + 
                a*(-4*a - 6*I*m + 3*a*m^2)*omega^2) + 
                8*omega*(-6*I + a^3*m*(-4 + m^2)*omega^2 + 
                3*a^2*omega*(-1 - 2*I*m^2*omega) - 
                a*m*(3 + 6*I*omega + 8*omega^2)))
            end
        elseif s == -1
            return begin
                -((1/(48*lambda))*(I*((-6 + lambda)*(-2 + lambda)*lambda^2 + 48*a*m*omega + 
                2*lambda*(-12*I*lambda + a*m*(-16 + lambda*(-10 + 3*lambda)))*omega + 
                4*a*(3*a*m^2*(-2 + lambda)*(4 + lambda) - 
                4*a*(3 + (-2 + lambda)*lambda) - 6*I*m*(4 + lambda^2))*omega^2 + 
                8*a*(-8*m*lambda - 6*I*a*(-2 + m^2*(2 + lambda)) + 
                a^2*m*(6 - 4*lambda + m^2*(6 + lambda)))*omega^3)))
            end
        elseif s == +2
            return begin
                -(one(omega)/48)*I*(lambda^3 + 2*lambda^2*(5 + 3*a*m*omega) +
                4*lambda*(6 + (3*I + 10*a*m)*omega + 
                a*(2*a - 6*I*m + 3*a*m^2)*omega^2) + 
                8*a*omega*(a*omega + 6*a*m^2*(1 - I*omega)*omega + 
                a^2*m^3*omega^2 + m*(2 - 9*I*omega + 2*(-4 + a^2)*
                omega^2)))
            end
        elseif s == -2
            return begin
                -((1/(48*(lambda*(2 + lambda) - 12*omega*(I - a*m + a^2*omega))))*
                (I*(-4 + lambda)*lambda^2*(2 + lambda)^2 + 
                2*I*a*m*lambda*(-96 + lambda*(-44 + lambda*(32 + 3*lambda)))*
                omega + 4*I*(36*(-4 + lambda) + 
                a*(-6*I*m*lambda*(2 + lambda)^2 + 
                a*lambda*(-60 + (40 - 13*lambda)*lambda) + 
                3*a*m^2*(-48 + lambda*(40 + lambda*(24 + lambda)))))*
                omega^2 + 8*I*a*(-6*I*a*(-3*(2 + lambda) + 
                m^2*(1 + lambda)*(18 + lambda)) - 
                4*m*(-9 + lambda*(13 + 2*lambda)) + 
                a^2*m*(108 - lambda*(44 + 31*lambda) + 
                m^2*(144 + lambda*(44 + lambda))))*omega^3 - 
                48*a*(16*m + 28*I*a*m^2 - 2*a^2*m*
                (5 + 7*m^2 - 7*lambda) - 
                I*a^3*(2*m^4 + 2*(-9 + 5*lambda) - 
                m^2*(32 + 7*lambda)))*omega^4 - 
                96*I*a^3*m*(-8 - 6*I*a*m + a^2*(-10 + m^2))*
                omega^5))
            end
        else
            throw(DomainError(s, "Currently only spin weight s of 0, +/-1, +/-2 are supported"))
        end
    else
        throw(ArgumentError("explicit infinity bridge supports orders 0 through 3"))
    end
end

function outgoing_coefficient_at_inf(
    s::Int, m::Int, a, omega, lambda, order::Int;
    data_type=_DEFAULTDATATYPE,
)
    key = _legacy_series_key(
        s, m, a, omega, lambda, INFINITY_OUTGOING_SERIES, order, data_type
    )
    T = _component_type(data_type)
    return _with_request_precision(T, key.precision_bits) do
        _chart_denominator(key)
        if order <= 3
            value = _outgoing_coefficient_at_inf_legacy_impl(
                key.s, key.m, key.a, key.omega, key.lambda, order;
                data_type=Complex{T},
            )
            _assert_value(key, Complex{T}(value), "legacy outgoing infinity coefficient")
        else
            build_asymptotic_series(key).coefficients[order + 1]
        end
    end
end

function PplusH(s::Int, m::Int, a, omega, lambda, x)
    if s == 0
        return begin
            ((a^2 + (1 + sqrt(1 - a^2) + x)^2)*
            (-((2*x*(1 + sqrt(1 - a^2) + x)*(2*sqrt(1 - a^2) + x))/
            (2*(1 + sqrt(1 - a^2)) + 2*(1 + sqrt(1 - a^2))*x + x^2)^2) + 
            (2*(sqrt(1 - a^2) + x))/(a^2 + (1 + sqrt(1 - a^2) + x)^2) + 
            2*I*(-((a*m)/(2*(1 + sqrt(1 - a^2)))) + omega)))/(2*sqrt(1 - a^2) + x)
        end
    elseif s == 1
        return begin
            (1/(2*sqrt(1 - a^2) + x))*((a^2 + (1 + sqrt(1 - a^2) + x)^2)*
            (-((2*x*(1 + sqrt(1 - a^2) + x)*(2*sqrt(1 - a^2) + x))/
            (2*(1 + sqrt(1 - a^2)) + 2*(1 + sqrt(1 - a^2))*x + x^2)^2) + 
            (2*(sqrt(1 - a^2) + x))/(a^2 + (1 + sqrt(1 - a^2) + x)^2) + 
            (2*a*x*(2*sqrt(1 - a^2) + x)*(-3*I*a^2*m*(1 + sqrt(1 - a^2) + x) - 
            I*m*(1 + sqrt(1 - a^2) + x)^3 + 2*a^3*(1 + lambda) + a*(1 + sqrt(1 - a^2) + x)*
            (3 + (1 + sqrt(1 - a^2) + x)*(3 + 2*lambda))))/((1 + sqrt(1 - a^2) + x)*
            (a^2 + (1 + sqrt(1 - a^2) + x)^2)*(-2*I*a^3*m*(1 + sqrt(1 - a^2) + x) - 
            2*I*a*m*(1 + sqrt(1 - a^2) + x)^3 + a^4*(1 + lambda) + (1 + sqrt(1 - a^2) + x)^4*
            (2 + lambda) + a^2*(1 + sqrt(1 - a^2) + x)*(2 + (1 + sqrt(1 - a^2) + x)*
            (3 + 2*lambda)))) + 2*I*(-((a*m)/(2*(1 + sqrt(1 - a^2)))) + omega)))
        end
    elseif s == -1
        return begin
            (1/(2*sqrt(1 - a^2) + x))*((a^2 + (1 + sqrt(1 - a^2) + x)^2)*
            (-((2*x*(1 + sqrt(1 - a^2) + x)*(2*sqrt(1 - a^2) + x))/
            (2*(1 + sqrt(1 - a^2)) + 2*(1 + sqrt(1 - a^2))*x + x^2)^2) + 
            (2*(sqrt(1 - a^2) + x))/(a^2 + (1 + sqrt(1 - a^2) + x)^2) + 
            (2*a*x*(2*sqrt(1 - a^2) + x)*(3*I*a^2*m*(1 + sqrt(1 - a^2) + x) + 
            I*m*(1 + sqrt(1 - a^2) + x)^3 + 2*a^3*(-1 + lambda) + a*(1 + sqrt(1 - a^2) + x)*
            (3 + (1 + sqrt(1 - a^2) + x)*(-1 + 2*lambda))))/((1 + sqrt(1 - a^2) + x)*
            (a^2 + (1 + sqrt(1 - a^2) + x)^2)*(2*I*a^3*m*(1 + sqrt(1 - a^2) + x) + 
            2*I*a*m*(1 + sqrt(1 - a^2) + x)^3 + a^4*(-1 + lambda) + (1 + sqrt(1 - a^2) + x)^4*
            lambda + a^2*(1 + sqrt(1 - a^2) + x)*(2 + (1 + sqrt(1 - a^2) + x)*(-1 + 2*lambda)))) + 
            2*I*(-((a*m)/(2*(1 + sqrt(1 - a^2)))) + omega)))
        end
    elseif s == 2
        return begin
            (1/(2*sqrt(1 - a^2) + x))*((a^2 + (1 + sqrt(1 - a^2) + x)^2)*
            (-((2*x*(1 + sqrt(1 - a^2) + x)*(2*sqrt(1 - a^2) + x))/
            (2*(1 + sqrt(1 - a^2)) + 2*(1 + sqrt(1 - a^2))*x + x^2)^2) + 
            (2*(sqrt(1 - a^2) + x))/(a^2 + (1 + sqrt(1 - a^2) + x)^2) + 
            2*I*(-((a*m)/(2*(1 + sqrt(1 - a^2)))) + omega) + 
            (8*a*x*(2*sqrt(1 - a^2) + x)*(I*m*(1 + sqrt(1 - a^2) + x)^2*
            (6 + (1 + sqrt(1 - a^2) + x)*(4 + lambda)) - 3*a^2*m*(1 + sqrt(1 - a^2) + x)*
            (3*I + 4*(1 + sqrt(1 - a^2) + x)*omega) + a*(1 + sqrt(1 - a^2) + x)*
            (9 + (1 + sqrt(1 - a^2) + x)*(-3 + 6*m^2 - 6*I*omega) - I*(1 + sqrt(1 - a^2) + x)^2*
            (1 + lambda)*omega) + a^3*(-6 + 9*I*(1 + sqrt(1 - a^2) + x)*omega + 
            6*(1 + sqrt(1 - a^2) + x)^2*omega^2)))/((1 + sqrt(1 - a^2) + x)*
            (a^2 + (1 + sqrt(1 - a^2) + x)^2)*((-(1 + sqrt(1 - a^2) + x)^4)*
            (24 + 10*lambda + lambda^2 + 12*I*omega) - 24*a^3*m*(1 + sqrt(1 - a^2) + x)*
            (I + 2*(1 + sqrt(1 - a^2) + x)*omega) + 4*a*m*(1 + sqrt(1 - a^2) + x)^2*
            (6*I + 2*I*(1 + sqrt(1 - a^2) + x)*(4 + lambda) - 3*(1 + sqrt(1 - a^2) + x)^2*omega) + 
            12*a^4*(-1 + 2*I*(1 + sqrt(1 - a^2) + x)*omega + 2*(1 + sqrt(1 - a^2) + x)^2*omega^2) + 
            4*a^2*(1 + sqrt(1 - a^2) + x)*(6 + (1 + sqrt(1 - a^2) + x)*
            (-3 + 6*m^2 - 6*I*omega) - 2*I*(1 + sqrt(1 - a^2) + x)^2*(1 + lambda)*omega + 
            3*(1 + sqrt(1 - a^2) + x)^3*omega^2)))))
        end
    elseif s == -2
        return begin
            (1/(2*sqrt(1 - a^2) + x))*((a^2 + (1 + sqrt(1 - a^2) + x)^2)*
            (-((2*x*(1 + sqrt(1 - a^2) + x)*(2*sqrt(1 - a^2) + x))/
            (2*(1 + sqrt(1 - a^2)) + 2*(1 + sqrt(1 - a^2))*x + x^2)^2) + 
            (2*(sqrt(1 - a^2) + x))/(a^2 + (1 + sqrt(1 - a^2) + x)^2) + 
            2*I*(-((a*m)/(2*(1 + sqrt(1 - a^2)))) + omega) - 
            (8*a*x*(2*sqrt(1 - a^2) + x)*((-I)*m*(1 + sqrt(1 - a^2) + x)^2*
            (6 + (1 + sqrt(1 - a^2) + x)*lambda) + 3*a^2*m*(1 + sqrt(1 - a^2) + x)*
            (3*I - 4*(1 + sqrt(1 - a^2) + x)*omega) + a*(1 + sqrt(1 - a^2) + x)*
            (9 + (1 + sqrt(1 - a^2) + x)*(-3 + 6*m^2 + 6*I*omega) + I*(1 + sqrt(1 - a^2) + x)^2*
            (-3 + lambda)*omega) + a^3*(-6 - 9*I*(1 + sqrt(1 - a^2) + x)*omega + 
            6*(1 + sqrt(1 - a^2) + x)^2*omega^2)))/((1 + sqrt(1 - a^2) + x)*
            (a^2 + (1 + sqrt(1 - a^2) + x)^2)*((1 + sqrt(1 - a^2) + x)^4*
            (2*lambda + lambda^2 - 12*I*omega) + 24*a^3*m*(1 + sqrt(1 - a^2) + x)*
            (-I + 2*(1 + sqrt(1 - a^2) + x)*omega) + 4*a*m*(1 + sqrt(1 - a^2) + x)^2*
            (6*I + 2*I*(1 + sqrt(1 - a^2) + x)*lambda + 3*(1 + sqrt(1 - a^2) + x)^2*omega) + 
            a^4*(12 + 24*I*(1 + sqrt(1 - a^2) + x)*omega - 24*(1 + sqrt(1 - a^2) + x)^2*omega^2) - 
            4*a^2*(1 + sqrt(1 - a^2) + x)*(6 + (1 + sqrt(1 - a^2) + x)*
            (-3 + 6*m^2 + 6*I*omega) + 2*I*(1 + sqrt(1 - a^2) + x)^2*(-3 + lambda)*omega + 
            3*(1 + sqrt(1 - a^2) + x)^3*omega^2)))))
        end
    else
        throw(DomainError(s, "Currently only spin weight s of 0, +/-1, +/-2 are supported"))
    end
end

function QplusH(s::Int, m::Int, a, omega, lambda, x)
    if s == 0
        return begin
            (1/(2*sqrt(1 - a^2) + x)^2)*((a^2 + (1 + sqrt(1 - a^2) + x)^2)^2*
            (-(-((a*m)/(2*(1 + sqrt(1 - a^2)))) + omega)^2 - (1/(a^2 + (1 + sqrt(1 - a^2) + x)^2)^4)*
            (x^2*(1 + sqrt(1 - a^2) + x)^2*(2*sqrt(1 - a^2) + x)^2 + 
            x*(2*sqrt(1 - a^2) + x)*(a^4 - 4*a^2*(1 + sqrt(1 - a^2) + x) - 
            (-3 + sqrt(1 - a^2) + x)*(1 + sqrt(1 - a^2) + x)^3) + 
            (a^2 + (1 + sqrt(1 - a^2) + x)^2)^2*(x*(2*sqrt(1 - a^2) + x)*lambda - 
            (a*m - (a^2 + (1 + sqrt(1 - a^2) + x)^2)*omega)^2))))
        end
    elseif s == 1
        return begin
            (1/(2*sqrt(1 - a^2) + x)^2)*((a^2 + (1 + sqrt(1 - a^2) + x)^2)^2*
            ((2*I*a*x*(2*sqrt(1 - a^2) + x)*(-3*I*a^2*m*(1 + sqrt(1 - a^2) + x) - 
            I*m*(1 + sqrt(1 - a^2) + x)^3 + 2*a^3*(1 + lambda) + a*(1 + sqrt(1 - a^2) + x)*
            (3 + (1 + sqrt(1 - a^2) + x)*(3 + 2*lambda)))*(-((a*m)/(2*(1 + sqrt(1 - a^2)))) + 
            omega))/((1 + sqrt(1 - a^2) + x)*(a^2 + (1 + sqrt(1 - a^2) + x)^2)*
            (-2*I*a^3*m*(1 + sqrt(1 - a^2) + x) - 2*I*a*m*(1 + sqrt(1 - a^2) + x)^3 + 
            a^4*(1 + lambda) + (1 + sqrt(1 - a^2) + x)^4*(2 + lambda) + a^2*(1 + sqrt(1 - a^2) + x)*
            (2 + (1 + sqrt(1 - a^2) + x)*(3 + 2*lambda)))) - 
            (-((a*m)/(2*(1 + sqrt(1 - a^2)))) + omega)^2 - (1/(a^2 + (1 + sqrt(1 - a^2) + x)^2)^4)*
            (2*x*(2*sqrt(1 - a^2) + x)*(a^4 - a^2*(1 + sqrt(1 - a^2) + x) - 
            (-2 + sqrt(1 - a^2) + x)*(1 + sqrt(1 - a^2) + x)^3) + 
            ((1 + sqrt(1 - a^2) + x)^2*(-1 + 2*sqrt(1 - a^2) + 2*x) + 
            a^2*(1 + 2*sqrt(1 - a^2) + 2*x))^2 + (2*a*x*(2*sqrt(1 - a^2) + x)*
            (a^2 + (1 + sqrt(1 - a^2) + x)^2)*((1 + sqrt(1 - a^2) + x)^2*
            (-1 + 2*sqrt(1 - a^2) + 2*x) + a^2*(1 + 2*sqrt(1 - a^2) + 2*x))*
            (-3*I*a^2*m*(1 + sqrt(1 - a^2) + x) - I*m*(1 + sqrt(1 - a^2) + x)^3 + 
            2*a^3*(1 + lambda) + a*(1 + sqrt(1 - a^2) + x)*(3 + (1 + sqrt(1 - a^2) + x)*
            (3 + 2*lambda))))/((1 + sqrt(1 - a^2) + x)*(-2*I*a^3*m*(1 + sqrt(1 - a^2) + x) - 
            2*I*a*m*(1 + sqrt(1 - a^2) + x)^3 + a^4*(1 + lambda) + (1 + sqrt(1 - a^2) + x)^4*
            (2 + lambda) + a^2*(1 + sqrt(1 - a^2) + x)*(2 + (1 + sqrt(1 - a^2) + x)*
            (3 + 2*lambda)))) - ((a^2 + (1 + sqrt(1 - a^2) + x)^2)^2*
            (2*a^7*m*(1 + sqrt(1 - a^2) + x)^2*omega*(-lambda - I*(1 + sqrt(1 - a^2) + x)*omega) + 
            a^8*(1 + lambda)*(2 + (1 + sqrt(1 - a^2) + x)^2*omega^2) - 
            2*I*a^5*m*(1 + sqrt(1 - a^2) + x)^2*(-6 + (1 + sqrt(1 - a^2) + x)*
            (4 + m^2 - lambda - 4*I*omega) - 3*I*(1 + sqrt(1 - a^2) + x)^2*(1 + lambda)*omega + 
            3*(1 + sqrt(1 - a^2) + x)^3*omega^2) - 2*I*a*m*(1 + sqrt(1 - a^2) + x)^5*
            (3 + (1 + sqrt(1 - a^2) + x)*(-5 + 2*lambda) + (1 + sqrt(1 - a^2) + x)^2*
            (2 - lambda + 2*I*omega) - I*(1 + sqrt(1 - a^2) + x)^3*(3 + lambda)*omega + 
            (1 + sqrt(1 - a^2) + x)^4*omega^2) - 2*I*a^3*m*(1 + sqrt(1 - a^2) + x)^3*
            (13 + (1 + sqrt(1 - a^2) + x)*(-17 + 2*lambda) + (1 + sqrt(1 - a^2) + x)^2*
            (6 + m^2 - 2*lambda - 2*I*omega) - 3*I*(1 + sqrt(1 - a^2) + x)^3*(2 + lambda)*omega + 
            3*(1 + sqrt(1 - a^2) + x)^4*omega^2) + (1 + sqrt(1 - a^2) + x)^6*
            (-3*(2 + lambda) - (1 + sqrt(1 - a^2) + x)^2*lambda*(2 + lambda) + 
            2*(1 + sqrt(1 - a^2) + x)*(2 + 3*lambda + lambda^2) + (1 + sqrt(1 - a^2) + x)^4*
            (2 + lambda)*omega^2) + a^6*(1 + sqrt(1 - a^2) + x)*(-16*(1 + lambda) + 
            (1 + sqrt(1 - a^2) + x)*(5 + m^2*(-1 + lambda) + 6*lambda - lambda^2 + 2*I*omega) + 
            (1 + sqrt(1 - a^2) + x)^3*(5 + 4*lambda)*omega^2 + 2*(1 + sqrt(1 - a^2) + x)^2*omega*
            (I + 2*I*m^2 + omega)) + a^4*(1 + sqrt(1 - a^2) + x)^2*
            (11 + 25*lambda + 2*(1 + sqrt(1 - a^2) + x)*(-5 + 3*m^2 - 13*lambda + lambda^2 - 2*I*omega) + 
            (1 + sqrt(1 - a^2) + x)^2*(5 + 4*lambda - 3*lambda^2 + m^2*(3 + 2*lambda) - 8*I*omega) + 
            3*(1 + sqrt(1 - a^2) + x)^4*(3 + 2*lambda)*omega^2 + 4*(1 + sqrt(1 - a^2) + x)^3*omega*
            (I + 2*I*m^2 + omega)) + a^2*(1 + sqrt(1 - a^2) + x)^3*
            (30 + 5*(1 + sqrt(1 - a^2) + x)*(-7 + 2*lambda) - 4*(1 + sqrt(1 - a^2) + x)^2*
            (-2 + m^2 + lambda - lambda^2 - 3*I*omega) + (1 + sqrt(1 - a^2) + x)^3*
            (2 - 2*lambda - 3*lambda^2 + m^2*(4 + lambda) - 10*I*omega) + (1 + sqrt(1 - a^2) + x)^5*
            (7 + 4*lambda)*omega^2 + 2*(1 + sqrt(1 - a^2) + x)^4*omega*(I + 2*I*m^2 + omega))))/
            ((1 + sqrt(1 - a^2) + x)^2*(-2*I*a^3*m*(1 + sqrt(1 - a^2) + x) - 
            2*I*a*m*(1 + sqrt(1 - a^2) + x)^3 + a^4*(1 + lambda) + (1 + sqrt(1 - a^2) + x)^4*
            (2 + lambda) + a^2*(1 + sqrt(1 - a^2) + x)*(2 + (1 + sqrt(1 - a^2) + x)*
            (3 + 2*lambda)))))))
        end
    elseif s == -1
        return begin
            (1/(2*sqrt(1 - a^2) + x)^2)*((a^2 + (1 + sqrt(1 - a^2) + x)^2)^2*
            ((2*I*a*x*(2*sqrt(1 - a^2) + x)*(3*I*a^2*m*(1 + sqrt(1 - a^2) + x) + 
            I*m*(1 + sqrt(1 - a^2) + x)^3 + 2*a^3*(-1 + lambda) + a*(1 + sqrt(1 - a^2) + x)*
            (3 + (1 + sqrt(1 - a^2) + x)*(-1 + 2*lambda)))*(-((a*m)/(2*(1 + sqrt(1 - a^2)))) + 
            omega))/((1 + sqrt(1 - a^2) + x)*(a^2 + (1 + sqrt(1 - a^2) + x)^2)*
            (2*I*a^3*m*(1 + sqrt(1 - a^2) + x) + 2*I*a*m*(1 + sqrt(1 - a^2) + x)^3 + 
            a^4*(-1 + lambda) + (1 + sqrt(1 - a^2) + x)^4*lambda + a^2*(1 + sqrt(1 - a^2) + x)*
            (2 + (1 + sqrt(1 - a^2) + x)*(-1 + 2*lambda)))) - 
            (-((a*m)/(2*(1 + sqrt(1 - a^2)))) + omega)^2 - (1/(a^2 + (1 + sqrt(1 - a^2) + x)^2)^4)*
            ((a^2 - (1 + sqrt(1 - a^2) + x)^2)^2 + 2*x*(1 + sqrt(1 - a^2) + x)*
            (2*sqrt(1 - a^2) + x)*(-3*a^2 + (1 + sqrt(1 - a^2) + x)^2) + 
            (2*a*x*(2*sqrt(1 - a^2) + x)*(a^2 - (1 + sqrt(1 - a^2) + x)^2)*
            (a^2 + (1 + sqrt(1 - a^2) + x)^2)*(3*I*a^2*m*(1 + sqrt(1 - a^2) + x) + 
            I*m*(1 + sqrt(1 - a^2) + x)^3 + 2*a^3*(-1 + lambda) + a*(1 + sqrt(1 - a^2) + x)*
            (3 + (1 + sqrt(1 - a^2) + x)*(-1 + 2*lambda))))/((1 + sqrt(1 - a^2) + x)*
            (2*I*a^3*m*(1 + sqrt(1 - a^2) + x) + 2*I*a*m*(1 + sqrt(1 - a^2) + x)^3 + 
            a^4*(-1 + lambda) + (1 + sqrt(1 - a^2) + x)^4*lambda + a^2*(1 + sqrt(1 - a^2) + x)*
            (2 + (1 + sqrt(1 - a^2) + x)*(-1 + 2*lambda)))) - 
            ((a^2 + (1 + sqrt(1 - a^2) + x)^2)^2*(2*a^7*m*(1 + sqrt(1 - a^2) + x)^2*omega*
            (2 - lambda + I*(1 + sqrt(1 - a^2) + x)*omega) + a^8*(-1 + lambda)*
            (2 + (1 + sqrt(1 - a^2) + x)^2*omega^2) + 2*I*a^5*m*(1 + sqrt(1 - a^2) + x)^3*
            (-2 + m^2 - lambda + 4*I*omega - 3*I*(1 + sqrt(1 - a^2) + x)*omega + 
            3*I*(1 + sqrt(1 - a^2) + x)*lambda*omega + 3*(1 + sqrt(1 - a^2) + x)^2*omega^2) + 
            (1 + sqrt(1 - a^2) + x)^6*lambda*(-3 - (1 + sqrt(1 - a^2) + x)^2*lambda + 
            2*(1 + sqrt(1 - a^2) + x)*(1 + lambda) + (1 + sqrt(1 - a^2) + x)^4*omega^2) + 
            2*I*a*m*(1 + sqrt(1 - a^2) + x)^5*(sqrt(1 - a^2) + x + 
            2*(1 + sqrt(1 - a^2) + x)*lambda - (1 + sqrt(1 - a^2) + x)^2*(lambda + 2*I*omega) + 
            I*(1 + sqrt(1 - a^2) + x)^3*(1 + lambda)*omega + (1 + sqrt(1 - a^2) + x)^4*omega^2) + 
            2*I*a^3*m*(1 + sqrt(1 - a^2) + x)^3*(1 + (1 + sqrt(1 - a^2) + x)*(3 + 2*lambda) + 
            (1 + sqrt(1 - a^2) + x)^2*(-2 + m^2 - 2*lambda + 2*I*omega) + 
            3*I*(1 + sqrt(1 - a^2) + x)^3*lambda*omega + 3*(1 + sqrt(1 - a^2) + x)^4*omega^2) + 
            a^6*(1 + sqrt(1 - a^2) + x)*(8 - 8*lambda + (1 + sqrt(1 - a^2) + x)*
            (-1 + m^2*(-3 + lambda) - lambda^2 - 2*I*omega) + (1 + sqrt(1 - a^2) + x)^3*(-3 + 4*lambda)*
            omega^2 + 2*(1 + sqrt(1 - a^2) + x)^2*omega*(-I - 2*I*m^2 + omega)) + 
            a^4*(1 + sqrt(1 - a^2) + x)^2*(-11 + 9*lambda + 2*(1 + sqrt(1 - a^2) + x)*
            (1 + 3*m^2 + lambda + lambda^2 + 2*I*omega) + (1 + sqrt(1 - a^2) + x)^2*
            (1 - 6*lambda - 3*lambda^2 + m^2*(-1 + 2*lambda) + 8*I*omega) + 3*(1 + sqrt(1 - a^2) + x)^4*
            (-1 + 2*lambda)*omega^2 + 4*(1 + sqrt(1 - a^2) + x)^3*omega*(-I - 2*I*m^2 + omega)) + 
            a^2*(1 + sqrt(1 - a^2) + x)^3*(6 - 3*(1 + sqrt(1 - a^2) + x)*(1 + 2*lambda) - 
            4*(1 + sqrt(1 - a^2) + x)^2*(m^2 - 3*lambda - lambda^2 + 3*I*omega) + 
            (1 + sqrt(1 - a^2) + x)^3*(-4*lambda - 3*lambda^2 + m^2*(2 + lambda) + 10*I*omega) + 
            (1 + sqrt(1 - a^2) + x)^5*(-1 + 4*lambda)*omega^2 + 2*(1 + sqrt(1 - a^2) + x)^4*omega*
            (-I - 2*I*m^2 + omega))))/((1 + sqrt(1 - a^2) + x)^2*
            (2*I*a^3*m*(1 + sqrt(1 - a^2) + x) + 2*I*a*m*(1 + sqrt(1 - a^2) + x)^3 + 
            a^4*(-1 + lambda) + (1 + sqrt(1 - a^2) + x)^4*lambda + a^2*(1 + sqrt(1 - a^2) + x)*
            (2 + (1 + sqrt(1 - a^2) + x)*(-1 + 2*lambda)))))))
        end
    elseif s == 2
        return begin
            (1/(2*sqrt(1 - a^2) + x)^2)*((a^2 + (1 + sqrt(1 - a^2) + x)^2)^2*
            (-(-((a*m)/(2*(1 + sqrt(1 - a^2)))) + omega)^2 - 
            (8*I*a*x*(2*sqrt(1 - a^2) + x)*(-((a*m)/(2*(1 + sqrt(1 - a^2)))) + omega)*
            (I*m*(1 + sqrt(1 - a^2) + x)^2*(6 + (1 + sqrt(1 - a^2) + x)*(4 + lambda)) - 
            3*a^2*m*(1 + sqrt(1 - a^2) + x)*(3*I + 4*(1 + sqrt(1 - a^2) + x)*omega) + 
            a*(1 + sqrt(1 - a^2) + x)*(9 + (1 + sqrt(1 - a^2) + x)*(-3 + 6*m^2 - 6*I*omega) - 
            I*(1 + sqrt(1 - a^2) + x)^2*(1 + lambda)*omega) + 
            a^3*(-6 + 9*I*(1 + sqrt(1 - a^2) + x)*omega + 6*(1 + sqrt(1 - a^2) + x)^2*omega^2)))/
            ((1 + sqrt(1 - a^2) + x)*(a^2 + (1 + sqrt(1 - a^2) + x)^2)*
            ((1 + sqrt(1 - a^2) + x)^4*(24 + 10*lambda + lambda^2 + 12*I*omega) + 
            24*a^3*m*(1 + sqrt(1 - a^2) + x)*(I + 2*(1 + sqrt(1 - a^2) + x)*omega) + 
            4*a*m*(1 + sqrt(1 - a^2) + x)^2*(-6*I - 2*I*(1 + sqrt(1 - a^2) + x)*(4 + lambda) + 
            3*(1 + sqrt(1 - a^2) + x)^2*omega) - 12*a^4*(-1 + 2*I*(1 + sqrt(1 - a^2) + x)*omega + 
            2*(1 + sqrt(1 - a^2) + x)^2*omega^2) - 4*a^2*(1 + sqrt(1 - a^2) + x)*
            (6 + (1 + sqrt(1 - a^2) + x)*(-3 + 6*m^2 - 6*I*omega) - 
            2*I*(1 + sqrt(1 - a^2) + x)^2*(1 + lambda)*omega + 3*(1 + sqrt(1 - a^2) + x)^3*
            omega^2))) - (((1 + sqrt(1 - a^2) + x)^2*(-1 + 3*sqrt(1 - a^2) + 3*x) + 
            a^2*(1 + 3*sqrt(1 - a^2) + 3*x))^2 + x*(2*sqrt(1 - a^2) + x)*
            (3*a^4 + (1 + sqrt(1 - a^2) + x)^3*(8 - 3*(1 + sqrt(1 - a^2) + x))) + 
            (8*a*x*(2*sqrt(1 - a^2) + x)*(a^2 + (1 + sqrt(1 - a^2) + x)^2)*
            ((1 + sqrt(1 - a^2) + x)^2*(-1 + 3*sqrt(1 - a^2) + 3*x) + 
            a^2*(1 + 3*sqrt(1 - a^2) + 3*x))*(I*m*(1 + sqrt(1 - a^2) + x)^2*
            (6 + (1 + sqrt(1 - a^2) + x)*(4 + lambda)) - 3*a^2*m*(1 + sqrt(1 - a^2) + x)*
            (3*I + 4*(1 + sqrt(1 - a^2) + x)*omega) + a*(1 + sqrt(1 - a^2) + x)*
            (9 + (1 + sqrt(1 - a^2) + x)*(-3 + 6*m^2 - 6*I*omega) - 
            I*(1 + sqrt(1 - a^2) + x)^2*(1 + lambda)*omega) + 
            a^3*(-6 + 9*I*(1 + sqrt(1 - a^2) + x)*omega + 6*(1 + sqrt(1 - a^2) + x)^2*omega^2)))/
            ((1 + sqrt(1 - a^2) + x)*((-(1 + sqrt(1 - a^2) + x)^4)*(24 + 10*lambda + lambda^2 + 
            12*I*omega) - 24*a^3*m*(1 + sqrt(1 - a^2) + x)*(I + 2*(1 + sqrt(1 - a^2) + x)*
            omega) + 4*a*m*(1 + sqrt(1 - a^2) + x)^2*(6*I + 2*I*(1 + sqrt(1 - a^2) + x)*
            (4 + lambda) - 3*(1 + sqrt(1 - a^2) + x)^2*omega) + 
            12*a^4*(-1 + 2*I*(1 + sqrt(1 - a^2) + x)*omega + 2*(1 + sqrt(1 - a^2) + x)^2*
            omega^2) + 4*a^2*(1 + sqrt(1 - a^2) + x)*(6 + (1 + sqrt(1 - a^2) + x)*
            (-3 + 6*m^2 - 6*I*omega) - 2*I*(1 + sqrt(1 - a^2) + x)^2*(1 + lambda)*omega + 
            3*(1 + sqrt(1 - a^2) + x)^3*omega^2))) - ((a^2 + (1 + sqrt(1 - a^2) + x)^2)^2*
            (24*a^7*m*(1 + sqrt(1 - a^2) + x)^2*omega*(3 + 3*I*(1 + sqrt(1 - a^2) + x)*omega - 
            4*(1 + sqrt(1 - a^2) + x)^2*omega^2) - (1 + sqrt(1 - a^2) + x)^6*
            (24 + 10*lambda + lambda^2 + 12*I*omega)*(-12 - (1 + sqrt(1 - a^2) + x)^2*lambda + 
            2*(1 + sqrt(1 - a^2) + x)*(4 + lambda) + (1 + sqrt(1 - a^2) + x)^4*omega^2) - 
            4*a^5*m*(1 + sqrt(1 - a^2) + x)^2*(-54*I - 2*I*(1 + sqrt(1 - a^2) + x)*
            (-55 + 3*m^2 - 4*lambda - 18*I*omega) + 2*(1 + sqrt(1 - a^2) + x)^2*
            (4 + 12*m^2 - 8*lambda + 27*I*omega)*omega - 6*I*(1 + sqrt(1 - a^2) + x)^3*(8 + lambda)*
            omega^2 + 45*(1 + sqrt(1 - a^2) + x)^4*omega^3) + 
            12*a^8*(-2 - 3*(1 + sqrt(1 - a^2) + x)^2*omega^2 - 2*I*(1 + sqrt(1 - a^2) + x)^3*
            omega^3 + 2*(1 + sqrt(1 - a^2) + x)^4*omega^4) + 4*a^6*(1 + sqrt(1 - a^2) + x)*
            (60 - 3*(1 + sqrt(1 - a^2) + x)*(16 + 3*m^2 + 18*I*omega) + 
            (1 + sqrt(1 - a^2) + x)^3*(1 + 36*m^2 - 8*lambda + 18*I*omega)*omega^2 - 
            2*I*(1 + sqrt(1 - a^2) + x)^4*(7 + lambda)*omega^3 + 15*(1 + sqrt(1 - a^2) + x)^5*
            omega^4 - 2*(1 + sqrt(1 - a^2) + x)^2*omega*(-40*I + 9*I*m^2 - 4*I*lambda + 9*omega)) + 
            2*a*m*(1 + sqrt(1 - a^2) + x)^4*(144*I + 8*I*(1 + sqrt(1 - a^2) + x)*
            (-38 + lambda) + (1 + sqrt(1 - a^2) + x)^4*(40 + 20*lambda + lambda^2 + 24*I*omega)*omega + 
            4*I*(1 + sqrt(1 - a^2) + x)^5*(4 + lambda)*omega^2 - 6*(1 + sqrt(1 - a^2) + x)^6*
            omega^3 + 4*(1 + sqrt(1 - a^2) + x)^2*(16*I + 3*I*lambda + 2*I*lambda^2 + 6*omega) - 
            4*I*(1 + sqrt(1 - a^2) + x)^3*(-12 + lambda + lambda^2 - 14*I*omega - 5*I*lambda*omega)) - 
            2*a^3*m*(1 + sqrt(1 - a^2) + x)^3*(312*I + (1 + sqrt(1 - a^2) + x)^3*
            (84 + 30*m^2 - 52*lambda - lambda^2 + 36*I*omega)*omega - 4*I*(1 + sqrt(1 - a^2) + x)^4*
            (19 + 4*lambda)*omega^2 + 48*(1 + sqrt(1 - a^2) + x)^5*omega^3 + 
            12*(1 + sqrt(1 - a^2) + x)*(-63*I + 3*I*m^2 - 3*I*lambda + 32*omega) + 
            4*(1 + sqrt(1 - a^2) + x)^2*(71*I + I*lambda^2 - I*m^2*(10 + lambda) - 104*omega + 
            lambda*(9*I + 16*omega))) + a^2*(1 + sqrt(1 - a^2) + x)^3*
            (576 + 96*(1 + sqrt(1 - a^2) + x)*(-12 + 4*m^2 - 3*I*omega) + 
            8*(1 + sqrt(1 - a^2) + x)^2*(18 - 3*lambda^2 + m^2*(-58 + 8*lambda) + 
            lambda*(-30 - 2*I*omega) + 46*I*omega) - 8*I*(1 + sqrt(1 - a^2) + x)^4*
            (-lambda^2 + 2*m^2*(7 + lambda) + lambda*(2 + 5*I*omega) + 11*I*omega)*omega + 
            2*(1 + sqrt(1 - a^2) + x)^5*(-34 + 24*m^2 - 20*lambda - lambda^2 - 24*I*omega)*omega^2 - 
            8*I*(1 + sqrt(1 - a^2) + x)^6*(1 + lambda)*omega^3 + 12*(1 + sqrt(1 - a^2) + x)^7*
            omega^4 + (1 + sqrt(1 - a^2) + x)^3*(lambda^3 + 36*lambda*(4 + I*omega) + 
            2*lambda^2*(11 - 8*I*omega) - m^2*(-136 + 42*lambda + lambda^2 - 36*I*omega) - 
            8*(-18 + 19*I*omega + 6*omega^2))) + a^4*(1 + sqrt(1 - a^2) + x)^2*
            (-672 + (1 + sqrt(1 - a^2) + x)*(960 - 72*m^2 + 624*I*omega) + 
            (1 + sqrt(1 - a^2) + x)^4*(44 + 180*m^2 - 62*lambda - lambda^2 + 36*I*omega)*omega^2 - 
            8*I*(1 + sqrt(1 - a^2) + x)^5*(5 + 2*lambda)*omega^3 + 48*(1 + sqrt(1 - a^2) + x)^6*
            omega^4 + 8*(1 + sqrt(1 - a^2) + x)^3*omega*(56*I + I*lambda^2 - 3*I*m^2*(9 + lambda) - 
            46*omega + lambda*(6*I + 8*omega)) + 4*(1 + sqrt(1 - a^2) + x)^2*
            (6*m^4 + m^2*(7 - 8*lambda + 54*I*omega) + 2*(-15 + 10*lambda + lambda^2 - 144*I*omega - 9*I*
            lambda*omega + 48*omega^2)))))/((1 + sqrt(1 - a^2) + x)^2*
            ((-(1 + sqrt(1 - a^2) + x)^4)*(24 + 10*lambda + lambda^2 + 12*I*omega) - 
            24*a^3*m*(1 + sqrt(1 - a^2) + x)*(I + 2*(1 + sqrt(1 - a^2) + x)*omega) + 
            4*a*m*(1 + sqrt(1 - a^2) + x)^2*(6*I + 2*I*(1 + sqrt(1 - a^2) + x)*(4 + lambda) - 
            3*(1 + sqrt(1 - a^2) + x)^2*omega) + 12*a^4*(-1 + 2*I*(1 + sqrt(1 - a^2) + x)*
            omega + 2*(1 + sqrt(1 - a^2) + x)^2*omega^2) + 4*a^2*(1 + sqrt(1 - a^2) + x)*
            (6 + (1 + sqrt(1 - a^2) + x)*(-3 + 6*m^2 - 6*I*omega) - 
            2*I*(1 + sqrt(1 - a^2) + x)^2*(1 + lambda)*omega + 3*(1 + sqrt(1 - a^2) + x)^3*
            omega^2))))/(a^2 + (1 + sqrt(1 - a^2) + x)^2)^4))
        end
    elseif s == -2
        return begin
            (1/(2*sqrt(1 - a^2) + x)^2)*((a^2 + (1 + sqrt(1 - a^2) + x)^2)^2*
            (-(-((a*m)/(2*(1 + sqrt(1 - a^2)))) + omega)^2 - 
            (8*I*a*x*(2*sqrt(1 - a^2) + x)*(-((a*m)/(2*(1 + sqrt(1 - a^2)))) + omega)*
            ((-I)*m*(1 + sqrt(1 - a^2) + x)^2*(6 + (1 + sqrt(1 - a^2) + x)*lambda) + 
            3*a^2*m*(1 + sqrt(1 - a^2) + x)*(3*I - 4*(1 + sqrt(1 - a^2) + x)*omega) + 
            a*(1 + sqrt(1 - a^2) + x)*(9 + (1 + sqrt(1 - a^2) + x)*(-3 + 6*m^2 + 6*I*omega) + 
            I*(1 + sqrt(1 - a^2) + x)^2*(-3 + lambda)*omega) + 
            a^3*(-6 - 9*I*(1 + sqrt(1 - a^2) + x)*omega + 6*(1 + sqrt(1 - a^2) + x)^2*omega^2)))/
            ((1 + sqrt(1 - a^2) + x)*(a^2 + (1 + sqrt(1 - a^2) + x)^2)*
            ((1 + sqrt(1 - a^2) + x)^4*(2*lambda + lambda^2 - 12*I*omega) + 
            24*a^3*m*(1 + sqrt(1 - a^2) + x)*(-I + 2*(1 + sqrt(1 - a^2) + x)*omega) + 
            4*a*m*(1 + sqrt(1 - a^2) + x)^2*(6*I + 2*I*(1 + sqrt(1 - a^2) + x)*lambda + 
            3*(1 + sqrt(1 - a^2) + x)^2*omega) + a^4*(12 + 24*I*(1 + sqrt(1 - a^2) + x)*omega - 
            24*(1 + sqrt(1 - a^2) + x)^2*omega^2) - 4*a^2*(1 + sqrt(1 - a^2) + x)*
            (6 + (1 + sqrt(1 - a^2) + x)*(-3 + 6*m^2 + 6*I*omega) + 
            2*I*(1 + sqrt(1 - a^2) + x)^2*(-3 + lambda)*omega + 3*(1 + sqrt(1 - a^2) + x)^3*
            omega^2))) - (1/(a^2 + (1 + sqrt(1 - a^2) + x)^2)^4)*
            ((a^2*(-1 + sqrt(1 - a^2) + x) + (1 + sqrt(1 - a^2) + x)^3)^2 + 
            x*(2*sqrt(1 - a^2) + x)*(-a^4 - 8*a^2*(1 + sqrt(1 - a^2) + x) + 
            (1 + sqrt(1 - a^2) + x)^4) + (8*a*x*(2*sqrt(1 - a^2) + x)*
            (a^2 + (1 + sqrt(1 - a^2) + x)^2)*(a^2*(-1 + sqrt(1 - a^2) + x) + 
            (1 + sqrt(1 - a^2) + x)^3)*((-I)*m*(1 + sqrt(1 - a^2) + x)^2*
            (6 + (1 + sqrt(1 - a^2) + x)*lambda) + 3*a^2*m*(1 + sqrt(1 - a^2) + x)*
            (3*I - 4*(1 + sqrt(1 - a^2) + x)*omega) + a*(1 + sqrt(1 - a^2) + x)*
            (9 + (1 + sqrt(1 - a^2) + x)*(-3 + 6*m^2 + 6*I*omega) + 
            I*(1 + sqrt(1 - a^2) + x)^2*(-3 + lambda)*omega) + 
            a^3*(-6 - 9*I*(1 + sqrt(1 - a^2) + x)*omega + 6*(1 + sqrt(1 - a^2) + x)^2*omega^2)))/
            ((1 + sqrt(1 - a^2) + x)*((1 + sqrt(1 - a^2) + x)^4*(2*lambda + lambda^2 - 12*I*omega) + 
            24*a^3*m*(1 + sqrt(1 - a^2) + x)*(-I + 2*(1 + sqrt(1 - a^2) + x)*omega) + 
            4*a*m*(1 + sqrt(1 - a^2) + x)^2*(6*I + 2*I*(1 + sqrt(1 - a^2) + x)*lambda + 
            3*(1 + sqrt(1 - a^2) + x)^2*omega) + a^4*(12 + 24*I*(1 + sqrt(1 - a^2) + x)*omega - 
            24*(1 + sqrt(1 - a^2) + x)^2*omega^2) - 4*a^2*(1 + sqrt(1 - a^2) + x)*
            (6 + (1 + sqrt(1 - a^2) + x)*(-3 + 6*m^2 + 6*I*omega) + 
            2*I*(1 + sqrt(1 - a^2) + x)^2*(-3 + lambda)*omega + 3*(1 + sqrt(1 - a^2) + x)^3*
            omega^2))) - ((a^2 + (1 + sqrt(1 - a^2) + x)^2)^2*
            (-24*a^7*m*(1 + sqrt(1 - a^2) + x)^2*omega*(-3 + 3*I*(1 + sqrt(1 - a^2) + x)*omega + 
            4*(1 + sqrt(1 - a^2) + x)^2*omega^2) - 2*a^3*m*(1 + sqrt(1 - a^2) + x)^3*
            (72*I - 4*I*(1 + sqrt(1 - a^2) + x)*(15 + 9*m^2 - 13*lambda) + 
            4*(1 + sqrt(1 - a^2) + x)^2*(I*m^2*(6 + lambda) - I*(3 + lambda^2 + lambda*
            (9 + 16*I*omega) + 24*I*omega)) + (1 + sqrt(1 - a^2) + x)^3*
            (-36 + 30*m^2 - 44*lambda - lambda^2 - 36*I*omega)*omega + 4*I*(1 + sqrt(1 - a^2) + x)^4*
            (3 + 4*lambda)*omega^2 + 48*(1 + sqrt(1 - a^2) + x)^5*omega^3) + 
            12*a^8*(-2 - 3*(1 + sqrt(1 - a^2) + x)^2*omega^2 + 2*I*(1 + sqrt(1 - a^2) + x)^3*
            omega^3 + 2*(1 + sqrt(1 - a^2) + x)^4*omega^4) + 4*a^6*(1 + sqrt(1 - a^2) + x)*
            (12 - 3*(1 + sqrt(1 - a^2) + x)*(-4 + 3*m^2 + 6*I*omega) + 
            (1 + sqrt(1 - a^2) + x)^3*(-39 + 36*m^2 - 8*lambda - 18*I*omega)*omega^2 + 
            2*I*(1 + sqrt(1 - a^2) + x)^4*(3 + lambda)*omega^3 + 15*(1 + sqrt(1 - a^2) + x)^5*
            omega^4 + 2*(1 + sqrt(1 - a^2) + x)^2*omega*(24*I + 9*I*m^2 - 4*I*lambda + 15*omega)) - 
            4*a^5*m*(1 + sqrt(1 - a^2) + x)^2*(-18*I + 2*(1 + sqrt(1 - a^2) + x)^2*
            (-36 + 12*m^2 - 8*lambda - 27*I*omega)*omega + 6*I*(1 + sqrt(1 - a^2) + x)^3*(4 + lambda)*
            omega^2 + 45*(1 + sqrt(1 - a^2) + x)^4*omega^3 + 2*(1 + sqrt(1 - a^2) + x)*
            (9*I + 3*I*m^2 - 4*I*lambda + 30*omega)) - 2*a*m*(1 + sqrt(1 - a^2) + x)^4*
            (-48*I - 24*I*(1 + sqrt(1 - a^2) + x)*(-2 + lambda) + 
            4*I*(1 + sqrt(1 - a^2) + x)^2*(7*lambda + 2*lambda^2 + 6*I*omega) - 
            (1 + sqrt(1 - a^2) + x)^4*(12*lambda + lambda^2 - 24*I*omega)*omega + 
            4*I*(1 + sqrt(1 - a^2) + x)^5*lambda*omega^2 + 6*(1 + sqrt(1 - a^2) + x)^6*omega^3 - 
            4*I*(1 + sqrt(1 - a^2) + x)^3*(lambda + lambda^2 + 6*I*omega + 5*I*lambda*omega)) + 
            a^4*(1 + sqrt(1 - a^2) + x)^3*(24*m^4*(1 + sqrt(1 - a^2) + x) + 
            48*(-4 + 3*I*omega) + 8*(1 + sqrt(1 - a^2) + x)*(9 + lambda^2 + lambda*(2 + 13*I*omega) - 
            72*I*omega) - (1 + sqrt(1 - a^2) + x)^3*(60 + 54*lambda + lambda^2 + 36*I*omega)*omega^2 + 
            8*I*(1 + sqrt(1 - a^2) + x)^4*(-3 + 2*lambda)*omega^3 + 48*(1 + sqrt(1 - a^2) + x)^5*
            omega^4 + 8*(1 + sqrt(1 - a^2) + x)^2*omega*(24*I - 6*I*lambda - I*lambda^2 + 18*omega + 
            8*lambda*omega) + 4*m^2*(30 - (1 + sqrt(1 - a^2) + x)*(33 + 8*lambda + 54*I*omega) + 
            6*I*(1 + sqrt(1 - a^2) + x)^2*(5 + lambda)*omega + 45*(1 + sqrt(1 - a^2) + x)^3*
            omega^2)) + (1 + sqrt(1 - a^2) + x)^6*((-1 + sqrt(1 - a^2) + x)*
            (1 + sqrt(1 - a^2) + x)*lambda^3 + lambda^2*(12 - 12*(1 + sqrt(1 - a^2) + x) + 
            2*(1 + sqrt(1 - a^2) + x)^2 - (1 + sqrt(1 - a^2) + x)^4*omega^2) + 
            12*I*omega*(-12 + 8*(1 + sqrt(1 - a^2) + x) + (1 + sqrt(1 - a^2) + x)^4*omega^2) - 
            2*lambda*(-12 + 4*(1 + sqrt(1 - a^2) + x)*(2 - 3*I*omega) + 
            6*I*(1 + sqrt(1 - a^2) + x)^2*omega + (1 + sqrt(1 - a^2) + x)^4*omega^2)) + 
            a^2*(1 + sqrt(1 - a^2) + x)^4*(96 + 8*(1 + sqrt(1 - a^2) + x)*
            (m^2*(6 + 8*lambda) - 3*(2 + lambda^2 + lambda*(2 + 2*I*omega) - 22*I*omega)) - 96*I*omega + 
            2*(1 + sqrt(1 - a^2) + x)^4*(6 + 24*m^2 - 12*lambda - lambda^2 + 24*I*omega)*omega^2 + 
            8*I*(1 + sqrt(1 - a^2) + x)^5*(-3 + lambda)*omega^3 + 12*(1 + sqrt(1 - a^2) + x)^6*
            omega^4 + (1 + sqrt(1 - a^2) + x)^2*(lambda^3 + lambda*(24 - 34*m^2 - 4*I*omega) + 
            lambda^2*(14 - m^2 + 16*I*omega) - 12*I*(22 + 3*m^2 - 4*I*omega)*omega) + 
            8*(1 + sqrt(1 - a^2) + x)^3*omega*((-I)*lambda^2 + 2*I*m^2*(3 + lambda) + 3*omega + 
            lambda*(2*I + 5*omega)))))/((1 + sqrt(1 - a^2) + x)^2*
            ((-(1 + sqrt(1 - a^2) + x)^4)*(2*lambda + lambda^2 - 12*I*omega) + 
            24*a^3*m*(1 + sqrt(1 - a^2) + x)*(I - 2*(1 + sqrt(1 - a^2) + x)*omega) - 
            4*a*m*(1 + sqrt(1 - a^2) + x)^2*(6*I + 2*I*(1 + sqrt(1 - a^2) + x)*lambda + 
            3*(1 + sqrt(1 - a^2) + x)^2*omega) + 12*a^4*(-1 - 2*I*(1 + sqrt(1 - a^2) + x)*
            omega + 2*(1 + sqrt(1 - a^2) + x)^2*omega^2) + 4*a^2*(1 + sqrt(1 - a^2) + x)*
            (6 + (1 + sqrt(1 - a^2) + x)*(-3 + 6*m^2 + 6*I*omega) + 
            2*I*(1 + sqrt(1 - a^2) + x)^2*(-3 + lambda)*omega + 3*(1 + sqrt(1 - a^2) + x)^3*
            omega^2))))))
        end
    else
        throw(DomainError(s, "Currently only spin weight s of 0, +/-1, +/-2 are supported"))
    end
end

function outgoing_coefficient_at_hor(
    s::Int, m::Int, a, omega, lambda, order::Int;
    data_type=_DEFAULTDATATYPE,
)
    key = _legacy_series_key(
        s, m, a, omega, lambda, HORIZON_OUTGOING_SERIES, order, data_type
    )
    return build_asymptotic_series(key).coefficients[order + 1]
end

function PminusH(s::Int, m::Int, a, omega, lambda, x)
    if s == 0
        return begin
            ((a^2 + (1 + sqrt(1 - a^2) + x)^2)*
            (-((2*x*(1 + sqrt(1 - a^2) + x)*(2*sqrt(1 - a^2) + x))/
            (2*(1 + sqrt(1 - a^2)) + 2*(1 + sqrt(1 - a^2))*x + x^2)^2) + 
            (2*(sqrt(1 - a^2) + x))/(a^2 + (1 + sqrt(1 - a^2) + x)^2) + 
            I*((a*m)/(1 + sqrt(1 - a^2)) - 2*omega)))/(2*sqrt(1 - a^2) + x)
        end
    elseif s == 1
        return begin
            (1/(2*sqrt(1 - a^2) + x))*((a^2 + (1 + sqrt(1 - a^2) + x)^2)*
            (-((2*x*(1 + sqrt(1 - a^2) + x)*(2*sqrt(1 - a^2) + x))/
            (2*(1 + sqrt(1 - a^2)) + 2*(1 + sqrt(1 - a^2))*x + x^2)^2) + 
            (2*(sqrt(1 - a^2) + x))/(a^2 + (1 + sqrt(1 - a^2) + x)^2) + 
            (2*a*x*(2*sqrt(1 - a^2) + x)*(-3*I*a^2*m*(1 + sqrt(1 - a^2) + x) - 
            I*m*(1 + sqrt(1 - a^2) + x)^3 + 2*a^3*(1 + lambda) + a*(1 + sqrt(1 - a^2) + x)*
            (3 + (1 + sqrt(1 - a^2) + x)*(3 + 2*lambda))))/((1 + sqrt(1 - a^2) + x)*
            (a^2 + (1 + sqrt(1 - a^2) + x)^2)*(-2*I*a^3*m*(1 + sqrt(1 - a^2) + x) - 
            2*I*a*m*(1 + sqrt(1 - a^2) + x)^3 + a^4*(1 + lambda) + (1 + sqrt(1 - a^2) + x)^4*
            (2 + lambda) + a^2*(1 + sqrt(1 - a^2) + x)*(2 + (1 + sqrt(1 - a^2) + x)*
            (3 + 2*lambda)))) + I*((a*m)/(1 + sqrt(1 - a^2)) - 2*omega)))
        end
    elseif s == -1
        return begin
            (1/(2*sqrt(1 - a^2) + x))*((a^2 + (1 + sqrt(1 - a^2) + x)^2)*
            (-((2*x*(1 + sqrt(1 - a^2) + x)*(2*sqrt(1 - a^2) + x))/
            (2*(1 + sqrt(1 - a^2)) + 2*(1 + sqrt(1 - a^2))*x + x^2)^2) + 
            (2*(sqrt(1 - a^2) + x))/(a^2 + (1 + sqrt(1 - a^2) + x)^2) + 
            (2*a*x*(2*sqrt(1 - a^2) + x)*(3*I*a^2*m*(1 + sqrt(1 - a^2) + x) + 
            I*m*(1 + sqrt(1 - a^2) + x)^3 + 2*a^3*(-1 + lambda) + a*(1 + sqrt(1 - a^2) + x)*
            (3 + (1 + sqrt(1 - a^2) + x)*(-1 + 2*lambda))))/((1 + sqrt(1 - a^2) + x)*
            (a^2 + (1 + sqrt(1 - a^2) + x)^2)*(2*I*a^3*m*(1 + sqrt(1 - a^2) + x) + 
            2*I*a*m*(1 + sqrt(1 - a^2) + x)^3 + a^4*(-1 + lambda) + (1 + sqrt(1 - a^2) + x)^4*
            lambda + a^2*(1 + sqrt(1 - a^2) + x)*(2 + (1 + sqrt(1 - a^2) + x)*(-1 + 2*lambda)))) + 
            I*((a*m)/(1 + sqrt(1 - a^2)) - 2*omega)))
        end
    elseif s == 2
        return begin
            (1/(2*sqrt(1 - a^2) + x))*((a^2 + (1 + sqrt(1 - a^2) + x)^2)*
            (-((2*x*(1 + sqrt(1 - a^2) + x)*(2*sqrt(1 - a^2) + x))/
            (2*(1 + sqrt(1 - a^2)) + 2*(1 + sqrt(1 - a^2))*x + x^2)^2) + 
            (2*(sqrt(1 - a^2) + x))/(a^2 + (1 + sqrt(1 - a^2) + x)^2) + 
            I*((a*m)/(1 + sqrt(1 - a^2)) - 2*omega) + 
            (8*a*x*(2*sqrt(1 - a^2) + x)*(I*m*(1 + sqrt(1 - a^2) + x)^2*
            (6 + (1 + sqrt(1 - a^2) + x)*(4 + lambda)) - 3*a^2*m*(1 + sqrt(1 - a^2) + x)*
            (3*I + 4*(1 + sqrt(1 - a^2) + x)*omega) + a*(1 + sqrt(1 - a^2) + x)*
            (9 + (1 + sqrt(1 - a^2) + x)*(-3 + 6*m^2 - 6*I*omega) - I*(1 + sqrt(1 - a^2) + x)^2*
            (1 + lambda)*omega) + a^3*(-6 + 9*I*(1 + sqrt(1 - a^2) + x)*omega + 
            6*(1 + sqrt(1 - a^2) + x)^2*omega^2)))/((1 + sqrt(1 - a^2) + x)*
            (a^2 + (1 + sqrt(1 - a^2) + x)^2)*((-(1 + sqrt(1 - a^2) + x)^4)*
            (24 + 10*lambda + lambda^2 + 12*I*omega) - 24*a^3*m*(1 + sqrt(1 - a^2) + x)*
            (I + 2*(1 + sqrt(1 - a^2) + x)*omega) + 4*a*m*(1 + sqrt(1 - a^2) + x)^2*
            (6*I + 2*I*(1 + sqrt(1 - a^2) + x)*(4 + lambda) - 3*(1 + sqrt(1 - a^2) + x)^2*omega) + 
            12*a^4*(-1 + 2*I*(1 + sqrt(1 - a^2) + x)*omega + 2*(1 + sqrt(1 - a^2) + x)^2*omega^2) + 
            4*a^2*(1 + sqrt(1 - a^2) + x)*(6 + (1 + sqrt(1 - a^2) + x)*
            (-3 + 6*m^2 - 6*I*omega) - 2*I*(1 + sqrt(1 - a^2) + x)^2*(1 + lambda)*omega + 
            3*(1 + sqrt(1 - a^2) + x)^3*omega^2)))))
        end
    elseif s == -2
        return begin
            (1/(2*sqrt(1 - a^2) + x))*((a^2 + (1 + sqrt(1 - a^2) + x)^2)*
            (-((2*x*(1 + sqrt(1 - a^2) + x)*(2*sqrt(1 - a^2) + x))/
            (2*(1 + sqrt(1 - a^2)) + 2*(1 + sqrt(1 - a^2))*x + x^2)^2) + 
            (2*(sqrt(1 - a^2) + x))/(a^2 + (1 + sqrt(1 - a^2) + x)^2) + 
            I*((a*m)/(1 + sqrt(1 - a^2)) - 2*omega) - 
            (8*a*x*(2*sqrt(1 - a^2) + x)*((-I)*m*(1 + sqrt(1 - a^2) + x)^2*
            (6 + (1 + sqrt(1 - a^2) + x)*lambda) + 3*a^2*m*(1 + sqrt(1 - a^2) + x)*
            (3*I - 4*(1 + sqrt(1 - a^2) + x)*omega) + a*(1 + sqrt(1 - a^2) + x)*
            (9 + (1 + sqrt(1 - a^2) + x)*(-3 + 6*m^2 + 6*I*omega) + I*(1 + sqrt(1 - a^2) + x)^2*
            (-3 + lambda)*omega) + a^3*(-6 - 9*I*(1 + sqrt(1 - a^2) + x)*omega + 
            6*(1 + sqrt(1 - a^2) + x)^2*omega^2)))/((1 + sqrt(1 - a^2) + x)*
            (a^2 + (1 + sqrt(1 - a^2) + x)^2)*((1 + sqrt(1 - a^2) + x)^4*
            (2*lambda + lambda^2 - 12*I*omega) + 24*a^3*m*(1 + sqrt(1 - a^2) + x)*
            (-I + 2*(1 + sqrt(1 - a^2) + x)*omega) + 4*a*m*(1 + sqrt(1 - a^2) + x)^2*
            (6*I + 2*I*(1 + sqrt(1 - a^2) + x)*lambda + 3*(1 + sqrt(1 - a^2) + x)^2*omega) + 
            a^4*(12 + 24*I*(1 + sqrt(1 - a^2) + x)*omega - 24*(1 + sqrt(1 - a^2) + x)^2*omega^2) - 
            4*a^2*(1 + sqrt(1 - a^2) + x)*(6 + (1 + sqrt(1 - a^2) + x)*
            (-3 + 6*m^2 + 6*I*omega) + 2*I*(1 + sqrt(1 - a^2) + x)^2*(-3 + lambda)*omega + 
            3*(1 + sqrt(1 - a^2) + x)^3*omega^2)))))
        end
    else
        throw(DomainError(s, "Currently only spin weight s of 0, +/-1, +/-2 are supported"))
    end
end

function QminusH(s::Int, m::Int, a, omega, lambda, x)
    if s == 0
        return begin
            (1/(2*sqrt(1 - a^2) + x)^2)*((a^2 + (1 + sqrt(1 - a^2) + x)^2)^2*
            (-(-((a*m)/(2*(1 + sqrt(1 - a^2)))) + omega)^2 - (1/(a^2 + (1 + sqrt(1 - a^2) + x)^2)^4)*
            (x^2*(1 + sqrt(1 - a^2) + x)^2*(2*sqrt(1 - a^2) + x)^2 + 
            x*(2*sqrt(1 - a^2) + x)*(a^4 - 4*a^2*(1 + sqrt(1 - a^2) + x) - 
            (-3 + sqrt(1 - a^2) + x)*(1 + sqrt(1 - a^2) + x)^3) + 
            (a^2 + (1 + sqrt(1 - a^2) + x)^2)^2*(x*(2*sqrt(1 - a^2) + x)*lambda - 
            (a*m - (a^2 + (1 + sqrt(1 - a^2) + x)^2)*omega)^2))))
        end
    elseif s == 1
        return begin
            (1/(2*sqrt(1 - a^2) + x)^2)*((a^2 + (1 + sqrt(1 - a^2) + x)^2)^2*
            (-((2*I*a*x*(2*sqrt(1 - a^2) + x)*(-3*I*a^2*m*(1 + sqrt(1 - a^2) + x) - 
            I*m*(1 + sqrt(1 - a^2) + x)^3 + 2*a^3*(1 + lambda) + a*(1 + sqrt(1 - a^2) + x)*
            (3 + (1 + sqrt(1 - a^2) + x)*(3 + 2*lambda)))*(-((a*m)/(2*(1 + sqrt(1 - a^2)))) + 
            omega))/((1 + sqrt(1 - a^2) + x)*(a^2 + (1 + sqrt(1 - a^2) + x)^2)*
            (-2*I*a^3*m*(1 + sqrt(1 - a^2) + x) - 2*I*a*m*(1 + sqrt(1 - a^2) + x)^3 + 
            a^4*(1 + lambda) + (1 + sqrt(1 - a^2) + x)^4*(2 + lambda) + a^2*(1 + sqrt(1 - a^2) + x)*
            (2 + (1 + sqrt(1 - a^2) + x)*(3 + 2*lambda))))) - 
            (-((a*m)/(2*(1 + sqrt(1 - a^2)))) + omega)^2 - (1/(a^2 + (1 + sqrt(1 - a^2) + x)^2)^4)*
            (2*x*(2*sqrt(1 - a^2) + x)*(a^4 - a^2*(1 + sqrt(1 - a^2) + x) - 
            (-2 + sqrt(1 - a^2) + x)*(1 + sqrt(1 - a^2) + x)^3) + 
            ((1 + sqrt(1 - a^2) + x)^2*(-1 + 2*sqrt(1 - a^2) + 2*x) + 
            a^2*(1 + 2*sqrt(1 - a^2) + 2*x))^2 + (2*a*x*(2*sqrt(1 - a^2) + x)*
            (a^2 + (1 + sqrt(1 - a^2) + x)^2)*((1 + sqrt(1 - a^2) + x)^2*
            (-1 + 2*sqrt(1 - a^2) + 2*x) + a^2*(1 + 2*sqrt(1 - a^2) + 2*x))*
            (-3*I*a^2*m*(1 + sqrt(1 - a^2) + x) - I*m*(1 + sqrt(1 - a^2) + x)^3 + 
            2*a^3*(1 + lambda) + a*(1 + sqrt(1 - a^2) + x)*(3 + (1 + sqrt(1 - a^2) + x)*
            (3 + 2*lambda))))/((1 + sqrt(1 - a^2) + x)*(-2*I*a^3*m*(1 + sqrt(1 - a^2) + x) - 
            2*I*a*m*(1 + sqrt(1 - a^2) + x)^3 + a^4*(1 + lambda) + (1 + sqrt(1 - a^2) + x)^4*
            (2 + lambda) + a^2*(1 + sqrt(1 - a^2) + x)*(2 + (1 + sqrt(1 - a^2) + x)*
            (3 + 2*lambda)))) - ((a^2 + (1 + sqrt(1 - a^2) + x)^2)^2*
            (2*a^7*m*(1 + sqrt(1 - a^2) + x)^2*omega*(-lambda - I*(1 + sqrt(1 - a^2) + x)*omega) + 
            a^8*(1 + lambda)*(2 + (1 + sqrt(1 - a^2) + x)^2*omega^2) - 
            2*I*a^5*m*(1 + sqrt(1 - a^2) + x)^2*(-6 + (1 + sqrt(1 - a^2) + x)*
            (4 + m^2 - lambda - 4*I*omega) - 3*I*(1 + sqrt(1 - a^2) + x)^2*(1 + lambda)*omega + 
            3*(1 + sqrt(1 - a^2) + x)^3*omega^2) - 2*I*a*m*(1 + sqrt(1 - a^2) + x)^5*
            (3 + (1 + sqrt(1 - a^2) + x)*(-5 + 2*lambda) + (1 + sqrt(1 - a^2) + x)^2*
            (2 - lambda + 2*I*omega) - I*(1 + sqrt(1 - a^2) + x)^3*(3 + lambda)*omega + 
            (1 + sqrt(1 - a^2) + x)^4*omega^2) - 2*I*a^3*m*(1 + sqrt(1 - a^2) + x)^3*
            (13 + (1 + sqrt(1 - a^2) + x)*(-17 + 2*lambda) + (1 + sqrt(1 - a^2) + x)^2*
            (6 + m^2 - 2*lambda - 2*I*omega) - 3*I*(1 + sqrt(1 - a^2) + x)^3*(2 + lambda)*omega + 
            3*(1 + sqrt(1 - a^2) + x)^4*omega^2) + (1 + sqrt(1 - a^2) + x)^6*
            (-3*(2 + lambda) - (1 + sqrt(1 - a^2) + x)^2*lambda*(2 + lambda) + 
            2*(1 + sqrt(1 - a^2) + x)*(2 + 3*lambda + lambda^2) + (1 + sqrt(1 - a^2) + x)^4*
            (2 + lambda)*omega^2) + a^6*(1 + sqrt(1 - a^2) + x)*(-16*(1 + lambda) + 
            (1 + sqrt(1 - a^2) + x)*(5 + m^2*(-1 + lambda) + 6*lambda - lambda^2 + 2*I*omega) + 
            (1 + sqrt(1 - a^2) + x)^3*(5 + 4*lambda)*omega^2 + 2*(1 + sqrt(1 - a^2) + x)^2*omega*
            (I + 2*I*m^2 + omega)) + a^4*(1 + sqrt(1 - a^2) + x)^2*
            (11 + 25*lambda + 2*(1 + sqrt(1 - a^2) + x)*(-5 + 3*m^2 - 13*lambda + lambda^2 - 2*I*omega) + 
            (1 + sqrt(1 - a^2) + x)^2*(5 + 4*lambda - 3*lambda^2 + m^2*(3 + 2*lambda) - 8*I*omega) + 
            3*(1 + sqrt(1 - a^2) + x)^4*(3 + 2*lambda)*omega^2 + 4*(1 + sqrt(1 - a^2) + x)^3*omega*
            (I + 2*I*m^2 + omega)) + a^2*(1 + sqrt(1 - a^2) + x)^3*
            (30 + 5*(1 + sqrt(1 - a^2) + x)*(-7 + 2*lambda) - 4*(1 + sqrt(1 - a^2) + x)^2*
            (-2 + m^2 + lambda - lambda^2 - 3*I*omega) + (1 + sqrt(1 - a^2) + x)^3*
            (2 - 2*lambda - 3*lambda^2 + m^2*(4 + lambda) - 10*I*omega) + (1 + sqrt(1 - a^2) + x)^5*
            (7 + 4*lambda)*omega^2 + 2*(1 + sqrt(1 - a^2) + x)^4*omega*(I + 2*I*m^2 + omega))))/
            ((1 + sqrt(1 - a^2) + x)^2*(-2*I*a^3*m*(1 + sqrt(1 - a^2) + x) - 
            2*I*a*m*(1 + sqrt(1 - a^2) + x)^3 + a^4*(1 + lambda) + (1 + sqrt(1 - a^2) + x)^4*
            (2 + lambda) + a^2*(1 + sqrt(1 - a^2) + x)*(2 + (1 + sqrt(1 - a^2) + x)*
            (3 + 2*lambda)))))))
        end
    elseif s == -1
        return begin
            (1/(2*sqrt(1 - a^2) + x)^2)*((a^2 + (1 + sqrt(1 - a^2) + x)^2)^2*
            (-((2*I*a*x*(2*sqrt(1 - a^2) + x)*(3*I*a^2*m*(1 + sqrt(1 - a^2) + x) + 
            I*m*(1 + sqrt(1 - a^2) + x)^3 + 2*a^3*(-1 + lambda) + a*(1 + sqrt(1 - a^2) + x)*
            (3 + (1 + sqrt(1 - a^2) + x)*(-1 + 2*lambda)))*(-((a*m)/(2*(1 + sqrt(1 - a^2)))) + 
            omega))/((1 + sqrt(1 - a^2) + x)*(a^2 + (1 + sqrt(1 - a^2) + x)^2)*
            (2*I*a^3*m*(1 + sqrt(1 - a^2) + x) + 2*I*a*m*(1 + sqrt(1 - a^2) + x)^3 + 
            a^4*(-1 + lambda) + (1 + sqrt(1 - a^2) + x)^4*lambda + a^2*(1 + sqrt(1 - a^2) + x)*
            (2 + (1 + sqrt(1 - a^2) + x)*(-1 + 2*lambda))))) - 
            (-((a*m)/(2*(1 + sqrt(1 - a^2)))) + omega)^2 - (1/(a^2 + (1 + sqrt(1 - a^2) + x)^2)^4)*
            ((a^2 - (1 + sqrt(1 - a^2) + x)^2)^2 + 2*x*(1 + sqrt(1 - a^2) + x)*
            (2*sqrt(1 - a^2) + x)*(-3*a^2 + (1 + sqrt(1 - a^2) + x)^2) + 
            (2*a*x*(2*sqrt(1 - a^2) + x)*(a^2 - (1 + sqrt(1 - a^2) + x)^2)*
            (a^2 + (1 + sqrt(1 - a^2) + x)^2)*(3*I*a^2*m*(1 + sqrt(1 - a^2) + x) + 
            I*m*(1 + sqrt(1 - a^2) + x)^3 + 2*a^3*(-1 + lambda) + a*(1 + sqrt(1 - a^2) + x)*
            (3 + (1 + sqrt(1 - a^2) + x)*(-1 + 2*lambda))))/((1 + sqrt(1 - a^2) + x)*
            (2*I*a^3*m*(1 + sqrt(1 - a^2) + x) + 2*I*a*m*(1 + sqrt(1 - a^2) + x)^3 + 
            a^4*(-1 + lambda) + (1 + sqrt(1 - a^2) + x)^4*lambda + a^2*(1 + sqrt(1 - a^2) + x)*
            (2 + (1 + sqrt(1 - a^2) + x)*(-1 + 2*lambda)))) - 
            ((a^2 + (1 + sqrt(1 - a^2) + x)^2)^2*(2*a^7*m*(1 + sqrt(1 - a^2) + x)^2*omega*
            (2 - lambda + I*(1 + sqrt(1 - a^2) + x)*omega) + a^8*(-1 + lambda)*
            (2 + (1 + sqrt(1 - a^2) + x)^2*omega^2) + 2*I*a^5*m*(1 + sqrt(1 - a^2) + x)^3*
            (-2 + m^2 - lambda + 4*I*omega - 3*I*(1 + sqrt(1 - a^2) + x)*omega + 
            3*I*(1 + sqrt(1 - a^2) + x)*lambda*omega + 3*(1 + sqrt(1 - a^2) + x)^2*omega^2) + 
            (1 + sqrt(1 - a^2) + x)^6*lambda*(-3 - (1 + sqrt(1 - a^2) + x)^2*lambda + 
            2*(1 + sqrt(1 - a^2) + x)*(1 + lambda) + (1 + sqrt(1 - a^2) + x)^4*omega^2) + 
            2*I*a*m*(1 + sqrt(1 - a^2) + x)^5*(sqrt(1 - a^2) + x + 
            2*(1 + sqrt(1 - a^2) + x)*lambda - (1 + sqrt(1 - a^2) + x)^2*(lambda + 2*I*omega) + 
            I*(1 + sqrt(1 - a^2) + x)^3*(1 + lambda)*omega + (1 + sqrt(1 - a^2) + x)^4*omega^2) + 
            2*I*a^3*m*(1 + sqrt(1 - a^2) + x)^3*(1 + (1 + sqrt(1 - a^2) + x)*(3 + 2*lambda) + 
            (1 + sqrt(1 - a^2) + x)^2*(-2 + m^2 - 2*lambda + 2*I*omega) + 
            3*I*(1 + sqrt(1 - a^2) + x)^3*lambda*omega + 3*(1 + sqrt(1 - a^2) + x)^4*omega^2) + 
            a^6*(1 + sqrt(1 - a^2) + x)*(8 - 8*lambda + (1 + sqrt(1 - a^2) + x)*
            (-1 + m^2*(-3 + lambda) - lambda^2 - 2*I*omega) + (1 + sqrt(1 - a^2) + x)^3*(-3 + 4*lambda)*
            omega^2 + 2*(1 + sqrt(1 - a^2) + x)^2*omega*(-I - 2*I*m^2 + omega)) + 
            a^4*(1 + sqrt(1 - a^2) + x)^2*(-11 + 9*lambda + 2*(1 + sqrt(1 - a^2) + x)*
            (1 + 3*m^2 + lambda + lambda^2 + 2*I*omega) + (1 + sqrt(1 - a^2) + x)^2*
            (1 - 6*lambda - 3*lambda^2 + m^2*(-1 + 2*lambda) + 8*I*omega) + 3*(1 + sqrt(1 - a^2) + x)^4*
            (-1 + 2*lambda)*omega^2 + 4*(1 + sqrt(1 - a^2) + x)^3*omega*(-I - 2*I*m^2 + omega)) + 
            a^2*(1 + sqrt(1 - a^2) + x)^3*(6 - 3*(1 + sqrt(1 - a^2) + x)*(1 + 2*lambda) - 
            4*(1 + sqrt(1 - a^2) + x)^2*(m^2 - 3*lambda - lambda^2 + 3*I*omega) + 
            (1 + sqrt(1 - a^2) + x)^3*(-4*lambda - 3*lambda^2 + m^2*(2 + lambda) + 10*I*omega) + 
            (1 + sqrt(1 - a^2) + x)^5*(-1 + 4*lambda)*omega^2 + 2*(1 + sqrt(1 - a^2) + x)^4*omega*
            (-I - 2*I*m^2 + omega))))/((1 + sqrt(1 - a^2) + x)^2*
            (2*I*a^3*m*(1 + sqrt(1 - a^2) + x) + 2*I*a*m*(1 + sqrt(1 - a^2) + x)^3 + 
            a^4*(-1 + lambda) + (1 + sqrt(1 - a^2) + x)^4*lambda + a^2*(1 + sqrt(1 - a^2) + x)*
            (2 + (1 + sqrt(1 - a^2) + x)*(-1 + 2*lambda)))))))
        end
    elseif s == 2
        return begin
            (1/(2*sqrt(1 - a^2) + x)^2)*((a^2 + (1 + sqrt(1 - a^2) + x)^2)^2*
            (-(-((a*m)/(2*(1 + sqrt(1 - a^2)))) + omega)^2 + 
            (8*I*a*x*(2*sqrt(1 - a^2) + x)*(-((a*m)/(2*(1 + sqrt(1 - a^2)))) + omega)*
            (I*m*(1 + sqrt(1 - a^2) + x)^2*(6 + (1 + sqrt(1 - a^2) + x)*(4 + lambda)) - 
            3*a^2*m*(1 + sqrt(1 - a^2) + x)*(3*I + 4*(1 + sqrt(1 - a^2) + x)*omega) + 
            a*(1 + sqrt(1 - a^2) + x)*(9 + (1 + sqrt(1 - a^2) + x)*(-3 + 6*m^2 - 6*I*omega) - 
            I*(1 + sqrt(1 - a^2) + x)^2*(1 + lambda)*omega) + 
            a^3*(-6 + 9*I*(1 + sqrt(1 - a^2) + x)*omega + 6*(1 + sqrt(1 - a^2) + x)^2*omega^2)))/
            ((1 + sqrt(1 - a^2) + x)*(a^2 + (1 + sqrt(1 - a^2) + x)^2)*
            ((1 + sqrt(1 - a^2) + x)^4*(24 + 10*lambda + lambda^2 + 12*I*omega) + 
            24*a^3*m*(1 + sqrt(1 - a^2) + x)*(I + 2*(1 + sqrt(1 - a^2) + x)*omega) + 
            4*a*m*(1 + sqrt(1 - a^2) + x)^2*(-6*I - 2*I*(1 + sqrt(1 - a^2) + x)*(4 + lambda) + 
            3*(1 + sqrt(1 - a^2) + x)^2*omega) - 12*a^4*(-1 + 2*I*(1 + sqrt(1 - a^2) + x)*omega + 
            2*(1 + sqrt(1 - a^2) + x)^2*omega^2) - 4*a^2*(1 + sqrt(1 - a^2) + x)*
            (6 + (1 + sqrt(1 - a^2) + x)*(-3 + 6*m^2 - 6*I*omega) - 
            2*I*(1 + sqrt(1 - a^2) + x)^2*(1 + lambda)*omega + 3*(1 + sqrt(1 - a^2) + x)^3*
            omega^2))) - (((1 + sqrt(1 - a^2) + x)^2*(-1 + 3*sqrt(1 - a^2) + 3*x) + 
            a^2*(1 + 3*sqrt(1 - a^2) + 3*x))^2 + x*(2*sqrt(1 - a^2) + x)*
            (3*a^4 + (1 + sqrt(1 - a^2) + x)^3*(8 - 3*(1 + sqrt(1 - a^2) + x))) + 
            (8*a*x*(2*sqrt(1 - a^2) + x)*(a^2 + (1 + sqrt(1 - a^2) + x)^2)*
            ((1 + sqrt(1 - a^2) + x)^2*(-1 + 3*sqrt(1 - a^2) + 3*x) + 
            a^2*(1 + 3*sqrt(1 - a^2) + 3*x))*(I*m*(1 + sqrt(1 - a^2) + x)^2*
            (6 + (1 + sqrt(1 - a^2) + x)*(4 + lambda)) - 3*a^2*m*(1 + sqrt(1 - a^2) + x)*
            (3*I + 4*(1 + sqrt(1 - a^2) + x)*omega) + a*(1 + sqrt(1 - a^2) + x)*
            (9 + (1 + sqrt(1 - a^2) + x)*(-3 + 6*m^2 - 6*I*omega) - 
            I*(1 + sqrt(1 - a^2) + x)^2*(1 + lambda)*omega) + 
            a^3*(-6 + 9*I*(1 + sqrt(1 - a^2) + x)*omega + 6*(1 + sqrt(1 - a^2) + x)^2*omega^2)))/
            ((1 + sqrt(1 - a^2) + x)*((-(1 + sqrt(1 - a^2) + x)^4)*(24 + 10*lambda + lambda^2 + 
            12*I*omega) - 24*a^3*m*(1 + sqrt(1 - a^2) + x)*(I + 2*(1 + sqrt(1 - a^2) + x)*
            omega) + 4*a*m*(1 + sqrt(1 - a^2) + x)^2*(6*I + 2*I*(1 + sqrt(1 - a^2) + x)*
            (4 + lambda) - 3*(1 + sqrt(1 - a^2) + x)^2*omega) + 
            12*a^4*(-1 + 2*I*(1 + sqrt(1 - a^2) + x)*omega + 2*(1 + sqrt(1 - a^2) + x)^2*
            omega^2) + 4*a^2*(1 + sqrt(1 - a^2) + x)*(6 + (1 + sqrt(1 - a^2) + x)*
            (-3 + 6*m^2 - 6*I*omega) - 2*I*(1 + sqrt(1 - a^2) + x)^2*(1 + lambda)*omega + 
            3*(1 + sqrt(1 - a^2) + x)^3*omega^2))) - ((a^2 + (1 + sqrt(1 - a^2) + x)^2)^2*
            (24*a^7*m*(1 + sqrt(1 - a^2) + x)^2*omega*(3 + 3*I*(1 + sqrt(1 - a^2) + x)*omega - 
            4*(1 + sqrt(1 - a^2) + x)^2*omega^2) - (1 + sqrt(1 - a^2) + x)^6*
            (24 + 10*lambda + lambda^2 + 12*I*omega)*(-12 - (1 + sqrt(1 - a^2) + x)^2*lambda + 
            2*(1 + sqrt(1 - a^2) + x)*(4 + lambda) + (1 + sqrt(1 - a^2) + x)^4*omega^2) - 
            4*a^5*m*(1 + sqrt(1 - a^2) + x)^2*(-54*I - 2*I*(1 + sqrt(1 - a^2) + x)*
            (-55 + 3*m^2 - 4*lambda - 18*I*omega) + 2*(1 + sqrt(1 - a^2) + x)^2*
            (4 + 12*m^2 - 8*lambda + 27*I*omega)*omega - 6*I*(1 + sqrt(1 - a^2) + x)^3*(8 + lambda)*
            omega^2 + 45*(1 + sqrt(1 - a^2) + x)^4*omega^3) + 
            12*a^8*(-2 - 3*(1 + sqrt(1 - a^2) + x)^2*omega^2 - 2*I*(1 + sqrt(1 - a^2) + x)^3*
            omega^3 + 2*(1 + sqrt(1 - a^2) + x)^4*omega^4) + 4*a^6*(1 + sqrt(1 - a^2) + x)*
            (60 - 3*(1 + sqrt(1 - a^2) + x)*(16 + 3*m^2 + 18*I*omega) + 
            (1 + sqrt(1 - a^2) + x)^3*(1 + 36*m^2 - 8*lambda + 18*I*omega)*omega^2 - 
            2*I*(1 + sqrt(1 - a^2) + x)^4*(7 + lambda)*omega^3 + 15*(1 + sqrt(1 - a^2) + x)^5*
            omega^4 - 2*(1 + sqrt(1 - a^2) + x)^2*omega*(-40*I + 9*I*m^2 - 4*I*lambda + 9*omega)) + 
            2*a*m*(1 + sqrt(1 - a^2) + x)^4*(144*I + 8*I*(1 + sqrt(1 - a^2) + x)*
            (-38 + lambda) + (1 + sqrt(1 - a^2) + x)^4*(40 + 20*lambda + lambda^2 + 24*I*omega)*omega + 
            4*I*(1 + sqrt(1 - a^2) + x)^5*(4 + lambda)*omega^2 - 6*(1 + sqrt(1 - a^2) + x)^6*
            omega^3 + 4*(1 + sqrt(1 - a^2) + x)^2*(16*I + 3*I*lambda + 2*I*lambda^2 + 6*omega) - 
            4*I*(1 + sqrt(1 - a^2) + x)^3*(-12 + lambda + lambda^2 - 14*I*omega - 5*I*lambda*omega)) - 
            2*a^3*m*(1 + sqrt(1 - a^2) + x)^3*(312*I + (1 + sqrt(1 - a^2) + x)^3*
            (84 + 30*m^2 - 52*lambda - lambda^2 + 36*I*omega)*omega - 4*I*(1 + sqrt(1 - a^2) + x)^4*
            (19 + 4*lambda)*omega^2 + 48*(1 + sqrt(1 - a^2) + x)^5*omega^3 + 
            12*(1 + sqrt(1 - a^2) + x)*(-63*I + 3*I*m^2 - 3*I*lambda + 32*omega) + 
            4*(1 + sqrt(1 - a^2) + x)^2*(71*I + I*lambda^2 - I*m^2*(10 + lambda) - 104*omega + 
            lambda*(9*I + 16*omega))) + a^2*(1 + sqrt(1 - a^2) + x)^3*
            (576 + 96*(1 + sqrt(1 - a^2) + x)*(-12 + 4*m^2 - 3*I*omega) + 
            8*(1 + sqrt(1 - a^2) + x)^2*(18 - 3*lambda^2 + m^2*(-58 + 8*lambda) + 
            lambda*(-30 - 2*I*omega) + 46*I*omega) - 8*I*(1 + sqrt(1 - a^2) + x)^4*
            (-lambda^2 + 2*m^2*(7 + lambda) + lambda*(2 + 5*I*omega) + 11*I*omega)*omega + 
            2*(1 + sqrt(1 - a^2) + x)^5*(-34 + 24*m^2 - 20*lambda - lambda^2 - 24*I*omega)*omega^2 - 
            8*I*(1 + sqrt(1 - a^2) + x)^6*(1 + lambda)*omega^3 + 12*(1 + sqrt(1 - a^2) + x)^7*
            omega^4 + (1 + sqrt(1 - a^2) + x)^3*(lambda^3 + 36*lambda*(4 + I*omega) + 
            2*lambda^2*(11 - 8*I*omega) - m^2*(-136 + 42*lambda + lambda^2 - 36*I*omega) - 
            8*(-18 + 19*I*omega + 6*omega^2))) + a^4*(1 + sqrt(1 - a^2) + x)^2*
            (-672 + (1 + sqrt(1 - a^2) + x)*(960 - 72*m^2 + 624*I*omega) + 
            (1 + sqrt(1 - a^2) + x)^4*(44 + 180*m^2 - 62*lambda - lambda^2 + 36*I*omega)*omega^2 - 
            8*I*(1 + sqrt(1 - a^2) + x)^5*(5 + 2*lambda)*omega^3 + 48*(1 + sqrt(1 - a^2) + x)^6*
            omega^4 + 8*(1 + sqrt(1 - a^2) + x)^3*omega*(56*I + I*lambda^2 - 3*I*m^2*(9 + lambda) - 
            46*omega + lambda*(6*I + 8*omega)) + 4*(1 + sqrt(1 - a^2) + x)^2*
            (6*m^4 + m^2*(7 - 8*lambda + 54*I*omega) + 2*(-15 + 10*lambda + lambda^2 - 144*I*omega - 9*I*
            lambda*omega + 48*omega^2)))))/((1 + sqrt(1 - a^2) + x)^2*
            ((-(1 + sqrt(1 - a^2) + x)^4)*(24 + 10*lambda + lambda^2 + 12*I*omega) - 
            24*a^3*m*(1 + sqrt(1 - a^2) + x)*(I + 2*(1 + sqrt(1 - a^2) + x)*omega) + 
            4*a*m*(1 + sqrt(1 - a^2) + x)^2*(6*I + 2*I*(1 + sqrt(1 - a^2) + x)*(4 + lambda) - 
            3*(1 + sqrt(1 - a^2) + x)^2*omega) + 12*a^4*(-1 + 2*I*(1 + sqrt(1 - a^2) + x)*
            omega + 2*(1 + sqrt(1 - a^2) + x)^2*omega^2) + 4*a^2*(1 + sqrt(1 - a^2) + x)*
            (6 + (1 + sqrt(1 - a^2) + x)*(-3 + 6*m^2 - 6*I*omega) - 
            2*I*(1 + sqrt(1 - a^2) + x)^2*(1 + lambda)*omega + 3*(1 + sqrt(1 - a^2) + x)^3*
            omega^2))))/(a^2 + (1 + sqrt(1 - a^2) + x)^2)^4))
        end
    elseif s == -2
        return begin
            (1/(2*sqrt(1 - a^2) + x)^2)*((a^2 + (1 + sqrt(1 - a^2) + x)^2)^2*
            (-(-((a*m)/(2*(1 + sqrt(1 - a^2)))) + omega)^2 + 
            (8*I*a*x*(2*sqrt(1 - a^2) + x)*(-((a*m)/(2*(1 + sqrt(1 - a^2)))) + omega)*
            ((-I)*m*(1 + sqrt(1 - a^2) + x)^2*(6 + (1 + sqrt(1 - a^2) + x)*lambda) + 
            3*a^2*m*(1 + sqrt(1 - a^2) + x)*(3*I - 4*(1 + sqrt(1 - a^2) + x)*omega) + 
            a*(1 + sqrt(1 - a^2) + x)*(9 + (1 + sqrt(1 - a^2) + x)*(-3 + 6*m^2 + 6*I*omega) + 
            I*(1 + sqrt(1 - a^2) + x)^2*(-3 + lambda)*omega) + 
            a^3*(-6 - 9*I*(1 + sqrt(1 - a^2) + x)*omega + 6*(1 + sqrt(1 - a^2) + x)^2*omega^2)))/
            ((1 + sqrt(1 - a^2) + x)*(a^2 + (1 + sqrt(1 - a^2) + x)^2)*
            ((1 + sqrt(1 - a^2) + x)^4*(2*lambda + lambda^2 - 12*I*omega) + 
            24*a^3*m*(1 + sqrt(1 - a^2) + x)*(-I + 2*(1 + sqrt(1 - a^2) + x)*omega) + 
            4*a*m*(1 + sqrt(1 - a^2) + x)^2*(6*I + 2*I*(1 + sqrt(1 - a^2) + x)*lambda + 
            3*(1 + sqrt(1 - a^2) + x)^2*omega) + a^4*(12 + 24*I*(1 + sqrt(1 - a^2) + x)*omega - 
            24*(1 + sqrt(1 - a^2) + x)^2*omega^2) - 4*a^2*(1 + sqrt(1 - a^2) + x)*
            (6 + (1 + sqrt(1 - a^2) + x)*(-3 + 6*m^2 + 6*I*omega) + 
            2*I*(1 + sqrt(1 - a^2) + x)^2*(-3 + lambda)*omega + 3*(1 + sqrt(1 - a^2) + x)^3*
            omega^2))) - (1/(a^2 + (1 + sqrt(1 - a^2) + x)^2)^4)*
            ((a^2*(-1 + sqrt(1 - a^2) + x) + (1 + sqrt(1 - a^2) + x)^3)^2 + 
            x*(2*sqrt(1 - a^2) + x)*(-a^4 - 8*a^2*(1 + sqrt(1 - a^2) + x) + 
            (1 + sqrt(1 - a^2) + x)^4) + (8*a*x*(2*sqrt(1 - a^2) + x)*
            (a^2 + (1 + sqrt(1 - a^2) + x)^2)*(a^2*(-1 + sqrt(1 - a^2) + x) + 
            (1 + sqrt(1 - a^2) + x)^3)*((-I)*m*(1 + sqrt(1 - a^2) + x)^2*
            (6 + (1 + sqrt(1 - a^2) + x)*lambda) + 3*a^2*m*(1 + sqrt(1 - a^2) + x)*
            (3*I - 4*(1 + sqrt(1 - a^2) + x)*omega) + a*(1 + sqrt(1 - a^2) + x)*
            (9 + (1 + sqrt(1 - a^2) + x)*(-3 + 6*m^2 + 6*I*omega) + 
            I*(1 + sqrt(1 - a^2) + x)^2*(-3 + lambda)*omega) + 
            a^3*(-6 - 9*I*(1 + sqrt(1 - a^2) + x)*omega + 6*(1 + sqrt(1 - a^2) + x)^2*omega^2)))/
            ((1 + sqrt(1 - a^2) + x)*((1 + sqrt(1 - a^2) + x)^4*(2*lambda + lambda^2 - 12*I*omega) + 
            24*a^3*m*(1 + sqrt(1 - a^2) + x)*(-I + 2*(1 + sqrt(1 - a^2) + x)*omega) + 
            4*a*m*(1 + sqrt(1 - a^2) + x)^2*(6*I + 2*I*(1 + sqrt(1 - a^2) + x)*lambda + 
            3*(1 + sqrt(1 - a^2) + x)^2*omega) + a^4*(12 + 24*I*(1 + sqrt(1 - a^2) + x)*omega - 
            24*(1 + sqrt(1 - a^2) + x)^2*omega^2) - 4*a^2*(1 + sqrt(1 - a^2) + x)*
            (6 + (1 + sqrt(1 - a^2) + x)*(-3 + 6*m^2 + 6*I*omega) + 
            2*I*(1 + sqrt(1 - a^2) + x)^2*(-3 + lambda)*omega + 3*(1 + sqrt(1 - a^2) + x)^3*
            omega^2))) - ((a^2 + (1 + sqrt(1 - a^2) + x)^2)^2*
            (-24*a^7*m*(1 + sqrt(1 - a^2) + x)^2*omega*(-3 + 3*I*(1 + sqrt(1 - a^2) + x)*omega + 
            4*(1 + sqrt(1 - a^2) + x)^2*omega^2) - 2*a^3*m*(1 + sqrt(1 - a^2) + x)^3*
            (72*I - 4*I*(1 + sqrt(1 - a^2) + x)*(15 + 9*m^2 - 13*lambda) + 
            4*(1 + sqrt(1 - a^2) + x)^2*(I*m^2*(6 + lambda) - I*(3 + lambda^2 + lambda*
            (9 + 16*I*omega) + 24*I*omega)) + (1 + sqrt(1 - a^2) + x)^3*
            (-36 + 30*m^2 - 44*lambda - lambda^2 - 36*I*omega)*omega + 4*I*(1 + sqrt(1 - a^2) + x)^4*
            (3 + 4*lambda)*omega^2 + 48*(1 + sqrt(1 - a^2) + x)^5*omega^3) + 
            12*a^8*(-2 - 3*(1 + sqrt(1 - a^2) + x)^2*omega^2 + 2*I*(1 + sqrt(1 - a^2) + x)^3*
            omega^3 + 2*(1 + sqrt(1 - a^2) + x)^4*omega^4) + 4*a^6*(1 + sqrt(1 - a^2) + x)*
            (12 - 3*(1 + sqrt(1 - a^2) + x)*(-4 + 3*m^2 + 6*I*omega) + 
            (1 + sqrt(1 - a^2) + x)^3*(-39 + 36*m^2 - 8*lambda - 18*I*omega)*omega^2 + 
            2*I*(1 + sqrt(1 - a^2) + x)^4*(3 + lambda)*omega^3 + 15*(1 + sqrt(1 - a^2) + x)^5*
            omega^4 + 2*(1 + sqrt(1 - a^2) + x)^2*omega*(24*I + 9*I*m^2 - 4*I*lambda + 15*omega)) - 
            4*a^5*m*(1 + sqrt(1 - a^2) + x)^2*(-18*I + 2*(1 + sqrt(1 - a^2) + x)^2*
            (-36 + 12*m^2 - 8*lambda - 27*I*omega)*omega + 6*I*(1 + sqrt(1 - a^2) + x)^3*(4 + lambda)*
            omega^2 + 45*(1 + sqrt(1 - a^2) + x)^4*omega^3 + 2*(1 + sqrt(1 - a^2) + x)*
            (9*I + 3*I*m^2 - 4*I*lambda + 30*omega)) - 2*a*m*(1 + sqrt(1 - a^2) + x)^4*
            (-48*I - 24*I*(1 + sqrt(1 - a^2) + x)*(-2 + lambda) + 
            4*I*(1 + sqrt(1 - a^2) + x)^2*(7*lambda + 2*lambda^2 + 6*I*omega) - 
            (1 + sqrt(1 - a^2) + x)^4*(12*lambda + lambda^2 - 24*I*omega)*omega + 
            4*I*(1 + sqrt(1 - a^2) + x)^5*lambda*omega^2 + 6*(1 + sqrt(1 - a^2) + x)^6*omega^3 - 
            4*I*(1 + sqrt(1 - a^2) + x)^3*(lambda + lambda^2 + 6*I*omega + 5*I*lambda*omega)) + 
            a^4*(1 + sqrt(1 - a^2) + x)^3*(24*m^4*(1 + sqrt(1 - a^2) + x) + 
            48*(-4 + 3*I*omega) + 8*(1 + sqrt(1 - a^2) + x)*(9 + lambda^2 + lambda*(2 + 13*I*omega) - 
            72*I*omega) - (1 + sqrt(1 - a^2) + x)^3*(60 + 54*lambda + lambda^2 + 36*I*omega)*omega^2 + 
            8*I*(1 + sqrt(1 - a^2) + x)^4*(-3 + 2*lambda)*omega^3 + 48*(1 + sqrt(1 - a^2) + x)^5*
            omega^4 + 8*(1 + sqrt(1 - a^2) + x)^2*omega*(24*I - 6*I*lambda - I*lambda^2 + 18*omega + 
            8*lambda*omega) + 4*m^2*(30 - (1 + sqrt(1 - a^2) + x)*(33 + 8*lambda + 54*I*omega) + 
            6*I*(1 + sqrt(1 - a^2) + x)^2*(5 + lambda)*omega + 45*(1 + sqrt(1 - a^2) + x)^3*
            omega^2)) + (1 + sqrt(1 - a^2) + x)^6*((-1 + sqrt(1 - a^2) + x)*
            (1 + sqrt(1 - a^2) + x)*lambda^3 + lambda^2*(12 - 12*(1 + sqrt(1 - a^2) + x) + 
            2*(1 + sqrt(1 - a^2) + x)^2 - (1 + sqrt(1 - a^2) + x)^4*omega^2) + 
            12*I*omega*(-12 + 8*(1 + sqrt(1 - a^2) + x) + (1 + sqrt(1 - a^2) + x)^4*omega^2) - 
            2*lambda*(-12 + 4*(1 + sqrt(1 - a^2) + x)*(2 - 3*I*omega) + 
            6*I*(1 + sqrt(1 - a^2) + x)^2*omega + (1 + sqrt(1 - a^2) + x)^4*omega^2)) + 
            a^2*(1 + sqrt(1 - a^2) + x)^4*(96 + 8*(1 + sqrt(1 - a^2) + x)*
            (m^2*(6 + 8*lambda) - 3*(2 + lambda^2 + lambda*(2 + 2*I*omega) - 22*I*omega)) - 96*I*omega + 
            2*(1 + sqrt(1 - a^2) + x)^4*(6 + 24*m^2 - 12*lambda - lambda^2 + 24*I*omega)*omega^2 + 
            8*I*(1 + sqrt(1 - a^2) + x)^5*(-3 + lambda)*omega^3 + 12*(1 + sqrt(1 - a^2) + x)^6*
            omega^4 + (1 + sqrt(1 - a^2) + x)^2*(lambda^3 + lambda*(24 - 34*m^2 - 4*I*omega) + 
            lambda^2*(14 - m^2 + 16*I*omega) - 12*I*(22 + 3*m^2 - 4*I*omega)*omega) + 
            8*(1 + sqrt(1 - a^2) + x)^3*omega*((-I)*lambda^2 + 2*I*m^2*(3 + lambda) + 3*omega + 
            lambda*(2*I + 5*omega)))))/((1 + sqrt(1 - a^2) + x)^2*
            ((-(1 + sqrt(1 - a^2) + x)^4)*(2*lambda + lambda^2 - 12*I*omega) + 
            24*a^3*m*(1 + sqrt(1 - a^2) + x)*(I - 2*(1 + sqrt(1 - a^2) + x)*omega) - 
            4*a*m*(1 + sqrt(1 - a^2) + x)^2*(6*I + 2*I*(1 + sqrt(1 - a^2) + x)*lambda + 
            3*(1 + sqrt(1 - a^2) + x)^2*omega) + 12*a^4*(-1 - 2*I*(1 + sqrt(1 - a^2) + x)*
            omega + 2*(1 + sqrt(1 - a^2) + x)^2*omega^2) + 4*a^2*(1 + sqrt(1 - a^2) + x)*
            (6 + (1 + sqrt(1 - a^2) + x)*(-3 + 6*m^2 + 6*I*omega) + 
            2*I*(1 + sqrt(1 - a^2) + x)^2*(-3 + lambda)*omega + 3*(1 + sqrt(1 - a^2) + x)^3*
            omega^2))))))
        end
    else
        throw(DomainError(s, "Currently only spin weight s of 0, +/-1, +/-2 are supported"))
    end
end

function ingoing_coefficient_at_hor(
    s::Int, m::Int, a, omega, lambda, order::Int;
    data_type=_DEFAULTDATATYPE,
)
    key = _legacy_series_key(
        s, m, a, omega, lambda, HORIZON_INGOING_SERIES, order, data_type
    )
    return build_asymptotic_series(key).coefficients[order + 1]
end

end
