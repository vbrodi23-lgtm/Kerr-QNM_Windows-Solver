# This file is included by the package test runner after Task 1D integration.
# It is intentionally not executed in the implementation airgap session.

const SOL = GeneralizedSasakiNakamura.Solutions
const FS = GeneralizedSasakiNakamura.FactoredSolutions
const IC_SCATTERING = GeneralizedSasakiNakamura.InitialConditions
const COORD_SCATTERING = GeneralizedSasakiNakamura.Coordinates
const AEC_SCATTERING = GeneralizedSasakiNakamura.AsymptoticExpansionCoefficients
const KERR_SCATTERING = GeneralizedSasakiNakamura.Kerr

function synthetic_basis(::Type{T}, scale_1::T, scale_2::T) where {T<:AbstractFloat}
    precision_bits = precision(T)
    omega = complex(T(2) / T(5), T(1) / T(20))
    p_horizon = complex(T(1) / T(3), T(1) / T(20))
    convention = COORD_SCATTERING.gsn_branch_convention(
        omega, p_horizon
    )
    common_carrier = FS.PlaneWaveCarrier(
        FS.HORIZON_INGOING, p_horizon, zero(T), convention
    )
    outgoing_source_carrier = FS.PlaneWaveCarrier(
        FS.HORIZON_OUTGOING, p_horizon, zero(T), convention
    )
    column_1 = FS.FactoredEndpointState{T}(
        complex(scale_1, zero(T)), zero(Complex{T})
    )
    column_2 = FS.FactoredEndpointState{T}(
        zero(Complex{T}), complex(scale_2, zero(T))
    )
    diagnostics = FS.CarrierChangeDiagnostics{T}(
        zero(T), zero(T), one(T), zero(T)
    )
    return SOL.CommonCarrierHorizonBasis{T}(
        column_1,
        column_2,
        common_carrier,
        outgoing_source_carrier,
        nothing,
        zero(T),
        zero(Complex{T}),
        precision_bits,
        FS.RegularRemainderContract(),
        diagnostics,
    )
end

function synthetic_basis_from_columns(
    column_1::FS.FactoredEndpointState{T},
    column_2::FS.FactoredEndpointState{T},
) where {T<:AbstractFloat}
    template = synthetic_basis(T, one(T), one(T))
    return SOL.CommonCarrierHorizonBasis{T}(
        column_1,
        column_2,
        template.common_carrier,
        template.outgoing_source_carrier,
        template.carrier_tangent,
        template.rho_endpoint,
        template.r_endpoint,
        template.precision_bits,
        template.contract,
        template.carrier_change,
    )
end

function exercise_scaled_scattering(::Type{T}) where {T<:AbstractFloat}
    basis = synthetic_basis(T, T(10)^T(40), T(10)^(-T(40)))
    expected_cref = complex(T(3) / T(2), T(1) / T(4))
    expected_cinc = complex(-T(5) / T(4), T(2) / T(3))
    target = FS.FactoredEndpointState{T}(
        expected_cref * basis.column_1.Y + expected_cinc * basis.column_2.Y,
        expected_cref * basis.column_1.Yrho + expected_cinc * basis.column_2.Yrho,
    )
    result = SOL.solve_scaled_factored_scattering(
        target, basis.common_carrier, basis
    )
    tolerance = T(256) * eps(T)

    @test result.Cref ≈ expected_cref rtol=tolerance
    @test result.Cinc ≈ expected_cinc rtol=tolerance
    @test result.reconstructed_endpoint.Y ≈ target.Y rtol=tolerance
    @test result.reconstructed_endpoint.Yrho ≈ target.Yrho rtol=tolerance
    @test result.diagnostics.matching_reconstruction_residual <= tolerance
    @test result.diagnostics.backward_error <= tolerance
    @test result.diagnostics.condition_frobenius ≈ T(2) rtol=tolerance
    @test result.diagnostics.column_norm_1 != result.diagnostics.column_norm_2
    @test result.diagnostics.legacy_comparator_available
    @test result.diagnostics.legacy_comparator_failure_reason === nothing
    @test something(result.diagnostics.legacy_Cref) ≈ result.Cref rtol=tolerance
    @test something(result.diagnostics.legacy_Cinc) ≈ result.Cinc rtol=tolerance

    legacy = SOL.unscaled_cramer_scattering_coefficients(
        target, basis.column_1, basis.column_2, basis.precision_bits
    )
    @test legacy.Cref ≈ result.Cref rtol=tolerance
    @test legacy.Cinc ≈ result.Cinc rtol=tolerance
