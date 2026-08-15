# Pure algebraic specification for the worker finite-difference diagnostic.
# It intentionally performs no solver, ODE, PowerShell, or external I/O work.
# This specification is written for the user's authenticated Julia environment
# and is not executed in the implementation airgap session.

using Test

include("m02_worker.jl")

function finite_difference_control_request(;
    frequency_step="1e-6",
    frequency_step_minimum="1e-12",
    frequency_step_maximum="1e-3",
    determinant_error_safety_factor="8",
)
    digest = repeat("0", 64)
    return Dict{String,Any}(
        "precision_digits" => 80,
        "request_sha256" => digest,
        "job_id" => "finite-difference-spec",
        "leaf_id" => 13,
        "role" => "specification",
        "job_policy_sha256" => digest,
        "backend_identity_sha256" => digest,
        "refinement_level" => 0,
        "resource_policy_schema" =>
            "windows-solver.execution-resource-policy/1",
        "resource_policy_version" => 1,
        "resource_policy_sha256" => digest,
        "frequency_step" => frequency_step,
        "frequency_step_minimum" => frequency_step_minimum,
        "frequency_step_maximum" => frequency_step_maximum,
        "determinant_error_safety_factor" => determinant_error_safety_factor,
        # Needed only to build a real DeterminantRequestContext for the
        # executed caller-chain testsets; the algebraic testsets ignore them.
        "spin" => "0.95",
        "m" => 2,
    )
end

@testset "determinant error breakdown validates and aggregates absolute components" begin
    request = finite_difference_control_request()
    breakdown = determinant_error_breakdown(
        Float64,
        request,
        2.0;
        control_disagreement_abs=3.0,
        equivalence_disagreement_abs=5.0,
        precision_disagreement_abs=nothing,
    )
    @test breakdown.endpoint_disagreement_abs == 2.0
    @test breakdown.control_disagreement_abs == 3.0
    @test breakdown.equivalence_disagreement_abs == 5.0
    @test breakdown.precision_disagreement_abs === nothing
    @test breakdown.safety_factor == 8.0
    @test breakdown.numerical_error_abs == 40.0
    @test_throws ArgumentError determinant_error_breakdown(
        Float64, request, -1.0
    )
    @test_throws ArgumentError determinant_error_breakdown(
        Float64, request, 1.0; control_disagreement_abs=Inf
    )
end

@testset "centred stencil propagates unequal endpoint errors" begin
    @test propagated_centered_difference_error(2.0, 6.0, 2.0) == 2.0
    @test propagated_centered_difference_error(1.0, 9.0, 0.5) == 10.0
end

#####
##### Executed caller-chain specification
#####
#
# The helper above is pure algebra. Asserting it alone leaves the question that
# actually matters unanswered: whether the error a sample carries reaches the
# bound the ladder decides on, through finite_difference_pair, final_derivative
# and the rung search as production calls them. These testsets execute that
# chain against a controlled determinant.

const SPEC_ROOT = complex(0.5, -0.1)

"""
    spec_determinant_evaluator(; slope, plus_error, minus_error, calls)

Return a determinant evaluator with an exactly known derivative.

`D(omega) = slope * (omega - SPEC_ROOT)` is linear, so every centred difference
returns `slope` exactly at every step. Step disagreement is therefore zero by
construction and the only thing that can move the derivative lower bound is the
propagated determinant error -- which is what these tests are about.

The two half-stencil samples carry deliberately unequal errors so a chain that
silently used one endpoint twice, or averaged before propagating, would show up.
"""
function spec_determinant_evaluator(;
    slope::ComplexF64=complex(2.0, 0.0),
    plus_error::Float64=1.0e-12,
    minus_error::Float64=5.0e-13,
    calls::Union{Nothing,Vector{ComplexF64}}=nothing,
)
    return function (
        value_type, request, context, omega, amplitude, purpose, current
    )
        calls === nothing || push!(calls, ComplexF64(omega))
        error_abs = real(omega) >= real(SPEC_ROOT) ? plus_error : minus_error
        breakdown = DeterminantErrorBreakdown{Float64}(
            error_abs, nothing, nothing, nothing, 1.0, error_abs
        )
        return (
            value=slope * (omega - SPEC_ROOT),
            error_breakdown=breakdown,
            error_model_id="specification-evaluator/v1",
        )
    end
