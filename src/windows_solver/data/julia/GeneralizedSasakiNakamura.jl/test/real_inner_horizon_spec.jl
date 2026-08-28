# Specification for the real-inner horizon contour, its geometry gate, and the
# horizon solution basis built at the matching point.
#
# These are the behaviours that block recurrence of the Leaf 13 failure modes.
# The fixture is a small synthetic mode, not Leaf 13: what is asserted here is
# structural (which contour is used, what is checked before an ODE is allowed to
# start, what the basis solve is invariant under), and structure is what went
# wrong. The physical Leaf 13 evidence gates are a separate, non-CI exercise.

using Test
using DifferentialEquations

# The worker main is guarded, so including it exposes the coordinate-identity
# contract without starting a request or a solver campaign.
include(joinpath(@__DIR__, "..", "..", "m02_worker.jl"))

const CF_HORIZON = GeneralizedSasakiNakamura.ComplexFrequencies
const FS_HORIZON = GeneralizedSasakiNakamura.FactoredSolutions
const SOL_HORIZON = GeneralizedSasakiNakamura.Solutions
const COORD_HORIZON = GeneralizedSasakiNakamura.Coordinates
const KERR_HORIZON = GeneralizedSasakiNakamura.Kerr

function horizon_spec_context(::Type{T}) where {T<:AbstractFloat}
    s, m = -2, 2
    a = T(1) / T(5)
    omega = complex(T(2) / T(5), T(1) / T(20))
    lambda = complex(T(4), T(1) / T(10))
    geometry = KERR_HORIZON.stable_horizon_geometry(a)
    p_horizon = omega - T(m) * geometry.omega_horizon
    frozen = COORD_HORIZON.gsn_branch_convention(omega, p_horizon)
    spectral = CF_HORIZON.build_homogeneous_spectral_context(
        s, m, a, omega, lambda,
        T === Float64 ? 15 : 40,
        precision(T),
        2,
        frozen,
    )
    match_radius = T(12)
    rstar_match = T(COORD_HORIZON.rstar_from_r(a, match_radius))
    return (
        spectral=spectral,
        match_radius=match_radius,
        rstar_match=rstar_match,
        geometry=geometry,
    )
end

"""
    real_inner_map(context, T)

Solve the coordinate map on the real-inner convention: beta = 0, sign = +1, so
r_*(rho) = rstar_match + rho and r approaches r_plus as rho decreases.
"""
function real_inner_map(context, ::Type{T}; rho_min::T=-T(100)) where {T}
    return CF_HORIZON.solve_r_from_rho(
        context.spectral.a,
        zero(T),
        context.rstar_match,
        rho_min;
        sign=Int8(1),
        dtype=Complex{T},
        reltol=T === Float64 ? 1e-12 : T(1) / T(10)^20,
        abstol=T === Float64 ? 1e-14 : T(1) / T(10)^22,
        verbose=false,
        r_at_rho_zero=Complex{T}(context.match_radius),
    )
end

function horizon_geometry_candidates(context, contour; maximum_distance)
    return CF_HORIZON.horizon_endpoint_geometry_candidates(
        context.spectral,
        contour;
        maximum_horizon_distance=maximum_distance,
    )
end

function horizon_series_candidates(
    context,
    contour,
    geometry_candidates;
    required_digits,
    maximum_distance,
)
    return CF_HORIZON.horizon_endpoint_candidates(
        context.spectral,
        contour,
        geometry_candidates,
        required_digits;
        maximum_horizon_distance=maximum_distance,
    )
end

function coordinate_identity_spec_request()
    digest = repeat("0", 64)
    return Dict{String,Any}(
        "precision_digits" => 80,
        "request_sha256" => digest,
        "job_id" => "coordinate-identity-spec",
        "leaf_id" => "coordinate-identity-spec-leaf",
        "role" => "specification",
        "job_policy_sha256" => digest,
        "backend_identity_sha256" => digest,
        "refinement_level" => 0,
        "resource_policy_schema" =>
            "windows-solver.execution-resource-policy/1",
        "resource_policy_version" => 1,
        "resource_policy_sha256" => digest,
        "coordinate_ode_relative_tolerance" => "1e-12",
        "coordinate_ode_absolute_tolerance" => "1e-14",
        "execution_identity" => Dict{String,Any}(
            "schema" => OPERATION_EXECUTION_IDENTITY_SCHEMA,
            "scope" => "REQUEST",
            "operation" => "root-readout",
            "request_schema" => "windows-solver.root-readout/1",
            "request_sha256" => digest,
            "leaf_id" => "coordinate-identity-spec-leaf",
            "job_id" => "coordinate-identity-spec",
            "backend_identity_sha256" => digest,
            "precision_digits" => 80,
            "working_precision_bits" => 298,
            "semantic_precision_tier" => "BF80",
            "effective_policy_identity" => digest,
            "execution_resource_policy_identity" => Dict{String,Any}(
                "schema" => "windows-solver.execution-resource-policy/1",
                "version" => 1,
                "sha256" => digest,
            ),
            "role" => "specification",
            "job_policy_sha256" => digest,
            "refinement_level" => 0,
        ),
    )
