module ComplexFrequencies

using ..Kerr
using ..Coordinates: r_from_rstar, contour_half_plane_sign
using ..Coordinates: rstar_from_r
using ..Coordinates:
    GSNBranchConvention,
    GSNBranchCell,
    gsn_branch_convention,
    branch_cell,
    assert_no_branch_crossing,
    infinity_contour_tangent,
    horizon_contour_tangent,
    contour_angle_deformation
using ..FactoredSolutions
using ..Potentials
using ..AsymptoticExpansionCoefficients
using ..InitialConditions
import ..Solutions

using DifferentialEquations
using StaticArrays

_DEFAULTDATATYPE = Solutions._DEFAULTDATATYPE
_DEFAULTSOLVER = Solutions._DEFAULTSOLVER
_DEFAULTTOLERANCE = Solutions._DEFAULTTOLERANCE

export ContourAngleDeformation, HomogeneousSpectralContext
export ComplexContourContext, ContourContext
export FactoredPropagationFailureReason, FactoredPropagationError
export FactoredEndpointPreparation
export HorizonDeterminantPreparation, ExteriorDeterminantPreparation
export FactoredGSNParameters, FactoredODEDiagnostics, FactoredODESolution
export FactoredCarrierTransition, FactoredScatteringPropagation
export FactoredExteriorMatches, FactoredMatchState
export HOMOGENEOUS_REPRESENTATION_ID
export FACTORED_HOMOGENEOUS_ODE_SCOPE_ID
export MATCH_RADIAL_DERIVATIVE_CONVENTION_ID
export build_homogeneous_spectral_context, build_contour_context
export prepare_factored_infinity_outgoing
export prepare_factored_horizon_ingoing, prepare_factored_horizon_outgoing
export prepare_factored_horizon_determinant_branches
export prepare_factored_exterior_determinant_branches
export assert_factored_preflights_adequate
export assert_factored_exterior_preparations_ready
export factored_GSN_linear_eqn!, solve_factored_endpoint
export solve_factored_infinity_outer_to_match
export change_factored_infinity_to_horizon_at_match
export solve_factored_horizon_match_to_inner
export solve_factored_xup_scattering_endpoint
export solve_factored_xin_to_match, solve_factored_xup_to_match
export solve_factored_exterior_matches, reconstruct_factored_match_state
export RealInnerHorizonContour
export HorizonEndpointGeometryCandidate, HorizonEndpointCandidate
export RealInnerHorizonEndpoint, VerifiedHorizonEndpoints
export VerifiedHorizonBasisSolution
export REAL_INNER_HORIZON_CONTOUR_ID
export DEFAULT_HORIZON_ENDPOINT_CANDIDATES
export DEFAULT_MAXIMUM_HORIZON_DISTANCE
export build_outer_contour_context, build_real_inner_horizon_contour
export horizon_endpoint_geometry_candidates
export horizon_endpoint_candidates, select_verified_horizon_endpoints
export select_horizon_endpoint_best_prefix
export horizon_endpoint_prefix_orders
export recover_verified_horizon_endpoint_pair
export SingleEndpointRecoveryCandidate, SingleEndpointRecovery
export recover_single_factored_endpoint, aggregate_endpoint_limitations
export canonical_single_endpoint_recovery_evidence
export verified_horizon_endpoints_from_recovery
export canonical_horizon_endpoint_search_evidence
export NO_GEOMETRY_VALID_CANDIDATE, MAX_SERIES_ORDER_INADEQUATE
export ARITHMETIC_PRECISION_INADEQUATE, COORDINATE_INVERSION_FAILURE
export FEWER_THAN_TWO_VERIFIED_ENDPOINTS
export prepare_real_inner_horizon_endpoint
export solve_factored_horizon_branch_to_match
export solve_verified_horizon_basis_to_match

function _begin_ode_observation(factory, leg, tspan, odealgo)
    factory === nothing && return nothing, nothing
    return factory(leg, tspan, odealgo)
end

function _finish_ode_observation(ode_solution_observer, leg, solution, observation)
    ode_solution_observer === nothing ||
        ode_solution_observer(leg, solution, observation)
    return solution
end

determine_sign(x) = contour_half_plane_sign(x)

function drdrho(u, p, rho)
    #=
    u[1] = r
    du[1] = dr/drho = exp(i\beta) \Delta/(r^2 + a^2)

    p should be a named tuple with the following fields: (a, beta)

    NOTE This is an autonomous equation, so the RHS does not depend on rho
    =#
    return SA[p.sign*exp(1im*p.beta) * Delta(p.a, u[1]) / (u[1]^2 + p.a^2)]
end

function solve_r_from_rho(
    a, beta, rs_mp, rho_end; verbose=true, sign=1,
    dtype=_DEFAULTDATATYPE, odealgo=_DEFAULTSOLVER,
    reltol=_DEFAULTTOLERANCE, abstol=_DEFAULTTOLERANCE,
    ode_maxiters=10^7,
    ode_observation_factory=nothing, ode_solution_observer=nothing,
    ode_leg="r_from_rho",
    r_at_rho_zero=nothing,
)
    # Keep the exact coordinate origin with the integrator so an observation
    # callback can authenticate r_*(rho) even when it aborts before a solution
    # object exists.
    p = (a=a, beta=beta, sign=sign, rs_mp=rs_mp)
    # Initial condition at rho = 0.
    #
    # By construction r_*(0) = rs_mp, so r(0) is the radius whose tortoise
    # coordinate is rs_mp. When the caller already holds that radius — the
    # production path always does, because rs_mp was built as
    # rstar_from_r(a, match_radius) — passing it directly avoids a numerical
    # inverse round trip that can only lose accuracy. The fallback keeps the
    # historical behaviour for callers that supply rs_mp alone.
    r0 = r_at_rho_zero === nothing ?
        r_from_rstar(a, rs_mp) : r_at_rho_zero
    u0 = SA[dtype(r0)]

    rhospan = (0, rho_end)
    odeprob = ODEProblem(drdrho, u0, rhospan, p)
    observation_callback, observation = _begin_ode_observation(
        ode_observation_factory, ode_leg, rhospan, odealgo
    )
    solve_arguments = observation_callback === nothing ?
        NamedTuple() : (; callback=observation_callback)
    odesoln = solve(
        odeprob, odealgo;
        maxiters=ode_maxiters, reltol=reltol, abstol=abstol,
        verbose=verbose, solve_arguments...
    )
    _finish_ode_observation(ode_solution_observer, ode_leg, odesoln, observation)

    r_from_rho(rho) = odesoln(rho)[1] # Flatten the output
    return r_from_rho
end

# Power of multiple dispatch
function solve_r_from_rho(
    a, beta_neg, beta_pos,
    rs_mp, rho_neg_end, rho_pos_end;
    sign_neg=1, sign_pos=1, verbose=true,
    dtype=_DEFAULTDATATYPE, odealgo=_DEFAULTSOLVER,
    reltol=_DEFAULTTOLERANCE, abstol=_DEFAULTTOLERANCE,
    ode_maxiters=10^7,
    ode_observation_factory=nothing, ode_solution_observer=nothing,
    r_at_rho_zero=nothing,
)
    # Obtain r_from_rho for positive rho
    r_from_rhopos = solve_r_from_rho(
        a, beta_pos, rs_mp, rho_pos_end; sign=sign_pos,
        dtype=dtype, odealgo=odealgo, verbose=verbose,
        reltol=reltol, abstol=abstol,
        ode_maxiters=ode_maxiters,
        ode_observation_factory=ode_observation_factory,
        ode_solution_observer=ode_solution_observer,
        ode_leg="r_from_rho_positive",
        r_at_rho_zero=r_at_rho_zero,
    )

    # Obtain r_from_rho for negative rho
    r_from_rhoneg = solve_r_from_rho(
        a, beta_neg, rs_mp, rho_neg_end; sign=sign_neg,
        dtype=dtype, odealgo=odealgo, verbose=verbose,
        reltol=reltol, abstol=abstol,
        ode_maxiters=ode_maxiters,
        ode_observation_factory=ode_observation_factory,
        ode_solution_observer=ode_solution_observer,
        ode_leg="r_from_rho_negative",
        r_at_rho_zero=r_at_rho_zero,
    )

    # Stitch together the two solutions
    r_from_rho(rho) = rho >= 0 ? rho <= rho_pos_end ? r_from_rhopos(rho) : NaN : rho >= rho_neg_end ? r_from_rhoneg(rho) : NaN
    return r_from_rho
end

function solve_r_from_rho(
    s, m, a, omega, lambda,
    beta_neg, beta_pos,
    rho_neg_end, rho_pos_end;
    sign_neg=1, sign_pos=1,
    dtype=_DEFAULTDATATYPE, odealgo=_DEFAULTSOLVER,
    reltol=_DEFAULTTOLERANCE, abstol=_DEFAULTTOLERANCE,
    ode_maxiters=10^7
)
    # Some helper functions
    p = omega - m*omega_horizon(a)

    solve_r_from_rho_rsmp(rsmp) = solve_r_from_rho(
        a, beta_neg, beta_pos, rsmp, rho_neg_end, rho_pos_end;
        sign_neg=sign_neg, sign_pos=sign_pos,
        dtype=dtype, odealgo=odealgo,
        reltol=reltol, abstol=abstol,
        ode_maxiters=ode_maxiters, verbose=false
    )

    function check_potential_behaviors(u)
        #=
        This function solves for r(\rho) and then checks if the asymptotic behavior of
        sF and sU in the limit \rho \to \pm \infty are satisfied.

        We want
            sF \to 0 as \rho \to \pm \infty
            sU \to -ω^2 as \rho \to \infty, and sU -> -p^2 as \rho \to -\infty

        We also check for thhe behavior of sU in the "interaction" region, where
        for numerical stability we do not want a sharp change in the potential.
        =#
        # Solve for r(ρ)
        sol = solve_r_from_rho_rsmp(u)

        # Get the asymptotic behavior of sF and sU as \rho \to \infty
        sF_rhoout = sF(s, m, a, omega, lambda, sol(rho_pos_end))
        sU_rhoout = sU(s, m, a, omega, lambda, sol(rho_pos_end)) + omega^2
        
        # Get the asymptotic behavior of sF and sU as \rho \to -\infty
        # NOTE Since r approaches r_+ counterclockwise in the complex r plane,
        # we check the "average" behavior for convergence
        rhos = rho_neg_end:1:rho_neg_end + abs(rho_neg_end)/10
        sF_rhoin = sum(sF.(s, m, a, omega, lambda, sol.(rhos)))/length(rhos)
        sU_rhoin = sum(sU.(s, m, a, omega, lambda, sol.(rhos)))/length(rhos) + p^2

        _int_region_min = -50
        _int_region_max = 50
        _h = 0.01 # For finite differencing
        int_rhos = _int_region_min:_h:_int_region_max
        _sU(x) = sU(s, m, a, omega, lambda, sol(x))
        int_sUs = _sU.(int_rhos)
        dUdx = diff(int_sUs)./_h

        _dUdx_max = 10
        if maximum(real.(dUdx)) > _dUdx_max || maximum(imag.(dUdx)) > _dUdx_max
            return NaN
        end

        return abs(sF_rhoout^2 + sF_rhoin^2 + sU_rhoout^2 + sU_rhoin^2)
    end

    # Lower and upper bound chosen such that 1/25 <= exp(|Im \omega| rsmp) <= 1 respectively
    rsmp_candidate = -range(log(25)/abs(imag(omega)), 0, length=25)
    for rsmp in rsmp_candidate
        objective_value = check_potential_behaviors(rsmp)
        if objective_value < 1e-10
            return solve_r_from_rho_rsmp(rsmp), rsmp
        end
    end
    # Found no candidate, revert to just 0 but return rsmp = NaN to signify optimization failure
    return solve_r_from_rho_rsmp(0), NaN
end

const HOMOGENEOUS_REPRESENTATION_ID = "factored-plane-wave-gsn/v1"
const FACTORED_HOMOGENEOUS_ODE_SCOPE_ID = "factored-homogeneous-gsn/v1"
const MATCH_RADIAL_DERIVATIVE_CONVENTION_ID =
    "match-state2=dX/drstar-from-Xrho-over-contour-tangent/v1"
const _FACTORED_DEFAULTSOLVER = AutoVern9(Rosenbrock23(autodiff=false))

@enum FactoredPropagationFailureReason begin
    INVALID_FACTORED_PROPAGATION_INPUT = 1
    FACTORED_PROPAGATION_PRECISION_MISMATCH = 2
    NONFINITE_FACTORED_PROPAGATION_DATA = 3
    INSUFFICIENT_ASYMPTOTIC_PRECISION = 4
    CARRIER_CHANGE_INCONSISTENT = 5
    FACTORED_ODE_FAILURE = 6
    NO_VERIFIED_HORIZON_ENDPOINT = 7
    COORDINATE_INVERSION_STALLED = 8
end

@enum FactoredODESolveExceptionDisposition begin
    PASSTHROUGH_ODE_EXCEPTION = 1
    WRAP_ODE_EXCEPTION = 2
end

struct FactoredPropagationError{T<:AbstractFloat} <: Exception
    reason::Union{FactoredPropagationFailureReason,AsymptoticFailureReason}
    assessment::Union{Nothing,AsymptoticConditioningAssessment{T}}
    precision_bits::Int
    factored_homogeneous_rhs_evaluations::Int
    avoided_ode_scope::String
    message::String
end

function Base.showerror(io::IO, error::FactoredPropagationError)
    print(
        io,
        string(error.reason),
        ": ",
        error.message,
        " (precision_bits=",
        error.precision_bits,
        ", factored_homogeneous_rhs_evaluations=",
        error.factored_homogeneous_rhs_evaluations,
        ", avoided_ode_scope=",
        error.avoided_ode_scope,
        ")",
    )
end

struct ContourAngleDeformation{T<:AbstractFloat}
    infinity_delta::T
    horizon_delta::T
    maximum_absolute::T
end

struct HomogeneousSpectralContext{T<:AbstractFloat}
    s::Int
    m::Int
    a::T
    omega::Complex{T}
    lambda::Complex{T}
    p_horizon::Complex{T}
    precision_digits::Int
    precision_bits::Int
    endpoint_order::Int
    series::AsymptoticSeriesBundle{T}
    contract::RegularRemainderContract
    convention::GSNBranchConvention{T}
    frozen_convention::GSNBranchConvention{T}
    frozen_branch_cell::GSNBranchCell
    contour_deformation::ContourAngleDeformation{T}
end

struct ComplexContourContext{T<:AbstractFloat,F}
    match_radius::T
    rstar_match::T
    rho_in::T
    rho_out::T
    precision_bits::Int
    infinity_contour_angle::T
    horizon_contour_angle::T
    infinity_sign::Int8
    horizon_sign::Int8
    infinity_tangent::Complex{T}
    horizon_tangent::Complex{T}
    radius_from_rho::F
    convention::GSNBranchConvention{T}
    frozen_branch_cell::GSNBranchCell
    contour_deformation::ContourAngleDeformation{T}
end

# Compatibility alias for callers written while Task 1C was under review. New
# production code uses the mathematically explicit ComplexContourContext name.
const ContourContext = ComplexContourContext

struct FactoredEndpointPreparation{T<:AbstractFloat}
    branch::CarrierKind
    initial_condition::FactoredInitialCondition{T}
    assessment::AsymptoticConditioningAssessment{T}
    required_digits::T
    precision_bits::Int
    endpoint_order::Int
    frozen_branch_cell::GSNBranchCell
    contour_deformation::ContourAngleDeformation{T}
end

struct HorizonDeterminantPreparation{T<:AbstractFloat}
    infinity_outgoing::FactoredEndpointPreparation{T}
    horizon_ingoing::FactoredEndpointPreparation{T}
    horizon_outgoing::FactoredEndpointPreparation{T}
end

struct ExteriorDeterminantPreparation{T<:AbstractFloat}
    horizon_ingoing::FactoredEndpointPreparation{T}
    infinity_outgoing::FactoredEndpointPreparation{T}
end

struct FactoredGSNParameters{T<:AbstractFloat,F}
    s::Int
    m::Int
    a::T
    omega::Complex{T}
    lambda::Complex{T}
    radius_from_rho::F
    tangent::Complex{T}
    carrier::PlaneWaveCarrier{T}
    precision_bits::Int
    rhs_evaluations_at_start::Int
    factored_homogeneous_rhs_evaluations::Base.RefValue{Int}
end

mutable struct _FactoredDiagnosticAccumulator{T<:AbstractFloat}
    accepted_steps::Int
    maximum_remainder_state_norm::T
    minimum_remainder_state_norm::T
    maximum_absolute_real_carrier_log::T
end

struct FactoredODEDiagnostics{T<:AbstractFloat}
    branch::CarrierKind
    ode_leg::String
    representation_id::String
    ode_scope_id::String
    precision_bits::Int
    accepted_steps::Int
    rejected_steps::Int
    maximum_remainder_state_norm::T
    minimum_remainder_state_norm::T
    maximum_absolute_real_carrier_log::T
    initial_regularity::RemainderRegularityEvidence{T}
    assessment::AsymptoticConditioningAssessment{T}
    convention::GSNBranchConvention{T}
    frozen_branch_cell::GSNBranchCell
    contour_deformation::ContourAngleDeformation{T}
    factored_homogeneous_rhs_evaluations::Int
    endpoint_only_saved_points::Int
end

struct FactoredODESolution{T<:AbstractFloat}
    endpoint::FactoredEndpointState{T}
    carrier::PlaneWaveCarrier{T}
    endpoint_rho::T
    diagnostics::FactoredODEDiagnostics{T}
end

struct FactoredCarrierTransition{T<:AbstractFloat}
    state::FactoredEndpointState{T}
    source_carrier::PlaneWaveCarrier{T}
    target_carrier::PlaneWaveCarrier{T}
    diagnostics::CarrierChangeDiagnostics{T}
    reconstruction_tolerance::T
    frozen_branch_cell::GSNBranchCell
    contour_deformation::ContourAngleDeformation{T}
end

struct FactoredScatteringPropagation{T<:AbstractFloat}
    infinity_outer_to_match::FactoredODESolution{T}
    carrier_transition::FactoredCarrierTransition{T}
    horizon_match_to_inner::FactoredODESolution{T}
end

struct FactoredExteriorMatches{T<:AbstractFloat}
    xin_at_match::FactoredODESolution{T}
    xup_at_match::FactoredODESolution{T}
end

struct FactoredMatchState{T<:AbstractFloat}
    X::Complex{T}
    Xrho::Complex{T}
    dX_drstar::Complex{T}
    rho::T
    branch::CarrierKind
    tangent::Complex{T}
    radial_derivative_convention::String
end

function _factored_error(
    ::Type{T},
    reason::Union{FactoredPropagationFailureReason,AsymptoticFailureReason},
    precision_bits::Int,
    message::AbstractString;
    assessment::Union{Nothing,AsymptoticConditioningAssessment{T}}=nothing,
    factored_homogeneous_rhs_evaluations::Int=0,
) where {T<:AbstractFloat}
    return FactoredPropagationError{T}(
        reason,
        assessment,
        precision_bits,
        factored_homogeneous_rhs_evaluations,
        FACTORED_HOMOGENEOUS_ODE_SCOPE_ID,
        String(message),
    )
end

function _translate_factored_failure(
    operation::F,
    ::Type{T},
    precision_bits::Int,
    context::AbstractString;
    argument_reason::FactoredPropagationFailureReason=
        INVALID_FACTORED_PROPAGATION_INPUT,
    factored_homogeneous_rhs_evaluations::Int=0,
) where {F,T<:AbstractFloat}
    try
        return operation()
    catch error
        error isa FactoredPropagationError && rethrow()
        if error isa AsymptoticConstructionError
            throw(_factored_error(
                T,
                error.reason,
                precision_bits,
                "$context: $(error.message)";
                factored_homogeneous_rhs_evaluations=
                    factored_homogeneous_rhs_evaluations,
            ))
        elseif error isa ArgumentError || error isa DomainError
            throw(_factored_error(
                T,
                argument_reason,
                precision_bits,
                "$context: $(sprint(showerror, error))";
                factored_homogeneous_rhs_evaluations=
                    factored_homogeneous_rhs_evaluations,
            ))
        end
        rethrow()
    end
end

function _factored_rhs_evaluation_count(parameters::FactoredGSNParameters)
    return max(
        0,
        parameters.factored_homogeneous_rhs_evaluations[] -
            parameters.rhs_evaluations_at_start,
    )
end

_never_passthrough_ode_exception(_error) = false

function _factored_ode_exception_disposition(
    error, ode_exception_passthrough
)
    if error isa FactoredPropagationError || error isa InterruptException
        return PASSTHROUGH_ODE_EXCEPTION
    end
    passthrough = ode_exception_passthrough(error)
    passthrough isa Bool || throw(ArgumentError(
        "ode_exception_passthrough must return Bool"
    ))
    return passthrough ?
        PASSTHROUGH_ODE_EXCEPTION : WRAP_ODE_EXCEPTION
end

function _throw_or_wrap_factored_ode_failure(
    error,
    ode_exception_passthrough,
    ::Type{T},
    precision_bits::Int,
    assessment::AsymptoticConditioningAssessment{T},
    factored_homogeneous_rhs_evaluations::Int,
) where {T<:AbstractFloat}
    disposition = _factored_ode_exception_disposition(
        error, ode_exception_passthrough
    )
    disposition === PASSTHROUGH_ODE_EXCEPTION && throw(error)
    throw(_factored_error(
        T,
        FACTORED_ODE_FAILURE,
        precision_bits,
        "factored ODE solve failed: $(sprint(showerror, error))";
        assessment=assessment,
        factored_homogeneous_rhs_evaluations=
            factored_homogeneous_rhs_evaluations,
    ))
end

function _with_factored_precision(
    operation::F, ::Type{BigFloat}, precision_bits::Int
) where {F}
    return setprecision(BigFloat, precision_bits) do
        operation()
    end
end

function _with_factored_precision(
    operation::F, ::Type{T}, precision_bits::Int
) where {F,T<:AbstractFloat}
    precision(T) == precision_bits || throw(ArgumentError(
        "requested precision does not match the floating component type"
    ))
    return operation()
end

function _finite_factored_complex(value::Complex)
    return isfinite(real(value)) && isfinite(imag(value))
end

function _factored_precision_matches(value::T, precision_bits::Int) where {T<:AbstractFloat}
    return precision(value) == precision_bits
end

function _factored_precision_matches(
    value::Complex{T}, precision_bits::Int
) where {T<:AbstractFloat}
    return precision(real(value)) == precision_bits &&
        precision(imag(value)) == precision_bits
end

_exact_factored_value(left, right) =
    typeof(left) === typeof(right) && isequal(left, right)

function _exact_factored_value(left::T, right::T) where {T<:AbstractFloat}
    return isequal(left, right) && precision(left) == precision(right)
end

function _exact_factored_value(
    left::Complex{T}, right::Complex{T}
) where {T<:AbstractFloat}
    return _exact_factored_value(real(left), real(right)) &&
        _exact_factored_value(imag(left), imag(right))
end

function _primitive_fields_match_exactly(left::S, right::S) where {S}
    return all(
        name -> _exact_factored_value(
            getfield(left, name), getfield(right, name)
        ),
        fieldnames(S),
    )
end

_conventions_match_exactly(
    left::GSNBranchConvention, right::GSNBranchConvention
) = _primitive_fields_match_exactly(left, right)

_branch_cells_match_exactly(left::GSNBranchCell, right::GSNBranchCell) =
    _primitive_fields_match_exactly(left, right)

