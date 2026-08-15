#!/usr/bin/env julia

# Bounded numerical-control calibration for the production three-leg Leaf 13
# horizon determinant.  It emits evidence; it does not select or admit a
# production profile.

include(joinpath(@__DIR__, "leaf13_horizon_harness_common.jl"))
using .Leaf13HorizonHarnessCommon

const CALIBRATION_PREFIX = "@@LEAF13_HORIZON_CONTROL_CALIBRATION@@"
const CALIBRATION_SCHEMA =
    "windows-solver.leaf13-horizon-control-calibration/2"
const CALIBRATION_CLAIM_CEILING =
    "numerical-response-measurement-only-not-math-validation"

const CONTROL_RUNGS = (
    (label="base", homogeneous_exponent=18, coordinate_exponent=18),
    (label="tight-1", homogeneous_exponent=22, coordinate_exponent=20),
    (label="tight-2", homogeneous_exponent=26, coordinate_exponent=22),
    (label="tight-3", homogeneous_exponent=30, coordinate_exponent=24),
)
const DERIVATIVE_STEP_EXPONENTS = (4, 6, 8, 10, 12, 16, 20)

function emit_calibration(identity, kind::AbstractString; payload)
    write_receipt_event(
        CALIBRATION_PREFIX,
        CALIBRATION_SCHEMA,
        kind,
        identity,
        payload;
        claim_ceiling=CALIBRATION_CLAIM_CEILING,
    )
end

function calibration_request(
    ; precision_digits::Int,
    homogeneous_exponent::Int,
    coordinate_exponent::Int,
)
    return leaf13_request(
        precision_digits=precision_digits,
        homogeneous_exponent=homogeneous_exponent,
        coordinate_exponent=coordinate_exponent,
        operation="leaf13-horizon-control-calibration",
    )
end

function measure_rung(request, label::AbstractString)
    started = time_ns()
    try
        result = fixed_frequency_determinant_execution(request)
        diagnostics = result.evaluation.diagnostics
        return (
            label=String(label),
            succeeded=true,
            value=result.evaluation.value,
            determinant_error=result.determinant_evidence,
            normalised_determinant_abs=
                diagnostics.normalised_determinant_abs,
            raw_determinant_abs=diagnostics.raw_determinant_abs,
            basis_condition=diagnostics.maximum_basis_condition,
            basis_backward_error=
                diagnostics.maximum_basis_backward_error,
            matching_reconstruction_residual=
                diagnostics.maximum_matching_reconstruction_residual,
            cref_chart_margin=diagnostics.minimum_cref_chart_margin,
            carrier_change_error=diagnostics.maximum_carrier_change_error,
            ode_statistics=result.ode_statistics,
            elapsed_seconds=result.elapsed_seconds,
            failure=nothing,
        )
    catch failure
        evidence = typed_failure_evidence(request, failure)
        return (
            label=String(label),
            succeeded=false,
            value=nothing,
            determinant_error=nothing,
            normalised_determinant_abs=nothing,
            raw_determinant_abs=nothing,
            basis_condition=nothing,
            basis_backward_error=nothing,
            matching_reconstruction_residual=nothing,
            cref_chart_margin=nothing,
            carrier_change_error=nothing,
            ode_statistics=ode_statistics(),
            elapsed_seconds=(time_ns() - started) / 1.0e9,
            failure=evidence,
        )
    end
end

function rung_payload(measurement, rung, precision_digits::Int)
    return Dict{String,Any}(
        "label" => measurement.label,
        "precision_digits" => precision_digits,
        "homogeneous_ode_relative_tolerance" =>
            "1e-$(rung.homogeneous_exponent)",
        "coordinate_ode_relative_tolerance" =>
            "1e-$(rung.coordinate_exponent)",
        "succeeded" => measurement.succeeded,
        "determinant_error" => measurement.determinant_error,
        "normalised_determinant_abs" =>
            optional_text(measurement.normalised_determinant_abs),
        "raw_determinant_abs" =>
            optional_text(measurement.raw_determinant_abs),
        "basis_condition" => optional_text(measurement.basis_condition),
        "basis_backward_error" =>
            optional_text(measurement.basis_backward_error),
        "matching_reconstruction_residual" =>
            optional_text(measurement.matching_reconstruction_residual),
        "cref_chart_margin" =>
            optional_text(measurement.cref_chart_margin),
        "carrier_change_error" =>
            optional_text(measurement.carrier_change_error),
        "ode_statistics" => measurement.ode_statistics,
        "elapsed_seconds" => measurement.elapsed_seconds,
        "failure" => measurement.failure,
    )
