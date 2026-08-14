from decimal import Decimal, localcontext
from fractions import Fraction


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
        "schema": "windows-solver.m02-conditioning/2",
        "determinant_family": (
            "horizon-scattering/v1" if horizon else "exterior-wronskian/v1"
        ),
        "scattering_diagnostics_applicable": horizon,
        "homogeneous_representation": "factored-plane-wave-gsn/v1",
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


def valid_schema_two_julia_root_response(
    request: dict[str, object],
) -> dict[str, object]:
    """Return a complete successful promoted-worker response for one request."""

    def shifted(value: str, delta: str) -> str:
        with localcontext() as context:
            context.prec = 180
            return str(Decimal(value) + Decimal(delta))

    omega = request["omega"]
    policy = request["policy"]
    radii = {
        "truncation": "2E-55",
        "resolution": "3E-55",
        "seed-path": "4E-55",
    }
    return {
        "schema_version": 2,
        "status": "ok",
        "adapter": "package-owned-julia-gsn-root-readout",
        "request_sha256": "e" * 64,
        "precision_digits": request["precision_digits"],
        "working_precision_bits": request["working_precision_bits"],
        "root_omega_re": omega["real"],
        "root_omega_im": omega["imaginary"],
        "root_residual_abs": "1E-60",
        "raw_determinant_abs": (
            "6.75E+220"
            if request["mechanism_id"] == "horizon-admittance"
            else None
        ),
        "root_derivative_abs": "2.5",
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
