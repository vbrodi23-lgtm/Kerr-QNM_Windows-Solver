using Test
using GeneralizedSasakiNakamura

const GSN = GeneralizedSasakiNakamura

function exercise_carriers(::Type{T}) where {T<:AbstractFloat}
    omega = complex(T(3), T(4))
    p_horizon = complex(T(-5), T(12))
    rstar_match = T(2)
    convention = gsn_branch_convention(omega, p_horizon)

    infinity = PlaneWaveCarrier(
        INFINITY_OUTGOING, omega, rstar_match, convention
    )
    horizon_in = PlaneWaveCarrier(
        HORIZON_INGOING, p_horizon, rstar_match, convention
    )
    horizon_out = PlaneWaveCarrier(
        HORIZON_OUTGOING, p_horizon, rstar_match, convention
    )

    @test carrier_log(infinity, zero(T)) == complex(T(-8), T(6))
    @test carrier_log_derivative(infinity) == complex(zero(T), T(5))
    @test carrier_log(horizon_in, zero(T)) == complex(T(24), T(10))
    @test carrier_log_derivative(horizon_in) == complex(zero(T), T(13))
    @test carrier_log(horizon_out, zero(T)) == complex(T(-24), T(-10))
    @test carrier_log_derivative(horizon_out) == complex(zero(T), T(-13))
    @test carrier_log_derivative_derivative(infinity) == zero(Complex{T})
    @test carrier_value(infinity, zero(T)) ≈ exp(complex(T(-8), T(6)))
    @test carrier_value(horizon_in, zero(T)) ≈ exp(complex(T(24), T(10)))
    @test carrier_value(horizon_out, zero(T)) ≈ exp(complex(T(-24), T(-10)))

    rho = T(1) / T(4)
    state = FactoredEndpointState(
        complex(T(2), T(-3)), complex(T(-7), T(5))
    )
    raw = reconstruct_state(state, infinity, rho)
    round_trip = factor_state(raw.X, raw.Xrho, infinity, rho)
    @test round_trip.Y ≈ state.Y
    @test round_trip.Yrho ≈ state.Yrho

    changed = change_carrier(state, infinity, horizon_in, zero(T))
    raw_before = reconstruct_state(state, infinity, zero(T))
    raw_after = reconstruct_state(changed, horizon_in, zero(T))
    diagnostics = carrier_change_diagnostics(
        state, changed, infinity, horizon_in, zero(T)
    )
    @test carrier_value(infinity, zero(T)) != one(Complex{T})
    @test carrier_value(horizon_in, zero(T)) != one(Complex{T})
    @test raw_after.X ≈ raw_before.X
    @test raw_after.Xrho ≈ raw_before.Xrho
    @test diagnostics.X_reconstruction_error ≈ zero(T) atol=sqrt(eps(T))
    @test diagnostics.Xrho_reconstruction_error ≈ zero(T) atol=sqrt(eps(T))
    @test diagnostics.carrier_ratio_magnitude > zero(T)
    @test isfinite(diagnostics.carrier_ratio_phase)

    scale = complex(T(7), T(-2))
    scaled_state = FactoredEndpointState(scale * state.Y, scale * state.Yrho)
    scaled_changed = change_carrier(
        scaled_state, infinity, horizon_in, zero(T)
    )
    @test scaled_changed.Y ≈ scale * changed.Y
    @test scaled_changed.Yrho ≈ scale * changed.Yrho

    @test_throws ArgumentError PlaneWaveCarrier(
        INFINITY_OUTGOING, zero(Complex{T}), rstar_match, convention
    )
    @test_throws ArgumentError PlaneWaveCarrier(
        INFINITY_OUTGOING, p_horizon, rstar_match, convention
    )
    @test_throws ArgumentError PlaneWaveCarrier(
        INFINITY_OUTGOING,
        complex(T(Inf), zero(T)),
        rstar_match,
        convention,
    )
end

@testset "canonical GSN carriers are precision-generic" begin
    exercise_carriers(Float64)
    setprecision(BigFloat, 256) do
        exercise_carriers(BigFloat)
    end
end

@testset "full convention and branch-cell semantics" begin
    omega = 3.0 + 4.0im
    p_horizon = -5.0 + 12.0im
    reference = gsn_branch_convention(omega, p_horizon)
    sample = gsn_branch_convention(4.0 + 4.0im, -4.0 + 12.0im)

    @test full_convention_equal(reference, reference)
    @test !full_convention_equal(reference, sample)
    @test branch_cell_compatible(reference, sample)
    deformation = contour_angle_deformation(reference, sample)
    @test deformation.infinity_delta == (
        sample.infinity_contour_angle - reference.infinity_contour_angle
    )
    @test deformation.horizon_delta == (
        sample.horizon_contour_angle - reference.horizon_contour_angle
    )
    @test infinity_contour_tangent(reference) ≈ cis(-atan(4.0, 3.0))
    @test horizon_contour_tangent(reference) ≈ -cis(-atan(12.0, -5.0))

    sign_crossing = gsn_branch_convention(-3.0 + 4.0im, p_horizon)
    @test !branch_cell_compatible(reference, sign_crossing)
    @test_throws ArgumentError assert_no_branch_crossing(reference, sign_crossing)

    above_cut = gsn_branch_convention(-3.0 + 1.0e-6im, p_horizon)
    below_cut = gsn_branch_convention(-3.0 - 1.0e-6im, p_horizon)
    @test branch_cell_compatible(above_cut, below_cut)
    @test_throws ArgumentError contour_angle_deformation(above_cut, below_cut)

    source = PlaneWaveCarrier(INFINITY_OUTGOING, omega, 2.0, reference)
    incompatible_target = PlaneWaveCarrier(
        HORIZON_INGOING, p_horizon, 2.0, sign_crossing
    )
    state = FactoredEndpointState(2.0 + 1.0im, -1.0 + 3.0im)
    @test_throws ArgumentError change_carrier(
        state, source, incompatible_target, 0.0
    )

    above_cut_carrier = PlaneWaveCarrier(
        INFINITY_OUTGOING, -3.0 + 1.0e-6im, 2.0, above_cut
    )
    below_cut_carrier = PlaneWaveCarrier(
        INFINITY_OUTGOING, -3.0 - 1.0e-6im, 2.0, below_cut
    )
    @test_throws ArgumentError change_carrier(
        state, above_cut_carrier, below_cut_carrier, 0.0
    )

    extreme_infinity = PlaneWaveCarrier(
        INFINITY_OUTGOING, omega, 100.0, reference
    )
    extreme_horizon = PlaneWaveCarrier(
        HORIZON_INGOING, p_horizon, 100.0, reference
    )
    @test_throws ArgumentError change_carrier(
        state, extreme_infinity, extreme_horizon, 0.0
    )
    @test_throws ArgumentError change_carrier(
        state, extreme_horizon, extreme_infinity, 0.0
    )
end

