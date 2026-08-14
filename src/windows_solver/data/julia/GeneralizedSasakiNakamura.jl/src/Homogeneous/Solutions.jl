module Solutions

using DifferentialEquations
using ForwardDiff
using HypergeometricFunctions
using StaticArrays
using ..Kerr
using ..Transformation
using ..Coordinates
using ..Potentials
using ..AsymptoticExpansionCoefficients
using ..InitialConditions
using ..FactoredSolutions
using ..ConversionFactors

export CommonCarrierHorizonBasis
export BasisSolveDiagnostics, ScatteringCoefficients
export ScatteringFailureReason, ScatteringExtractionError
export INVALID_SCATTERING_INPUT, SCATTERING_PRECISION_MISMATCH
export NONFINITE_SCATTERING_DATA, SCATTERING_BASIS_ILL_CONDITIONED
export SCATTERING_CHART_ILL_CONDITIONED
export build_common_horizon_basis
export solve_scaled_factored_scattering
export unscaled_cramer_scattering_coefficients
export ScatteringChartErrorInputs, DeterminantChartAssessment
export DeterminantChartEvaluation
export estimate_cref_error, raw_scattering_determinant
export assess_horizon_determinant_chart
export evaluate_normalised_horizon_determinant
export HOMOGENEOUS_REPRESENTATION_ID, SCATTERING_EXTRACTION_ID
export HORIZON_DETERMINANT_CHART_ID, BASIS_CONDITION_ESTIMATE_KIND
export CREF_ERROR_ESTIMATE_KIND, SCATTERING_CHART_SAFETY_FACTOR

const I = 1im # Mathematica being Mathematica
_DEFAULTDATATYPE = ComplexF64 # Double precision by default
_DEFAULTSOLVER = AutoVern9(Rosenbrock23(autodiff=false))
_DEFAULTTOLERANCE = 1e-12

const HOMOGENEOUS_REPRESENTATION_ID = "factored-plane-wave-gsn/v1"
const SCATTERING_EXTRACTION_ID = "scaled-factored-horizon-basis/v1"
const HORIZON_DETERMINANT_CHART_ID =
    "cinc-over-cref-minus-reflectivity/v1"
const BASIS_CONDITION_ESTIMATE_KIND =
    "scaled-basis-frobenius-condition/not-a-bound/v1"
const CREF_ERROR_ESTIMATE_KIND = "empirical-cref-error/not-a-bound/v1"
const SCATTERING_CHART_SAFETY_FACTOR = 64

@enum ScatteringFailureReason begin
    INVALID_SCATTERING_INPUT = 1
    SCATTERING_PRECISION_MISMATCH = 2
    NONFINITE_SCATTERING_DATA = 3
    SCATTERING_BASIS_ILL_CONDITIONED = 4
    SCATTERING_CHART_ILL_CONDITIONED = 5
end

struct ScatteringExtractionError{D} <: Exception
    reason::ScatteringFailureReason
    precision_bits::Int
    message::String
    diagnostics::D
end

function Base.showerror(io::IO, error::ScatteringExtractionError)
    print(
        io,
        string(error.reason),
        ": ",
        error.message,
        " (precision_bits=",
        error.precision_bits,
        ")",
    )
end

function _scattering_error(
    reason::ScatteringFailureReason,
    precision_bits::Int,
    message::AbstractString;
    diagnostics=nothing,
)
    return ScatteringExtractionError(
        reason, precision_bits, String(message), diagnostics
    )
end

function _with_scattering_precision(
    operation::F, ::Type{BigFloat}, precision_bits::Int
) where {F}
    precision_bits > 0 || throw(_scattering_error(
        SCATTERING_PRECISION_MISMATCH,
        precision_bits,
        "scattering precision_bits must be positive",
    ))
    return setprecision(BigFloat, precision_bits) do
        operation()
    end
end

function _with_scattering_precision(
    operation::F, ::Type{T}, precision_bits::Int
) where {F,T<:AbstractFloat}
    precision(T) == precision_bits || throw(_scattering_error(
        SCATTERING_PRECISION_MISMATCH,
        precision_bits,
        "fixed-width scattering type disagrees with originating precision",
    ))
    return operation()
end

_finite_scattering_complex(value::Complex) =
    isfinite(real(value)) && isfinite(imag(value))

function _assert_scattering_real(
    value::T,
    precision_bits::Int,
    name::AbstractString;
    nonnegative::Bool=false,
    positive::Bool=false,
) where {T<:AbstractFloat}
    isfinite(value) || throw(_scattering_error(
        NONFINITE_SCATTERING_DATA,
        precision_bits,
        "$name is nonfinite",
    ))
    precision(value) == precision_bits || throw(_scattering_error(
        SCATTERING_PRECISION_MISMATCH,
        precision_bits,
        "$name precision differs from the originating scattering request",
    ))
    nonnegative && value < zero(T) && throw(_scattering_error(
        INVALID_SCATTERING_INPUT,
        precision_bits,
        "$name must be nonnegative",
    ))
    positive && value <= zero(T) && throw(_scattering_error(
        INVALID_SCATTERING_INPUT,
        precision_bits,
        "$name must be strictly positive",
    ))
    return value
end

function _assert_scattering_complex(
    value::Complex{T}, precision_bits::Int, name::AbstractString
) where {T<:AbstractFloat}
    _finite_scattering_complex(value) || throw(_scattering_error(
        NONFINITE_SCATTERING_DATA,
        precision_bits,
        "$name is nonfinite",
    ))
    (precision(real(value)) == precision_bits &&
     precision(imag(value)) == precision_bits) || throw(_scattering_error(
        SCATTERING_PRECISION_MISMATCH,
        precision_bits,
        "$name precision differs from the originating scattering request",
    ))
    return value
end

function _assert_scattering_state(
    state::FactoredEndpointState{T},
    precision_bits::Int,
    name::AbstractString,
) where {T<:AbstractFloat}
    _assert_scattering_complex(state.Y, precision_bits, "$name Y")
    _assert_scattering_complex(state.Yrho, precision_bits, "$name Yrho")
    return state
end

function _canonical_remainder_contract(contract::RegularRemainderContract)
    return contract.identity == regular_remainder_contract &&
        contract.scattering_columns == scattering_column_convention &&
        contract.radial_derivative == radial_derivative_convention &&
        contract.determinant == determinant_convention &&
        contract.factored_state == factored_remainder_state_convention
end

function _same_remainder_contract(
    left::RegularRemainderContract, right::RegularRemainderContract
)
    return left.identity == right.identity &&
        left.scattering_columns == right.scattering_columns &&
        left.radial_derivative == right.radial_derivative &&
        left.determinant == right.determinant &&
        left.factored_state == right.factored_state
end

function _same_spectral_endpoint_key(left::SeriesKey, right::SeriesKey)
    return left.s == right.s &&
        left.m == right.m &&
        isequal(left.a, right.a) &&
        isequal(left.omega, right.omega) &&
        isequal(left.lambda, right.lambda) &&
        left.max_order == right.max_order &&
        left.precision_bits == right.precision_bits
end

function _same_carrier(left::PlaneWaveCarrier, right::PlaneWaveCarrier)
    return left.kind == right.kind &&
        isequal(left.wave_number, right.wave_number) &&
        isequal(left.rstar_match, right.rstar_match) &&
        isequal(left.log_at_match, right.log_at_match) &&
        isequal(left.q, right.q) &&
        full_convention_equal(left.convention, right.convention)
end

function _assert_scattering_carrier(
    carrier::PlaneWaveCarrier{T},
    precision_bits::Int,
    name::AbstractString,
) where {T<:AbstractFloat}
    _assert_scattering_complex(
        carrier.wave_number, precision_bits, "$name wave number"
    )
    _assert_scattering_complex(
        carrier.log_at_match, precision_bits, "$name log at match"
    )
    _assert_scattering_complex(carrier.q, precision_bits, "$name q")
    _assert_scattering_real(
        carrier.rstar_match, precision_bits, "$name rstar match"
    )
    for (field_name, value) in (
        ("infinity contour angle", carrier.convention.infinity_contour_angle),
        ("horizon contour angle", carrier.convention.horizon_contour_angle),
        ("omega argument", carrier.convention.omega_argument),
        ("horizon-wave-number argument", carrier.convention.p_horizon_argument),
    )
        _assert_scattering_real(
            value, precision_bits, "$name $field_name"
        )
    end
    branch_cell(carrier.convention).version == GSN_BRANCH_CONVENTION_ID ||
        throw(_scattering_error(
            INVALID_SCATTERING_INPUT,
            precision_bits,
            "$name does not use the canonical GSN branch identity",
        ))
    carrier.convention.tortoise_branch_id == GSN_TORTOISE_BRANCH_ID &&
        carrier.convention.infinity_carrier_id == GSN_INFINITY_CARRIER_ID &&
        carrier.convention.horizon_ingoing_carrier_id ==
            GSN_HORIZON_INGOING_CARRIER_ID &&
        carrier.convention.horizon_outgoing_carrier_id ==
            GSN_HORIZON_OUTGOING_CARRIER_ID || throw(_scattering_error(
                INVALID_SCATTERING_INPUT,
                precision_bits,
                "$name convention identities are not canonical",
            ))
    leg = if carrier.kind === INFINITY_OUTGOING
        :infinity
    elseif carrier.kind === HORIZON_INGOING ||
            carrier.kind === HORIZON_OUTGOING
        :horizon
    else
        throw(_scattering_error(
            INVALID_SCATTERING_INPUT,
            precision_bits,
            "$name has an unsupported carrier kind",
        ))
    end
    try
        assert_wave_number_matches_leg(
            carrier.wave_number, carrier.convention, leg
        )
    catch error
        error isa ArgumentError || rethrow()
        throw(_scattering_error(
            INVALID_SCATTERING_INPUT,
            precision_bits,
            "$name wave number disagrees with its coordinate-bound leg: " *
                sprint(showerror, error),
        ))
    end
    iszero(carrier.wave_number) && throw(_scattering_error(
        SCATTERING_BASIS_ILL_CONDITIONED,
        precision_bits,
        "$name wave number is zero",
    ))
    canonical_carrier = try
        PlaneWaveCarrier(
            carrier.kind,
            carrier.wave_number,
            carrier.rstar_match,
            carrier.convention,
        )
    catch error
        error isa ArgumentError || rethrow()
        throw(_scattering_error(
            INVALID_SCATTERING_INPUT,
            precision_bits,
            "$name cannot be reconstructed from the canonical carrier contract: " *
                sprint(showerror, error),
        ))
    end
    _same_carrier(carrier, canonical_carrier) || throw(_scattering_error(
        INVALID_SCATTERING_INPUT,
        precision_bits,
        "$name q or match-point logarithm is not canonical",
    ))
    return carrier
end

struct CommonCarrierHorizonBasis{T<:AbstractFloat}
    column_1::FactoredEndpointState{T}
    column_2::FactoredEndpointState{T}
    common_carrier::PlaneWaveCarrier{T}
    outgoing_source_carrier::PlaneWaveCarrier{T}
    rho_endpoint::T
    r_endpoint::Complex{T}
    precision_bits::Int
    contract::RegularRemainderContract
    carrier_change::CarrierChangeDiagnostics{T}
end