_deformations_match_exactly(
    left::ContourAngleDeformation, right::ContourAngleDeformation
) = _primitive_fields_match_exactly(left, right)

_contracts_match_exactly(
    left::RegularRemainderContract, right::RegularRemainderContract
) = _primitive_fields_match_exactly(left, right)

_series_keys_match_exactly(left::SeriesKey, right::SeriesKey) =
    _primitive_fields_match_exactly(left, right)

function _series_evaluations_match_exactly(
    left::SeriesEvaluation, right::SeriesEvaluation
)
    _series_keys_match_exactly(left.key, right.key) || return false
    return all(
        name -> name === :key || _exact_factored_value(
            getfield(left, name), getfield(right, name)
        ),
        fieldnames(typeof(left)),
    )
end

_endpoint_states_match_exactly(
    left::FactoredEndpointState, right::FactoredEndpointState
) = _primitive_fields_match_exactly(left, right)

_regularity_evidence_matches_exactly(
    left::RemainderRegularityEvidence, right::RemainderRegularityEvidence
) = _primitive_fields_match_exactly(left, right)

function _carriers_match_exactly(
    left::PlaneWaveCarrier, right::PlaneWaveCarrier
)
    return left.kind === right.kind &&
        _exact_factored_value(left.wave_number, right.wave_number) &&
        _exact_factored_value(left.rstar_match, right.rstar_match) &&
        _exact_factored_value(left.log_at_match, right.log_at_match) &&
        _exact_factored_value(left.q, right.q) &&
        _conventions_match_exactly(left.convention, right.convention)
end

function _factored_initial_conditions_match_exactly(
    left::FactoredInitialCondition, right::FactoredInitialCondition
)
    return _endpoint_states_match_exactly(left.state, right.state) &&
        _carriers_match_exactly(left.carrier, right.carrier) &&
        _series_evaluations_match_exactly(left.evaluation, right.evaluation) &&
        _regularity_evidence_matches_exactly(
            left.regularity, right.regularity
        ) &&
        _contracts_match_exactly(left.contract, right.contract)
end

_assessments_match_exactly(
    left::AsymptoticConditioningAssessment,
    right::AsymptoticConditioningAssessment,
) = _primitive_fields_match_exactly(left, right)

function _canonical_carrier(
    spectral::HomogeneousSpectralContext{T},
    contour::ComplexContourContext{T},
    kind::CarrierKind,
) where {T<:AbstractFloat}
    wave_number = kind === INFINITY_OUTGOING ?
        spectral.omega : spectral.p_horizon
    return PlaneWaveCarrier(
        kind, wave_number, contour.rstar_match, spectral.convention
    )
end

function _assert_carrier_provenance(
    spectral::HomogeneousSpectralContext{T},
    contour::ComplexContourContext{T},
    carrier::PlaneWaveCarrier{T},
    kind::CarrierKind,
    context::AbstractString,
) where {T<:AbstractFloat}
    canonical = _translate_factored_failure(
        T,
        spectral.precision_bits,
        "$context canonical carrier construction";
        argument_reason=CARRIER_CHANGE_INCONSISTENT,
    ) do
        _canonical_carrier(spectral, contour, kind)
    end
    _carriers_match_exactly(carrier, canonical) || throw(_factored_error(
        T,
        CARRIER_CHANGE_INCONSISTENT,
        spectral.precision_bits,
        "$context carrier wave_number, rstar_match, log_at_match, q, kind, " *
        "or convention differs from the canonical spectral carrier",
    ))
    return canonical
end

function _series_key_matches_spectral(
    key::SeriesKey,
    spectral::HomogeneousSpectralContext,
    family::AsymptoticFamily,
)
    return key.s == spectral.s &&
        key.m == spectral.m &&
        _exact_factored_value(key.a, spectral.a) &&
        _exact_factored_value(key.omega, spectral.omega) &&
        _exact_factored_value(key.lambda, spectral.lambda) &&
        key.family === family &&
        key.max_order == spectral.endpoint_order &&
        key.precision_bits == spectral.precision_bits
end

function _assert_spectral_context_provenance(
    spectral::HomogeneousSpectralContext{T},
) where {T<:AbstractFloat}
    return _translate_factored_failure(
        T,
        spectral.precision_bits,
        "spectral context provenance",
    ) do
        _with_factored_precision(T, spectral.precision_bits) do
            spectral.precision_digits > 0 || throw(ArgumentError(
                "spectral precision_digits must be positive"
            ))
            spectral.endpoint_order >= 0 || throw(ArgumentError(
                "spectral endpoint_order must be nonnegative"
            ))
            all(
                value -> _factored_precision_matches(
                    value, spectral.precision_bits
                ),
                (
                    spectral.a,
                    spectral.omega,
                    spectral.lambda,
                    spectral.p_horizon,
                ),
            ) || throw(_factored_error(
                T,
                FACTORED_PROPAGATION_PRECISION_MISMATCH,
                spectral.precision_bits,
                "spectral context values do not preserve request precision",
            ))
            isfinite(spectral.a) &&
                _finite_factored_complex(spectral.omega) &&
                _finite_factored_complex(spectral.lambda) &&
                _finite_factored_complex(spectral.p_horizon) ||
                throw(ArgumentError("spectral context values must be finite"))
            iszero(spectral.omega) && throw(_factored_error(
                T,
                PHYSICAL_SINGULAR_LIMIT,
                spectral.precision_bits,
                "omega=0 is a physical singular limit of the selected " *
                "infinity plane-wave representation",
            ))
            geometry = stable_horizon_geometry(spectral.a)
            canonical_p_horizon = spectral.omega -
                T(spectral.m) * geometry.omega_horizon
            iszero(canonical_p_horizon) && throw(_factored_error(
                T,
                PHYSICAL_SINGULAR_LIMIT,
                spectral.precision_bits,
                "p_horizon=0 is a physical coalescence of the horizon carriers",
            ))
            _exact_factored_value(
                spectral.p_horizon, canonical_p_horizon
            ) || throw(ArgumentError(
                "spectral p_horizon does not reproduce from a, m, and omega"
            ))
            canonical_convention = gsn_branch_convention(
                spectral.omega, canonical_p_horizon
            )
            _conventions_match_exactly(
                spectral.convention, canonical_convention
            ) || throw(ArgumentError(
                "spectral convention does not reproduce from its wave numbers"
            ))
            assert_no_branch_crossing(
                spectral.frozen_convention, canonical_convention
            )
            canonical_branch_cell = branch_cell(spectral.frozen_convention)
            _branch_cells_match_exactly(
                spectral.frozen_branch_cell, canonical_branch_cell
            ) || throw(ArgumentError(
                "spectral frozen branch cell does not reproduce"
            ))
            raw_deformation = contour_angle_deformation(
                spectral.frozen_convention, canonical_convention
            )
            canonical_deformation = ContourAngleDeformation{T}(
                T(raw_deformation.infinity_delta),
                T(raw_deformation.horizon_delta),
                max(
                    abs(T(raw_deformation.infinity_delta)),
                    abs(T(raw_deformation.horizon_delta)),
                ),
            )
            _deformations_match_exactly(
                spectral.contour_deformation, canonical_deformation
            ) || throw(ArgumentError(
                "spectral contour deformation does not reproduce"
            ))
            _contracts_match_exactly(
                spectral.contract, RegularRemainderContract()
            ) || throw(ArgumentError(
                "spectral regular-remainder contract is not canonical"
            ))
            expected_families = (
                INFINITY_INGOING_SERIES,
                INFINITY_OUTGOING_SERIES,
                HORIZON_INGOING_SERIES,
                HORIZON_OUTGOING_SERIES,
            )
            actual_series = (
                spectral.series.infinity_ingoing,
                spectral.series.infinity_outgoing,
                spectral.series.horizon_ingoing,
                spectral.series.horizon_outgoing,
            )
            all(
                index -> _series_key_matches_spectral(
                    actual_series[index].key,
                    spectral,
                    expected_families[index],
                ),
                eachindex(actual_series),
            ) || throw(ArgumentError(
                "spectral asymptotic-series keys do not match their context"
            ))
            return nothing
        end
    end
end

function _assert_contour_context_provenance(
    spectral::HomogeneousSpectralContext{T},
    contour::ComplexContourContext{T},
) where {T<:AbstractFloat}
    _assert_spectral_context_provenance(spectral)
    return _translate_factored_failure(
        T,
        spectral.precision_bits,
        "contour context provenance";
        argument_reason=CARRIER_CHANGE_INCONSISTENT,
    ) do
        _with_factored_precision(T, spectral.precision_bits) do
            contour.precision_bits == spectral.precision_bits || throw(
                _factored_error(
                    T,
                    FACTORED_PROPAGATION_PRECISION_MISMATCH,
                    spectral.precision_bits,
                    "contour and spectral precision bits differ",
                )
            )
            all(
                value -> _factored_precision_matches(
                    value, spectral.precision_bits
                ),
                (
                    contour.match_radius,
                    contour.rstar_match,
                    contour.rho_in,
                    contour.rho_out,
                    contour.infinity_contour_angle,
                    contour.horizon_contour_angle,
                    contour.infinity_tangent,
                    contour.horizon_tangent,
                ),
            ) || throw(_factored_error(
                T,
                FACTORED_PROPAGATION_PRECISION_MISMATCH,
                spectral.precision_bits,
                "contour context values do not preserve request precision",
            ))
            _conventions_match_exactly(
                contour.convention, spectral.convention
            ) || throw(ArgumentError(
                "contour and spectral conventions differ"
            ))
            _branch_cells_match_exactly(
                contour.frozen_branch_cell, spectral.frozen_branch_cell
            ) || throw(ArgumentError(
                "contour and spectral frozen branch cells differ"
            ))
            _deformations_match_exactly(
                contour.contour_deformation, spectral.contour_deformation
            ) || throw(ArgumentError(
                "contour and spectral deformations differ"
            ))
            _exact_factored_value(
                contour.infinity_contour_angle,
                spectral.convention.infinity_contour_angle,
            ) && _exact_factored_value(
                contour.horizon_contour_angle,
                spectral.convention.horizon_contour_angle,
            ) && contour.infinity_sign == spectral.convention.infinity_sign &&
                contour.horizon_sign == spectral.convention.horizon_sign ||
                throw(ArgumentError(
                    "contour angles or signs differ from the sample convention"
                ))
            canonical_infinity_tangent = Complex{T}(
                infinity_contour_tangent(spectral.convention)
            )
            canonical_horizon_tangent = Complex{T}(
                horizon_contour_tangent(spectral.convention)
            )
            _exact_factored_value(
                contour.infinity_tangent, canonical_infinity_tangent
            ) && _exact_factored_value(
                contour.horizon_tangent, canonical_horizon_tangent
            ) || throw(ArgumentError(
                "contour tangents do not reproduce from the sample convention"
            ))
            canonical_rstar_match = T(rstar_from_r(
                spectral.a, contour.match_radius
            ))
            _exact_factored_value(
                contour.rstar_match, canonical_rstar_match
            ) || throw(ArgumentError(
                "rstar_match does not reproduce from a and match_radius"
            ))
            raw_match_radius = contour.radius_from_rho(zero(T))
            (raw_match_radius isa T || raw_match_radius isa Complex{T}) ||
                throw(_factored_error(
                    T,
                    FACTORED_PROPAGATION_PRECISION_MISMATCH,
                    spectral.precision_bits,
                    "radius_from_rho changed the contour component type",
                ))
            typed_match_radius = Complex{T}(raw_match_radius)
            _factored_precision_matches(
                typed_match_radius, spectral.precision_bits
            ) || throw(_factored_error(
                T,
                FACTORED_PROPAGATION_PRECISION_MISMATCH,
                spectral.precision_bits,
                "radius_from_rho narrowed the match-radius precision",
            ))
            match_radius_tolerance = T(256) * eps(T) *
                max(one(T), abs(contour.match_radius))
            abs(
                typed_match_radius -
                complex(contour.match_radius, zero(T))
            ) <= match_radius_tolerance || throw(ArgumentError(
                "radius_from_rho(0) does not reproduce match_radius"
            ))
            return nothing
        end
    end
end

function _branch_series(
    series::AsymptoticSeriesBundle, branch::CarrierKind
)
    if branch === INFINITY_OUTGOING
        return series.infinity_outgoing
    elseif branch === HORIZON_INGOING
        return series.horizon_ingoing
    elseif branch === HORIZON_OUTGOING
        return series.horizon_outgoing
    end
    throw(ArgumentError("unsupported factored branch"))
end

function _branch_tangent(
    contour::ComplexContourContext, branch::CarrierKind
)
    return branch === INFINITY_OUTGOING ?
        contour.infinity_tangent : contour.horizon_tangent
end

function _factored_default_tolerance(::Type{T}) where {T<:AbstractFloat}
    return one(T) / T(10)^12
end

function _resolve_factored_tolerance(
    ::Type{T},
    precision_bits::Int,
    value::Union{Nothing,T},
    name::AbstractString,
) where {T<:AbstractFloat}
    return _with_factored_precision(T, precision_bits) do
        resolved = value === nothing ? _factored_default_tolerance(T) : value
        _factored_precision_matches(resolved, precision_bits) || throw(
            _factored_error(
                T,
                FACTORED_PROPAGATION_PRECISION_MISMATCH,
                precision_bits,
                "$name does not preserve the context precision",
            )
        )
        resolved
    end
end

function build_homogeneous_spectral_context(
    s::Int,
    m::Int,
    a::T,
    omega::Complex{T},
    lambda::Complex{T},
    precision_digits::Int,
    precision_bits::Int,
    endpoint_order::Int,
    frozen_convention::GSNBranchConvention{T},
) where {T<:AbstractFloat}
    return _translate_factored_failure(
        T, precision_bits, "homogeneous spectral context construction"
    ) do
        precision_digits > 0 || throw(ArgumentError(
            "precision_digits must be positive"
        ))
        precision_bits > 0 || throw(ArgumentError(
            "precision_bits must be positive"
        ))
        endpoint_order >= 0 || throw(ArgumentError(
            "endpoint_order must be nonnegative"
        ))
        _factored_precision_matches(a, precision_bits) &&
            _factored_precision_matches(omega, precision_bits) &&
            _factored_precision_matches(lambda, precision_bits) ||
            throw(ArgumentError(
                "spectral values do not share the requested precision"
            ))
        isfinite(a) && _finite_factored_complex(omega) &&
            _finite_factored_complex(lambda) || throw(ArgumentError(
                "spectral values must be finite"
            ))
        frozen_numeric_fields = (
            frozen_convention.infinity_contour_angle,
            frozen_convention.horizon_contour_angle,
            frozen_convention.omega_argument,
            frozen_convention.p_horizon_argument,
        )
        all(isfinite, frozen_numeric_fields) || throw(ArgumentError(
            "frozen convention numeric fields must be finite"
        ))
        all(
            value -> _factored_precision_matches(value, precision_bits),
            frozen_numeric_fields,
        ) || throw(ArgumentError(
            "frozen convention does not preserve the requested precision"
        ))
        _with_factored_precision(T, precision_bits) do
            iszero(omega) && throw(_factored_error(
                T,
                PHYSICAL_SINGULAR_LIMIT,
                precision_bits,
                "omega=0 is a physical singular limit of the selected " *
                "infinity plane-wave representation",
            ))
            geometry = stable_horizon_geometry(a)
            p_horizon = omega - T(m) * geometry.omega_horizon
            _finite_factored_complex(p_horizon) || throw(ArgumentError(
                "horizon wave number must be finite"
            ))
            iszero(p_horizon) && throw(_factored_error(
                T,
                PHYSICAL_SINGULAR_LIMIT,
                precision_bits,
                "p_horizon=0 is a physical coalescence of the horizon carriers",
            ))
            convention = gsn_branch_convention(omega, p_horizon)
            deltas = try
                assert_no_branch_crossing(frozen_convention, convention)
                contour_angle_deformation(frozen_convention, convention)
            catch error
                error isa ArgumentError || rethrow()
                throw(_factored_error(
                    T,
                    CARRIER_CHANGE_INCONSISTENT,
                    precision_bits,
                    "sample convention crosses the frozen branch cell: " *
                    sprint(showerror, error),
                ))
            end
            deformation = ContourAngleDeformation{T}(
                T(deltas.infinity_delta),
                T(deltas.horizon_delta),
                max(
                    abs(T(deltas.infinity_delta)),
                    abs(T(deltas.horizon_delta)),
                ),
            )
            series = build_asymptotic_series_bundle(
                s,
                m,
                a,
                omega,
                lambda,
                endpoint_order;
                precision_bits=precision_bits,
            )
            return HomogeneousSpectralContext{T}(
                s,
                m,
                a,
                omega,
                lambda,
                p_horizon,
                precision_digits,
                precision_bits,
                endpoint_order,
                series,
                RegularRemainderContract(),
                convention,
                frozen_convention,
                branch_cell(frozen_convention),
                deformation,
            )
        end
    end
end

function build_contour_context(
    spectral::HomogeneousSpectralContext{T},
    match_radius::T,
    rstar_match::T,
    rho_in::T,
    rho_out::T,
    radius_from_rho::F,
) where {T<:AbstractFloat,F}
    return _translate_factored_failure(
        T,
        spectral.precision_bits,
        "contour context construction",
    ) do
        _with_factored_precision(T, spectral.precision_bits) do
            _assert_spectral_context_provenance(spectral)
            all(isfinite, (match_radius, rstar_match, rho_in, rho_out)) ||
                throw(ArgumentError("contour scalars must be finite"))
            all(
                value -> _factored_precision_matches(
                    value, spectral.precision_bits
                ),
                (match_radius, rstar_match, rho_in, rho_out),
            ) || throw(ArgumentError(
                "contour scalars do not preserve the spectral precision"
            ))
            rho_in < zero(T) < rho_out || throw(ArgumentError(
                "contour endpoints must satisfy rho_in < 0 < rho_out"
            ))
            geometry = stable_horizon_geometry(spectral.a)
            match_radius > geometry.rplus || throw(ArgumentError(
                "match radius must lie outside the outer horizon"
            ))
            canonical_rstar_match = T(rstar_from_r(
                spectral.a, match_radius
            ))
            _factored_precision_matches(
                canonical_rstar_match, spectral.precision_bits
            ) || throw(ArgumentError(
                "canonical rstar_match does not preserve spectral precision"
            ))
            _exact_factored_value(
                rstar_match, canonical_rstar_match
            ) || throw(ArgumentError(
                "rstar_match must equal Coordinates.rstar_from_r(a, match_radius)"
            ))
            raw_match_radius = radius_from_rho(zero(match_radius))
            (raw_match_radius isa T || raw_match_radius isa Complex{T}) ||
                throw(ArgumentError(
                    "radius_from_rho must preserve the context component type"
                ))
            typed_match_radius = Complex{T}(raw_match_radius)
            _factored_precision_matches(
                typed_match_radius, spectral.precision_bits
            ) || throw(ArgumentError(
                "radius_from_rho narrowed the match-radius precision"
            ))
            _finite_factored_complex(typed_match_radius) ||
                throw(ArgumentError(
                    "radius_from_rho returned a nonfinite match radius"
                ))
            match_radius_tolerance = T(256) * eps(T) *
                max(one(T), abs(match_radius))
            abs(
                typed_match_radius - complex(match_radius, zero(T))
            ) <= match_radius_tolerance || throw(ArgumentError(
                "radius_from_rho(0) does not reproduce match_radius"
            ))
            assert_no_branch_crossing(
                spectral.frozen_convention, spectral.convention
            )
            infinity_tangent = Complex{T}(
                infinity_contour_tangent(spectral.convention)
            )
            horizon_tangent = Complex{T}(
                horizon_contour_tangent(spectral.convention)
            )
            _factored_precision_matches(
                infinity_tangent, spectral.precision_bits
            ) && _factored_precision_matches(
                horizon_tangent, spectral.precision_bits
            ) || throw(ArgumentError(
                "contour tangents do not preserve spectral precision"
            ))
            _finite_factored_complex(infinity_tangent) &&
                _finite_factored_complex(horizon_tangent) &&
                !iszero(infinity_tangent) && !iszero(horizon_tangent) ||
                throw(ArgumentError(
                    "contour tangents must be finite and nonzero"
                ))
            return ComplexContourContext{T,F}(
                match_radius,
                canonical_rstar_match,
                rho_in,
                rho_out,
                spectral.precision_bits,
                spectral.convention.infinity_contour_angle,
                spectral.convention.horizon_contour_angle,
                spectral.convention.infinity_sign,
                spectral.convention.horizon_sign,
                infinity_tangent,
                horizon_tangent,
                radius_from_rho,
                spectral.convention,
                spectral.frozen_branch_cell,
                spectral.contour_deformation,
            )
        end
    end
end

function _build_factored_initial_condition(
    spectral::HomogeneousSpectralContext{T},
    contour::ComplexContourContext{T},
    branch::CarrierKind,
    order::Int,
) where {T<:AbstractFloat}
    0 <= order <= spectral.endpoint_order || throw(ArgumentError(
        "factored endpoint prefix order is outside the generated series"
    ))
    series = _branch_series(spectral.series, branch)
    if branch === INFINITY_OUTGOING
        return factored_infinity_outgoing_initialconditions(
            series,
            contour.rho_out,
            contour.rstar_match,
            contour.radius_from_rho,
            spectral.convention,
            spectral.contract;
            order=order,
        )
    elseif branch === HORIZON_INGOING
        return factored_horizon_ingoing_initialconditions(
            series,
            contour.rho_in,
            contour.rstar_match,
            contour.radius_from_rho,
            spectral.convention,
            spectral.contract;
            order=order,
        )
    elseif branch === HORIZON_OUTGOING
        return factored_horizon_outgoing_initialconditions(
            series,
            contour.rho_in,
            contour.rstar_match,
            contour.radius_from_rho,
            spectral.convention,
            spectral.contract;
            order=order,
        )
    end
    throw(ArgumentError("unsupported factored endpoint branch"))
end

function _prepare_factored_endpoint(
    spectral::HomogeneousSpectralContext{T},
    contour::ComplexContourContext{T},
    branch::CarrierKind,
    required_digits::T,
    order::Int,
) where {T<:AbstractFloat}
    return _translate_factored_failure(
        T,
        spectral.precision_bits,
        "factored endpoint preparation",
    ) do
        _with_factored_precision(T, spectral.precision_bits) do
            _factored_precision_matches(
                required_digits, spectral.precision_bits
            ) || throw(_factored_error(
                T,
                FACTORED_PROPAGATION_PRECISION_MISMATCH,
                spectral.precision_bits,
                "required reliable digits do not preserve request precision",
            ))
            isfinite(required_digits) && required_digits >= zero(T) ||
                throw(ArgumentError(
                    "required reliable digits must be finite and nonnegative"
                ))
            _assert_contour_context_provenance(spectral, contour)
            series = _branch_series(spectral.series, branch)
            initial_condition = _build_factored_initial_condition(
                spectral, contour, branch, order
            )
            initial_condition.regularity.finite || throw(ArgumentError(
                "regular-remainder endpoint evidence is not finite"
            ))
            assessment = assess_asymptotic_preflight(
                series, initial_condition.evaluation, required_digits
            )
            return FactoredEndpointPreparation{T}(
                branch,
                initial_condition,
                assessment,
                required_digits,
                spectral.precision_bits,
                order,
                spectral.frozen_branch_cell,
                spectral.contour_deformation,
            )
        end
    end
end