end

@testset "coordinate map starts exactly at the matching radius" begin
    for T in (Float64, BigFloat)
        context = horizon_spec_context(T)
        radial = real_inner_map(context, T)
        # r(0) must be the supplied matching radius, not a numerical inverse of
        # its tortoise coordinate.
        @test abs(
            Complex{T}(radial(zero(T))) -
            complex(context.match_radius, zero(T))
        ) <= T(256) * eps(T) * max(one(T), context.match_radius)
        # The identity rstar_from_r(a, match_radius) == rstar_match is what
        # licenses seeding r(0) directly.
        @test T(COORD_HORIZON.rstar_from_r(
            context.spectral.a, context.match_radius
        )) == context.rstar_match
    end
end

@testset "real-inner contour approaches the horizon monotonically" begin
    T = BigFloat
    context = horizon_spec_context(T)
    radial = real_inner_map(context, T)
    rplus = complex(T(context.geometry.rplus), zero(T))
    previous = T(Inf)
    for rho in (-T(10), -T(25), -T(50), -T(75), -T(100))
        radius = Complex{T}(radial(rho))
        distance = abs(radius - rplus)
        # Strictly decreasing distance to r_plus is the property the
        # frequency-aligned negative contour lacks: for Leaf 13 that contour
        # reached |r - r_plus| ~ 96.8 at rho = -100, moving away.
        @test distance < previous
        @test real(radius) > T(context.geometry.rplus)
        previous = distance
    end
    @test previous < T(1) / T(10)
end

@testset "contour construction rejects a non-real-inner tangent" begin
    T = BigFloat
    context = horizon_spec_context(T)
    radial = real_inner_map(context, T)
    contour = CF_HORIZON.build_real_inner_horizon_contour(
        context.spectral,
        context.match_radius,
        context.rstar_match,
        -T(100),
        radial,
    )
    @test contour.contour_id == CF_HORIZON.REAL_INNER_HORIZON_CONTOUR_ID
    @test contour.tangent == complex(one(T), zero(T))
    # A positive rho_min is not an inner contour at all.
    @test_throws Exception CF_HORIZON.build_real_inner_horizon_contour(
        context.spectral,
        context.match_radius,
        context.rstar_match,
        T(100),
        radial,
    )
end

@testset "geometry gate precedes and outranks the series assessment" begin
    T = BigFloat
    context = horizon_spec_context(T)
    radial = real_inner_map(context, T)
    contour = CF_HORIZON.build_real_inner_horizon_contour(
        context.spectral, context.match_radius, context.rstar_match,
        -T(100), radial,
    )
    required = T(12)
    maximum_distance = T(1) / T(10)
    geometry_candidates = horizon_geometry_candidates(
        context, contour; maximum_distance=maximum_distance
    )
    candidates = horizon_series_candidates(
        context,
        contour,
        geometry_candidates;
        required_digits=required,
        maximum_distance=maximum_distance,
    )
    @test length(candidates) == 5
    @test all(candidate -> candidate.geometry.rho < zero(T), candidates)
    @test all(candidate -> candidate.geometry.exterior, candidates)
    # Radial-approach conditions are recorded independently of the series
    # verdicts, so no truncation order can substitute for correct geometry.
    for candidate in candidates
        @test candidate.geometry.approaches_horizon isa Bool
        @test candidate.geometry.within_maximum_distance isa Bool
    end

    # An unreachable distance bound leaves nothing adequate, and the failure is
    # raised before any homogeneous ODE has been started.
    starved_maximum = T(1) / T(10)^40
    starved_geometry = horizon_geometry_candidates(
        context, contour; maximum_distance=starved_maximum
    )
    starved = horizon_series_candidates(
        context,
        contour,
        starved_geometry;
        required_digits=required,
        maximum_distance=starved_maximum,
    )
    @test all(
        candidate -> !candidate.geometry.within_maximum_distance,
        starved,
    )
    failure = try
        CF_HORIZON.select_verified_horizon_endpoints(
            context.spectral, starved;
            maximum_horizon_distance=T(1) / T(10)^40,
        )
        nothing
    catch error
        error
    end
    @test failure isa CF_HORIZON.FactoredPropagationError
    @test failure.reason == CF_HORIZON.NO_VERIFIED_HORIZON_ENDPOINT
    @test failure.factored_homogeneous_rhs_evaluations == 0