function build_common_horizon_basis(
    ingoing::FactoredInitialCondition{T},
    outgoing::FactoredInitialCondition{T},
)::CommonCarrierHorizonBasis{T} where {T<:AbstractFloat}
    precision_bits = ingoing.evaluation.precision_bits
    return _with_scattering_precision(T, precision_bits) do
        ingoing.evaluation.family == HORIZON_INGOING_SERIES ||
            throw(_scattering_error(
                INVALID_SCATTERING_INPUT,
                precision_bits,
                "column 1 must use the horizon-ingoing asymptotic family",
            ))
        outgoing.evaluation.family == HORIZON_OUTGOING_SERIES ||
            throw(_scattering_error(
                INVALID_SCATTERING_INPUT,
                precision_bits,
                "column 2 must use the horizon-outgoing asymptotic family",
            ))
        ingoing.carrier.kind == HORIZON_INGOING ||
            throw(_scattering_error(
                INVALID_SCATTERING_INPUT,
                precision_bits,
                "column 1 carrier must be horizon ingoing (Cref)",
            ))
        outgoing.carrier.kind == HORIZON_OUTGOING ||
            throw(_scattering_error(
                INVALID_SCATTERING_INPUT,
                precision_bits,
                "column 2 carrier must be horizon outgoing (Cinc)",
            ))
        outgoing.evaluation.precision_bits == precision_bits ||
            throw(_scattering_error(
                SCATTERING_PRECISION_MISMATCH,
                precision_bits,
                "horizon basis endpoints have different originating precisions",
            ))
        ingoing.evaluation.order == outgoing.evaluation.order ||
            throw(_scattering_error(
                INVALID_SCATTERING_INPUT,
                precision_bits,
                "horizon basis endpoint evaluations use different selected orders",
            ))
        _same_spectral_endpoint_key(
            ingoing.evaluation.key, outgoing.evaluation.key
        ) || throw(_scattering_error(
            INVALID_SCATTERING_INPUT,
            precision_bits,
            "horizon basis endpoints do not share one spectral key and order",
        ))
        full_convention_equal(
            ingoing.carrier.convention, outgoing.carrier.convention
        ) || throw(_scattering_error(
            INVALID_SCATTERING_INPUT,
            precision_bits,
            "horizon basis endpoints do not share one sample-local convention",
        ))
        _canonical_remainder_contract(ingoing.contract) &&
            _canonical_remainder_contract(outgoing.contract) &&
            _same_remainder_contract(
                ingoing.contract, outgoing.contract
            ) || throw(_scattering_error(
                INVALID_SCATTERING_INPUT,
                precision_bits,
                "horizon basis endpoints do not share the canonical remainder contract",
            ))
        ingoing.regularity.branch == HORIZON_INGOING &&
            outgoing.regularity.branch == HORIZON_OUTGOING ||
            throw(_scattering_error(
                INVALID_SCATTERING_INPUT,
                precision_bits,
                "horizon endpoint regularity evidence has the wrong branch order",
            ))
        isequal(
            ingoing.regularity.rho_endpoint,
            outgoing.regularity.rho_endpoint,
        ) || throw(_scattering_error(
            INVALID_SCATTERING_INPUT,
            precision_bits,
            "horizon basis endpoints have different rho coordinates",
        ))
        isequal(
            ingoing.regularity.r_endpoint,
            outgoing.regularity.r_endpoint,
        ) || throw(_scattering_error(
            INVALID_SCATTERING_INPUT,
            precision_bits,
            "horizon basis endpoints have different radial coordinates",
        ))
        isequal(
            ingoing.carrier.rstar_match, outgoing.carrier.rstar_match
        ) && isequal(
            ingoing.carrier.wave_number, outgoing.carrier.wave_number
        ) || throw(_scattering_error(
            INVALID_SCATTERING_INPUT,
            precision_bits,
            "horizon basis carriers differ in match point or wave number",
        ))
        iszero(outgoing.carrier.q - ingoing.carrier.q) &&
            throw(_scattering_error(
                SCATTERING_BASIS_ILL_CONDITIONED,
                precision_bits,
                "horizon ingoing and outgoing carriers have coalesced",
            ))
        _assert_scattering_state(
            ingoing.state, precision_bits, "horizon-ingoing column"
        )
        _assert_scattering_state(
            outgoing.state, precision_bits, "horizon-outgoing source column"
        )
        _assert_scattering_carrier(
            ingoing.carrier, precision_bits, "horizon-ingoing carrier"
        )
        _assert_scattering_carrier(
            outgoing.carrier, precision_bits, "horizon-outgoing carrier"
        )
        _assert_scattering_real(
            ingoing.regularity.rho_endpoint,
            precision_bits,
            "horizon basis rho endpoint",
        )
        _assert_scattering_complex(
            ingoing.regularity.r_endpoint,
            precision_bits,
            "horizon basis radial endpoint",
        )
        ingoing.regularity.finite && outgoing.regularity.finite ||
            throw(_scattering_error(
                NONFINITE_SCATTERING_DATA,
                precision_bits,
                "horizon endpoint regularity evidence is not finite",
            ))
        for (prefix, evidence) in (
            ("horizon-ingoing", ingoing.regularity),
            ("horizon-outgoing", outgoing.regularity),
        )
            for (name, value) in (
                ("remainder norm", evidence.remainder_norm),
                ("remainder derivative norm", evidence.remainder_derivative_norm),
                ("carrier magnitude", evidence.carrier_magnitude),
                ("relative X reconstruction error", evidence.relative_X_reconstruction_error),
                ("relative Xrho reconstruction error", evidence.relative_Xrho_reconstruction_error),
                ("Xrho backward residual", evidence.Xrho_backward_residual),
                ("carrier operation scale", evidence.carrier_operation_scale),
                ("reconstruction tolerance", evidence.reconstruction_tolerance),
            )
                _assert_scattering_real(
                    value,
                    precision_bits,
                    "$prefix $name";
                    nonnegative=true,
                )
            end
            evidence.carrier_magnitude > zero(T) ||
                throw(_scattering_error(
                    NONFINITE_SCATTERING_DATA,
                    precision_bits,
                    "$prefix carrier magnitude must be nonzero",
                ))
            evidence.carrier_operation_scale >= one(T) ||
                throw(_scattering_error(
                    INVALID_SCATTERING_INPUT,
                    precision_bits,
                    "$prefix carrier operation scale must be at least one",
                ))
            evidence.reconstruction_tolerance > zero(T) ||
                throw(_scattering_error(
                    INVALID_SCATTERING_INPUT,
                    precision_bits,
                    "$prefix reconstruction tolerance must be positive",
                ))
            maximum_reconstruction_error = max(
                evidence.relative_X_reconstruction_error,
                evidence.Xrho_backward_residual,
            )
            maximum_reconstruction_error <= evidence.reconstruction_tolerance ||
                throw(_scattering_error(
                    INVALID_SCATTERING_INPUT,
                    precision_bits,
                    "$prefix endpoint reconstruction gate is not satisfied",
                    diagnostics=(
                        maximum_error=maximum_reconstruction_error,
                        tolerance=evidence.reconstruction_tolerance,
                    ),
                ))
        end
        isequal(ingoing.regularity.remainder_norm, abs(ingoing.state.Y)) &&
            isequal(
                ingoing.regularity.remainder_derivative_norm,
                abs(ingoing.state.Yrho),
            ) && isequal(
                outgoing.regularity.remainder_norm,
                abs(outgoing.state.Y),
            ) && isequal(
                outgoing.regularity.remainder_derivative_norm,
                abs(outgoing.state.Yrho),
            ) || throw(_scattering_error(
                INVALID_SCATTERING_INPUT,
                precision_bits,
                "horizon endpoint regularity norms do not match their states",
            ))

        rho_endpoint = ingoing.regularity.rho_endpoint
        column_2 = try
            change_carrier(
                outgoing.state,
                outgoing.carrier,
                ingoing.carrier,
                rho_endpoint,
            )
        catch error
            error isa ArgumentError || rethrow()
            detail = sprint(showerror, error)
            reason = occursin("nonfinite", detail) ||
                occursin("underflow", detail) ?
                NONFINITE_SCATTERING_DATA : INVALID_SCATTERING_INPUT
            throw(_scattering_error(
                reason,
                precision_bits,
                "horizon outgoing-to-ingoing carrier change failed: $detail",
            ))
        end
        carrier_change = try
            carrier_change_diagnostics(
                outgoing.state,
                column_2,
                outgoing.carrier,
                ingoing.carrier,
                rho_endpoint,
            )
        catch error
            error isa ArgumentError || rethrow()
            throw(_scattering_error(
                NONFINITE_SCATTERING_DATA,
                precision_bits,
                "horizon carrier-change diagnostics failed: " *
                sprint(showerror, error),
            ))
        end
        _assert_scattering_state(
            column_2, precision_bits, "common-carrier outgoing column"
        )
        for (name, value, nonnegative) in (
            ("carrier-change X error", carrier_change.X_reconstruction_error, true),
            ("carrier-change Xrho error", carrier_change.Xrho_reconstruction_error, true),
            ("carrier ratio magnitude", carrier_change.carrier_ratio_magnitude, true),
            ("carrier ratio phase", carrier_change.carrier_ratio_phase, false),
        )
            _assert_scattering_real(
                value, precision_bits, name; nonnegative=nonnegative
            )
        end
        carrier_change.carrier_ratio_magnitude > zero(T) ||
            throw(_scattering_error(
                NONFINITE_SCATTERING_DATA,
                precision_bits,
                "horizon carrier ratio magnitude must be nonzero",
            ))

        # TODO: [HUMAN MATH REVIEW REQUIRED — verify the branch-specific plane-wave carriers, the transformed complex-contour GSN equation, the carrier change at ρ=0, the factored horizon basis, and the Cinc/Cref determinant chart against the current GSN amplitude and branch conventions.]
        return CommonCarrierHorizonBasis{T}(
            ingoing.state,
            column_2,
            ingoing.carrier,
            outgoing.carrier,
            rho_endpoint,
            ingoing.regularity.r_endpoint,
            precision_bits,
            ingoing.contract,
            carrier_change,
        )
    end
end

function build_common_horizon_basis(
    ingoing::FactoredInitialCondition,
    outgoing::FactoredInitialCondition,
)
    throw(_scattering_error(
        SCATTERING_PRECISION_MISMATCH,
        ingoing.evaluation.precision_bits,
        "horizon initial conditions do not share one exact real component type",
    ))
end

struct BasisSolveDiagnostics{T<:AbstractFloat}
    precision_bits::Int
    condition_frobenius::T
    condition_estimate_kind::String
    backward_error::T
    matching_reconstruction_residual::T
    scaled_basis_determinant::Complex{T}
    scaled_basis_determinant_abs::T
    column_norm_1::T
    column_norm_2::T
    scaled_coefficient_1::Complex{T}
    scaled_coefficient_2::Complex{T}
    legacy_comparator_available::Bool
    legacy_comparator_failure_reason::Union{Nothing,ScatteringFailureReason}
    legacy_Cref::Union{Nothing,Complex{T}}
    legacy_Cinc::Union{Nothing,Complex{T}}
    legacy_relative_disagreement_cref::Union{Nothing,T}
    legacy_relative_disagreement_cinc::Union{Nothing,T}
    carrier_change_error::T
    extraction_id::String
    column_convention::String
    factored_state_convention::String
end

struct ScatteringCoefficients{T<:AbstractFloat}
    Cref::Complex{T}
    Cinc::Complex{T}
    reconstructed_endpoint::FactoredEndpointState{T}
    diagnostics::BasisSolveDiagnostics{T}
end

_state_norm(state::FactoredEndpointState) =
    hypot(abs(state.Y), abs(state.Yrho))

function _four_norm(a, b, c, d)
    return hypot(hypot(abs(a), abs(b)), hypot(abs(c), abs(d)))
end

function _relative_scattering_disagreement(
    left::Complex{T}, right::Complex{T}
) where {T<:AbstractFloat}
    scale = max(abs(left), abs(right), floatmin(T))
    return abs(left / scale - right / scale)
end

function _finite_scattering_ratio(
    numerator_terms::NTuple{2,T},
    denominator::T,
    precision_bits::Int,
    name::AbstractString,
) where {T<:AbstractFloat}
    for (term_index, numerator) in enumerate(numerator_terms)
        _assert_scattering_real(
            numerator,
            precision_bits,
            "$name numerator term $term_index";
            nonnegative=true,
        )
    end
    _assert_scattering_real(
        denominator, precision_bits, "$name denominator"; positive=true
    )
    scale = max(numerator_terms[1], numerator_terms[2], denominator)
    scaled_numerator = numerator_terms[1] / scale +
        numerator_terms[2] / scale
    scaled_denominator = denominator / scale
    ratio = scaled_numerator / scaled_denominator
    saturated = !isfinite(ratio) && !iszero(scaled_numerator)
    if saturated
        ratio = floatmax(T)
    end
    return (
        _assert_scattering_real(
            ratio, precision_bits, name; nonnegative=true
        ),
        saturated,
    )
end

function _stable_matrix_two_norm(a, b, c, d, precision_bits::Int)
    T = typeof(real(a))
    scale = max(abs(a), abs(b), abs(c), abs(d))
    _assert_scattering_real(scale, precision_bits, "basis matrix scale";
        positive=true)
    as = a / scale
    bs = b / scale
    cs = c / scale
    ds = d / scale
    trace_gram = abs2(as) + abs2(bs) + abs2(cs) + abs2(ds)
    determinant_abs = abs(as * ds - bs * cs)
    discriminant = max(
        zero(T),
        trace_gram^2 - T(4) * determinant_abs^2,
    )
    result = scale * sqrt(
        (trace_gram + sqrt(discriminant)) / T(2)
    )
    return _assert_scattering_real(
        result, precision_bits, "basis spectral norm"; positive=true
    )
end

