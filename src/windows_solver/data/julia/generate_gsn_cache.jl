#!/usr/bin/env julia

# Canonical Stage 1: derive the spin-minus-two GSN infinity-series cache by
# executing the vendored Julia sF/sU equations over an exact symbolic rational
# function type.  No Python generator and no stored cache are consulted.

using SHA
using Printf

function bootstrap_argument_value(flag::String)
    index = findfirst(==(flag), ARGS)
    index === nothing && error("missing argument $flag")
    index == length(ARGS) && error("missing value for $flag")
    return ARGS[index + 1]
end

const GSN_SOURCE_ROOT = abspath(bootstrap_argument_value("--gsn-source-root"))

module ReferenceSpinMinusTwoGSN
include(joinpath(
    Main.GSN_SOURCE_ROOT,
    "src", "Homogeneous", "Kerr.jl",
))
module Transformation end
include(joinpath(
    Main.GSN_SOURCE_ROOT,
    "src", "Homogeneous", "Potentials.jl",
))
end

module ExactSeriesAlgebra

export URat, omega_symbol, lambda_symbol, inverse_radius_symbol,
       coefficient_lists, evaluate_urat

const Q = Rational{BigInt}
const GQ = Complex{Q}
const BKey = Tuple{Int,Int}

_q(x::Integer) = Q(BigInt(x), BigInt(1))
_q(x::Rational) = Q(BigInt(numerator(x)), BigInt(denominator(x)))

function _gq(x::Real)
    x isa Integer && return GQ(_q(x), _q(0))
    x isa Rational && return GQ(_q(x), _q(0))
    throw(ArgumentError("symbolic algebra accepts exact real numbers only: $(typeof(x))"))
end

function _gq(x::Complex)
    return GQ(_q(real(x)), _q(imag(x)))
end

struct BivarPoly
    terms::Dict{BKey,GQ}
    function BivarPoly(terms::Dict{BKey,GQ})
        cleaned = Dict{BKey,GQ}()
        for (key, value) in terms
            iszero(value) || (cleaned[key] = value)
        end
        new(cleaned)
    end
end

BivarPoly(x::Number) = BivarPoly(
    iszero(x) ? Dict{BKey,GQ}() : Dict{BKey,GQ}((0, 0) => _gq(x))
)

Base.zero(::Type{BivarPoly}) = BivarPoly(0)
Base.one(::Type{BivarPoly}) = BivarPoly(1)
Base.iszero(value::BivarPoly) = isempty(value.terms)
Base.:(==)(first::BivarPoly, second::BivarPoly) = first.terms == second.terms

function Base.:+(first::BivarPoly, second::BivarPoly)
    terms = copy(first.terms)
    for (key, value) in second.terms
        terms[key] = get(terms, key, GQ(_q(0), _q(0))) + value
    end
    return BivarPoly(terms)
end
Base.:-(value::BivarPoly) = BivarPoly(Dict(key => -item for (key, item) in value.terms))
Base.:-(first::BivarPoly, second::BivarPoly) = first + (-second)

function Base.:*(first::BivarPoly, second::BivarPoly)
    iszero(first) && return zero(BivarPoly)
    iszero(second) && return zero(BivarPoly)
    terms = Dict{BKey,GQ}()
    for ((omega_first, lambda_first), coefficient_first) in first.terms
        for ((omega_second, lambda_second), coefficient_second) in second.terms
            key = (omega_first + omega_second, lambda_first + lambda_second)
            terms[key] = get(terms, key, GQ(_q(0), _q(0))) +
                         coefficient_first * coefficient_second
        end
    end
    return BivarPoly(terms)
end

function Base.:^(value::BivarPoly, exponent::Integer)
    exponent < 0 && throw(ArgumentError("negative bivariate polynomial exponent"))
    result = one(BivarPoly)
    factor = value
    power = Int(exponent)
    while power > 0
        isodd(power) && (result = result * factor)
        power >>= 1
        power > 0 && (factor = factor * factor)
    end
    return result