function prepare_factored_infinity_outgoing(
    spectral::HomogeneousSpectralContext{T},
    contour::ComplexContourContext{T},
    required_digits::T,
    ; order::Int=spectral.endpoint_order,
) where {T<:AbstractFloat}
    return _prepare_factored_endpoint(
        spectral, contour, INFINITY_OUTGOING, required_digits, order
    )
end

function prepare_factored_horizon_ingoing(
    spectral::HomogeneousSpectralContext{T},
    contour::ComplexContourContext{T},
    required_digits::T,
    ; order::Int=spectral.endpoint_order,
) where {T<:AbstractFloat}
    return _prepare_factored_endpoint(
        spectral, contour, HORIZON_INGOING, required_digits, order
    )
end

function prepare_factored_horizon_outgoing(
    spectral::HomogeneousSpectralContext{T},
    contour::ComplexContourContext{T},
    required_digits::T,
    ; order::Int=spectral.endpoint_order,
) where {T<:AbstractFloat}
    return _prepare_factored_endpoint(
        spectral, contour, HORIZON_OUTGOING, required_digits, order
    )
end

function prepare_factored_horizon_determinant_branches(
    spectral::HomogeneousSpectralContext{T},
    contour::ComplexContourContext{T},
    required_digits::T,
) where {T<:AbstractFloat}
    infinity_outgoing = prepare_factored_infinity_outgoing(
        spectral, contour, required_digits
    )
    horizon_ingoing = prepare_factored_horizon_ingoing(
        spectral, contour, required_digits
    )
    horizon_outgoing = prepare_factored_horizon_outgoing(
        spectral, contour, required_digits
    )
    return HorizonDeterminantPreparation{T}(
        infinity_outgoing, horizon_ingoing, horizon_outgoing
    )
end

function prepare_factored_exterior_determinant_branches(
    spectral::HomogeneousSpectralContext{T},
    contour::ComplexContourContext{T},
    required_digits::T,
) where {T<:AbstractFloat}
    horizon_ingoing = prepare_factored_horizon_ingoing(
        spectral, contour, required_digits
    )
    infinity_outgoing = prepare_factored_infinity_outgoing(
        spectral, contour, required_digits
    )
    return ExteriorDeterminantPreparation{T}(
        horizon_ingoing, infinity_outgoing
    )
end

function _assert_factored_preflight_adequate(
    preparation::FactoredEndpointPreparation{T}
) where {T<:AbstractFloat}
    preparation.assessment.adequate || throw(_factored_error(
        T,
        INSUFFICIENT_ASYMPTOTIC_PRECISION,
        preparation.precision_bits,
        "asymptotic construction cannot supply the required reliable digits";
        assessment=preparation.assessment,
        factored_homogeneous_rhs_evaluations=0,
    ))
    return preparation
end

function assert_factored_preflights_adequate(
    preparations::FactoredEndpointPreparation...
)
    for preparation in preparations
        _assert_factored_preflight_adequate(preparation)
    end
    return preparations
end

function assert_factored_preflights_adequate(
    preparation::HorizonDeterminantPreparation
)
    return assert_factored_preflights_adequate(
        preparation.infinity_outgoing,
        preparation.horizon_ingoing,
        preparation.horizon_outgoing,
    )
end

function assert_factored_preflights_adequate(
    preparation::ExteriorDeterminantPreparation
)
    return assert_factored_preflights_adequate(
        preparation.horizon_ingoing, preparation.infinity_outgoing
    )
end

function _assert_preparation_provenance(
    spectral::HomogeneousSpectralContext{T},
    contour::ComplexContourContext{T},
    preparation::FactoredEndpointPreparation{T},
) where {T<:AbstractFloat}
    return _translate_factored_failure(
        T,
        spectral.precision_bits,
        "prepared endpoint provenance",
    ) do
        _with_factored_precision(T, spectral.precision_bits) do
            _assert_contour_context_provenance(spectral, contour)
            preparation.precision_bits == spectral.precision_bits || throw(
                _factored_error(
                    T,
                    FACTORED_PROPAGATION_PRECISION_MISMATCH,
                    spectral.precision_bits,
                    "prepared endpoint precision differs from spectral context",
                )
            )
            _factored_precision_matches(
                preparation.required_digits, spectral.precision_bits
            ) || throw(_factored_error(
                T,
                FACTORED_PROPAGATION_PRECISION_MISMATCH,
                spectral.precision_bits,
                "prepared required_digits do not preserve request precision",
            ))
            0 <= preparation.endpoint_order <= spectral.endpoint_order || throw(
                _factored_error(
                    T,
                    INVALID_FACTORED_PROPAGATION_INPUT,
                    spectral.precision_bits,
                    "prepared endpoint order exceeds the generated series",
                )
            )
            _branch_cells_match_exactly(
                preparation.frozen_branch_cell,
                spectral.frozen_branch_cell,
            ) && _branch_cells_match_exactly(
                preparation.frozen_branch_cell,
                contour.frozen_branch_cell,
            ) || throw(_factored_error(
                T,
                CARRIER_CHANGE_INCONSISTENT,
                spectral.precision_bits,
                "prepared, spectral, and contour branch cells differ",
            ))
            _deformations_match_exactly(
                preparation.contour_deformation,
                spectral.contour_deformation,
            ) && _deformations_match_exactly(
                preparation.contour_deformation,
                contour.contour_deformation,
            ) || throw(_factored_error(
                T,
                CARRIER_CHANGE_INCONSISTENT,
                spectral.precision_bits,
                "prepared, spectral, and contour deformations differ",
            ))
            expected_initial_condition = _build_factored_initial_condition(
                spectral, contour, preparation.branch,
                preparation.endpoint_order,
            )
            _factored_initial_conditions_match_exactly(
                preparation.initial_condition, expected_initial_condition
            ) || throw(_factored_error(
                T,
                INVALID_FACTORED_PROPAGATION_INPUT,
                spectral.precision_bits,
                "prepared factored initial condition does not reproduce exactly",
            ))
            _assert_carrier_provenance(
                spectral,
                contour,
                preparation.initial_condition.carrier,
                preparation.branch,
                "prepared endpoint",
            )
            series = _branch_series(spectral.series, preparation.branch)
            refreshed = assess_asymptotic_preflight(
                series,
                expected_initial_condition.evaluation,
                preparation.required_digits,
            )
            _assessments_match_exactly(
                refreshed, preparation.assessment
            ) || throw(_factored_error(
                T,
                INVALID_FACTORED_PROPAGATION_INPUT,
                spectral.precision_bits,
                "prepared asymptotic assessment does not reproduce exactly",
            ))
            return nothing
        end
    end
end

function _assert_horizon_preparation_provenance(
    spectral::HomogeneousSpectralContext{T},
    contour::ComplexContourContext{T},
    preparations::HorizonDeterminantPreparation{T},
) where {T<:AbstractFloat}
    _assert_preparation_provenance(
        spectral, contour, preparations.infinity_outgoing
    )
    _assert_preparation_provenance(
        spectral, contour, preparations.horizon_ingoing
    )
    _assert_preparation_provenance(
        spectral, contour, preparations.horizon_outgoing
    )
    preparations.infinity_outgoing.branch === INFINITY_OUTGOING &&
        preparations.horizon_ingoing.branch === HORIZON_INGOING &&
        preparations.horizon_outgoing.branch === HORIZON_OUTGOING ||
        throw(_factored_error(
            T,
            INVALID_FACTORED_PROPAGATION_INPUT,
            spectral.precision_bits,
            "horizon determinant preparation branch slots are not canonical",
        ))
    return nothing
end

function _assert_exterior_preparation_provenance(
    spectral::HomogeneousSpectralContext{T},
    contour::ComplexContourContext{T},
    preparations::ExteriorDeterminantPreparation{T},
) where {T<:AbstractFloat}
    _assert_preparation_provenance(
        spectral, contour, preparations.horizon_ingoing
    )
    _assert_preparation_provenance(
        spectral, contour, preparations.infinity_outgoing
    )
    preparations.horizon_ingoing.branch === HORIZON_INGOING &&
        preparations.infinity_outgoing.branch === INFINITY_OUTGOING ||
        throw(_factored_error(
            T,
            INVALID_FACTORED_PROPAGATION_INPUT,
            spectral.precision_bits,
            "exterior determinant preparation branch slots are not canonical",
        ))
    return nothing
end

function assert_factored_exterior_preparations_ready(
    spectral::HomogeneousSpectralContext{T},
    horizon_contour::ComplexContourContext{T},
    horizon_ingoing::FactoredEndpointPreparation{T},
    infinity_contour::ComplexContourContext{T},
    infinity_outgoing::FactoredEndpointPreparation{T},
) where {T<:AbstractFloat}
    _assert_preparation_provenance(
        spectral, horizon_contour, horizon_ingoing
    )
    _assert_preparation_provenance(
        spectral, infinity_contour, infinity_outgoing
    )
    horizon_ingoing.branch === HORIZON_INGOING &&
        infinity_outgoing.branch === INFINITY_OUTGOING || throw(
            _factored_error(
                T,
                INVALID_FACTORED_PROPAGATION_INPUT,
                spectral.precision_bits,
                "exterior endpoint branch slots are not canonical",
            )
        )
    assert_factored_preflights_adequate(
        horizon_ingoing, infinity_outgoing
    )
    return nothing
end

function _factored_transformed_rhs_second(
    Y::Complex{T},
    Yrho::Complex{T},
    F_rho::Complex{T},
    U_rho::Complex{T},
    q::Complex{T},
    q_rho::Complex{T},
)::Complex{T} where {T<:AbstractFloat}
    return (F_rho - 2 * q) * Yrho +
        (U_rho + F_rho * q - q_rho - q^2) * Y
end

function factored_GSN_linear_eqn!(du, state, parameters, rho)
    factored_homogeneous_rhs_evaluations =
        parameters.factored_homogeneous_rhs_evaluations
    factored_homogeneous_rhs_evaluations[] += 1
    T = typeof(parameters.a)
    rhs_count = _factored_rhs_evaluation_count(parameters)
    return _translate_factored_failure(
        T,
        parameters.precision_bits,
        "factored homogeneous RHS";
        factored_homogeneous_rhs_evaluations=rhs_count,
    ) do
        _with_factored_precision(T, parameters.precision_bits) do
            length(state) == 2 && length(du) == 2 || throw(ArgumentError(
                "factored homogeneous state and derivative must have length two"
            ))
            rho isa T && _factored_precision_matches(
                rho, parameters.precision_bits
            ) || throw(_factored_error(
                T,
                FACTORED_PROPAGATION_PRECISION_MISMATCH,
                parameters.precision_bits,
                "RHS rho does not preserve request precision";
                factored_homogeneous_rhs_evaluations=rhs_count,
            ))
            isfinite(rho) || throw(_factored_error(
                T,
                NONFINITE_FACTORED_PROPAGATION_DATA,
                parameters.precision_bits,
                "RHS rho is nonfinite";
                factored_homogeneous_rhs_evaluations=rhs_count,
            ))
            all(
                value -> value isa Complex{T} &&
                    _factored_precision_matches(
                        value, parameters.precision_bits
                    ),
                state,
            ) || throw(_factored_error(
                T,
                FACTORED_PROPAGATION_PRECISION_MISMATCH,
                parameters.precision_bits,
                "factored RHS state narrowed or changed component type";
                factored_homogeneous_rhs_evaluations=rhs_count,
            ))
            all(_finite_factored_complex, state) || throw(_factored_error(
                T,
                NONFINITE_FACTORED_PROPAGATION_DATA,
                parameters.precision_bits,
                "factored RHS state is nonfinite";
                factored_homogeneous_rhs_evaluations=rhs_count,
            ))
            raw_r = parameters.radius_from_rho(rho)
            (raw_r isa T || raw_r isa Complex{T}) || throw(
                _factored_error(
                    T,
                    FACTORED_PROPAGATION_PRECISION_MISMATCH,
                    parameters.precision_bits,
                    "radius_from_rho narrowed or changed the RHS component type";
                    factored_homogeneous_rhs_evaluations=rhs_count,
                )
            )
            r = Complex{T}(raw_r)
            _factored_precision_matches(r, parameters.precision_bits) || throw(
                _factored_error(
                    T,
                    FACTORED_PROPAGATION_PRECISION_MISMATCH,
                    parameters.precision_bits,
                    "radius_from_rho narrowed RHS precision";
                    factored_homogeneous_rhs_evaluations=rhs_count,
                )
            )
            _finite_factored_complex(r) || throw(_factored_error(
                T,
                NONFINITE_FACTORED_PROPAGATION_DATA,
                parameters.precision_bits,
                "radius_from_rho returned nonfinite RHS geometry";
                factored_homogeneous_rhs_evaluations=rhs_count,
            ))
            F_rho = parameters.tangent * sF(
                parameters.s,
                parameters.m,
                parameters.a,
                parameters.omega,
                parameters.lambda,
                r,
            )
            U_rho = parameters.tangent^2 * sU(
                parameters.s,
                parameters.m,
                parameters.a,
                parameters.omega,
                parameters.lambda,
                r,
            )
            q = carrier_log_derivative(parameters.carrier)
            q_rho = carrier_log_derivative_derivative(parameters.carrier)
            _finite_factored_complex(F_rho) &&
                _finite_factored_complex(U_rho) &&
                _finite_factored_complex(q) &&
                _finite_factored_complex(q_rho) || throw(_factored_error(
                    T,
                    NONFINITE_FACTORED_PROPAGATION_DATA,
                    parameters.precision_bits,
                    "factored RHS coefficient is nonfinite";
                    factored_homogeneous_rhs_evaluations=rhs_count,
                ))
            iszero(q_rho) || throw(_factored_error(
                T,
                INVALID_FACTORED_PROPAGATION_INPUT,
                parameters.precision_bits,
                "production plane-wave carrier must have q_rho=0";
                factored_homogeneous_rhs_evaluations=rhs_count,
            ))
            du[1] = state[2]
            du[2] = _factored_transformed_rhs_second(
                state[1], state[2], F_rho, U_rho, q, q_rho
            )
            du[1] isa Complex{T} && du[2] isa Complex{T} &&
                _finite_factored_complex(du[1]) &&
                _finite_factored_complex(du[2]) || throw(_factored_error(
                    T,
                    NONFINITE_FACTORED_PROPAGATION_DATA,
                    parameters.precision_bits,
                    "factored RHS derivative is nonfinite or narrowed";
                    factored_homogeneous_rhs_evaluations=rhs_count,
                ))
            return nothing
        end
    end
end

function _factored_internal_callback(
    accumulator::_FactoredDiagnosticAccumulator{T},
    carrier::PlaneWaveCarrier{T},
) where {T<:AbstractFloat}
    condition = (_state, _rho, _integrator) -> true
    affect! = integrator -> begin
        try
            state_norm = hypot(abs(integrator.u[1]), abs(integrator.u[2]))
            absolute_real_carrier_log = abs(real(carrier_log(
                carrier, integrator.t
            )))
            isfinite(state_norm) && isfinite(absolute_real_carrier_log) ||
                throw(ArgumentError(
                    "factored ODE diagnostics became nonfinite"
                ))
            accumulator.accepted_steps += 1
            accumulator.maximum_remainder_state_norm = max(
                accumulator.maximum_remainder_state_norm, state_norm
            )
            accumulator.minimum_remainder_state_norm = min(
                accumulator.minimum_remainder_state_norm, state_norm
            )
            accumulator.maximum_absolute_real_carrier_log = max(
                accumulator.maximum_absolute_real_carrier_log,
                absolute_real_carrier_log,
            )
        finally
            DifferentialEquations.SciMLBase.u_modified!(integrator, false)
        end
        nothing
    end
    return DiscreteCallback(
        condition, affect!; save_positions=(false, false)
    )
end

function _combine_factored_callbacks(external_callback, internal_callback)
    external_callback === nothing && return internal_callback
    internal_callback === nothing && return external_callback
    return CallbackSet(external_callback, internal_callback)
end

function _assert_factored_ode_solution_provenance(
    spectral::HomogeneousSpectralContext{T},
    contour::ComplexContourContext{T},
    propagated::FactoredODESolution{T},
    expected_branch::CarrierKind,
    expected_rho::T,
) where {T<:AbstractFloat}
    _assert_contour_context_provenance(spectral, contour)
    _assert_carrier_provenance(
        spectral,
        contour,
        propagated.carrier,
        expected_branch,
        "propagated factored endpoint",
    )
    _exact_factored_value(
        propagated.endpoint_rho, expected_rho
    ) || throw(_factored_error(
        T,
        CARRIER_CHANGE_INCONSISTENT,
        spectral.precision_bits,
        "propagated endpoint rho differs from the requested match point",
    ))
    _finite_factored_complex(propagated.endpoint.Y) &&
        _finite_factored_complex(propagated.endpoint.Yrho) || throw(
            _factored_error(
                T,
                NONFINITE_FACTORED_PROPAGATION_DATA,
                spectral.precision_bits,
                "propagated factored endpoint is nonfinite",
            )
        )
    diagnostics = propagated.diagnostics
    diagnostics.branch === expected_branch &&
        diagnostics.representation_id == HOMOGENEOUS_REPRESENTATION_ID &&
        diagnostics.ode_scope_id == FACTORED_HOMOGENEOUS_ODE_SCOPE_ID &&
        diagnostics.precision_bits == spectral.precision_bits &&
        diagnostics.factored_homogeneous_rhs_evaluations >= 0 &&
        diagnostics.endpoint_only_saved_points == 1 &&
        _conventions_match_exactly(
            diagnostics.convention, spectral.convention
        ) && _branch_cells_match_exactly(
            diagnostics.frozen_branch_cell, spectral.frozen_branch_cell
        ) && _deformations_match_exactly(
            diagnostics.contour_deformation, spectral.contour_deformation
        ) || throw(_factored_error(
            T,
            CARRIER_CHANGE_INCONSISTENT,
            spectral.precision_bits,
            "propagated endpoint diagnostics do not authenticate to the sample",
        ))
    return nothing
end

function _assert_carrier_transition_provenance(
    spectral::HomogeneousSpectralContext{T},
    contour::ComplexContourContext{T},
    transition::FactoredCarrierTransition{T},
) where {T<:AbstractFloat}
    _assert_contour_context_provenance(spectral, contour)
    _assert_carrier_provenance(
        spectral,
        contour,
        transition.source_carrier,
        INFINITY_OUTGOING,
        "carrier transition source",
    )
    _assert_carrier_provenance(
        spectral,
        contour,
        transition.target_carrier,
        HORIZON_INGOING,
        "carrier transition target",
    )
    _branch_cells_match_exactly(
        transition.frozen_branch_cell, spectral.frozen_branch_cell
    ) && _deformations_match_exactly(
        transition.contour_deformation, spectral.contour_deformation
    ) || throw(_factored_error(
        T,
        CARRIER_CHANGE_INCONSISTENT,
        spectral.precision_bits,
        "carrier transition branch-cell or deformation provenance differs",
    ))
    all(
        value -> _factored_precision_matches(
            value, spectral.precision_bits
        ),
        (
            transition.state.Y,
            transition.state.Yrho,
            transition.reconstruction_tolerance,
        ),
    ) || throw(_factored_error(
        T,
        FACTORED_PROPAGATION_PRECISION_MISMATCH,
        spectral.precision_bits,
        "carrier transition state or tolerance narrowed request precision",
    ))
    _finite_factored_complex(transition.state.Y) &&
        _finite_factored_complex(transition.state.Yrho) &&
        isfinite(transition.reconstruction_tolerance) &&
        transition.reconstruction_tolerance >= zero(T) &&
        transition.diagnostics.X_reconstruction_error <=
            transition.reconstruction_tolerance &&
        transition.diagnostics.Xrho_reconstruction_error <=
            transition.reconstruction_tolerance || throw(_factored_error(
                T,
                CARRIER_CHANGE_INCONSISTENT,
                spectral.precision_bits,
                "carrier transition fails its reconstruction evidence",
            ))
    return nothing
end

function _assert_successful_factored_ode_result(
    odesoln,
    ::Type{T},
    precision_bits::Int,
    assessment::AsymptoticConditioningAssessment{T},
    factored_homogeneous_rhs_evaluations::Int,
) where {T<:AbstractFloat}
    DifferentialEquations.SciMLBase.successful_retcode(odesoln) || throw(
        _factored_error(
            T,
            FACTORED_ODE_FAILURE,
            precision_bits,
            "factored ODE returned unsuccessful retcode $(odesoln.retcode)";
            assessment=assessment,
            factored_homogeneous_rhs_evaluations=
                factored_homogeneous_rhs_evaluations,
        )
    )
    return nothing
end