end

function spec_request_context(request)
    return build_determinant_request_context(Float64, request, SPEC_ROOT)
end

@testset "sample errors reach the accepted bound through the real chain" begin
    request = finite_difference_control_request()
    context = spec_request_context(request)
    calls = ComplexF64[]
    evaluator = spec_determinant_evaluator(calls=calls)

    ladder = evaluate_derivative_step_ladder(
        Float64,
        request,
        context,
        SPEC_ROOT,
        complex(0.0, 0.0),
        nothing;
        authenticate_controls=true,
        determinant_evaluator=evaluator,
    )

    # A linear determinant differentiates exactly, so the estimate is the slope
    # and the step disagreement is zero at every rung.
    @test ladder.derivative_real_half ≈ complex(2.0, 0.0)
    @test ladder.derivative_uncertainty_abs ≈ 0.0 atol = 1.0e-9

    # The accepted derivative is the h/2 estimate, so the reported step is h/2
    # and the reported error is the error propagated at that step, not at h.
    authentication = ladder.derivative_authentication
    @test authentication.step ≈ ladder.h / 2
    expected_error = propagated_centered_difference_error(
        1.0e-12, 5.0e-13, ladder.h / 2
    )
    @test authentication.propagated_error_abs ≈ expected_error
    @test ladder.derivative_error_abs ≈ expected_error
    # Unequal endpoint errors must not collapse to either one alone.
    @test authentication.propagated_error_abs !=
        propagated_centered_difference_error(1.0e-12, 1.0e-12, ladder.h / 2)

    # The lower bound is the estimate less both the step disagreement and the
    # propagated error, and it is what acceptance was decided on.
    @test authentication.lower_bound_abs ≈
        abs(ladder.derivative_real_half) -
        ladder.derivative_uncertainty_abs -
        expected_error
    @test authentication.lower_bound_abs > 0

    # Four samples per rung -- h, h/2, 2h, ih -- each a centred pair.
    @test length(calls) == 8
    @test ladder.rung_index == 1
end

@testset "unresolved noise exhausts the range with a typed failure" begin
    request = finite_difference_control_request()
    context = spec_request_context(request)
    calls = ComplexF64[]
    # An error far larger than the derivative can never leave a positive lower
    # bound at any step, so every rung must be rejected.
    evaluator = spec_determinant_evaluator(
        plus_error=1.0e6, minus_error=1.0e6, calls=calls
    )

    failure = try
        evaluate_derivative_step_ladder(
            Float64,
            request,
            context,
            SPEC_ROOT,
            complex(0.0, 0.0),
            nothing;
            authenticate_controls=true,
            determinant_evaluator=evaluator,
        )
        nothing
    catch caught
        caught
    end

    @test failure isa NumericalControlFailure
    details = failure_details(failure)
    @test details["failure_code"] == "FINITE_DIFFERENCE_NOISE_LIMIT"
    attempts = details["attempts"]
    # Exhaustion is finite and every attempt records which condition failed.
    @test !isempty(attempts)
    @test length(attempts) <= MAXIMUM_FREQUENCY_STEP_RUNGS
    @test all(attempt -> attempt["accepted"] == false, attempts)
    @test all(attempt -> attempt["noise_resolved"] == false, attempts)
    @test length(calls) == 8 * length(attempts)
end

