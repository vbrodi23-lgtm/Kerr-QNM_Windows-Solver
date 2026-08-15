#!/usr/bin/env julia

# Numerical-control calibration harness for the verified horizon-basis graph.
#
# This exists because the previous 120-digit controls were never measured. They
# were produced by a formula over the stored digit count -- 10^-(digits - 18) --
# which demanded a 1e-102 root target and handed the same tolerance to the
# coordinate map. The result was a coordinate leg pinned at 8.1e-17 steps:
# 2,000,002 RHS evaluations and 87.8 s to cover 1.01e-11 of a 5000 span.
#
# Replacing one guessed table with another guessed table would not be progress.
# So this harness measures how the determinant actually responds to each control
# and reports the evidence needed to choose a profile:
#
#   * coordinate-map identity residual, |r_*(r(rho)) - (rstar_match + t*rho)|
#   * the fixed-frequency determinant at each control rung
#   * the reference/verification endpoint disagreement (eta_endpoint)
#   * the base/tight-control disagreement (eta_control)
#   * the raw/normalised chart equivalence error (eta_equiv)
#   * RHS counts and wall time per rung
#   * derivative estimates at h/2, h, 2h and ih
#   * the resulting error-aware root-correction upper bound
#
# It starts from the demonstrated-healthy 80-digit level (1e-18 / 1e-20, which
# reached rho=5000 in 2,978 RHS evaluations on the exact Leaf 13 positive leg)
# and tightens in bounded rungs. It does not search: it reports, and the profile
# committed to the repository is expected to carry this receipt.
#
# Evidence ceiling: this measures numerical response and internal consistency.
# It is not a mathematical validation of the GSN representation, and it does not
# open the production-readiness gate.

const CALIBRATION_REPOSITORY_ROOT = normpath(joinpath(@__DIR__, ".."))
const CALIBRATION_LEG_HARNESS = joinpath(
    CALIBRATION_REPOSITORY_ROOT,
    "tools",
    "benchmark_leaf13_factored_legs.jl",
)

leg_harness_source = read(CALIBRATION_LEG_HARNESS, String)
leg_harness_definitions = first(split(
    leg_harness_source, "\ntry\n"; limit=2
))
include_string(Main, leg_harness_definitions, CALIBRATION_LEG_HARNESS)

const CALIBRATION_PREFIX = "@@LEAF13_HORIZON_CONTROL_CALIBRATION@@"
const CALIBRATION_SCHEMA =
    "windows-solver.leaf13-horizon-control-calibration/1"
const CALIBRATION_CLAIM_CEILING =
    "numerical-response-measurement-only-not-math-validation"

# Bounded rungs over the healthy 80-digit level. Each entry tightens both ODE
# families by the same factor so a change in the determinant can be attributed
# to control tightening rather than to which control moved.
const CONTROL_RUNGS = (
    (label="base", homogeneous_exponent=18, coordinate_exponent=18),
    (label="tight-1", homogeneous_exponent=22, coordinate_exponent=20),
    (label="tight-2", homogeneous_exponent=26, coordinate_exponent=22),
    (label="tight-3", homogeneous_exponent=30, coordinate_exponent=24),
)

# Derivative steps are explored over the same ladder the acceptance path uses,
# so the measured noise/curvature balance is the one the solver will act on.
const DERIVATIVE_STEP_EXPONENTS = (4, 6, 8, 10, 12, 16, 20)

function emit_calibration(
    kind::AbstractString; payload=Dict{String,Any}()
)
    println(CALIBRATION_PREFIX * JSON.json(Dict{String,Any}(
        "schema" => CALIBRATION_SCHEMA,
        "kind" => String(kind),
        "claim_ceiling" => CALIBRATION_CLAIM_CEILING,
        "payload" => payload,
    )))
    flush(stdout)
end