end

function run_control_calibration(; precision_digits::Int=80)
    identity_request = calibration_request(
        precision_digits=precision_digits,
        homogeneous_exponent=first(CONTROL_RUNGS).homogeneous_exponent,
        coordinate_exponent=first(CONTROL_RUNGS).coordinate_exponent,
    )
    identity = source_runtime_identity(identity_request)
    emit_calibration(identity, "calibration_started"; payload=Dict{String,Any}(
        "leaf_id" => identity_request["leaf_id"],
        "precision_digits" => precision_digits,
        "rungs" => [rung.label for rung in CONTROL_RUNGS],
        "derivative_step_exponents" =>
            collect(DERIVATIVE_STEP_EXPONENTS),
        "control_profile_label" => CONTROL_PROFILE_LABEL,
        "calibration_status" => CALIBRATION_STATUS,
        "production_readiness_assertion_bypassed" => true,
    ))

    measurements = Any[]
    for rung in CONTROL_RUNGS
        request = calibration_request(
            precision_digits=precision_digits,
            homogeneous_exponent=rung.homogeneous_exponent,
            coordinate_exponent=rung.coordinate_exponent,
        )
        measurement = measure_rung(request, rung.label)
        push!(measurements, (rung=rung, measurement=measurement))
        emit_calibration(identity, "control_rung_measured"; payload=
            rung_payload(measurement, rung, precision_digits))
    end

    successful = filter(entry -> entry.measurement.succeeded, measurements)
    control_differences = Dict{String,Any}[]
    if length(successful) >= 2
        baseline = first(successful).measurement
        for entry in successful[2:end]
            push!(control_differences, Dict{String,Any}(
                "from" => baseline.label,
                "to" => entry.measurement.label,
                "control_disagreement_abs" =>
                    string(abs(baseline.value - entry.measurement.value)),
                "reference_numerical_error_abs" =>
                    baseline.determinant_error["numerical_error_abs"],
            ))
        end
    end
    emit_calibration(identity, "control_response_measured"; payload=
        Dict{String,Any}(
            "successful_rungs" => length(successful),
            "total_rungs" => length(measurements),
            "control_differences" => control_differences,
        ))

    if !isempty(successful)
        base = first(successful)
        request = calibration_request(
            precision_digits=precision_digits,
            homogeneous_exponent=base.rung.homogeneous_exponent,
            coordinate_exponent=base.rung.coordinate_exponent,
        )
        ladder = derivative_ladder_execution(
            request, DERIVATIVE_STEP_EXPONENTS
        )
        emit_calibration(identity, "derivative_ladder_measured"; payload=
            Dict{String,Any}(
                "precision_digits" => precision_digits,
                "estimates" => ladder,
            ))
    end

    emit_calibration(identity, "calibration_completed"; payload=
        Dict{String,Any}(
            "precision_digits" => precision_digits,
            "successful_rungs" => length(successful),
            "selection_is_automatic" => false,
            "calibration_status" => CALIBRATION_STATUS,
            "note" =>
                "profile remains provisional until this native receipt is " *
                "reviewed and its selected controls are committed",
        ))
    return 0
end

function main()
    digits = length(ARGS) >= 1 ? parse(Int, ARGS[1]) : 80
    return run_control_calibration(precision_digits=digits)
end

if abspath(PROGRAM_FILE) == @__FILE__
    try
        exit(main())
    catch failure
        showerror(stderr, failure, catch_backtrace())
        println(stderr)
        exit(1)
    end
end