@testset "regular-remainder identities and activation boundary" begin
    contract = RegularRemainderContract()
    @test contract.identity == "known-carrier-times-regular-remainder/v1"
    @test contract.scattering_columns == scattering_column_convention
    @test contract.radial_derivative == radial_derivative_convention
    @test contract.determinant == determinant_convention
    @test contract.factored_state == factored_remainder_state_convention
    @test scattering_column_convention ==
        "column1=horizon-ingoing-Cref;column2=horizon-outgoing-Cinc/v1"
    @test radial_derivative_convention == "state2=dX/drho/v1"
    @test determinant_convention == "cinc-over-cref-minus-R/v1"
    @test factored_remainder_state_convention ==
        "state1=Y;state2=dY/drho/v1"
    @test_throws ArgumentError gsn_branch_convention(0.0 + 0.0im, 1.0 + 1.0im)
    @test_throws ArgumentError gsn_branch_convention(1.0 + 1.0im, 0.0 + 0.0im)
    @test_throws ArgumentError gsn_branch_convention(Inf + 1.0im, 1.0 + 1.0im)

    # TODO: [HUMAN MATH REVIEW REQUIRED — generate and freeze independent high-precision reference values for the three GSN asymptotic branches after the branch and normalization conventions have been verified.]
    @test_throws ErrorException assert_independent_reference_fixture_available()
    @test_throws ErrorException assert_regularised_gsn_production_ready()
end

const AEC = GSN.AsymptoticExpansionCoefficients

function typed_asymptotic_parameters(::Type{T}) where {T<:AbstractFloat}
    return (
        s=-2,
        m=2,
        a=T(1) / T(5),
        omega=complex(T(2) / T(5), T(1) / T(20)),
        lambda=complex(T(4), T(1) / T(10)),
    )
end

function captured_asymptotic_error(operation)
    caught = try
        operation()
        nothing
    catch error
        error
    end
    @test caught isa AEC.AsymptoticConstructionError
    return caught::AEC.AsymptoticConstructionError
end

function assert_asymptotic_error(
    operation;
    reason,
    family,
    order::Int,
    precision_bits::Int,
)
    caught = captured_asymptotic_error(operation)
    @test caught.reason == reason
    @test caught.family == family
    @test caught.order == order
    @test caught.precision_bits == precision_bits
    return caught
end

@testset "request-local asymptotic batches preserve exact precision" begin
    p64 = typed_asymptotic_parameters(Float64)
    bundle64 = AEC.build_asymptotic_series_bundle(
        p64.s, p64.m, p64.a, p64.omega, p64.lambda, 12;
        precision_bits=precision(Float64),
    )
    @test bundle64.infinity_ingoing.key.precision_bits == precision(Float64)
    @test eltype(bundle64.infinity_ingoing.coefficients) == ComplexF64
    @test eltype(bundle64.infinity_outgoing.P.coefficients) == ComplexF64
    @test eltype(bundle64.horizon_ingoing.Q.coefficients) == ComplexF64

    low_request = setprecision(BigFloat, 128) do
        p = typed_asymptotic_parameters(BigFloat)
        AEC.build_asymptotic_series_bundle(
            p.s, p.m, p.a, p.omega, p.lambda, 12;
            precision_bits=128,
        )
    end
    high_request = setprecision(BigFloat, 256) do
        p = typed_asymptotic_parameters(BigFloat)
        AEC.build_asymptotic_series_bundle(
            p.s, p.m, p.a, p.omega, p.lambda, 12;
            precision_bits=256,
        )
    end

    for (bundle, bits) in ((low_request, 128), (high_request, 256))
        for series in (
            bundle.infinity_ingoing,
            bundle.infinity_outgoing,
            bundle.horizon_ingoing,
            bundle.horizon_outgoing,
        )
            @test series.key.precision_bits == bits
            @test eltype(series.coefficients) == Complex{BigFloat}
            @test eltype(series.P.coefficients) == Complex{BigFloat}
            @test eltype(series.Q.coefficients) == Complex{BigFloat}
            @test precision(real(series.P.center)) == bits
            @test precision(real(series.Q.center)) == bits
            @test all(evidence -> evidence.precision_bits == bits, series.evidence)
            for order in (4, 5, 10, 12)
                @test precision(real(series.coefficients[order + 1])) == bits
                @test precision(imag(series.coefficients[order + 1])) == bits
            end
        end
    end

    setprecision(BigFloat, 96) do
        @test precision(real(low_request.infinity_outgoing.coefficients[11])) == 128
        @test precision(real(high_request.infinity_outgoing.coefficients[11])) == 256
    end

    @test_throws AEC.AsymptoticConstructionError AEC.build_asymptotic_series_bundle(
        p64.s, p64.m, p64.a, p64.omega, p64.lambda, 4;
        precision_bits=256,
    )
end

@testset "batch coefficients retain legacy API bridges" begin
    p = typed_asymptotic_parameters(Float64)
    bundle = AEC.build_asymptotic_series_bundle(
        p.s, p.m, p.a, p.omega, p.lambda, 12;
        precision_bits=precision(Float64),
    )
    bridges = (
        (AEC.ingoing_coefficient_at_inf, bundle.infinity_ingoing),
        (AEC.outgoing_coefficient_at_inf, bundle.infinity_outgoing),
        (AEC.ingoing_coefficient_at_hor, bundle.horizon_ingoing),
        (AEC.outgoing_coefficient_at_hor, bundle.horizon_outgoing),
    )
    for (legacy, series) in bridges, order in 0:12
        @test legacy(
            p.s, p.m, p.a, p.omega, p.lambda, order;
            data_type=ComplexF64,
        ) ≈ series.coefficients[order + 1]
    end

    # The horizon bridge functions intentionally consume the same request-local
    # recurrence and therefore establish API compatibility, not an independent
    # analytic oracle.  At infinity, recurrence-from-zero bypasses the explicit
    # order-1:3 seeds and provides the independent low-order equivalence check.
    for family in (AEC.INFINITY_INGOING_SERIES, AEC.INFINITY_OUTGOING_SERIES)
        key = AEC.SeriesKey(
            p.s, p.m, p.a, p.omega, p.lambda, family, 3,
            precision(Float64),
        )
        recurrence = AEC.build_infinity_recurrence_from_zero(key)
        explicit = AEC.build_asymptotic_series(key)
        @test recurrence.coefficients[2:4] ≈ explicit.coefficients[2:4]
    end
end

