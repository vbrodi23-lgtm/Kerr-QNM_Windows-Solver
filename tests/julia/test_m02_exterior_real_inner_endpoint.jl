#!/usr/bin/env julia

using Test

const REPOSITORY_ROOT = normpath(joinpath(@__DIR__, "..", ".."))
include(joinpath(
    REPOSITORY_ROOT,
    "src",
    "windows_solver",
    "data",
    "julia",
    "m02_worker.jl",
))

const TEST_RHO_SCHEDULE = [
    "-10", "-25", "-50", "-75", "-100", "-150", "-225", "-337.5",
    "-400",
]

struct EndpointFailureFixtureRequest
    recovery_policy::Dict{String,Any}
end

function required(request::EndpointFailureFixtureRequest, key::String)
    key == "fixed_root_endpoint_recovery_policy" || error(
        "unexpected endpoint failure fixture key"
    )
    return request.recovery_policy
end

control_failure_context(::EndpointFailureFixtureRequest) = Dict{String,Any}()

function fixture_request()
    return Dict{String,Any}(
        "horizon_rho_inner_min" => "-400",
        "horizon_maximum_endpoint_distance" => "0.1",
        "fixed_root_endpoint_recovery_policy" => Dict{String,Any}(
            "identity" =>
                "cause-aware-real-inner-fixed-root-exterior-endpoint-recovery/v2",
            "policy_sha256" => repeat("a", 64),
            "endpoint_order_schedule" => [28, 56, 112],
            "horizon_geometry_schedule" => copy(TEST_RHO_SCHEDULE),
            "infinity_geometry_schedule" => [
                "100", "250", "500", "1000", "2000", "5000", "10000",
                "20000",
            ],
            "horizon_rho_inner_min" => "-400",
            "horizon_endpoint_rho_floor" => "-400",
            "horizon_maximum_endpoint_distance" => "0.1",
        ),
    )
end

function deterministic_recovery(
    verdict;
    coordinate_failure::Bool=false,
)
    request = fixture_request()
    required_digits = 17.0
    prepared = Ref(0)
    inspected = Ref(0)
    homogeneous_rhs = Ref(0)
    coordinate = CoordinateIdentityEvidence{Float64}(
        0.0, 0.0, 1.0e-20, 1.0e-20, 0.0, 0.0, 9
    )
    contour = (
        contour_id=CF.REAL_INNER_HORIZON_CONTOUR_ID,
        match_radius=2.5,
        rstar_match=0.75,
        rho_min=-400.0,
        tangent=1.0 + 0.0im,
    )
    contour_builder = function (
        ::Type{T}, request, spectral, match_radius, label;
        retain_coordinate_identity=false,
    ) where {T<:AbstractFloat}
        coordinate_failure && throw(NumericalControlFailure(
            "coordinate identity mismatch",
            Dict{String,Any}(
                "failure_code" => "COORDINATE_IDENTITY_MISMATCH",
                "failure_class" => "CONTROL",
                "stage" => "coordinate-inversion",
                "factored_homogeneous_rhs_evaluations" => homogeneous_rhs[],
            ),
        ))
        @test retain_coordinate_identity
        @test match_radius == T(2.5)
        return (contour=contour, coordinate_identity=coordinate)
    end
    geometry_builder = function (
        spectral,
        contour;
        rho_candidates,
        maximum_horizon_distance,
    )
        return [begin
            depth = abs(rho)
            distance = 0.04 * exp(-(depth - 10) / 20)
            (
                rho=rho,
                radius=1.5 + distance + 0.0im,
                horizon_distance=distance,
                imaginary_radius_abs=0.0,
                exterior=true,
                on_real_axis=true,
                approaches_horizon=true,
                within_maximum_distance=distance <= maximum_horizon_distance,
                contour_id=contour.contour_id,
            )
        end for rho in rho_candidates]
    end
    candidate_builder = function (
        spectral,
        contour,
        geometry_candidates,
        required_digits;
        maximum_horizon_distance,
        endpoint_orders,
        attempted_endpoint_order,
    )
        inspected[] += 1
        geometry = only(geometry_candidates)
        limitation = verdict(geometry.rho, attempted_endpoint_order)
        adequate = limitation == CF.ENDPOINT_ADEQUATE
        predicted = adequate ? required_digits + 5 : required_digits - 2
        assessment = (
            adequate=adequate,
            maximum_last_term_ratio=0.1,
            maximum_truncation_digits_lost=5.0,
            maximum_recurrence_digits_lost=1.0,
            maximum_series_evaluation_digits_lost=1.0,
            predicted_reliable_digits=predicted,
            required_digits=required_digits,
        )
        evaluation = (order=last(endpoint_orders),)
        return [(
            geometry=geometry,
            ingoing_adequate=adequate,
            outgoing_adequate=false,
            ingoing_evaluation=evaluation,
            outgoing_evaluation=nothing,
            ingoing_assessment=assessment,
            outgoing_assessment=nothing,
            endpoint_order=evaluation.order,
            attempted_endpoint_order=attempted_endpoint_order,
            fixture_limitation=limitation,
        )]
    end
    endpoint_preparer = function (
        spectral, contour, candidate, branch, required_digits
    )
        prepared[] += 1
        @test branch === CF.HORIZON_INGOING
        return (candidate=candidate, branch=branch)
    end
    limitation_classifier = (candidate, maximum_distance) ->
        candidate.fixture_limitation
    result = recover_fixed_root_real_inner_horizon_endpoint(
        Float64,
        request,
        nothing,
        2.5,
        required_digits;
        factored_homogeneous_rhs_counter=homogeneous_rhs,
        contour_builder=contour_builder,
        geometry_builder=geometry_builder,
        candidate_builder=candidate_builder,
        endpoint_preparer=endpoint_preparer,
        candidate_emitter=candidate -> nothing,
        limitation_classifier=limitation_classifier,
    )
    return result, prepared[], inspected[]