function _execute_factored_endpoint_after_readiness(
    spectral::HomogeneousSpectralContext{T},
    contour::ComplexContourContext{T},
    preparation::FactoredEndpointPreparation{T},
    start_rho::T,
    stop_rho::T;
    initial_state::FactoredEndpointState{T}=
        preparation.initial_condition.state,
    initial_carrier::PlaneWaveCarrier{T}=
        preparation.initial_condition.carrier,
    odealgo=_FACTORED_DEFAULTSOLVER,
    reltol::T=_factored_default_tolerance(T),
    abstol::T=_factored_default_tolerance(T),
    ode_maxiters::Int=10^7,
    verbose::Bool=false,
    ode_observation_factory=nothing,
    ode_solution_observer=nothing,
    ode_exception_passthrough=_never_passthrough_ode_exception,
    ode_leg::AbstractString="factored_endpoint",
    factored_homogeneous_rhs_counter::Base.RefValue{Int}=Ref(0),
) where {T<:AbstractFloat}
    return _with_factored_precision(T, spectral.precision_bits) do
    _assert_contour_context_provenance(spectral, contour)
    _assert_carrier_provenance(
        spectral,
        contour,
        initial_carrier,
        preparation.branch,
        "factored ODE seed",
    )
    all(
        value -> _factored_precision_matches(
            value, spectral.precision_bits
        ),
        (
            start_rho,
            stop_rho,
            reltol,
            abstol,
            initial_state.Y,
            initial_state.Yrho,
            initial_carrier.wave_number,
            initial_carrier.rstar_match,
            initial_carrier.log_at_match,
            initial_carrier.q,
        ),
    ) || throw(_factored_error(
        T,
        FACTORED_PROPAGATION_PRECISION_MISMATCH,
        spectral.precision_bits,
        "factored ODE seed or controls do not preserve context precision",
    ))
    all(isfinite, (start_rho, stop_rho, reltol, abstol)) || throw(
        _factored_error(
            T,
            NONFINITE_FACTORED_PROPAGATION_DATA,
            spectral.precision_bits,
            "factored ODE controls must be finite",
        )
    )
    start_rho != stop_rho || throw(_factored_error(
        T,
        INVALID_FACTORED_PROPAGATION_INPUT,
        spectral.precision_bits,
        "factored ODE interval must have nonzero length",
    ))
    reltol > zero(T) && abstol > zero(T) || throw(_factored_error(
        T,
        INVALID_FACTORED_PROPAGATION_INPUT,
        spectral.precision_bits,
        "factored ODE tolerances must be positive",
    ))
    ode_maxiters > 0 || throw(_factored_error(
        T,
        INVALID_FACTORED_PROPAGATION_INPUT,
        spectral.precision_bits,
        "factored ODE maxiters must be positive",
    ))
    _finite_factored_complex(initial_state.Y) &&
        _finite_factored_complex(initial_state.Yrho) || throw(
            _factored_error(
                T,
                NONFINITE_FACTORED_PROPAGATION_DATA,
                spectral.precision_bits,
                "factored ODE seed state is nonfinite",
            )
        )
    tangent = _branch_tangent(contour, initial_carrier.kind)
    _finite_factored_complex(tangent) && !iszero(tangent) || throw(
        _factored_error(
            T,
            NONFINITE_FACTORED_PROPAGATION_DATA,
            spectral.precision_bits,
            "factored ODE contour tangent is nonfinite or zero",
        )
    )
    initial_norm = hypot(abs(initial_state.Y), abs(initial_state.Yrho))
    initial_carrier_log = T(abs(real(carrier_log(
        initial_carrier, start_rho
    ))))
    isfinite(initial_norm) && isfinite(initial_carrier_log) || throw(
        _factored_error(
            T,
            NONFINITE_FACTORED_PROPAGATION_DATA,
            spectral.precision_bits,
            "factored ODE initial diagnostics are nonfinite",
        )
    )
    accumulator = _FactoredDiagnosticAccumulator{T}(
        0, initial_norm, initial_norm, initial_carrier_log
    )
    internal_callback = _factored_internal_callback(
        accumulator, initial_carrier
    )
    rhospan = (start_rho, stop_rho)
    external_callback, observation = _begin_ode_observation(
        ode_observation_factory, String(ode_leg), rhospan, odealgo
    )
    callback = _combine_factored_callbacks(
        external_callback, internal_callback
    )
    rhs_count_before = factored_homogeneous_rhs_counter[]
    parameters = FactoredGSNParameters(
        spectral.s,
        spectral.m,
        spectral.a,
        spectral.omega,
        spectral.lambda,
        contour.radius_from_rho,
        tangent,
        initial_carrier,
        spectral.precision_bits,
        rhs_count_before,
        factored_homogeneous_rhs_counter,
    )
    initial_values = Complex{T}[initial_state.Y, initial_state.Yrho]
    odeprob = ODEProblem(factored_GSN_linear_eqn!, initial_values, rhospan, parameters)
    odesoln = try
        solve(
            odeprob,
            odealgo;
            maxiters=ode_maxiters,
            reltol=reltol,
            abstol=abstol,
            tstops=[stop_rho],
            save_everystep=false,
            save_start=false,
            save_end=true,
            dense=false,
            callback=callback,
            verbose=verbose,
        )
    catch error
        _throw_or_wrap_factored_ode_failure(
            error,
            ode_exception_passthrough,
            T,
            spectral.precision_bits,
            preparation.assessment,
            _factored_rhs_evaluation_count(parameters),
        )
    end
    _finish_ode_observation(
        ode_solution_observer, String(ode_leg), odesoln, observation
    )
    _assert_successful_factored_ode_result(
        odesoln,
        T,
        spectral.precision_bits,
        preparation.assessment,
        _factored_rhs_evaluation_count(parameters),
    )
    isempty(odesoln.u) && throw(_factored_error(
        T,
        FACTORED_ODE_FAILURE,
        spectral.precision_bits,
        "factored ODE returned no saved endpoint";
        assessment=preparation.assessment,
        factored_homogeneous_rhs_evaluations=
            _factored_rhs_evaluation_count(parameters),
    ))
    length(odesoln.u) == 1 && length(odesoln.t) == 1 || throw(
        _factored_error(
            T,
            FACTORED_ODE_FAILURE,
            spectral.precision_bits,
            "factored ODE violated the endpoint-only save contract";
            assessment=preparation.assessment,
            factored_homogeneous_rhs_evaluations=
                _factored_rhs_evaluation_count(parameters),
        )
    )
    reached_rho = T(last(odesoln.t))
    endpoint_tolerance = T(64) * eps(T) * max(one(T), abs(stop_rho))
    abs(reached_rho - stop_rho) <= endpoint_tolerance || throw(
        _factored_error(
            T,
            FACTORED_ODE_FAILURE,
            spectral.precision_bits,
            "factored ODE did not reach the requested endpoint";
            assessment=preparation.assessment,
            factored_homogeneous_rhs_evaluations=
                _factored_rhs_evaluation_count(parameters),
        )
    )
    endpoint_values = last(odesoln.u)
    endpoint = FactoredEndpointState{T}(
        Complex{T}(endpoint_values[1]), Complex{T}(endpoint_values[2])
    )
    _finite_factored_complex(endpoint.Y) &&
        _finite_factored_complex(endpoint.Yrho) || throw(_factored_error(
            T,
            NONFINITE_FACTORED_PROPAGATION_DATA,
            spectral.precision_bits,
            "factored ODE endpoint state is nonfinite";
            assessment=preparation.assessment,
            factored_homogeneous_rhs_evaluations=
                _factored_rhs_evaluation_count(parameters),
        ))
    solver_stats = hasproperty(odesoln, :destats) ?
        getproperty(odesoln, :destats) : nothing
    accepted_steps = solver_stats !== nothing &&
        hasproperty(solver_stats, :naccept) ?
            Int(getproperty(solver_stats, :naccept)) :
            accumulator.accepted_steps
    rejected_steps = solver_stats !== nothing &&
        hasproperty(solver_stats, :nreject) ?
            Int(getproperty(solver_stats, :nreject)) : 0
    diagnostics = FactoredODEDiagnostics{T}(
        initial_carrier.kind,
        String(ode_leg),
        HOMOGENEOUS_REPRESENTATION_ID,
        FACTORED_HOMOGENEOUS_ODE_SCOPE_ID,
        spectral.precision_bits,
        accepted_steps,
        rejected_steps,
        accumulator.maximum_remainder_state_norm,
        accumulator.minimum_remainder_state_norm,
        accumulator.maximum_absolute_real_carrier_log,
        preparation.initial_condition.regularity,
        preparation.assessment,
        spectral.convention,
        preparation.frozen_branch_cell,
        preparation.contour_deformation,
        _factored_rhs_evaluation_count(parameters),
        length(odesoln.u),
    )
    return FactoredODESolution{T}(
        endpoint, initial_carrier, stop_rho, diagnostics
    )
    end
end

function solve_factored_endpoint(
    spectral::HomogeneousSpectralContext{T},
    contour::ComplexContourContext{T},
    preparation::FactoredEndpointPreparation{T},
    start_rho::T,
    stop_rho::T;
    odealgo=_FACTORED_DEFAULTSOLVER,
    reltol::Union{Nothing,T}=nothing,
    abstol::Union{Nothing,T}=nothing,
    ode_maxiters::Int=10^7,
    verbose::Bool=false,
    ode_observation_factory=nothing,
    ode_solution_observer=nothing,
    ode_exception_passthrough=_never_passthrough_ode_exception,
    ode_leg::AbstractString="factored_endpoint",
    factored_homogeneous_rhs_counter::Base.RefValue{Int}=Ref(0),
) where {T<:AbstractFloat}
    _assert_preparation_provenance(spectral, contour, preparation)
    _assert_factored_preflight_adequate(preparation)
    expected_start = preparation.branch === INFINITY_OUTGOING ?
        contour.rho_out : contour.rho_in
    start_rho == expected_start || throw(_factored_error(
        T,
        INVALID_FACTORED_PROPAGATION_INPUT,
        spectral.precision_bits,
        "factored endpoint solve must begin at its prepared endpoint",
    ))
    # TODO: [HUMAN MATH REVIEW REQUIRED — verify the branch-specific plane-wave carriers, the transformed complex-contour GSN equation, the carrier change at ρ=0, the factored horizon basis, and the Cinc/Cref determinant chart against the current GSN amplitude and branch conventions.]
    # TODO: [HUMAN MATH REVIEW REQUIRED — decide whether derivative stencils freeze only the GSN branch cell while allowing frequency-local contour angles, or freeze the full contour tangent and use q=±i z t_frozen; verify contour-deformation invariance before production activation.]
    typed_reltol = _resolve_factored_tolerance(
        T, spectral.precision_bits, reltol, "relative tolerance"
    )
    typed_abstol = _resolve_factored_tolerance(
        T, spectral.precision_bits, abstol, "absolute tolerance"
    )
    return _execute_factored_endpoint_after_readiness(
        spectral,
        contour,
        preparation,
        start_rho,
        stop_rho;
        odealgo=odealgo,
        reltol=typed_reltol,
        abstol=typed_abstol,
        ode_maxiters=ode_maxiters,
        verbose=verbose,
        ode_observation_factory=ode_observation_factory,
        ode_solution_observer=ode_solution_observer,
        ode_exception_passthrough=ode_exception_passthrough,
        ode_leg=ode_leg,
        factored_homogeneous_rhs_counter=
            factored_homogeneous_rhs_counter,
    )
end

function solve_factored_infinity_outer_to_match(
    spectral::HomogeneousSpectralContext{T},
    contour::ComplexContourContext{T},
    preparation::FactoredEndpointPreparation{T};
    ode_leg::AbstractString="Xup_outer_to_match",
    kwargs...,
) where {T<:AbstractFloat}
    preparation.branch === INFINITY_OUTGOING || throw(_factored_error(
        T,
        INVALID_FACTORED_PROPAGATION_INPUT,
        spectral.precision_bits,
        "outer-to-match path requires infinity-outgoing preparation",
    ))
    return solve_factored_endpoint(
        spectral,
        contour,
        preparation,
        contour.rho_out,
        zero(contour.rho_out);
        ode_leg=ode_leg,
        kwargs...,
    )
end

function change_factored_infinity_to_horizon_at_match(
    spectral::HomogeneousSpectralContext{T},
    contour::ComplexContourContext{T},
    state::FactoredEndpointState{T},
    source_carrier::PlaneWaveCarrier{T},
) where {T<:AbstractFloat}
    return _translate_factored_failure(
        T,
        spectral.precision_bits,
        "infinity-to-horizon carrier transition";
        argument_reason=CARRIER_CHANGE_INCONSISTENT,
    ) do
        _with_factored_precision(T, spectral.precision_bits) do
            _assert_contour_context_provenance(spectral, contour)
            _assert_carrier_provenance(
                spectral,
                contour,
                source_carrier,
                INFINITY_OUTGOING,
                "carrier change source",
            )
            _factored_precision_matches(
                state.Y, spectral.precision_bits
            ) && _factored_precision_matches(
                state.Yrho, spectral.precision_bits
            ) || throw(_factored_error(
                T,
                FACTORED_PROPAGATION_PRECISION_MISMATCH,
                spectral.precision_bits,
                "carrier-change state does not preserve request precision",
            ))
            _finite_factored_complex(state.Y) &&
                _finite_factored_complex(state.Yrho) || throw(
                    _factored_error(
                        T,
                        NONFINITE_FACTORED_PROPAGATION_DATA,
                        spectral.precision_bits,
                        "carrier-change state is nonfinite",
                    )
                )
            target_carrier = _canonical_carrier(
                spectral, contour, HORIZON_INGOING
            )
            target_state = change_carrier(
                state, source_carrier, target_carrier, zero(T)
            )
            diagnostics = carrier_change_diagnostics(
                state,
                target_state,
                source_carrier,
                target_carrier,
                zero(T),
            )
            raw = reconstruct_state(state, source_carrier, zero(T))
            scale = max(one(T), abs(raw.X), abs(raw.Xrho))
            tolerance = T(256) * eps(T) * scale
            diagnostics.X_reconstruction_error <= tolerance &&
                diagnostics.Xrho_reconstruction_error <= tolerance || throw(
                    _factored_error(
                        T,
                        CARRIER_CHANGE_INCONSISTENT,
                        spectral.precision_bits,
                        "carrier change failed the X/Xrho reconstruction invariant",
                    )
                )
            return FactoredCarrierTransition{T}(
                target_state,
                source_carrier,
                target_carrier,
                diagnostics,
                tolerance,
                spectral.frozen_branch_cell,
                spectral.contour_deformation,
            )
        end
    end
end

function change_factored_infinity_to_horizon_at_match(
    spectral::HomogeneousSpectralContext{T},
    contour::ComplexContourContext{T},
    propagated::FactoredODESolution{T},
) where {T<:AbstractFloat}
    _assert_factored_ode_solution_provenance(
        spectral,
        contour,
        propagated,
        INFINITY_OUTGOING,
        zero(T),
    )
    return change_factored_infinity_to_horizon_at_match(
        spectral, contour, propagated.endpoint, propagated.carrier
    )
end

function solve_factored_horizon_match_to_inner(
    spectral::HomogeneousSpectralContext{T},
    contour::ComplexContourContext{T},
    preparation::FactoredEndpointPreparation{T},
    transition::FactoredCarrierTransition{T};
    odealgo=_FACTORED_DEFAULTSOLVER,
    reltol::Union{Nothing,T}=nothing,
    abstol::Union{Nothing,T}=nothing,
    ode_maxiters::Int=10^7,
    verbose::Bool=false,
    ode_observation_factory=nothing,
    ode_solution_observer=nothing,
    ode_exception_passthrough=_never_passthrough_ode_exception,
    ode_leg::AbstractString="Xup_match_to_inner",
    factored_homogeneous_rhs_counter::Base.RefValue{Int}=Ref(0),
) where {T<:AbstractFloat}
    _assert_preparation_provenance(spectral, contour, preparation)
    _assert_factored_preflight_adequate(preparation)
    preparation.branch === HORIZON_INGOING || throw(_factored_error(
        T,
        INVALID_FACTORED_PROPAGATION_INPUT,
        spectral.precision_bits,
        "match-to-inner path requires horizon-ingoing preparation",
    ))
    _assert_carrier_transition_provenance(spectral, contour, transition)
    typed_reltol = _resolve_factored_tolerance(
        T, spectral.precision_bits, reltol, "relative tolerance"
    )
    typed_abstol = _resolve_factored_tolerance(
        T, spectral.precision_bits, abstol, "absolute tolerance"
    )
    return _execute_factored_endpoint_after_readiness(
        spectral,
        contour,
        preparation,
        zero(contour.rho_in),
        contour.rho_in;
        initial_state=transition.state,
        initial_carrier=transition.target_carrier,
        odealgo=odealgo,
        reltol=typed_reltol,
        abstol=typed_abstol,
        ode_maxiters=ode_maxiters,
        verbose=verbose,
        ode_observation_factory=ode_observation_factory,
        ode_solution_observer=ode_solution_observer,
        ode_exception_passthrough=ode_exception_passthrough,
        ode_leg=ode_leg,
        factored_homogeneous_rhs_counter=
            factored_homogeneous_rhs_counter,
    )
end

function solve_factored_xup_scattering_endpoint(
    spectral::HomogeneousSpectralContext{T},
    contour::ComplexContourContext{T},
    preparations::HorizonDeterminantPreparation{T};
    odealgo=_FACTORED_DEFAULTSOLVER,
    reltol::Union{Nothing,T}=nothing,
    abstol::Union{Nothing,T}=nothing,
    ode_maxiters::Int=10^7,
    verbose::Bool=false,
    ode_observation_factory=nothing,
    ode_solution_observer=nothing,
    ode_exception_passthrough=_never_passthrough_ode_exception,
    factored_homogeneous_rhs_counter::Base.RefValue{Int}=Ref(0),
) where {T<:AbstractFloat}
    _assert_horizon_preparation_provenance(
        spectral, contour, preparations
    )
    assert_factored_preflights_adequate(preparations)
    outer = solve_factored_infinity_outer_to_match(
        spectral,
        contour,
        preparations.infinity_outgoing;
        odealgo=odealgo,
        reltol=reltol,
        abstol=abstol,
        ode_maxiters=ode_maxiters,
        verbose=verbose,
        ode_observation_factory=ode_observation_factory,
        ode_solution_observer=ode_solution_observer,
        ode_exception_passthrough=ode_exception_passthrough,
        ode_leg="Xup_outer_to_match",
        factored_homogeneous_rhs_counter=
            factored_homogeneous_rhs_counter,
    )
    transition = change_factored_infinity_to_horizon_at_match(
        spectral, contour, outer
    )
    inner = solve_factored_horizon_match_to_inner(
        spectral,
        contour,
        preparations.horizon_ingoing,
        transition;
        odealgo=odealgo,
        reltol=reltol,
        abstol=abstol,
        ode_maxiters=ode_maxiters,
        verbose=verbose,
        ode_observation_factory=ode_observation_factory,
        ode_solution_observer=ode_solution_observer,
        ode_exception_passthrough=ode_exception_passthrough,
        ode_leg="Xup_match_to_inner",
        factored_homogeneous_rhs_counter=
            factored_homogeneous_rhs_counter,
    )
    return FactoredScatteringPropagation{T}(outer, transition, inner)
end

function solve_factored_xin_to_match(
    spectral::HomogeneousSpectralContext{T},
    contour::ComplexContourContext{T},
    preparation::FactoredEndpointPreparation{T};
    ode_leg::AbstractString="Xin_inner_to_match",
    kwargs...,
) where {T<:AbstractFloat}
    preparation.branch === HORIZON_INGOING || throw(_factored_error(
        T,
        INVALID_FACTORED_PROPAGATION_INPUT,
        spectral.precision_bits,
        "Xin-to-match path requires horizon-ingoing preparation",
    ))
    return solve_factored_endpoint(
        spectral,
        contour,
        preparation,
        contour.rho_in,
        zero(contour.rho_in);
        ode_leg=ode_leg,
        kwargs...,
    )
end

function solve_factored_xup_to_match(
    spectral::HomogeneousSpectralContext{T},
    contour::ComplexContourContext{T},
    preparation::FactoredEndpointPreparation{T};
    ode_leg::AbstractString="Xup_outer_to_match",
    kwargs...,
) where {T<:AbstractFloat}
    return solve_factored_infinity_outer_to_match(
        spectral, contour, preparation; ode_leg=ode_leg, kwargs...
    )
end

function solve_factored_exterior_matches(
    spectral::HomogeneousSpectralContext{T},
    contour::ComplexContourContext{T},
    preparations::ExteriorDeterminantPreparation{T};
    odealgo=_FACTORED_DEFAULTSOLVER,
    reltol::Union{Nothing,T}=nothing,
    abstol::Union{Nothing,T}=nothing,
    ode_maxiters::Int=10^7,
    verbose::Bool=false,
    ode_observation_factory=nothing,
    ode_solution_observer=nothing,
    ode_exception_passthrough=_never_passthrough_ode_exception,
    factored_homogeneous_rhs_counter::Base.RefValue{Int}=Ref(0),
) where {T<:AbstractFloat}
    _assert_exterior_preparation_provenance(
        spectral, contour, preparations
    )
    assert_factored_preflights_adequate(preparations)
    xin = solve_factored_xin_to_match(
        spectral,
        contour,
        preparations.horizon_ingoing;
        odealgo=odealgo,
        reltol=reltol,
        abstol=abstol,
        ode_maxiters=ode_maxiters,
        verbose=verbose,
        ode_observation_factory=ode_observation_factory,
        ode_solution_observer=ode_solution_observer,
        ode_exception_passthrough=ode_exception_passthrough,
        ode_leg="Xin_inner_to_match",
        factored_homogeneous_rhs_counter=
            factored_homogeneous_rhs_counter,
    )
    xup = solve_factored_xup_to_match(
        spectral,
        contour,
        preparations.infinity_outgoing;
        odealgo=odealgo,
        reltol=reltol,
        abstol=abstol,
        ode_maxiters=ode_maxiters,
        verbose=verbose,
        ode_observation_factory=ode_observation_factory,
        ode_solution_observer=ode_solution_observer,
        ode_exception_passthrough=ode_exception_passthrough,
        ode_leg="Xup_outer_to_match",
        factored_homogeneous_rhs_counter=
            factored_homogeneous_rhs_counter,
    )
    return FactoredExteriorMatches{T}(xin, xup)
end

function reconstruct_factored_match_state(
    state::FactoredEndpointState{T},
    carrier::PlaneWaveCarrier{T},
    rho::T,
    spectral::HomogeneousSpectralContext{T},
    contour::ComplexContourContext{T},
) where {T<:AbstractFloat}
    return _translate_factored_failure(
        T,
        spectral.precision_bits,
        "factored match-state reconstruction";
        argument_reason=CARRIER_CHANGE_INCONSISTENT,
    ) do
        _with_factored_precision(T, spectral.precision_bits) do
            _assert_contour_context_provenance(spectral, contour)
            _assert_carrier_provenance(
                spectral,
                contour,
                carrier,
                carrier.kind,
                "factored match state",
            )
            all(
                value -> _factored_precision_matches(
                    value, spectral.precision_bits
                ),
                (
                    state.Y,
                    state.Yrho,
                    carrier.wave_number,
                    carrier.rstar_match,
                    carrier.log_at_match,
                    carrier.q,
                    rho,
                ),
            ) || throw(_factored_error(
                T,
                FACTORED_PROPAGATION_PRECISION_MISMATCH,
                spectral.precision_bits,
                "factored match state does not preserve request precision",
            ))
            rho == zero(T) || throw(_factored_error(
                T,
                INVALID_FACTORED_PROPAGATION_INPUT,
                spectral.precision_bits,
                "factored match-state conversion is defined at rho=0",
            ))
            _finite_factored_complex(state.Y) &&
                _finite_factored_complex(state.Yrho) || throw(
                    _factored_error(
                        T,
                        NONFINITE_FACTORED_PROPAGATION_DATA,
                        spectral.precision_bits,
                        "factored match state is nonfinite",
                    )
                )
            raw = reconstruct_state(state, carrier, rho)
            tangent = _branch_tangent(contour, carrier.kind)
            _finite_factored_complex(tangent) && !iszero(tangent) || throw(
                _factored_error(
                    T,
                    INVALID_FACTORED_PROPAGATION_INPUT,
                    spectral.precision_bits,
                    "match-state contour tangent must be finite and nonzero",
                )
            )
            dX_drstar = raw.Xrho / tangent
            radial_derivative_convention =
                MATCH_RADIAL_DERIVATIVE_CONVENTION_ID
            _finite_factored_complex(raw.X) &&
                _finite_factored_complex(raw.Xrho) &&
                _finite_factored_complex(dX_drstar) || throw(
                    _factored_error(
                        T,
                        NONFINITE_FACTORED_PROPAGATION_DATA,
                        spectral.precision_bits,
                        "reconstructed match state or derivative is nonfinite",
                    )
                )
            return FactoredMatchState{T}(
                raw.X,
                raw.Xrho,
                dX_drstar,
                rho,
                carrier.kind,
                tangent,
                radial_derivative_convention,
            )
        end
    end
end

function reconstruct_factored_match_state(
    propagated::FactoredODESolution{T},
    spectral::HomogeneousSpectralContext{T},
    contour::ComplexContourContext{T},
) where {T<:AbstractFloat}
    _assert_factored_ode_solution_provenance(
        spectral,
        contour,
        propagated,
        propagated.carrier.kind,
        zero(T),
    )
    return reconstruct_factored_match_state(
        propagated.endpoint,
        propagated.carrier,
        propagated.endpoint_rho,
        spectral,
        contour,
    )
end

# Legacy raw-comparator equation
#####
##### Real-inner horizon contour, geometry gate, and horizon basis at match
#####
#
# The frequency-aligned negative contour is chosen so that the *infinity*
# carrier stays bounded; nothing forces it to approach r_plus.  For sufficiently
# damped modes it does the opposite and runs off toward complex infinity, which
# makes every horizon expansion evaluated on it meaningless.  The contour below
# is built for the horizon instead: it advances r_* along the positive real axis
# from the matching point, so r_* -> -infinity and therefore r -> r_plus from
# the exterior as rho becomes more negative.
#
#     r_*(rho) = rstar_match + rho,    dr_*/drho = 1,    rho < 0
#
# In the underlying coordinate ODE that is beta = 0, sign = +1, tangent = 1+0im.