@testset "near-resonant horizon denominators feed recurrence conditioning" begin
    bits = precision(Float64)
    a = 0.0
    m = 0
    lambda = 4.0 + 0.0im
    cases = (
        (AEC.HORIZON_OUTGOING_SERIES, 0.0 + 0.25im),
        (AEC.HORIZON_INGOING_SERIES, 0.0 - 0.25im),
    )
    for (family, resonant_omega) in cases
        losses = Float64[]
        for perturbation in (2.0^(-12), 2.0^(-24))
            key = AEC.SeriesKey(
                0,
                m,
                a,
                resonant_omega + complex(perturbation, 0.0),
                lambda,
                family,
                1,
                bits,
            )
            evidence = AEC.build_asymptotic_series(key).evidence[2]
            @test !iszero(evidence.denominator_value)
            @test evidence.denominator_scale > abs(evidence.denominator_value)
            @test evidence.cancellation_digits > 0.0
            push!(losses, evidence.cancellation_digits)
        end
        @test losses[2] > losses[1]

        assert_asymptotic_error(
            () -> AEC.build_asymptotic_series(AEC.SeriesKey(
                0, m, a, resonant_omega, lambda, family, 1, bits,
            ));
            reason=AEC.PHYSICAL_SINGULAR_LIMIT,
            family=family,
            order=1,
            precision_bits=bits,
        )
    end
end

@testset "asymptotic construction guards audited singularities" begin
    bits = precision(Float64)
    p = typed_asymptotic_parameters(Float64)
    assert_asymptotic_error(
        () -> AEC.SeriesKey(
            p.s,
            p.m,
            p.a,
            p.omega,
            p.lambda,
            AEC.INFINITY_OUTGOING_SERIES,
            -1,
            bits,
        );
        reason=AEC.INVALID_ASYMPTOTIC_ORDER,
        family=AEC.INFINITY_OUTGOING_SERIES,
        order=-1,
        precision_bits=bits,
    )

    chart_singularities = (
        ("lambda+2", 1, -2.0 + 0.0im),
        ("lambda", -1, 0.0 + 0.0im),
        ("Eplus", 2, -4.0 + 0.0im),
        ("Eminus", -2, -2.0 + 0.0im),
    )
    for (label, spin_weight, lambda) in chart_singularities
        @testset "$label exact chart denominator" begin
            family = AEC.INFINITY_OUTGOING_SERIES
            assert_asymptotic_error(
                () -> AEC.build_asymptotic_series(AEC.SeriesKey(
                    spin_weight,
                    0,
                    0.0,
                    0.0 + 0.0im,
                    lambda,
                    family,
                    3,
                    bits,
                ));
                reason=AEC.ALGEBRAIC_REPRESENTATION_SINGULAR,
                family=family,
                order=3,
                precision_bits=bits,
            )
        end
    end

    assert_asymptotic_error(
        () -> AEC.build_asymptotic_series(AEC.SeriesKey(
            0,
            0,
            1.0,
            p.omega,
            p.lambda,
            AEC.HORIZON_INGOING_SERIES,
            3,
            bits,
        ));
        reason=AEC.PHYSICAL_SINGULAR_LIMIT,
        family=AEC.HORIZON_INGOING_SERIES,
        order=3,
        precision_bits=bits,
    )

    assert_asymptotic_error(
        () -> AEC.build_asymptotic_series(AEC.SeriesKey(
            0,
            0,
            0.0,
            0.0 + 0.0im,
            4.0 + 0.0im,
            AEC.HORIZON_OUTGOING_SERIES,
            3,
            bits,
        ));
        reason=AEC.PHYSICAL_SINGULAR_LIMIT,
        family=AEC.HORIZON_OUTGOING_SERIES,
        order=3,
        precision_bits=bits,
    )

    assert_asymptotic_error(
        () -> AEC.SeriesKey(
            0,
            0,
            0.0,
            complex(Inf, 0.0),
            4.0 + 0.0im,
            AEC.INFINITY_OUTGOING_SERIES,
            3,
            bits,
        );
        reason=AEC.NONFINITE_ASYMPTOTIC_DATA,
        family=AEC.INFINITY_OUTGOING_SERIES,
        order=3,
        precision_bits=bits,
    )

    zero_frequency = AEC.SeriesKey(
        0, 0, 0.25, 0.0 + 0.0im, 4.0 + 0.0im,
        AEC.INFINITY_OUTGOING_SERIES, 5, bits,
    )
    @test all(isfinite, real.(AEC.build_asymptotic_series(zero_frequency).coefficients))
end

function synthetic_asymptotic_series(
    coefficients::Vector{Complex{T}},
    family::AEC.AsymptoticFamily;
    omega::Complex{T}=complex(T(1) / T(2), zero(T)),
    recurrence_digits_lost::T=zero(T),
) where {T<:AbstractFloat}
    order = length(coefficients) - 1
    bits = precision(T)
    key = AEC.SeriesKey(
        0,
        0,
        T(1) / T(5),
        omega,
        complex(T(4), zero(T)),
        family,
        order,
        bits,
    )
    workspace = AEC.TypedTaylorWorkspace{T}(
        zero(Complex{T}), fill(zero(Complex{T}), order + 2)
    )
    evidence = AEC.RecurrenceEvidence{T}[
        AEC.RecurrenceEvidence{T}(
            one(Complex{T}),
            one(T),
            abs(coefficient),
            abs(coefficient),
            T(10)^recurrence_digits_lost,
            recurrence_digits_lost,
            family,
            coefficient_order,
            bits,
        )
        for (coefficient_order, coefficient) in zip(0:order, coefficients)
    ]
    return AEC.AsymptoticSeries{T}(
        key, copy(coefficients), workspace, workspace, evidence
    )
end

function with_recurrence_cancellation_factors(
    series::AEC.AsymptoticSeries{T}, factors::Vector{T}
) where {T<:AbstractFloat}
    @assert length(factors) == length(series.evidence)
    evidence = AEC.RecurrenceEvidence{T}[]
    for (source, factor) in zip(series.evidence, factors)
        push!(evidence, AEC.RecurrenceEvidence{T}(
            source.denominator_value,
            source.denominator_scale,
            source.value_scale,
            source.recurrence_term_abs_sum,
            factor,
            log10(max(one(T), factor)),
            source.family,
            source.order,
            source.precision_bits,
        ))
    end
    return AEC.AsymptoticSeries{T}(
        series.key,
        copy(series.coefficients),
        series.P,
        series.Q,
        evidence,
    )
end