end

@testset "M02 fixed-root real-inner exterior endpoint" begin
    @testset "a=0.95 representative selects rho=-10" begin
        result, prepared, inspected = deterministic_recovery(
            (rho, order) -> CF.ENDPOINT_ADEQUATE
        )
        @test result.receipt["selected_rho"] == "-10"
        @test parse(Float64, result.receipt["attempts"][1][
            "predicted_reliable_digits"
        ]) > parse(Float64, result.receipt["attempts"][1][
            "required_reliable_digits"
        ])
        @test prepared == 1
        @test inspected == 1
        @test result.receipt[
            "factored_homogeneous_rhs_evaluations_before_decision"
        ] == 0
    end

    @testset "a=0.99 alpha representative selects rho=-25" begin
        result, prepared, inspected = deterministic_recovery(
            (rho, order) -> rho == -10.0 ?
                CF.ENDPOINT_SERIES_ORDER_LIMITED : CF.ENDPOINT_ADEQUATE
        )
        @test result.receipt["selected_rho"] == "-25"
        @test result.receipt["attempts"][1]["adequate"] == false
        @test result.receipt["attempts"][2]["adequate"] == true
        @test prepared == 1
        @test inspected == 2
    end

    @testset "no adequate candidate is causal and pre-ODE" begin
        result, prepared, inspected = deterministic_recovery(
            (rho, order) -> CF.ENDPOINT_SERIES_ORDER_LIMITED
        )
        @test result.outcome == CF.ENDPOINT_SERIES_ORDER_LIMITED
        @test result.preparation === nothing
        @test result.receipt["selected_rho"] === nothing
        @test prepared == 0
        @test inspected == 27
        @test result.receipt[
            "factored_homogeneous_rhs_evaluations_before_decision"
        ] == 0
        failure = exterior_endpoint_recovery_failure(
            EndpointFailureFixtureRequest(
                fixture_request()["fixed_root_endpoint_recovery_policy"]
            ),
            Any[result.receipt],
            result.outcome,
        )
        @test failure isa NumericalControlFailure
        @test failure.details["failure_code"] ==
            "EXTERIOR_ENDPOINT_MAXIMUM_ORDER_INADEQUATE"
        @test failure.details["stage"] == "asymptotic-preflight"
        @test failure.details["retryable"] == false
        @test failure.details["diagnostics"][
            "factored_homogeneous_rhs_evaluations"
        ] == 0
    end

    @testset "coordinate identity failure is coordinate-specific and pre-ODE" begin
        failure = try
            deterministic_recovery(
                (rho, order) -> CF.ENDPOINT_ADEQUATE;
                coordinate_failure=true,
            )
            nothing
        catch error
            error
        end
        @test failure isa NumericalControlFailure
        @test failure.details["failure_code"] == "COORDINATE_IDENTITY_MISMATCH"
        @test failure.details["stage"] == "coordinate-inversion"
        @test failure.details["factored_homogeneous_rhs_evaluations"] == 0
    end

    @testset "earlier adequate candidate prevents deeper inspection" begin
        result, prepared, inspected = deterministic_recovery(
            (rho, order) -> CF.ENDPOINT_ADEQUATE
        )
        @test result.receipt["selected_rho"] == "-10"
        @test length(result.receipt["attempts"]) == 1
        @test prepared == 1
        @test inspected == 1
    end
end
