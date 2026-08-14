# This file is included by the package test runner after Task 1C integration.
# It is intentionally not executed in the implementation airgap session.

using Test
using DifferentialEquations

const CF_FACTORED = GeneralizedSasakiNakamura.ComplexFrequencies
const FS_FACTORED = GeneralizedSasakiNakamura.FactoredSolutions
const COORD_FACTORED = GeneralizedSasakiNakamura.Coordinates
const KERR_FACTORED = GeneralizedSasakiNakamura.Kerr
const POT_FACTORED = GeneralizedSasakiNakamura.Potentials

struct FactoredUnsuccessfulODESolution
    retcode::Symbol
end

struct FactoredExternalControlError <: Exception
    receipt::String
end

DifferentialEquations.SciMLBase.successful_retcode(
    ::FactoredUnsuccessfulODESolution
) = false

function factored_spec_parameters(::Type{T}) where {T<:AbstractFloat}
    return (
        s=-2,
        m=2,
        a=T(1) / T(5),
        omega=complex(T(2) / T(5), T(1) / T(20)),
        lambda=complex(T(4), T(1) / T(10)),
    )
end

function factored_spec_context(
    ::Type{T}; outer_radius::T=T(14)
) where {T<:AbstractFloat}
    parameters = factored_spec_parameters(T)
    geometry = KERR_FACTORED.stable_horizon_geometry(parameters.a)
    p_horizon = parameters.omega - T(parameters.m) *
        geometry.omega_horizon
    frozen = COORD_FACTORED.gsn_branch_convention(
        parameters.omega, p_horizon
    )
    decimal_digits = T === Float64 ? 15 : 40
    spectral = CF_FACTORED.build_homogeneous_spectral_context(
        parameters.s,
        parameters.m,
        parameters.a,
        parameters.omega,
        parameters.lambda,
        decimal_digits,
        precision(T),
        2,
        frozen,
    )
    match_radius = T(12)
    rstar_match = T(COORD_FACTORED.rstar_from_r(
        parameters.a, match_radius
    ))
    rho_in = -one(T)
    rho_out = one(T)
    radius_from_rho = function (rho::T)
        if rho < zero(T)
            return complex(geometry.rplus + T(1) / T(10), -T(1) / T(50))
        elseif rho > zero(T)
            return complex(outer_radius, T(1) / T(50))
        end
        return complex(match_radius, zero(T))
    end
    contour = CF_FACTORED.build_contour_context(
        spectral,
        match_radius,
        rstar_match,
        rho_in,
        rho_out,
        radius_from_rho,
    )
    return (spectral=spectral, contour=contour)
end

function exercise_transformed_rhs_identity(::Type{T}) where {T<:AbstractFloat}
    parameters = factored_spec_parameters(T)
    geometry = KERR_FACTORED.stable_horizon_geometry(parameters.a)
    p_horizon = parameters.omega - T(parameters.m) *
        geometry.omega_horizon
    convention = COORD_FACTORED.gsn_branch_convention(
        parameters.omega, p_horizon
    )
    carrier = FS_FACTORED.PlaneWaveCarrier(
        FS_FACTORED.INFINITY_OUTGOING,
        parameters.omega,
        T(1) / T(8),
        convention,
    )
    radius = complex(T(7) / T(2), T(1) / T(7))
    radius_from_rho = (_rho::T) -> radius
    tangent = Complex{T}(COORD_FACTORED.infinity_contour_tangent(convention))
    rhs_count = Ref(0)
    rhs_parameters = CF_FACTORED.FactoredGSNParameters(
        parameters.s,
        parameters.m,
        parameters.a,
        parameters.omega,
        parameters.lambda,
        radius_from_rho,
        tangent,
        carrier,
        precision(T),
        rhs_count[],
        rhs_count,
    )
    state = Complex{T}[
        complex(T(3) / T(2), -T(2) / T(5)),
        complex(-T(1) / T(3), T(4) / T(7)),
    ]
    derivative = similar(state)
    rho = T(1) / T(9)
    CF_FACTORED.factored_GSN_linear_eqn!(
        derivative, state, rhs_parameters, rho
    )

    A = FS_FACTORED.carrier_value(carrier, rho)
    q = FS_FACTORED.carrier_log_derivative(carrier)
    q_rho = FS_FACTORED.carrier_log_derivative_derivative(carrier)
    X = A * state[1]
    Xrho = A * (state[2] + q * state[1])
    reconstructed_Xrhorho = A * (
        derivative[2] + 2 * q * state[2] +
        (q_rho + q^2) * state[1]
    )
    F_rho = tangent * POT_FACTORED.sF(
        parameters.s,
        parameters.m,
        parameters.a,
        parameters.omega,
        parameters.lambda,
        radius,
    )
    U_rho = tangent^2 * POT_FACTORED.sU(
        parameters.s,
        parameters.m,
        parameters.a,
        parameters.omega,
        parameters.lambda,
        radius,
    )
    tolerance = T(2048) * eps(T)
    @test derivative[1] == state[2]
    @test reconstructed_Xrhorho ≈ F_rho * Xrho + U_rho * X rtol=tolerance
    @test rhs_count[] == 1