const REAL_INNER_HORIZON_CONTOUR_ID = real_inner_horizon_contour_id
const DEFAULT_HORIZON_ENDPOINT_CANDIDATES = (-10, -25, -50, -75, -100)
const DEFAULT_MAXIMUM_HORIZON_DISTANCE = 0.1

struct RealInnerHorizonContour{T<:AbstractFloat,F}
    contour_id::String
    match_radius::T
    rstar_match::T
    rho_min::T
    tangent::Complex{T}
    radius_from_rho::F
    precision_bits::Int
    convention::GSNBranchConvention{T}
    frozen_branch_cell::GSNBranchCell
    contour_deformation::ContourAngleDeformation{T}
end

struct HorizonEndpointGeometryCandidate{T<:AbstractFloat}
    rho::T
    radius::Complex{T}
    horizon_distance::T
    imaginary_radius_abs::T
    exterior::Bool
    on_real_axis::Bool
    approaches_horizon::Bool
    within_maximum_distance::Bool
    contour_id::String
    precision_bits::Int
    frozen_branch_cell::GSNBranchCell
end

struct HorizonEndpointCandidate{T<:AbstractFloat}
    geometry::HorizonEndpointGeometryCandidate{T}
    ingoing_adequate::Bool
    outgoing_adequate::Bool
    ingoing_evaluation::Union{Nothing,SeriesEvaluation{T}}
    outgoing_evaluation::Union{Nothing,SeriesEvaluation{T}}
    ingoing_assessment::Union{Nothing,AsymptoticConditioningAssessment{T}}
    outgoing_assessment::Union{Nothing,AsymptoticConditioningAssessment{T}}
    endpoint_order::Union{Nothing,Int}
    attempted_endpoint_order::Union{Nothing,Int}
end

# Why a candidate failed decides what fixes it. A candidate whose series is
# still converging needs more order; one whose arithmetic has been eaten by
# cancellation needs more precision; one already past its optimal truncation at
# this radius needs a radius nearer the horizon, and neither more order nor
# more precision will move it.
const HORIZON_ENDPOINT_ADEQUATE = ENDPOINT_ADEQUATE
const HORIZON_ENDPOINT_ORDER_LIMITED = ENDPOINT_SERIES_ORDER_LIMITED
const HORIZON_ENDPOINT_PRECISION_LIMITED = ENDPOINT_ARITHMETIC_LIMITED
const HORIZON_ENDPOINT_GEOMETRY_LIMITED = ENDPOINT_GEOMETRY_LIMITED
const NO_GEOMETRY_VALID_CANDIDATE = "no-geometry-valid-candidate/v1"
const MAX_SERIES_ORDER_INADEQUATE = "maximum-series-order-inadequate/v1"
const ARITHMETIC_PRECISION_INADEQUATE = "arithmetic-precision-inadequate/v1"
const COORDINATE_INVERSION_FAILURE = "coordinate-inversion-failure/v1"
const FEWER_THAN_TWO_VERIFIED_ENDPOINTS =
    "fewer-than-two-verified-endpoints/v1"

function _describe_horizon_candidate(candidate::HorizonEndpointCandidate)
    geometry = candidate.geometry
    return string(
        "rho=", geometry.rho,
        " distance=", geometry.horizon_distance,
        " exterior=", geometry.exterior,
        " real_axis=", geometry.on_real_axis,
        " approaching=", geometry.approaches_horizon,
        " within_max=", geometry.within_maximum_distance,
        " ingoing=", candidate.ingoing_adequate,
        " outgoing=", candidate.outgoing_adequate,
    )
end

function _geometry_candidate_adequate(
    candidate::HorizonEndpointGeometryCandidate{T},
    maximum_horizon_distance::T,
) where {T<:AbstractFloat}
    return all(isfinite, (
            candidate.rho,
            real(candidate.radius),
            imag(candidate.radius),
            candidate.horizon_distance,
            candidate.imaginary_radius_abs,
        )) &&
        candidate.rho < zero(T) &&
        candidate.exterior &&
        candidate.on_real_axis &&
        candidate.approaches_horizon &&
        candidate.within_maximum_distance &&
        candidate.horizon_distance <= maximum_horizon_distance
end

function _candidate_adequate(
    candidate::HorizonEndpointCandidate{T},
    maximum_horizon_distance::T,
) where {T<:AbstractFloat}
    return _geometry_candidate_adequate(
            candidate.geometry, maximum_horizon_distance
        ) &&
        candidate.ingoing_adequate &&
        candidate.outgoing_adequate &&
        candidate.ingoing_evaluation !== nothing &&
        candidate.outgoing_evaluation !== nothing &&
        candidate.ingoing_assessment !== nothing &&
        candidate.outgoing_assessment !== nothing
end

function _branch_candidate_adequate(
    candidate::HorizonEndpointCandidate{T},
    maximum_horizon_distance::T,
    branch::CarrierKind,
) where {T<:AbstractFloat}
    _geometry_candidate_adequate(
        candidate.geometry, maximum_horizon_distance
    ) || return false
    if branch === HORIZON_INGOING
        return candidate.ingoing_adequate &&
            candidate.ingoing_evaluation !== nothing &&
            candidate.ingoing_assessment !== nothing
    elseif branch === HORIZON_OUTGOING
        return candidate.outgoing_adequate &&
            candidate.outgoing_evaluation !== nothing &&
            candidate.outgoing_assessment !== nothing
    end
    return false
end

"""
    horizon_endpoint_limitation(candidate, maximum_horizon_distance)

Name the single constraint that keeps `candidate` from being usable.
"""
function horizon_endpoint_limitation(
    candidate::HorizonEndpointCandidate{T},
    maximum_horizon_distance::T,
) where {T<:AbstractFloat}
    _geometry_candidate_adequate(
        candidate.geometry, maximum_horizon_distance
    ) || return HORIZON_ENDPOINT_GEOMETRY_LIMITED
    _candidate_adequate(candidate, maximum_horizon_distance) &&
        return HORIZON_ENDPOINT_ADEQUATE
    assessments = filter(
        !isnothing,
        (candidate.ingoing_assessment, candidate.outgoing_assessment),
    )
    isempty(assessments) && return HORIZON_ENDPOINT_GEOMETRY_LIMITED
    binding = argmin(
        assessment -> assessment.predicted_reliable_digits, assessments
    )
    return asymptotic_endpoint_limitation(binding)
end

"""One causal attempt for one factored exterior endpoint."""
struct SingleEndpointRecoveryCandidate{T<:AbstractFloat}
    endpoint_branch::String
    endpoint_order::Int
    geometry::T
    preparation::FactoredEndpointPreparation{T}
    payload::Any
    limitation::String
    selected_intervention::String
    result::String
end

"""Complete bounded same-tier recovery history for one endpoint branch."""
struct SingleEndpointRecovery{T<:AbstractFloat}
    endpoint_branch::String
    policy_identity::String
    endpoint_orders::Vector{Int}
    geometry_schedule::Vector{T}
    candidates::Vector{SingleEndpointRecoveryCandidate{T}}
    terminal::SingleEndpointRecoveryCandidate{T}
    outcome::String
    factored_homogeneous_rhs_evaluations::Int
end

"""
    recover_single_factored_endpoint(branch, orders, geometries, policy, prepare)

Run one bounded causal endpoint ladder without entering the homogeneous ODE.
`prepare(order, geometry)` returns `(preparation, payload)`, where `payload`
retains branch-specific contour data required if the candidate is selected.
"""
function recover_single_factored_endpoint(
    endpoint_branch::AbstractString,
    endpoint_orders::Vector{Int},
    geometry_schedule::Vector{T},
    policy_identity::AbstractString,
    prepare_candidate::F;
    factored_homogeneous_rhs_counter::Base.RefValue{Int}=Ref(0),
) where {T<:AbstractFloat,F}
    isempty(endpoint_orders) && throw(ArgumentError(
        "single-endpoint recovery order schedule must be nonempty"
    ))
    isempty(geometry_schedule) && throw(ArgumentError(
        "single-endpoint recovery geometry schedule must be nonempty"
    ))
    all(order -> order > 0, endpoint_orders) &&
        issorted(endpoint_orders) &&
        length(unique(endpoint_orders)) == length(endpoint_orders) ||
        throw(ArgumentError("single-endpoint recovery orders are invalid"))
    length(unique(geometry_schedule)) == length(geometry_schedule) ||
        throw(ArgumentError("single-endpoint recovery geometry is duplicated"))
    factored_homogeneous_rhs_counter[] == 0 || throw(ArgumentError(
        "single-endpoint recovery began after homogeneous RHS work"
    ))
    order_index = 1
    geometry_index = 1
    candidates = SingleEndpointRecoveryCandidate{T}[]
    while true
        order = endpoint_orders[order_index]
        geometry = geometry_schedule[geometry_index]
        preparation, payload = prepare_candidate(order, geometry)
        factored_homogeneous_rhs_counter[] == 0 || throw(ArgumentError(
            "homogeneous RHS executed during endpoint recovery"
        ))
        limitation = asymptotic_endpoint_limitation(preparation.assessment)
        intervention, result, terminal = if limitation == ENDPOINT_ADEQUATE
            ("ENTER_HOMOGENEOUS_ODE", "ADEQUATE", true)
        elseif limitation == ENDPOINT_SERIES_ORDER_LIMITED
            order_index < length(endpoint_orders) ?
                ("INCREASE_ENDPOINT_ORDER", "RETRY", false) :
                ("NONE", "ORDER_EXHAUSTED", true)
        elseif limitation == ENDPOINT_GEOMETRY_LIMITED
            geometry_index < length(geometry_schedule) ?
                ("DEEPEN_ENDPOINT_GEOMETRY", "RETRY", false) :
                ("NONE", "GEOMETRY_EXHAUSTED", true)
        elseif limitation == ENDPOINT_ARITHMETIC_LIMITED
            ("PROMOTE_ARITHMETIC_TIER_IF_AGGREGATE_ALLOWS",
             "ARITHMETIC_INADEQUATE", true)
        else
            throw(ArgumentError("unknown endpoint limitation"))
        end
        candidate = SingleEndpointRecoveryCandidate{T}(
            String(endpoint_branch), order, geometry, preparation, payload,
            limitation, intervention, result,
        )
        push!(candidates, candidate)
        terminal && return SingleEndpointRecovery{T}(
            String(endpoint_branch), String(policy_identity),
            copy(endpoint_orders), copy(geometry_schedule), candidates,
            candidate, limitation, factored_homogeneous_rhs_counter[],
        )
        if limitation == ENDPOINT_SERIES_ORDER_LIMITED
            order_index += 1
        else
            geometry_index += 1
            order_index = 1
        end
    end
end

"""Apply the determinant-wide mixed-blocker rule to endpoint limitations."""
function aggregate_endpoint_limitations(limitations)
    values = collect(limitations)
    isempty(values) && throw(ArgumentError(
        "endpoint limitation aggregate must be nonempty"
    ))
    all(==(ENDPOINT_ADEQUATE), values) && return ENDPOINT_ADEQUATE
    any(==(ENDPOINT_SERIES_ORDER_LIMITED), values) &&
        return ENDPOINT_SERIES_ORDER_LIMITED
    any(==(ENDPOINT_GEOMETRY_LIMITED), values) &&
        return ENDPOINT_GEOMETRY_LIMITED
    all(value -> value in (ENDPOINT_ADEQUATE, ENDPOINT_ARITHMETIC_LIMITED), values) &&
        any(==(ENDPOINT_ARITHMETIC_LIMITED), values) &&
        return ENDPOINT_ARITHMETIC_LIMITED
    throw(ArgumentError("endpoint limitation aggregate is inconsistent"))
end

function _single_endpoint_attempt_evidence(candidate)
    assessment = candidate.preparation.assessment
    return Dict{String,Any}(
        "endpoint_branch" => candidate.endpoint_branch,
        "attempted_endpoint_order" => candidate.endpoint_order,
        "attempted_geometry" => string(candidate.geometry),
        "maximum_last_term_ratio" => string(assessment.maximum_last_term_ratio),
        "maximum_truncation_digits_lost" =>
            string(assessment.maximum_truncation_digits_lost),
        "maximum_recurrence_digits_lost" =>
            string(assessment.maximum_recurrence_digits_lost),
        "maximum_series_evaluation_digits_lost" =>
            string(assessment.maximum_series_evaluation_digits_lost),
        "predicted_reliable_digits" =>
            string(assessment.predicted_reliable_digits),
        "required_reliable_digits" => string(assessment.required_digits),
        "candidate_limitation" => candidate.limitation,
        "selected_intervention" => candidate.selected_intervention,
        "result" => candidate.result,
    )
end

"""Return the complete terminal receipt crossing the Julia/Python boundary."""
function canonical_single_endpoint_recovery_evidence(
    recovery::SingleEndpointRecovery;
    aggregate_limitation::AbstractString=recovery.outcome,
)
    attempts = [_single_endpoint_attempt_evidence(candidate)
                for candidate in recovery.candidates]
    terminal = recovery.terminal.preparation.assessment
    return Dict{String,Any}(
        "schema" => "windows-solver.exterior-endpoint-recovery-receipt/1",
        "endpoint_branch" => recovery.endpoint_branch,
        "recovery_policy_identity" => recovery.policy_identity,
        "base_endpoint_order" => first(recovery.endpoint_orders),
        "generated_maximum_order" => last(recovery.endpoint_orders),
        "attempted_endpoint_orders" =>
            [candidate.endpoint_order for candidate in recovery.candidates],
        "terminal_endpoint_order" => recovery.terminal.endpoint_order,
        "candidate_geometry_schedule" => string.(recovery.geometry_schedule),
        "terminal_geometry" => string(recovery.terminal.geometry),
        "maximum_last_term_ratio" => string(maximum(
            candidate.preparation.assessment.maximum_last_term_ratio
            for candidate in recovery.candidates
        )),
        "maximum_truncation_digits_lost" => string(maximum(
            candidate.preparation.assessment.maximum_truncation_digits_lost
            for candidate in recovery.candidates
        )),
        "maximum_recurrence_digits_lost" => string(maximum(
            candidate.preparation.assessment.maximum_recurrence_digits_lost
            for candidate in recovery.candidates
        )),
        "maximum_series_evaluation_digits_lost" => string(maximum(
            candidate.preparation.assessment.maximum_series_evaluation_digits_lost
            for candidate in recovery.candidates
        )),
        "predicted_reliable_digits" => string(terminal.predicted_reliable_digits),
        "required_reliable_digits" => string(terminal.required_digits),
        "candidate_limitation" => recovery.outcome,
        "aggregate_limitation" => String(aggregate_limitation),
        "factored_homogeneous_rhs_evaluations" =>
            recovery.factored_homogeneous_rhs_evaluations,
        "attempts" => attempts,
    )
end

"""
    diagnose_horizon_endpoint_limitation(candidates, maximum_horizon_distance)

Name the constraint binding the candidate set as a whole.

Two adequate endpoints are required, so the diagnosis describes why the set
cannot supply them. The remedy is read from the candidate that came closest to
passing: it is the one a single change of order, precision, or depth is most
likely to move.
"""
function diagnose_horizon_endpoint_limitation(
    candidates::Vector{HorizonEndpointCandidate{T}},
    maximum_horizon_distance::T,
) where {T<:AbstractFloat}
    adequate = count(
        candidate -> _candidate_adequate(candidate, maximum_horizon_distance),
        candidates,
    )
    adequate >= 2 && return HORIZON_ENDPOINT_ADEQUATE
    reachable = filter(
        candidate -> _geometry_candidate_adequate(
                candidate.geometry, maximum_horizon_distance
            ) &&
            !_candidate_adequate(candidate, maximum_horizon_distance) &&
            candidate.ingoing_assessment !== nothing &&
            candidate.outgoing_assessment !== nothing,
        candidates,
    )
    isempty(reachable) && return HORIZON_ENDPOINT_GEOMETRY_LIMITED
    best = argmax(
        candidate -> min(
            candidate.ingoing_assessment.predicted_reliable_digits,
            candidate.outgoing_assessment.predicted_reliable_digits,
        ),
        reachable,
    )
    return horizon_endpoint_limitation(best, maximum_horizon_distance)
end

"""
    horizon_endpoint_order_ladder(base_order; maximum_order)

The endpoint series orders tried at one radius, coarsest first.

Doubling keeps the ladder short: each extra entry costs a full series
evaluation, and the search stops at the first adequate order anyway.
"""
function horizon_endpoint_order_ladder(
    base_order::Integer; maximum_order::Integer=4 * base_order
)
    base_order > 0 || throw(ArgumentError(
        "horizon endpoint base order must be positive"
    ))
    maximum_order >= base_order || throw(ArgumentError(
        "horizon endpoint maximum order must not precede the base order"
    ))
    orders = Int[]
    order = Int(base_order)
    while order < maximum_order
        push!(orders, order)
        order += order
    end
    push!(orders, Int(maximum_order))
    return orders
end

"""
    deepen_horizon_endpoint_rho_candidates(candidates, floor_rho)

Extend the endpoint candidate depths toward the declared coordinate floor.

Moving the expansion point closer to the horizon shrinks the series parameter,
so a deeper candidate repairs both a geometry that never came within the
maximum horizon distance and a series that simply needed more terms.

Returns `nothing` once the floor has been reached, which is how the caller
learns that no further depth is available and the failure is real.
"""
function deepen_horizon_endpoint_rho_candidates(
    candidates::Vector{T},
    floor_rho::T;
    growth::T=T(3) / T(2),
    added::Int=2,
) where {T<:AbstractFloat}
    isempty(candidates) && return nothing
    growth > one(T) || throw(ArgumentError(
        "horizon endpoint depth growth must exceed one"
    ))
    floor_rho < zero(T) || throw(ArgumentError(
        "horizon endpoint coordinate floor must be negative"
    ))
    deepest = minimum(candidates)
    deepest <= floor_rho && return nothing
    extended = copy(candidates)
    current = deepest
    for _ in 1:added
        current = current * growth
        current < floor_rho && (current = floor_rho)
        current in extended || push!(extended, current)
        current == floor_rho && break
    end
    length(extended) == length(candidates) && return nothing
    return sort(extended; rev=true)
end

function horizon_endpoint_prefix_orders(
    maximum_order::Int;
    minimum_order::Int=4,
    order_step::Int=4,
)
    maximum_order >= minimum_order || throw(ArgumentError(
        "horizon prefix maximum order is below the minimum"
    ))
    order_step > 0 || throw(ArgumentError(
        "horizon prefix order step must be positive"
    ))
    orders = collect(minimum_order:order_step:maximum_order)
    orders[end] == maximum_order || push!(orders, maximum_order)
    return orders
end


function select_horizon_endpoint_best_prefix(
    series,
    radius,
    required_digits::T,
    orders::Vector{Int},
) where {T<:AbstractFloat}
    best_order = nothing
    best_evaluation = nothing
    best_assessment = nothing
    for order in orders
        evaluation = evaluate_horizon_asymptotic_series(
            series, radius; order=order
        )
        # These are the actual scaled terminal terms and cancellation/spread
        # diagnostics produced by the package evaluator. Ingoing and outgoing
        # branches call this selector independently; no prefix is inferred
        # from the total series value alone.
        scaled_term_magnitudes = (
            evaluation.last_term_magnitude,
            evaluation.derivative_last_term_magnitude,
        )
        cancellation = evaluation.maximum_recurrence_cancellation_factor
        last_term = maximum(scaled_term_magnitudes)
        all(isfinite, (last_term, cancellation)) || continue
        assessment = assess_asymptotic_preflight(
            series, evaluation, required_digits
        )
        if best_assessment === nothing ||
            assessment.predicted_reliable_digits >
                best_assessment.predicted_reliable_digits
            best_order = order
            best_evaluation = evaluation
            best_assessment = assessment
        end
        # The recurrence was generated once in `series` to its maximum order.
        # Evaluate the full schedule so later asymptotic growth cannot displace
        # an earlier least-term prefix with the larger reliable-digit score.
    end
    return best_order, best_evaluation, best_assessment
end

const _best_prefix_assessment = select_horizon_endpoint_best_prefix

struct RealInnerHorizonEndpoint{T<:AbstractFloat}
    branch::CarrierKind
    state::FactoredEndpointState{T}
    carrier::PlaneWaveCarrier{T}
    rho::T
    radius::Complex{T}
    horizon_distance::T
    assessment::AsymptoticConditioningAssessment{T}
    regularity::RemainderRegularityEvidence{T}
    required_digits::T
    precision_bits::Int
    endpoint_order::Int
    contour_id::String
    frozen_branch_cell::GSNBranchCell
    contour_deformation::ContourAngleDeformation{T}
end

function _real_inner_endpoint_regularity(
    branch::CarrierKind,
    state::FactoredEndpointState{T},
    carrier::PlaneWaveCarrier{T},
    rho::T,
    radius::Complex{T},
) where {T<:AbstractFloat}
    raw = reconstruct_state(state, carrier, rho)
    recovered = factor_state(raw.X, raw.Xrho, carrier, rho)
    carrier_magnitude = abs(carrier_value(carrier, rho))
    remainder_norm = abs(state.Y)
    remainder_derivative_norm = abs(state.Yrho)
    y_scale = max(remainder_norm, floatmin(T))
    yrho_scale = max(remainder_derivative_norm, floatmin(T))
    relative_X_error = abs(recovered.Y - state.Y) / y_scale
    relative_Xrho_error = abs(recovered.Yrho - state.Yrho) / yrho_scale
    # The Yrho recovery subtracts q*Y, so its backward residual is measured
    # against the scale that subtraction actually operates on.
    backward_scale = max(
        remainder_derivative_norm,
        abs(carrier_log_derivative(carrier)) * remainder_norm,
        floatmin(T),
    )
    backward_residual = abs(recovered.Yrho - state.Yrho) / backward_scale
    carrier_operation_scale = max(
        one(T),
        abs(carrier_log_derivative(carrier)) * max(abs(rho), one(T)),
    )
    reconstruction_tolerance = T(256) * eps(T) * carrier_operation_scale
    finite = all(
        isfinite,
        (
            carrier_magnitude,
            remainder_norm,
            remainder_derivative_norm,
            relative_X_error,
            relative_Xrho_error,
            backward_residual,
        ),
    )
    return RemainderRegularityEvidence{T}(
        branch,
        rho,
        radius,
        finite,
        remainder_norm,
        remainder_derivative_norm,
        carrier_magnitude,
        relative_X_error,
        relative_Xrho_error,
        backward_residual,
        carrier_operation_scale,
        reconstruction_tolerance,
    )
end

struct VerifiedHorizonEndpoints{T<:AbstractFloat}
    reference::HorizonEndpointCandidate{T}
    verification::HorizonEndpointCandidate{T}
    candidates::Vector{HorizonEndpointCandidate{T}}
    maximum_horizon_distance::T
    contour_id::String
end

struct VerifiedHorizonBasisSolution{T<:AbstractFloat}
    ingoing::FactoredODESolution{T}
    outgoing::FactoredODESolution{T}
    ingoing_endpoint::RealInnerHorizonEndpoint{T}
    outgoing_endpoint::RealInnerHorizonEndpoint{T}
    rho_endpoint::T
    horizon_distance::T
end

"""
    build_outer_contour_context(spectral, match_radius, rstar_match, rho_out,
                                radius_from_rho)

Build the contour context used by the infinity-outgoing leg alone.

This is [`build_contour_context`] restricted to the outer half of the map. The
horizon determinant no longer shares one joined `rho_in < 0 < rho_out` contour
with the infinity leg, so the outer context is constructed with a nominal
negative endpoint that no horizon preparation reads.
"""
function build_outer_contour_context(
    spectral::HomogeneousSpectralContext{T},
    match_radius::T,
    rstar_match::T,
    rho_out::T,
    radius_from_rho::F,
) where {T<:AbstractFloat,F}
    rho_out > zero(T) || throw(ArgumentError(
        "outer contour requires a positive rho_out"
    ))
    return build_contour_context(
        spectral,
        match_radius,
        rstar_match,
        -rho_out,
        rho_out,
        radius_from_rho,
    )
