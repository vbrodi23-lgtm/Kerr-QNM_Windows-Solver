using Test

include(joinpath(@__DIR__, "leaf13_horizon_harness_common.jl"))
using .Leaf13HorizonHarnessCommon

@testset "calibration payload preserves determinant-error certificate" begin
    diagnostics = DeterminantDiagnostics{Float64}(
        "synthetic-representation/v1",
        "horizon-scattering/v1",
        true,
        0.0,
        0.0,
        0.0,
        0.0,
        80.0,
        2.0,
        0.0,
        0.0,
        true,
        0.0,
        13.0,
        "available/v1",
        13.0,
        1.0,
        0.0,
        0.0,
    )
    breakdown = DeterminantErrorBreakdown{Float64}(
        2.0,
        3.0,
        5.0,
        7.0,
        8.0,
        56.0,
    )
    model_id = leaf13_request()["determinant_error_model"]
    evaluation = DeterminantEvaluation{Float64}(
        complex(11.0, -13.0),
        breakdown,
        model_id,
        diagnostics,
    )

    payload = calibration_payload(Float64, evaluation)
    @test payload["central_determinant_re"] == "11.0"
    @test payload["central_determinant_im"] == "-13.0"
    @test payload["endpoint_disagreement_abs"] == "2.0"
    @test payload["control_disagreement_abs"] == "3.0"
    @test payload["equivalence_disagreement_abs"] == "5.0"
    @test payload["precision_disagreement_abs"] == "7.0"
    @test payload["safety_factor"] == "8.0"
    @test payload["numerical_error_abs"] == "56.0"
    @test payload["error_model_id"] == model_id
end