function _scale_normalised_backward_error(
    residual_norm::T,
    basis_two_norm::T,
    coefficient_norm::T,
    target_norm::T,
    precision_bits::Int,
) where {T<:AbstractFloat}
    for (name, value) in (
        ("matching residual norm", residual_norm),
        ("basis spectral norm", basis_two_norm),
        ("scattering coefficient norm", coefficient_norm),
        ("scattering target norm", target_norm),
    )
        _assert_scattering_real(
            value, precision_bits, name; nonnegative=true
        )
    end
    basis_two_norm > zero(T) || throw(_scattering_error(
        SCATTERING_BASIS_ILL_CONDITIONED,
        precision_bits,
        "basis spectral norm must be strictly positive",
    ))

    scale = max(
        residual_norm,
        basis_two_norm,
        target_norm,
        floatmin(T),
    )
    scaled_denominator = (basis_two_norm / scale) * coefficient_norm +
        target_norm / scale
    _assert_scattering_real(
        scaled_denominator,
        precision_bits,
        "scale-normalised backward-error denominator";
        nonnegative=true,
    )
    backward_error = (residual_norm / scale) /
        max(scaled_denominator, floatmin(T))
    return _assert_scattering_real(
        backward_error,
        precision_bits,
        "basis backward error";
        nonnegative=true,
    )
end

function unscaled_cramer_scattering_coefficients(
    target::FactoredEndpointState{T},
    column_1::FactoredEndpointState{T},
    column_2::FactoredEndpointState{T},
    precision_bits::Int,
) where {T<:AbstractFloat}
    return _with_scattering_precision(T, precision_bits) do
        _assert_scattering_state(target, precision_bits, "Cramer target")
        _assert_scattering_state(column_1, precision_bits, "Cramer column 1")
        _assert_scattering_state(column_2, precision_bits, "Cramer column 2")
        determinant = column_1.Y * column_2.Yrho -
            column_2.Y * column_1.Yrho
        _assert_scattering_complex(
            determinant, precision_bits, "unscaled Cramer determinant"
        )
        iszero(determinant) && throw(_scattering_error(
            SCATTERING_BASIS_ILL_CONDITIONED,
            precision_bits,
            "unscaled Cramer comparator determinant is zero",
        ))
        Cref = (
            target.Y * column_2.Yrho - column_2.Y * target.Yrho
        ) / determinant
        Cinc = (
            column_1.Y * target.Yrho - target.Y * column_1.Yrho
        ) / determinant
        _assert_scattering_complex(Cref, precision_bits, "legacy Cref")
        _assert_scattering_complex(Cinc, precision_bits, "legacy Cinc")
        return (Cref=Cref, Cinc=Cinc, determinant=determinant)
    end
end

function unscaled_cramer_scattering_coefficients(
    target::FactoredEndpointState,
    column_1::FactoredEndpointState,
    column_2::FactoredEndpointState,
    precision_bits::Int,
)
    throw(_scattering_error(
        SCATTERING_PRECISION_MISMATCH,
        precision_bits,
        "unscaled Cramer inputs do not share one exact real component type",
    ))
end

function _solve_scaled_factored_scattering_unchecked(
    target::FactoredEndpointState{T},
    basis::CommonCarrierHorizonBasis{T},
)::ScatteringCoefficients{T} where {T<:AbstractFloat}
    precision_bits = basis.precision_bits
    return _with_scattering_precision(T, precision_bits) do
        _canonical_remainder_contract(basis.contract) ||
            throw(_scattering_error(
                INVALID_SCATTERING_INPUT,
                precision_bits,
                "scattering basis remainder contract is not canonical",
            ))
        basis.common_carrier.kind == HORIZON_INGOING &&
            basis.outgoing_source_carrier.kind == HORIZON_OUTGOING ||
            throw(_scattering_error(
                INVALID_SCATTERING_INPUT,
                precision_bits,
                "scattering basis carrier slots do not match Cref/Cinc order",
            ))
        _assert_scattering_carrier(
            basis.common_carrier, precision_bits, "common horizon carrier"
        )
        _assert_scattering_carrier(
            basis.outgoing_source_carrier,
            precision_bits,
            "outgoing source carrier",
        )
        full_convention_equal(
            basis.common_carrier.convention,
            basis.outgoing_source_carrier.convention,
        ) || throw(_scattering_error(
            INVALID_SCATTERING_INPUT,
            precision_bits,
            "scattering basis carriers do not share one convention",
        ))
        isequal(
            basis.common_carrier.wave_number,
            basis.outgoing_source_carrier.wave_number,
        ) && isequal(
            basis.common_carrier.rstar_match,
            basis.outgoing_source_carrier.rstar_match,
        ) || throw(_scattering_error(
            INVALID_SCATTERING_INPUT,
            precision_bits,
            "scattering basis carriers differ in match point or wave number",
        ))
        iszero(
            basis.outgoing_source_carrier.q - basis.common_carrier.q
        ) && throw(_scattering_error(
            SCATTERING_BASIS_ILL_CONDITIONED,
            precision_bits,
            "scattering basis horizon carriers have coalesced",
        ))
        _assert_scattering_real(
            basis.rho_endpoint, precision_bits, "scattering basis rho endpoint"
        )
        _assert_scattering_complex(
            basis.r_endpoint,
            precision_bits,
            "scattering basis radial endpoint",
        )
        for (name, value, nonnegative) in (
            ("basis carrier-change X error", basis.carrier_change.X_reconstruction_error, true),
            ("basis carrier-change Xrho error", basis.carrier_change.Xrho_reconstruction_error, true),
            ("basis carrier ratio magnitude", basis.carrier_change.carrier_ratio_magnitude, true),
            ("basis carrier ratio phase", basis.carrier_change.carrier_ratio_phase, false),
        )
            _assert_scattering_real(
                value, precision_bits, name; nonnegative=nonnegative
            )
        end
        basis.carrier_change.carrier_ratio_magnitude > zero(T) ||
            throw(_scattering_error(
                NONFINITE_SCATTERING_DATA,
                precision_bits,
                "scattering basis carrier ratio magnitude must be nonzero",
            ))
        _assert_scattering_state(target, precision_bits, "scattering target")
        _assert_scattering_state(
            basis.column_1, precision_bits, "scattering column 1"
        )
        _assert_scattering_state(
            basis.column_2, precision_bits, "scattering column 2"
        )
        column_norm_1 = _state_norm(basis.column_1)
        column_norm_2 = _state_norm(basis.column_2)
        for (name, value) in (
            ("column norm 1", column_norm_1),
            ("column norm 2", column_norm_2),
        )
            _assert_scattering_real(value, precision_bits, name;
                nonnegative=true)
            iszero(value) && throw(_scattering_error(
                SCATTERING_BASIS_ILL_CONDITIONED,
                precision_bits,
                "$name is zero",
                diagnostics=(column_norm_1=column_norm_1,
                    column_norm_2=column_norm_2),
            ))
        end

        scaled_a = basis.column_1.Y / column_norm_1
        scaled_c = basis.column_1.Yrho / column_norm_1
        scaled_b = basis.column_2.Y / column_norm_2
        scaled_d = basis.column_2.Yrho / column_norm_2
        for (name, value) in (
            ("scaled basis a", scaled_a),
            ("scaled basis b", scaled_b),
            ("scaled basis c", scaled_c),
            ("scaled basis d", scaled_d),
        )
            _assert_scattering_complex(value, precision_bits, name)
        end
        scaled_basis_determinant = scaled_a * scaled_d - scaled_b * scaled_c
        _assert_scattering_complex(
            scaled_basis_determinant,
            precision_bits,
            "scaled basis determinant",
        )
        scaled_basis_determinant_abs = abs(scaled_basis_determinant)
        scaled_basis_norm = _four_norm(
            scaled_a, scaled_b, scaled_c, scaled_d
        )
        scaled_adjugate_norm = _four_norm(
            scaled_d, -scaled_b, -scaled_c, scaled_a
        )
        resolution_floor = eps(T) * scaled_basis_norm *
            scaled_adjugate_norm
        for (name, value) in (
            ("scaled basis determinant magnitude", scaled_basis_determinant_abs),
            ("scaled basis Frobenius norm", scaled_basis_norm),
            ("scaled basis adjugate norm", scaled_adjugate_norm),
            ("scaled basis resolution floor", resolution_floor),
        )
            _assert_scattering_real(value, precision_bits, name;
                nonnegative=true)
        end
        failure_evidence = (
            column_norm_1=column_norm_1,
            column_norm_2=column_norm_2,
            scaled_basis_determinant_abs=scaled_basis_determinant_abs,
            resolution_floor=resolution_floor,
        )
        scaled_basis_determinant_abs > resolution_floor ||
            throw(_scattering_error(
                SCATTERING_BASIS_ILL_CONDITIONED,
                precision_bits,
                "scaled horizon basis determinant is arithmetically unresolved",
                diagnostics=failure_evidence,
            ))
        condition_frobenius = scaled_basis_norm *
            (scaled_adjugate_norm / scaled_basis_determinant_abs)
        _assert_scattering_real(
            condition_frobenius,
            precision_bits,
            "scaled Frobenius condition estimate";
            positive=true,
        )

        z1 = (target.Y * scaled_d - scaled_b * target.Yrho) /
            scaled_basis_determinant
        z2 = (scaled_a * target.Yrho - target.Y * scaled_c) /
            scaled_basis_determinant
        _assert_scattering_complex(z1, precision_bits, "scaled coefficient 1")
        _assert_scattering_complex(z2, precision_bits, "scaled coefficient 2")
        Cref = z1 / column_norm_1
        Cinc = z2 / column_norm_2
        _assert_scattering_complex(Cref, precision_bits, "Cref")
        _assert_scattering_complex(Cinc, precision_bits, "Cinc")

        legacy_comparator_failure_reason = nothing
        legacy_diagnostics = try
            legacy = unscaled_cramer_scattering_coefficients(
                target,
                basis.column_1,
                basis.column_2,
                precision_bits,
            )
            disagreement_cref = _relative_scattering_disagreement(
                Cref, legacy.Cref
            )
            disagreement_cinc = _relative_scattering_disagreement(
                Cinc, legacy.Cinc
            )
            _assert_scattering_real(
                disagreement_cref,
                precision_bits,
                "legacy Cref disagreement";
                nonnegative=true,
            )
            _assert_scattering_real(
                disagreement_cinc,
                precision_bits,
                "legacy Cinc disagreement";
                nonnegative=true,
            )
            (
                Cref=legacy.Cref,
                Cinc=legacy.Cinc,
                disagreement_cref=disagreement_cref,
                disagreement_cinc=disagreement_cinc,
            )
        catch error
            if error isa ScatteringExtractionError &&
                    (error.reason == NONFINITE_SCATTERING_DATA ||
                     error.reason == SCATTERING_BASIS_ILL_CONDITIONED)
                legacy_comparator_failure_reason = error.reason
                nothing
            else
                rethrow()
            end
        end
        legacy_comparator_available = legacy_diagnostics !== nothing
        legacy_Cref = legacy_diagnostics === nothing ? nothing :
            legacy_diagnostics.Cref
        legacy_Cinc = legacy_diagnostics === nothing ? nothing :
            legacy_diagnostics.Cinc
        legacy_relative_disagreement_cref =
            legacy_diagnostics === nothing ? nothing :
                legacy_diagnostics.disagreement_cref
        legacy_relative_disagreement_cinc =
            legacy_diagnostics === nothing ? nothing :
                legacy_diagnostics.disagreement_cinc

        reconstructed_endpoint = FactoredEndpointState{T}(
            z1 * scaled_a + z2 * scaled_b,
            z1 * scaled_c + z2 * scaled_d,
        )
        _assert_scattering_state(
            reconstructed_endpoint,
            precision_bits,
            "reconstructed scattering endpoint",
        )
        residual = FactoredEndpointState{T}(
            reconstructed_endpoint.Y - target.Y,
            reconstructed_endpoint.Yrho - target.Yrho,
        )
        residual_norm = _state_norm(residual)
        target_norm = _state_norm(target)
        coefficient_norm = hypot(abs(z1), abs(z2))
        basis_two_norm = _stable_matrix_two_norm(
            scaled_a,
            scaled_b,
            scaled_c,
            scaled_d,
            precision_bits,
        )
        tinyT = floatmin(T)
        matching_reconstruction_residual = residual_norm /
            max(target_norm, tinyT)
        backward_error = _scale_normalised_backward_error(
            residual_norm,
            basis_two_norm,
            coefficient_norm,
            target_norm,
            precision_bits,
        )
        carrier_change_error = max(
            basis.carrier_change.X_reconstruction_error,
            basis.carrier_change.Xrho_reconstruction_error,
        )
        for (name, value) in (
            ("matching reconstruction residual", matching_reconstruction_residual),
            ("basis backward error", backward_error),
            ("carrier-change error", carrier_change_error),
        )
            _assert_scattering_real(value, precision_bits, name;
                nonnegative=true)
        end
        diagnostics = BasisSolveDiagnostics{T}(
            precision_bits,
            condition_frobenius,
            BASIS_CONDITION_ESTIMATE_KIND,
            backward_error,
            matching_reconstruction_residual,
            scaled_basis_determinant,
            scaled_basis_determinant_abs,
            column_norm_1,
            column_norm_2,
            z1,
            z2,
            legacy_comparator_available,
            legacy_comparator_failure_reason,
            legacy_Cref,
            legacy_Cinc,
            legacy_relative_disagreement_cref,
            legacy_relative_disagreement_cinc,
            carrier_change_error,
            SCATTERING_EXTRACTION_ID,
            scattering_column_convention,
            factored_remainder_state_convention,
        )
        return ScatteringCoefficients{T}(
            Cref, Cinc, reconstructed_endpoint, diagnostics
        )
    end