@testset "three-way endpoint series evaluation is typed and independent" begin
    for T in (Float64, BigFloat)
        operation = function ()
            coefficients = Complex{T}[
                complex(T(1), zero(T)),
                complex(T(2), zero(T)),
                complex(T(3), zero(T)),
            ]
            series = synthetic_asymptotic_series(
                coefficients, AEC.INFINITY_OUTGOING_SERIES
            )
            z = complex(T(1) / T(4), zero(T))
            dz_dr = one(Complex{T})
            evaluation = AEC.evaluate_asymptotic_series(series, z, dz_dr)

            @test evaluation isa AEC.SeriesEvaluation{T}
            @test evaluation.series_eval_horner ≈ complex(T(27) / T(16), zero(T))
            @test evaluation.series_derivative_horner ≈ complex(T(7) / T(2), zero(T))
            @test evaluation.series_eval_compensated ≈ evaluation.series_eval_horner
            @test evaluation.series_eval_alternate ≈ evaluation.series_eval_horner
            @test evaluation.series_derivative_compensated ≈
                evaluation.series_derivative_horner
            @test evaluation.series_derivative_alternate ≈
                evaluation.series_derivative_horner
            @test evaluation.family == series.key.family
            @test evaluation.order == series.key.max_order
            @test evaluation.precision_bits == series.key.precision_bits
            @test evaluation.estimate_kind ==
                AEC.ASYMPTOTIC_CONDITIONING_ESTIMATE_KIND
            @test evaluation.last_term_magnitude == abs(coefficients[3] * z^2)
            @test evaluation.derivative_last_term_magnitude ==
                abs(T(2) * coefficients[3] * z * dz_dr)

            infinity_r = complex(T(10), zero(T))
            infinity_evaluation = AEC.evaluate_infinity_asymptotic_series(
                series, infinity_r
            )
            infinity_z = inv(series.key.omega * infinity_r)
            direct_infinity = AEC.evaluate_asymptotic_series(
                series, infinity_z, -infinity_z / infinity_r
            )
            @test infinity_evaluation.series_eval_horner ≈
                direct_infinity.series_eval_horner
            @test infinity_evaluation.series_derivative_horner ≈
                direct_infinity.series_derivative_horner

            horizon_series = synthetic_asymptotic_series(
                coefficients, AEC.HORIZON_INGOING_SERIES
            )
            rplus = one(T) + sqrt(
                (one(T) - horizon_series.key.a) *
                (one(T) + horizon_series.key.a)
            )
            horizon_r = complex(rplus + T(1) / T(10), zero(T))
            horizon_evaluation = AEC.evaluate_horizon_asymptotic_series(
                horizon_series, horizon_r
            )
            direct_horizon = AEC.evaluate_asymptotic_series(
                horizon_series,
                horizon_r - complex(rplus, zero(T)),
                one(Complex{T}),
            )
            @test horizon_evaluation.series_eval_horner ≈
                direct_horizon.series_eval_horner
            @test horizon_evaluation.series_derivative_horner ≈
                direct_horizon.series_derivative_horner
        end
        if T == BigFloat
            setprecision(BigFloat, 192) do
                operation()
            end
        else
            operation()
        end
    end

    cancelling = synthetic_asymptotic_series(
        ComplexF64[1.0e16 + 0.0im, 1.0 + 0.0im, -1.0e16 + 0.0im],
        AEC.INFINITY_OUTGOING_SERIES,
    )
    cancellation = AEC.evaluate_asymptotic_series(
        cancelling, 1.0 + 0.0im, 1.0 + 0.0im
    )
    @test cancellation.series_evaluation_spread > 0.0
    @test cancellation.series_evaluation_digits_lost > 0.0
    @test cancellation.series_eval_horner != cancellation.series_eval_compensated
    @test cancellation.series_eval_alternate ≈ cancellation.series_eval_compensated

    derivative_cancelling = synthetic_asymptotic_series(
        ComplexF64[
            0.0 + 0.0im,
            1.0e16 + 0.0im,
            -5.0e15 + 0.0im,
            1.0 / 3.0 + 0.0im,
        ],
        AEC.INFINITY_OUTGOING_SERIES,
    )
    derivative_cancellation = AEC.evaluate_asymptotic_series(
        derivative_cancelling, 1.0 + 0.0im, 1.0 + 0.0im
    )
    @test derivative_cancellation.derivative_evaluation_spread > 0.0
    @test derivative_cancellation.derivative_evaluation_digits_lost > 0.0
    @test derivative_cancellation.series_derivative_horner !=
        derivative_cancellation.series_derivative_compensated
end

@testset "asymptotic preflight is empirical, exact-margin, and fail-loud" begin
    stable = synthetic_asymptotic_series(
        ComplexF64[1.0 + 0.0im, 1.0 + 0.0im, 1.0e-20 + 0.0im],
        AEC.INFINITY_OUTGOING_SERIES,
    )
    stable_evaluation = AEC.evaluate_asymptotic_series(
        stable, 0.5 + 0.0im, 1.0 + 0.0im
    )
    recurrence_conditioned = with_recurrence_cancellation_factors(
        stable, Float64[1.0, 100.0, 10.0]
    )
    recurrence_evaluation = AEC.evaluate_asymptotic_series(
        recurrence_conditioned, 0.5 + 0.0im, 1.0 + 0.0im
    )
    @test recurrence_evaluation.maximum_recurrence_cancellation_factor == 100.0
    recurrence_assessment = AEC.assess_asymptotic_preflight(
        recurrence_conditioned, recurrence_evaluation, 0.0
    )
    @test recurrence_assessment.maximum_recurrence_cancellation_factor == 100.0
    adequate = AEC.assess_asymptotic_preflight(
        stable, stable_evaluation, 7.0
    )
    @test adequate isa AEC.AsymptoticConditioningAssessment{Float64}
    @test adequate.adequate
    @test isnothing(adequate.reason)
    @test adequate.safety_margin_digits == 8.0
    @test adequate.arithmetic_decimal_digits ==
        precision(Float64) * log10(2.0)
    @test adequate.predicted_reliable_digits >= adequate.required_digits
    @test adequate.estimate_kind ==
        "empirical-three-way-series-conditioning/not-a-bound/v1"

    inadequate = AEC.assess_asymptotic_preflight(
        stable, stable_evaluation, 8.0
    )
    @test !inadequate.adequate
    @test inadequate.reason == "INSUFFICIENT_ASYMPTOTIC_PRECISION"
    @test inadequate.predicted_reliable_digits < inadequate.required_digits

    cancelling = synthetic_asymptotic_series(
        ComplexF64[1.0e16 + 0.0im, 1.0 + 0.0im, -1.0e16 + 0.0im],
        AEC.INFINITY_OUTGOING_SERIES,
    )
    cancellation = AEC.evaluate_asymptotic_series(
        cancelling, 1.0 + 0.0im, 1.0 + 0.0im
    )
    cancellation_assessment = AEC.assess_asymptotic_preflight(
        cancelling, cancellation, 0.0
    )
    @test cancellation_assessment.predicted_reliable_digits < 0.0
    @test !cancellation_assessment.adequate

    short_series = synthetic_asymptotic_series(
        ComplexF64[1.0 + 0.0im], AEC.INFINITY_OUTGOING_SERIES
    )
    @test_throws AEC.AsymptoticConstructionError AEC.assess_asymptotic_preflight(
        short_series, stable_evaluation, 1.0
    )

    horizon = synthetic_asymptotic_series(
        ComplexF64[1.0 + 0.0im, 0.5 + 0.0im], AEC.HORIZON_INGOING_SERIES
    )
    horizon_evaluation = AEC.evaluate_asymptotic_series(
        horizon, 0.1 + 0.0im, 1.0 + 0.0im
    )
    @test_throws AEC.AsymptoticConstructionError AEC.assess_asymptotic_preflight(
        stable, horizon_evaluation, 1.0
    )

    spectral_peer = synthetic_asymptotic_series(
        copy(stable.coefficients),
        AEC.INFINITY_OUTGOING_SERIES;
        omega=0.75 + 0.0im,
    )
    spectral_peer_evaluation = AEC.evaluate_asymptotic_series(
        spectral_peer, 0.5 + 0.0im, 1.0 + 0.0im
    )
    @test spectral_peer_evaluation.family == stable_evaluation.family
    @test spectral_peer_evaluation.order == stable_evaluation.order
    @test spectral_peer_evaluation.precision_bits ==
        stable_evaluation.precision_bits
    key_mismatch = captured_asymptotic_error(
        () -> AEC.assess_asymptotic_preflight(
            stable, spectral_peer_evaluation, 1.0
        )
    )
    @test key_mismatch.reason == AEC.INVALID_ASYMPTOTIC_INPUT
    @test occursin("spectral key differs", key_mismatch.message)