end

@testset "transformed factored RHS identity" begin
    exercise_transformed_rhs_identity(Float64)
    setprecision(BigFloat, 192) do
        exercise_transformed_rhs_identity(BigFloat)
    end
end

@testset "production carriers have q_rho zero" begin
    prepared = factored_spec_context(Float64)
    for kind in (
        FS_FACTORED.INFINITY_OUTGOING,
        FS_FACTORED.HORIZON_INGOING,
        FS_FACTORED.HORIZON_OUTGOING,
    )
        wave_number = kind === FS_FACTORED.INFINITY_OUTGOING ?
            prepared.spectral.omega : prepared.spectral.p_horizon
        carrier = FS_FACTORED.PlaneWaveCarrier(
            kind,
            wave_number,
            prepared.contour.rstar_match,
            prepared.spectral.convention,
        )
        @test FS_FACTORED.carrier_log_derivative_derivative(carrier) ==
            zero(ComplexF64)
    end
end

@testset "inadequate preflight performs zero factored homogeneous RHS evaluations" begin
    prepared = factored_spec_context(Float64)
    branch = CF_FACTORED.prepare_factored_infinity_outgoing(
        prepared.spectral, prepared.contour, 1.0e6
    )
    rhs_count = Ref(0)
    observer_factory_calls = Ref(0)
    observer_factory = function (_leg, _span, _algorithm)
        observer_factory_calls[] += 1
        return nothing, nothing
    end
    error = try
        CF_FACTORED.solve_factored_endpoint(
            prepared.spectral,
            prepared.contour,
            branch,
            prepared.contour.rho_out,
            zero(Float64);
            ode_leg="test_inadequate",
            factored_homogeneous_rhs_counter=rhs_count,
            ode_observation_factory=observer_factory,
        )
        nothing
    catch caught
        caught
    end
    @test error isa CF_FACTORED.FactoredPropagationError
    @test error.reason == CF_FACTORED.INSUFFICIENT_ASYMPTOTIC_PRECISION
    @test error.avoided_ode_scope ==
        CF_FACTORED.FACTORED_HOMOGENEOUS_ODE_SCOPE_ID
    @test error.factored_homogeneous_rhs_evaluations == 0
    @test rhs_count[] == 0
    @test observer_factory_calls[] == 0
end

@testset "adequate preflight executes the public numerical solver" begin
    prepared = factored_spec_context(Float64; outer_radius=1.0e12)
    branch = CF_FACTORED.prepare_factored_infinity_outgoing(
        prepared.spectral, prepared.contour, 0.0
    )
    rhs_count = Ref(0)
    observer_factory_calls = Ref(0)
    solution = CF_FACTORED.solve_factored_endpoint(
        prepared.spectral,
        prepared.contour,
        branch,
        prepared.contour.rho_out,
        zero(Float64);
        ode_leg="test_public_numerical_solver",
        factored_homogeneous_rhs_counter=rhs_count,
        ode_observation_factory=(_leg, _span, _algorithm) -> begin
            observer_factory_calls[] += 1
            (nothing, nothing)
        end,
    )
    @test solution isa CF_FACTORED.FactoredODESolution{Float64}
    @test solution.diagnostics.factored_homogeneous_rhs_evaluations > 0
    @test rhs_count[] > 0
    @test observer_factory_calls[] == 1
end

