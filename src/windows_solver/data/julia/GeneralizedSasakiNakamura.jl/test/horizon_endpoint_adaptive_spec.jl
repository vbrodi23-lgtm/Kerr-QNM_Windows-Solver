using Test

using GeneralizedSasakiNakamura
const CF_ADAPTIVE = GeneralizedSasakiNakamura.ComplexFrequencies

# The 222 row at a/M = 0.9999 failed with every declared depth exhausted:
# rho = -10 and -25 never came within the maximum horizon distance, while
# rho = -50, -75 and -100 were close enough but had both series rejected at the
# single fixed endpoint order. Nothing in the old policy could try a deeper
# radius or a longer series, so the leaf failed before any homogeneous ODE ran.
const DECLARED_222_RHO_CANDIDATES = Float64[-10, -25, -50, -75, -100]
const CAPTURED_222_ORDER_28_FAILURE = [
    (rho=-10, horizon_distance=0.780708315432074, geometry_ok=false,
     ingoing_ok=false, outgoing_ok=false, endpoint_order=28),
    (rho=-25, horizon_distance=0.1343843030342528, geometry_ok=false,
     ingoing_ok=false, outgoing_ok=false, endpoint_order=28),
    (rho=-50, horizon_distance=0.04199390049280419, geometry_ok=true,
     ingoing_ok=false, outgoing_ok=false, endpoint_order=28),
    (rho=-75, horizon_distance=0.020989841197182793, geometry_ok=true,
     ingoing_ok=false, outgoing_ok=false, endpoint_order=28),
    (rho=-100, horizon_distance=0.01225366578659957, geometry_ok=true,
     ingoing_ok=false, outgoing_ok=false, endpoint_order=28),
]
const CAPTURED_222_FAILURE_OUTCOME = "NO_VERIFIED_HORIZON_ENDPOINT"
const CAPTURED_PREFIX_RELIABLE_DIGITS = [
    (order=4, reliable_digits=18.0),
    (order=8, reliable_digits=26.0),
    (order=12, reliable_digits=31.5),
    (order=16, reliable_digits=29.0),
    (order=20, reliable_digits=21.0),
]

@testset "intermediate least-term prefix survives later asymptotic growth" begin
    schedule = CF_ADAPTIVE.horizon_endpoint_prefix_orders(20)
    @test schedule == [4, 8, 12, 16, 20]
    selected = argmax(
        row.reliable_digits for row in CAPTURED_PREFIX_RELIABLE_DIGITS
    )
    @test CAPTURED_PREFIX_RELIABLE_DIGITS[selected].order == 12
    @test CAPTURED_PREFIX_RELIABLE_DIGITS[end].reliable_digits <
        CAPTURED_PREFIX_RELIABLE_DIGITS[selected].reliable_digits
end

@testset "captured 222 order-28 failure remains a five-row fixture" begin
    @test length(CAPTURED_222_ORDER_28_FAILURE) == 5
    @test all(row.endpoint_order == 28 for row in CAPTURED_222_ORDER_28_FAILURE)
    @test count(row.geometry_ok for row in CAPTURED_222_ORDER_28_FAILURE) == 3
    @test all(!row.ingoing_ok && !row.outgoing_ok for row in CAPTURED_222_ORDER_28_FAILURE)
    @test CAPTURED_222_FAILURE_OUTCOME == "NO_VERIFIED_HORIZON_ENDPOINT"
end

@testset "endpoint order ladder spans the declared order upward" begin
    ladder = CF_ADAPTIVE.horizon_endpoint_order_ladder(28)

    @test first(ladder) == 28
    @test last(ladder) == 112
    @test issorted(ladder)
    @test allunique(ladder)
    # Doubling keeps the ladder short: each entry costs a full series
    # evaluation at every candidate radius.
    @test length(ladder) <= 4

    @test CF_ADAPTIVE.horizon_endpoint_order_ladder(
        28; maximum_order=28
    ) == [28]
    @test_throws ArgumentError CF_ADAPTIVE.horizon_endpoint_order_ladder(0)
    @test_throws ArgumentError CF_ADAPTIVE.horizon_endpoint_order_ladder(
        28; maximum_order=16
    )
end

@testset "endpoint depth extends past the declared candidates" begin
    deeper = CF_ADAPTIVE.deepen_horizon_endpoint_rho_candidates(
        DECLARED_222_RHO_CANDIDATES, -400.0
    )

    @test deeper !== nothing
    # Every declared depth is kept; the search only ever adds.
    @test issubset(DECLARED_222_RHO_CANDIDATES, deeper)
    @test minimum(deeper) < minimum(DECLARED_222_RHO_CANDIDATES)
    @test issorted(deeper; rev=true)
    @test allunique(deeper)
    @test minimum(deeper) >= -400.0
end

@testset "endpoint depth stops at the declared coordinate floor" begin
    # Already at the floor: there is no further depth to offer, and the caller
    # must be told so rather than looping.
    @test CF_ADAPTIVE.deepen_horizon_endpoint_rho_candidates(
        Float64[-10, -400], -400.0
    ) === nothing

    # Past the floor is also exhausted.
    @test CF_ADAPTIVE.deepen_horizon_endpoint_rho_candidates(
        Float64[-10, -500], -400.0
    ) === nothing

    @test CF_ADAPTIVE.deepen_horizon_endpoint_rho_candidates(
        Float64[], -400.0
    ) === nothing

    # Repeated deepening converges onto the floor instead of overshooting it.
    candidates = copy(DECLARED_222_RHO_CANDIDATES)
    for _ in 1:64
        extended = CF_ADAPTIVE.deepen_horizon_endpoint_rho_candidates(
            candidates, -400.0
        )
        extended === nothing && break
        candidates = extended
    end
    @test minimum(candidates) == -400.0
    @test CF_ADAPTIVE.deepen_horizon_endpoint_rho_candidates(
        candidates, -400.0
    ) === nothing
end

@testset "endpoint depth rejects an unusable search policy" begin
    @test_throws ArgumentError CF_ADAPTIVE.deepen_horizon_endpoint_rho_candidates(
        DECLARED_222_RHO_CANDIDATES, -400.0; growth=1.0
    )
    @test_throws ArgumentError CF_ADAPTIVE.deepen_horizon_endpoint_rho_candidates(
        DECLARED_222_RHO_CANDIDATES, 400.0
    )
end

@testset "endpoint limitations are distinct named remedies" begin
    limitations = (
        CF_ADAPTIVE.HORIZON_ENDPOINT_ADEQUATE,
        CF_ADAPTIVE.HORIZON_ENDPOINT_ORDER_LIMITED,
        CF_ADAPTIVE.HORIZON_ENDPOINT_PRECISION_LIMITED,
        CF_ADAPTIVE.HORIZON_ENDPOINT_GEOMETRY_LIMITED,
    )

    # The worker routes on these values: depth is retried, precision escalates
    # the digit tier, and adequacy proceeds. Collapsing any two would silently
    # send one remedy down the other's path.
    @test allunique(limitations)
    @test all(!isempty, limitations)
    @test all(endswith(value, "/v1") for value in limitations)
end