end

@testset "series evaluation rejects mixed precision and infinity static limit" begin
    series = synthetic_asymptotic_series(
        ComplexF64[1.0 + 0.0im, 0.5 + 0.0im],
        AEC.INFINITY_OUTGOING_SERIES,
    )
    setprecision(BigFloat, 128) do
        @test_throws AEC.AsymptoticConstructionError AEC.evaluate_asymptotic_series(
            series,
            complex(BigFloat("0.5"), BigFloat("0")),
            one(Complex{BigFloat}),
        )
    end

    zero_frequency = synthetic_asymptotic_series(
        ComplexF64[1.0 + 0.0im, 0.5 + 0.0im],
        AEC.INFINITY_OUTGOING_SERIES;
        omega=0.0 + 0.0im,
    )
    error = captured_asymptotic_error(
        () -> AEC.evaluate_infinity_asymptotic_series(
            zero_frequency, 10.0 + 0.0im
        )
    )
    @test error.reason == AEC.PHYSICAL_SINGULAR_LIMIT

    overflow_product = synthetic_asymptotic_series(
        ComplexF64[1.0 + 0.0im],
        AEC.INFINITY_OUTGOING_SERIES;
        omega=complex(floatmax(Float64), 0.0),
    )
    overflow_error = captured_asymptotic_error(
        () -> AEC.evaluate_infinity_asymptotic_series(
            overflow_product, 2.0 + 0.0im
        )
    )
    @test overflow_error.reason == AEC.NONFINITE_ASYMPTOTIC_DATA
    @test occursin("omega*r product is nonfinite", overflow_error.message)

    underflow_product = synthetic_asymptotic_series(
        ComplexF64[1.0 + 0.0im],
        AEC.INFINITY_OUTGOING_SERIES;
        omega=complex(nextfloat(0.0), 0.0),
    )
    underflow_error = captured_asymptotic_error(
        () -> AEC.evaluate_infinity_asymptotic_series(
            underflow_product, 0.5 + 0.0im
        )
    )
    @test underflow_error.reason == AEC.ALGEBRAIC_REPRESENTATION_SINGULAR
    @test occursin(
        "omega*r product underflowed to zero before inversion",
        underflow_error.message,
    )

    horizon = synthetic_asymptotic_series(
        ComplexF64[1.0 + 0.0im], AEC.HORIZON_OUTGOING_SERIES
    )
    @test_throws AEC.AsymptoticConstructionError AEC.evaluate_infinity_asymptotic_series(
        horizon, 10.0 + 0.0im
    )
    @test_throws AEC.AsymptoticConstructionError AEC.evaluate_horizon_asymptotic_series(
        series, 2.0 + 0.0im
    )
end

const IC = GSN.InitialConditions
const KERR = GSN.Kerr

function exercise_factored_endpoint_initialconditions(
    ::Type{T}
) where {T<:AbstractFloat}
    parameters = typed_asymptotic_parameters(T)
    precision_bits = precision(T)
    bundle = AEC.build_asymptotic_series_bundle(
        parameters.s,
        parameters.m,
        parameters.a,
        parameters.omega,
        parameters.lambda,
        6;
        precision_bits=precision_bits,
    )
    rplus = one(T) + sqrt(
        (one(T) - parameters.a) * (one(T) + parameters.a)
    )
    p_horizon = parameters.omega - T(parameters.m) *
        KERR.stable_horizon_geometry(parameters.a).omega_horizon
    convention = gsn_branch_convention(parameters.omega, p_horizon)
    contract = RegularRemainderContract()
    rstar_match = T(1) / T(7)
    infinity_rho = T(1) / T(3)
    horizon_rho = -T(1) / T(2)
    infinity_radius = complex(T(12), T(1) / T(10))
    horizon_radius = complex(
        rplus + T(1) / T(50), -T(1) / T(80)
    )
    infinity_radius_from_rho = rho -> begin
        @test rho == infinity_rho
        infinity_radius
    end
    horizon_radius_from_rho = rho -> begin
        @test rho == horizon_rho
        horizon_radius
    end

    infinity = factored_infinity_outgoing_initialconditions(
        bundle.infinity_outgoing,
        infinity_rho,
        rstar_match,
        infinity_radius_from_rho,
        convention,
        contract,
    )
    horizon_ingoing = factored_horizon_ingoing_initialconditions(
        bundle.horizon_ingoing,
        horizon_rho,
        rstar_match,
        horizon_radius_from_rho,
        convention,
        contract,
    )
    horizon_outgoing = factored_horizon_outgoing_initialconditions(
        bundle.horizon_outgoing,
        horizon_rho,
        rstar_match,
        horizon_radius_from_rho,
        convention,
        contract,
    )

    cases = (
        (
            infinity,
            bundle.infinity_outgoing,
            INFINITY_OUTGOING,
            infinity_radius,
            infinity_rho,
            infinity_contour_tangent(convention),
            legacy_raw_infinity_outgoing_rho_initialconditions,
        ),
        (
            horizon_ingoing,
            bundle.horizon_ingoing,
            HORIZON_INGOING,
            horizon_radius,
            horizon_rho,
            horizon_contour_tangent(convention),
            legacy_raw_horizon_ingoing_rho_initialconditions,
        ),
        (
            horizon_outgoing,
            bundle.horizon_outgoing,
            HORIZON_OUTGOING,
            horizon_radius,
            horizon_rho,
            horizon_contour_tangent(convention),
            legacy_raw_horizon_outgoing_rho_initialconditions,
        ),
    )

    tolerance = T(64) * sqrt(eps(T))
    for (result, series, branch, radius, rho, tangent, raw_bridge) in cases
        @test result isa FactoredInitialCondition{T}
        @test result.state isa FactoredEndpointState{T}
        @test result.carrier isa PlaneWaveCarrier{T}
        @test result.evaluation isa AEC.SeriesEvaluation{T}
        @test result.regularity isa RemainderRegularityEvidence{T}
        @test result.contract.identity == regular_remainder_contract
        @test result.contract.factored_state ==
            factored_remainder_state_convention
        @test result.state.Y == result.evaluation.series_eval_horner

        radial_factor = KERR.Delta(parameters.a, radius) /
            (radius^2 + parameters.a^2)
        expected_Yrho = tangent * radial_factor *
            result.evaluation.series_derivative_horner
        @test result.state.Yrho ≈ expected_Yrho
        @test !isapprox(
            result.state.Yrho,
            result.evaluation.series_derivative_horner;
            rtol=tolerance,
            atol=zero(T),
        )

        legacy_raw = raw_bridge(
            series,
            result.evaluation,
            radius,
            rho,
            rstar_match,
            convention,
        )
        reconstructed = reconstruct_state(
            result.state, result.carrier, rho
        )
        @test reconstructed.X ≈ legacy_raw.X rtol=tolerance
        @test reconstructed.Xrho ≈ legacy_raw.Xrho rtol=tolerance
        @test !isapprox(
            result.state.Y, legacy_raw.X; rtol=tolerance, atol=zero(T)
        )

        evidence = result.regularity
        @test evidence.branch == branch
        @test evidence.rho_endpoint == rho
        @test evidence.r_endpoint == radius
        @test evidence.finite
        @test evidence.remainder_norm == abs(result.state.Y)
        @test evidence.remainder_derivative_norm == abs(result.state.Yrho)
        @test evidence.carrier_magnitude == abs(
            carrier_value(result.carrier, rho)
        )
        @test evidence.carrier_magnitude != one(T)
        @test evidence.relative_X_reconstruction_error <= tolerance
        @test evidence.relative_Xrho_reconstruction_error <= tolerance
        @test evidence.Xrho_backward_residual <=
            evidence.reconstruction_tolerance
        @test evidence.carrier_operation_scale >= one(T)
        @test evidence.reconstruction_tolerance > zero(T)
        @test evidence.reconstruction_tolerance <= sqrt(eps(T))
        @test evidence.relative_X_reconstruction_error <=
            evidence.reconstruction_tolerance
        @test precision(evidence.remainder_norm) == precision_bits
        @test precision(real(result.state.Y)) == precision_bits
        @test precision(real(result.state.Yrho)) == precision_bits
    end
