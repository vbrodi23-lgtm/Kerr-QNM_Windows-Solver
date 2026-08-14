#!/usr/bin/env julia

# Performance-only prototype for PR #44.
#
# The production readiness gate remains closed.  This tool reuses the existing
# authenticated spectral/asymptotic machinery and outer-leg executor, but gives
# the two pure horizon branches a positive real tortoise tangent so their radial
# map actually approaches r_plus.  It then extracts the connection coefficients
# from an independently scaled basis at rho=0.  The result is cost and
# conditioning evidence, not a mathematical activation receipt.

const HORIZON_BASIS_REPOSITORY_ROOT = normpath(joinpath(@__DIR__, ".."))
const LEAF13_LEG_HARNESS = joinpath(
    HORIZON_BASIS_REPOSITORY_ROOT,
    "tools",
    "benchmark_leaf13_factored_legs.jl",
)

leg_harness_source = read(LEAF13_LEG_HARNESS, String)
leg_harness_definitions = first(split(
    leg_harness_source, "\ntry\n"; limit=2
))
include_string(Main, leg_harness_definitions, LEAF13_LEG_HARNESS)

const HORIZON_BASIS_PREFIX = "@@LEAF13_HORIZON_BASIS_AT_MATCH@@"
const HORIZON_BASIS_SCHEMA =
    "windows-solver.leaf13-horizon-basis-at-match/1"
const HORIZON_BASIS_CLAIM_CEILING =
    "performance-and-internal-consistency-only-not-math-validation"
const STRONG_PASS_MAXIMUM_HORIZON_RHS = 200_000

function emit_horizon_basis(
    kind::AbstractString; payload=Dict{String,Any}()
)
    println(HORIZON_BASIS_PREFIX * JSON.json(Dict{String,Any}(
        "schema" => HORIZON_BASIS_SCHEMA,
        "kind" => String(kind),
        "claim_ceiling" => HORIZON_BASIS_CLAIM_CEILING,
        "payload" => payload,
    )))
    flush(stdout)
end

function _finite_complex(value::Complex)
    return isfinite(real(value)) && isfinite(imag(value))
end

function explicit_tangent_carrier(
    kind::CarrierKind,
    wave_number::Complex{T},
    rstar_match::T,
    convention::GSNBranchConvention{T},
    tangent::Complex{T},
) where {T<:AbstractFloat}
    (kind === HORIZON_INGOING || kind === HORIZON_OUTGOING) ||
        error("explicit-tangent prototype carrier must be a horizon branch")
    _finite_complex(wave_number) && !iszero(wave_number) ||
        error("explicit-tangent carrier wave number must be finite and nonzero")
    _finite_complex(tangent) && !iszero(tangent) ||
        error("explicit-tangent carrier tangent must be finite and nonzero")
    canonical = PlaneWaveCarrier(
        kind, wave_number, rstar_match, convention
    )
    carrier_sign = kind === HORIZON_INGOING ? -one(T) : one(T)
    q = carrier_sign * complex(zero(T), one(T)) * wave_number * tangent
    _finite_complex(q) || error("explicit-tangent carrier q is nonfinite")
    return PlaneWaveCarrier{T}(
        canonical.kind,
        canonical.wave_number,
        canonical.rstar_match,
        canonical.log_at_match,
        q,
        canonical.convention,
    )
end

function factor_physical_match_state(
    X::Complex{T},
    dX_drstar::Complex{T},
    carrier::PlaneWaveCarrier{T},
    tangent::Complex{T},
) where {T<:AbstractFloat}
    _finite_complex(X) && _finite_complex(dX_drstar) ||
        error("physical match state must be finite")
    _finite_complex(tangent) && !iszero(tangent) ||
        error("physical match tangent must be finite and nonzero")
    return factor_state(
        X, tangent * dX_drstar, carrier, zero(T)
    )
end

function _prototype_state_norm(state::FactoredEndpointState)
    return hypot(abs(state.Y), abs(state.Yrho))
end

function _relative_coefficient_pair_difference(left, right)
    T = typeof(real(left.Cref))
    difference = hypot(
        abs(left.Cref - right.Cref),
        abs(left.Cinc - right.Cinc),
    )
    scale = max(
        hypot(abs(left.Cref), abs(left.Cinc)),
        hypot(abs(right.Cref), abs(right.Cinc)),
        floatmin(T),
    )
    return difference / scale
end

