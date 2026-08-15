from dataclasses import replace
from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import math

from windows_solver.contracts import canonical_json_bytes


EXPECTED_KAPPA_SPINS = {
    Fraction(1, 100): (0.999791731748236, "0x1.ffe4b3ad56fa5p-1"),
    Fraction(1, 200): (0.9999489834961278, "0x1.fff9502b91917p-1"),
    Fraction(1, 500): (0.9999919355814243, "0x1.fffef1672c027p-1"),
    Fraction(1, 1000): (0.9999979919739198, "0x1.ffffbc9f2ff3bp-1"),
}


def expected_lattice_keys() -> set[tuple[int, int, int, int, int]]:
    """Return the approved pure-Kerr lattice with canonical rational χ keys."""

    high = {
        Fraction(97, 100), Fraction(49, 50), Fraction(99, 100),
        Fraction(199, 200), Fraction(997, 1000), Fraction(999, 1000),
    }
    keys = set()
    for ell in (2, 3, 4):
        spins = (
            {Fraction(19 * i, 780) for i in range(40)} | high
            if ell in (2, 3)
            else {Fraction(i, 52) for i in range(40)}
        )
        for m in range(-ell, ell + 1):
            for n in range(3):
                for spin in spins:
                    keys.add((ell, m, n, spin.numerator, spin.denominator))
    return keys


VALID_STUDY = {
    "schema_version": 1,
    "target": "problem-contract",
    "theory_id": "general-relativity",
    "convention_id": "kerr-mass-normalized-outgoing",
    "modes": [
        {
            "s": -2,
            "ell": 2,
            "m": 2,
            "n": 0,
            "branch": "damped",
            "polarization": "plus",
        }
    ],
    "spins": [0.0, 0.7],
    "evidence_profile": "research",
    "numerical_policy": {"precision_bits": 128, "root_tolerance": 1e-10},
}


SUPPORTED_SPECTRUM_STUDY = {
    "schema_version": 1,
    "target": "spectral-core",
    "theory_id": "general-relativity",
    "convention_id": "kerr-mass-normalized-outgoing",
    "modes": [
        {
            "s": -2,
            "ell": 2,
            "m": 2,
            "n": 0,
            "branch": "schwarzschild-overtone-continuation",
            "polarization": "gravitational",
        }
    ],
    "spins": [0.95, 0.997],
    "evidence_profile": "research",
    "numerical_policy": {},
}


