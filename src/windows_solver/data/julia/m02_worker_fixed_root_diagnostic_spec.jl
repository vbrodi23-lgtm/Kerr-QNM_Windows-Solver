# Composed no-ODE fixed-root diagnostic contract.
#
# Python supplies production request documents through the PR #59 canonical
# request fixture.  This specification keeps Julia's real request flattening,
# policy validation, phase orchestration, raw determinant progress accounting,
# and exterior empirical certificate aggregation.  Only the expensive raw
# determinant calculation is replaced with a type-specialised in-memory
# determinant so no spectral context, Newton solve, coordinate map, or ODE is
# constructed.

using Test

include("m02_worker.jl")

length(ARGS) == 1 || error(
    "usage: m02_worker_fixed_root_diagnostic_spec.jl PYTHON_FIXTURE_JSON"
)

fixture = JSON.parsefile(ARGS[1])
documents = fixture["requests"]

mutable struct FixedRootSpecScenario
    raw_calls::Int
    missing_evidence_call::Union{Nothing,Int}
    extra_raw_evaluation::Bool
    raw_values::Vector{Any}
end

FixedRootSpecScenario(;
    missing_evidence_call=nothing,
    extra_raw_evaluation=false,
) = FixedRootSpecScenario(
    0, missing_evidence_call, extra_raw_evaluation, Any[]
)

mutable struct FixedRootSpecRequest <: AbstractDict{String,Any}
    data::Dict{String,Any}
    scenario::FixedRootSpecScenario
end

Base.length(request::FixedRootSpecRequest) = length(request.data)
Base.iterate(request::FixedRootSpecRequest, state...) =
    iterate(request.data, state...)
Base.getindex(request::FixedRootSpecRequest, key) = request.data[key]
Base.get(request::FixedRootSpecRequest, key, default) =
    get(request.data, key, default)
Base.setindex!(request::FixedRootSpecRequest, value, key) =
    setindex!(request.data, value, key)
Base.haskey(request::FixedRootSpecRequest, key) = haskey(request.data, key)
Base.copy(request::FixedRootSpecRequest) =
    FixedRootSpecRequest(copy(request.data), request.scenario)

function fixed_root_spec_diagnostics(
    ::Type{T}, request, value::Complex{T}
) where {T<:AbstractFloat}
    horizon = string(required(request, "mechanism_id")) ==
        "horizon-admittance"
    return DeterminantDiagnostics{T}(
        HOMOGENEOUS_REPRESENTATION_ID,
        horizon ? HORIZON_DETERMINANT_FAMILY_ID :
            EXTERIOR_DETERMINANT_FAMILY_ID,
        horizon,
        zero(T),
        zero(T),
        zero(T),
        zero(T),
        T(80),
        nothing,
        nothing,
        nothing,
        true,
        zero(T),
        horizon ? abs(value) : nothing,
        horizon ? "available/v1" : "not-applicable/v1",
        abs(value),
        nothing,
        nothing,
        zero(T),
    )
end

# This method is more specific than the production determinant method.  Raw
# progress, counter increments, tight controls, preceding precision, and
# certificate aggregation remain production code.
function determinant(
    ::Type{T},
    request::FixedRootSpecRequest,
    context::DeterminantRequestContext{T},
    omega::Complex{T},
    amplitude::Complex{T},
) where {T<:AbstractFloat}
    request.scenario.raw_calls += 1
    call = request.scenario.raw_calls
    if request.scenario.missing_evidence_call == 3 && call == 3
        error("synthetic preceding-precision evidence is unavailable")
    end
    value = complex(T(call) * T("1e-12"), zero(T))
    push!(request.scenario.raw_values, value)
    diagnostics = fixed_root_spec_diagnostics(T, request, value)
    if request.scenario.missing_evidence_call == call
        return DeterminantEvaluation{T}(value, diagnostics)
    end
    endpoint_error = T(call) * T("1e-17")
    breakdown = DeterminantErrorBreakdown{T}(
        endpoint_error,
        nothing,
        nothing,
        nothing,
        one(T),
        endpoint_error,
    )
    error_model_id = string(required(request, "mechanism_id")) ==
        "horizon-admittance" ? VERIFIED_ENDPOINT_ERROR_MODEL_ID :
        EXTERIOR_EMPIRICAL_ERROR_MODEL_ID
    return DeterminantEvaluation{T}(
        value, breakdown, error_model_id, diagnostics
    )
end

# Inject one deliberately unauthenticated fourth raw evaluation only for the
# negative contract case.  The ordinary path invokes the production method.
function determinant_progress(
    ::Type{T},
    request::FixedRootSpecRequest,
    evaluation_context::DeterminantRequestContext{T},
    omega::Complex{T},
    amplitude::Complex{T},
    purpose::String,
    current::Complex{T},
) where {T<:AbstractFloat}
    evaluation = invoke(
        determinant_progress,
        Tuple{
            Type{T},
            Any,
            DeterminantRequestContext{T},
            Complex{T},
            Complex{T},
            String,
            Complex{T},
        },
        T,
        request,
        evaluation_context,
        omega,
        amplitude,
        purpose,
        current,
    )
    if request.scenario.extra_raw_evaluation
        raw_determinant_progress(
            T,
            request,
            evaluation_context,
            omega,
            amplitude,
            "$(purpose) unexpected fourth evaluation",
            current,
        )
    end
    return evaluation