end

@testset "invalid geometry does not evaluate either horizon series" begin
    T = BigFloat
    context = horizon_spec_context(T)
    radial = real_inner_map(context, T)
    contour = CF_HORIZON.build_real_inner_horizon_contour(
        context.spectral, context.match_radius, context.rstar_match,
        -T(100), radial,
    )
    invalid = CF_HORIZON.HorizonEndpointGeometryCandidate{T}(
        -T(10),
        complex(T(NaN), zero(T)),
        T(Inf),
        zero(T),
        false,
        false,
        false,
        false,
        contour.contour_id,
        contour.precision_bits,
        contour.frozen_branch_cell,
    )
    candidates = horizon_series_candidates(
        context,
        contour,
        [invalid];
        required_digits=T(12),
        maximum_distance=T(1) / T(10),
    )
    @test length(candidates) == 1
    @test candidates[1].ingoing_evaluation === nothing
    @test candidates[1].outgoing_evaluation === nothing
    @test !candidates[1].ingoing_adequate
    @test !candidates[1].outgoing_adequate
end

@testset "verification requires a second adequate endpoint" begin
    T = BigFloat
    context = horizon_spec_context(T)
    radial = real_inner_map(context, T)
    contour = CF_HORIZON.build_real_inner_horizon_contour(
        context.spectral, context.match_radius, context.rstar_match,
        -T(100), radial,
    )
    maximum_distance = T(1) / T(10)
    geometry_candidates = horizon_geometry_candidates(
        context, contour; maximum_distance=maximum_distance
    )
    candidates = horizon_series_candidates(
        context,
        contour,
        geometry_candidates;
        required_digits=T(12),
        maximum_distance=maximum_distance,
    )
    adequate = filter(
        candidate -> candidate.geometry.rho < zero(T) &&
            candidate.geometry.exterior &&
            candidate.geometry.on_real_axis &&
            candidate.geometry.approaches_horizon &&
            candidate.geometry.within_maximum_distance &&
            candidate.ingoing_adequate && candidate.outgoing_adequate,
        candidates,
    )
    if length(adequate) >= 2
        endpoints = CF_HORIZON.select_verified_horizon_endpoints(
            context.spectral, candidates
        )
        # Reference is the nearest adequate endpoint (shortest leg);
        # verification is the next one deeper.
        @test endpoints.reference.geometry.rho >
            endpoints.verification.geometry.rho
        @test endpoints.contour_id ==
            CF_HORIZON.REAL_INNER_HORIZON_CONTOUR_ID
    end
    # One adequate candidate can never satisfy the gate: a single endpoint
    # supplies no disagreement term for the determinant error.
    single = length(adequate) >= 1 ? [first(adequate)] :
        CF_HORIZON.HorizonEndpointCandidate{T}[]
    failure = try
        CF_HORIZON.select_verified_horizon_endpoints(
            context.spectral, single
        )
        nothing
    catch error
        error
    end
    @test failure isa CF_HORIZON.FactoredPropagationError
    @test failure.reason == CF_HORIZON.NO_VERIFIED_HORIZON_ENDPOINT
end