end

@testset "widely separated column norms and matching reconstruction residual" begin
    exercise_scaled_scattering(Float64)
    setprecision(BigFloat, 192) do
        exercise_scaled_scattering(BigFloat)
    end
end

function exercise_coefficient_scale_and_phase_recovery(
    ::Type{T}
) where {T<:AbstractFloat}
    column_1 = FS.FactoredEndpointState{T}(
        complex(T(3), one(T)), complex(T(2), -one(T))
    )
    column_2 = FS.FactoredEndpointState{T}(
        complex(T(-3), -one(T)), complex(one(T), T(2))
    )
    basis = synthetic_basis_from_columns(column_1, column_2)
    small = sqrt(eps(T))
    phase = complex(one(T), one(T))
    cases = (
        (cref=complex(T(5) / T(4), T(3) / T(4)),
         cinc=complex(-one(T) / T(2), T(3) / T(2))),
        (cref=complex(one(T), -one(T) / T(4)),
         cinc=small * complex(one(T) / T(2), one(T))),
        (cref=small * complex(one(T), -one(T) / T(2)),
         cinc=complex(-T(3) / T(4), one(T) / T(4))),
        (cref=phase, cinc=phase * (one(T) - small)),
    )
    relative_tolerance = T(32) * sqrt(eps(T))
    absolute_tolerance = T(256) * eps(T)
    for case in cases
        target = FS.FactoredEndpointState{T}(
            case.cref * column_1.Y + case.cinc * column_2.Y,
            case.cref * column_1.Yrho + case.cinc * column_2.Yrho,
        )
        result = SOL.solve_scaled_factored_scattering(
            target, basis.common_carrier, basis
        )
        @test isapprox(
            result.Cref,
            case.cref;
            rtol=relative_tolerance,
            atol=absolute_tolerance,
        )
        @test isapprox(
            result.Cinc,
            case.cinc;
            rtol=relative_tolerance,
            atol=absolute_tolerance,
        )
        @test result.diagnostics.matching_reconstruction_residual <=
            relative_tolerance
        @test result.reconstructed_endpoint.Y ≈ target.Y rtol=relative_tolerance
        @test result.reconstructed_endpoint.Yrho ≈ target.Yrho rtol=relative_tolerance
    end
end

@testset "table-driven coefficient-scale and phase recovery" begin
    exercise_coefficient_scale_and_phase_recovery(Float64)
    setprecision(BigFloat, 192) do
        exercise_coefficient_scale_and_phase_recovery(BigFloat)
    end
end

@testset "BigFloat origin precision" begin
    prepared = setprecision(BigFloat, 192) do
        basis = synthetic_basis(
            BigFloat,
            parse(BigFloat, "1e60"),
            parse(BigFloat, "1e-60"),
        )
        target = FS.FactoredEndpointState{BigFloat}(
            complex(parse(BigFloat, "2e60"), zero(BigFloat)),
            complex(parse(BigFloat, "-3e-60"), zero(BigFloat)),
        )
        chart_inputs = SOL.ScatteringChartErrorInputs{BigFloat}(
            one(BigFloat),
            parse(BigFloat, "1e-40"),
            parse(BigFloat, "1e-35"),
        )
        reflectivity = complex(
            parse(BigFloat, "0.2"), parse(BigFloat, "0.05")
        )
        (
            basis=basis,
            target=target,
            chart_inputs=chart_inputs,
            reflectivity=reflectivity,
        )
    end
    setprecision(BigFloat, 96) do
        result = SOL.solve_scaled_factored_scattering(
            prepared.target,
            prepared.basis.common_carrier,
            prepared.basis,
        )
        @test result.diagnostics.precision_bits == 192
        @test precision(real(result.Cref)) == 192
        @test precision(result.diagnostics.condition_frobenius) == 192
        assessment = SOL.assess_horizon_determinant_chart(
            result, prepared.reflectivity, prepared.chart_inputs
        )
        @test precision(assessment.estimated_cref_error) == 192
        @test precision(assessment.raw_determinant_abs) == 192
    end