function calibration_request(
    ; precision_digits::Int, homogeneous_exponent::Int,
    coordinate_exponent::Int,
)
    request = benchmark_request()
    request["precision_digits"] = precision_digits
    request["working_precision_bits"] =
        ceil(Int, precision_digits * log2(10)) + 32
    for (key, exponent) in (
        ("homogeneous_ode_relative_tolerance", homogeneous_exponent),
        ("homogeneous_ode_absolute_tolerance", homogeneous_exponent + 2),
        ("coordinate_ode_relative_tolerance", coordinate_exponent),
        ("coordinate_ode_absolute_tolerance", coordinate_exponent + 2),
        ("ode_relative_tolerance", homogeneous_exponent),
        ("ode_absolute_tolerance", homogeneous_exponent + 2),
    )
        request[key] = "1e-$(exponent)"
    end
    return request
end

"""
    measure_rung(request, label)

Evaluate one determinant at fixed frequency under one control rung.

Returns the determinant value, its published absolute error, the endpoint
disagreement that produced that error, the chart diagnostics, and the RHS/time
cost. Any typed control failure is captured rather than thrown, because a rung
that fails is itself a calibration result -- it bounds the usable range.
"""
function measure_rung(request, label::AbstractString)
    bits = parse_integer(request, "working_precision_bits")
    return setprecision(BigFloat, bits) do
        REQUEST_STARTED_NS[] = time_ns()
        ACTIVE_PHASE_STARTED_NS[] = REQUEST_STARTED_NS[]
        ACTIVE_PHASE[] = "HORIZON_CONTROL_CALIBRATION"
        omega = parse_complex(BigFloat, request, "omega_re", "omega_im")
        amplitude = parse_complex(
            BigFloat, request, "amplitude_re", "amplitude_im"
        )
        context = build_determinant_request_context(
            BigFloat, request, omega
        )
        started = time_ns()
        try
            evaluation = evaluate_horizon_determinant(
                BigFloat, request, context, omega, amplitude
            )
            elapsed = (time_ns() - started) / 1.0e9
            diagnostics = evaluation.diagnostics
            return (
                label=label,
                succeeded=true,
                value=evaluation.value,
                numerical_error_abs=evaluation.numerical_error_abs,
                error_model_id=evaluation.error_model_id,
                normalised_determinant_abs=
                    diagnostics.normalised_determinant_abs,
                raw_determinant_abs=diagnostics.raw_determinant_abs,
                basis_condition=diagnostics.maximum_basis_condition,
                basis_backward_error=
                    diagnostics.maximum_basis_backward_error,
                matching_reconstruction_residual=
                    diagnostics.maximum_matching_reconstruction_residual,
                cref_chart_margin=diagnostics.minimum_cref_chart_margin,
                carrier_change_error=
                    diagnostics.maximum_carrier_change_error,
                elapsed_seconds=elapsed,
                failure=nothing,
            )
        catch failure
            elapsed = (time_ns() - started) / 1.0e9
            translated = translate_numerical_control_failure(request, failure)
            detail = translated isa WorkerControlFailure ?
                get(failure_details(translated), "failure_code", "UNKNOWN") :
                string(typeof(failure))
            return (
                label=label,
                succeeded=false,
                value=nothing,
                numerical_error_abs=nothing,
                error_model_id=nothing,
                normalised_determinant_abs=nothing,
                raw_determinant_abs=nothing,
                basis_condition=nothing,
                basis_backward_error=nothing,
                matching_reconstruction_residual=nothing,
                cref_chart_margin=nothing,
                carrier_change_error=nothing,
                elapsed_seconds=elapsed,
                failure=(code=detail, message=sprint(showerror, failure)),
            )
        end
    end
end

optional_text(value) = value === nothing ? nothing : string(value)