@testset "selector revalidates the configured maximum horizon distance" begin
    T = BigFloat
    context = horizon_spec_context(T)
    radial = real_inner_map(context, T)
    contour = CF_HORIZON.build_real_inner_horizon_contour(
        context.spectral, context.match_radius, context.rstar_match,
        -T(100), radial,
    )
    original_maximum = T(1) / T(10)
    geometry_candidates = horizon_geometry_candidates(
        context, contour; maximum_distance=original_maximum
    )
    candidates = horizon_series_candidates(
        context,
        contour,
        geometry_candidates;
        required_digits=T(12),
        maximum_distance=original_maximum,
    )
    positive_distances = [
        candidate.geometry.horizon_distance for candidate in candidates
        if candidate.geometry.horizon_distance > zero(T)
    ]
    tighter_maximum = minimum(positive_distances) / T(2)
    failure = try
        CF_HORIZON.select_verified_horizon_endpoints(
            context.spectral,
            candidates;
            maximum_horizon_distance=tighter_maximum,
        )
        nothing
    catch error
        error
    end
    @test failure isa CF_HORIZON.FactoredPropagationError
    @test failure.reason == CF_HORIZON.NO_VERIFIED_HORIZON_ENDPOINT
end

@testset "coordinate identity rejects nonfinite and excessive residuals" begin
    T = Float64
    context = horizon_spec_context(T)
    request = coordinate_identity_spec_request()
    tangent = complex(one(T), zero(T))
    at_match(_rho) = complex(context.match_radius, zero(T))

    evidence = assert_coordinate_identity(
        T,
        request,
        context.spectral,
        at_match,
        context.rstar_match,
        tangent,
        (zero(T),),
        "coordinate-identity-valid",
    )
    @test evidence isa CoordinateIdentityEvidence{T}
    @test isfinite(evidence.maximum_absolute_residual)
    @test isfinite(evidence.maximum_relative_residual)
    @test isfinite(evidence.absolute_tolerance)
    @test isfinite(evidence.relative_tolerance)

    excessive = try
        assert_coordinate_identity(
            T,
            request,
            context.spectral,
            at_match,
            context.rstar_match,
            tangent,
            (zero(T), -one(T)),
            "coordinate-identity-excessive",
        )
        nothing
    catch error
        error
    end
    @test excessive isa NumericalControlFailure
    @test failure_details(excessive)["failure_code"] ==
        "COORDINATE_IDENTITY_MISMATCH"
    excessive_diagnostics = failure_details(excessive)["diagnostics"]
    for field in (
        "maximum_absolute_residual",
        "maximum_relative_residual",
        "absolute_tolerance",
        "relative_tolerance",
        "coordinate_ode_relative_tolerance",
        "coordinate_ode_absolute_tolerance",
    )
        @test haskey(excessive_diagnostics, field)
    end

    nonfinite_map(_rho) = complex(T(NaN), zero(T))
    nonfinite = try
        assert_coordinate_identity(
            T,
            request,
            context.spectral,
            nonfinite_map,
            context.rstar_match,
            tangent,
            (zero(T),),
            "coordinate-identity-nonfinite",
        )
        nothing
    catch error
        error
    end
    @test nonfinite isa NumericalControlFailure
    @test failure_details(nonfinite)["failure_code"] ==
        "COORDINATE_IDENTITY_MISMATCH"
end

@testset "explicit-tangent horizon carriers keep the canonical match point" begin
    T = BigFloat
    context = horizon_spec_context(T)
    tangent = complex(one(T), zero(T))
    for kind in (FS_HORIZON.HORIZON_INGOING, FS_HORIZON.HORIZON_OUTGOING)
        canonical = FS_HORIZON.PlaneWaveCarrier(
            kind,
            context.spectral.p_horizon,
            context.rstar_match,
            context.spectral.convention,
        )
        explicit = FS_HORIZON.horizon_carrier_with_explicit_tangent(
            kind,
            context.spectral.p_horizon,
            context.rstar_match,
            context.spectral.convention,
            tangent,
        )
        # Only the exponent derivative is rebound; the logarithm at the
        # matching point is unchanged, so states factored against either
        # carrier remain comparable at rho = 0.
        @test explicit.log_at_match == canonical.log_at_match
        @test explicit.wave_number == canonical.wave_number
        @test explicit.rstar_match == canonical.rstar_match
        sign = kind === FS_HORIZON.HORIZON_INGOING ? -one(T) : one(T)
        @test explicit.q ≈ sign * complex(zero(T), one(T)) *
            context.spectral.p_horizon * tangent
    end
    # The infinity branch has no real-inner tangent to rebind.
    @test_throws Exception FS_HORIZON.horizon_carrier_with_explicit_tangent(
        FS_HORIZON.INFINITY_OUTGOING,
        context.spectral.p_horizon,
        context.rstar_match,
        context.spectral.convention,
        tangent,
    )