end

function solve_scaled_factored_scattering(
    target::FactoredEndpointState{T},
    target_carrier::PlaneWaveCarrier{T},
    basis::CommonCarrierHorizonBasis{T},
) where {T<:AbstractFloat}
    return _with_scattering_precision(T, basis.precision_bits) do
        _assert_scattering_carrier(
            target_carrier,
            basis.precision_bits,
            "propagated scattering target carrier",
        )
        _same_carrier(target_carrier, basis.common_carrier) ||
            throw(_scattering_error(
                INVALID_SCATTERING_INPUT,
                basis.precision_bits,
                "propagated scattering target is not in the common horizon-ingoing carrier",
            ))
        return _solve_scaled_factored_scattering_unchecked(target, basis)
    end
end

function _solve_scaled_factored_scattering_unchecked(
    target::FactoredEndpointState,
    basis::CommonCarrierHorizonBasis,
)
    throw(_scattering_error(
        SCATTERING_PRECISION_MISMATCH,
        basis.precision_bits,
        "scattering target and basis do not share one exact real component type",
    ))
end

function solve_scaled_factored_scattering(
    target::FactoredEndpointState,
    target_carrier::PlaneWaveCarrier,
    basis::CommonCarrierHorizonBasis,
)
    throw(_scattering_error(
        SCATTERING_PRECISION_MISMATCH,
        basis.precision_bits,
        "scattering target, carrier, and basis do not share one exact real component type",
    ))
end

struct ScatteringChartErrorInputs{T<:AbstractFloat}
    coefficient_scale::T
    series_disagreement::T
    ode_relative_tolerance::T
end

struct DeterminantChartAssessment{T<:AbstractFloat}
    estimated_cref_error::T
    safety_factor::Int
    cref_chart_margin::T
    cref_fraction::T
    safe::Bool
    raw_determinant::Complex{T}
    normalised_determinant::Union{Nothing,Complex{T}}
    raw_determinant_abs::T
    normalised_determinant_abs::Union{Nothing,T}
    cref_abs::T
    cinc_abs::T
    raw_cancellation_ratio::T
    raw_cancellation_ratio_saturated::Bool
    equivalence_relative_error::Union{Nothing,T}
    homogeneous_representation::String
    branch_convention::String
    scattering_coefficient_extraction::String
    scattering_column_convention::String
    radial_derivative_convention::String
    determinant_convention::String
    regular_remainder_contract::String
    factored_remainder_state_convention::String
    horizon_determinant_chart::String
    error_estimate_kind::String
end

struct DeterminantChartEvaluation{T<:AbstractFloat}
    value::Complex{T}
    assessment::DeterminantChartAssessment{T}
end

function estimate_cref_error(
    coefficients::ScatteringCoefficients{T},
    inputs::ScatteringChartErrorInputs{T},
) where {T<:AbstractFloat}
    precision_bits = coefficients.diagnostics.precision_bits
    return _with_scattering_precision(T, precision_bits) do
        _assert_scattering_real(
            inputs.coefficient_scale,
            precision_bits,
            "Cref coefficient scale";
            positive=true,
        )
        _assert_scattering_real(
            inputs.series_disagreement,
            precision_bits,
            "series disagreement";
            nonnegative=true,
        )
        _assert_scattering_real(
            inputs.ode_relative_tolerance,
            precision_bits,
            "ODE relative tolerance";
            positive=true,
        )
        relative_error_scale = max(
            coefficients.diagnostics.backward_error,
            inputs.series_disagreement,
            coefficients.diagnostics.matching_reconstruction_residual,
            inputs.ode_relative_tolerance,
        )
        estimated_error = inputs.coefficient_scale *
            coefficients.diagnostics.condition_frobenius *
            relative_error_scale
        return _assert_scattering_real(
            estimated_error,
            precision_bits,
            "empirical Cref error";
            positive=true,
        )
    end
end

function estimate_cref_error(
    coefficients::ScatteringCoefficients,
    inputs::ScatteringChartErrorInputs,
)
    throw(_scattering_error(
        SCATTERING_PRECISION_MISMATCH,
        coefficients.diagnostics.precision_bits,
        "Cref-error inputs do not share one exact real component type",
    ))
end

function raw_scattering_determinant(
    coefficients::ScatteringCoefficients{T},
    reflectivity::Union{T,Complex{T}},
) where {T<:AbstractFloat}
    precision_bits = coefficients.diagnostics.precision_bits
    return _with_scattering_precision(T, precision_bits) do
        typed_reflectivity = _assert_scattering_complex(
            Complex{T}(reflectivity), precision_bits, "reflectivity"
        )
        value = coefficients.Cinc - typed_reflectivity * coefficients.Cref
        return _assert_scattering_complex(
            value, precision_bits, "raw scattering determinant"
        )
    end
end

function raw_scattering_determinant(
    coefficients::ScatteringCoefficients,
    reflectivity::Number,
)
    throw(_scattering_error(
        SCATTERING_PRECISION_MISMATCH,
        coefficients.diagnostics.precision_bits,
        "raw determinant inputs do not share one exact real component type",
    ))
end

function assess_horizon_determinant_chart(
    coefficients::ScatteringCoefficients{T},
    reflectivity::Union{T,Complex{T}},
    estimated_cref_error::T,
)::DeterminantChartAssessment{T} where {T<:AbstractFloat}
    precision_bits = coefficients.diagnostics.precision_bits
    return _with_scattering_precision(T, precision_bits) do
        _assert_scattering_real(
            estimated_cref_error,
            precision_bits,
            "empirical Cref error";
            positive=true,
        )
        typed_reflectivity = _assert_scattering_complex(
            Complex{T}(reflectivity), precision_bits, "reflectivity"
        )
        Cref = _assert_scattering_complex(
            coefficients.Cref, precision_bits, "chart Cref"
        )
        Cinc = _assert_scattering_complex(
            coefficients.Cinc, precision_bits, "chart Cinc"
        )
        raw_determinant = Cinc - typed_reflectivity * Cref
        _assert_scattering_complex(
            raw_determinant, precision_bits, "raw determinant evidence"
        )
        cref_abs = abs(Cref)
        cinc_abs = abs(Cinc)
        denominator = T(SCATTERING_CHART_SAFETY_FACTOR) *
            estimated_cref_error
        _assert_scattering_real(
            denominator, precision_bits, "Cref chart safety denominator";
            positive=true,
        )
        margin = cref_abs / denominator
        _assert_scattering_real(
            margin, precision_bits, "Cref chart margin"; nonnegative=true
        )
        coefficient_pair_norm = hypot(cref_abs, cinc_abs)
        _assert_scattering_real(
            coefficient_pair_norm,
            precision_bits,
            "scattering coefficient-pair norm";
            nonnegative=true,
        )
        cref_fraction = cref_abs / max(coefficient_pair_norm, floatmin(T))
        safe = !iszero(Cref) && margin > one(T)
        normalised_determinant = iszero(Cref) ? nothing :
            Cinc / Cref - typed_reflectivity
        if normalised_determinant !== nothing
            _assert_scattering_complex(
                normalised_determinant,
                precision_bits,
                "normalised scattering determinant",
            )
        end
        raw_determinant_abs = abs(raw_determinant)
        normalised_determinant_abs = normalised_determinant === nothing ?
            nothing : abs(normalised_determinant)
        reflected_cref_abs = abs(typed_reflectivity * Cref)
        raw_cancellation_ratio, raw_cancellation_ratio_saturated =
            _finite_scattering_ratio(
                (cinc_abs, reflected_cref_abs),
                max(raw_determinant_abs, floatmin(T)),
                precision_bits,
                "raw determinant cancellation ratio",
            )
        equivalence_relative_error = if normalised_determinant === nothing
            nothing
        else
            reconstructed_raw = Cref * normalised_determinant
            _relative_scattering_disagreement(
                raw_determinant, reconstructed_raw
            )
        end
        for (name, value) in (
            ("Cref magnitude", cref_abs),
            ("Cinc magnitude", cinc_abs),
            ("Cref fraction", cref_fraction),
            ("raw determinant magnitude", raw_determinant_abs),
            ("raw cancellation ratio", raw_cancellation_ratio),
        )
            _assert_scattering_real(value, precision_bits, name;
                nonnegative=true)
        end
        normalised_determinant_abs === nothing ||
            _assert_scattering_real(
                normalised_determinant_abs,
                precision_bits,
                "normalised determinant magnitude";
                nonnegative=true,
            )
        equivalence_relative_error === nothing ||
            _assert_scattering_real(
                equivalence_relative_error,
                precision_bits,
                "raw/normalised determinant equivalence error";
                nonnegative=true,
            )
        return DeterminantChartAssessment{T}(
            estimated_cref_error,
            SCATTERING_CHART_SAFETY_FACTOR,
            margin,
            cref_fraction,
            safe,
            raw_determinant,
            normalised_determinant,
            raw_determinant_abs,
            normalised_determinant_abs,
            cref_abs,
            cinc_abs,
            raw_cancellation_ratio,
            raw_cancellation_ratio_saturated,
            equivalence_relative_error,
            HOMOGENEOUS_REPRESENTATION_ID,
            GSN_BRANCH_CONVENTION_ID,
            SCATTERING_EXTRACTION_ID,
            scattering_column_convention,
            radial_derivative_convention,
            determinant_convention,
            regular_remainder_contract,
            factored_remainder_state_convention,
            HORIZON_DETERMINANT_CHART_ID,
            CREF_ERROR_ESTIMATE_KIND,
        )
    end
end

function assess_horizon_determinant_chart(
    coefficients::ScatteringCoefficients,
    reflectivity::Number,
    estimated_cref_error::Real,
)
    throw(_scattering_error(
        SCATTERING_PRECISION_MISMATCH,
        coefficients.diagnostics.precision_bits,
        "determinant-chart inputs do not share one exact real component type",
    ))
end

function assess_horizon_determinant_chart(
    coefficients::ScatteringCoefficients{T},
    reflectivity::Union{T,Complex{T}},
    inputs::ScatteringChartErrorInputs{T},
) where {T<:AbstractFloat}
    estimated_error = estimate_cref_error(coefficients, inputs)
    return assess_horizon_determinant_chart(
        coefficients, reflectivity, estimated_error
    )
end


function assess_horizon_determinant_chart(
    coefficients::ScatteringCoefficients,
    reflectivity::Number,
    inputs::ScatteringChartErrorInputs,
)
    throw(_scattering_error(
        SCATTERING_PRECISION_MISMATCH,
        coefficients.diagnostics.precision_bits,
        "determinant-chart inputs do not share one exact real component type",
    ))
end

function evaluate_normalised_horizon_determinant(
    coefficients::ScatteringCoefficients{T},
    reflectivity::Union{T,Complex{T}},
    estimated_cref_error::T,
)::DeterminantChartEvaluation{T} where {T<:AbstractFloat}
    assessment = assess_horizon_determinant_chart(
        coefficients, reflectivity, estimated_cref_error
    )
    assessment.safe || throw(_scattering_error(
        SCATTERING_CHART_ILL_CONDITIONED,
        coefficients.diagnostics.precision_bits,
        "Cref does not satisfy the strict factor-64 normalised-chart margin",
        diagnostics=assessment,
    ))
    assessment.normalised_determinant === nothing && throw(
        _scattering_error(
            SCATTERING_CHART_ILL_CONDITIONED,
            coefficients.diagnostics.precision_bits,
            "safe normalised chart unexpectedly lacks a determinant value",
            diagnostics=assessment,
        )
    )
    return DeterminantChartEvaluation{T}(
        assessment.normalised_determinant, assessment
    )
end

function evaluate_normalised_horizon_determinant(
    coefficients::ScatteringCoefficients,
    reflectivity::Number,
    estimated_cref_error::Real,
)
    throw(_scattering_error(
        SCATTERING_PRECISION_MISMATCH,
        coefficients.diagnostics.precision_bits,
        "normalised determinant inputs do not share one exact real component type",
    ))
end

function evaluate_normalised_horizon_determinant(
    coefficients::ScatteringCoefficients{T},
    reflectivity::Union{T,Complex{T}},
    inputs::ScatteringChartErrorInputs{T},
) where {T<:AbstractFloat}
    estimated_error = estimate_cref_error(coefficients, inputs)
    return evaluate_normalised_horizon_determinant(
        coefficients, reflectivity, estimated_error
    )
end


function evaluate_normalised_horizon_determinant(
    coefficients::ScatteringCoefficients,
    reflectivity::Number,
    inputs::ScatteringChartErrorInputs,
)
    throw(_scattering_error(
        SCATTERING_PRECISION_MISMATCH,
        coefficients.diagnostics.precision_bits,
        "normalised determinant inputs do not share one exact real component type",
    ))