function solve_scaled_match_basis(
    target::FactoredEndpointState{T},
    column_1::FactoredEndpointState{T},
    column_2::FactoredEndpointState{T},
) where {T<:AbstractFloat}
    all(
        _finite_complex,
        (
            target.Y,
            target.Yrho,
            column_1.Y,
            column_1.Yrho,
            column_2.Y,
            column_2.Yrho,
        ),
    ) || error("match-basis inputs must be finite")
    column_norm_1 = _prototype_state_norm(column_1)
    column_norm_2 = _prototype_state_norm(column_2)
    iszero(column_norm_1) && error("match-basis column 1 is zero")
    iszero(column_norm_2) && error("match-basis column 2 is zero")

    a = column_1.Y / column_norm_1
    c = column_1.Yrho / column_norm_1
    b = column_2.Y / column_norm_2
    d = column_2.Yrho / column_norm_2
    determinant = a * d - b * c
    determinant_abs = abs(determinant)
    basis_norm = hypot(hypot(abs(a), abs(b)), hypot(abs(c), abs(d)))
    adjugate_norm = hypot(hypot(abs(d), abs(b)), hypot(abs(c), abs(a)))
    resolution_floor = eps(T) * basis_norm * adjugate_norm
    determinant_abs > resolution_floor || error(
        "scaled match basis is arithmetically unresolved"
    )

    scaled_coefficient_1 =
        (target.Y * d - b * target.Yrho) / determinant
    scaled_coefficient_2 =
        (a * target.Yrho - target.Y * c) / determinant
    Cref = scaled_coefficient_1 / column_norm_1
    Cinc = scaled_coefficient_2 / column_norm_2
    reconstructed = FactoredEndpointState{T}(
        scaled_coefficient_1 * a + scaled_coefficient_2 * b,
        scaled_coefficient_1 * c + scaled_coefficient_2 * d,
    )
    residual = FactoredEndpointState{T}(
        reconstructed.Y - target.Y,
        reconstructed.Yrho - target.Yrho,
    )
    reconstruction_residual = _prototype_state_norm(residual) /
        max(_prototype_state_norm(target), floatmin(T))
    condition_frobenius = basis_norm * adjugate_norm / determinant_abs
    all(
        isfinite,
        (
            determinant_abs,
            reconstruction_residual,
            condition_frobenius,
        ),
    ) || error("scaled match-basis diagnostics are nonfinite")
    _finite_complex(Cref) && _finite_complex(Cinc) ||
        error("scaled match-basis coefficients are nonfinite")
    return (
        Cref=Cref,
        Cinc=Cinc,
        reconstructed=reconstructed,
        reconstruction_residual=reconstruction_residual,
        scaled_basis_determinant=determinant,
        scaled_basis_determinant_abs=determinant_abs,
        condition_frobenius=condition_frobenius,
        column_norm_1=column_norm_1,
        column_norm_2=column_norm_2,
    )
end

function select_nearest_adequate_horizon_endpoint(
    candidates;
    maximum_horizon_distance,
)
    maximum_horizon_distance > zero(maximum_horizon_distance) ||
        error("maximum horizon distance must be positive")
    eligible = filter(candidates) do candidate
        candidate.rho < zero(candidate.rho) &&
            isfinite(candidate.horizon_distance) &&
            candidate.horizon_distance <= maximum_horizon_distance &&
            candidate.ingoing_adequate && candidate.outgoing_adequate
    end
    isempty(eligible) && error(
        "no horizon endpoint passes radial-approach and dual-series preflights"
    )
    return argmax(candidate -> candidate.rho, eligible)
end

function _real_horizon_radial_map(
    request,
    spectral::CF.HomogeneousSpectralContext{T},
    rstar_match::T,
    rho_min::T,
) where {T<:AbstractFloat}
    return CF.solve_r_from_rho(
        spectral.a,
        zero(T),
        rstar_match,
        rho_min;
        sign=Int8(1),
        dtype=Complex{T},
        odealgo=AutoVern9(Rosenbrock23(autodiff=false)),
        reltol=parse_real(T, request, "ode_relative_tolerance"),
        abstol=parse_real(T, request, "ode_absolute_tolerance"),
        ode_maxiters=parse_integer(request, "homogeneous_ode_maxiters"),
        verbose=false,
    )
end