end

@testset "factored endpoint states are regular typed remainders" begin
    exercise_factored_endpoint_initialconditions(Float64)
    setprecision(BigFloat, 192) do
        exercise_factored_endpoint_initialconditions(BigFloat)
    end
end

function exercise_rho_zero_legacy_endpoint_bridges(
    ::Type{T}
) where {T<:AbstractFloat}
    parameters = typed_asymptotic_parameters(T)
    precision_bits = precision(T)
    order = 6
    bundle = AEC.build_asymptotic_series_bundle(
        parameters.s,
        parameters.m,
        parameters.a,
        parameters.omega,
        parameters.lambda,
        order;
        precision_bits=precision_bits,
    )
    p_horizon = parameters.omega - T(parameters.m) *
        KERR.stable_horizon_geometry(parameters.a).omega_horizon
    convention = gsn_branch_convention(parameters.omega, p_horizon)
    contract = RegularRemainderContract()
    rho = zero(T)
    infinity_rstar = T(20)
    horizon_rstar = -T(10)
    infinity_radius = complex(
        T(r_from_rstar(parameters.a, infinity_rstar)), zero(T)
    )
    horizon_radius = complex(
        T(r_from_rstar(parameters.a, horizon_rstar)), zero(T)
    )
    infinity_radius_from_rho = _ -> infinity_radius
    horizon_radius_from_rho = _ -> horizon_radius

    infinity = factored_infinity_outgoing_initialconditions(
        bundle.infinity_outgoing,
        rho,
        infinity_rstar,
        infinity_radius_from_rho,
        convention,
        contract,
    )
    reconstructed_up = reconstruct_state(
        infinity.state, infinity.carrier, rho
    )
    legacy_up, legacy_up_drstar = IC.Xup_initialconditions(
        parameters.s,
        parameters.m,
        parameters.a,
        parameters.omega,
        parameters.lambda,
        infinity_rstar;
        order=order,
        dtype=Complex{T},
    )

    horizon_ingoing = factored_horizon_ingoing_initialconditions(
        bundle.horizon_ingoing,
        rho,
        horizon_rstar,
        horizon_radius_from_rho,
        convention,
        contract,
    )
    reconstructed_in = reconstruct_state(
        horizon_ingoing.state, horizon_ingoing.carrier, rho
    )
    legacy_in, legacy_in_drstar = IC.Xin_initialconditions(
        parameters.s,
        parameters.m,
        parameters.a,
        parameters.omega,
        parameters.lambda,
        horizon_rstar;
        order=order,
        dtype=Complex{T},
    )

    tolerance = T(512) * sqrt(eps(T))
    @test reconstructed_up.X ≈ Complex{T}(legacy_up) rtol=tolerance
    @test reconstructed_up.Xrho ≈
        infinity_contour_tangent(convention) * legacy_up_drstar rtol=tolerance
    @test reconstructed_in.X ≈ Complex{T}(legacy_in) rtol=tolerance
    @test reconstructed_in.Xrho ≈
        horizon_contour_tangent(convention) * legacy_in_drstar rtol=tolerance

    horizon_outgoing = factored_horizon_outgoing_initialconditions(
        bundle.horizon_outgoing,
        rho,
        horizon_rstar,
        horizon_radius_from_rho,
        convention,
        contract,
    )
    reconstructed_out = reconstruct_state(
        horizon_outgoing.state, horizon_outgoing.carrier, rho
    )
    legacy_out = legacy_raw_horizon_outgoing_rho_initialconditions(
        bundle.horizon_outgoing,
        horizon_outgoing.evaluation,
        horizon_radius,
        rho,
        horizon_rstar,
        convention,
    )
    @test reconstructed_out.X ≈ legacy_out.X rtol=tolerance
    @test reconstructed_out.Xrho ≈ legacy_out.Xrho rtol=tolerance
end

@testset "rho=0 factored endpoints reproduce legacy raw APIs" begin
    exercise_rho_zero_legacy_endpoint_bridges(Float64)
    setprecision(BigFloat, 192) do
        exercise_rho_zero_legacy_endpoint_bridges(BigFloat)
    end
end