end

@testset "match-basis column scaling does not move the coefficients" begin
    T = BigFloat
    context = horizon_spec_context(T)
    tangent = complex(one(T), zero(T))
    ingoing_carrier = FS_HORIZON.horizon_carrier_with_explicit_tangent(
        FS_HORIZON.HORIZON_INGOING,
        context.spectral.p_horizon,
        context.rstar_match,
        context.spectral.convention,
        tangent,
    )
    outgoing_carrier = FS_HORIZON.horizon_carrier_with_explicit_tangent(
        FS_HORIZON.HORIZON_OUTGOING,
        context.spectral.p_horizon,
        context.rstar_match,
        context.spectral.convention,
        tangent,
    )
    bits = precision(T)
    ingoing_state = FS_HORIZON.FactoredEndpointState{T}(
        complex(T(3) / T(2), T(1) / T(4)),
        complex(-T(1) / T(3), T(2) / T(5)),
    )
    outgoing_state = FS_HORIZON.FactoredEndpointState{T}(
        complex(T(1) / T(7), -T(5) / T(6)),
        complex(T(4) / T(9), T(1) / T(8)),
    )
    target = FS_HORIZON.FactoredEndpointState{T}(
        complex(T(2) / T(5), T(3) / T(7)),
        complex(T(1) / T(6), -T(2) / T(9)),
    )
    basis = SOL_HORIZON.build_match_horizon_basis(
        ingoing_state,
        ingoing_carrier,
        outgoing_state,
        outgoing_carrier,
        tangent,
        complex(context.match_radius, zero(T)),
        bits,
    )
    solved = SOL_HORIZON.solve_scaled_horizon_basis_at_match(
        target, ingoing_carrier, basis
    )
    @test solved.diagnostics.extraction_id ==
        SOL_HORIZON.HORIZON_BASIS_AT_MATCH_EXTRACTION_ID

    # Rescaling a physical column rescales only its own coefficient. This is
    # the property that lets a near-extremal magnitude disparity between the
    # ingoing and outgoing columns be handled without the system looking
    # singular.
    factor = T(10)^6
    scaled_basis = SOL_HORIZON.build_match_horizon_basis(
        FS_HORIZON.FactoredEndpointState{T}(
            factor * ingoing_state.Y, factor * ingoing_state.Yrho
        ),
        ingoing_carrier,
        outgoing_state,
        outgoing_carrier,
        tangent,
        complex(context.match_radius, zero(T)),
        bits,
    )
    scaled = SOL_HORIZON.solve_scaled_horizon_basis_at_match(
        target, ingoing_carrier, scaled_basis
    )
    @test abs(scaled.Cref * factor - solved.Cref) <=
        T(10)^(-25) * max(abs(solved.Cref), one(T))
    @test abs(scaled.Cinc - solved.Cinc) <=
        T(10)^(-25) * max(abs(solved.Cinc), one(T))
    @test solved.diagnostics.matching_reconstruction_residual <= T(10)^(-25)
end

@testset "match basis enforces the Cref/Cinc column order" begin
    T = BigFloat
    context = horizon_spec_context(T)
    tangent = complex(one(T), zero(T))
    ingoing_carrier = FS_HORIZON.horizon_carrier_with_explicit_tangent(
        FS_HORIZON.HORIZON_INGOING,
        context.spectral.p_horizon,
        context.rstar_match,
        context.spectral.convention,
        tangent,
    )
    outgoing_carrier = FS_HORIZON.horizon_carrier_with_explicit_tangent(
        FS_HORIZON.HORIZON_OUTGOING,
        context.spectral.p_horizon,
        context.rstar_match,
        context.spectral.convention,
        tangent,
    )
    state = FS_HORIZON.FactoredEndpointState{T}(
        complex(one(T), zero(T)), complex(zero(T), one(T))
    )
    other = FS_HORIZON.FactoredEndpointState{T}(
        complex(zero(T), one(T)), complex(one(T), zero(T))
    )
    # Swapping the columns swaps the physical meaning of the recovered
    # coefficients, so it must be rejected rather than silently solved.
    @test_throws Exception SOL_HORIZON.build_match_horizon_basis(
        state,
        outgoing_carrier,
        other,
        ingoing_carrier,
        tangent,
        complex(context.match_radius, zero(T)),
        precision(T),
    )
end