end

# First-order non-linear ODE form of the GSN equation
function GSN_Riccati_eqn(u, p, rs)
    r = r_from_rstar(p.a, rs)
    _sF = sF(p.s, p.m, p.a, p.omega, p.lambda, r)
    _sU = sU(p.s, p.m, p.a, p.omega, p.lambda, r)
    
    #=
    We write X = exp(I*Phi)
    Substitute X in this form into the GSN equation will give
    a Riccati equation, a first-order non-linear equation

    u[1] = Phi
    u[2] = dPhidrs
    =#
    return SA[u[2], -1im*_sU + _sF*u[2] - 1im*u[2]*u[2]]
end

# Second-order linear ODE form of the GSN equation
function GSN_linear_eqn(u, p, rs)
    r = r_from_rstar(p.a, rs)
    _sF = sF(p.s, p.m, p.a, p.omega, p.lambda, r)
    _sU = sU(p.s, p.m, p.a, p.omega, p.lambda, r)

    #=
    Using the convention for DifferentialEquations
    u[1] = X(rs)
    u[2] = dX/drs = X'
    therefore
    X'' - sF X' - sU X = 0 => u[2]' - sF u[2] - sU u[1] = 0 => u[2]' = sF u[2] + sU u[1]
    =#
    return SA[u[2], _sF*u[2] + _sU*u[1]]
end

function PhiPhiprime_from_XXprime(X, Xprime)
    Phi = -1im*log(X)
    Phiprime = -1im*Xprime/X

    return Phi, Phiprime
end

function XXprime_from_PhiPhiprime(Phi, Phiprime)
    X = exp(1im*Phi)
    Xprime = 1im*X*Phiprime

    return X, Xprime
end

function Xsoln_from_Phisoln(Phisoln)
    return rs -> XXprime_from_PhiPhiprime(Phisoln(rs)[1], Phisoln(rs)[2])
end

function solve_Phiup(s::Int, m::Int, a, omega, lambda, rsin, rsout; initialconditions_order=-1, dtype=_DEFAULTDATATYPE, odealgo=_DEFAULTSOLVER, reltol=_DEFAULTTOLERANCE, abstol=_DEFAULTTOLERANCE)
    # Sanity check
    if rsin > rsout
        throw(DomainError(rsout, "rsout ($rsout) must be larger than rsin ($rsin)"))
    end
    maxiters = min(50 * floor(rsout - rsin), 1e5)
    # Initial conditions at rs = rsout, the outer boundary
    Xup_rsout, Xupprime_rsout = Xup_initialconditions(s, m, a, omega, lambda, rsout; order=initialconditions_order, dtype=dtype)
    # Convert initial conditions for Xup for Phi
    Phi, Phiprime = PhiPhiprime_from_XXprime(Xup_rsout, Xupprime_rsout)
    u0 = SA[dtype(Phi); dtype(Phiprime)]
    rsspan = (rsout, rsin) # Integrate from rsout to rsin *inward*
    p = (s=s, m=m, a=a, omega=omega, lambda=lambda)
    odeprob = ODEProblem(GSN_Riccati_eqn, u0, rsspan, p)
    odesoln = solve(odeprob, odealgo; reltol=reltol, abstol=abstol, maxiters=maxiters)
    return odesoln
end

function solve_Phiin(s::Int, m::Int, a, omega, lambda, rsin, rsout; initialconditions_order=-1, dtype=_DEFAULTDATATYPE, odealgo=_DEFAULTSOLVER, reltol=_DEFAULTTOLERANCE, abstol=_DEFAULTTOLERANCE)
    # Sanity check
    if rsin > rsout
        throw(DomainError(rsin, "rsin ($rsin) must be smaller than rsout ($rsout)"))
    end
    maxiters = min(50 * floor(rsout - rsin), 1e5) 
    # Initial conditions at rs = rsin, the inner boundary; this should be very close to EH
    Xin_rsin, Xinprime_rsin = Xin_initialconditions(s, m, a, omega, lambda, rsin; order=initialconditions_order, dtype=dtype)
    # Convert initial conditions for Xin for PhiRe PhiIm
    Phi, Phiprime = PhiPhiprime_from_XXprime(Xin_rsin, Xinprime_rsin)
    u0 = SA[dtype(Phi); dtype(Phiprime)]
    rsspan = (rsin, rsout) # Integrate from rsin to rsout *outward*
    p = (s=s, m=m, a=a, omega=omega, lambda=lambda)
    odeprob = ODEProblem(GSN_Riccati_eqn, u0, rsspan, p)
    odesoln = solve(odeprob, odealgo; reltol=reltol, abstol=abstol, maxiters=maxiters)
    return odesoln
end

function solve_Xup(s::Int, m::Int, a, omega, lambda, rsin, rsout; initialconditions_order=-1, dtype=_DEFAULTDATATYPE, odealgo=_DEFAULTSOLVER, reltol=_DEFAULTTOLERANCE, abstol=_DEFAULTTOLERANCE)
    # Sanity check
    if rsin > rsout
        throw(DomainError(rsout, "rsout ($rsout) must be larger than rsin ($rsin)"))
    end
    maxiters = min(50 * floor(rsout - rsin), 1e5)
    # Initial conditions at rs = rsout, the outer boundary
    Xup_rsout, Xupprime_rsout = Xup_initialconditions(s, m, a, omega, lambda, rsout; order=initialconditions_order, dtype=dtype)
    u0 = SA[dtype(Xup_rsout); dtype(Xupprime_rsout)]
    rsspan = (rsout, rsin) # Integrate from rsout to rsin *inward*
    p = (s=s, m=m, a=a, omega=omega, lambda=lambda)
    odeprob = ODEProblem(GSN_linear_eqn, u0, rsspan, p)
    odesoln = solve(odeprob, odealgo; reltol=reltol, abstol=abstol, maxiters=maxiters)
    return odesoln
end

function solve_Xin(s::Int, m::Int, a, omega, lambda, rsin, rsout; initialconditions_order=-1, dtype=_DEFAULTDATATYPE, odealgo=_DEFAULTSOLVER, reltol=_DEFAULTTOLERANCE, abstol=_DEFAULTTOLERANCE)
    # Sanity check
    if rsin > rsout
        throw(DomainError(rsin, "rsin ($rsin) must be smaller than rsout ($rsout)"))
    end
    maxiters = min(50 * floor(rsout - rsin), 1e5)
    # Initial conditions at rs = rsin, the inner boundary; this should be very close to EH
    Xin_rsin, Xinprime_rsin = Xin_initialconditions(s, m, a, omega, lambda, rsin; order=initialconditions_order, dtype=dtype)
    u0 = SA[dtype(Xin_rsin); dtype(Xinprime_rsin)]
    rsspan = (rsin, rsout) # Integrate from rsin to rsout *outward*
    p = (s=s, m=m, a=a, omega=omega, lambda=lambda)
    odeprob = ODEProblem(GSN_linear_eqn, u0, rsspan, p)
    odesoln = solve(odeprob, odealgo; reltol=reltol, abstol=abstol, maxiters=maxiters)
    return odesoln
end