end

"""
    build_real_inner_horizon_contour(spectral, match_radius, rho_min,
                                     radius_from_rho)

Build the horizon-side contour whose radial map genuinely approaches `r_plus`.

`radius_from_rho` must be the solution of the coordinate ODE taken with
`beta = 0` and `sign = +1`, so that `r_*(rho) = rstar_match + rho`. The
constructed context is validated the same way the joined contour is: the
supplied `rstar_match` must equal `rstar_from_r(a, match_radius)` exactly, and
`radius_from_rho(0)` must reproduce `match_radius`.

No horizon expansion may be evaluated on a contour built any other way; that is
what [`horizon_endpoint_candidates`] and [`select_verified_horizon_endpoints`]
enforce before any homogeneous ODE is started.
"""
function build_real_inner_horizon_contour(
    spectral::HomogeneousSpectralContext{T},
    match_radius::T,
    rstar_match::T,
    rho_min::T,
    radius_from_rho::F,
) where {T<:AbstractFloat,F}
    return _translate_factored_failure(
        T,
        spectral.precision_bits,
        "real-inner horizon contour construction",
    ) do
        _with_factored_precision(T, spectral.precision_bits) do
            _assert_spectral_context_provenance(spectral)
            all(isfinite, (match_radius, rstar_match, rho_min)) ||
                throw(ArgumentError(
                    "real-inner contour scalars must be finite"
                ))
            all(
                value -> _factored_precision_matches(
                    value, spectral.precision_bits
                ),
                (match_radius, rstar_match, rho_min),
            ) || throw(ArgumentError(
                "real-inner contour scalars do not preserve spectral precision"
            ))
            rho_min < zero(T) || throw(ArgumentError(
                "real-inner horizon contour requires rho_min < 0"
            ))
            geometry = stable_horizon_geometry(spectral.a)
            match_radius > geometry.rplus || throw(ArgumentError(
                "match radius must lie outside the outer horizon"
            ))
            canonical_rstar_match = T(rstar_from_r(
                spectral.a, match_radius
            ))
            _exact_factored_value(
                rstar_match, canonical_rstar_match
            ) || throw(ArgumentError(
                "rstar_match must equal Coordinates.rstar_from_r(a, match_radius)"
            ))
            raw_match_radius = radius_from_rho(zero(T))
            typed_match_radius = Complex{T}(raw_match_radius)
            _finite_factored_complex(typed_match_radius) ||
                throw(ArgumentError(
                    "real-inner radius_from_rho returned a nonfinite match radius"
                ))
            _factored_precision_matches(
                typed_match_radius, spectral.precision_bits
            ) || throw(ArgumentError(
                "real-inner radius_from_rho narrowed the match-radius precision"
            ))
            match_radius_tolerance = T(256) * eps(T) *
                max(one(T), abs(match_radius))
            abs(
                typed_match_radius - complex(match_radius, zero(T))
            ) <= match_radius_tolerance || throw(ArgumentError(
                "real-inner radius_from_rho(0) does not reproduce match_radius"
            ))
            tangent = complex(one(T), zero(T))
            return RealInnerHorizonContour{T,F}(
                REAL_INNER_HORIZON_CONTOUR_ID,
                match_radius,
                canonical_rstar_match,
                rho_min,
                tangent,
                radius_from_rho,
                spectral.precision_bits,
                spectral.convention,
                spectral.frozen_branch_cell,
                spectral.contour_deformation,
            )
        end
    end
end

"""
    horizon_endpoint_geometry_candidates(spectral, contour;
                                         rho_candidates,
                                         maximum_horizon_distance)

Screen the bounded horizon endpoint set using radial geometry alone.

For each candidate `rho` the radial map is sampled and its approach to the
horizon is recorded. This phase owns no asymptotic series and cannot invoke a
series assessment. A candidate passes the geometry gate only when all of the
following hold:

  * `rho < 0`
  * `Re(r) > r_plus`  — the endpoint is still exterior
  * `|Im(r)|` is negligible against the horizon distance — the real-inner
    contour must not have wandered off the real axis
  * `|r - r_plus|` decreases as `rho` becomes more negative
  * `|r - r_plus| <= maximum_horizon_distance`

The result carries contour provenance so a later series phase cannot assess a
candidate from another contour, precision, or branch cell.
"""
function horizon_endpoint_geometry_candidates(
    spectral::HomogeneousSpectralContext{T},
    contour::RealInnerHorizonContour{T};
    rho_candidates=DEFAULT_HORIZON_ENDPOINT_CANDIDATES,
    maximum_horizon_distance::T=T(DEFAULT_MAXIMUM_HORIZON_DISTANCE),
) where {T<:AbstractFloat}
    return _translate_factored_failure(
        T,
        spectral.precision_bits,
        "horizon endpoint geometry evaluation",
    ) do
        _with_factored_precision(T, spectral.precision_bits) do
            _assert_real_inner_contour_provenance(spectral, contour)
            isfinite(maximum_horizon_distance) &&
                maximum_horizon_distance > zero(T) ||
                throw(ArgumentError(
                    "maximum horizon distance must be finite and positive"
                ))
            isempty(rho_candidates) && throw(ArgumentError(
                "horizon endpoint candidate set must be nonempty"
            ))
            geometry = stable_horizon_geometry(spectral.a)
            rplus = complex(T(geometry.rplus), zero(T))
            ordered = sort(collect(T.(rho_candidates)); rev=true)
            candidates = Vector{HorizonEndpointGeometryCandidate{T}}()
            previous_distance = T(Inf)
            for rho in ordered
                isfinite(rho) && rho < zero(T) || throw(ArgumentError(
                    "horizon endpoint candidates must be finite and negative"
                ))
                rho >= contour.rho_min || throw(ArgumentError(
                    "horizon endpoint candidate lies beyond the contour rho_min"
                ))
                radius = Complex{T}(contour.radius_from_rho(rho))
                _finite_factored_complex(radius) || throw(_factored_error(
                    T,
                    NONFINITE_FACTORED_PROPAGATION_DATA,
                    spectral.precision_bits,
                    "real-inner radial map returned a nonfinite radius",
                ))
                horizon_distance = abs(radius - rplus)
                imaginary_radius_abs = abs(imag(radius))
                exterior = real(radius) > T(geometry.rplus)
                # The real-inner contour is real by construction, so any
                # imaginary part is numerical drift.  Compare it against the
                # horizon distance rather than an absolute floor so the test
                # stays meaningful as the endpoint approaches r_plus.
                on_real_axis = imaginary_radius_abs <=
                    sqrt(eps(T)) * max(horizon_distance, one(T))
                approaches_horizon = horizon_distance < previous_distance
                within_maximum_distance =
                    horizon_distance <= maximum_horizon_distance
                push!(candidates, HorizonEndpointGeometryCandidate{T}(
                    rho,
                    radius,
                    horizon_distance,
                    imaginary_radius_abs,
                    exterior,
                    on_real_axis,
                    approaches_horizon,
                    within_maximum_distance,
                    contour.contour_id,
                    contour.precision_bits,
                    contour.frozen_branch_cell,
                ))
                previous_distance = horizon_distance
            end
            return candidates
        end
    end
end

function _assert_horizon_geometry_candidate_provenance(
    spectral::HomogeneousSpectralContext{T},
    contour::RealInnerHorizonContour{T},
    candidate::HorizonEndpointGeometryCandidate{T},
) where {T<:AbstractFloat}
    candidate.contour_id == contour.contour_id || throw(_factored_error(
        T,
        INVALID_FACTORED_PROPAGATION_INPUT,
        spectral.precision_bits,
        "horizon geometry candidate changed contour identity",
    ))
    candidate.precision_bits == contour.precision_bits || throw(
        _factored_error(
            T,
            FACTORED_PROPAGATION_PRECISION_MISMATCH,
            spectral.precision_bits,
            "horizon geometry candidate changed contour precision",
        )
    )
    candidate.frozen_branch_cell == contour.frozen_branch_cell || throw(
        _factored_error(
            T,
            INVALID_FACTORED_PROPAGATION_INPUT,
            spectral.precision_bits,
            "horizon geometry candidate changed the frozen branch cell",
        )
    )
    return nothing
end


"""
    horizon_endpoint_candidates(spectral, contour, geometry_candidates,
                                required_digits; maximum_horizon_distance)

Assess horizon series only for candidates that already pass the radial gate.

Geometry failures remain in the returned vector with absent series evidence so
their rejection is diagnosable, but neither the ingoing nor outgoing horizon
series is evaluated for them. The configured maximum distance is checked again
against the measured distance rather than trusting the stored boolean verdict.
"""
function horizon_endpoint_candidates(
    spectral::HomogeneousSpectralContext{T},
    contour::RealInnerHorizonContour{T},
    geometry_candidates::Vector{HorizonEndpointGeometryCandidate{T}},
    required_digits::T;
    maximum_horizon_distance::T=T(DEFAULT_MAXIMUM_HORIZON_DISTANCE),
    endpoint_orders::Union{Nothing,Vector{Int}}=nothing,
    attempted_endpoint_order::Union{Nothing,Int}=nothing,
) where {T<:AbstractFloat}
    return _translate_factored_failure(
        T,
        spectral.precision_bits,
        "horizon endpoint series evaluation",
    ) do
        _with_factored_precision(T, spectral.precision_bits) do
            _assert_real_inner_contour_provenance(spectral, contour)
            isfinite(maximum_horizon_distance) &&
                maximum_horizon_distance > zero(T) ||
                throw(ArgumentError(
                    "maximum horizon distance must be finite and positive"
                ))
            isempty(geometry_candidates) && throw(ArgumentError(
                "horizon endpoint geometry candidate set must be nonempty"
            ))
            ingoing_series = _branch_series(
                spectral.series, HORIZON_INGOING
            )
            outgoing_series = _branch_series(
                spectral.series, HORIZON_OUTGOING
            )
            orders = endpoint_orders === nothing ?
                Int[spectral.endpoint_order] : endpoint_orders
            attempted_order = attempted_endpoint_order === nothing ?
                last(orders) : attempted_endpoint_order
            attempted_order == last(orders) || throw(ArgumentError(
                "attempted endpoint order must equal the generated prefix maximum"
            ))
            candidates = Vector{HorizonEndpointCandidate{T}}()
            for geometry_candidate in geometry_candidates
                _assert_horizon_geometry_candidate_provenance(
                    spectral, contour, geometry_candidate
                )
                geometry_adequate = _geometry_candidate_adequate(
                    geometry_candidate, maximum_horizon_distance
                )
                if !geometry_adequate
                    push!(candidates, HorizonEndpointCandidate{T}(
                        geometry_candidate,
                        false,
                        false,
                        nothing,
                        nothing,
                        nothing,
                        nothing,
                        nothing,
                        nothing,
                    ))
                    continue
                end
                radius = geometry_candidate.radius
                ingoing_order, ingoing_evaluation, ingoing_assessment =
                    _best_prefix_assessment(
                        ingoing_series, radius, required_digits, orders
                    )
                outgoing_order, outgoing_evaluation, outgoing_assessment =
                    _best_prefix_assessment(
                        outgoing_series, radius, required_digits, orders
                    )
                if ingoing_assessment === nothing || outgoing_assessment === nothing
                    push!(candidates, HorizonEndpointCandidate{T}(
                        geometry_candidate,
                        false,
                        false,
                        ingoing_evaluation,
                        outgoing_evaluation,
                        ingoing_assessment,
                        outgoing_assessment,
                        nothing,
                        attempted_order,
                    ))
                    continue
                end
                push!(candidates, HorizonEndpointCandidate{T}(
                    geometry_candidate,
                    ingoing_assessment.adequate,
                    outgoing_assessment.adequate,
                    ingoing_evaluation,
                    outgoing_evaluation,
                    ingoing_assessment,
                    outgoing_assessment,
                    max(ingoing_order, outgoing_order),
                    attempted_order,
                ))
            end
            return candidates
        end
    end
end

struct HorizonEndpointRecovery{T<:AbstractFloat}
    outcome::String
    selected_pair::Vector{HorizonEndpointCandidate{T}}
    candidates::Vector{HorizonEndpointCandidate{T}}
    geometry_schedule::Vector{HorizonEndpointGeometryCandidate{T}}
    endpoint_orders::Vector{Int}
    policy_identity::String
    maximum_horizon_distance::T
    homogeneous_rhs_evaluations_before_pair::Int
end

function _horizon_recovery_outcome(
    candidates::Vector{HorizonEndpointCandidate{T}},
    maximum_horizon_distance::T,
) where {T<:AbstractFloat}
    geometry_valid = filter(
        candidate -> _geometry_candidate_adequate(
            candidate.geometry, maximum_horizon_distance
        ),
        candidates,
    )
    isempty(geometry_valid) && return NO_GEOMETRY_VALID_CANDIDATE
    adequate = filter(
        candidate -> _candidate_adequate(
            candidate, maximum_horizon_distance
        ),
        geometry_valid,
    )
    length(adequate) == 1 && return FEWER_THAN_TWO_VERIFIED_ENDPOINTS
    any(
        candidate -> horizon_endpoint_limitation(
            candidate, maximum_horizon_distance
        ) == HORIZON_ENDPOINT_PRECISION_LIMITED,
        geometry_valid,
    ) && return ARITHMETIC_PRECISION_INADEQUATE
    return MAX_SERIES_ORDER_INADEQUATE
end

"""
    recover_verified_horizon_endpoint_pair(...)

Exhaust the complete depth schedule at one order before raising the order.
Geometry is cached once and geometry-invalid radii are never retried. The two
horizon branches retain their independently selected best prefixes, and no
homogeneous RHS work is admitted through this preflight-only function.
"""
function recover_verified_horizon_endpoint_pair(
    spectral::HomogeneousSpectralContext{T},
    contour::RealInnerHorizonContour{T},
    geometry_schedule::Vector{HorizonEndpointGeometryCandidate{T}},
    required_digits::T;
    maximum_horizon_distance::T=T(DEFAULT_MAXIMUM_HORIZON_DISTANCE),
    endpoint_orders::Vector{Int}=Int[spectral.endpoint_order],
    prefix_minimum_order::Int=4,
    prefix_order_step::Int=4,
    policy_identity::AbstractString,
) where {T<:AbstractFloat}
    isempty(endpoint_orders) && throw(ArgumentError(
        "horizon endpoint order schedule must be nonempty"
    ))
    issorted(endpoint_orders) || throw(ArgumentError(
        "horizon endpoint order schedule must be increasing"
    ))
    geometry_cache = Dict(
        geometry.rho => geometry for geometry in geometry_schedule
    )
    geometry_invalid_rhos = Set(
        geometry.rho for geometry in geometry_schedule
        if !_geometry_candidate_adequate(geometry, maximum_horizon_distance)
    )
    trials = HorizonEndpointCandidate{T}[]
    for geometry in geometry_schedule
        geometry.rho in geometry_invalid_rhos || continue
        push!(trials, HorizonEndpointCandidate{T}(
            geometry, false, false, nothing, nothing, nothing, nothing,
            nothing, nothing
        ))
    end
    verified_by_rho = Dict{T,HorizonEndpointCandidate{T}}()
    for endpoint_order in endpoint_orders
        # Depth is the inner loop: every usable radius is attempted at this
        # order before the next order is considered.
        for geometry in geometry_schedule
            geometry.rho in geometry_invalid_rhos && continue
            haskey(geometry_cache, geometry.rho) || error(
                "horizon endpoint geometry cache lost a declared radius"
            )
            haskey(verified_by_rho, geometry.rho) && continue
            assessed = horizon_endpoint_candidates(
                spectral,
                contour,
                HorizonEndpointGeometryCandidate{T}[geometry],
                required_digits;
                maximum_horizon_distance=maximum_horizon_distance,
                endpoint_orders=horizon_endpoint_prefix_orders(
                    endpoint_order;
                    minimum_order=prefix_minimum_order,
                    order_step=prefix_order_step,
                ),
                attempted_endpoint_order=endpoint_order,
            )[1]
            push!(trials, assessed)
            ingoing_best_prefix_order = assessed.ingoing_evaluation === nothing ?
                nothing : assessed.ingoing_evaluation.order
            outgoing_best_prefix_order = assessed.outgoing_evaluation === nothing ?
                nothing : assessed.outgoing_evaluation.order
            if _candidate_adequate(assessed, maximum_horizon_distance)
                verified_by_rho[geometry.rho] = assessed
            end
            # The independent names above are intentionally retained at this
            # boundary for canonical evidence and static schema review.
            (ingoing_best_prefix_order, outgoing_best_prefix_order)
        end
        if length(verified_by_rho) >= 2
            selected_pair = sort!(
                collect(values(verified_by_rho));
                by=candidate -> candidate.geometry.rho,
                rev=true,
            )[1:2]
            return HorizonEndpointRecovery{T}(
                HORIZON_ENDPOINT_ADEQUATE,
                selected_pair,
                trials,
                copy(geometry_schedule),
                copy(endpoint_orders),
                String(policy_identity),
                maximum_horizon_distance,
                0,
            )
        end
    end
    return HorizonEndpointRecovery{T}(
        _horizon_recovery_outcome(trials, maximum_horizon_distance),
        HorizonEndpointCandidate{T}[],
        trials,
        copy(geometry_schedule),
        copy(endpoint_orders),
        String(policy_identity),
        maximum_horizon_distance,
        0,
    )
end

function canonical_horizon_endpoint_search_evidence(
    recovery::HorizonEndpointRecovery,
)
    function candidate_evidence(candidate)
        limitation = horizon_endpoint_limitation(
            candidate, recovery.maximum_horizon_distance
        )
        assessments = filter(
            !isnothing,
            (candidate.ingoing_assessment, candidate.outgoing_assessment),
        )
        binding = (
            limitation == HORIZON_ENDPOINT_ADEQUATE || isempty(assessments)
        ) ? nothing : argmin(
                assessment -> assessment.predicted_reliable_digits,
                assessments,
            )
        limitation_conditioning = binding === nothing ? (
            binding_predicted_reliable_digits=nothing,
            maximum_last_term_ratio=nothing,
            maximum_recurrence_digits_lost=nothing,
            maximum_series_evaluation_digits_lost=nothing,
            maximum_truncation_digits_lost=nothing,
        ) : (
            binding_predicted_reliable_digits=string(
                binding.predicted_reliable_digits
            ),
            maximum_last_term_ratio=string(binding.maximum_last_term_ratio),
            maximum_recurrence_digits_lost=string(
                binding.maximum_recurrence_digits_lost
            ),
            maximum_series_evaluation_digits_lost=string(
                binding.maximum_series_evaluation_digits_lost
            ),
            maximum_truncation_digits_lost=string(
                binding.maximum_truncation_digits_lost
            ),
        )
        return (
            rho=string(candidate.geometry.rho),
            attempted_endpoint_order=candidate.attempted_endpoint_order,
            endpoint_order=candidate.endpoint_order,
            ingoing_best_prefix_order=(
                candidate.ingoing_evaluation === nothing ? nothing :
                candidate.ingoing_evaluation.order
            ),
            outgoing_best_prefix_order=(
                candidate.outgoing_evaluation === nothing ? nothing :
                candidate.outgoing_evaluation.order
            ),
            ingoing_adequate=candidate.ingoing_adequate,
            outgoing_adequate=candidate.outgoing_adequate,
            limitation=limitation,
            precision_limited=(
                limitation == HORIZON_ENDPOINT_PRECISION_LIMITED
            ),
            limitation_conditioning=limitation_conditioning,
        )
    end
    selected_keys = Set(
        (candidate.geometry.rho, candidate.attempted_endpoint_order)
        for candidate in recovery.selected_pair
    )
    selected_pair = map(candidate_evidence, recovery.selected_pair)
    rejected_candidates = map(
        candidate_evidence,
        filter(
            candidate -> !(
                (candidate.geometry.rho, candidate.attempted_endpoint_order)
                in selected_keys
            ),
            recovery.candidates,
        ),
    )
    return (
        outcome=recovery.outcome,
        policy_identity=recovery.policy_identity,
        selected_pair=selected_pair,
        rejected_candidates=rejected_candidates,
        endpoint_orders=recovery.endpoint_orders,
        homogeneous_rhs_evaluations_before_pair=
            recovery.homogeneous_rhs_evaluations_before_pair,
    )
end

function verified_horizon_endpoints_from_recovery(
    recovery::HorizonEndpointRecovery{T},
    maximum_horizon_distance::T,
) where {T<:AbstractFloat}
    length(recovery.selected_pair) == 2 || throw(ArgumentError(
        "horizon endpoint recovery result does not contain a verified pair"
    ))
    pair = recovery.selected_pair
    return VerifiedHorizonEndpoints{T}(
        pair[1],
        pair[2],
        recovery.candidates,
        maximum_horizon_distance,
        REAL_INNER_HORIZON_CONTOUR_ID,
    )
end

"""
    select_verified_horizon_endpoints(spectral, candidates;
                                      maximum_horizon_distance)

Select the reference and verification horizon endpoints.

The reference endpoint is the *nearest* adequate candidate — the one with the
largest `rho`, hence the shortest homogeneous leg — and the verification
endpoint is the next deeper adequate candidate. Two adequate endpoints are
required: one alone cannot supply the endpoint-disagreement term that the
absolute determinant error is built from.

Throws `NO_VERIFIED_HORIZON_ENDPOINT` when fewer than two candidates are
adequate, before any homogeneous ODE has been started.
"""
function select_verified_horizon_endpoints(
    spectral::HomogeneousSpectralContext{T},
    candidates::Vector{HorizonEndpointCandidate{T}};
    maximum_horizon_distance::T=T(DEFAULT_MAXIMUM_HORIZON_DISTANCE),
) where {T<:AbstractFloat}
    isfinite(maximum_horizon_distance) &&
        maximum_horizon_distance > zero(T) || throw(ArgumentError(
            "maximum horizon distance must be finite and positive"
        ))
    adequate = filter(
        candidate -> _candidate_adequate(
                candidate, maximum_horizon_distance
            ) && candidate.geometry.horizon_distance <= maximum_horizon_distance,
        candidates,
    )
    if length(adequate) < 2
        detail = isempty(candidates) ? "no candidates were evaluated" :
            join(map(_describe_horizon_candidate, candidates), "; ")
        limitation = diagnose_horizon_endpoint_limitation(
            candidates, maximum_horizon_distance
        )
        throw(_factored_error(
            T,
            NO_VERIFIED_HORIZON_ENDPOINT,
            spectral.precision_bits,
            "fewer than two horizon endpoints passed the radial-approach and " *
            "dual-series gate [limitation=" * limitation * "]: " * detail,
        ))
    end
    ordered = sort(
        adequate; by=candidate -> candidate.geometry.rho, rev=true
    )
    return VerifiedHorizonEndpoints{T}(
        ordered[1],
        ordered[2],
        candidates,
        maximum_horizon_distance,
        REAL_INNER_HORIZON_CONTOUR_ID,
    )
end