end

struct LaurentPoly
    terms::Dict{Int,BivarPoly}
    function LaurentPoly(terms::Dict{Int,BivarPoly})
        cleaned = Dict{Int,BivarPoly}()
        for (power, coefficient) in terms
            iszero(coefficient) || (cleaned[power] = coefficient)
        end
        new(cleaned)
    end
end

LaurentPoly(x::Number) = LaurentPoly(
    iszero(x) ? Dict{Int,BivarPoly}() : Dict{Int,BivarPoly}(0 => BivarPoly(x))
)
LaurentPoly(value::BivarPoly) = LaurentPoly(
    iszero(value) ? Dict{Int,BivarPoly}() : Dict{Int,BivarPoly}(0 => value)
)

Base.zero(::Type{LaurentPoly}) = LaurentPoly(0)
Base.one(::Type{LaurentPoly}) = LaurentPoly(1)
Base.iszero(value::LaurentPoly) = isempty(value.terms)
Base.:(==)(first::LaurentPoly, second::LaurentPoly) = first.terms == second.terms

function Base.:+(first::LaurentPoly, second::LaurentPoly)
    terms = copy(first.terms)
    for (power, coefficient) in second.terms
        terms[power] = get(terms, power, zero(BivarPoly)) + coefficient
    end
    return LaurentPoly(terms)
end
Base.:-(value::LaurentPoly) = LaurentPoly(Dict(power => -item for (power, item) in value.terms))
Base.:-(first::LaurentPoly, second::LaurentPoly) = first + (-second)

function Base.:*(first::LaurentPoly, second::LaurentPoly)
    iszero(first) && return zero(LaurentPoly)
    iszero(second) && return zero(LaurentPoly)
    terms = Dict{Int,BivarPoly}()
    for (power_first, coefficient_first) in first.terms
        for (power_second, coefficient_second) in second.terms
            power = power_first + power_second
            terms[power] = get(terms, power, zero(BivarPoly)) +
                           coefficient_first * coefficient_second
        end
    end
    return LaurentPoly(terms)
end

function Base.:^(value::LaurentPoly, exponent::Integer)
    exponent < 0 && throw(ArgumentError("negative Laurent polynomial exponent"))
    result = one(LaurentPoly)
    factor = value
    power = Int(exponent)
    while power > 0
        isodd(power) && (result = result * factor)
        power >>= 1
        power > 0 && (factor = factor * factor)
    end
    return result
end

struct URat
    numerator::LaurentPoly
    denominator::LaurentPoly
    function URat(numerator::LaurentPoly, denominator::LaurentPoly)
        iszero(denominator) && throw(DivideError())
        new(numerator, denominator)
    end
end

URat(x::Number) = URat(LaurentPoly(x), LaurentPoly(1))
URat(value::BivarPoly) = URat(LaurentPoly(value), LaurentPoly(1))
URat(value::LaurentPoly) = URat(value, LaurentPoly(1))

Base.zero(::Type{URat}) = URat(0)
Base.one(::Type{URat}) = URat(1)
Base.iszero(value::URat) = iszero(value.numerator)
Base.:(==)(first::URat, second::URat) =
    first.numerator * second.denominator == second.numerator * first.denominator

function Base.:+(first::URat, second::URat)
    if first.denominator == second.denominator
        return URat(first.numerator + second.numerator, first.denominator)
    end
    return URat(
        first.numerator * second.denominator + second.numerator * first.denominator,
        first.denominator * second.denominator,
    )
end
Base.:-(value::URat) = URat(-value.numerator, value.denominator)
Base.:-(first::URat, second::URat) = first + (-second)
Base.:*(first::URat, second::URat) = URat(
    first.numerator * second.numerator,
    first.denominator * second.denominator,
)
Base.:/(first::URat, second::URat) = URat(
    first.numerator * second.denominator,
    first.denominator * second.numerator,
)
Base.inv(value::URat) = URat(value.denominator, value.numerator)