function Teukolsky_radial_function_from_Sasaki_Nakamura_function_conversion_matrix(s, m, a, omega, lambda, r)
    #=
    Here we use explicit form for the conversion matrix to
    faciliate cancellations
    =#
    M11 = M12 = M21 = M22 = 0.0
    if s == 0
        M11 = 1/sqrt(a^2 + r^2)
        M21 = -(r/(a^2 + r^2)^(3/2))
        M22 = sqrt(a^2 + r^2)/(a^2 + (-2 + r)*r)
    elseif s == +1
        M11 = begin
            -((I*r*sqrt((a^2 + r^2)/(a^2 + (-2 + r)*r))*
            ((-a^3)*m*r - a*m*r^3 + r^5*omega + 
            a^4*(2*I + r*omega) + 2*a^2*r*(-2*I + I*r + 
            r^2*omega)))/(sqrt(a^2 + r^2)*
            sqrt((a^2 + (-2 + r)*r)*(a^2 + r^2))*
            (-2*I*a^3*m*r - 2*I*a*m*r^3 + a^4*(1 + lambda) + 
            r^4*(2 + lambda) + a^2*r*(2 + r*(3 + 2*lambda)))))
        end
        M12 = begin
            (r^2*(a^2 + r^2)^(3/2)*
            sqrt((a^2 + r^2)/(a^2 + (-2 + r)*r)))/
            (sqrt((a^2 + (-2 + r)*r)*(a^2 + r^2))*
            (-2*I*a^3*m*r - 2*I*a*m*r^3 + a^4*(1 + lambda) + 
            r^4*(2 + lambda) + a^2*r*(2 + r*(3 + 2*lambda))))
        end
        M21 = begin
            -((r*sqrt((a^2 + r^2)/(a^2 + (-2 + r)*r))*
            (-2*a^7*m*(I + r*omega) + a^8*omega*(2*I + r*omega) + 
            a^5*m*r*(2*I - I*r - 6*r^2*omega) + 
            a*m*r^5*(-4*I + 3*I*r - 2*r^2*omega) - 
            2*a^3*m*r^3*(I - 2*I*r + 3*r^2*omega) + 
            r^6*(2*(2 + lambda) - r*(2 + lambda) - I*r^2*omega + 
            r^3*omega^2) + a^6*(-4 + r*(1 + m^2 - lambda - 
            2*I*omega) + 5*I*r^2*omega + 4*r^3*omega^2) + 
            a^2*r^3*(4 + 4*r*lambda + r^2*(-3 + m^2 - 3*lambda - 
            2*I*omega) - I*r^3*omega + 4*r^4*omega^2) + 
            a^4*r*(8 + 2*r*(-4 + lambda) + 
            r^2*(2*m^2 - 3*lambda - 4*I*omega) + 3*I*r^3*omega + 
            6*r^4*omega^2)))/(sqrt(a^2 + r^2)*
            ((a^2 + (-2 + r)*r)*(a^2 + r^2))^(3/2)*
            (-2*I*a^3*m*r - 2*I*a*m*r^3 + a^4*(1 + lambda) + 
            r^4*(2 + lambda) + a^2*r*(2 + r*(3 + 2*lambda)))))
        end
        M22 = begin
            -((I*r^2*((a^2 + r^2)/(a^2 + (-2 + r)*r))^(3/2)*
            ((-a^3)*m - a*m*r^2 + a^4*omega + r^3*(-I + r*omega) + 
            a^2*(2*I - I*r + 2*r^2*omega)))/
            (sqrt(a^2 + r^2)*sqrt((a^2 + (-2 + r)*r)*
            (a^2 + r^2))*(-2*I*a^3*m*r - 2*I*a*m*r^3 + 
            a^4*(1 + lambda) + r^4*(2 + lambda) + 
            a^2*r*(2 + r*(3 + 2*lambda)))))
        end
    elseif s == -1
        M11 = begin
            (I*r*sqrt(a^2 + r^2)*((-a^3)*m*r - a*m*r^3 + 
            r^5*omega + a^4*(-2*I + r*omega) + 
            2*a^2*r*(2*I - I*r + r^2*omega)))/
            (sqrt((a^2 + r^2)/(a^2 + (-2 + r)*r))*
            sqrt((a^2 + (-2 + r)*r)*(a^2 + r^2))*
            (2*I*a^3*m*r + 2*I*a*m*r^3 + a^4*(-1 + lambda) + 
            r^4*lambda + a^2*r*(2 + r*(-1 + 2*lambda))))
        end
        M12 = begin
            (r^2*sqrt(a^2 + r^2)*sqrt((a^2 + r^2)/
            (a^2 + (-2 + r)*r))*sqrt((a^2 + (-2 + r)*r)*
            (a^2 + r^2)))/(2*I*a^3*m*r + 2*I*a*m*r^3 + 
            a^4*(-1 + lambda) + r^4*lambda + 
            a^2*r*(2 + r*(-1 + 2*lambda)))
        end
        M21 = begin
            (r*sqrt((a^2 + r^2)/(a^2 + (-2 + r)*r))*
            (a^8*omega*(2*I - r*omega) + 2*a^7*m*(-I + r*omega) + 
            a*m*r^5*(-2*I + I*r + 2*r^2*omega) + 
            2*a^3*m*r^3*(I + 3*r^2*omega) + 
            a^5*m*r*(4*I - 3*I*r + 6*r^2*omega) + 
            a^6*r*(1 - m^2 + lambda - 4*I*omega + 7*I*r*omega - 
            4*r^2*omega^2) - a^4*r^2*(2*(2 + lambda) + 
            r*(-2 + 2*m^2 - 3*lambda + 10*I*omega) - 9*I*r^2*omega + 
            6*r^3*omega^2) + a^2*r^3*(4 - 4*r*(1 + lambda) - 
            r^2*(-1 + m^2 - 3*lambda + 8*I*omega) + 5*I*r^3*omega - 
            4*r^4*omega^2) + r^6*((-2 + r)*lambda - 
            r*omega*(2*I - I*r + r^2*omega))))/
            ((a^2 + r^2)^(3/2)*sqrt((a^2 + (-2 + r)*r)*
            (a^2 + r^2))*(2*I*a^3*m*r + 2*I*a*m*r^3 + 
            a^4*(-1 + lambda) + r^4*lambda + 
            a^2*r*(2 + r*(-1 + 2*lambda))))
        end
        M22 = begin
            -((r^2*sqrt((a^2 + r^2)/(a^2 + (-2 + r)*r))*
            sqrt((a^2 + (-2 + r)*r)*(a^2 + r^2))*
            (-r - (I*(a^2 + r^2)*((-a)*m + (a^2 + r^2)*omega))/
            (a^2 + (-2 + r)*r)))/(sqrt(a^2 + r^2)*
            (2*I*a^3*m*r + 2*I*a*m*r^3 + a^4*(-1 + lambda) + 
            r^4*lambda + a^2*r*(2 + r*(-1 + 2*lambda)))))
        end
    elseif s == +2
        M11 = begin
            (r^2*(a^2 + (-2 + r)*r)*(-4*a^5*m*r*(I + r*omega) - 
            2*a^3*m*r^2*(-3*I + 2*I*r + 4*r^2*omega) + 
            a*m*(2*I*r^4 - 4*r^6*omega) + 
            2*a^6*(-5 + 2*I*r*omega + r^2*omega^2) + 
            a^4*r*(32 + r*(-24 + 2*m^2 - lambda - 6*I*omega) + 
            10*I*r^2*omega + 6*r^3*omega^2) + 
            r^4*(-12 + 2*r*(9 + lambda) - 
            r^2*(6 + lambda + 6*I*omega) + 2*I*r^3*omega + 
            2*r^4*omega^2) + 2*a^2*r^2*(-12 + r*(23 + lambda) + 
            r^2*(-10 + m^2 - lambda - 6*I*omega) + 4*I*r^3*omega + 
            3*r^4*omega^2)))/
            (((a^2 + (-2 + r)*r)^2*(a^2 + r^2))^(3/2)*
            ((-r^4)*(24 + 10*lambda + lambda^2 + 12*I*omega) - 
            24*a^3*m*r*(I + 2*r*omega) + 4*a*m*r^2*
            (6*I + 2*I*r*(4 + lambda) - 3*r^2*omega) + 
            12*a^4*(-1 + 2*I*r*omega + 2*r^2*omega^2) + 
            4*a^2*r*(6 + r*(-3 + 6*m^2 - 6*I*omega) - 
            2*I*r^2*(1 + lambda)*omega + 3*r^3*omega^2)))
        end
        M12 = begin
            (2*r^3*(a^2 + (-2 + r)*r)*(a^2 + r^2)^2*
            ((-I)*a*m*r + a^2*(-2 + I*r*omega) + 
            r*(3 - r + I*r^2*omega)))/
            (((a^2 + (-2 + r)*r)^2*(a^2 + r^2))^(3/2)*
            ((-r^4)*(24 + 10*lambda + lambda^2 + 12*I*omega) - 
            24*a^3*m*r*(I + 2*r*omega) + 4*a*m*r^2*
            (6*I + 2*I*r*(4 + lambda) - 3*r^2*omega) + 
            12*a^4*(-1 + 2*I*r*omega + 2*r^2*omega^2) + 
            4*a^2*r*(6 + r*(-3 + 6*m^2 - 6*I*omega) - 
            2*I*r^2*(1 + lambda)*omega + 3*r^3*omega^2)))
        end
        M21 = begin
            -((I*r*(-2*a^7*m*r*(-2 + 4*I*r*omega + 3*r^2*omega^2) - 
            2*a^5*m*r^2*(-4 + r*(3 + m^2 - lambda + 2*I*omega) + 
            4*I*r^2*omega + 9*r^3*omega^2) + 
            2*a*m*r^5*(-10 + r*(3 - 2*lambda) + 
            r^2*(2 + lambda + 2*I*omega) + 4*I*r^3*omega - 
            3*r^4*omega^2) - 2*a^3*m*r^3*
            (12 + r^2*(3 + m^2 - 2*lambda) + r*(-17 + 2*lambda) - 
            4*I*r^3*omega + 9*r^4*omega^2) + 
            2*a^8*(-6*I - 2*r*omega + 2*I*r^2*omega^2 + 
            r^3*omega^3) + 2*a^6*r*(16*I + 
            I*r*(-9 + 2*m^2 - 2*lambda + 4*I*omega) + 
            r^2*(-8 + 3*m^2 - lambda + I*omega)*omega + 
            6*I*r^3*omega^2 + 4*r^4*omega^3) + 
            r^6*(-4*I*lambda - 2*r^3*(4 + lambda + 5*I*omega)*omega + 
            2*r^5*omega^3 - 12*r*(I + omega) + 
            r^2*(6*I + I*lambda + 18*omega + 4*lambda*omega)) + 
            a^4*r^2*(-16*I + 2*I*r*(10 + m^2 + 6*lambda - 
            12*I*omega) + 2*r^3*(-14 + 6*m^2 - 3*lambda - 
            3*I*omega)*omega + 12*I*r^4*omega^2 + 12*r^5*omega^3 + 
            r^2*(-2*I - 4*I*m^2 - 7*I*lambda + 22*omega + 
            4*lambda*omega)) + 2*a^2*r^4*(-4*I*lambda + 
            I*r*(-4 + 3*m^2 + 6*lambda + 6*I*omega) + 
            3*r^3*(-4 + m^2 - lambda - 3*I*omega)*omega + 
            2*I*r^4*omega^2 + 4*r^5*omega^3 + 
            r^2*(5*I - 4*I*m^2 - I*lambda + 24*omega + 
            4*lambda*omega))))/
            (((a^2 + (-2 + r)*r)^2*(a^2 + r^2))^(3/2)*
            ((-r^4)*(24 + 10*lambda + lambda^2 + 12*I*omega) - 
            24*a^3*m*r*(I + 2*r*omega) + 4*a*m*r^2*
            (6*I + 2*I*r*(4 + lambda) - 3*r^2*omega) + 
            12*a^4*(-1 + 2*I*r*omega + 2*r^2*omega^2) + 
            4*a^2*r*(6 + r*(-3 + 6*m^2 - 6*I*omega) - 
            2*I*r^2*(1 + lambda)*omega + 3*r^3*omega^2))))
        end
        M22 = begin
            (r^2*(a^2 + r^2)^2*(-4*a^3*m*r*(I + r*omega) - 
            2*a*m*r^2*(I - 3*I*r + 2*r^2*omega) + 
            2*a^4*(-3 + 2*I*r*omega + r^2*omega^2) + 
            r^3*(2*lambda - r*(2 + lambda + 10*I*omega) + 2*r^3*omega^2) + 
            a^2*r*(8 + 2*m^2*r - r*lambda + 2*I*r*omega + 
            4*I*r^2*omega + 4*r^3*omega^2)))/
            (((a^2 + (-2 + r)*r)^2*(a^2 + r^2))^(3/2)*
            ((-r^4)*(24 + 10*lambda + lambda^2 + 12*I*omega) - 
            24*a^3*m*r*(I + 2*r*omega) + 4*a*m*r^2*
            (6*I + 2*I*r*(4 + lambda) - 3*r^2*omega) + 
            12*a^4*(-1 + 2*I*r*omega + 2*r^2*omega^2) + 
            4*a^2*r*(6 + r*(-3 + 6*m^2 - 6*I*omega) - 
            2*I*r^2*(1 + lambda)*omega + 3*r^3*omega^2)))
        end
    elseif s == -2
        M11 = begin
            (r^2*(-4*a^5*m*r*(-I + r*omega) - 
            2*a*m*r^4*(I + 2*r^2*omega) - 2*a^3*m*r^2*
            (3*I - 2*I*r + 4*r^2*omega) + 
            2*a^6*(-5 - 2*I*r*omega + r^2*omega^2) + 
            a^4*r*(32 + r*(-20 + 2*m^2 - lambda + 6*I*omega) - 
            10*I*r^2*omega + 6*r^3*omega^2) + 
            r^4*(-12 + 2*r*(5 + lambda) - 
            r^2*(2 + lambda - 6*I*omega) - 2*I*r^3*omega + 
            2*r^4*omega^2) + 2*a^2*r^2*(-12 + r*(19 + lambda) + 
            r^2*(-6 + m^2 - lambda + 6*I*omega) - 4*I*r^3*omega + 
            3*r^4*omega^2)))/((a^2 + (-2 + r)*r)^3*
            ((a^2 + r^2)/(a^2 + (-2 + r)*r)^2)^(3/2)*
            ((-r^4)*(2*lambda + lambda^2 - 12*I*omega) + 
            24*a^3*m*r*(I - 2*r*omega) - 4*a*m*r^2*
            (6*I + 2*I*r*lambda + 3*r^2*omega) + 
            12*a^4*(-1 - 2*I*r*omega + 2*r^2*omega^2) + 
            4*a^2*r*(6 + r*(-3 + 6*m^2 + 6*I*omega) + 
            2*I*r^2*(-3 + lambda)*omega + 3*r^3*omega^2)))
        end
        M12 = begin
            (2*r^3*(a^2 + (-2 + r)*r)*
            sqrt((a^2 + r^2)/(a^2 + (-2 + r)*r)^2)*
            (I*a*m*r + a^2*(-2 - I*r*omega) + 
            r*(3 - r - I*r^2*omega)))/
            ((-r^4)*(2*lambda + lambda^2 - 12*I*omega) + 
            24*a^3*m*r*(I - 2*r*omega) - 
            4*a*m*r^2*(6*I + 2*I*r*lambda + 3*r^2*omega) + 
            12*a^4*(-1 - 2*I*r*omega + 2*r^2*omega^2) + 
            4*a^2*r*(6 + r*(-3 + 6*m^2 + 6*I*omega) + 
            2*I*r^2*(-3 + lambda)*omega + 3*r^3*omega^2))
        end
        M21 = begin
            (I*r*sqrt((a^2 + r^2)/(a^2 + (-2 + r)*r)^2)*
            (2*a^7*m*r*(2 + 4*I*r*omega - 3*r^2*omega^2) - 
            2*a^5*m*r^2*(4 + r*(-1 + m^2 - lambda + 6*I*omega) - 
            12*I*r^2*omega + 9*r^3*omega^2) - 
            2*a^3*m*r^4*(-5 + 2*lambda + r*(3 + m^2 - 2*lambda + 
            16*I*omega) - 12*I*r^2*omega + 9*r^3*omega^2) - 
            2*a*m*r^5*(6 + r*(-7 + 2*lambda) + 
            r^2*(2 - lambda + 10*I*omega) - 4*I*r^3*omega + 
            3*r^4*omega^2) + 2*a^8*(6*I - 2*r*omega - 
            2*I*r^2*omega^2 + r^3*omega^3) + 
            2*a^6*r*(-36*I + r^2*(-12 + 3*m^2 - lambda + 3*I*omega)*
            omega - 10*I*r^3*omega^2 + 4*r^4*omega^3 + 
            r*(21*I - 2*I*m^2 + 2*I*lambda + 4*omega)) + 
            r^5*(-48*I + 12*I*r*(6 + lambda) - 
            12*I*r^2*(3 + lambda - 3*I*omega) - 
            2*r^4*(4 + lambda - 9*I*omega)*omega - 8*I*r^5*omega^2 + 
            2*r^6*omega^3 + r^3*(6*I + 3*I*lambda + 34*omega + 
            4*lambda*omega)) + 2*a^2*r^3*(-48*I + 
            4*I*r*(27 + 2*lambda) + I*r^2*(-72 + m^2 - 14*lambda + 
            30*I*omega) + r^4*(-16 + 3*m^2 - 3*lambda + 
            21*I*omega)*omega - 14*I*r^5*omega^2 + 4*r^6*omega^3 + 
            r^3*(15*I + 5*I*lambda + 48*omega + 4*lambda*omega)) + 
            a^4*r^2*(144*I + 2*I*r*(-90 + 3*m^2 - 8*lambda) + 
            2*r^3*(-22 + 6*m^2 - 3*lambda + 15*I*omega)*omega - 
            36*I*r^4*omega^2 + 12*r^5*omega^3 + 
            r^2*(54*I - 4*I*m^2 + 11*I*lambda + 70*omega + 
            4*lambda*omega))))/((a^2 + r^2)^2*
            ((-r^4)*(2*lambda + lambda^2 - 12*I*omega) + 
            24*a^3*m*r*(I - 2*r*omega) - 4*a*m*r^2*
            (6*I + 2*I*r*lambda + 3*r^2*omega) + 
            12*a^4*(-1 - 2*I*r*omega + 2*r^2*omega^2) + 
            4*a^2*r*(6 + r*(-3 + 6*m^2 + 6*I*omega) + 
            2*I*r^2*(-3 + lambda)*omega + 3*r^3*omega^2)))
        end
        M22 = begin
            (r^2*sqrt((a^2 + r^2)/(a^2 + (-2 + r)*r)^2)*
            (-4*a^3*m*r*(-I + r*omega) - 2*a*m*r^2*
            (3*I - I*r + 2*r^2*omega) + 
            2*a^4*(-3 - 2*I*r*omega + r^2*omega^2) + 
            a^2*r*(24 + r*(-12 + 2*m^2 - lambda + 6*I*omega) - 
            12*I*r^2*omega + 4*r^3*omega^2) + 
            r^2*(-24 + 2*r*(12 + lambda) - 
            r^2*(6 + lambda - 18*I*omega) - 8*I*r^3*omega + 
            2*r^4*omega^2)))/
            ((-r^4)*(2*lambda + lambda^2 - 12*I*omega) + 
            24*a^3*m*r*(I - 2*r*omega) - 
            4*a*m*r^2*(6*I + 2*I*r*lambda + 3*r^2*omega) + 
            12*a^4*(-1 - 2*I*r*omega + 2*r^2*omega^2) + 
            4*a^2*r*(6 + r*(-3 + 6*m^2 + 6*I*omega) + 
            2*I*r^2*(-3 + lambda)*omega + 3*r^3*omega^2))
        end
    else
        # Throw an error, this spin weight is not supported
        throw(DomainError(s, "Currently only spin weight s of 0, +/-1, +/-2 are supported"))
    end 
    return SA[M11 M12; M21 M22]