end

function production_document(mechanism::String)
    return only(filter(documents) do document
        document["mechanism_id"] == mechanism &&
            document["precision_digits"] == 80 &&
            document["refinement_level"] == 0
    end)
end

function run_fixed_root_phase(
    document,
    phase::String;
    scenario=FixedRootSpecScenario(),
)
    flattened = flatten_request(document)
    validate_regularised_gsn_policy(flattened)
    bits = parse_integer(flattened, "working_precision_bits")
    return setprecision(BigFloat, bits) do
        request = FixedRootSpecRequest(flattened, scenario)
        refinement = phase == "TRUNCATION" ? :truncation : :resolution
        phase_request = refined_request(BigFloat, request, refinement)
        omega_primary = parse_complex(
            BigFloat, phase_request, "omega_re", "omega_im"
        )
        amplitude = parse_complex(
            BigFloat, phase_request, "amplitude_re", "amplitude_im"
        )
        context = build_determinant_request_context(
            BigFloat, phase_request, omega_primary
        )
        result = solve_phase(
            BigFloat,
            phase_request,
            context,
            phase,
            omega_primary,
            amplitude;
            seed_kind="ACCEPTED_PRIMARY",
            solve_role=FIXED_ROOT_DIAGNOSTIC,
            authenticated_primary_root=omega_primary,
            primary_derivative=complex(one(BigFloat), zero(BigFloat)),
        )
        expected_cross_precision_disagreement = if length(
            scenario.raw_values
        ) >= 3
            cross = scenario.raw_values[3]
            cross_value = Complex{BigFloat}(
                BigFloat(real(cross)), BigFloat(imag(cross))
            )
            abs(scenario.raw_values[1] - cross_value)
        else
            nothing
        end
        return (
            result,
            scenario,
            omega_primary,
            expected_cross_precision_disagreement,
        )
    end
end

@testset "promoted exterior fixed-root phases return one logical authenticated determinant" begin
    exterior = production_document("exterior-light-ring")
    for phase in ("TRUNCATION", "RESOLUTION")
        result, scenario, omega_primary, expected_cross =
            run_fixed_root_phase(exterior, phase)
        @test result.root_phase == phase
        @test result.fixed_root
        @test result.logical_authenticated_determinant_count == 1
        @test result.determinant_count == 1
        @test result.raw_determinant_evaluation_count == 3
        @test scenario.raw_calls == 3
        breakdown = result.root_evaluation.error_breakdown
        @test breakdown !== nothing
        @test isapprox(
            breakdown.endpoint_disagreement_abs,
            BigFloat("2e-17");
            rtol=BigFloat("1e-70"),
        )
        @test isapprox(
            breakdown.control_disagreement_abs,
            BigFloat("1e-12");
            rtol=BigFloat("1e-70"),
        )
        @test expected_cross !== nothing
        @test breakdown.precision_disagreement_abs == expected_cross
        @test breakdown.safety_factor == BigFloat(64)
        @test result.root_evaluation.error_model_id ==
            EXTERIOR_EMPIRICAL_ERROR_MODEL_ID
        @test result.root == omega_primary
    end
end

@testset "horizon fixed-root phase keeps its one-raw one-logical contract" begin
    horizon = production_document("horizon-admittance")
    result, scenario, omega_primary, expected_cross =
        run_fixed_root_phase(horizon, "TRUNCATION")
    @test result.logical_authenticated_determinant_count == 1
    @test result.determinant_count == 1
    @test result.raw_determinant_evaluation_count == 1
    @test scenario.raw_calls == 1
    @test result.root == omega_primary
    @test expected_cross === nothing
end


@testset "missing exterior certificate evidence fails closed" begin
    exterior = production_document("exterior-light-ring")
    for missing_call in (1, 2, 3)
        scenario = FixedRootSpecScenario(
            missing_evidence_call=missing_call
        )
        failure = try
            run_fixed_root_phase(
                exterior, "TRUNCATION"; scenario=scenario
            )
            nothing
        catch caught
            caught
        end
        @test failure isa NumericalControlFailure
        @test failure_details(failure)["failure_code"] ==
            EXTERIOR_EMPIRICAL_ERROR_MISSING_OUTCOME
        @test scenario.raw_calls == missing_call
    end
end

@testset "an unexpected fourth raw evaluation fails closed" begin
    exterior = production_document("exterior-light-ring")
    scenario = FixedRootSpecScenario(extra_raw_evaluation=true)
    failure = try
        run_fixed_root_phase(
            exterior, "RESOLUTION"; scenario=scenario
        )
        nothing
    catch caught
        caught
    end
    @test failure isa ErrorException
    @test occursin(
        "required determinant evaluations", sprint(showerror, failure)
    )
    @test scenario.raw_calls == 4
end