end

@testset "unscaled Cramer comparator" begin
    basis = synthetic_basis(Float64, 3.0, 7.0)
    target = FS.FactoredEndpointState{Float64}(2.0 + 0im, -5.0 + 0im)
    scaled = SOL.solve_scaled_factored_scattering(
        target, basis.common_carrier, basis
    )
    legacy = SOL.unscaled_cramer_scattering_coefficients(
        target, basis.column_1, basis.column_2, 53
    )
    @test scaled.Cref ≈ legacy.Cref
    @test scaled.Cinc ≈ legacy.Cinc
end

@testset "non-diagonal analytic condition estimate" begin
    column_1 = FS.FactoredEndpointState{Float64}(3.0 + 0im, 0.0 + 0im)
    column_2 = FS.FactoredEndpointState{Float64}(3.0 + 0im, 4.0 + 0im)
    basis = synthetic_basis_from_columns(column_1, column_2)
    expected_cref = 2.0 - 0.5im
    expected_cinc = -1.0 + 0.25im
    target = FS.FactoredEndpointState{Float64}(
        expected_cref * column_1.Y + expected_cinc * column_2.Y,
        expected_cref * column_1.Yrho + expected_cinc * column_2.Yrho,
    )
    result = SOL.solve_scaled_factored_scattering(
        target, basis.common_carrier, basis
    )
    @test result.Cref ≈ expected_cref
    @test result.Cinc ≈ expected_cinc
    @test result.diagnostics.condition_frobenius ≈ 2.5
    @test result.diagnostics.matching_reconstruction_residual <=
        64 * eps(Float64)
    @test result.diagnostics.backward_error <= 64 * eps(Float64)
end

@testset "scaled solve survives unavailable legacy comparator" begin
    cases = (
        (
            scale_1=1.0e308,
            scale_2=1.0e10,
            reason=SOL.NONFINITE_SCATTERING_DATA,
        ),
        (
            scale_1=1.0e-200,
            scale_2=1.0e-200,
            reason=SOL.SCATTERING_BASIS_ILL_CONDITIONED,
        ),
    )
    target = FS.FactoredEndpointState{Float64}(1.0 + 0im, 1.0 + 0im)
    for case in cases
        basis = synthetic_basis(Float64, case.scale_1, case.scale_2)
        result = SOL.solve_scaled_factored_scattering(
            target, basis.common_carrier, basis
        )
        @test !result.diagnostics.legacy_comparator_available
        @test result.diagnostics.legacy_comparator_failure_reason == case.reason
        @test result.diagnostics.legacy_Cref === nothing
        @test result.diagnostics.legacy_Cinc === nothing
        @test result.diagnostics.legacy_relative_disagreement_cref === nothing
        @test result.diagnostics.legacy_relative_disagreement_cinc === nothing
        @test result.reconstructed_endpoint.Y ≈ target.Y
        @test result.reconstructed_endpoint.Yrho ≈ target.Yrho
        @test result.diagnostics.matching_reconstruction_residual <= eps(Float64)
    end
end

@testset "safe normalised horizon chart survives raw diagnostic overflow" begin
    # Both coefficients are finite.  Their raw Cinc - R*Cref subtraction
    # overflows, while Cinc/Cref - R is finite and has a safe Cref margin.
    huge = Float64(0.75) * floatmax(Float64)
    basis = synthetic_basis(Float64, 1.0, 1.0)
    target = FS.FactoredEndpointState{Float64}(
        complex(huge, 0.0), complex(huge, 0.0)
    )
    coefficients = SOL.solve_scaled_factored_scattering(
        target, basis.common_carrier, basis
    )
    assessment = SOL.assess_horizon_determinant_chart(
        coefficients,
        -1.0 + 0.0im,
        huge / 128.0,
    )
    evaluation = SOL.evaluate_normalised_horizon_determinant(
        coefficients,
        -1.0 + 0.0im,
        huge / 128.0,
    )

    @test assessment.safe
    @test assessment.normalised_determinant == 2.0 + 0.0im
    @test assessment.normalised_determinant_abs == 2.0
    @test assessment.raw_determinant_evidence_status ==
        "unavailable-overflow/v1"
    @test assessment.raw_determinant === nothing
    @test assessment.raw_determinant_abs === nothing
    @test evaluation.value == assessment.normalised_determinant
