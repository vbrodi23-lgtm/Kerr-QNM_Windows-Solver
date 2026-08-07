"""Spin-weighted spheroidal angular solver used by the offline Kerr builder.

This module is a formatting-only migration of the project's canonical angular
matrix implementation.  Its source identity is recorded in the lattice
receipt; it is deliberately kept outside the installed runtime package.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.special import gammaln


SOURCE_BLOB_SHA = "5d7641b349c4a1e1428629593cb2c81c441279a7"


def _cal_f(s: int, ell: int, m: int) -> float:
    if s == 0 and ell + 1 == 0:
        return 0.0
    return float(
        np.sqrt(
            (((ell + 1) ** 2 - m * m) / (2 * ell + 3) / (2 * ell + 1))
            * (((ell + 1) ** 2 - s * s) / (ell + 1) ** 2)
        )
    )


def _cal_g(s: int, ell: int, m: int) -> float:
    if ell == 0:
        return 0.0
    return float(
        np.sqrt(
            (ell * ell - m * m)
            / (4 * ell * ell - 1)
            * (1 - s * s / ell / ell)
        )
    )


def _cal_h(s: int, ell: int, m: int) -> float:
    if ell == 0 or s == 0:
        return 0.0
    return -m * s / ell / (ell + 1)


def _cal_a(s: int, ell: int, m: int) -> float:
    return _cal_f(s, ell, m) * _cal_f(s, ell + 1, m)


def _cal_d(s: int, ell: int, m: int) -> float:
    return _cal_f(s, ell, m) * (
        _cal_h(s, ell + 1, m) + _cal_h(s, ell, m)
    )


def _cal_b(s: int, ell: int, m: int) -> float:
    return (
        _cal_f(s, ell, m) * _cal_g(s, ell + 1, m)
        + _cal_g(s, ell, m) * _cal_f(s, ell - 1, m)
        + _cal_h(s, ell, m) ** 2
    )


def _cal_e(s: int, ell: int, m: int) -> float:
    return _cal_g(s, ell, m) * (
        _cal_h(s, ell - 1, m) + _cal_h(s, ell, m)
    )


def _cal_c(s: int, ell: int, m: int) -> float:
    return _cal_g(s, ell, m) * _cal_g(s, ell - 1, m)


def spherical_a(s: int, ell: int, m: int) -> int:
    del m
    return ell * (ell + 1) - s * (s + 1)


def ell_min(s: int, m: int) -> int:
    return max(abs(s), abs(m))


def ells(s: int, m: int, ell_max: int) -> np.ndarray:
    return np.arange(ell_min(s, m), ell_max + 1)


def matrix_element(
    s: int, c: complex, m: int, ell: int, ell_prime: int
) -> complex:
    if ell_prime == ell - 2:
        return -c * c * _cal_a(s, ell_prime, m)
    if ell_prime == ell - 1:
        return (
            -c * c * _cal_d(s, ell_prime, m)
            + 2 * c * s * _cal_f(s, ell_prime, m)
        )
    if ell_prime == ell:
        return (
            spherical_a(s, ell_prime, m)
            - c * c * _cal_b(s, ell_prime, m)
            + 2 * c * s * _cal_h(s, ell_prime, m)
        )
    if ell_prime == ell + 1:
        return (
            -c * c * _cal_e(s, ell_prime, m)
            + 2 * c * s * _cal_g(s, ell_prime, m)
        )
    if ell_prime == ell + 2:
        return -c * c * _cal_c(s, ell_prime, m)
    return 0j


def matrix(s: int, c: complex, m: int, ell_max: int) -> np.ndarray:
    ell_values = ells(s, m, ell_max)
    result = np.empty((len(ell_values), len(ell_values)), complex)
    for row, ell in enumerate(ell_values):
        for column, ell_prime in enumerate(ell_values):
            result[row, column] = matrix_element(
                s, c, m, int(ell), int(ell_prime)
            )
    return result


def eigenpair(
    s: int,
    c: complex,
    m: int,
    ell: int,
    ell_max: int | None = None,
) -> tuple[complex, np.ndarray, np.ndarray]:
    if ell_max is None:
        ell_max = ell + 16
    ell_values = ells(s, m, ell_max)
    values, vectors = np.linalg.eig(matrix(s, c, m, ell_max))
    index = int(np.argmin(np.abs(values - spherical_a(s, ell, m))))
    vector = np.asarray(vectors[:, index], complex)
    vector /= np.linalg.norm(vector)
    target = int(ell - ell_values[0])
    vector *= np.exp(-1j * np.angle(vector[target]))
    if vector[target].real < 0:
        vector *= -1
    return complex(values[index]), vector, ell_values


def separation_constant_closest(
    spherical_value: complex,
    s: int,
    c: complex,
    m: int,
    ell_max: int,
) -> complex:
    values = np.linalg.eigvals(matrix(s, c, m, ell_max))
    return complex(values[np.argmin(np.abs(values - spherical_value))])


def _log_factorial(value: int) -> float:
    if value < 0:
        return float("inf")
    return float(gammaln(value + 1))


def wigner_d(ell: int, mp: int, m: int, theta: float) -> float:
    minimum = max(0, m - mp)
    maximum = min(ell + m, ell - mp)
    cosine = math.cos(theta / 2)
    sine = math.sin(theta / 2)
    log_prefactor = 0.5 * (
        _log_factorial(ell + m)
        + _log_factorial(ell - m)
        + _log_factorial(ell + mp)
        + _log_factorial(ell - mp)
    )
    total = 0.0
    for index in range(minimum, maximum + 1):
        denominator = (
            _log_factorial(ell + m - index)
            + _log_factorial(index)
            + _log_factorial(mp - m + index)
            + _log_factorial(ell - mp - index)
        )
        coefficient = (-1) ** (index - m + mp) * math.exp(
            log_prefactor - denominator
        )
        cosine_power = 2 * ell + m - mp - 2 * index
        sine_power = mp - m + 2 * index
        total += coefficient * cosine**cosine_power * sine**sine_power
    return total


# Compatibility names retained inside the offline numerical boundary.
swsphericalh_A = spherical_a
sep_const_closest = separation_constant_closest