def valid_numerical_conditioning(
    mechanism_id: str = "horizon-admittance",
) -> dict[str, object]:
    """Return one complete mechanism-honest promoted conditioning fixture."""

    supported_exterior = {
        "exterior-fixed-r3",
        "exterior-light-ring",
        "exterior-throat-kappa",
        "exterior-alpha-zero",
        "exterior-alpha-half",
        "exterior-alpha-one",
    }
    horizon = mechanism_id == "horizon-admittance"
    if not horizon and mechanism_id not in supported_exterior:
        raise ValueError("conditioning fixture mechanism is invalid")

    return {
        "schema": "windows-solver.m02-conditioning/3",
        "determinant_family": (
            "horizon-scattering/v1" if horizon else "exterior-wronskian/v1"
        ),
        "scattering_diagnostics_applicable": horizon,
        # The horizon family builds a three-leg solution basis on a verified
        # real-inner contour; the exterior family is unchanged.
        "homogeneous_representation": (
            "factored-three-leg-horizon-basis-at-match-gsn/v1"
            if horizon
            else "factored-plane-wave-gsn/v1"
        ),
        "branch_convention": "gsn-complex-rho/v1",
        "scattering_column_convention": (
            "column1=horizon-ingoing-Cref;"
            "column2=horizon-outgoing-Cinc/v1"
            if horizon
            else None
        ),
        "radial_derivative_convention": "state2=dX/drho/v1",
        "determinant_convention": (
            "cinc-over-cref-minus-R/v1"
            if horizon
            else "wronskian-perturbed-Xin-with-Xup/v1"
        ),
        "determinant_normalisation": (
            "cinc-over-cref-minus-reflectivity/v1"
            if horizon
            else "unit-asymptotic-branch-wronskian/v1"
        ),
        "regular_remainder_contract": (
            "known-carrier-times-regular-remainder/v1"
        ),
        "factored_remainder_state_convention": "state1=Y;state2=dY/drho/v1",
        "human_math_review_receipt_status": "absent-unapproved/v1",
        "human_math_review_receipt_sha256": None,
        "independent_reference_fixture_receipt_status": "absent-unreviewed/v1",
        "independent_reference_fixture_receipt_sha256": None,
        "maximum_series_digits_lost": "4.2500",
        "maximum_recurrence_digits_lost": "7.1250",
        "maximum_series_evaluation_spread": "1.25E-20",
        "maximum_last_term_ratio": "2.50E-18",
        "minimum_asymptotic_predicted_reliable_digits": "45.500",
        "maximum_basis_condition": "8.00E+12" if horizon else None,
        "maximum_basis_backward_error": "3.75E-44" if horizon else None,
        "maximum_matching_reconstruction_residual": (
            "4.50E-43" if horizon else None
        ),
        "endpoint_remainders_regular": True,
        "maximum_endpoint_reconstruction_error": "2.25E-42",
        "maximum_fd_digits_lost": "11.750",
        "predicted_reliable_digits": "52.250",
        "required_reliable_digits": "24",
        "precision_limited": False,
        "asymptotic_preflight_avoided_ode": False,
        "minimum_cref_chart_margin": "96.00" if horizon else None,
        "maximum_carrier_change_error": "5.00E-46" if horizon else None,
        "maximum_contour_angle_deformation": "7.50E-8",
    }