end

@testset "near-dependent basis rejection" begin
    epsilon = eps(Float64) / 4
    column_1 = FS.FactoredEndpointState{Float64}(1.0 + 0im, 0.0 + 0im)
    column_2 = FS.FactoredEndpointState{Float64}(1.0 + 0im, epsilon + 0im)
    basis = synthetic_basis(Float64, 1.0, 1.0)
    basis = SOL.CommonCarrierHorizonBasis{Float64}(
        column_1,
        column_2,
        basis.common_carrier,
        basis.outgoing_source_carrier,
        basis.carrier_tangent,
        basis.rho_endpoint,
        basis.r_endpoint,
        basis.precision_bits,
        basis.contract,
        basis.carrier_change,
    )
    error = try
        SOL.solve_scaled_factored_scattering(
            column_1, basis.common_carrier, basis
        )
        nothing
    catch caught
        caught
    end
    @test error isa SOL.ScatteringExtractionError
    @test error.reason == SOL.SCATTERING_BASIS_ILL_CONDITIONED
end

@testset "forged target carrier rejection" begin
    basis = synthetic_basis(Float64, 2.0, 3.0)
    forged_carrier = FS.PlaneWaveCarrier{Float64}(
        basis.common_carrier.kind,
        -basis.common_carrier.wave_number,
        basis.common_carrier.rstar_match,
        basis.common_carrier.log_at_match,
        basis.common_carrier.q,
        basis.common_carrier.convention,
    )
    target = FS.FactoredEndpointState{Float64}(4.0 + 0im, 6.0 + 0im)
    error = try
        SOL.solve_scaled_factored_scattering(target, forged_carrier, basis)
        nothing
    catch caught
        caught
    end
    @test error isa SOL.ScatteringExtractionError
    @test error.reason == SOL.INVALID_SCATTERING_INPUT
end

@testset "forged carrier q and match log rejection" begin
    basis = synthetic_basis(Float64, 2.0, 3.0)
    canonical = basis.common_carrier
    forged_carriers = (
        FS.PlaneWaveCarrier{Float64}(
            canonical.kind,
            canonical.wave_number,
            canonical.rstar_match,
            canonical.log_at_match,
            canonical.q + (1.0 + 0im),
            canonical.convention,
        ),
        FS.PlaneWaveCarrier{Float64}(
            canonical.kind,
            canonical.wave_number,
            canonical.rstar_match,
            canonical.log_at_match + (1.0 + 0im),
            canonical.q,
            canonical.convention,
        ),
    )
    target = FS.FactoredEndpointState{Float64}(4.0 + 0im, 6.0 + 0im)
    for forged_carrier in forged_carriers
        error = try
            SOL.solve_scaled_factored_scattering(
                target, forged_carrier, basis
            )
            nothing
        catch caught
            caught
        end
        @test error isa SOL.ScatteringExtractionError
        @test error.reason == SOL.INVALID_SCATTERING_INPUT
    end
end

@testset "raw and normalised determinant equivalence and strict chart safety boundary" begin
    basis = synthetic_basis(Float64, 2.0, 3.0)
    target = FS.FactoredEndpointState{Float64}(4.0 + 0im, 6.0 + 0im)
    coefficients = SOL.solve_scaled_factored_scattering(
        target, basis.common_carrier, basis
    )
    reflectivity = 0.25 + 0.1im
    cref_abs = abs(coefficients.Cref)

    safe_error = cref_abs / 65
    safe = SOL.assess_horizon_determinant_chart(
        coefficients, reflectivity, safe_error
    )
    @test safe.safe
    @test SOL.raw_scattering_determinant(coefficients, reflectivity) ≈
        safe.raw_determinant
    @test safe.raw_determinant ≈
        coefficients.Cref * something(safe.normalised_determinant)
    @test safe.equivalence_disagreement_abs ≈ abs(
        something(safe.raw_determinant) / coefficients.Cref -
        something(safe.normalised_determinant)
    )
    @test safe.equivalence_disagreement_abs >= 0
    @test safe.equivalence_relative_error <= 32 * eps(Float64)

    boundary = SOL.assess_horizon_determinant_chart(
        coefficients, reflectivity, cref_abs / 64
    )
    @test !boundary.safe
    @test_throws SOL.ScatteringExtractionError SOL.evaluate_normalised_horizon_determinant(
        coefficients, reflectivity, cref_abs / 64
    )