Base.:+(first::URat, second::Number) = first + URat(second)
Base.:+(first::Number, second::URat) = URat(first) + second
Base.:-(first::URat, second::Number) = first - URat(second)
Base.:-(first::Number, second::URat) = URat(first) - second
Base.:*(first::URat, second::Number) = first * URat(second)
Base.:*(first::Number, second::URat) = URat(first) * second
Base.:/(first::URat, second::Number) = first / URat(second)
Base.:/(first::Number, second::URat) = URat(first) / second

function Base.:^(value::URat, exponent::Integer)
    if exponent == 0
        return one(URat)
    elseif exponent > 0
        return URat(value.numerator^exponent, value.denominator^exponent)
    else
        positive = -Int(exponent)
        return URat(value.denominator^positive, value.numerator^positive)
    end
end

function omega_symbol()
    return URat(BivarPoly(Dict{BKey,GQ}((1, 0) => GQ(_q(1), _q(0)))))
end

function lambda_symbol()
    return URat(BivarPoly(Dict{BKey,GQ}((0, 1) => GQ(_q(1), _q(0)))))
end

function inverse_radius_symbol()
    u = LaurentPoly(Dict{Int,BivarPoly}(1 => BivarPoly(1)))
    return URat(u)
end

function _shift(value::LaurentPoly, amount::Int)
    return LaurentPoly(Dict(power + amount => coefficient for (power, coefficient) in value.terms))
end

function _minimum_power(value::LaurentPoly)
    return isempty(value.terms) ? 0 : minimum(keys(value.terms))
end

function _maximum_power(value::LaurentPoly)
    return isempty(value.terms) ? 0 : maximum(keys(value.terms))
end

function _rational_python(value::Q)
    denominator(value) == 1 && return string(numerator(value))
    return "(" * string(numerator(value)) * "/" * string(denominator(value)) * ")"
end

function _gaussian_python(value::GQ)
    real_part = real(value)
    imaginary_part = imag(value)
    if iszero(imaginary_part)
        return _rational_python(real_part)
    elseif iszero(real_part)
        return "(" * _rational_python(imaginary_part) * "*1j)"
    end
    return "(" * _rational_python(real_part) * "+(" *
           _rational_python(imaginary_part) * "*1j))"
end

function _bivariate_python(value::BivarPoly)
    isempty(value.terms) && return "0"
    rendered = String[]
    for ((omega_power, lambda_power), coefficient) in sort(
        collect(value.terms);
        by=item -> (item[1][1], item[1][2]),
    )
        factors = String[_gaussian_python(coefficient)]
        omega_power > 0 && push!(factors, "(omega**$(omega_power))")
        lambda_power > 0 && push!(factors, "(lam**$(lambda_power))")
        push!(rendered, "(" * join(factors, "*") * ")")
    end
    return "(" * join(rendered, "+") * ")"
end

function _coefficient_vector(value::LaurentPoly)
    maximum_power = _maximum_power(value)
    maximum_power < 0 && throw(ArgumentError("negative terminal Laurent power"))
    return [
        _bivariate_python(get(value.terms, power, zero(BivarPoly)))
        for power in 0:maximum_power
    ]
end

function coefficient_lists(value::URat)
    minimum_power = min(
        _minimum_power(value.numerator),
        _minimum_power(value.denominator),
    )
    shift = minimum_power < 0 ? -minimum_power : 0
    numerator = _shift(value.numerator, shift)
    denominator = _shift(value.denominator, shift)
    numerator_values = iszero(numerator) ? ["0"] : _coefficient_vector(numerator)
    denominator_values = _coefficient_vector(denominator)
    return numerator_values, denominator_values
end

function _evaluate(value::BivarPoly, omega::ComplexF64, lambda::ComplexF64)
    total = 0.0 + 0.0im
    for ((omega_power, lambda_power), coefficient) in value.terms
        total += ComplexF64(Float64(real(coefficient)), Float64(imag(coefficient))) *
                 omega^omega_power * lambda^lambda_power
    end
    return total
end

