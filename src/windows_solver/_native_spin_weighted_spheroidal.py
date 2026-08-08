"""Spin-weighted spheroidal angular eigenvalue solver.

This module is self-contained.  It replaces both ``qnm.angular`` and
``pybhpt.swsh`` for the subset of functionality used in the validated Kerr
source calculations.

Conventions
-----------
* Time dependence is exp(-i omega t).
* The angular equation uses the Teukolsky separation eigenvalue A.
* The spherical basis is orthonormal on the full sphere.
* ``angular_values(..., theta_only=True)`` converts from full-sphere
  normalization to unit theta-only normalization by multiplying by
  sqrt(2*pi).
* Eigenvector phases are fixed deterministically by requiring the target
  spherical component to be real and positive.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

import numpy as np
from scipy.special import gammaln


def _arbitrary_precision_module():
    try:
        import mpmath
    except ImportError as error:
        raise RuntimeError(
            "arbitrary-precision angular diagnostics require optional mpmath"
        ) from error
    return mpmath


class _LazyArbitraryPrecision:
    def __getattr__(self, name: str):
        return getattr(_arbitrary_precision_module(), name)


mp = _LazyArbitraryPrecision()


def _calF(s: int, ell: int, m: int) -> float:
    if s == 0 and ell + 1 == 0:
        return 0.0
    return float(
        np.sqrt(
            (((ell + 1) ** 2 - m * m) / ((2 * ell + 3) * (2 * ell + 1)))
            * (((ell + 1) ** 2 - s * s) / (ell + 1) ** 2)
        )
    )


def _calG(s: int, ell: int, m: int) -> float:
    if ell == 0:
        return 0.0
    return float(np.sqrt((ell * ell - m * m) / (4 * ell * ell - 1) * (1 - s * s / ell**2)))


def _calH(s: int, ell: int, m: int) -> float:
    if ell == 0 or s == 0:
        return 0.0
    return -m * s / ell / (ell + 1)


def _calA(s: int, ell: int, m: int) -> float:
    return _calF(s, ell, m) * _calF(s, ell + 1, m)


def _calD(s: int, ell: int, m: int) -> float:
    return _calF(s, ell, m) * (_calH(s, ell + 1, m) + _calH(s, ell, m))


def _calB(s: int, ell: int, m: int) -> float:
    return (
        _calF(s, ell, m) * _calG(s, ell + 1, m)
        + _calG(s, ell, m) * _calF(s, ell - 1, m)
        + _calH(s, ell, m) ** 2
    )


def _calE(s: int, ell: int, m: int) -> float:
    return _calG(s, ell, m) * (_calH(s, ell - 1, m) + _calH(s, ell, m))


def _calC(s: int, ell: int, m: int) -> float:
    return _calG(s, ell, m) * _calG(s, ell - 1, m)


def _calF_mp(s: int, ell: int, m: int) -> mp.mpf:
    """Arbitrary-precision counterpart of :func:`_calF`."""

    if s == 0 and ell + 1 == 0:
        return mp.mpf("0")
    ell_plus_one = mp.mpf(ell + 1)
    return mp.sqrt(
        (
            (ell_plus_one**2 - m * m)
            / ((2 * ell + 3) * (2 * ell + 1))
        )
        * ((ell_plus_one**2 - s * s) / ell_plus_one**2)
    )


def _calG_mp(s: int, ell: int, m: int) -> mp.mpf:
    """Arbitrary-precision counterpart of :func:`_calG`."""

    if ell == 0:
        return mp.mpf("0")
    ell_mp = mp.mpf(ell)
    return mp.sqrt(
        (ell_mp**2 - m * m)
        / (4 * ell_mp**2 - 1)
        * (1 - mp.mpf(s * s) / ell_mp**2)
    )


def _calH_mp(s: int, ell: int, m: int) -> mp.mpf:
    """Arbitrary-precision counterpart of :func:`_calH`."""

    if ell == 0 or s == 0:
        return mp.mpf("0")
    return -mp.mpf(m * s) / ell / (ell + 1)


def _calA_mp(s: int, ell: int, m: int) -> mp.mpf:
    return _calF_mp(s, ell, m) * _calF_mp(s, ell + 1, m)


def _calD_mp(s: int, ell: int, m: int) -> mp.mpf:
    return _calF_mp(s, ell, m) * (
        _calH_mp(s, ell + 1, m) + _calH_mp(s, ell, m)
    )


def _calB_mp(s: int, ell: int, m: int) -> mp.mpf:
    return (
        _calF_mp(s, ell, m) * _calG_mp(s, ell + 1, m)
        + _calG_mp(s, ell, m) * _calF_mp(s, ell - 1, m)
        + _calH_mp(s, ell, m) ** 2
    )


def _calE_mp(s: int, ell: int, m: int) -> mp.mpf:
    return _calG_mp(s, ell, m) * (
        _calH_mp(s, ell - 1, m) + _calH_mp(s, ell, m)
    )


def _calC_mp(s: int, ell: int, m: int) -> mp.mpf:
    return _calG_mp(s, ell, m) * _calG_mp(s, ell - 1, m)


def swsphericalh_A(s: int, ell: int, m: int) -> int:
    """Spherical-limit angular eigenvalue A_{s ell m}(0)."""
    del m
    return ell * (ell + 1) - s * (s + 1)


# Compatibility alias used by newer code.
spherical_A = swsphericalh_A


def l_min(s: int, m: int) -> int:
    return max(abs(s), abs(m))


def ells(s: int, m: int, l_max: int) -> np.ndarray:
    return np.arange(l_min(s, m), l_max + 1, dtype=int)


def M_matrix_elem(s: int, c: complex, m: int, ell: int, ell_prime: int) -> complex:
    if ell_prime == ell - 2:
        return -c * c * _calA(s, ell_prime, m)
    if ell_prime == ell - 1:
        return -c * c * _calD(s, ell_prime, m) + 2 * c * s * _calF(s, ell_prime, m)
    if ell_prime == ell:
        return (
            swsphericalh_A(s, ell_prime, m)
            - c * c * _calB(s, ell_prime, m)
            + 2 * c * s * _calH(s, ell_prime, m)
        )
    if ell_prime == ell + 1:
        return -c * c * _calE(s, ell_prime, m) + 2 * c * s * _calG(s, ell_prime, m)
    if ell_prime == ell + 2:
        return -c * c * _calC(s, ell_prime, m)
    return 0.0j


def M_matrix(s: int, c: complex, m: int, l_max: int) -> np.ndarray:
    ls = ells(s, m, l_max)
    mat = np.empty((len(ls), len(ls)), dtype=complex)
    for i, ell in enumerate(ls):
        for j, ell_prime in enumerate(ls):
            mat[i, j] = M_matrix_elem(s, c, m, int(ell), int(ell_prime))
    return mat


def M_matrix_elem_mp(
    s: int,
    c: mp.mpc,
    m: int,
    ell: int,
    ell_prime: int,
) -> mp.mpc:
    """High-precision angular-matrix entry without binary64 intermediates."""

    if ell_prime == ell - 2:
        return -c * c * _calA_mp(s, ell_prime, m)
    if ell_prime == ell - 1:
        return -c * c * _calD_mp(s, ell_prime, m) + 2 * c * s * _calF_mp(
            s, ell_prime, m
        )
    if ell_prime == ell:
        return (
            swsphericalh_A(s, ell_prime, m)
            - c * c * _calB_mp(s, ell_prime, m)
            + 2 * c * s * _calH_mp(s, ell_prime, m)
        )
    if ell_prime == ell + 1:
        return -c * c * _calE_mp(s, ell_prime, m) + 2 * c * s * _calG_mp(
            s, ell_prime, m
        )
    if ell_prime == ell + 2:
        return -c * c * _calC_mp(s, ell_prime, m)
    return mp.mpc(0)


def M_matrix_mp(s: int, c: mp.mpc, m: int, l_max: int) -> mp.matrix:
    """Return the arbitrary-precision complex-symmetric angular matrix."""

    basis = range(l_min(s, m), l_max + 1)
    basis_list = list(basis)
    matrix_mp = mp.matrix(len(basis_list), len(basis_list))
    for row, ell in enumerate(basis_list):
        for column, ell_prime in enumerate(basis_list):
            matrix_mp[row, column] = M_matrix_elem_mp(
                s, c, m, ell, ell_prime
            )
    return matrix_mp


# Compatibility aliases.
matrix = M_matrix
matrix_elem = M_matrix_elem


def sep_consts(s: int, c: complex, m: int, l_max: int) -> np.ndarray:
    return np.linalg.eigvals(M_matrix(s, c, m, l_max))


def sep_const_closest(A0: complex, s: int, c: complex, m: int, l_max: int) -> complex:
    vals = sep_consts(s, c, m, l_max)
    return complex(vals[int(np.argmin(np.abs(vals - A0)))])


@dataclass(frozen=True)
class AngularEigenpair:
    A: complex
    coefficients: np.ndarray
    ells: np.ndarray


def eigenpair(s: int, c: complex, m: int, ell: int, l_max: int | None = None) -> AngularEigenpair:
    if l_max is None:
        l_max = ell + 16
    ls = ells(s, m, l_max)
    vals, vecs = np.linalg.eig(M_matrix(s, c, m, l_max))
    idx = int(np.argmin(np.abs(vals - swsphericalh_A(s, ell, m))))
    coeff = np.asarray(vecs[:, idx], dtype=complex)
    coeff /= np.linalg.norm(coeff)

    # Deterministic analytic phase: target spherical component real-positive.
    target = int(ell - ls[0])
    if abs(coeff[target]) > 0:
        coeff *= np.exp(-1j * np.angle(coeff[target]))
    if coeff[target].real < 0:
        coeff *= -1
    return AngularEigenpair(complex(vals[idx]), coeff, ls)


def C_and_sep_const_closest(
    A0: complex,
    s: int,
    c: complex,
    m: int,
    l_max: int,
) -> tuple[complex, np.ndarray]:
    """Compatibility replacement for ``qnm.angular.C_and_sep_const_closest``."""
    vals, vecs = np.linalg.eig(M_matrix(s, c, m, l_max))
    idx = int(np.argmin(np.abs(vals - A0)))
    coeff = np.asarray(vecs[:, idx], dtype=complex)
    coeff /= np.linalg.norm(coeff)

    # Identify the target spherical basis vector from A0 when possible.
    ls = ells(s, m, l_max)
    target = int(np.argmin(np.abs(np.array([swsphericalh_A(s, int(ll), m) for ll in ls]) - A0)))
    if abs(coeff[target]) > 0:
        coeff *= np.exp(-1j * np.angle(coeff[target]))
    if coeff[target].real < 0:
        coeff *= -1
    return complex(vals[idx]), coeff


def sep_const(s: int, c: complex, m: int, ell: int, l_max: int | None = None) -> complex:
    return eigenpair(s, c, m, ell, l_max).A


def sep_const_mp(
    s: int,
    c: complex | mp.mpc,
    m: int,
    ell: int,
    l_max: int | None = None,
    *,
    dps: int = 80,
) -> mp.mpc:
    """Return the target angular eigenvalue in arbitrary precision.

    The finite-spin manuscript selector subtracts two eigenvalues close to
    the spherical value and divides by a small ``a m``.  Binary64 is not a
    reliable arithmetic class for that audit.  This side path deliberately
    leaves the established binary64 eigenpair API unchanged for radial stages.
    """

    if l_max is None:
        l_max = ell + 16
    if dps < 30:
        raise ValueError("angular arbitrary precision must be at least 30 dps")
    with mp.workdps(dps):
        c_mp = mp.mpc(mp.mpf(c.real), mp.mpf(c.imag))
        values = mp.eig(
            M_matrix_mp(s, c_mp, m, l_max),
            left=False,
            right=False,
        )
        target = mp.mpf(swsphericalh_A(s, ell, m))
        selected = min(values, key=lambda value: abs(value - target))
        return mp.mpc(selected.real, selected.imag)


def _logfac(n: int) -> float:
    if n < 0:
        return float("inf")
    return float(gammaln(n + 1))


def wigner_d(ell: int, mp: int, m: int, theta: float) -> float:
    """Wigner small-d function in the Varshalovich convention."""
    kmin = max(0, m - mp)
    kmax = min(ell + m, ell - mp)
    ct = math.cos(theta / 2)
    st = math.sin(theta / 2)
    logpref = 0.5 * (
        _logfac(ell + m)
        + _logfac(ell - m)
        + _logfac(ell + mp)
        + _logfac(ell - mp)
    )
    total = 0.0
    for k in range(kmin, kmax + 1):
        den = (
            _logfac(ell + m - k)
            + _logfac(k)
            + _logfac(mp - m + k)
            + _logfac(ell - mp - k)
        )
        coeff = (-1) ** (k - m + mp) * math.exp(logpref - den)
        pc = 2 * ell + m - mp - 2 * k
        ps = mp - m + 2 * k
        total += coeff * (ct**pc) * (st**ps)
    return total


def spin_weighted_Y(s: int, ell: int, m: int, theta: float, phi: float = 0.0) -> complex:
    """Full-sphere-normalized spin-weighted spherical harmonic."""
    return (
        ((-1) ** s)
        * math.sqrt((2 * ell + 1) / (4 * math.pi))
        * wigner_d(ell, m, -s, theta)
        * np.exp(1j * m * phi)
    )


def spin_weighted_Y_derivative(
    s: int,
    ell: int,
    m: int,
    theta: float,
    phi: float = 0.0,
) -> complex:
    """Theta derivative via a deterministic five-point stencil."""
    h = 1.0e-6
    return (
        -spin_weighted_Y(s, ell, m, theta + 2 * h, phi)
        + 8 * spin_weighted_Y(s, ell, m, theta + h, phi)
        - 8 * spin_weighted_Y(s, ell, m, theta - h, phi)
        + spin_weighted_Y(s, ell, m, theta - 2 * h, phi)
    ) / (12 * h)


# pybhpt.swsh compatibility names.  These are full-sphere normalized.
def Yslm(s: int, ell: int, m: int, theta: float) -> complex:
    return spin_weighted_Y(s, ell, m, theta, 0.0)


def Yslm_derivative(s: int, ell: int, m: int, theta: float) -> complex:
    return spin_weighted_Y_derivative(s, ell, m, theta, 0.0)


def angular_values(
    s: int,
    ell: int,
    m: int,
    c: complex,
    theta: float = math.pi / 2,
    l_pad: int = 16,
    theta_only: bool = True,
) -> tuple[complex, complex, complex, np.ndarray, np.ndarray]:
    """Return spheroidal S, dS/dtheta, A, coefficients and basis ells.

    ``theta_only=True`` implements
    integral_0^pi |S(theta)|^2 sin(theta) dtheta = 1.
    """
    pair = eigenpair(s, c, m, ell, ell + l_pad)
    S = sum(
        pair.coefficients[i] * spin_weighted_Y(s, int(ll), m, theta, 0.0)
        for i, ll in enumerate(pair.ells)
    )
    Sp = sum(
        pair.coefficients[i] * spin_weighted_Y_derivative(s, int(ll), m, theta, 0.0)
        for i, ll in enumerate(pair.ells)
    )
    if theta_only:
        S *= math.sqrt(2 * math.pi)
        Sp *= math.sqrt(2 * math.pi)
    return complex(S), complex(Sp), pair.A, pair.coefficients.copy(), pair.ells.copy()


if __name__ == "__main__":
    # Minimal deterministic self-checks.
    y22 = spin_weighted_Y(-2, 2, 2, math.pi / 2)
    expected = math.sqrt(5 / (64 * math.pi))
    if abs(y22 - expected) > 2e-14:
        raise SystemExit(f"spherical harmonic check failed: {y22} vs {expected}")
    A, coeff = C_and_sep_const_closest(4.0, -2, 0.0j, 2, 18)
    if abs(A - 4.0) > 1e-13 or abs(abs(coeff[0]) - 1.0) > 1e-13:
        raise SystemExit("spherical-limit eigenpair check failed")
    print("spin_weighted_spheroidal_spectral self-check: PASS")