function _horizon_series_candidate(
    spectral::CF.HomogeneousSpectralContext{T},
    radial_map,
    rho::T,
    required_digits::T,
) where {T<:AbstractFloat}
    radius = Complex{T}(radial_map(rho))
    geometry = Kerr.stable_horizon_geometry(spectral.a)
    horizon_distance = abs(
        radius - complex(geometry.rplus, zero(T))
    )
    ingoing_series = CF._branch_series(
        spectral.series, HORIZON_INGOING
    )
    outgoing_series = CF._branch_series(
        spectral.series, HORIZON_OUTGOING
    )
    ingoing_evaluation = CF.evaluate_horizon_asymptotic_series(
        ingoing_series, radius; order=spectral.endpoint_order
    )
    outgoing_evaluation = CF.evaluate_horizon_asymptotic_series(
        outgoing_series, radius; order=spectral.endpoint_order
    )
    ingoing_assessment = CF.assess_asymptotic_preflight(
        ingoing_series, ingoing_evaluation, required_digits
    )
    outgoing_assessment = CF.assess_asymptotic_preflight(
        outgoing_series, outgoing_evaluation, required_digits
    )
    return (
        rho=rho,
        radius=radius,
        horizon_distance=horizon_distance,
        ingoing_adequate=ingoing_assessment.adequate,
        outgoing_adequate=outgoing_assessment.adequate,
        ingoing_series=ingoing_series,
        outgoing_series=outgoing_series,
        ingoing_evaluation=ingoing_evaluation,
        outgoing_evaluation=outgoing_evaluation,
        ingoing_assessment=ingoing_assessment,
        outgoing_assessment=outgoing_assessment,
    )
end

function _candidate_payload(candidate)
    return Dict{String,Any}(
        "rho" => string(candidate.rho),
        "radius_re" => string(real(candidate.radius)),
        "radius_im" => string(imag(candidate.radius)),
        "horizon_distance" => string(candidate.horizon_distance),
        "ingoing_adequate" => candidate.ingoing_adequate,
        "outgoing_adequate" => candidate.outgoing_adequate,
        "ingoing_predicted_reliable_digits" => string(
            candidate.ingoing_assessment.predicted_reliable_digits
        ),
        "outgoing_predicted_reliable_digits" => string(
            candidate.outgoing_assessment.predicted_reliable_digits
        ),
        "ingoing_last_term_ratio" => string(
            candidate.ingoing_assessment.maximum_last_term_ratio
        ),
        "outgoing_last_term_ratio" => string(
            candidate.outgoing_assessment.maximum_last_term_ratio
        ),
    )
end

function _build_pure_horizon_seed(
    spectral::CF.HomogeneousSpectralContext{T},
    selected,
    kind::CarrierKind,
    tangent::Complex{T},
    rstar_match::T,
) where {T<:AbstractFloat}
    if kind === HORIZON_INGOING
        evaluation = selected.ingoing_evaluation
        assessment = selected.ingoing_assessment
    elseif kind === HORIZON_OUTGOING
        evaluation = selected.outgoing_evaluation
        assessment = selected.outgoing_assessment
    else
        error("pure horizon seed has unsupported carrier kind")
    end
    assessment.adequate || error(
        "pure horizon seed cannot bypass an inadequate preflight"
    )
    radius = selected.radius
    radial_factor = Kerr.Delta(spectral.a, radius) /
        (radius^2 + complex(spectral.a^2, zero(T)))
    state = FactoredEndpointState{T}(
        evaluation.series_eval_horner,
        tangent * radial_factor *
            evaluation.series_derivative_horner,
    )
    carrier = explicit_tangent_carrier(
        kind,
        spectral.p_horizon,
        rstar_match,
        spectral.convention,
        tangent,
    )
    return (state=state, carrier=carrier, assessment=assessment)
end

