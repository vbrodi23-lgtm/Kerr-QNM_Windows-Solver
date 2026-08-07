"""Canonical coupled angular/Leaver solver for offline Kerr catalog builds.

The determinant equations are migrated unchanged from the project's accepted
backend.  Public-product names and formatting are new; the numerical machinery
is not.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import root

try:
    from . import kerr_angular as angular
except ImportError:  # pragma: no cover - direct script execution
    import kerr_angular as angular


SOURCE_BLOB_SHA = "ffb17a6be8e15da3bbce21f6c5f66420b251b077"
CONTINUED_FRACTION_TOLERANCE = 1e-14
CONTINUED_FRACTION_MINIMUM_TERMS = 1000
CONTINUED_FRACTION_MAXIMUM_TERMS = 60_000


def singular_point_characteristic_exponents(
    omega: complex, spin: float, s: int, m: int
) -> tuple[complex, complex, complex]:
    root_term = np.sqrt(1 - spin * spin)
    radius_plus, radius_minus = 1 + root_term, 1 - root_term
    sigma_plus = (2 * omega * radius_plus - m * spin) / (2 * root_term)
    sigma_minus = (2 * omega * radius_minus - m * spin) / (2 * root_term)
    return 1j * omega, -s - 1j * sigma_plus, -1j * sigma_minus


def recurrence_coefficients(
    omega: complex, spin: float, s: int, m: int, separation: complex
) -> np.ndarray:
    zeta, xi, eta = singular_point_characteristic_exponents(
        omega, spin, s, m
    )
    root_term = np.sqrt(1 - spin * spin)
    p_value = root_term * zeta
    alpha = 1 + s + xi + eta - 2 * zeta + s
    gamma = 1 + s + 2 * eta
    delta = 1 + s + 2 * xi
    sigma = (
        separation
        + spin * spin * omega * omega
        - 8 * omega * omega
        + p_value * (2 * alpha + gamma - delta)
        + (1 + s - 0.5 * (gamma + delta))
        * (s + 0.5 * (gamma + delta))
    )
    return np.array(
        [
            delta,
            4 * p_value - 2 * alpha + gamma - delta - 2,
            2 * alpha - gamma + 2,
            alpha * (4 * p_value - delta) - sigma,
            alpha * (alpha - gamma + 1),
        ],
        complex,
    )


def leaver_continued_fraction(
    omega: complex,
    spin: float,
    s: int,
    m: int,
    separation: complex,
    inversion_index: int,
    tolerance: float = CONTINUED_FRACTION_TOLERANCE,
    minimum_terms: int = CONTINUED_FRACTION_MINIMUM_TERMS,
    maximum_terms: int = CONTINUED_FRACTION_MAXIMUM_TERMS,
) -> tuple[complex, float, int]:
    coefficients = recurrence_coefficients(omega, spin, s, m, separation)
    indices = np.arange(inversion_index + 1, dtype=float)
    alpha = indices * indices + (coefficients[0] + 1) * indices + coefficients[0]
    beta = -2 * indices * indices + (coefficients[1] + 2) * indices + coefficients[3]
    gamma = (
        indices * indices
        + (coefficients[2] - 3) * indices
        + coefficients[4]
        - coefficients[2]
        + 2
    )
    convergent = 0j
    for index in range(inversion_index):
        convergent = alpha[index] / (
            beta[index] - gamma[index] * convergent
        )
    tiny = 1e-30
    fraction_old = tiny + 0j
    c_old = fraction_old
    d_old = 0j
    iterations = 1
    n_value = inversion_index
    delta_value = 99 + 0j
    while iterations < maximum_terms:
        numerator = -(
            n_value * n_value
            + (coefficients[0] + 1) * n_value
            + coefficients[0]
        ) / (
            n_value * n_value
            + (coefficients[2] - 3) * n_value
            + coefficients[4]
            - coefficients[2]
            + 2
        )
        n_value += 1
        denominator = (
            -2 * n_value * n_value
            + (coefficients[1] + 2) * n_value
            + coefficients[3]
        ) / (
            n_value * n_value
            + (coefficients[2] - 3) * n_value
            + coefficients[4]
            - coefficients[2]
            + 2
        )
        d_new = denominator + numerator * d_old
        if d_new == 0:
            d_new = tiny
        c_new = denominator + numerator / c_old
        if c_new == 0:
            c_new = tiny
        d_new = 1 / d_new
        delta_value = c_new * d_new
        fraction_new = fraction_old * delta_value
        iterations += 1
        d_old, c_old, fraction_old = d_new, c_new, fraction_new
        if iterations > minimum_terms and abs(delta_value - 1) < tolerance:
            break
    value = (
        beta[inversion_index]
        - gamma[inversion_index] * convergent
        + gamma[inversion_index] * fraction_old
    )
    return complex(value), float(abs(delta_value - 1)), iterations - 1


def coupled_error(
    omega: complex,
    spin: float,
    s: int,
    ell: int,
    m: int,
    n: int,
    angular_padding: int = 14,
) -> tuple[complex, complex, float, int]:
    spherical = angular.swsphericalh_A(s, ell, m)
    separation = angular.sep_const_closest(
        spherical, s, spin * omega, m, ell + angular_padding
    )
    value, error, iterations = leaver_continued_fraction(
        omega, spin, s, m, separation, n
    )
    return value, separation, error, iterations


def solve_mode(
    spin: float,
    s: int,
    ell: int,
    m: int,
    n: int,
    guess: complex,
    angular_padding: int = 14,
    tolerance: float = 1e-11,
) -> tuple[complex, complex, float, float, int, bool, str]:
    def residual(coordinates: np.ndarray) -> list[float]:
        omega = coordinates[0] + 1j * coordinates[1]
        value, _, _, _ = coupled_error(
            omega, spin, s, ell, m, n, angular_padding
        )
        return [float(value.real), float(value.imag)]

    result = root(
        residual,
        [guess.real, guess.imag],
        method="hybr",
        tol=tolerance,
    )
    omega = complex(result.x[0], result.x[1])
    value, separation, error, iterations = coupled_error(
        omega, spin, s, ell, m, n, angular_padding
    )
    return (
        omega,
        separation,
        float(abs(value)),
        error,
        iterations,
        bool(result.success),
        str(result.message),
    )


# Neutral aliases make provenance comparisons with the source snapshot exact.
sing_pt_char_exps = singular_point_characteristic_exponents
D_coeffs = recurrence_coefficients
leaver_cf = leaver_continued_fraction