function _assert_real_inner_contour_provenance(
    spectral::HomogeneousSpectralContext{T},
    contour::RealInnerHorizonContour{T},
) where {T<:AbstractFloat}
    contour.contour_id == REAL_INNER_HORIZON_CONTOUR_ID || throw(
        _factored_error(
            T,
            INVALID_FACTORED_PROPAGATION_INPUT,
            spectral.precision_bits,
            "real-inner horizon contour identity changed",
        )
    )
    contour.precision_bits == spectral.precision_bits || throw(
        _factored_error(
            T,
            FACTORED_PROPAGATION_PRECISION_MISMATCH,
            spectral.precision_bits,
            "real-inner horizon contour precision does not match the spectral context",
        )
    )
    contour.frozen_branch_cell == spectral.frozen_branch_cell || throw(
        _factored_error(
            T,
            INVALID_FACTORED_PROPAGATION_INPUT,
            spectral.precision_bits,
            "real-inner horizon contour changed the frozen branch cell",
        )
    )
    isequal(contour.tangent, complex(one(T), zero(T))) || throw(
        _factored_error(
            T,
            INVALID_FACTORED_PROPAGATION_INPUT,
            spectral.precision_bits,
            "real-inner horizon contour tangent must be exactly 1 + 0im",
        )
    )
    return nothing
end

"""
    prepare_real_inner_horizon_endpoint(spectral, contour, candidate, branch,
                                        required_digits)

Build the seed state and explicit-tangent carrier for one horizon branch at a
verified endpoint.

The endpoint state is `(Y, dY/drho)` taken from the horizon series evaluation,
with the radial derivative converted to the contour parameter through

    dY/drho = tangent * (Delta / (r^2 + a^2)) * dY/dr

and the carrier is the horizon carrier rebound to the real-inner tangent (see
`FactoredSolutions.horizon_carrier_with_explicit_tangent`). An inadequate
preflight cannot be prepared: the assessment is re-checked here so a caller
cannot bypass the gate by constructing an endpoint directly.
"""
function prepare_real_inner_horizon_endpoint(
    spectral::HomogeneousSpectralContext{T},
    contour::RealInnerHorizonContour{T},
    candidate::HorizonEndpointCandidate{T},
    branch::CarrierKind,
    required_digits::T,
) where {T<:AbstractFloat}
    return _translate_factored_failure(
        T,
        spectral.precision_bits,
        "real-inner horizon endpoint preparation",
    ) do
        _with_factored_precision(T, spectral.precision_bits) do
            _assert_real_inner_contour_provenance(spectral, contour)
            (branch === HORIZON_INGOING || branch === HORIZON_OUTGOING) ||
                throw(_factored_error(
                    T,
                    INVALID_FACTORED_PROPAGATION_INPUT,
                    spectral.precision_bits,
                    "real-inner endpoint branch must be a horizon branch",
                ))
            _branch_candidate_adequate(
                candidate, candidate.geometry.horizon_distance, branch
            ) || throw(_factored_error(
                T,
                NO_VERIFIED_HORIZON_ENDPOINT,
                spectral.precision_bits,
                "real-inner endpoint preparation refused an unverified candidate",
            ))
            evaluation = branch === HORIZON_INGOING ?
                candidate.ingoing_evaluation : candidate.outgoing_evaluation
            assessment = branch === HORIZON_INGOING ?
                candidate.ingoing_assessment : candidate.outgoing_assessment
            evaluation === nothing && throw(_factored_error(
                T,
                NO_VERIFIED_HORIZON_ENDPOINT,
                spectral.precision_bits,
                "real-inner endpoint has no series evaluation",
            ))
            assessment === nothing && throw(_factored_error(
                T,
                NO_VERIFIED_HORIZON_ENDPOINT,
                spectral.precision_bits,
                "real-inner endpoint has no series assessment",
            ))
            assessment.adequate || throw(_factored_error(
                T,
                INSUFFICIENT_ASYMPTOTIC_PRECISION,
                spectral.precision_bits,
                "real-inner horizon seed cannot bypass an inadequate preflight",
                assessment=assessment,
            ))
            selected_endpoint_order = evaluation.order
            geometry_candidate = candidate.geometry
            radius = geometry_candidate.radius
            radial_factor = Delta(spectral.a, radius) /
                (radius^2 + complex(spectral.a^2, zero(T)))
            _finite_factored_complex(radial_factor) || throw(_factored_error(
                T,
                NONFINITE_FACTORED_PROPAGATION_DATA,
                spectral.precision_bits,
                "real-inner endpoint radial factor is nonfinite",
            ))
            state = FactoredEndpointState{T}(
                Complex{T}(evaluation.series_eval_horner),
                Complex{T}(
                    contour.tangent * radial_factor *
                    evaluation.series_derivative_horner
                ),
            )
            _finite_factored_complex(state.Y) &&
                _finite_factored_complex(state.Yrho) ||
                throw(_factored_error(
                    T,
                    NONFINITE_FACTORED_PROPAGATION_DATA,
                    spectral.precision_bits,
                    "real-inner horizon endpoint state is nonfinite",
                ))
            carrier = horizon_carrier_with_explicit_tangent(
                branch,
                spectral.p_horizon,
                contour.rstar_match,
                spectral.convention,
                contour.tangent,
            )
            regularity = _real_inner_endpoint_regularity(
                branch, state, carrier, geometry_candidate.rho, radius
            )
            regularity.finite || throw(_factored_error(
                T,
                NONFINITE_FACTORED_PROPAGATION_DATA,
                spectral.precision_bits,
                "real-inner horizon endpoint regularity evidence is nonfinite",
            ))
            max(
                regularity.relative_X_reconstruction_error,
                regularity.Xrho_backward_residual,
            ) <= regularity.reconstruction_tolerance || throw(
                _factored_error(
                    T,
                    NONFINITE_FACTORED_PROPAGATION_DATA,
                    spectral.precision_bits,
                    "real-inner horizon endpoint failed its reconstruction gate",
                )
            )
            return RealInnerHorizonEndpoint{T}(
                branch,
                state,
                carrier,
                geometry_candidate.rho,
                radius,
                geometry_candidate.horizon_distance,
                assessment,
                regularity,
                required_digits,
                spectral.precision_bits,
                selected_endpoint_order,
                REAL_INNER_HORIZON_CONTOUR_ID,
                spectral.frozen_branch_cell,
                spectral.contour_deformation,
            )
        end
    end
end

"""
    solve_factored_horizon_branch_to_match(spectral, contour, endpoint; ...)

Propagate one pure horizon branch from its verified real-inner endpoint to the
matching point `rho = 0`.

This replaces the mixed `Xup_match_to_inner` leg. Nothing about the infinity
solution enters here: the branch is a genuine homogeneous solution of the
factored GSN equation seeded from its own horizon expansion, so the two horizon
legs form an actual solution basis rather than one propagated solution carried
into horizon coordinates.
"""
function solve_factored_horizon_branch_to_match(
    spectral::HomogeneousSpectralContext{T},
    contour::RealInnerHorizonContour{T},
    endpoint::RealInnerHorizonEndpoint{T};
    odealgo=_FACTORED_DEFAULTSOLVER,
    reltol::Union{Nothing,T}=nothing,
    abstol::Union{Nothing,T}=nothing,
    ode_maxiters::Int=10^7,
    verbose::Bool=false,
    ode_observation_factory=nothing,
    ode_solution_observer=nothing,
    ode_exception_passthrough=_never_passthrough_ode_exception,
    ode_leg::AbstractString="horizon_branch_to_match",
    factored_homogeneous_rhs_counter::Base.RefValue{Int}=Ref(0),
) where {T<:AbstractFloat}
    _assert_real_inner_contour_provenance(spectral, contour)
    endpoint.contour_id == REAL_INNER_HORIZON_CONTOUR_ID || throw(
        _factored_error(
            T,
            INVALID_FACTORED_PROPAGATION_INPUT,
            spectral.precision_bits,
            "horizon branch endpoint was not prepared on the real-inner contour",
        )
    )
    endpoint.assessment.adequate || throw(_factored_error(
        T,
        INSUFFICIENT_ASYMPTOTIC_PRECISION,
        spectral.precision_bits,
        "horizon branch leg refused an inadequate endpoint preflight",
        assessment=endpoint.assessment,
    ))
    typed_reltol = _resolve_factored_tolerance(
        T, spectral.precision_bits, reltol, "relative tolerance"
    )
    typed_abstol = _resolve_factored_tolerance(
        T, spectral.precision_bits, abstol, "absolute tolerance"
    )
    return _execute_real_inner_horizon_leg(
        spectral,
        contour,
        endpoint;
        odealgo=odealgo,
        reltol=typed_reltol,
        abstol=typed_abstol,
        ode_maxiters=ode_maxiters,
        verbose=verbose,
        ode_observation_factory=ode_observation_factory,
        ode_solution_observer=ode_solution_observer,
        ode_exception_passthrough=ode_exception_passthrough,
        ode_leg=ode_leg,
        factored_homogeneous_rhs_counter=factored_homogeneous_rhs_counter,
    )
end

"""
    solve_verified_horizon_basis_to_match(spectral, contour, candidate,
                                          required_digits; ...)

Propagate both horizon branches from one verified endpoint to the matching
point, returning the pair that forms the horizon solution basis there.
"""
function solve_verified_horizon_basis_to_match(
    spectral::HomogeneousSpectralContext{T},
    contour::RealInnerHorizonContour{T},
    candidate::HorizonEndpointCandidate{T},
    required_digits::T;
    ode_leg_prefix::AbstractString="horizon",
    kwargs...,
) where {T<:AbstractFloat}
    ingoing_endpoint = prepare_real_inner_horizon_endpoint(
        spectral, contour, candidate, HORIZON_INGOING, required_digits
    )
    outgoing_endpoint = prepare_real_inner_horizon_endpoint(
        spectral, contour, candidate, HORIZON_OUTGOING, required_digits
    )
    ingoing = solve_factored_horizon_branch_to_match(
        spectral,
        contour,
        ingoing_endpoint;
        ode_leg="$(ode_leg_prefix)_ingoing_inner_to_match",
        kwargs...,
    )
    outgoing = solve_factored_horizon_branch_to_match(
        spectral,
        contour,
        outgoing_endpoint;
        ode_leg="$(ode_leg_prefix)_outgoing_inner_to_match",
        kwargs...,
    )
    return VerifiedHorizonBasisSolution{T}(
        ingoing,
        outgoing,
        ingoing_endpoint,
        outgoing_endpoint,
        candidate.geometry.rho,
        candidate.geometry.horizon_distance,
    )
end

function _execute_real_inner_horizon_leg(
    spectral::HomogeneousSpectralContext{T},
    contour::RealInnerHorizonContour{T},
    endpoint::RealInnerHorizonEndpoint{T};
    odealgo=_FACTORED_DEFAULTSOLVER,
    reltol::T=_factored_default_tolerance(T),
    abstol::T=_factored_default_tolerance(T),
    ode_maxiters::Int=10^7,
    verbose::Bool=false,
    ode_observation_factory=nothing,
    ode_solution_observer=nothing,
    ode_exception_passthrough=_never_passthrough_ode_exception,
    ode_leg::AbstractString="horizon_branch_to_match",
    factored_homogeneous_rhs_counter::Base.RefValue{Int}=Ref(0),
) where {T<:AbstractFloat}
    return _with_factored_precision(T, spectral.precision_bits) do
    start_rho = endpoint.rho
    stop_rho = zero(T)
    carrier = endpoint.carrier
    all(
        value -> _factored_precision_matches(
            value, spectral.precision_bits
        ),
        (
            start_rho,
            reltol,
            abstol,
            endpoint.state.Y,
            endpoint.state.Yrho,
            carrier.wave_number,
            carrier.rstar_match,
            carrier.log_at_match,
            carrier.q,
        ),
    ) || throw(_factored_error(
        T,
        FACTORED_PROPAGATION_PRECISION_MISMATCH,
        spectral.precision_bits,
        "real-inner horizon seed or controls do not preserve context precision",
    ))
    all(isfinite, (start_rho, reltol, abstol)) || throw(_factored_error(
        T,
        NONFINITE_FACTORED_PROPAGATION_DATA,
        spectral.precision_bits,
        "real-inner horizon ODE controls must be finite",
    ))
    start_rho < stop_rho || throw(_factored_error(
        T,
        INVALID_FACTORED_PROPAGATION_INPUT,
        spectral.precision_bits,
        "real-inner horizon leg must start strictly inside the matching point",
    ))
    reltol > zero(T) && abstol > zero(T) || throw(_factored_error(
        T,
        INVALID_FACTORED_PROPAGATION_INPUT,
        spectral.precision_bits,
        "real-inner horizon ODE tolerances must be positive",
    ))
    ode_maxiters > 0 || throw(_factored_error(
        T,
        INVALID_FACTORED_PROPAGATION_INPUT,
        spectral.precision_bits,
        "real-inner horizon ODE maxiters must be positive",
    ))
    tangent = contour.tangent
    initial_norm = hypot(
        abs(endpoint.state.Y), abs(endpoint.state.Yrho)
    )
    initial_carrier_log = T(abs(real(carrier_log(carrier, start_rho))))
    isfinite(initial_norm) && isfinite(initial_carrier_log) || throw(
        _factored_error(
            T,
            NONFINITE_FACTORED_PROPAGATION_DATA,
            spectral.precision_bits,
            "real-inner horizon initial diagnostics are nonfinite",
        )
    )
    accumulator = _FactoredDiagnosticAccumulator{T}(
        0, initial_norm, initial_norm, initial_carrier_log
    )
    internal_callback = _factored_internal_callback(accumulator, carrier)
    rhospan = (start_rho, stop_rho)
    external_callback, observation = _begin_ode_observation(
        ode_observation_factory, String(ode_leg), rhospan, odealgo
    )
    callback = _combine_factored_callbacks(
        external_callback, internal_callback
    )
    rhs_count_before = factored_homogeneous_rhs_counter[]
    parameters = FactoredGSNParameters(
        spectral.s,
        spectral.m,
        spectral.a,
        spectral.omega,
        spectral.lambda,
        contour.radius_from_rho,
        tangent,
        carrier,
        spectral.precision_bits,
        rhs_count_before,
        factored_homogeneous_rhs_counter,
    )
    initial_values = Complex{T}[endpoint.state.Y, endpoint.state.Yrho]
    odeprob = ODEProblem(
        factored_GSN_linear_eqn!, initial_values, rhospan, parameters
    )
    odesoln = try
        solve(
            odeprob,
            odealgo;
            maxiters=ode_maxiters,
            reltol=reltol,
            abstol=abstol,
            tstops=[stop_rho],
            save_everystep=false,
            save_start=false,
            save_end=true,
            dense=false,
            callback=callback,
            verbose=verbose,
        )
    catch error
        _throw_or_wrap_factored_ode_failure(
            error,
            ode_exception_passthrough,
            T,
            spectral.precision_bits,
            endpoint.assessment,
            _factored_rhs_evaluation_count(parameters),
        )
    end
    _finish_ode_observation(
        ode_solution_observer, String(ode_leg), odesoln, observation
    )
    _assert_successful_factored_ode_result(
        odesoln,
        T,
        spectral.precision_bits,
        endpoint.assessment,
        _factored_rhs_evaluation_count(parameters),
    )
    length(odesoln.u) == 1 && length(odesoln.t) == 1 || throw(
        _factored_error(
            T,
            FACTORED_ODE_FAILURE,
            spectral.precision_bits,
            "real-inner horizon leg violated the endpoint-only save contract";
            assessment=endpoint.assessment,
            factored_homogeneous_rhs_evaluations=
                _factored_rhs_evaluation_count(parameters),
        )
    )
    reached_rho = T(last(odesoln.t))
    endpoint_tolerance = T(64) * eps(T)
    abs(reached_rho - stop_rho) <= endpoint_tolerance || throw(
        _factored_error(
            T,
            FACTORED_ODE_FAILURE,
            spectral.precision_bits,
            "real-inner horizon leg did not reach the matching point";
            assessment=endpoint.assessment,
            factored_homogeneous_rhs_evaluations=
                _factored_rhs_evaluation_count(parameters),
        )
    )
    endpoint_values = last(odesoln.u)
    match_state = FactoredEndpointState{T}(
        Complex{T}(endpoint_values[1]), Complex{T}(endpoint_values[2])
    )
    _finite_factored_complex(match_state.Y) &&
        _finite_factored_complex(match_state.Yrho) || throw(
            _factored_error(
                T,
                NONFINITE_FACTORED_PROPAGATION_DATA,
                spectral.precision_bits,
                "real-inner horizon leg endpoint state is nonfinite";
                assessment=endpoint.assessment,
                factored_homogeneous_rhs_evaluations=
                    _factored_rhs_evaluation_count(parameters),
            )
        )
    solver_stats = hasproperty(odesoln, :destats) ?
        getproperty(odesoln, :destats) : nothing
    accepted_steps = solver_stats !== nothing &&
        hasproperty(solver_stats, :naccept) ?
            Int(getproperty(solver_stats, :naccept)) :
            accumulator.accepted_steps
    rejected_steps = solver_stats !== nothing &&
        hasproperty(solver_stats, :nreject) ?
            Int(getproperty(solver_stats, :nreject)) : 0
    diagnostics = FactoredODEDiagnostics{T}(
        endpoint.branch,
        String(ode_leg),
        HOMOGENEOUS_REPRESENTATION_ID,
        FACTORED_HOMOGENEOUS_ODE_SCOPE_ID,
        spectral.precision_bits,
        accepted_steps,
        rejected_steps,
        accumulator.maximum_remainder_state_norm,
        accumulator.minimum_remainder_state_norm,
        accumulator.maximum_absolute_real_carrier_log,
        endpoint.regularity,
        endpoint.assessment,
        spectral.convention,
        endpoint.frozen_branch_cell,
        endpoint.contour_deformation,
        _factored_rhs_evaluation_count(parameters),
        length(odesoln.u),
    )
    return FactoredODESolution{T}(
        match_state, carrier, stop_rho, diagnostics
    )
    end
end

function GSN_linear_eqn(u, p, rho)
    r = p.r_from_rho(rho)
    _sF = p.sign * exp(1im*p.beta)*sF(p.s, p.m, p.a, p.omega, p.lambda, r)
    _sU = exp(2im*p.beta)*sU(p.s, p.m, p.a, p.omega, p.lambda, r)

    #=
    Using the convention for DifferentialEquations
    u[1] = X(rho)
    u[2] = dX/drho = X'
    therefore
    X'' - sF X' - sU X = 0 => u[2]' - sF u[2] - sU u[1] = 0 => u[2]' = sF u[2] + sU u[1]
    =#
    return SA[u[2], _sF*u[2] + _sU*u[1]]
end

function GSN_Riccati_eqn(u, p, rho)
    r = p.r_from_rho(rho)
    _sF = p.sign * exp(1im*p.beta)*sF(p.s, p.m, p.a, p.omega, p.lambda, r)
    _sU = exp(2im*p.beta)*sU(p.s, p.m, p.a, p.omega, p.lambda, r)
    
    #=
    We write X = exp(I*Phi)
    Substitute X in this form into the GSN equation will give
    a Riccati equation, a first-order non-linear equation

    u[1] = Phi
    u[2] = dPhidrs
    =#
    return SA[u[2], -1im*_sU + _sF*u[2] - 1im*u[2]*u[2]]
end

function solve_X_in_rho(
    s::Int, m::Int, a, beta, omega, lambda, r_from_rho, sign, rhospan,
    initial_conditions; dtype=_DEFAULTDATATYPE, odealgo=_DEFAULTSOLVER,
    reltol=_DEFAULTTOLERANCE, abstol=_DEFAULTTOLERANCE,
    ode_maxiters=10^7,
    ode_observation_factory=nothing, ode_solution_observer=nothing,
    ode_leg="X_in_rho"
)
    p = (s=s, m=m, a=a, beta=beta, omega=omega, lambda=lambda, sign=sign, r_from_rho=r_from_rho)

    odeprob = ODEProblem(GSN_linear_eqn, initial_conditions, rhospan, p)
    observation_callback, observation = _begin_ode_observation(
        ode_observation_factory, ode_leg, rhospan, odealgo
    )
    solve_arguments = observation_callback === nothing ?
        NamedTuple() : (; callback=observation_callback)
    odesoln = solve(
        odeprob, odealgo;
        maxiters=ode_maxiters, reltol=reltol, abstol=abstol, solve_arguments...
    )
    _finish_ode_observation(ode_solution_observer, ode_leg, odesoln, observation)

    return odesoln
end

function solve_Phi_in_rho(s::Int, m::Int, a, beta, omega, lambda, r_from_rho, sign, rhospan, initial_conditions; dtype=_DEFAULTDATATYPE, odealgo=_DEFAULTSOLVER, reltol=_DEFAULTTOLERANCE, abstol=_DEFAULTTOLERANCE, ode_maxiters=10^7)
    p = (s=s, m=m, a=a, beta=beta, omega=omega, lambda=lambda, sign=sign, r_from_rho=r_from_rho)

    odeprob = ODEProblem(GSN_Riccati_eqn, initial_conditions, rhospan, p)
    odesoln = solve(odeprob, odealgo; maxiters=ode_maxiters, reltol=reltol, abstol=abstol)

    return odesoln
end

function Xup_initialconditions(s::Int, m::Int, a, beta, omega, lambda, r_from_rho, rs_mp, rhoout; order::Int=-1, dtype=_DEFAULTDATATYPE)
    outgoing_coeff_func(ord) = outgoing_coefficient_at_inf(s, m, a, omega, lambda, ord; data_type=dtype)
    fout(r) = fansatz(outgoing_coeff_func, omega, r; order=order)
    dfout_dr(r) = dfansatz_dr(outgoing_coeff_func, omega, r; order=order)

    rout = r_from_rho(rhoout)
    _fansatz = fout(rout)
    _dfansatz_dr = dfout_dr(rout)

    phase = exp(1im * abs(omega) * determine_sign(omega)*rhoout) * exp(1im * omega * rs_mp)

    Xrho_out = phase*_fansatz
    dXdrho_out = determine_sign(omega)*exp(1im*beta)*phase*(1im*omega*_fansatz + (Delta(a, rout)/(rout^2 + a^2))*_dfansatz_dr)

    return Xrho_out, dXdrho_out
end

function solve_Xup(
    s::Int, m::Int, a, beta_pos, beta_neg, omega, lambda, r_from_rho,
    rs_mp, rhoin, rhoout; initialconditions_order=-1,
    dtype=_DEFAULTDATATYPE, odealgo=_DEFAULTSOLVER,
    reltol=_DEFAULTTOLERANCE, abstol=_DEFAULTTOLERANCE,
    ode_observation_factory=nothing, ode_solution_observer=nothing
)
    # Sanity check
    if rhoin > rhoout
        throw(DomainError(rhoout, "rhoout ($rhoout) must be larger than rhoin ($rhoin)"))
    end
    if rhoout < 0
        throw(DomainError(rhoout, "rhoout ($rhoout) must be positive"))
    end

    # Initial conditions at rho = rhoout, the outer boundary
    Xup_rhoout, Xupprime_rhoout = Xup_initialconditions(s, m, a, beta_pos, omega, lambda, r_from_rho, rs_mp, rhoout; order=initialconditions_order, dtype=dtype)
    u0 = SA[dtype(Xup_rhoout); dtype(Xupprime_rhoout)]

    # Solve the ODE to the matching point no matter what
    odesoln_pos = solve_X_in_rho(
        s, m, a, beta_pos, omega, lambda, r_from_rho, determine_sign(omega),
        (rhoout, 0), u0; dtype=dtype, odealgo=odealgo,
        reltol=reltol, abstol=abstol,
        ode_observation_factory=ode_observation_factory,
        ode_solution_observer=ode_solution_observer,
        ode_leg="Xup_outer_to_match",
    )

    if rhoin < 0
        v0 = SA[dtype(1); dtype(determine_sign(omega - m*omega_horizon(a))*exp(1im*beta_neg))] .* SA[dtype(1); dtype(determine_sign(omega)*exp(-1im*beta_pos))] .* odesoln_pos(0)
        # Continue the integration
        odesoln_neg = solve_X_in_rho(
            s, m, a, beta_neg, omega, lambda, r_from_rho,
            determine_sign(omega - m*omega_horizon(a)), (0, rhoin), v0;
            dtype=dtype, odealgo=odealgo, reltol=reltol, abstol=abstol,
            ode_observation_factory=ode_observation_factory,
            ode_solution_observer=ode_solution_observer,
            ode_leg="Xup_match_to_inner",
        )
    else
        # Should not be used
        odesoln_neg = rho -> SA[NaN; NaN]
    end

    # Stitch together the two solutions
    # NOTE This *always* return X(rho) and dX(rho)/drs
    odesoln(rho) = rho >= 0 ? SA[dtype(1); dtype(determine_sign(omega)*exp(-1im*beta_pos))] .* odesoln_pos(rho) : SA[dtype(1); dtype(determine_sign(omega - m*omega_horizon(a))*exp(-1im*beta_neg))] .* odesoln_neg(rho)

    return odesoln, odesoln_pos, odesoln_neg