@testset "unauthenticated control keeps the single-step historical path" begin
    request = finite_difference_control_request()
    context = spec_request_context(request)
    calls = ComplexF64[]
    evaluator = spec_determinant_evaluator(calls=calls)

    ladder = evaluate_derivative_step_ladder(
        Float64,
        request,
        context,
        SPEC_ROOT,
        complex(0.0, 0.0),
        nothing;
        authenticate_controls=false,
        determinant_evaluator=evaluator,
    )

    # No rung search: one step, taken at the nominal policy value. The exterior
    # scientific identity is unchanged by this work, so its derivative
    # selection must be unchanged too -- otherwise two runs under one identity
    # could disagree.
    @test ladder.rung_count == 1
    @test ladder.rung_index == 1
    @test ladder.h ≈ validated_frequency_step(Float64, request) *
        (1.0 + abs(SPEC_ROOT))
    @test length(calls) == 8
    @test ladder.derivative_real_half ≈ complex(2.0, 0.0)

    # The accepted Newton derivative is reused on this path, which removes the
    # base pair.
    reuse_calls = ComplexF64[]
    reused = evaluate_derivative_step_ladder(
        Float64,
        request,
        context,
        SPEC_ROOT,
        complex(0.0, 0.0),
        complex(2.0, 0.0);
        authenticate_controls=false,
        determinant_evaluator=spec_determinant_evaluator(calls=reuse_calls),
    )
    @test reused.derivative_real_base ≈ complex(2.0, 0.0)
    @test length(reuse_calls) == 6
end

@testset "a narrow range cannot silently sample outside policy" begin
    # The authenticated search needs room for h/2 and 2h; a range narrower than
    # a factor of four has none, and must be refused rather than evaluated
    # outside the configured bounds.
    request = finite_difference_control_request(
        frequency_step="1e-6",
        frequency_step_minimum="1e-6",
        frequency_step_maximum="2e-6",
    )
    context = spec_request_context(request)
    @test_throws NumericalControlFailure evaluate_derivative_step_ladder(
        Float64,
        request,
        context,
        SPEC_ROOT,
        complex(0.0, 0.0),
        nothing;
        authenticate_controls=true,
        determinant_evaluator=spec_determinant_evaluator(),
    )

    # The unauthenticated path only ever uses the nominal step, so the same
    # narrow policy remains usable there.
    ladder = evaluate_derivative_step_ladder(
        Float64,
        request,
        context,
        SPEC_ROOT,
        complex(0.0, 0.0),
        nothing;
        authenticate_controls=false,
        determinant_evaluator=spec_determinant_evaluator(),
    )
    @test ladder.rung_count == 1
end

@testset "frequency step rungs are finite bounded and de-duplicated" begin
    request = finite_difference_control_request(
        frequency_step="1e-6",
        frequency_step_minimum="1e-6",
        frequency_step_maximum="1e-3",
    )
    nominal, minimum_step, maximum_step = validated_frequency_steps(
        Float64, request
    )
    @test minimum_step <= nominal <= maximum_step
    rungs = frequency_step_rungs(nominal, minimum_step, maximum_step)
    @test all(isfinite, rungs)
    @test length(rungs) == length(unique(rungs))
    @test length(rungs) <= MAXIMUM_FREQUENCY_STEP_RUNGS

    # Every rung evaluates h/2, h and 2h, and reports h/2 as the accepted step.
    # Bounding h alone would let the finest sample fall below the configured
    # minimum and the coarsest rise above the configured maximum, so the range
    # actually evaluated would not be the range that was configured. Assert the
    # samples, not just the rung.
    for step in rungs
        @test minimum_step <= step / 2 <= maximum_step
        @test minimum_step <= step <= maximum_step
        @test minimum_step <= 2 * step <= maximum_step
    end

    # The accepted step reported by the ladder is h/2 and must also be inside
    # policy for whichever rung is selected.
    finest, coarsest = admissible_frequency_step_interval(
        minimum_step, maximum_step
    )
    @test all(step -> finest <= step <= coarsest, rungs)
    @test minimum(rungs) / 2 >= minimum_step
    @test 2 * maximum(rungs) <= maximum_step

    for invalid in ("0", "-1", "Inf", "NaN")
        @test_throws NumericalControlFailure validated_frequency_steps(
            Float64,
            finite_difference_control_request(frequency_step=invalid),
        )
    end
    @test_throws NumericalControlFailure validated_frequency_steps(
        Float64,
        finite_difference_control_request(
            frequency_step="1e-8",
            frequency_step_minimum="1e-6",
        ),
    )
    # A range narrower than a factor of four cannot hold any admissible rung,
    # so it is rejected at policy validation rather than deep in the search.
    @test_throws NumericalControlFailure validated_frequency_steps(
        Float64,
        finite_difference_control_request(
            frequency_step="1e-6",
            frequency_step_minimum="1e-6",
            frequency_step_maximum="2e-6",
        ),
    )