def current_promoted_component_payload(
    result,
    digits: int,
    *,
    precision_limited: bool,
    leaf,
) -> dict[str, object]:
    """Wrap a mocked promoted result in the current package evidence contract."""

    from windows_solver.response_engine import (
        ComponentStatus,
        NumericalConditioningEvidence,
        RootAuthenticationEvidence,
        regularised_gsn_precision_policy,
    )

    mapping = valid_numerical_conditioning(result.mechanism_id)
    mapping.update({
        "predicted_reliable_digits": (
            "11.25" if precision_limited else "55.125"
        ),
        "required_reliable_digits": "24",
        "precision_limited": precision_limited,
    })
    evidence = NumericalConditioningEvidence.from_mapping(mapping)
    raw_status = (
        "available/v1"
        if evidence.scattering_diagnostics_applicable
        else "not-applicable/v1"
    )

    scientific_runtime = {
        "precision_digits": digits,
        "working_precision_bits": math.ceil(digits * math.log2(10)) + 32,
        "refinement_level": 0,
        "regularised_gsn_precision_policy": dict(
            regularised_gsn_precision_policy(result.mechanism_id)
        ),
    }

    def conditioned(readout, readout_id):
        correction_tolerance = Decimal("1e-18")
        derivative = Decimal(str(readout.determinant_derivative_abs))
        normalised = Decimal(str(readout.determinant_residual_abs))
        if readout.converged:
            normalised = min(
                normalised,
                derivative * correction_tolerance / Decimal(10),
            )
        authentication = RootAuthenticationEvidence.from_mapping(
            root_authentication_for_readout(
                mechanism_id=result.mechanism_id,
                determinant_abs=normalised,
                derivative_abs=derivative,
                root_correction_tolerance=correction_tolerance,
                accepted=readout.converged,
            )
        )
        updated = replace(
            readout,
            determinant_residual_abs=float(normalised),
            diagnostic_readouts=(readout.diagnostic_readouts or None),
            numerical_conditioning=evidence,
            normalised_determinant_abs=normalised,
            raw_determinant_abs=(
                normalised
                if raw_status == "available/v1"
                else None
            ),
            raw_determinant_evidence_status=raw_status,
            worker_response_receipt=None,
            root_authentication=authentication,
        )
        request_binding = {
            "schema_version": 1,
            "operation": "root-readout",
            "job_id": leaf.job.job_id,
            "leaf_id": leaf.leaf_id,
            "role": leaf.role,
            "mechanism_id": leaf.mechanism_id,
            "job_policy_sha256": leaf.job.policy.identity_sha256,
            "backend_identity_sha256": (
                leaf.job.backend_identity.identity_sha256
            ),
            "precision_digits": digits,
            "refinement_level": 0,
            "synthetic_readout_id": readout_id,
            "policy": {
                "root_correction_tolerance": str(correction_tolerance),
            },
        }
        receipt_material = {
            "schema": "windows-solver.worker-response-receipt/1",
            "request_binding": request_binding,
            "request_sha256": hashlib.sha256(
                canonical_json_bytes(request_binding)
            ).hexdigest(),
            "scientific_runtime_sha256": hashlib.sha256(
                canonical_json_bytes(scientific_runtime)
            ).hexdigest(),
            "worker_response_schema_version": 4,
            "root_residual_abs_text": str(
                updated.normalised_determinant_abs
            ),
            "raw_determinant_abs_text": (
                None
                if updated.raw_determinant_abs is None
                else str(updated.raw_determinant_abs)
            ),
            "raw_determinant_evidence_status": raw_status,
        }
        return replace(
            updated,
            diagnostic_readouts=(updated.diagnostic_readouts or None),
            worker_response_receipt={
                **receipt_material,
                "receipt_sha256": hashlib.sha256(
                    canonical_json_bytes(receipt_material)
                ).hexdigest(),
            },
        )

    levels = tuple(
        replace(
            level,
            real_plus=conditioned(level.real_plus, f"level-{index}-real-plus"),
            real_minus=conditioned(level.real_minus, f"level-{index}-real-minus"),
            imaginary_plus=conditioned(
                level.imaginary_plus, f"level-{index}-imaginary-plus"
            ),
            imaginary_minus=conditioned(
                level.imaginary_minus, f"level-{index}-imaginary-minus"
            ),
        )
        for index, level in enumerate(result.levels)
    )
    conditioned_result = replace(
        result,
        baseline=conditioned(result.baseline, "baseline"),
        levels=levels,
    )
    payload: dict[str, object] = {
        "evidence_kind": "package-owned-julia-promoted-component-engine",
        "result": conditioned_result.to_mapping(),
        "self_refinement_result": None,
        "scientific_runtime": scientific_runtime,
    }
    if result.status is ComponentStatus.NOT_CONVERGED:
        payload["self_refinement_skipped_reason"] = "PRIMARY_NOT_CONVERGED"
    return payload


CONTROL_FAILURE_STAGE_FOR_CODE = {
    "COORDINATE_INVERSION_STALLED": "coordinate-inversion",
    "NO_VERIFIED_HORIZON_ENDPOINT": "horizon-endpoint-geometry",
    "INSUFFICIENT_ASYMPTOTIC_PRECISION": "asymptotic-preflight",
    "ASYMPTOTIC_SERIES_INVALID": "asymptotic-preflight",
    "ALGEBRAIC_REPRESENTATION_SINGULAR": "finite-difference",
    "FINITE_DIFFERENCE_NOISE_LIMIT": "finite-difference",
    "DETERMINANT_UNCERTAINTY_TOO_LARGE": "root-authentication",
    "SCATTERING_BASIS_ILL_CONDITIONED": "scattering-extraction",
    "SCATTERING_CHART_ILL_CONDITIONED": "determinant-chart",
}
"""Stage each control code is attributed to when a fixture synthesises one.

A failure code says what went wrong; the stage says where. Several codes can
arise at more than one point in the pipeline, so a receipt carrying only the
code cannot be attributed. Shared here so the test modules that synthesise
control receipts cannot drift apart on the answer.
"""


def control_failure_stage(failure_code: str) -> str:
    return CONTROL_FAILURE_STAGE_FOR_CODE.get(
        failure_code, "homogeneous-propagation"
    )


