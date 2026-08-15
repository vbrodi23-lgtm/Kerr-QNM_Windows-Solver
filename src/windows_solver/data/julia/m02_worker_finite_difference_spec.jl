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
    @test all(step -> minimum_step <= step <= maximum_step, rungs)
    @test length(rungs) == length(unique(rungs))
    @test length(rungs) <= MAXIMUM_FREQUENCY_STEP_RUNGS
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
    @test_throws ArgumentError build_finite_difference_diagnostics(
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