function rung_payload(measurement, rung, precision_digits::Int)
    return Dict{String,Any}(
        "label" => measurement.label,
        "precision_digits" => precision_digits,
        "homogeneous_ode_relative_tolerance" =>
            "1e-$(rung.homogeneous_exponent)",
        "coordinate_ode_relative_tolerance" =>
            "1e-$(rung.coordinate_exponent)",
        "succeeded" => measurement.succeeded,
        "determinant_abs" => measurement.value === nothing ?
            nothing : string(abs(measurement.value)),
        "determinant_re" => measurement.value === nothing ?
            nothing : string(real(measurement.value)),
        "determinant_im" => measurement.value === nothing ?
            nothing : string(imag(measurement.value)),
        "numerical_error_abs" =>
            optional_text(measurement.numerical_error_abs),
        "error_model_id" => measurement.error_model_id,
        "normalised_determinant_abs" =>
            optional_text(measurement.normalised_determinant_abs),
        "raw_determinant_abs" =>
            optional_text(measurement.raw_determinant_abs),
        "basis_condition" => optional_text(measurement.basis_condition),
        "basis_backward_error" =>
            optional_text(measurement.basis_backward_error),
        "matching_reconstruction_residual" =>
            optional_text(measurement.matching_reconstruction_residual),
        "cref_chart_margin" => optional_text(measurement.cref_chart_margin),
        "carrier_change_error" =>
            optional_text(measurement.carrier_change_error),
        "elapsed_seconds" => measurement.elapsed_seconds,
        "failure_code" => measurement.failure === nothing ?
            nothing : measurement.failure.code,
        "failure_message" => measurement.failure === nothing ?
            nothing : measurement.failure.message,
    )
end

"""
    measure_derivative_ladder(request, precision_digits)

Report the finite-difference derivative across a bounded step ladder.

For a centred difference the derivative error behaves as

    delta_D' ~ |D'''| h^2 / 6  +  eta_D / h

so the usable step is set by measured determinant noise against measured
curvature. It cannot be read off the stored digit count, which is exactly the
mistake the fixed 1e-60 step encoded.
"""
function measure_derivative_ladder(request, precision_digits::Int)
    bits = parse_integer(request, "working_precision_bits")
    return setprecision(BigFloat, bits) do
        REQUEST_STARTED_NS[] = time_ns()
        ACTIVE_PHASE_STARTED_NS[] = REQUEST_STARTED_NS[]
        ACTIVE_PHASE[] = "HORIZON_DERIVATIVE_CALIBRATION"
        omega = parse_complex(BigFloat, request, "omega_re", "omega_im")
        amplitude = parse_complex(
            BigFloat, request, "amplitude_re", "amplitude_im"
        )
        context = build_determinant_request_context(
            BigFloat, request, omega
        )
        results = Dict{String,Any}[]
        for exponent in DERIVATIVE_STEP_EXPONENTS
            h = parse(BigFloat, "1e-$(exponent)") * (one(BigFloat) + abs(omega))
            for (axis, offset) in (
                ("real", Complex{BigFloat}(h, zero(BigFloat))),
                ("imaginary", Complex{BigFloat}(zero(BigFloat), h)),
            )
                started = time_ns()
                try
                    derivative, diagnostics, derivative_error_abs =
                        finite_difference_pair(
                            BigFloat,
                            request,
                            context,
                            omega,
                            amplitude,
                            offset,
                            "calibration 1e-$(exponent) $(axis)",
                            omega;
                            axis=axis,
                        )
                    push!(results, Dict{String,Any}(
                        "step_exponent" => exponent,
                        "h" => string(h),
                        "axis" => axis,
                        "succeeded" => true,
                        "derivative_abs" => string(abs(derivative)),
                        "derivative_error_abs" =>
                            string(derivative_error_abs),
                        "derivative_lower_bound_abs" =>
                            string(abs(derivative) - derivative_error_abs),
                        "kappa_fd" => string(diagnostics.kappa),
                        "finite_difference_digits_lost" =>
                            string(diagnostics.finite_difference_digits_lost),
                        "saturation_status" => diagnostics.saturation_status,
                        "elapsed_seconds" => (time_ns() - started) / 1.0e9,
                    ))
                catch failure
                    push!(results, Dict{String,Any}(
                        "step_exponent" => exponent,
                        "h" => string(h),
                        "axis" => axis,
                        "succeeded" => false,
                        "failure_message" => sprint(showerror, failure),
                        "elapsed_seconds" => (time_ns() - started) / 1.0e9,
                    ))
                end
            end
        end
        return results
    end