function _evaluate(value::LaurentPoly, omega::ComplexF64, lambda::ComplexF64, u::ComplexF64)
    total = 0.0 + 0.0im
    for (power, coefficient) in value.terms
        total += _evaluate(coefficient, omega, lambda) * u^power
    end
    return total
end

function _evaluate_shifted(
    value::LaurentPoly,
    omega::ComplexF64,
    lambda::ComplexF64,
    u::ComplexF64,
    common_minimum_power::Int,
)
    total = 0.0 + 0.0im
    for (power, coefficient) in value.terms
        total += _evaluate(coefficient, omega, lambda) *
                 u^(power - common_minimum_power)
    end
    return total
end

function evaluate_urat(value::URat, omega::ComplexF64, lambda::ComplexF64, u::ComplexF64)
    # The unsimplified exact rational expression can carry a large common
    # Laurent factor (for the Schwarzschild U expression it reaches u^235).
    # Remove that shared power before Float64 validation so numerator and
    # denominator cannot underflow independently even though their ratio is
    # regular.
    common_minimum_power = min(
        _minimum_power(value.numerator),
        _minimum_power(value.denominator),
    )
    numerator = _evaluate_shifted(
        value.numerator, omega, lambda, u, common_minimum_power,
    )
    denominator = _evaluate_shifted(
        value.denominator, omega, lambda, u, common_minimum_power,
    )
    return numerator / denominator
end

end

using .ExactSeriesAlgebra

const Q = Rational{BigInt}

function declared_pairs()
    pairs_path = abspath(argument_value("--pairs-file"))
    isfile(pairs_path) || error("parameter-pairs file is absent: $pairs_path")
    pairs = Tuple{Q,Int}[]
    seen = Set{Tuple{Q,Int}}()
    for (line_number, line) in enumerate(eachline(pairs_path))
        isempty(strip(line)) && continue
        fields = split(strip(line), ',')
        length(fields) == 3 || error(
            "parameter-pairs line $line_number must have three fields"
        )
        numerator = parse(BigInt, fields[1])
        denominator = parse(BigInt, fields[2])
        denominator > 0 || error(
            "parameter-pairs line $line_number has a nonpositive denominator"
        )
        spin = Q(numerator, denominator)
        -1 <= spin <= 1 || error(
            "parameter-pairs line $line_number has spin outside [-1, 1]"
        )
        pair = (spin, parse(Int, fields[3]))
        pair in seen && error("parameter-pairs file contains duplicate pair $pair")
        push!(pairs, pair)
        push!(seen, pair)
    end
    isempty(pairs) && error("parameter-pairs file is empty")
    return pairs
end

const VALIDATION_POINTS = (
    (7.25, 0.40 - 0.08im, 4.10 + 0.03im),
    (12.50, 0.70 - 0.12im, 10.20 - 0.04im),
    (30.00, 1.10 - 0.20im, 18.00 + 0.05im),
)
const VALIDATION_TOLERANCE = 1.0e-12

function argument_value(flag::String)
    index = findfirst(==(flag), ARGS)
    index === nothing && error("missing argument $flag")
    index == length(ARGS) && error("missing value for $flag")
    return ARGS[index + 1]
end

function json_escape(value::AbstractString)
    io = IOBuffer()
    for character in value
        if character == '"'
            print(io, "\\\"")
        elseif character == '\\'
            print(io, "\\\\")
        elseif character == '\n'
            print(io, "\\n")
        elseif character == '\r'
            print(io, "\\r")
        elseif character == '\t'
            print(io, "\\t")
        elseif Int(character) < 0x20
            @printf(io, "\\u%04x", Int(character))
        else
            print(io, character)
        end
    end
    return String(take!(io))
end