function exercise_large_rho_endpoint_reconstruction(
    ::Type{T}
) where {T<:AbstractFloat}
    parameters = typed_asymptotic_parameters(T)
    bundle = AEC.build_asymptotic_series_bundle(
        parameters.s,
        parameters.m,
        parameters.a,
        parameters.omega,
        parameters.lambda,
        6;
        precision_bits=precision(T),
    )
    geometry = KERR.stable_horizon_geometry(parameters.a)
    p_horizon = parameters.omega - T(parameters.m) *
        geometry.omega_horizon
    convention = gsn_branch_convention(parameters.omega, p_horizon)
    contract = RegularRemainderContract()
    infinity_rho = T(5000)
    horizon_rho = -T(5000)
    rstar_match = T(1) / T(8)
    infinity_radius = complex(T(12), T(1) / T(10))
    horizon_radius = complex(
        geometry.rplus + T(1) / T(50), -T(1) / T(80)
    )

    results = (
        factored_infinity_outgoing_initialconditions(
            bundle.infinity_outgoing,
            infinity_rho,
            rstar_match,
            _ -> infinity_radius,
            convention,
            contract,
        ),
        factored_horizon_ingoing_initialconditions(
            bundle.horizon_ingoing,
            horizon_rho,
            rstar_match,
            _ -> horizon_radius,
            convention,
            contract,
        ),
        factored_horizon_outgoing_initialconditions(
            bundle.horizon_outgoing,
            horizon_rho,
            rstar_match,
            _ -> horizon_radius,
            convention,
            contract,
        ),
    )

    for result in results
        evidence = result.regularity
        @test evidence.carrier_operation_scale > one(T)
        @test evidence.reconstruction_tolerance <= sqrt(eps(T))
        @test evidence.relative_X_reconstruction_error <=
            evidence.reconstruction_tolerance
        @test evidence.Xrho_backward_residual <=
            evidence.reconstruction_tolerance
    end
end

@testset "large-rho endpoint reconstruction remains scale-aware" begin
    exercise_large_rho_endpoint_reconstruction(Float64)
    setprecision(BigFloat, 192) do
        exercise_large_rho_endpoint_reconstruction(BigFloat)
    end
end

@testset "stable horizon geometry remains resolved near abs(a)=1" begin
    for T in (Float64, BigFloat)
        operation = function ()
            for a in (prevfloat(one(T)), nextfloat(-one(T)))
                geometry = KERR.stable_horizon_geometry(a)
                expected_delta = sqrt((one(T) - a) * (one(T) + a))
                @test geometry.delta == expected_delta
                @test geometry.delta > zero(T)
                @test geometry.rplus == one(T) + expected_delta
                @test geometry.rminus == a^2 / geometry.rplus
                @test geometry.omega_horizon ==
                    a / (T(2) * geometry.rplus)

                key = AEC.SeriesKey(
                    -2,
                    2,
                    a,
                    complex(T(2) / T(5), T(1) / T(20)),
                    complex(T(4), T(1) / T(10)),
                    AEC.HORIZON_INGOING_SERIES,
                    0,
                    precision(T),
                )
                delta, rplus, p_horizon = AEC._horizon_geometry(key)
                @test delta == geometry.delta
                @test rplus == geometry.rplus
                @test p_horizon == key.omega -
                    T(key.m) * geometry.omega_horizon
                @test IC._endpoint_wave_number(key, HORIZON_INGOING) ==
                    p_horizon
            end
        end
        if T == BigFloat
            setprecision(BigFloat, 192) do
                operation()
            end
        else
            operation()
        end
    end
end


@testset "horizon radial factor avoids near-rplus cancellation" begin
    T = Float64
    a = one(T) - ldexp(one(T), -40)
    geometry = KERR.stable_horizon_geometry(a)
    radius = complex(
        geometry.rplus + ldexp(one(T), -42), zero(T)
    )
    key = AEC.SeriesKey(
        -2,
        2,
        a,
        complex(T(2) / T(5), T(1) / T(20)),
        complex(T(4), T(1) / T(10)),
        AEC.HORIZON_INGOING_SERIES,
        0,
        precision(T),
    )
    stable_factor = IC._endpoint_radial_factor(
        key, radius, HORIZON_INGOING
    )
    direct_delta_factor = KERR.Delta(a, radius) /
        (radius^2 + a^2)
    high_precision_oracle = setprecision(BigFloat, 256) do
        big_a = BigFloat(a)
        big_radius = complex(
            BigFloat(real(radius)), BigFloat(imag(radius))
        )
        big_geometry = KERR.stable_horizon_geometry(big_a)
        big_delta = (big_radius - big_geometry.rplus) *
            (big_radius - big_geometry.rminus)
        ComplexF64(big_delta / (big_radius^2 + big_a^2))
    end

    @test !iszero(stable_factor)
    @test isapprox(
        stable_factor,
        high_precision_oracle;
        rtol=1.0e-2,
        atol=0.0,
    )
    @test abs(stable_factor - high_precision_oracle) <
        abs(direct_delta_factor - high_precision_oracle)
end

@testset "factored endpoints retain their originating BigFloat precision" begin
    prepared = setprecision(BigFloat, 192) do
        parameters = typed_asymptotic_parameters(BigFloat)
        bundle = AEC.build_asymptotic_series_bundle(
            parameters.s,
            parameters.m,
            parameters.a,
            parameters.omega,
            parameters.lambda,
            6;
            precision_bits=192,
        )
        p_horizon = parameters.omega - BigFloat(parameters.m) *
            KERR.stable_horizon_geometry(parameters.a).omega_horizon
        convention = gsn_branch_convention(parameters.omega, p_horizon)
        (
            bundle=bundle,
            convention=convention,
            radius=complex(BigFloat("12.0"), BigFloat("0.1")),
            rho=BigFloat("0.25"),
            rstar_match=BigFloat("0.125"),
        )
    end

    setprecision(BigFloat, 96) do
        radius_from_rho = _ -> prepared.radius
        result = factored_infinity_outgoing_initialconditions(
            prepared.bundle.infinity_outgoing,
            prepared.rho,
            prepared.rstar_match,
            radius_from_rho,
            prepared.convention,
            RegularRemainderContract(),
        )
        @test result.evaluation.precision_bits == 192
        @test precision(real(result.state.Y)) == 192
        @test precision(real(result.state.Yrho)) == 192
        @test precision(real(result.carrier.q)) == 192
        @test precision(result.regularity.carrier_magnitude) == 192
        @test precision(
            result.regularity.relative_Xrho_reconstruction_error
        ) == 192
        @test precision(result.regularity.Xrho_backward_residual) == 192
        @test precision(result.regularity.carrier_operation_scale) == 192
        @test precision(result.regularity.reconstruction_tolerance) == 192
    end
end