end

@testset "rung anchoring keeps a boundary nominal step admissible" begin
    # A nominal step sitting on the policy boundary would sample 2h outside the
    # maximum. The anchor moves inside the admissible interval instead, and the
    # samples stay in range.
    request = finite_difference_control_request(
        frequency_step="1e-3",
        frequency_step_minimum="1e-9",
        frequency_step_maximum="1e-3",
    )
    nominal, minimum_step, maximum_step = validated_frequency_steps(
        Float64, request
    )
    @test nominal == maximum_step
    rungs = frequency_step_rungs(nominal, minimum_step, maximum_step)
    @test !isempty(rungs)
    for step in rungs
        @test minimum_step <= step / 2
        @test 2 * step <= maximum_step
    end
    @test maximum(rungs) <= maximum_step / 2
end

@testset "determinant ranking includes absolute numerical error" begin
    smaller_raw_larger_bound = (
        value=complex(1.0, 0.0),
        error_breakdown=(numerical_error_abs=10.0,),
    )
    larger_raw_smaller_bound = (
        value=complex(2.0, 0.0),
        error_breakdown=(numerical_error_abs=0.5,),
    )
    @test determinant_is_better(
        Float64, larger_raw_smaller_bound, smaller_raw_larger_bound
    )
    @test !determinant_is_better(
        Float64, smaller_raw_larger_bound, larger_raw_smaller_bound
    )
end

@testset "nonfinite stencil values are typed range failures" begin
    @test_throws FiniteDifferenceRangeError build_finite_difference_diagnostics(
        complex(Inf, 0.0),
        complex(1.0, 0.0),
        complex(1.0e-6, 0.0);
        axis="real",
    )
end

function assert_range_translation(
    range_failure::FiniteDifferenceRangeError,
    axis::String,
    h::T,
) where {T<:AbstractFloat}
    translated = translate_numerical_control_failure(
        finite_difference_control_request(),
        range_failure;
        finite_difference_axis=axis,
        finite_difference_h=h,
    )
    @test translated isa NumericalControlFailure
    if translated isa NumericalControlFailure
        details = failure_details(translated)
        @test details["failure_code"] ==
            "ALGEBRAIC_REPRESENTATION_SINGULAR"
        @test details["failure_class"] == "CONTROL"
        @test details["retryable"] == false
        diagnostics = details["diagnostics"]
        @test diagnostics["range_status"] == range_failure.status
        @test diagnostics["axis"] == axis
        @test diagnostics["h"] == string(h)
        @test !haskey(
            diagnostics, "factored_homogeneous_rhs_evaluations"
        )
        @test !haskey(diagnostics, "avoided_ode_scope")
        @test !haskey(diagnostics, "asymptotic_preflight_avoided_ode")
    end
end

function cancellation_sensitive_map(::Type{T}, z::Complex{T}) where {
    T<:AbstractFloat
}
    constant = complex(T(10)^8, zero(T))
    linear = complex(T(2), -T(3))
    return constant + z^2 + linear * z