@testset "carrier transition executes the public match-to-inner solver" begin
    prepared = factored_spec_context(Float64)
    horizon = CF_FACTORED.prepare_factored_horizon_ingoing(
        prepared.spectral, prepared.contour, 0.0
    )
    infinity_carrier = FS_FACTORED.PlaneWaveCarrier(
        FS_FACTORED.INFINITY_OUTGOING,
        prepared.spectral.omega,
        prepared.contour.rstar_match,
        prepared.spectral.convention,
    )
    transition = CF_FACTORED.change_factored_infinity_to_horizon_at_match(
        prepared.spectral,
        prepared.contour,
        FS_FACTORED.FactoredEndpointState(1.0 + 0.0im, 0.0 + 0.0im),
        infinity_carrier,
    )
    rhs_count = Ref(0)
    solution = CF_FACTORED.solve_factored_horizon_match_to_inner(
        prepared.spectral,
        prepared.contour,
        horizon,
        transition;
        ode_leg="test_public_match_to_inner_solver",
        factored_homogeneous_rhs_counter=rhs_count,
    )
    @test solution isa CF_FACTORED.FactoredODESolution{Float64}
    @test solution.diagnostics.factored_homogeneous_rhs_evaluations > 0
    @test rhs_count[] > 0
end

@testset "compatible contour deformation and branch crossing rejection" begin
    central = factored_spec_parameters(Float64)
    central_geometry = KERR_FACTORED.stable_horizon_geometry(central.a)
    central_p = central.omega - central.m * central_geometry.omega_horizon
    frozen = COORD_FACTORED.gsn_branch_convention(central.omega, central_p)

    deformed_omega = central.omega + 0.02im
    compatible = CF_FACTORED.build_homogeneous_spectral_context(
        central.s,
        central.m,
        central.a,
        deformed_omega,
        central.lambda,
        15,
        precision(Float64),
        2,
        frozen,
    )
    @test compatible.contour_deformation.maximum_absolute > 0.0
    @test compatible.frozen_branch_cell == COORD_FACTORED.branch_cell(frozen)

    crossing_error = try
        CF_FACTORED.build_homogeneous_spectral_context(
            central.s,
            central.m,
            central.a,
            complex(-real(central.omega), imag(central.omega)),
            central.lambda,
            15,
            precision(Float64),
            2,
            frozen,
        )
        nothing
    catch caught
        caught
    end
    @test crossing_error isa CF_FACTORED.FactoredPropagationError
    @test crossing_error.reason == CF_FACTORED.CARRIER_CHANGE_INCONSISTENT
end

@testset "carrier change preserves X and Xrho at rho zero" begin
    prepared = factored_spec_context(Float64)
    source = FS_FACTORED.PlaneWaveCarrier(
        FS_FACTORED.INFINITY_OUTGOING,
        prepared.spectral.omega,
        prepared.contour.rstar_match,
        prepared.spectral.convention,
    )
    state = FS_FACTORED.FactoredEndpointState(1.5 - 0.2im, -0.3 + 0.4im)
    transition = CF_FACTORED.change_factored_infinity_to_horizon_at_match(
        prepared.spectral, prepared.contour, state, source
    )
    raw_before = FS_FACTORED.reconstruct_state(state, source, 0.0)
    raw_after = FS_FACTORED.reconstruct_state(
        transition.state, transition.target_carrier, 0.0
    )
    @test raw_after.X ≈ raw_before.X
    @test raw_after.Xrho ≈ raw_before.Xrho
    @test transition.diagnostics.X_reconstruction_error <= 256eps(Float64)
    @test transition.diagnostics.Xrho_reconstruction_error <= 256eps(Float64)
end

@testset "Float64 and BigFloat branch preparation" begin
    function exercise(::Type{T}) where {T<:AbstractFloat}
        prepared = factored_spec_context(T)
        required_digits = zero(T)
        horizon = CF_FACTORED.prepare_factored_horizon_determinant_branches(
            prepared.spectral, prepared.contour, required_digits
        )
        @test horizon.infinity_outgoing.initial_condition isa
            GeneralizedSasakiNakamura.InitialConditions.FactoredInitialCondition{T}
        @test horizon.horizon_ingoing.assessment.precision_bits == precision(T)
        @test horizon.horizon_outgoing.required_digits == required_digits
    end
    exercise(Float64)
    setprecision(BigFloat, 192) do
        exercise(BigFloat)
    end
end