function write_json(io::IO, value)
    if value === nothing
        print(io, "null")
    elseif value isa Bool
        print(io, value ? "true" : "false")
    elseif value isa Integer
        print(io, value)
    elseif value isa AbstractFloat
        isfinite(value) || error("nonfinite JSON number")
        @printf(io, "%.17g", value)
    elseif value isa AbstractString
        print(io, '"', json_escape(value), '"')
    elseif value isa AbstractVector || value isa Tuple
        print(io, '[')
        for (index, item) in enumerate(value)
            index > 1 && print(io, ',')
            write_json(io, item)
        end
        print(io, ']')
    elseif value isa AbstractDict
        print(io, '{')
        ordered_keys = sort(collect(keys(value)); by=string)
        for (index, key) in enumerate(ordered_keys)
            index > 1 && print(io, ',')
            write_json(io, string(key))
            print(io, ':')
            write_json(io, value[key])
        end
        print(io, '}')
    else
        error("unsupported JSON value $(typeof(value))")
    end
end

function write_json_file(path::String, value)
    mkpath(dirname(path))
    open(path, "w") do io
        write_json(io, value)
        write(io, '\n')
    end
end

function append_json_line(path::String, value)
    mkpath(dirname(path))
    open(path, "a") do io
        write_json(io, value)
        write(io, '\n')
        flush(io)
    end
end

function finite_complex(value)
    return isfinite(real(value)) && isfinite(imag(value))
end

function scaled_error(first, second)
    return abs(first - second) / max(1.0, abs(first), abs(second))
end

function pair_key(spin::Q, m::Int)
    return "m=$(m);a=$(@sprintf("%.15g", Float64(spin)))"
end

function build_record(spin::Q, m::Int)
    u = inverse_radius_symbol()
    r = u^-1
    omega = omega_symbol()
    lambda = lambda_symbol()
    exact_spin = URat(spin)
    coefficient_f = ReferenceSpinMinusTwoGSN.Potentials.sF(
        -2, m, exact_spin, omega, lambda, r,
    )
    coefficient_u = ReferenceSpinMinusTwoGSN.Potentials.sU(
        -2, m, exact_spin, omega, lambda, r,
    )
    f_num, f_den = coefficient_lists(coefficient_f)
    u_num, u_den = coefficient_lists(coefficient_u)
    record = Dict{String,Any}(
        "F" => Dict{String,Any}(
            "numerator_coefficients_ascending" => f_num,
            "denominator_coefficients_ascending" => f_den,
        ),
        "U" => Dict{String,Any}(
            "numerator_coefficients_ascending" => u_num,
            "denominator_coefficients_ascending" => u_den,
        ),
    )
    maximum_error = 0.0
    for (radius, omega_value, lambda_value) in VALIDATION_POINTS
        generated_f = evaluate_urat(
            coefficient_f,
            ComplexF64(omega_value),
            ComplexF64(lambda_value),
            ComplexF64(1.0 / radius),
        )
        generated_u = evaluate_urat(
            coefficient_u,
            ComplexF64(omega_value),
            ComplexF64(lambda_value),
            ComplexF64(1.0 / radius),
        )
        direct_f = ComplexF64(ReferenceSpinMinusTwoGSN.Potentials.sF(
            -2, m, Float64(spin), ComplexF64(omega_value),
            ComplexF64(lambda_value), radius,
        ))
        direct_u = ComplexF64(ReferenceSpinMinusTwoGSN.Potentials.sU(
            -2, m, Float64(spin), ComplexF64(omega_value),
            ComplexF64(lambda_value), radius,
        ))
        all(finite_complex, (generated_f, generated_u, direct_f, direct_u)) ||
            error("nonfinite Stage-1 validation value")
        maximum_error = max(
            maximum_error,
            scaled_error(generated_f, direct_f),
            scaled_error(generated_u, direct_u),
        )
    end
    return record, maximum_error
end