end

function exercise_cancellation_axis(
    ::Type{T},
    direction::Complex{T},
    axis::String,
) where {T<:AbstractFloat}
    omega = complex(T(3) / T(4), -T(2) / T(5))
    exact_derivative = T(2) * omega + complex(T(2), -T(3))
    step_sizes = T[T(1) / T(10)^3, T(1) / T(10)^4, T(1) / T(10)^5]
    derivatives = Complex{T}[]
    diagnostics = FiniteDifferenceDiagnostics{T}[]

    for h in step_sizes
        offset = direction * h
        d_plus = cancellation_sensitive_map(T, omega + offset)
        d_minus = cancellation_sensitive_map(T, omega - offset)
        derivative, assessment = build_finite_difference_diagnostics(
            d_plus,
            d_minus,
            offset;
            axis=axis,
        )
        push!(derivatives, derivative)
        push!(diagnostics, assessment)
        @test assessment.axis == axis
        @test assessment.h == h
        @test isapprox(
            assessment.derivative_abs,
            abs(derivative);
            rtol=T(4) * eps(T),
        )
        @test !assessment.underflow_observed
    end

    tolerance = T(32) * eps(T) * T(10)^8 / minimum(step_sizes)
    @test tolerance < abs(exact_derivative) / T(4)
    @test all(isapprox.(
        derivatives,
        Ref(exact_derivative);
        rtol=zero(T),
        atol=tolerance,
    ))
    kappas = getproperty.(diagnostics, :kappa)
    digits_lost = getproperty.(diagnostics, :finite_difference_digits_lost)
    @test all(diff(kappas) .> zero(T))
    @test all(diff(digits_lost) .> zero(T))
end

function linear_map(::Type{T}, z::Complex{T}) where {T<:AbstractFloat}
    slope = complex(T(7) / T(3), -T(5) / T(4))
    return complex(T(11), T(13)) + slope * z
end

@testset "cancellation evidence worsens as real-axis h shrinks" begin
    exercise_cancellation_axis(Float64, 1.0 + 0.0im, "real")
    setprecision(BigFloat, 192) do
        exercise_cancellation_axis(
            BigFloat,
            complex(one(BigFloat), zero(BigFloat)),
            "real",
        )
    end
end

@testset "cancellation evidence worsens as imaginary-axis h shrinks" begin
    exercise_cancellation_axis(Float64, 0.0 + 1.0im, "imaginary")
    setprecision(BigFloat, 192) do
        exercise_cancellation_axis(
            BigFloat,
            complex(zero(BigFloat), one(BigFloat)),
            "imaginary",
        )
    end
end

@testset "diagnostic algebra avoids overflowing the raw difference" begin
    huge = Float64(0.75) * floatmax(Float64)
    derivative, assessment = build_finite_difference_diagnostics(
        complex(huge, 0.0),
        complex(-huge, 0.0),
        1.0 + 0.0im;
        axis="real",
    )
    @test isfinite(real(derivative))
    @test derivative == complex(huge, 0.0)
    @test assessment.difference_abs == floatmax(Float64)
    @test assessment.difference_abs_saturated
    @test assessment.kappa == 1.0
    @test !assessment.kappa_saturated
    @test assessment.saturation_observed
    @test assessment.saturation_status == "magnitude-clamped/v1"
    @test all(isfinite, (
        assessment.difference_abs,
        assessment.kappa,
        assessment.finite_difference_digits_lost,
        assessment.derivative_abs,
    ))
end

@testset "diagnostic algebra avoids underflow before division" begin
    tiny = nextfloat(0.0)
    derivative, assessment = build_finite_difference_diagnostics(
        complex(tiny, 0.0),
        complex(0.0, 0.0),
        complex(tiny, 0.0);
        axis="real",
    )
    @test derivative == 0.5 + 0.0im
    @test assessment.derivative_abs == 0.5
    @test assessment.difference_abs == tiny
    @test assessment.kappa == 1.0
    @test !assessment.saturation_observed