@testset "external callback is retained before internal diagnostics" begin
    condition = (_u, _t, _integrator) -> false
    affect! = _integrator -> nothing
    external = DiscreteCallback(condition, affect!)
    internal = DiscreteCallback(condition, affect!)
    @test CF_FACTORED._combine_factored_callbacks(nothing, internal) === internal
    combined = CF_FACTORED._combine_factored_callbacks(external, internal)
    @test combined isa CallbackSet
    @test combined !== internal
end

@testset "endpoint-only result contract" begin
    names = fieldnames(CF_FACTORED.FactoredODESolution{Float64})
    @test :endpoint in names
    @test :diagnostics in names
    @test :solution ∉ names
    @test :trajectory ∉ names
end

@testset "infinity and horizon match derivative conversion" begin
    prepared = factored_spec_context(Float64)
    state = FS_FACTORED.FactoredEndpointState(1.2 - 0.1im, -0.4 + 0.3im)
    for kind in (
        FS_FACTORED.INFINITY_OUTGOING,
        FS_FACTORED.HORIZON_INGOING,
    )
        wave_number = kind === FS_FACTORED.INFINITY_OUTGOING ?
            prepared.spectral.omega : prepared.spectral.p_horizon
        carrier = FS_FACTORED.PlaneWaveCarrier(
            kind,
            wave_number,
            prepared.contour.rstar_match,
            prepared.spectral.convention,
        )
        converted = CF_FACTORED.reconstruct_factored_match_state(
            state, carrier, 0.0, prepared.spectral, prepared.contour
        )
        raw = FS_FACTORED.reconstruct_state(state, carrier, 0.0)
        tangent = kind === FS_FACTORED.INFINITY_OUTGOING ?
            prepared.contour.infinity_tangent :
            prepared.contour.horizon_tangent
        @test converted.X == raw.X
        @test converted.Xrho == raw.Xrho
        @test converted.dX_drstar ≈ raw.Xrho / tangent
    end
end

@testset "BigFloat provenance is structural and ambient-precision independent" begin
    prepared, branch = setprecision(BigFloat, 192) do
        sample = factored_spec_context(BigFloat)
        endpoint = CF_FACTORED.prepare_factored_infinity_outgoing(
            sample.spectral, sample.contour, zero(BigFloat)
        )
        (sample, endpoint)
    end
    @test precision(prepared.spectral.a) == 192
    setprecision(BigFloat, 96) do
        @test CF_FACTORED._assert_preparation_provenance(
            prepared.spectral, prepared.contour, branch
        ) === nothing
    end
end

@testset "inconsistent match radius and tortoise coordinate are rejected" begin
    prepared = factored_spec_context(Float64)
    error = try
        CF_FACTORED.build_contour_context(
            prepared.spectral,
            prepared.contour.match_radius,
            nextfloat(prepared.contour.rstar_match),
            prepared.contour.rho_in,
            prepared.contour.rho_out,
            prepared.contour.radius_from_rho,
        )
        nothing
    catch caught
        caught
    end
    @test error isa CF_FACTORED.FactoredPropagationError
    @test error.reason == CF_FACTORED.INVALID_FACTORED_PROPAGATION_INPUT
end

@testset "inadequate evidence is authenticated before promotion" begin
    prepared = factored_spec_context(Float64)
    authentic = CF_FACTORED.prepare_factored_infinity_outgoing(
        prepared.spectral, prepared.contour, 1.0e6
    )
    @test !authentic.assessment.adequate
    forged = CF_FACTORED.FactoredEndpointPreparation{Float64}(
        authentic.branch,
        authentic.initial_condition,
        authentic.assessment,
        authentic.required_digits,
        authentic.precision_bits,
        authentic.endpoint_order + 1,
        authentic.frozen_branch_cell,
        authentic.contour_deformation,
    )
    rhs_count = Ref(0)
    error = try
        CF_FACTORED.solve_factored_endpoint(
            prepared.spectral,
            prepared.contour,
            forged,
            prepared.contour.rho_out,
            zero(Float64);
            factored_homogeneous_rhs_counter=rhs_count,
        )
        nothing
    catch caught
        caught
    end
    @test error isa CF_FACTORED.FactoredPropagationError
    @test error.reason == CF_FACTORED.INVALID_FACTORED_PROPAGATION_INPUT
    @test error.reason != CF_FACTORED.INSUFFICIENT_ASYMPTOTIC_PRECISION
    @test error.factored_homogeneous_rhs_evaluations == 0
    @test rhs_count[] == 0