end

function run_control_calibration(; precision_digits::Int=80)
    emit_calibration("calibration_started"; payload=Dict{String,Any}(
        "leaf_id" => "leaf-13-221-0.95-horizon-admittance",
        "precision_digits" => precision_digits,
        "rungs" => [rung.label for rung in CONTROL_RUNGS],
        "derivative_step_exponents" =>
            collect(DERIVATIVE_STEP_EXPONENTS),
        "production_readiness_assertion_bypassed" => true,
    ))

    measurements = Any[]
    for rung in CONTROL_RUNGS
        request = calibration_request(
            precision_digits=precision_digits,
            homogeneous_exponent=rung.homogeneous_exponent,
            coordinate_exponent=rung.coordinate_exponent,
        )
        validate_regularised_gsn_policy(request)
        measurement = measure_rung(request, rung.label)
        push!(measurements, (rung=rung, measurement=measurement))
        emit_calibration(
            "control_rung_measured";
            payload=rung_payload(measurement, rung, precision_digits),
        )
    end

    # eta_control: how much the determinant moves when the controls tighten.
    # A control profile is only defensible when this has fallen below the
    # scientific target the root acceptance is asked to certify.
    successful = filter(entry -> entry.measurement.succeeded, measurements)
    control_differences = Dict{String,Any}[]
    if length(successful) >= 2
        baseline = first(successful).measurement
        for entry in successful[2:end]
            push!(control_differences, Dict{String,Any}(
                "from" => baseline.label,
                "to" => entry.measurement.label,
                "eta_control_abs" =>
                    string(abs(baseline.value - entry.measurement.value)),
                "reference_determinant_abs" => string(abs(baseline.value)),
                "reference_numerical_error_abs" =>
                    optional_text(baseline.numerical_error_abs),
            ))
        end
    end
    emit_calibration("control_response_measured"; payload=Dict{String,Any}(
        "successful_rungs" => length(successful),
        "total_rungs" => length(measurements),
        "control_differences" => control_differences,
    ))

    if !isempty(successful)
        base_request = calibration_request(
            precision_digits=precision_digits,
            homogeneous_exponent=first(successful).rung.homogeneous_exponent,
            coordinate_exponent=first(successful).rung.coordinate_exponent,
        )
        ladder = measure_derivative_ladder(base_request, precision_digits)
        emit_calibration(
            "derivative_ladder_measured";
            payload=Dict{String,Any}(
                "precision_digits" => precision_digits,
                "estimates" => ladder,
            ),
        )
    end

    emit_calibration("calibration_completed"; payload=Dict{String,Any}(
        "precision_digits" => precision_digits,
        "successful_rungs" => length(successful),
        "selection_is_automatic" => false,
        "note" =>
            "control profile selection is a committed decision carrying this " *
            "receipt; the harness measures, it does not choose",
    ))
    return nothing
end

if abspath(PROGRAM_FILE) == @__FILE__
    digits = length(ARGS) >= 1 ? parse(Int, ARGS[1]) : 80
    try
        run_control_calibration(precision_digits=digits)
    catch failure
        emit_calibration("calibration_failed"; payload=Dict{String,Any}(
            "error_type" => string(typeof(failure)),
            "message" => sprint(showerror, failure),
        ))
        showerror(stderr, failure, catch_backtrace())
        println(stderr)
        exit(1)
    end
end