@testset "factored endpoint construction rejects invalid representation data" begin
    parameters = typed_asymptotic_parameters(Float64)
    bundle = AEC.build_asymptotic_series_bundle(
        parameters.s,
        parameters.m,
        parameters.a,
        parameters.omega,
        parameters.lambda,
        4;
        precision_bits=precision(Float64),
    )
    p_horizon = parameters.omega - parameters.m *
        KERR.stable_horizon_geometry(parameters.a).omega_horizon
    convention = gsn_branch_convention(parameters.omega, p_horizon)
    contract = RegularRemainderContract()
    radius = 12.0 + 0.1im

    @test_throws AEC.AsymptoticConstructionError factored_infinity_outgoing_initialconditions(
        bundle.horizon_outgoing,
        0.25,
        0.125,
        _ -> radius,
        convention,
        contract,
    )

    forged_contract = RegularRemainderContract(
        "raw-carrier-in-state/not-allowed",
        scattering_column_convention,
        radial_derivative_convention,
        determinant_convention,
        factored_remainder_state_convention,
    )
    @test_throws AEC.AsymptoticConstructionError factored_infinity_outgoing_initialconditions(
        bundle.infinity_outgoing,
        0.25,
        0.125,
        _ -> radius,
        convention,
        forged_contract,
    )

    mismatched_convention = gsn_branch_convention(
        parameters.omega + 0.1,
        p_horizon,
    )
    convention_error = captured_asymptotic_error(
        () -> factored_infinity_outgoing_initialconditions(
            bundle.infinity_outgoing,
            0.25,
            0.125,
            _ -> radius,
            mismatched_convention,
            contract,
        )
    )
    @test convention_error.reason == AEC.INVALID_ASYMPTOTIC_INPUT

    fake_p_horizon_convention = gsn_branch_convention(
        parameters.omega, p_horizon + 0.1
    )
    infinity_cross_leg_error = captured_asymptotic_error(
        () -> factored_infinity_outgoing_initialconditions(
            bundle.infinity_outgoing,
            0.25,
            0.125,
            _ -> radius,
            fake_p_horizon_convention,
            contract,
        )
    )
    @test infinity_cross_leg_error.reason == AEC.INVALID_ASYMPTOTIC_INPUT

    fake_omega_convention = gsn_branch_convention(
        parameters.omega + 0.1, p_horizon
    )
    horizon_cross_leg_error = captured_asymptotic_error(
        () -> factored_horizon_ingoing_initialconditions(
            bundle.horizon_ingoing,
            -0.25,
            0.125,
            _ -> complex(
                KERR.stable_horizon_geometry(parameters.a).rplus + 0.02,
                -0.01,
            ),
            fake_omega_convention,
            contract,
        )
    )
    @test horizon_cross_leg_error.reason == AEC.INVALID_ASYMPTOTIC_INPUT

    radius_callback_error = captured_asymptotic_error(
        () -> factored_infinity_outgoing_initialconditions(
            bundle.infinity_outgoing,
            0.25,
            0.125,
            _ -> throw(ArgumentError("callback claims underflow/nonfinite")),
            convention,
            contract,
        )
    )
    @test radius_callback_error.reason == AEC.INVALID_ASYMPTOTIC_INPUT

    nonfinite_radius_result_error = captured_asymptotic_error(
        () -> factored_infinity_outgoing_initialconditions(
            bundle.infinity_outgoing,
            0.25,
            0.125,
            _ -> complex(Inf, 0.0),
            convention,
            contract,
        )
    )
    @test nonfinite_radius_result_error.reason ==
        AEC.NONFINITE_ASYMPTOTIC_DATA

    singular_radius = complex(0.0, parameters.a)
    @test_throws AEC.AsymptoticConstructionError factored_infinity_outgoing_initialconditions(
        bundle.infinity_outgoing,
        0.25,
        0.125,
        _ -> singular_radius,
        convention,
        contract,
    )

    rplus = KERR.stable_horizon_geometry(parameters.a).rplus
    horizon_location_error = captured_asymptotic_error(
        () -> factored_horizon_ingoing_initialconditions(
            bundle.horizon_ingoing,
            -0.25,
            0.125,
            _ -> complex(rplus, 0.0),
            convention,
            contract,
        )
    )
    @test horizon_location_error.reason == AEC.INVALID_ASYMPTOTIC_INPUT
    @test occursin(
        "exact horizon radius r=r_plus", horizon_location_error.message
    )

    algebraic_tolerance = IC._scale_aware_reconstruction_tolerance(
        Float64, one(Float64)
    )
    reconstruction_error = captured_asymptotic_error(
        () -> IC._assert_reconstruction_within_tolerance(
            bundle.infinity_outgoing.key,
            2 * algebraic_tolerance,
            zero(Float64),
            algebraic_tolerance;
            order=4,
        )
    )
    @test reconstruction_error.reason ==
        AEC.ALGEBRAIC_REPRESENTATION_SINGULAR
    @test occursin(
        "exceeds the typed algebraic tolerance", reconstruction_error.message
    )

    carrier_underflow_error = captured_asymptotic_error(
        () -> factored_infinity_outgoing_initialconditions(
            bundle.infinity_outgoing,
            0.25,
            1.0e6,
            _ -> radius,
            convention,
            contract,
        )
    )
    @test carrier_underflow_error.reason ==
        AEC.ALGEBRAIC_REPRESENTATION_SINGULAR

    algebraic_callback_error = captured_asymptotic_error(
        () -> IC._translate_endpoint_argument_error(
            () -> throw(ArgumentError("reconstructed endpoint must be finite")),
            bundle.infinity_outgoing.key,
            "test reconstruction";
            argument_error_reason=AEC.ALGEBRAIC_REPRESENTATION_SINGULAR,
        )
    )
    @test algebraic_callback_error.reason ==
        AEC.ALGEBRAIC_REPRESENTATION_SINGULAR

    setprecision(BigFloat, 128) do
        big_parameters = typed_asymptotic_parameters(BigFloat)
        big_bundle = AEC.build_asymptotic_series_bundle(
            big_parameters.s,
            big_parameters.m,
            big_parameters.a,
            big_parameters.omega,
            big_parameters.lambda,
            4;
            precision_bits=128,
        )
        big_p_horizon = big_parameters.omega - BigFloat(big_parameters.m) *
            KERR.stable_horizon_geometry(big_parameters.a).omega_horizon
        big_convention = gsn_branch_convention(
            big_parameters.omega, big_p_horizon
        )
        @test_throws AEC.AsymptoticConstructionError factored_infinity_outgoing_initialconditions(
            big_bundle.infinity_outgoing,
            0.25,
            BigFloat("0.125"),
            _ -> complex(BigFloat("12"), BigFloat("0.1")),
            big_convention,
            RegularRemainderContract(),
        )
    end
end

@testset "negative-rstar BigFloat inverse round trip" begin
    setprecision(BigFloat, 192) do
        a = parse(BigFloat, "0.4")
        geometry = GSN.Kerr.stable_horizon_geometry(a)
        match_radius = geometry.rplus + parse(BigFloat, "0.01")
        rstar_match = rstar_from_r(a, match_radius)
        @test rstar_match < zero(BigFloat)
        recovered_radius = r_from_rstar(a, rstar_match)
        @test precision(recovered_radius) == 192
        @test isapprox(
            recovered_radius,
            match_radius;
            rtol=parse(BigFloat, "1e-50"),
            atol=parse(BigFloat, "1e-50"),
        )
    end
end

# The regularised propagation and scaled-scattering specifications remain
# load-bearing even while production activation is blocked on independent
# mathematical review and a frozen external reference fixture.
include("factored_propagation_spec.jl")
include("scaled_scattering_spec.jl")
