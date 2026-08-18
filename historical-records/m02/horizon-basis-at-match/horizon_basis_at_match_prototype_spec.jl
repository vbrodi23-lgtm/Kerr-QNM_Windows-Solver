using Test

const PROTOTYPE_PATH = normpath(joinpath(
    @__DIR__, "..", "..", "..", "..", "tools",
    "benchmark_leaf13_horizon_basis_at_match.jl",
))
include(PROTOTYPE_PATH)

@testset "explicit-tangent carrier preserves physical match state" begin
    setprecision(BigFloat, 192) do
        T = BigFloat
        omega = Complex{T}(T("0.7"), T("-0.15"))
        p_horizon = Complex{T}(T("0.02"), T("-0.16"))
        convention = GSN.Coordinates.gsn_branch_convention(
            omega, p_horizon
        )
        tangent = Complex{T}(one(T), zero(T))
        carrier = explicit_tangent_carrier(
            HORIZON_INGOING,
            p_horizon,
            T("1.25"),
            convention,
            tangent,
        )
        X = Complex{T}(T("1.2"), T("-0.3"))
        dX_drstar = Complex{T}(T("-0.4"), T("0.8"))
        factored = factor_physical_match_state(
            X, dX_drstar, carrier, tangent
        )
        raw = reconstruct_state(factored, carrier, zero(T))

        @test raw.X ≈ X rtol=T("1e-50")
        @test raw.Xrho / tangent ≈ dX_drstar rtol=T("1e-50")
        @test carrier.q == -complex(zero(T), one(T)) *
            p_horizon * tangent
    end
end

@testset "scaled match basis recovers literal coefficients" begin
    setprecision(BigFloat, 192) do
        T = BigFloat
        column_1 = FactoredEndpointState{T}(
            Complex{T}(T("1e12"), T("2e12")),
            Complex{T}(T("-3e12"), T("4e12")),
        )
        column_2 = FactoredEndpointState{T}(
            Complex{T}(T("5e-12"), T("-2e-12")),
            Complex{T}(T("7e-12"), T("3e-12")),
        )
        expected_cref = Complex{T}(T("1.25"), T("-0.5"))
        expected_cinc = Complex{T}(T("-0.75"), T("0.125"))
        target = FactoredEndpointState{T}(
            expected_cref * column_1.Y + expected_cinc * column_2.Y,
            expected_cref * column_1.Yrho +
                expected_cinc * column_2.Yrho,
        )

        result = solve_scaled_match_basis(target, column_1, column_2)

        @test result.Cref ≈ expected_cref rtol=T("1e-25")
        @test result.Cinc ≈ expected_cinc rtol=T("1e-25")
        @test result.reconstruction_residual <= T("1e-50")
        @test result.scaled_basis_determinant_abs > zero(T)
    end
end

@testset "horizon endpoint selection is fail closed" begin
    candidates = [
        (
            rho=BigFloat(-10),
            horizon_distance=BigFloat("0.52"),
            ingoing_adequate=true,
            outgoing_adequate=true,
        ),
        (
            rho=BigFloat(-25),
            horizon_distance=BigFloat("0.012"),
            ingoing_adequate=true,
            outgoing_adequate=true,
        ),
        (
            rho=BigFloat(-50),
            horizon_distance=BigFloat("3e-5"),
            ingoing_adequate=true,
            outgoing_adequate=true,
        ),
    ]

    selected = select_nearest_adequate_horizon_endpoint(
        candidates; maximum_horizon_distance=BigFloat("0.1")
    )
    @test selected.rho == BigFloat(-25)
    @test_throws ErrorException select_nearest_adequate_horizon_endpoint(
        candidates[1:1]; maximum_horizon_distance=BigFloat("0.1")
    )
end