end

@testset "forged carrier fields are rejected" begin
    prepared = factored_spec_context(Float64)
    canonical = FS_FACTORED.PlaneWaveCarrier(
        FS_FACTORED.INFINITY_OUTGOING,
        prepared.spectral.omega,
        prepared.contour.rstar_match,
        prepared.spectral.convention,
    )
    forged = FS_FACTORED.PlaneWaveCarrier{Float64}(
        canonical.kind,
        canonical.wave_number,
        canonical.rstar_match,
        canonical.log_at_match,
        canonical.q + one(ComplexF64),
        canonical.convention,
    )
    state = FS_FACTORED.FactoredEndpointState(1.0 + 0.0im, 0.0 + 0.0im)
    error = try
        CF_FACTORED.change_factored_infinity_to_horizon_at_match(
            prepared.spectral, prepared.contour, state, forged
        )
        nothing
    catch caught
        caught
    end
    @test error isa CF_FACTORED.FactoredPropagationError
    @test error.reason == CF_FACTORED.CARRIER_CHANGE_INCONSISTENT
end

@testset "all determinant branches are authenticated before the first ODE" begin
    prepared = factored_spec_context(Float64)
    authentic = CF_FACTORED.prepare_factored_horizon_determinant_branches(
        prepared.spectral, prepared.contour, 0.0
    )
    outgoing = authentic.horizon_outgoing
    forged_outgoing = CF_FACTORED.FactoredEndpointPreparation{Float64}(
        outgoing.branch,
        outgoing.initial_condition,
        outgoing.assessment,
        outgoing.required_digits,
        outgoing.precision_bits,
        outgoing.endpoint_order + 1,
        outgoing.frozen_branch_cell,
        outgoing.contour_deformation,
    )
    forged = CF_FACTORED.HorizonDeterminantPreparation{Float64}(
        authentic.infinity_outgoing,
        authentic.horizon_ingoing,
        forged_outgoing,
    )
    rhs_count = Ref(0)
    error = try
        CF_FACTORED.solve_factored_xup_scattering_endpoint(
            prepared.spectral,
            prepared.contour,
            forged;
            factored_homogeneous_rhs_counter=rhs_count,
        )
        nothing
    catch caught
        caught
    end
    @test error isa CF_FACTORED.FactoredPropagationError
    @test error.reason == CF_FACTORED.INVALID_FACTORED_PROPAGATION_INPUT
    @test rhs_count[] == 0
end

@testset "external callback executes before internal diagnostics" begin
    condition = (_u, _t, _integrator) -> false
    external = DiscreteCallback(condition, _integrator -> nothing)
    internal = DiscreteCallback(condition, _integrator -> nothing)
    combined = CF_FACTORED._combine_factored_callbacks(external, internal)
    @test combined.discrete_callbacks[1] === external
    @test combined.discrete_callbacks[2] === internal
end

@testset "nonfinite RHS and unsuccessful retcodes fail loudly" begin
    prepared = factored_spec_context(Float64)
    carrier = FS_FACTORED.PlaneWaveCarrier(
        FS_FACTORED.INFINITY_OUTGOING,
        prepared.spectral.omega,
        prepared.contour.rstar_match,
        prepared.spectral.convention,
    )
    rhs_count = Ref(12)
    parameters = CF_FACTORED.FactoredGSNParameters(
        prepared.spectral.s,
        prepared.spectral.m,
        prepared.spectral.a,
        prepared.spectral.omega,
        prepared.spectral.lambda,
        prepared.contour.radius_from_rho,
        prepared.contour.infinity_tangent,
        carrier,
        prepared.spectral.precision_bits,
        rhs_count[],
        rhs_count,
    )
    nonfinite_state = ComplexF64[complex(NaN, 0.0), 0.0 + 0.0im]
    derivative = similar(nonfinite_state)
    rhs_error = try
        CF_FACTORED.factored_GSN_linear_eqn!(
            derivative, nonfinite_state, parameters, 0.0
        )
        nothing
    catch caught
        caught
    end
    @test rhs_error isa CF_FACTORED.FactoredPropagationError
    @test rhs_error.reason == CF_FACTORED.NONFINITE_FACTORED_PROPAGATION_DATA
    @test rhs_error.factored_homogeneous_rhs_evaluations == 1
    @test rhs_count[] == 13

    branch = CF_FACTORED.prepare_factored_infinity_outgoing(
        prepared.spectral, prepared.contour, 0.0
    )
    result_error = try
        CF_FACTORED._assert_successful_factored_ode_result(
            FactoredUnsuccessfulODESolution(:MaxIters),
            Float64,
            prepared.spectral.precision_bits,
            branch.assessment,
            7,
        )
        nothing
    catch caught
        caught
    end
    @test result_error isa CF_FACTORED.FactoredPropagationError
    @test result_error.reason == CF_FACTORED.FACTORED_ODE_FAILURE
    @test result_error.factored_homogeneous_rhs_evaluations == 7