end

function Teukolsky_radial_function_from_Sasaki_Nakamura_function(s::Int, m::Int, a, omega, lambda, Xsoln)
    #=
    First convert [X(rs), dX/drs(rs)] to [X(r), dX/dr(r)], this is done by
    [X(r), dX/dr(r)]^T = [1, 0; 0, drstar/dr ] * [X(rs), dX/drs(rs)]^T

    Then we convert [X(r), dX/dr(r)] to [chi(r), dchi/dr(r)] by
    [chi(r), dchi/dr(r)]^T = [chi_conversion_factor(r), 0 ; dchi_conversion_factor_dr, chi_conversion_factor] * [X(r), dX/dr(r)]^T

    After that we convert [chi(r), dchi/dr(r)] to [R(r), dR/dr(r)] by
    [R(r), dR/dr(r)]^T = 1/eta(r) * [ alpha + beta_prime*Delta^(s+1), -beta*Delta^(s+1) ; -(alpha_prime + beta*VT*Delta^s), alpha ] *  [chi(r), dchi/dr(r)]^T

    Therefore the overall conversion matrix is 'just' (one matrix for each r)
    the multiplication of each conversion matrix
    =#

    overall_conversion_matrix(r) = Teukolsky_radial_function_from_Sasaki_Nakamura_function_conversion_matrix(s, m, a, omega, lambda, r)
    X(rs) = Xsoln(rs)[1]
    Xprime(rs) = Xsoln(rs)[2]
    Rsoln = (r -> overall_conversion_matrix(r) * SA[X(rstar_from_r(a, r)); Xprime(rstar_from_r(a, r))])
    return Rsoln
end

function Sasaki_Nakamura_function_from_Teukolsky_radial_function(s::Int, m::Int, a, omega, lambda, Rsoln)
    #=
    Teukolsky_radial_function_from_Sasaki_Nakamura_function_conversion_matrix() returns 
    the conversion matrix for going from (X, dX/drs) to (R, dR/dr). Here we need
    the inverse of that to go from (R, dR/dr) to (X, dX/drs).
    =#
    conversion_matrix(r) = inv(Teukolsky_radial_function_from_Sasaki_Nakamura_function_conversion_matrix(s, m, a, omega, lambda, r))

    Xsoln(rs) = begin
        r = r_from_rstar(a, rs)
        conversion_matrix(r) * Rsoln(r)
    end

    return Xsoln
end

function d2Rdr2_from_Rsoln(s::Int, m::Int, a, omega, lambda, Rsoln, r)
    #=
    Using the radial Teukolsky equation we can solve for d2Rdr2 from R and dRdr using

        d2Rdr2 = VT/\Delta R - (2(s+1)(r-M))/\Delta dRdr
    =#
    # NOTE DO NOT USE THE DOT PRODUCT IN LINEAR ALGEBRA
    R, dRdr = Rsoln(r)
    return (VT(s, m, a, omega, lambda, r)/Delta(a, r))*R - ((2*(s+1)*(r-1))/Delta(a,r))*dRdr
end

function scaled_Wronskian_Teukolsky(Rin_soln, Rup_soln, r, s, a)
    # The scaled Wronskian is given by W = Delta^{s+1} * det([Rin Rup; Rin' Rup'])
    Rin, Rin_prime = Rin_soln(r)
    Rup, Rup_prime = Rup_soln(r)
    return Delta(a, r)^(s+1) * (Rin*Rup_prime - Rup*Rin_prime)
end

function scaled_Wronskian_GSN(Xin_soln, Xup_soln, rs, s, m, a, omega, lambda)
    r = r_from_rstar(a, rs)
    Xin, dXindrs = Xin_soln(rs)
    Xup, dXupdrs = Xup_soln(rs)
    _eta = eta(s, m, a, omega, lambda, r)

    return (Xin*dXupdrs - dXindrs*Xup)/_eta
end

function scaled_Wronskian_from_Phisolns(Phiin_soln, Phiup_soln, rs, s, m, a, omega, lambda)
    r = r_from_rstar(a, rs)
    Xin = exp(1im*Phiin_soln(rs)[1])
    dXindrs = 1im*exp(1im*Phiinsoln(rs)[1])*Phiinsoln(rs)[2]
    Xup = exp(1im*Phiup_soln(rs)[1])
    dXupdrs = 1im*exp(1im*Phiupsoln(rs)[1])*Phiupsoln(rs)[2]
    _eta = eta(s, m, a, omega, lambda, r)

    return (Xin*dXupdrs - dXindrs*Xup)/_eta
end

function residual_from_Xsoln(s::Int, m::Int, a, omega, lambda, Xsoln)
    # Compute the second derivative using autodiff instead of finite diff
    X(rs) = Xsoln(rs)[1]
    first_deriv(rs) = Xsoln(rs)[2]
    second_deriv(rs) = ForwardDiff.derivative(first_deriv, rs)

    _sF(rs) = sF(s, m, a, omega, lambda, r_from_rstar(a, rs))
    _sU(rs) = sU(s, m, a, omega, lambda, r_from_rstar(a, rs))

    return rs -> second_deriv(rs) - _sF(rs)*first_deriv(rs) - _sU(rs)*X(rs)
end

function residual_RiccatiEqn_from_Phisoln(s::Int, m::Int, a, omega, lambda, Phisoln)
    Phi(rs) = Phisoln(rs)[1] # Does not matter actually!
    first_deriv(rs) = Phisoln(rs)[2]
    second_deriv(rs) = ForwardDiff.derivative(first_deriv, rs)

    _sF(rs) = sF(s, m, a, omega, lambda, r_from_rstar(a, rs))
    _sU(rs) = sU(s, m, a, omega, lambda, r_from_rstar(a, rs))

    return rs -> second_deriv(rs) + 1im*_sU(rs) - _sF(rs)*first_deriv(rs) + 1im*(first_deriv(rs))^2
end

function residual_GSNEqn_from_Phisoln(s::Int, m::Int, a, omega, lambda, Phisoln)
    # Compute the second derivative using autodiff instead of finite diff
    X = (rs -> exp(1im*Phisoln(rs)[1]))
    first_deriv = (rs -> 1im*exp(1im*Phisoln(rs)[1])*Phisoln(rs)[2])
    second_deriv(rs) = ForwardDiff.derivative(first_deriv, rs)

    _sF(rs) = sF(s, m, a, omega, lambda, r_from_rstar(a, rs))
    _sU(rs) = sU(s, m, a, omega, lambda, r_from_rstar(a, rs))

    return rs -> second_deriv(rs) - _sF(rs)*first_deriv(rs) - _sU(rs)*X(rs)
end

function CrefCinc_SN_from_Xup(s::Int, m::Int, a, omega, lambda, Xupsoln, rsin; order=0, dtype=_DEFAULTDATATYPE)
    p = omega - m*omega_horizon(a)

    rin = r_from_rstar(a, rsin)
    # Computing A1, A2, A3, A4
    gin(r) = gansatz(
        ord -> ingoing_coefficient_at_hor(s, m, a, omega, lambda, ord; data_type=dtype),
        a,
        r;
        order=order
    )
    dgin_dr(r) = dgansatz_dr(
        ord -> ingoing_coefficient_at_hor(s, m, a, omega, lambda, ord; data_type=dtype),
        a,
        r;
        order=order
    )
    A1 = gin(rin) * exp(-1im*p*rsin)
    gout(r) = gansatz(
        ord -> outgoing_coefficient_at_hor(s, m, a, omega, lambda, ord; data_type=dtype),
        a,
        r;
        order=order
    )
    dgout_dr(r) = dgansatz_dr(
        ord -> outgoing_coefficient_at_hor(s, m, a, omega, lambda, ord; data_type=dtype),
        a,
        r;
        order=order
    )
    A2 = gout(rin) * exp(1im*p*rsin)

    _DeltaOverr2pa2 = Delta(a, rin)/(rin^2 + a^2)
    A3 = (_DeltaOverr2pa2 * dgin_dr(rin) - 1im*p*gin(rin)) * exp(-1im*p*rsin)
    A4 = (_DeltaOverr2pa2 * dgout_dr(rin) + 1im*p*gout(rin)) * exp(1im*p*rsin)

    X(rs) = Xupsoln(rs)[1]
    Xprime(rs) = Xupsoln(rs)[2]
    C1 = X(rsin)
    C2 = Xprime(rsin)

    return -(A4*C1 - A2*C2)/(A2*A3 - A1*A4), -(-A3*C1 + A1*C2)/(A2*A3 - A1*A4)
end

function BrefBinc_SN_from_Xin(s::Int, m::Int, a, omega, lambda, Xinsoln, rsout; order=3, dtype=_DEFAULTDATATYPE)
    rout = r_from_rstar(a, rsout)
    # Computing A1, A2, A3, A4
    fin(r) = fansatz(
        ord -> ingoing_coefficient_at_inf(s, m, a, omega, lambda, ord; data_type=dtype),
        omega,
        r;
        order=order
    )
    dfin_dr(r) = dfansatz_dr(
        ord -> ingoing_coefficient_at_inf(s, m, a, omega, lambda, ord; data_type=dtype),
        omega,
        r;
        order=order
    )
    A1 = fin(rout) * exp(-1im*omega*rsout)
    fout(r) = fansatz(
        ord -> outgoing_coefficient_at_inf(s, m, a, omega, lambda, ord; data_type=dtype),
        omega,
        r;
        order=order
    )
    dfout_dr(r) = dfansatz_dr(
        ord -> outgoing_coefficient_at_inf(s, m, a, omega, lambda, ord; data_type=dtype),
        omega,
        r;
        order=order
    )
    A2 = fout(rout) * exp(1im*omega*rsout)

    _DeltaOverr2pa2 = Delta(a, rout)/(rout^2 + a^2)
    A3 = (_DeltaOverr2pa2 * dfin_dr(rout) - 1im*omega*fin(rout)) * exp(-1im*omega*rsout)
    A4 = (_DeltaOverr2pa2 * dfout_dr(rout) + 1im*omega*fout(rout)) * exp(1im*omega*rsout)

    X(rs) = Xinsoln(rs)[1]
    Xprime(rs) = Xinsoln(rs)[2]
    C1 = X(rsout)
    C2 = Xprime(rsout)

    return -(-A3*C1 + A1*C2)/(A2*A3 - A1*A4), -(A4*C1 - A2*C2)/(A2*A3 - A1*A4)
end

