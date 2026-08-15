#!/usr/bin/env julia

# Performance receipt for the production three-leg Leaf 13 horizon graph.
# This harness measures implementation cost and determinant evidence only; it
# does not open either mathematical-review or release-admission gates.

include(joinpath(@__DIR__, "leaf13_horizon_harness_common.jl"))
using .Leaf13HorizonHarnessCommon

const BENCHMARK_PREFIX = "@@LEAF13_FACTORED_BENCHMARK@@"
const BENCHMARK_SCHEMA = "windows-solver.leaf13-factored-benchmark/2"
const BENCHMARK_CLAIM_CEILING =
    "performance-and-numerical-response-only-not-math-validation"
const HISTORICAL_ACTIVE_LEG_RHS_EVALUATIONS = 1_960_000

function main()
    request = leaf13_request(
        precision_digits=80,
        operation="leaf13-three-leg-horizon-benchmark",
    )
    identity = source_runtime_identity(request)
    write_receipt_event(
        BENCHMARK_PREFIX,
        BENCHMARK_SCHEMA,
        "benchmark_started",
        identity,
        Dict{String,Any}(
            "leaf_id" => request["leaf_id"],
            "precision_digits" => request["precision_digits"],
            "historical_active_leg_rhs_evaluations" =>
                HISTORICAL_ACTIVE_LEG_RHS_EVALUATIONS,
            "homogeneous_representation" =>
                request["homogeneous_representation"],
            "horizon_contour" => request["horizon_contour"],
            "production_readiness_assertion_bypassed" => true,
        );
        claim_ceiling=BENCHMARK_CLAIM_CEILING,
    )

    try
        result = fixed_frequency_determinant_execution(request)
        write_receipt_event(
            BENCHMARK_PREFIX,
            BENCHMARK_SCHEMA,
            "benchmark_completed",
            identity,
            Dict{String,Any}(
                "succeeded" => true,
                "elapsed_seconds" => result.elapsed_seconds,
                "determinant_error" => result.determinant_evidence,
                "ode_statistics" => result.ode_statistics,
                "historical_active_leg_rhs_evaluations" =>
                    HISTORICAL_ACTIVE_LEG_RHS_EVALUATIONS,
            );
            claim_ceiling=BENCHMARK_CLAIM_CEILING,
        )
    catch failure
        evidence = typed_failure_evidence(request, failure)
        write_receipt_event(
            BENCHMARK_PREFIX,
            BENCHMARK_SCHEMA,
            "benchmark_failed",
            identity,
            Dict{String,Any}(
                "succeeded" => false,
                "failure" => evidence,
                "ode_statistics" => ode_statistics(),
            );
            claim_ceiling=BENCHMARK_CLAIM_CEILING,
        )
        showerror(stderr, failure, catch_backtrace())
        println(stderr)
        return 1
    end
    return 0
end

if abspath(PROGRAM_FILE) == @__FILE__
    exit(main())
end