def valid_control_failure_diagnostics(
    failure_code: str,
    *,
    precision_bits: int = 298,
) -> dict[str, object]:
    """Return the exact typed diagnostic shape for one control failure."""

    factored = {
        "reason": failure_code,
        "precision_bits": precision_bits,
        "factored_homogeneous_rhs_evaluations": 0,
        "avoided_ode_scope": "factored-homogeneous-gsn/v1",
    }
    if failure_code == "ASYMPTOTIC_SERIES_INVALID":
        factored["reason"] = "NONFINITE_ASYMPTOTIC_DATA"
    if failure_code == "INSUFFICIENT_ASYMPTOTIC_PRECISION":
        return {
            **factored,
            "predicted_reliable_digits": "11.25000000000000000001",
            "required_reliable_digits": "24",
            "asymptotic_preflight_avoided_ode": True,
            "asymptotic_preflight_reason": failure_code,
            "maximum_series_digits_lost": "37.5",
            "maximum_recurrence_digits_lost": "12.25",
        }
    if failure_code in {
        "ASYMPTOTIC_SERIES_INVALID",
        "PHYSICAL_SINGULAR_LIMIT",
        "CARRIER_CHANGE_INCONSISTENT",
        "INVALID_FACTORED_PROPAGATION_INPUT",
        "FACTORED_PROPAGATION_PRECISION_MISMATCH",
        "NONFINITE_FACTORED_PROPAGATION_DATA",
        "FACTORED_ODE_FAILURE",
        "NO_VERIFIED_HORIZON_ENDPOINT",
    }:
        return factored
    if failure_code in {
        "SCATTERING_BASIS_ILL_CONDITIONED",
        "SCATTERING_CHART_ILL_CONDITIONED",
    }:
        return {"reason": failure_code, "precision_bits": precision_bits}
    if failure_code == "ALGEBRAIC_REPRESENTATION_SINGULAR":
        return {
            "reason": "derivative-overflow/v1",
            "range_status": "derivative-overflow/v1",
            "operation": "finite-difference-derivative/v1",
            "axis": "real",
            "h": "1e-6",
        }
    if failure_code == "COORDINATE_INVERSION_STALLED":
        return {
            "reason": failure_code,
            "range_status": "coordinate-inversion-stalled/v1",
            "operation": "coordinate-inversion/v1",
            "stall_reason": "microscopic-step",
            "ode_leg": "r_from_rho_real_inner",
            "ode_t_current": "-1e-11",
            "ode_t_end": "-100",
            "ode_span_abs": "100",
            "ode_span_fraction": "1e-13",
            "ode_rhs_evaluations": 200000,
            "ode_accepted_steps": 12500,
            "ode_rejected_steps": 187500,
            "ode_last_accepted_step_abs": "8.1e-17",
            "ode_min_accepted_step_abs": "8.0e-17",
            "current_r_re": "1.4358898943540674",
            "current_r_im": "0",
            "coordinate_identity_residual_abs": "2.1e-25",
            "elapsed_leg_seconds": 8.75,
        }
    if failure_code == "DETERMINANT_UNCERTAINTY_TOO_LARGE":
        residual_upper = Decimal("1e-28") + Decimal("2e-18")
        correction_upper = residual_upper / Decimal(2)
        return {
            "determinant_abs": "1e-28",
            "determinant_error_abs": "2e-18",
            "correction_upper_bound": str(correction_upper),
            "correction_without_error": "5e-29",
            "root_correction_tolerance": "1e-18",
            "derivative_lower_bound_abs": "2",
            "root_authentication": {
                "central_determinant_re": "1e-28",
                "central_determinant_im": "0",
                "determinant_error": {
                    "endpoint_disagreement_abs": "1e-18",
                    "control_disagreement_abs": None,
                    "equivalence_disagreement_abs": None,
                    "precision_disagreement_abs": None,
                    "safety_factor": "2",
                    "numerical_error_abs": "2e-18",
                    "error_model_id": (
                        "verified-endpoint-control-equivalence-absolute-error/v2"
                    ),
                },
                "residual_upper_bound_abs": str(residual_upper),
                "derivative_authentication": {
                    "derivative_re": "2",
                    "derivative_im": "0",
                    "propagated_error_abs": "0",
                    "step_disagreement_abs": "0",
                    "lower_bound_abs": "2",
                    "selected_step": "5e-7",
                    "axis": "real",
                },
                "correction_upper_bound": str(correction_upper),
                "root_correction_tolerance": "1e-18",
                "accepted": False,
            },
        }
    if failure_code == "FINITE_DIFFERENCE_NOISE_LIMIT":
        return {
            "nominal_step": "1e-6",
            "minimum_step": "1e-8",
            "maximum_step": "1e-4",
            "attempts": [{
                "h": "1e-6",
                "real_step_convergent": False,
                "complex_axis_consistent": True,
                "noise_resolved": False,
                "derivative_abs": "2.4",
                "derivative_uncertainty_abs": "1e-8",
                "base_derivative_error_abs": "2e-8",
                "half_derivative_error_abs": "3e-8",
                "double_derivative_error_abs": "4e-8",
                "imaginary_derivative_error_abs": "5e-8",
                "derivative_error_abs": "3e-8",
                "accepted": False,
            }],
        }
    raise AssertionError(
        f"missing typed diagnostic fixture for {failure_code}"
    )