end

function solve_Phiup(s::Int, m::Int, a, beta_pos, beta_neg, omega, lambda, r_from_rho, rs_mp, rhoin, rhoout; initialconditions_order=-1, dtype=_DEFAULTDATATYPE, odealgo=_DEFAULTSOLVER, reltol=_DEFAULTTOLERANCE, abstol=_DEFAULTTOLERANCE)
    # Sanity check
    if rhoin > rhoout
        throw(DomainError(rhoout, "rhoout ($rhoout) must be larger than rhoin ($rhoin)"))
    end
    if rhoout < 0
        throw(DomainError(rhoout, "rhoout ($rhoout) must be positive"))
    end

    # Initial conditions at rho = rhoout, the outer boundary
    Xup_rhoout, Xupprime_rhoout = Xup_initialconditions(s, m, a, beta_pos, omega, lambda, r_from_rho, rs_mp, rhoout; order=initialconditions_order, dtype=dtype)
    # Convert initial conditions for Xup for Phi
    Phi, Phiprime = Solutions.PhiPhiprime_from_XXprime(Xup_rhoout, Xupprime_rhoout)
    u0 = SA[dtype(Phi); dtype(Phiprime)]

    # Solve the ODE to the matching point no matter what
    odesoln_pos = solve_Phi_in_rho(s, m, a, beta_pos, omega, lambda, r_from_rho, determine_sign(omega), (rhoout, 0), u0; dtype=dtype, odealgo=odealgo, reltol=reltol, abstol=abstol)

    if rhoin < 0
        _Phi, _Phiprime = odesoln_pos(0)
        _X, _Xprime = Solutions.XXprime_from_PhiPhiprime(_Phi, _Phiprime)
        v0_Phi, v0_Phiprime = Solutions.PhiPhiprime_from_XXprime(
            _X,
            dtype(determine_sign(omega - m*omega_horizon(a))*exp(1im*beta_neg)) * dtype(determine_sign(omega)*exp(-1im*beta_pos)) * _Xprime
        )
        # Continue the integration
        odesoln_neg = solve_Phi_in_rho(s, m, a, beta_neg, omega, lambda, r_from_rho, determine_sign(omega - m*omega_horizon(a)), (0, rhoin), SA[v0_Phi; v0_Phiprime]; dtype=dtype, odealgo=odealgo, reltol=reltol, abstol=abstol)
    else
        # Should not be used
        odesoln_neg = rho -> SA[NaN; NaN]
    end

    # Stitch together the two solutions
    # NOTE This *always* return Phi(rho) and dPhi(rho)/drs
    odesoln(rho) = rho >= 0 ? SA[dtype(1); dtype(determine_sign(omega)*exp(-1im*beta_pos))] .* odesoln_pos(rho) : SA[dtype(1); dtype(determine_sign(omega - m*omega_horizon(a))*exp(-1im*beta_neg))] .* odesoln_neg(rho)

    return odesoln, odesoln_pos, odesoln_neg
end

function Xin_initialconditions(s::Int, m::Int, a, beta, omega, lambda, r_from_rho, rs_mp, rhoin; order::Int=-1, dtype=_DEFAULTDATATYPE)
    ingoing_coeff_func(ord) = ingoing_coefficient_at_hor(s, m, a, omega, lambda, ord; data_type=dtype)
    gin(r) = gansatz(ingoing_coeff_func, a, r; order=order)
    dgin_dr(r) = dgansatz_dr(ingoing_coeff_func, a, r; order=order)

    rin = r_from_rho(rhoin)
    _gansatz = gin(rin)
    _dgansatz_dr = dgin_dr(rin)
    # rsin = rs_mp + rhoin * exp(1im*beta)
    p = omega - m*omega_horizon(a)
    phase = exp(-1im * abs(p) * determine_sign(p)*rhoin) * exp(-1im * p * rs_mp)

    Xrho_in = phase*_gansatz
    dXdrho_in = determine_sign(p)*exp(1im*beta)*phase*(-1im*p*_gansatz + (Delta(a, rin)/(rin^2 + a^2))*_dgansatz_dr)

    return Xrho_in, dXdrho_in
end

function solve_Xin(
    s::Int, m::Int, a, beta_pos, beta_neg, omega, lambda, r_from_rho,
    rs_mp, rhoin, rhoout; initialconditions_order=-1,
    dtype=_DEFAULTDATATYPE, odealgo=_DEFAULTSOLVER,
    reltol=_DEFAULTTOLERANCE, abstol=_DEFAULTTOLERANCE,
    ode_observation_factory=nothing, ode_solution_observer=nothing
)
    # Sanity check
    if rhoin > rhoout
        throw(DomainError(rhoin, "rhoin ($rhoin) must be smaller than rhoout ($rhoout)"))
    end
    if rhoin > 0
        throw(DomainError(rhoin, "rhoin ($rhoin) must be negative"))
    end

    # Initial conditions at rho = rhoin, the inner boundary
    Xin_rhoin, Xinprime_rhoin = Xin_initialconditions(s, m, a, beta_neg, omega, lambda, r_from_rho, rs_mp, rhoin; order=initialconditions_order, dtype=dtype)
    u0 = SA[dtype(Xin_rhoin); dtype(Xinprime_rhoin)]

    # Solve the ODE to the matching point no matter what
    odesoln_neg = solve_X_in_rho(
        s, m, a, beta_neg, omega, lambda, r_from_rho,
        determine_sign(omega - m*omega_horizon(a)), (rhoin, 0), u0;
        dtype=dtype, odealgo=odealgo, reltol=reltol, abstol=abstol,
        ode_observation_factory=ode_observation_factory,
        ode_solution_observer=ode_solution_observer,
        ode_leg="Xin_inner_to_match",
    )

    if rhoout > 0
        v0 = SA[dtype(1); dtype(determine_sign(omega)*exp(1im*beta_pos))] .* SA[dtype(1); dtype(determine_sign(omega - m*omega_horizon(a))*exp(-1im*beta_neg))] .* odesoln_neg(0)
        # Continue the integration
        odesoln_pos = solve_X_in_rho(
            s, m, a, beta_pos, omega, lambda, r_from_rho,
            determine_sign(omega), (0, rhoout), v0;
            dtype=dtype, odealgo=odealgo, reltol=reltol, abstol=abstol,
            ode_observation_factory=ode_observation_factory,
            ode_solution_observer=ode_solution_observer,
            ode_leg="Xin_match_to_outer",
        )
    else
        # Should not be used
        odesoln_pos = rho -> SA[NaN; NaN]
    end

    # Stitch together the two solutions
    # NOTE This *always* return X(rho) and dX(rho)/drs
    odesoln(rho) = rho > 0 ? SA[dtype(1); dtype(determine_sign(omega)*exp(-1im*beta_pos))] .* odesoln_pos(rho) : SA[dtype(1); dtype(determine_sign(omega - m*omega_horizon(a))*exp(-1im*beta_neg))] .* odesoln_neg(rho)

    return odesoln, odesoln_pos, odesoln_neg
end

function solve_Phiin(s::Int, m::Int, a, beta_pos, beta_neg, omega, lambda, r_from_rho, rs_mp, rhoin, rhoout; initialconditions_order=-1, dtype=_DEFAULTDATATYPE, odealgo=_DEFAULTSOLVER, reltol=_DEFAULTTOLERANCE, abstol=_DEFAULTTOLERANCE)
    # Sanity check
    if rhoin > rhoout
        throw(DomainError(rhoin, "rhoin ($rhoin) must be smaller than rhoout ($rhoout)"))
    end
    if rhoin > 0
        throw(DomainError(rhoin, "rhoin ($rhoin) must be negative"))
    end

    # Initial conditions at rho = rhoin, the inner boundary
    Xin_rhoin, Xinprime_rhoin = Xin_initialconditions(s, m, a, beta_neg, omega, lambda, r_from_rho, rs_mp, rhoin; order=initialconditions_order, dtype=dtype)
    # Convert initial conditions for Xin for Phi
    Phi, Phiprime = Solutions.PhiPhiprime_from_XXprime(Xin_rhoin, Xinprime_rhoin)
    u0 = SA[dtype(Phi); dtype(Phiprime)]

    # Solve the ODE to the matching point no matter what
    odesoln_neg = solve_Phi_in_rho(s, m, a, beta_neg, omega, lambda, r_from_rho, determine_sign(omega - m*omega_horizon(a)), (rhoin, 0), u0; dtype=dtype, odealgo=odealgo, reltol=reltol, abstol=abstol)
    
    if rhoout > 0
        _Phi, _Phiprime = odesoln_neg(0)
        _X, _Xprime = Solutions.XXprime_from_PhiPhiprime(_Phi, _Phiprime)
        v0_Phi, v0_Phiprime = Solutions.PhiPhiprime_from_XXprime(
            _X,
            dtype(determine_sign(omega)*exp(1im*beta_pos)) * dtype(determine_sign(omega - m*omega_horizon(a))*exp(-1im*beta_neg)) * _Xprime
        )
        # Continue the integration
        odesoln_pos = solve_Phi_in_rho(s, m, a, beta_pos, omega, lambda, r_from_rho, determine_sign(omega), (0, rhoout), SA[v0_Phi; v0_Phiprime]; dtype=dtype, odealgo=odealgo, reltol=reltol, abstol=abstol)
    else
        # Should not be used
        odesoln_pos = rho -> SA[NaN; NaN]
    end

    # Stitch together the two solutions
    # NOTE This *always* return Phi(rho) and dPhi(rho)/drs
    odesoln(rho) = rho > 0 ? SA[dtype(1); dtype(determine_sign(omega)*exp(-1im*beta_pos))] .* odesoln_pos(rho) : SA[dtype(1); dtype(determine_sign(omega - m*omega_horizon(a))*exp(-1im*beta_neg))] .* odesoln_neg(rho)

    return odesoln, odesoln_pos, odesoln_neg
end

function BrefBinc_SN_from_Xin(s::Int, m::Int, a, beta, omega, lambda, Xinsoln, r_from_rho, rs_mp, rhoout; order=10, dtype=_DEFAULTDATATYPE)
    rout = r_from_rho(rhoout)

    ingoing_coeff_func(ord) = ingoing_coefficient_at_inf(s, m, a, omega, lambda, ord; data_type=dtype)
    fin(r) = fansatz(ingoing_coeff_func, omega, r; order=order)
    dfin_dr(r) = dfansatz_dr(ingoing_coeff_func, omega, r; order=order)
    _fin = fin(rout)
    _dfin_dr = dfin_dr(rout)
    _phase_in = exp(-1im * abs(omega) * determine_sign(omega)*rhoout) * exp(-1im * omega * rs_mp)

    outgoing_coeff_func(ord) = outgoing_coefficient_at_inf(s, m, a, omega, lambda, ord; data_type=dtype)
    fout(r) = fansatz(outgoing_coeff_func, omega, r; order=order)
    dfout_dr(r) = dfansatz_dr(outgoing_coeff_func, omega, r; order=order)
    _fout = fout(rout)
    _dfout_dr = dfout_dr(rout)
    _phase_out = exp(1im * abs(omega) * determine_sign(omega)*rhoout) * exp(1im * omega * rs_mp)

    # Computing A1, A2, A3, A4
    A1 = _fin * _phase_in
    A2 = _fout * _phase_out
    A3 = determine_sign(omega)*exp(1im*beta)*_phase_in*(-1im*omega*_fin + (Delta(a, rout)/(rout^2 + a^2))*_dfin_dr)
    A4 = determine_sign(omega)*exp(1im*beta)*_phase_out*(1im*omega*_fout + (Delta(a, rout)/(rout^2 + a^2))*_dfout_dr)

    C1 = Xinsoln(rhoout)[1]
    C2 = determine_sign(omega)*exp(1im*beta)*Xinsoln(rhoout)[2]

    return -(-A3*C1 + A1*C2)/(A2*A3 - A1*A4), -(A4*C1 - A2*C2)/(A2*A3 - A1*A4)
end

function CrefCinc_SN_from_Xup(s::Int, m::Int, a, beta, omega, lambda, Xupsoln, r_from_rho, rs_mp, rhoin; order=10, dtype=_DEFAULTDATATYPE)
    p = omega - m*omega_horizon(a)
    rin = r_from_rho(rhoin)
    # rsin = rs_mp \pm rhoin * exp(1im*beta)

    ingoing_coeff_func(ord) = ingoing_coefficient_at_hor(s, m, a, omega, lambda, ord; data_type=dtype)
    gin(r) = gansatz(ingoing_coeff_func, a, r; order=order)
    dgin_dr(r) = dgansatz_dr(ingoing_coeff_func, a, r; order=order)
    _gin = gin(rin)
    _dgin_dr = dgin_dr(rin)
    _phase_in = exp(-1im * abs(p) * determine_sign(p)*rhoin) * exp(-1im * p * rs_mp)

    outgoing_coeff_func(ord) = outgoing_coefficient_at_hor(s, m, a, omega, lambda, ord; data_type=dtype)
    gout(r) = gansatz(outgoing_coeff_func, a, r; order=order)
    dgout_dr(r) = dgansatz_dr(outgoing_coeff_func, a, r; order=order)
    _gout = gout(rin)
    _dgout_dr = dgout_dr(rin)
    _phase_out = exp(1im * abs(p) * determine_sign(p)*rhoin) * exp(1im * p * rs_mp)

    # Computing A1, A2, A3, A4
    A1 = _gin * _phase_in
    A2 = _gout * _phase_out
    A3 = determine_sign(p)*exp(1im*beta)*_phase_in*(-1im*p*_gin + (Delta(a, rin)/(rin^2 + a^2))*_dgin_dr)
    A4 = determine_sign(p)*exp(1im*beta)*_phase_out*(1im*p*_gout + (Delta(a, rin)/(rin^2 + a^2))*_dgout_dr)

    C1 = Xupsoln(rhoin)[1]
    C2 = determine_sign(p)*exp(1im*beta)*Xupsoln(rhoin)[2]

    return -(A4*C1 - A2*C2)/(A2*A3 - A1*A4), -(-A3*C1 + A1*C2)/(A2*A3 - A1*A4)
end

function semianalytical_Xin(s::Int, m::Int, a, beta_pos, beta_neg, omega, lambda, Xinsoln, r_from_rho, rs_mp, rhoin, rhoout, horizon_expansionorder, infinity_expansionorder, rho; dtype=_DEFAULTDATATYPE)
    if rho < rhoin
        # Extend the numerical solution to the analytical ansatz from rhoin to horizon
        p = omega - m*omega_horizon(a)
        _r = r_from_rho(rho)
        if isnan(_r)
            # Resolve r_from_rho
            r_from_rho = solve_r_from_rho(a, beta_neg, beta_pos, rs_mp, rho, rhoout; sign_neg=determine_sign(p), sign_pos=determine_sign(omega))
            _r = r_from_rho(rho)
        end
        # _rs = rs_mp + rho * exp(1im*beta_neg)

        # Construct the analytical ansatz
        ingoing_coeff_func_hor(ord) = ingoing_coefficient_at_hor(s, m, a, omega, lambda, ord; data_type=dtype)
        gin(r) = gansatz(ingoing_coeff_func_hor, a, r; order=horizon_expansionorder)
        dgin_dr(r) = dgansatz_dr(ingoing_coeff_func_hor, a, r; order=horizon_expansionorder)
        _gin = gin(_r)
        _dgin_dr = dgin_dr(_r)
        _phase_in = exp(-1im * abs(p) * determine_sign(p)* rho) * exp(-1im * p * rs_mp)

        # NOTE There is no exp(1im*beta) since the derivative is wrt rstar
        _Xin = _gin * _phase_in
        _dXin_drs = _phase_in*(-1im*p*_gin + (Delta(a, _r)/(_r^2 + a^2))*_dgin_dr)

        return (_Xin, _dXin_drs)

    elseif rho > rhoout
        # Extend the numerical solution to the analytical ansatz from rhoout to infinity

        Bref_SN, Binc_SN = BrefBinc_SN_from_Xin(s, m, a, beta_pos, omega, lambda, Xinsoln, r_from_rho, rs_mp, rhoout; order=infinity_expansionorder, dtype=dtype)

        p = omega - m*omega_horizon(a)
        _r = r_from_rho(rho)
        if isnan(_r)
            # Resolve r_from_rho
            r_from_rho = solve_r_from_rho(a, beta_neg, beta_pos, rs_mp, rhoin, rho; sign_neg=determine_sign(p), sign_pos=determine_sign(omega))
            _r = r_from_rho(rho)
        end
        # _rs = rs_mp + rho * exp(1im*beta_pos)

        # Construct the analytical ansatz
        ingoing_coeff_func(ord) = ingoing_coefficient_at_inf(s, m, a, omega, lambda, ord; data_type=dtype)
        fin(r) = fansatz(ingoing_coeff_func, omega, r; order=infinity_expansionorder)
        dfin_dr(r) = dfansatz_dr(ingoing_coeff_func, omega, r; order=infinity_expansionorder)
        _fin = fin(_r)
        _dfin_dr = dfin_dr(_r)
        _phase_in = exp(-1im * abs(omega) * determine_sign(omega)*rho) * exp(-1im * omega * rs_mp)

        outgoing_coeff_func(ord) = outgoing_coefficient_at_inf(s, m, a, omega, lambda, ord; data_type=dtype)
        fout(r) = fansatz(outgoing_coeff_func, omega, r; order=infinity_expansionorder)
        dfout_dr(r) = dfansatz_dr(outgoing_coeff_func, omega, r; order=infinity_expansionorder)
        _fout = fout(_r)
        _dfout_dr = dfout_dr(_r)
        _phase_out = exp(1im * abs(omega) * determine_sign(omega)*rho) * exp(1im * omega * rs_mp)

        _Xin = Bref_SN*_fout*_phase_out + Binc_SN*_fin*_phase_in
        _dXin_drs = Bref_SN*_phase_out*(1im*omega*_fout + (Delta(a, _r)/(_r^2 + a^2))*_dfout_dr) + Binc_SN*_phase_in*(-1im*omega*_fin + (Delta(a, _r)/(_r^2 + a^2))*_dfin_dr)

        return (_Xin, _dXin_drs)
    else
        # Return the numerical solution
        return Xinsoln(rho)
    end
end

function semianalytical_Xup(s::Int, m::Int, a, beta_pos, beta_neg, omega, lambda, Xupsoln, r_from_rho, rs_mp, rhoin, rhoout, horizon_expansionorder, infinity_expansionorder, rho; dtype=_DEFAULTDATATYPE)
    if rho < rhoin
        # Extend the numerical solution to the analytical ansatz from rhoin to horizon

        Cref_SN, Cinc_SN = CrefCinc_SN_from_Xup(s, m, a, beta_neg, omega, lambda, Xupsoln, r_from_rho, rs_mp, rhoin; order=horizon_expansionorder, dtype=dtype)

        p = omega - m*omega_horizon(a)
        _r = r_from_rho(rho)
        if isnan(_r)
            # Resolve r_from_rho
            r_from_rho = solve_r_from_rho(a, beta_neg, beta_pos, rs_mp, rho, rhoout; sign_neg=determine_sign(p), sign_pos=determine_sign(omega))
            _r = r_from_rho(rho)
        end
        # _rs = rs_mp + rho * exp(1im*beta_neg)

        # Construct the analytical ansatz
        ingoing_coeff_func(ord) = ingoing_coefficient_at_hor(s, m, a, omega, lambda, ord; data_type=dtype)
        gin(r) = gansatz(ingoing_coeff_func, a, r; order=horizon_expansionorder)
        dgin_dr(r) = dgansatz_dr(ingoing_coeff_func, a, r; order=horizon_expansionorder)
        _gin = gin(_r)
        _dgin_dr = dgin_dr(_r)
        _phase_in = exp(-1im * abs(p) * determine_sign(p)* rho) * exp(-1im * p * rs_mp)

        outgoing_coeff_func(ord) = outgoing_coefficient_at_hor(s, m, a, omega, lambda, ord; data_type=dtype)
        gout(r) = gansatz(outgoing_coeff_func, a, r; order=horizon_expansionorder)
        dgout_dr(r) = dgansatz_dr(outgoing_coeff_func, a, r; order=horizon_expansionorder)
        _gout = gout(_r)
        _dgout_dr = dgout_dr(_r)
        _phase_out = exp(1im * abs(p) * determine_sign(p)* rho) * exp(1im * p * rs_mp)

        _Xup = Cref_SN*_gin*_phase_in + Cinc_SN*_gout*_phase_out
        _dXup_drs = Cref_SN*_phase_in*(-1im*p*_gin + (Delta(a, _r)/(_r^2 + a^2))*_dgin_dr) + Cinc_SN*_phase_out*(1im*p*_gout + (Delta(a, _r)/(_r^2 + a^2))*_dgout_dr)

        return (_Xup, _dXup_drs)
    elseif rho > rhoout
        # Extend the numerical solution to the analytical ansatz from rhoout to infinity
        p = omega - m*omega_horizon(a)
        _r = r_from_rho(rho)
        if isnan(_r)
            # Resolve r_from_rho
            r_from_rho = solve_r_from_rho(a, beta_neg, beta_pos, rs_mp, rhoin, rho; sign_neg=determine_sign(p), sign_pos=determine_sign(omega))
            _r = r_from_rho(rho)
        end

        # Construct the analytical ansatz
        outgoing_coeff_func_inf(ord) = outgoing_coefficient_at_inf(s, m, a, omega, lambda, ord; data_type=dtype)
        fout(r) = fansatz(outgoing_coeff_func_inf, omega, r; order=infinity_expansionorder)
        dfout_dr(r) = dfansatz_dr(outgoing_coeff_func_inf, omega, r; order=infinity_expansionorder)
        _fout = fout(_r)
        _dfout_dr = dfout_dr(_r)
        _phase_out = exp(1im * abs(omega) * determine_sign(omega)* rho) * exp(1im * omega * rs_mp)

        _Xup = _fout*_phase_out
        _dXup_drs = _phase_out*(1im*omega*_fout + (Delta(a, _r)/(_r^2 + a^2))*_dfout_dr)

        return (_Xup, _dXup_drs)
    else
        # Return the numerical solution
        return Xupsoln(rho)
    end
end

end