function write_status(path::String; status_code::Int, expected_count::Int,
                      generated_count::Int,
                      validation_count::Int, maximum_error::Float64,
                      all_accepted::Bool)
    mkpath(dirname(path))
    open(path, "w") do io
        println(io, join((
            "status_code",
            "expected_parameter_pair_count",
            "computed_parameter_pair_count",
            "accepted_parameter_pair_count",
            "rejected_parameter_pair_count",
            "expected_validation_sample_count",
            "computed_validation_sample_count",
            "accepted_validation_sample_count",
            "rejected_validation_sample_count",
            "source_equations_executed",
            "exact_symbolic_algebra_used",
            "maximum_scaled_validation_error_finite",
            "validation_tolerance_satisfied",
            "all_accepted",
        ), ','))
        accepted_count = all_accepted ? generated_count : 0
        accepted_validation = all_accepted ? validation_count : 0
        println(io, join((
            status_code,
            expected_count,
            generated_count,
            accepted_count,
            generated_count - accepted_count,
            expected_count * 2 * length(VALIDATION_POINTS),
            validation_count,
            accepted_validation,
            validation_count - accepted_validation,
            true,
            true,
            isfinite(maximum_error),
            maximum_error <= VALIDATION_TOLERANCE,
            all_accepted,
        ), ','))
    end
end

function main()
    output_cache = abspath(argument_value("--output-cache"))
    status_output = abspath(argument_value("--status-output"))
    journal_output = abspath(argument_value("--journal-output"))
    source_path = normpath(joinpath(
        GSN_SOURCE_ROOT,
        "src", "Homogeneous", "Potentials.jl",
    ))
    mkpath(dirname(journal_output))
    open(journal_output, "w") do io
        flush(io)
    end
    records = Dict{String,Any}()
    declared = Any[]
    maximum_error = 0.0
    generated_count = 0
    validation_count = 0
    pairs = Tuple{Q,Int}[]
    expected_count = 0
    try
        pairs = declared_pairs()
        expected_count = length(pairs)
        for (spin, m) in pairs
            key = pair_key(spin, m)
            record, error_value = build_record(spin, m)
            records[key] = record
            push!(declared, Dict{String,Any}(
                "spin" => Float64(spin),
                "azimuthal_index" => m,
            ))
            maximum_error = max(maximum_error, error_value)
            generated_count += 1
            validation_count += 2 * length(VALIDATION_POINTS)
            append_json_line(journal_output, Dict{String,Any}(
                "schema_version" => 1,
                "event" => "parameter_pair_completed",
                "completion_index" => generated_count,
                "declared_parameter_pair_count" => expected_count,
                "pair_key" => key,
                "spin" => Float64(spin),
                "spin_numerator" => numerator(spin),
                "spin_denominator" => denominator(spin),
                "azimuthal_index" => m,
                "validation_sample_count" => 2 * length(VALIDATION_POINTS),
                "maximum_scaled_validation_error" => error_value,
                "validation_accepted" => (
                    isfinite(error_value) &&
                    error_value <= VALIDATION_TOLERANCE
                ),
                "record" => record,
            ))
        end
        accepted = generated_count == expected_count &&
                   validation_count == expected_count * 2 * length(VALIDATION_POINTS) &&
                   isfinite(maximum_error) &&
                   maximum_error <= VALIDATION_TOLERANCE
        document = Dict{String,Any}(
            "schema_version" => 1,
            "spin_weight" => -2,
            "mass_normalization" => 1,
            "source_relative_path" => "src/Homogeneous/Potentials.jl",
            "source_sha256" => bytes2hex(sha256(read(source_path))),
            "declared_parameter_pairs" => declared,
            "records" => records,
        )
        write_json_file(output_cache, document)
        write_status(
            status_output;
            status_code=accepted ? 0 : 31,
            expected_count=expected_count,
            generated_count=generated_count,
            validation_count=validation_count,
            maximum_error=maximum_error,
            all_accepted=accepted,
        )
        return accepted ? 0 : 31
    catch failure
        @error "canonical Stage 1 failed" exception=(failure, catch_backtrace())
        write_status(
            status_output;
            status_code=21,
            expected_count=expected_count,
            generated_count=generated_count,
            validation_count=validation_count,
            maximum_error=maximum_error,
            all_accepted=false,
        )
        return 21
    end
end

exit(main())