end

@testset "exact-root cancellation saturation" begin
    basis = synthetic_basis(Float64, 2.0, 3.0)
    target = FS.FactoredEndpointState{Float64}(4.0 + 0im, 6.0 + 0im)
    coefficients = SOL.solve_scaled_factored_scattering(
        target, basis.common_carrier, basis
    )
    reflectivity = one(ComplexF64)
    assessment = SOL.assess_horizon_determinant_chart(
        coefficients, reflectivity, abs(coefficients.Cref) / 65
    )
    @test assessment.safe
    @test assessment.raw_determinant == zero(ComplexF64)
    @test something(assessment.normalised_determinant) == zero(ComplexF64)
    @test assessment.raw_cancellation_ratio == floatmax(Float64)
    @test assessment.raw_cancellation_ratio_saturated
    evaluation = SOL.evaluate_normalised_horizon_determinant(
        coefficients, reflectivity, abs(coefficients.Cref) / 65
    )
    @test evaluation.value == zero(ComplexF64)
end

@testset "common-carrier horizon basis" begin
    parameters = (
        s=-2,
        m=2,
        a=0.4,
        omega=0.35 + 0.07im,
        lambda=4.2 + 0.1im,
    )
    order = 4
    bundle = AEC_SCATTERING.build_asymptotic_series_bundle(
        parameters.s,
        parameters.m,
        parameters.a,
        parameters.omega,
        parameters.lambda,
        order;
        precision_bits=precision(Float64),
    )
    geometry = KERR_SCATTERING.stable_horizon_geometry(parameters.a)
    p_horizon = parameters.omega - parameters.m * geometry.omega_horizon
    convention = COORD_SCATTERING.gsn_branch_convention(
        parameters.omega, p_horizon
    )
    rho = zero(Float64)
    rstar_match = 0.125
    radius = complex(geometry.rplus + 0.02, -0.01)
    radius_from_rho = _ -> radius
    contract = FS.RegularRemainderContract()
    ingoing = IC_SCATTERING.factored_horizon_ingoing_initialconditions(
        bundle.horizon_ingoing,
        rho,
        rstar_match,
        radius_from_rho,
        convention,
        contract,
    )
    outgoing = IC_SCATTERING.factored_horizon_outgoing_initialconditions(
        bundle.horizon_outgoing,
        rho,
        rstar_match,
        radius_from_rho,
        convention,
        contract,
    )
    basis = SOL.build_common_horizon_basis(ingoing, outgoing)
    expected_outgoing = FS.change_carrier(
        outgoing.state,
        outgoing.carrier,
        ingoing.carrier,
        rho,
    )
    @test basis.column_1 == ingoing.state
    @test basis.column_2 == expected_outgoing
    @test basis.common_carrier.kind == FS.HORIZON_INGOING
    @test basis.outgoing_source_carrier.kind == FS.HORIZON_OUTGOING
    @test isequal(basis.common_carrier.wave_number, p_horizon)
    @test isequal(basis.outgoing_source_carrier.wave_number, p_horizon)
    @test basis.contract.identity == FS.regular_remainder_contract
    @test basis.rho_endpoint == rho
    @test basis.r_endpoint == radius
    raw_before = FS.reconstruct_state(
        outgoing.state, outgoing.carrier, rho
    )
    raw_after = FS.reconstruct_state(
        basis.column_2, basis.common_carrier, rho
    )
    @test raw_after.X ≈ raw_before.X
    @test raw_after.Xrho ≈ raw_before.Xrho
    @test basis.carrier_change.carrier_ratio_magnitude > 0
end