def valid_root_authentication(mechanism_id: str) -> dict[str, object]:
    """Return the worker's error-aware root authentication record.

    The error breakdown and model identity are published only by families that
    compute one, so the exterior Wronskian path carries nulls. Keeping that
    asymmetry here is deliberate: it is the property the backend cross-checks
    against ``scattering_diagnostics_applicable``.
    """

    horizon = mechanism_id == "horizon-admittance"
    # The record is arithmetically coherent so tests can assert the real
    # relationships rather than merely the field shapes:
    #   numerical_error_abs   = safety_factor * max(components) = 64 * 2.1875E-62
    #   residual_upper_bound  = |D| + eta_D  = 1E-60 + 1.4E-60
    #   correction_upper_bound= residual_upper_bound / derivative_lower_bound
    return {
        # Chosen so both families divide exactly: the horizon determinant is
        # 1E-60 with a 1.4E-60 error bound, the exterior one is 2.4E-60 with no
        # error model, and both give a 2.4E-60 residual bound over a 2.4
        # derivative bound.
        "central_determinant_re": "1E-60" if horizon else "2.4E-60",
        "central_determinant_im": "0",
        "determinant_error": (
            {
                "endpoint_disagreement_abs": "2.1875E-62",
                "control_disagreement_abs": "1E-62",
                "equivalence_disagreement_abs": "5E-63",
                # Populated, and deliberately not the largest component: a
                # reader that silently substituted it for the maximum would
                # still produce a plausible-looking bound, so the fixture makes
                # the two distinguishable.
                "precision_disagreement_abs": "3E-63",
                "safety_factor": "64",
                "numerical_error_abs": "1.4E-60",
                "error_model_id": (
                    "verified-endpoint-control-equivalence-absolute-error/v2"
                ),
            }
            if horizon
            else None
        ),
        "residual_upper_bound_abs": "2.4E-60",
        "derivative_authentication": {
            # The horizon estimate exceeds the lower bound by exactly the
            # 1E-54 propagated error plus 2E-54 step disagreement below.
            "derivative_re": (
                "2.400000000000000000000000000000000000000000000000000003"
                if horizon
                else "2.4"
            ),
            "derivative_im": "0",
            "propagated_error_abs": "1E-54" if horizon else "0",
            "step_disagreement_abs": "2E-54",
            "lower_bound_abs": "2.4",
            "selected_step": "1E-6",
            "axis": "real",
        },
        "correction_upper_bound": "1E-60",
        "root_correction_tolerance": "1E-18",
        "accepted": True,
    }