end


@testset "common large component cannot erase a subnormal difference" begin
    tiny = nextfloat(0.0)
    derivative, assessment = build_finite_difference_diagnostics(
        complex(floatmax(Float64), tiny),
        complex(floatmax(Float64), 0.0),
        complex(tiny, 0.0);
        axis="real",
    )
    @test derivative == 0.0 + 0.5im
    @test assessment.difference_abs == tiny
    @test !assessment.difference_abs_saturated
    @test !assessment.d_plus_abs_saturated
    @test assessment.d_minus_abs_saturated == false
end


@testset "finite kappa matches its defining equivalent form" begin
    d_plus = 3.0 + 4.0im
    d_minus = 1.0 + 0.0im
    exact_kappa = (abs(d_plus) + abs(d_minus)) / abs(d_plus - d_minus)
    _, assessment = build_finite_difference_diagnostics(
        d_plus,
        d_minus,
        0.25 + 0.0im;
        axis="real",
    )
    @test isapprox(
        assessment.kappa,
        exact_kappa;
        rtol=8 * eps(Float64),
    )
    @test !assessment.kappa_saturated
    @test !assessment.kappa_is_infinite
end


@testset "negative real and imaginary steps preserve derivative orientation" begin
    omega = 0.25 - 0.5im
    exact = 7.0 / 3.0 - 5.0im / 4.0
    for (negative, axis) in ((-0.125 + 0.0im, "real"),
                             (0.0 - 0.125im, "imaginary"))
        derivative, assessment = build_finite_difference_diagnostics(
            linear_map(Float64, omega + negative),
            linear_map(Float64, omega - negative),
            negative;
            axis=axis,
        )
        @test isapprox(derivative, exact; rtol=16 * eps(Float64))
        @test assessment.h == abs(negative)
        @test assessment.axis == axis
    end
end


@testset "exact cancellation is an explicit kappa lower bound" begin
    _, assessment = build_finite_difference_diagnostics(
        1.0 + 2.0im,
        1.0 + 2.0im,
        0.25 + 0.0im;
        axis="real",
    )
    @test assessment.kappa == floatmax(Float64)
    @test assessment.kappa_saturated
    @test assessment.kappa_is_infinite
    @test assessment.saturation_observed
    @test assessment.saturation_status == "kappa-infinite-lower-bound/v1"

    _, zero_assessment = build_finite_difference_diagnostics(
        0.0 + 0.0im,
        0.0 + 0.0im,
        0.25 + 0.0im;
        axis="real",
    )
    @test zero_assessment.kappa_saturated
    @test !zero_assessment.kappa_is_infinite
    @test zero_assessment.kappa_is_indeterminate
    @test zero_assessment.saturation_status ==
        "kappa-indeterminate-lower-bound/v1"
end


@testset "every clamped magnitude has typed saturation evidence" begin
    huge = 0.75 * floatmax(Float64)
    derivative, assessment = build_finite_difference_diagnostics(
        complex(huge, huge),
        complex(-huge, -huge),
        1.0 + 0.0im;
        axis="real",
    )
    @test derivative == complex(huge, huge)
    @test assessment.d_plus_abs_saturated
    @test assessment.d_minus_abs_saturated
    @test assessment.difference_abs_saturated
    @test assessment.derivative_abs_saturated
    @test assessment.saturation_observed
end