function _pure_horizon_leg(
    request,
    spectral::CF.HomogeneousSpectralContext{T},
    radial_map,
    seed,
    start_rho::T,
    tangent::Complex{T},
    ode_leg::AbstractString,
) where {T<:AbstractFloat}
    counter = Ref(0)
    parameters = CF.FactoredGSNParameters(
        spectral.s,
        spectral.m,
        spectral.a,
        spectral.omega,
        spectral.lambda,
        radial_map,
        tangent,
        seed.carrier,
        spectral.precision_bits,
        0,
        counter,
    )
    maximum_norm = Ref(_prototype_state_norm(seed.state))
    minimum_norm = Ref(maximum_norm[])
    accepted_by_callback = Ref(0)
    callback = DiscreteCallback(
        (_state, _rho, _integrator) -> true,
        integrator -> begin
            state_norm = hypot(abs(integrator.u[1]), abs(integrator.u[2]))
            isfinite(state_norm) || error(
                "pure horizon remainder norm became nonfinite"
            )
            maximum_norm[] = max(maximum_norm[], state_norm)
            minimum_norm[] = min(minimum_norm[], state_norm)
            accepted_by_callback[] += 1
            SciMLBase.u_modified!(integrator, false)
            nothing
        end;
        save_positions=(false, false),
    )
    initial_values = Complex{T}[seed.state.Y, seed.state.Yrho]
    problem = ODEProblem(
        CF.factored_GSN_linear_eqn!,
        initial_values,
        (start_rho, zero(T)),
        parameters,
    )
    started = time_ns()
    solution = solve(
        problem,
        AutoVern9(Rosenbrock23(autodiff=false));
        maxiters=parse_integer(request, "homogeneous_ode_maxiters"),
        reltol=parse_real(T, request, "ode_relative_tolerance"),
        abstol=parse_real(T, request, "ode_absolute_tolerance"),
        tstops=[zero(T)],
        save_everystep=false,
        save_start=false,
        save_end=true,
        dense=false,
        callback=callback,
        verbose=false,
    )
    elapsed_seconds = (time_ns() - started) / 1.0e9
    SciMLBase.successful_retcode(solution) || error(
        "$ode_leg returned unsuccessful retcode $(solution.retcode)"
    )
    length(solution.u) == 1 || error(
        "$ode_leg violated endpoint-only save contract"
    )
    values = only(solution.u)
    endpoint = FactoredEndpointState{T}(
        Complex{T}(values[1]), Complex{T}(values[2])
    )
    stats = solution.destats
    accepted_steps = hasproperty(stats, :naccept) ?
        Int(stats.naccept) : accepted_by_callback[]
    rejected_steps = hasproperty(stats, :nreject) ? Int(stats.nreject) : 0
    return (
        endpoint=endpoint,
        carrier=seed.carrier,
        rhs_evaluations=counter[],
        accepted_steps=accepted_steps,
        rejected_steps=rejected_steps,
        elapsed_seconds=elapsed_seconds,
        maximum_remainder_state_norm=maximum_norm[],
        minimum_remainder_state_norm=minimum_norm[],
    )
end

function _pure_leg_payload(result, ode_leg)
    return Dict{String,Any}(
        "ode_leg" => ode_leg,
        "rhs_evaluations" => result.rhs_evaluations,
        "accepted_steps" => result.accepted_steps,
        "rejected_steps" => result.rejected_steps,
        "elapsed_seconds" => result.elapsed_seconds,
        "maximum_remainder_state_norm" => string(
            result.maximum_remainder_state_norm
        ),
        "minimum_remainder_state_norm" => string(
            result.minimum_remainder_state_norm
        ),
        "endpoint_Y_abs" => string(abs(result.endpoint.Y)),
        "endpoint_Yrho_abs" => string(abs(result.endpoint.Yrho)),
    )
end