function semianalytical_Xin(s, m, a, omega, lambda, Xinsoln, rsin, rsout, horizon_expansionorder, infinity_expansionorder, rs; dtype=_DEFAULTDATATYPE)
    _r = r_from_rstar(a, rs) # Evaluate at this r

    if rs < rsin
        # Extend the numerical solution to the analytical ansatz from rsin to horizon

        # Construct the analytical ansatz
        p = omega - m*omega_horizon(a)
        gin(r) = gansatz(
            ord -> ingoing_coefficient_at_hor(s, m, a, omega, lambda, ord; data_type=dtype),
            a,
            r;
            order=horizon_expansionorder
        )
        dgin_dr(r) = dgansatz_dr(
            ord -> ingoing_coefficient_at_hor(s, m, a, omega, lambda, ord; data_type=dtype),
            a,
            r;
            order=horizon_expansionorder
        )

        _Xin = gin(_r)*exp(-1im*p*rs) # Evaluate at *this* rs

        _DeltaOverr2pa2 = Delta(a, _r)/(_r^2 + a^2)
        _dXindrs = (_DeltaOverr2pa2 * dgin_dr(_r) - 1im*p*gin(_r))*exp(-1im*p*rs)

        return (_Xin, _dXindrs)
    elseif rs > rsout
        # Extend the numerical solution to the analytical ansatz from rsout to infinity

        # Obtain the coefficients by imposing continuity in X and dX/drs
        Bref_SN, Binc_SN = BrefBinc_SN_from_Xin(s, m, a, omega, lambda, Xinsoln, rsout; order=infinity_expansionorder, dtype=dtype)

        # Construct the analytical ansatz
        fin(r) = fansatz(
            ord -> ingoing_coefficient_at_inf(s, m, a, omega, lambda, ord; data_type=dtype),
            omega,
            r;
            order=infinity_expansionorder
        )
        dfin_dr(r) = dfansatz_dr(
            ord -> ingoing_coefficient_at_inf(s, m, a, omega, lambda, ord; data_type=dtype),
            omega,
            r;
            order=infinity_expansionorder
        )
        fout(r) = fansatz(
            ord -> outgoing_coefficient_at_inf(s, m, a, omega, lambda, ord; data_type=dtype),
            omega,
            r;
            order=infinity_expansionorder
        )
        dfout_dr(r) = dfansatz_dr(
            ord -> outgoing_coefficient_at_inf(s, m, a, omega, lambda, ord; data_type=dtype),
            omega,
            r;
            order=infinity_expansionorder
        )

        _Xin = Bref_SN*fout(_r)*exp(1im*omega*rs) + Binc_SN*fin(_r)*exp(-1im*omega*rs)

        _DeltaOverr2pa2 = Delta(a, _r)/(_r^2 + a^2)
        _dXindrs = Bref_SN*(_DeltaOverr2pa2 * dfout_dr(_r) + 1im*omega*fout(_r))*exp(1im*omega*rs) + Binc_SN*(_DeltaOverr2pa2 * dfin_dr(_r) - 1im*omega*fin(_r))*exp(-1im*omega*rs)
        
        return (_Xin, _dXindrs)
    else
        # Requested rs is within the numerical solution
        return Xinsoln(rs)
    end 
end

function semianalytical_Xup(s, m, a, omega, lambda, Xupsoln, rsin, rsout, horizon_expansionorder, infinity_expansionorder, rs; dtype=_DEFAULTDATATYPE)
    _r = r_from_rstar(a, rs) # Evaluate at this r

    if rs < rsin
        # Extend the numerical solution to the analytical ansatz from rsin to horizon

        # Obtain the coefficients by imposing continuity in X and dX/drs
        Cref_SN, Cinc_SN = CrefCinc_SN_from_Xup(s, m, a, omega, lambda, Xupsoln, rsin; order=horizon_expansionorder, dtype=dtype)
        # with coefficient Cref_SN for the left-going and Cinc_SN for the right-going mode

        # Construct the analytical ansatz
        p = omega - m*omega_horizon(a)
        gin(r) = gansatz(
            ord -> ingoing_coefficient_at_hor(s, m, a, omega, lambda, ord; data_type=dtype),
            a,
            r;
            order=horizon_expansionorder
        )
        dgin_dr(r) = dgansatz_dr(
            ord -> ingoing_coefficient_at_hor(s, m, a, omega, lambda, ord; data_type=dtype),
            a,
            r;
            order=horizon_expansionorder
        )
        gout(r) = gansatz(
            ord -> outgoing_coefficient_at_hor(s, m, a, omega, lambda, ord; data_type=dtype),
            a,
            r;
            order=horizon_expansionorder
        )
        dgout_dr(r) = dgansatz_dr(
            ord -> outgoing_coefficient_at_hor(s, m, a, omega, lambda, ord; data_type=dtype),
            a,
            r;
            order=horizon_expansionorder
        )

        _Xup = Cinc_SN*gout(_r)*exp(1im*p*rs) + Cref_SN*gin(_r)*exp(-1im*p*rs) # Evaluate at *this* rs

        _DeltaOverr2pa2 = Delta(a, _r)/(_r^2 + a^2)
        _dXupdrs = Cinc_SN*(_DeltaOverr2pa2 * dgout_dr(_r) + 1im*p*gout(_r))*exp(1im*p*rs) + Cref_SN*(_DeltaOverr2pa2 * dgin_dr(_r) - 1im*p*gin(_r))*exp(-1im*p*rs)

        return (_Xup, _dXupdrs)
    elseif rs > rsout
        # Extend the numerical solution to the analytical ansatz from rsout to infinity

        fout(r) = fansatz(
            ord -> outgoing_coefficient_at_inf(s, m, a, omega, lambda, ord; data_type=dtype),
            omega,
            r;
            order=infinity_expansionorder
        )
        dfout_dr(r) = dfansatz_dr(
            ord -> outgoing_coefficient_at_inf(s, m, a, omega, lambda, ord; data_type=dtype),
            omega,
            r;
            order=infinity_expansionorder
        )

        _Xup = fout(_r)*exp(1im*omega*rs)

        _DeltaOverr2pa2 = Delta(a, _r)/(_r^2 + a^2)
        _dXupdrs = (_DeltaOverr2pa2 * dfout_dr(_r) + 1im*omega*fout(_r)) * exp(1im*omega*rs)
        
        return (_Xup, _dXupdrs)
    else
        # Requested rs is within the numerical solution
        return Xupsoln(rs)
    end 
end

function check_XinXup_sanity(Xin, Xup; tolerance=1e-6)
    #=
    Check if the X_in and X_up solutions are sane by checking if the identity

    Binc/Cinc = (p*c0)/(omega*eta(r_+)) [note: this is Eq. (42) in the paper]

    is satisfied within a specified tolerance
    =#

    # Check if the modes are the same
    if Xin.mode != Xup.mode
        throw(ArgumentError("The modes of Xin and Xup are different"))
    end

    # Calculate what Binc/Cinc is expected to be
    p = Xin.mode.omega - Xin.mode.m*omega_horizon(Xin.mode.a)
    c0 = eta_coefficient(Xin.mode.s, Xin.mode.m, Xin.mode.a, Xin.mode.omega, Xin.mode.lambda, 0)
    eta_at_rplus = eta(Xin.mode.s, Xin.mode.m, Xin.mode.a, Xin.mode.omega, Xin.mode.lambda, r_plus(Xin.mode.a))
    expected_value = (p*c0)/(Xin.mode.omega*eta_at_rplus)

    # Calculate the actual value
    actual_value = Xin.incidence_amplitude/Xup.incidence_amplitude

    if abs(actual_value - expected_value) > tolerance
        return false
    else
        return true
    end
end

# Some helper functions for static modes
function x_from_r(a, r)
    #=
    x \equiv (rp - r)/(rp - rm) is a transformed coordinate that
    is used only internally in the code/static mode computation
    =#
    gamma = sqrt(1 - a^2)
    return ((1+gamma)-r)/(2*gamma)
end

function r_from_x(a, x)
    gamma = sqrt(1 - a^2)
    return 1 + gamma - 2*gamma*x
end

function isnegativeinteger(x)
    isinteger(x) && x < 0
end

# Some helper functions for manipulating hypergeometric functions
function pochhammer(x, n)
    # Wrapper for the pochhammer function implemented in HypergeometricFunctions.jl
    HypergeometricFunctions.pochhammer(x, n)
end

#=
Since there is no implementation of a "regularized" Gauss hypergeometric function in
HypergeometricFunctions.jl yet, we use the fact that when c approaches a negative
integer, 2F1(a,b;c,z)/Gamma(c) approaches the value

lim c->-m 2F1(a, b; c, z)/Gamma(c) = (a)_m (b)_m / m! * z^m * 2F1(a+m, b+m; m+1; z)

which is implemented below
=#
function _2F1_over_Gamma_c(a, b, c, z)
    # NOTE This is true only when c is a negative integer
    z *= (1 + 0im) # Make sure that z is a complex number
    m = abs(c) + 1
    ( pochhammer(a, m) * pochhammer(b, m) / factorial(m) ) * z^m * pFq((a+m, b+m), (m+1, ), z)
end

function _d2F1_over_Gamma_c_dz(a, b, c, z)
    # NOTE This is true only when c is a negative integer
    z *= (1 + 0im) # Make sure that z is a complex number
    m = abs(c) + 1
    # Here we explicitly compute the derivative because ForwardDiff.jl does not work very well with HypergeometricFunctions.jl
    ( pochhammer(a, m) * pochhammer(b, m) / factorial(m) ) * (m*z^(m-1) * pFq((a+m, b+m), (m+1, ), z) + z^m * pFq((a+m+1, b+m+1), (m+2, ), z))
end

function solve_static_Rin(s::Int, l::Int, m::Int, a)
    #=
    This is an internal function that returns the static (omega = 0) solution that satisfies
    the "purely left-going" condition at the horizon, namely the R^in solution.

    Use instead GeneralizedSasakiNakamura.Teukolsky_radial() and set omega = 0 and boundary_condition = IN
    =#
    gamma = sqrt(1 - a^2)
    kappa = I*a*m/gamma

    normalization_const = begin
        (-1)^(-kappa/2) * exp(I*a*m/2) * gamma^(I*a*m/(1+gamma)) * (-4*gamma^2)^(-s)
    end

    Rin(r) = begin
        x = x_from_r(a, r)
        if iszero(kappa) && isnegativeinteger(1-s)
            # Regularization
            normalization_const * x^(-s + kappa/2) * (1-x)^(kappa/2) * _2F1_over_Gamma_c(-l+kappa, 1+l+kappa, 1-s, x)
        else
            normalization_const * x^(-s + kappa/2) * (1-x)^(kappa/2) * pFq((-l+kappa, 1+l+kappa), (1-s+kappa,), x)
        end
    end

    dRindr(r) = begin
        x = x_from_r(a, r)
        if iszero(kappa) && isnegativeinteger(1-s)
            # Regularization
            normalization_const * (-1/(2*gamma)) * ( (1/2) * (1-x)^(-1+kappa/2) * x^(-1-s+kappa/2) * (2*s*(x-1) + kappa - 2*kappa*x) * _2F1_over_Gamma_c(-l+kappa, 1+l+kappa, 1-s, x) + x^(-s + kappa/2) * (1-x)^(kappa/2) * _d2F1_over_Gamma_c_dz(-l+kappa, 1+l+kappa, 1-s, x) )
        else
            normalization_const * (-1/(2*gamma)) * ( (1/2) * (1-x)^(-1+kappa/2) * x^(-1-s+kappa/2) * (2*s*(x-1) + kappa - 2*kappa*x) * pFq((-l+kappa, 1+l+kappa), (1-s+kappa,), x) + x^(-s + kappa/2) * (1-x)^(kappa/2) * pochhammer(-l+kappa, 1) * pochhammer(1+l+kappa, 1) / pochhammer(1-s+kappa, 1) * pFq((-l+kappa+1, 1+l+kappa+1), (1-s+kappa+1,), x) )
        end
    end

    return (r -> [Rin(r);  dRindr(r)])
end

function solve_static_Rup(s::Int, l::Int, m::Int, a)
    #=
    This is an internal function that returns the static (omega = 0) solution that satisfies
    the "purely right-going" condition at spatial infinity, namely the R^up solution.

    Use instead GeneralizedSasakiNakamura.Teukolsky_radial() and set omega = 0 and boundary_condition = UP
    =#
    gamma = sqrt(1 - a^2)
    kappa = I*a*m/gamma

    normalization_const = begin
        (-2*gamma)^(-s-l-1)
    end

    Rup(r) = begin
        x = x_from_r(a, r)
        normalization_const * x^(-s-l-1-kappa/2) * (x-1)^(kappa/2) * pFq((1+l+kappa, 1+s+l), (2+2*l,),1/x)
    end
    
    dRupdr(r) = begin
        x = x_from_r(a, r)
        normalization_const * (-1/(2*gamma)) * ( ( (1/2)*(x-1)^(-1+kappa/2) * x^(-2-l-s-kappa/2) * (-2*(1+l+s)*(x-1) + kappa) ) * pFq((1+l+kappa, 1+s+l), (2+2*l,),1/x) + x^(-s-l-1-kappa/2) * (x-1)^(kappa/2) * pochhammer(1+l+kappa, 1) * pochhammer(1+s+l, 1) / pochhammer(2+2*l, 1) * pFq((2+l+kappa, 2+s+l), (3+2*l,),1/x) * (-1/x^2) )
    end

    return (r-> [Rup(r); dRupdr(r)])
end



end