end

@testset "physical zero-frequency limits retain their taxonomy" begin
    parameters = factored_spec_parameters(Float64)
    geometry = KERR_FACTORED.stable_horizon_geometry(parameters.a)
    p_horizon = parameters.omega - parameters.m * geometry.omega_horizon
    frozen = COORD_FACTORED.gsn_branch_convention(
        parameters.omega, p_horizon
    )
    zero_omega_error = try
        CF_FACTORED.build_homogeneous_spectral_context(
            parameters.s,
            parameters.m,
            parameters.a,
            zero(parameters.omega),
            parameters.lambda,
            15,
            precision(Float64),
            2,
            frozen,
        )
        nothing
    catch caught
        caught
    end
    @test zero_omega_error isa CF_FACTORED.FactoredPropagationError
    @test zero_omega_error.reason ==
        GeneralizedSasakiNakamura.AsymptoticExpansionCoefficients.PHYSICAL_SINGULAR_LIMIT

    coalescing_omega = complex(
        parameters.m * geometry.omega_horizon, 0.0
    )
    zero_p_error = try
        CF_FACTORED.build_homogeneous_spectral_context(
            parameters.s,
            parameters.m,
            parameters.a,
            coalescing_omega,
            parameters.lambda,
            15,
            precision(Float64),
            2,
            frozen,
        )
        nothing
    catch caught
        caught
    end
    @test zero_p_error isa CF_FACTORED.FactoredPropagationError
    @test zero_p_error.reason ==
        GeneralizedSasakiNakamura.AsymptoticExpansionCoefficients.PHYSICAL_SINGULAR_LIMIT
end


@testset "external ODE control exceptions preserve their typed receipt" begin
    prepared = factored_spec_context(Float64)
    branch = CF_FACTORED.prepare_factored_infinity_outgoing(
        prepared.spectral, prepared.contour, 0.0
    )
    external = FactoredExternalControlError("resource-receipt-17")
    passthrough = error -> error isa FactoredExternalControlError
    preserved = try
        CF_FACTORED._throw_or_wrap_factored_ode_failure(
            external,
            passthrough,
            Float64,
            prepared.spectral.precision_bits,
            branch.assessment,
            9,
        )
        nothing
    catch caught
        caught
    end
    @test preserved === external
    @test preserved.receipt == "resource-receipt-17"

    wrapped = try
        CF_FACTORED._throw_or_wrap_factored_ode_failure(
            ErrorException("genuine solver failure"),
            passthrough,
            Float64,
            prepared.spectral.precision_bits,
            branch.assessment,
            11,
        )
        nothing
    catch caught
        caught
    end
    @test wrapped isa CF_FACTORED.FactoredPropagationError
    @test wrapped.reason == CF_FACTORED.FACTORED_ODE_FAILURE
    @test wrapped.factored_homogeneous_rhs_evaluations == 11
end

@testset "synthetic nonzero q_rho transformed algebra" begin
    Y = 1.2 - 0.7im
    Yrho = -0.4 + 0.9im
    F_rho = 0.3 + 0.2im
    U_rho = -0.8 + 0.1im
    q = 0.6 - 0.5im
    q_rho = -0.2 + 0.4im
    A = 1.1 + 0.3im
    Yrhorho = CF_FACTORED._factored_transformed_rhs_second(
        Y, Yrho, F_rho, U_rho, q, q_rho
    )
    X = A * Y
    Xrho = A * (Yrho + q * Y)
    Xrhorho = A * (
        Yrhorho + 2q * Yrho + (q_rho + q^2) * Y
    )
    @test !iszero(q_rho)
    @test Xrhorho ≈ F_rho * Xrho + U_rho * X
end