function run_horizon_basis_at_match_prototype()
    request = benchmark_request()
    request["rho_in"] = "-100"
    validate_regularised_gsn_policy(request)
    bits = parse_integer(request, "working_precision_bits")
    return setprecision(BigFloat, bits) do
        REQUEST_STARTED_NS[] = time_ns()
        ACTIVE_PHASE_STARTED_NS[] = REQUEST_STARTED_NS[]
        ACTIVE_PHASE[] = "HORIZON_BASIS_AT_MATCH_PROTOTYPE"
        omega = parse_complex(BigFloat, request, "omega_re", "omega_im")
        context = build_determinant_request_context(
            BigFloat, request, omega
        )
        spectral = build_sample_spectral_context(
            BigFloat, request, omega, context
        )
        match_radius = parse_real(BigFloat, request, "readout_radius")
        rstar_match = BigFloat(GSN.rstar_from_r(
            spectral.a, match_radius
        ))
        required_digits = required_reliable_digits(BigFloat, request)
        tangent = complex(one(BigFloat), zero(BigFloat))

        emit_horizon_basis("prototype_started"; payload=Dict{String,Any}(
            "leaf_id" => request["leaf_id"],
            "precision_digits" => request["precision_digits"],
            "working_precision_bits" => bits,
            "endpoint_series_order" => request["endpoint_series_order"],
            "horizon_tangent_re" => string(real(tangent)),
            "horizon_tangent_im" => string(imag(tangent)),
            "production_readiness_assertion_bypassed" => true,
            "production_worker_changed" => false,
        ))

        radial_map = _real_horizon_radial_map(
            request, spectral, rstar_match, BigFloat(-100)
        )
        candidates = [
            _horizon_series_candidate(
                spectral, radial_map, BigFloat(rho), required_digits
            )
            for rho in (-10, -25, -50, -75, -100)
        ]
        for candidate in candidates
            emit_horizon_basis(
                "horizon_endpoint_candidate";
                payload=_candidate_payload(candidate),
            )
        end
        selected = select_nearest_adequate_horizon_endpoint(
            candidates; maximum_horizon_distance=BigFloat("0.1")
        )
        emit_horizon_basis(
            "horizon_endpoint_selected";
            payload=_candidate_payload(selected),
        )

        ingoing_seed = _build_pure_horizon_seed(
            spectral, selected, HORIZON_INGOING, tangent, rstar_match
        )
        outgoing_seed = _build_pure_horizon_seed(
            spectral, selected, HORIZON_OUTGOING, tangent, rstar_match
        )
        ingoing = _pure_horizon_leg(
            request,
            spectral,
            radial_map,
            ingoing_seed,
            selected.rho,
            tangent,
            "Xin_inner_to_match_prototype",
        )
        emit_horizon_basis(
            "leg_completed";
            payload=_pure_leg_payload(
                ingoing, "Xin_inner_to_match_prototype"
            ),
        )
        outgoing = _pure_horizon_leg(
            request,
            spectral,
            radial_map,
            outgoing_seed,
            selected.rho,
            tangent,
            "Xout_inner_to_match_prototype",
        )
        emit_horizon_basis(
            "leg_completed";
            payload=_pure_leg_payload(
                outgoing, "Xout_inner_to_match_prototype"
            ),
        )

        outer_contour = build_worker_contour_context(
            BigFloat,
            request,
            spectral,
            match_radius,
            "Xup-horizon-basis-prototype",
        )
        outer_preparation = CF.prepare_factored_infinity_outgoing(
            spectral, outer_contour, required_digits
        )
        CF.assert_factored_preflights_adequate(outer_preparation)
        outer_counter = Ref(0)
        outer_started = time_ns()
        outer = execute_leg(
            request,
            spectral,
            outer_contour,
            outer_preparation,
            outer_contour.rho_out,
            zero(BigFloat),
            outer_counter;
            ode_leg="Xup_outer_to_match_basis_prototype",
        )
        outer_elapsed_seconds = (time_ns() - outer_started) / 1.0e9
        emit_horizon_basis(
            "outer_leg_completed";
            payload=solution_payload(outer, outer_elapsed_seconds),
        )

        outer_raw = reconstruct_state(
            outer.endpoint, outer.carrier, zero(BigFloat)
        )
        outer_dX_drstar = outer_raw.Xrho /
            outer_contour.infinity_tangent
        target = factor_physical_match_state(
            outer_raw.X,
            outer_dX_drstar,
            ingoing.carrier,
            tangent,
        )
        outgoing_common = change_carrier(
            outgoing.endpoint,
            outgoing.carrier,
            ingoing.carrier,
            zero(BigFloat),
        )
        basis = solve_scaled_match_basis(
            target, ingoing.endpoint, outgoing_common
        )

        verification_selected = only(filter(
            candidate -> candidate.rho == BigFloat(-50), candidates
        ))
        verification_ingoing_seed = _build_pure_horizon_seed(
            spectral,
            verification_selected,
            HORIZON_INGOING,
            tangent,
            rstar_match,
        )
        verification_outgoing_seed = _build_pure_horizon_seed(
            spectral,
            verification_selected,
            HORIZON_OUTGOING,
            tangent,
            rstar_match,
        )
        verification_ingoing = _pure_horizon_leg(
            request,
            spectral,
            radial_map,
            verification_ingoing_seed,
            verification_selected.rho,
            tangent,
            "Xin_inner_to_match_endpoint_verification",
        )
        verification_outgoing = _pure_horizon_leg(
            request,
            spectral,
            radial_map,
            verification_outgoing_seed,
            verification_selected.rho,
            tangent,
            "Xout_inner_to_match_endpoint_verification",
        )
        verification_target = factor_physical_match_state(
            outer_raw.X,
            outer_dX_drstar,
            verification_ingoing.carrier,
            tangent,
        )
        verification_outgoing_common = change_carrier(
            verification_outgoing.endpoint,
            verification_outgoing.carrier,
            verification_ingoing.carrier,
            zero(BigFloat),
        )
        verification_basis = solve_scaled_match_basis(
            verification_target,
            verification_ingoing.endpoint,
            verification_outgoing_common,
        )
        coefficient_pair_difference =
            _relative_coefficient_pair_difference(
                basis, verification_basis
            )
        determinant_ratio = basis.Cinc / basis.Cref
        verification_determinant_ratio =
            verification_basis.Cinc / verification_basis.Cref
        determinant_ratio_relative_difference = abs(
            determinant_ratio - verification_determinant_ratio
        ) / max(
            abs(determinant_ratio),
            abs(verification_determinant_ratio),
            floatmin(BigFloat),
        )
        endpoint_invariance_tolerance = BigFloat("1e-12")
        endpoint_invariance_passed = coefficient_pair_difference <=
            endpoint_invariance_tolerance
        emit_horizon_basis(
            "endpoint_invariance_completed";
            payload=Dict{String,Any}(
                "reference_rho_in" => string(selected.rho),
                "verification_rho_in" => string(
                    verification_selected.rho
                ),
                "verification_ingoing_rhs_evaluations" =>
                    verification_ingoing.rhs_evaluations,
                "verification_outgoing_rhs_evaluations" =>
                    verification_outgoing.rhs_evaluations,
                "coefficient_pair_relative_difference" => string(
                    coefficient_pair_difference
                ),
                "determinant_ratio_relative_difference" => string(
                    determinant_ratio_relative_difference
                ),
                "verification_condition_frobenius" => string(
                    verification_basis.condition_frobenius
                ),
                "verification_matching_reconstruction_residual" => string(
                    verification_basis.reconstruction_residual
                ),
                "endpoint_invariance_tolerance" => string(
                    endpoint_invariance_tolerance
                ),
                "endpoint_invariance_passed" =>
                    endpoint_invariance_passed,
            ),
        )
        endpoint_invariance_passed || error(
            "horizon basis coefficients changed beyond the endpoint-invariance tolerance"
        )
        combined_horizon_rhs =
            ingoing.rhs_evaluations + outgoing.rhs_evaluations
        performance_verdict = combined_horizon_rhs <=
            STRONG_PASS_MAXIMUM_HORIZON_RHS ?
                "strong-performance-pass" :
                "performance-threshold-not-met"
        emit_horizon_basis("prototype_completed"; payload=Dict{String,Any}(
            "selected_rho_in" => string(selected.rho),
            "selected_horizon_distance" => string(
                selected.horizon_distance
            ),
            "ingoing_rhs_evaluations" => ingoing.rhs_evaluations,
            "outgoing_rhs_evaluations" => outgoing.rhs_evaluations,
            "combined_horizon_rhs_evaluations" => combined_horizon_rhs,
            "strong_pass_maximum_horizon_rhs" =>
                STRONG_PASS_MAXIMUM_HORIZON_RHS,
            "outer_rhs_evaluations" =>
                outer.diagnostics.factored_homogeneous_rhs_evaluations,
            "Cref_re" => string(real(basis.Cref)),
            "Cref_im" => string(imag(basis.Cref)),
            "Cinc_re" => string(real(basis.Cinc)),
            "Cinc_im" => string(imag(basis.Cinc)),
            "cref_fraction" => string(
                abs(basis.Cref) / hypot(abs(basis.Cref), abs(basis.Cinc))
            ),
            "scaled_basis_determinant_abs" => string(
                basis.scaled_basis_determinant_abs
            ),
            "condition_frobenius" => string(
                basis.condition_frobenius
            ),
            "matching_reconstruction_residual" => string(
                basis.reconstruction_residual
            ),
            "performance_verdict" => performance_verdict,
        ))
        return nothing
    end
end

if abspath(PROGRAM_FILE) == @__FILE__
    try
        run_horizon_basis_at_match_prototype()
    catch failure
        emit_horizon_basis("prototype_failed"; payload=Dict{String,Any}(
            "error_type" => string(typeof(failure)),
            "message" => sprint(showerror, failure),
        ))
        showerror(stderr, failure, catch_backtrace())
        println(stderr)
        exit(1)
    end
end