@testset "axis, zero, and nonfinite inputs fail before algebra" begin
    valid_plus = 1.0 + 2.0im
    valid_minus = 0.5 + 1.0im
    @test_throws ArgumentError validate_finite_difference_inputs(
        valid_plus, valid_minus, 0.0 + 0.0im; axis="real"
    )
    @test_throws ArgumentError validate_finite_difference_inputs(
        valid_plus, valid_minus, 0.1 + 0.0im; axis="imaginary"
    )
    @test_throws ArgumentError validate_finite_difference_inputs(
        valid_plus, valid_minus, 0.0 + 0.1im; axis="real"
    )
    @test_throws ArgumentError validate_finite_difference_inputs(
        valid_plus, valid_minus, 0.1 + 0.0im; axis="diagonal"
    )
    @test_throws ArgumentError validate_finite_difference_inputs(
        valid_plus, valid_minus, complex(Inf, 0.0); axis="real"
    )
    # The composite entry point runs the same validation before any algebra.
    # The two input classes keep distinct types on purpose: a nonfinite stencil
    # value is a numerical condition and must stay a FiniteDifferenceRangeError
    # so translate_numerical_control_failure can type it as
    # ALGEBRAIC_REPRESENTATION_SINGULAR (asserted above at "nonfinite stencil
    # values are typed range failures"), while a malformed offset or axis is a
    # caller error and stays an ArgumentError.
    @test_throws ArgumentError build_finite_difference_diagnostics(
        valid_plus, valid_minus, 0.0 + 0.0im; axis="real"
    )
    @test_throws ArgumentError build_finite_difference_diagnostics(
        valid_plus, valid_minus, 0.1 + 0.0im; axis="diagonal"
    )
    @test_throws FiniteDifferenceRangeError build_finite_difference_diagnostics(
        complex(Inf, 0.0), valid_minus, 0.1 + 0.0im; axis="real"
    )
end


@testset "request frequency step is positive and finite before sampling" begin
    @test validated_frequency_step(
        Float64, finite_difference_control_request(frequency_step="1e-6")
    ) == 1.0e-6
    for invalid in ("0", "-1e-6", "Inf", "NaN")
        failure = try
            validated_frequency_step(
                Float64,
                finite_difference_control_request(frequency_step=invalid),
            )
            nothing
        catch caught
            caught
        end
        @test failure isa NumericalControlFailure
        if failure isa NumericalControlFailure
            details = failure_details(failure)
            @test details["failure_code"] ==
                "ALGEBRAIC_REPRESENTATION_SINGULAR"
            @test details["retryable"] == false
            @test details["diagnostics"]["reason"] ==
                "INVALID_FREQUENCY_STEP"
        end
    end
end


@testset "BigFloat exponent combinations fail before integer wrap" begin
    setprecision(BigFloat, 192) do
        huge = floatmax(BigFloat) / BigFloat(2)
        tiny = floatmin(BigFloat)
        failure = try
            build_finite_difference_diagnostics(
                complex(huge, zero(BigFloat)),
                complex(-huge, zero(BigFloat)),
                complex(tiny, zero(BigFloat));
                axis="real",
            )
            nothing
        catch caught
            caught
        end
        @test failure isa FiniteDifferenceRangeError
        if failure isa FiniteDifferenceRangeError
            @test failure.status == "derivative-overflow/v1"
            assert_range_translation(failure, "real", tiny)
        end
    end
end


@testset "nonzero derivative underflow fails with typed range evidence" begin
    tiny = nextfloat(0.0)
    failure = try
        build_finite_difference_diagnostics(
            complex(tiny, 0.0),
            complex(0.0, 0.0),
            complex(floatmax(Float64), 0.0);
            axis="real",
        )
        nothing
    catch caught
        caught
    end
    @test failure isa FiniteDifferenceRangeError
    if failure isa FiniteDifferenceRangeError
        @test failure.status == "derivative-underflow/v1"
        assert_range_translation(failure, "real", floatmax(Float64))
    end

    materialized, upper_clamped, underflowed = _fd_materialize_clamped(
        _FDScaledValue{Float64}(0.5, BigInt(-4096))
    )
    @test materialized == 0.0
    @test !upper_clamped
    @test underflowed
end