def root_authentication_for_readout(
    *,
    mechanism_id: str,
    determinant_abs: Decimal,
    derivative_abs: Decimal,
    root_correction_tolerance: Decimal,
    accepted: bool,
) -> dict[str, object]:
    """Build exact synthetic evidence for a persisted promoted readout."""

    horizon = mechanism_id == "horizon-admittance"
    residual_upper = determinant_abs
    correction_upper = residual_upper / derivative_abs
    return {
        "central_determinant_re": str(determinant_abs),
        "central_determinant_im": "0",
        "determinant_error": (
            {
                "endpoint_disagreement_abs": "0",
                "control_disagreement_abs": None,
                "equivalence_disagreement_abs": None,
                "precision_disagreement_abs": None,
                "safety_factor": "64",
                "numerical_error_abs": "0",
                "error_model_id": (
                    "verified-endpoint-control-equivalence-absolute-error/v2"
                ),
            }
            if horizon
            else None
        ),
        "residual_upper_bound_abs": str(residual_upper),
        "derivative_authentication": {
            "derivative_re": str(derivative_abs),
            "derivative_im": "0",
            "propagated_error_abs": "0",
            "step_disagreement_abs": "0",
            "lower_bound_abs": str(derivative_abs),
            "selected_step": "1E-6",
            "axis": "real",
        },
        "correction_upper_bound": str(correction_upper),
        "root_correction_tolerance": str(root_correction_tolerance),
        "accepted": accepted,
    }


def valid_julia_root_response(
    request: dict[str, object],
) -> dict[str, object]:
    """Return a complete successful promoted-worker response for one request."""

    def shifted(value: str, delta: str) -> str:
        with localcontext() as context:
            context.prec = 180
            return str(Decimal(value) + Decimal(delta))

    omega = request["omega"]
    policy = request["policy"]
    root_authentication = valid_root_authentication(
        request["mechanism_id"]
    )
    root_authentication["root_correction_tolerance"] = policy[
        "root_correction_tolerance"
    ]
    radii = {
        "truncation": "2E-55",
        "resolution": "3E-55",
        "seed-path": "4E-55",
    }
    return {
        "schema_version": 4,
        "status": "ok",
        "adapter": "package-owned-julia-gsn-root-readout",
        "request_sha256": "e" * 64,
        "precision_digits": request["precision_digits"],
        "working_precision_bits": request["working_precision_bits"],
        "root_omega_re": omega["real"],
        "root_omega_im": omega["imaginary"],
        "root_residual_abs": (
            "1E-60"
            if request["mechanism_id"] == "horizon-admittance"
            else "2.4E-60"
        ),
        "raw_determinant_abs": (
            "6.75E+220"
            if request["mechanism_id"] == "horizon-admittance"
            else None
        ),
        "raw_determinant_evidence_status": (
            "available/v1"
            if request["mechanism_id"] == "horizon-admittance"
            else "not-applicable/v1"
        ),
        "root_derivative_abs": (
            "2.400000000000000000000000000000000000000000000000000003"
            if request["mechanism_id"] == "horizon-admittance"
            else "2.4"
        ),
        "root_authentication": root_authentication,
        "root_converged": True,
        "branch_authentication_contract_version": 3,
        "root_branch_continuation_valid": True,
        "branch_tolerance_abs": policy["branch_enclosure_radius_abs"],
        "root_displacement_abs": "0",
        "truncation_radius_abs": radii["truncation"],
        "resolution_radius_abs": radii["resolution"],
        "seed_path_radius_abs": radii["seed-path"],
        "diagnostic_roots": {
            phase: {
                "root_omega_re": shifted(omega["real"], radius),
                "root_omega_im": omega["imaginary"],
                "root_residual_abs": "1E-60",
                "root_derivative_abs": "2.5",
                "root_converged": True,
            }
            for phase, radius in radii.items()
        },
        "numerical_conditioning": valid_numerical_conditioning(
            request["mechanism_id"]
        ),
    }
