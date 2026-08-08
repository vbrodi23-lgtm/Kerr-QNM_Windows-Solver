"""Concrete vetted GSN determinant kernel for selected response jobs.

Construction authenticates the immutable coefficient cache before importing
the optional numerical stack.  The module never generates that cache and
performs no numerical work during import or validation.
"""

from __future__ import annotations

import cmath
from dataclasses import replace
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import platform
import struct
from typing import Callable, Mapping

from .response_engine import (
    BackendIdentity,
    DeterminantPartials,
    ExteriorPerturbation,
    HorizonPerturbation,
    NumericalPolicy,
    ResponseComponentJob,
    RootReadout,
)


PINNED_GSN_CACHE_SHA256 = (
    "0c49fe4c2839444422b2d0ebcf08c912ee06d7e60ed398c9b360ed4c151f28d3"
)
PINNED_POTENTIALS_SHA256 = (
    "8f60c740be8049878cf8cb3f58cd2c6676f10cc9c23cab13c5ce8af9ef3ae860"
)
_SOURCE_COMMIT = "0c1e8a3d3bca6e608c34e111476a4f6dcb73e86e"
_SOURCE_BLOBS = (
    ("determinant-backend", "b65f2236f828204aa21dfa8d9bc79c8a1c66ca3b"),
    ("standard-radial-equation", "e03764330c52fcc1753cd6279162c967e53fea93"),
    ("angular-spectral-equation", "60bfe6e76911916274df903fcac11b3d75079297"),
    ("spin-minus-two-equations", "d0d5c164871d2218bdaf76f9b59e97c128aa06cc"),
    ("exterior-common", "04baf49cf29e0e27ec7ae2bc68eea42703156805"),
    ("exterior-direct", "2e161c284ba841b403883449ebb78db57c849d9e"),
    ("horizon-coordinate", "ac72dd29ed506430fe2d8e88f5a7569debd196eb"),
    ("horizon-sensitivity", "0f7b3a67f99905f4c09e5f07b81a9e82f7673a8a"),
    ("gsn-potential-expressions", "34af90dd81e6e0f60823b338488d8d9587e2cc6a"),
)
_DERIVATIVE_STEP = 1.0e-5
_BRANCH_CONTINUATION_TOLERANCE_ABS = 5.0e-3
# Stable across source checkouts and wheels; source_commit/source_blobs below
# retain the authenticated upstream code identity.
_ADAPTED_SOURCE_CONTRACT_ID = "native-gsn-adapter-contract-1"


class NativeResourceUnavailableError(RuntimeError):
    """A required authenticated native resource is absent or unusable."""


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise NativeResourceUnavailableError(
                f"authenticated GSN cache has duplicate key {key!r}"
            )
        value[key] = item
    return value


def _native_identity() -> BackendIdentity:
    return BackendIdentity(
        backend_id="vetted-native-gsn-determinant",
        implementation_version="1",
        source_commit=_SOURCE_COMMIT,
        source_blobs=_SOURCE_BLOBS,
        runtime_fingerprint=(
            f"cpython-{platform.python_version()}-{platform.system().lower()}-"
            f"python-{8 * struct.calcsize('P')}bit-"
            f"gsn-cache-{PINNED_GSN_CACHE_SHA256}-"
            f"adapted-source-{_ADAPTED_SOURCE_CONTRACT_ID}"
        ),
    )


class VettedNativeDeterminantKernel:
    """Concrete same-equation horizon/exterior determinant and root kernel."""

    identity = _native_identity()

    def __init__(self, cache_path: Path, standard_sn_type: type) -> None:
        self.cache_path = cache_path
        self._standard_sn_type = standard_sn_type

    @classmethod
    def from_authenticated_resource(
        cls, cache_path: str | os.PathLike[str] | Path
    ) -> "VettedNativeDeterminantKernel":
        path = Path(cache_path)
        if not path.is_file():
            raise NativeResourceUnavailableError(
                f"authenticated GSN infinity-series resource is absent: {path}"
            )
        if path.is_symlink():
            raise NativeResourceUnavailableError(
                "authenticated GSN infinity-series resource must not be a symlink"
            )
        raw = path.read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        if actual != PINNED_GSN_CACHE_SHA256:
            raise NativeResourceUnavailableError(
                "authenticated GSN infinity-series resource digest mismatch"
            )
        try:
            value = json.loads(
                raw,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=lambda item: (_ for _ in ()).throw(
                    NativeResourceUnavailableError(
                        f"authenticated GSN cache contains non-finite constant {item}"
                    )
                ),
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise NativeResourceUnavailableError(
                "authenticated GSN infinity-series resource is invalid JSON"
            ) from error
        if (
            not isinstance(value, Mapping)
            or not isinstance(value.get("records"), Mapping)
            or not value["records"]
        ):
            raise NativeResourceUnavailableError(
                "authenticated GSN infinity-series resource has no records"
            )

        potentials = (
            Path(__file__).resolve().parent
            / "data"
            / "native_kernel"
            / "potentials.fixture"
        )
        if (
            not potentials.is_file()
            or hashlib.sha256(potentials.read_bytes()).hexdigest()
            != PINNED_POTENTIALS_SHA256
        ):
            raise NativeResourceUnavailableError(
                "authenticated GSN potential expression resource is absent or changed"
            )

        os.environ["GSN_INFINITY_SERIES_CACHE"] = str(path.resolve())
        os.environ["GSN_INFINITY_SERIES_CACHE_SHA256"] = PINNED_GSN_CACHE_SHA256
        try:
            module = importlib.import_module("windows_solver._native_sn_standard")
        except (ImportError, OSError, RuntimeError) as error:
            raise NativeResourceUnavailableError(
                f"vetted native numerical dependencies are unavailable: {error}"
            ) from error
        return cls(path.resolve(), module.StandardSN)

    def _standard_sn(
        self, job: ResponseComponentJob, policy: NumericalPolicy
    ) -> object:
        return self._standard_sn_type(
            job.spin,
            job.mode.ell,
            job.mode.m,
            horizon_order=policy.endpoint_series_order,
            horizon_cauchy_sample_count=max(
                256, 2 * (policy.endpoint_series_order + 1)
            ),
            integration_relative_tolerance=policy.ode_relative_tolerance,
            integration_absolute_tolerance=policy.ode_absolute_tolerance,
            real_maximum_step=0.2,
        )

    @staticmethod
    def _horizon_seed_branch(
        sn: object,
        omega: complex,
        separation: complex,
        sign: int,
        radius: float,
    ) -> tuple[complex, complex]:
        import numpy as np

        order = sn.horizon_order
        x = radius - sn.rp
        gap = sn.rp - sn.rm
        scale = min(0.05, max(1.0e-5, 0.2 * gap))
        count = max(sn.horizon_cauchy_sample_count, 2 * (order + 1))
        theta = 2.0 * np.pi * np.arange(count) / count
        z = scale * np.exp(1.0j * theta)
        radii = sn.rp + z
        pbar = z * np.asarray(sn._pfn(radii, omega, separation), complex)
        qbar = z * z * np.asarray(sn._qfn(radii, omega, separation), complex)
        phase = np.exp(-1.0j * np.outer(np.arange(order + 1), theta))
        p_coefficients = (phase @ pbar) / count
        q_coefficients = (phase @ qbar) / count
        horizon_frequency = omega - sn.m * sn.OmH
        conversion = (sn.rp * sn.rp + sn.a * sn.a) / gap
        exponent = sign * 1.0j * horizon_frequency * conversion
        coefficients = np.zeros(order + 1, complex)
        coefficients[0] = 1.0
        for index in range(1, order + 1):
            denominator = (
                (exponent + index) * (exponent + index - 1)
                + p_coefficients[0] * (exponent + index)
                + q_coefficients[0]
            )
            coefficients[index] = -sum(
                (
                    p_coefficients[index - previous] * (exponent + previous)
                    + q_coefficients[index - previous]
                )
                * coefficients[previous]
                for previous in range(index)
            ) / denominator
        t = x / scale
        series = sum(coefficients[k] * t**k for k in range(order + 1))
        derivative = sum(
            k * coefficients[k] * t ** (k - 1)
            for k in range(1, order + 1)
        ) / scale
        value = x**exponent * series
        radial_derivative = x**exponent * (exponent * series / x + derivative)
        constant = (
            sn.rp
            - conversion * math.log(2.0)
            - 2.0 * sn.rm / gap * math.log(gap / 2.0)
        )
        normalization = cmath.exp(sign * 1.0j * horizon_frequency * constant)
        return normalization * value, normalization * radial_derivative

    @classmethod
    def _integrate_horizon_branch(
        cls, sn: object, omega: complex, sign: int, readout: float
    ) -> object:
        separation, _ = sn.lambda_phys(omega)
        radius = sn.rp + min(2.0e-4, 0.02 * (sn.rp - sn.rm))
        seed = cls._horizon_seed_branch(
            sn, omega, separation, sign, radius
        )
        return sn.integrate_real(
            omega, separation, radius, readout, seed
        ).y[:, -1]

    @staticmethod
    def _integrate_exterior(
        sn: object,
        omega: complex,
        separation: complex,
        start: float,
        stop: float,
        seed: object,
        perturbation: ExteriorPerturbation,
        policy: NumericalPolicy,
    ) -> object:
        import numpy as np
        from scipy.integrate import solve_ivp

        def equation(radius: float, state: object) -> object:
            p_value = complex(sn._pfn(radius, omega, separation))
            q_value = complex(sn._qfn(radius, omega, separation))
            q_value += perturbation.profile_value(radius)
            return np.asarray(
                (state[1], -p_value * state[1] - q_value * state[0]),
                dtype=complex,
            )

        boundaries = [float(start), float(stop)]
        lower, upper = sorted((float(start), float(stop)))
        boundaries.extend(
            value
            for value in (perturbation.support.lower, perturbation.support.upper)
            if lower < value < upper
        )
        boundaries = sorted(set(boundaries), reverse=stop < start)
        state = np.asarray(seed, dtype=complex)
        for left, right in zip(boundaries[:-1], boundaries[1:]):
            midpoint = 0.5 * (left + right)
            inside = perturbation.support.lower <= midpoint <= perturbation.support.upper
            step = 0.2
            if inside:
                step = min(
                    step,
                    (perturbation.support.upper - perturbation.support.lower)
                    / policy.support_subinterval_count,
                )
            solution = solve_ivp(
                equation,
                (left, right),
                state,
                method="DOP853",
                rtol=policy.ode_relative_tolerance,
                atol=policy.ode_absolute_tolerance,
                max_step=step,
            )
            if not solution.success:
                raise RuntimeError(solution.message)
            state = solution.y[:, -1]
        return state

    @classmethod
    def _determinant(
        cls,
        sn: object,
        omega: complex,
        perturbation: HorizonPerturbation | ExteriorPerturbation,
        policy: NumericalPolicy,
    ) -> complex:
        readout = policy.readout_radius
        if isinstance(perturbation, HorizonPerturbation):
            outgoing, _ = sn.outgoing_at(omega, readout)
            ingoing = cls._integrate_horizon_branch(sn, omega, -1, readout)
            outgoing_horizon = cls._integrate_horizon_branch(
                sn, omega, +1, readout
            )
            reflectivity = perturbation.reflectivity(omega)
            horizon = ingoing + reflectivity * outgoing_horizon
            return sn.wfac(readout) * (
                horizon[0] * outgoing[1] - horizon[1] * outgoing[0]
            )

        separation, _ = sn.lambda_phys(omega)
        horizon_radius = sn.rp + min(2.0e-4, 0.02 * (sn.rp - sn.rm))
        horizon_seed = sn.horizon_seed(omega, separation, horizon_radius)
        infinity_radius, infinity_seed = sn.outgoing_real_seed(omega, separation)
        horizon = cls._integrate_exterior(
            sn,
            omega,
            separation,
            horizon_radius,
            readout,
            horizon_seed,
            perturbation,
            policy,
        )
        infinity = cls._integrate_exterior(
            sn,
            omega,
            separation,
            infinity_radius,
            readout,
            infinity_seed,
            perturbation,
            policy,
        )
        return sn.wfac(readout) * (
            horizon[0] * infinity[1] - horizon[1] * infinity[0]
        )

    @staticmethod
    def _bounded_newton(
        determinant: Callable[[complex], complex], guess: complex
    ) -> tuple[complex, float, bool]:
        value = complex(guess)
        best = (value, abs(determinant(value)))
        for _ in range(12):
            residual = determinant(value)
            magnitude = abs(residual)
            if magnitude < best[1]:
                best = value, magnitude
            if magnitude < 2.0e-11:
                return value, magnitude, True
            h = _DERIVATIVE_STEP * (1.0 + abs(value))
            derivative = (determinant(value + h) - determinant(value - h)) / (2.0 * h)
            if not math.isfinite(abs(derivative)) or derivative == 0.0j:
                break
            step = residual / derivative
            if abs(step) > 6.0e-3:
                step *= 6.0e-3 / abs(step)
            for damping in (1.0, 0.5, 0.25, 0.125):
                candidate = value - damping * step
                if abs(determinant(candidate)) < magnitude:
                    value = candidate
                    break
            else:
                value -= 0.125 * step
        return best[0], best[1], best[1] < 2.0e-11

    def _solve_once(
        self,
        *,
        sn: object,
        job: ResponseComponentJob,
        perturbation: HorizonPerturbation | ExteriorPerturbation,
        policy: NumericalPolicy,
        guess: complex,
    ) -> tuple[complex, float, float, bool]:
        determinant = lambda omega: self._determinant(
            sn, complex(omega), perturbation, policy
        )
        root, residual, converged = self._bounded_newton(determinant, guess)
        h = _DERIVATIVE_STEP * (1.0 + abs(root))
        derivative = abs(
            (determinant(root + h) - determinant(root - h)) / (2.0 * h)
        )
        if not math.isfinite(derivative) or derivative <= 0.0:
            raise NativeResourceUnavailableError(
                "native determinant frequency derivative is not usable"
            )
        return root, residual, derivative, converged

    def evaluate_root(
        self,
        *,
        job: ResponseComponentJob,
        background_root: object,
        perturbation: HorizonPerturbation | ExteriorPerturbation,
        policy: NumericalPolicy,
    ) -> RootReadout:
        primary_sn = self._standard_sn(job, policy)
        root, residual, derivative, primary_converged = self._solve_once(
            sn=primary_sn,
            job=job,
            perturbation=perturbation,
            policy=policy,
            guess=background_root.omega,
        )

        truncation_policy = replace(
            policy, endpoint_series_order=policy.endpoint_series_order + 8
        )
        truncation_root, _, _, truncation_converged = self._solve_once(
            sn=self._standard_sn(job, truncation_policy),
            job=job,
            perturbation=perturbation,
            policy=truncation_policy,
            guess=root,
        )

        resolution_policy = replace(
            policy,
            ode_relative_tolerance=policy.ode_relative_tolerance / 2.0,
            ode_absolute_tolerance=policy.ode_absolute_tolerance / 2.0,
            support_subinterval_count=policy.support_subinterval_count * 2,
        )
        resolution_root, _, _, resolution_converged = self._solve_once(
            sn=self._standard_sn(job, resolution_policy),
            job=job,
            perturbation=perturbation,
            policy=resolution_policy,
            guess=root,
        )

        alternate_guess = background_root.omega + complex(2.5e-4, 1.25e-4) * (
            1.0 + abs(background_root.omega)
        )
        seed_path_root, _, _, seed_path_converged = self._solve_once(
            sn=primary_sn,
            job=job,
            perturbation=perturbation,
            policy=policy,
            guess=alternate_guess,
        )
        diagnostic_roots = (truncation_root, resolution_root, seed_path_root)
        branch_continuation_valid = (
            abs(root - background_root.omega)
            <= _BRANCH_CONTINUATION_TOLERANCE_ABS
            and all(
                abs(candidate - root) <= _BRANCH_CONTINUATION_TOLERANCE_ABS
                for candidate in diagnostic_roots
            )
        )
        diagnostics_converged = all(
            (
                primary_converged,
                truncation_converged,
                resolution_converged,
                seed_path_converged,
            )
        )
        converged = diagnostics_converged and branch_continuation_valid
        return RootReadout(
            omega=root,
            determinant_residual_abs=residual,
            determinant_derivative_abs=derivative,
            converged=converged,
            root_reference_id=background_root.root_reference_id,
            branch_id=(
                background_root.branch_id
                if converged
                else "nonmatching-native-continuation"
            ),
            equation_id=job.equation_id,
            truncation_radius=abs(truncation_root - root),
            resolution_radius=abs(resolution_root - root),
            seed_path_radius=abs(seed_path_root - root),
        )

    def horizon_partials(
        self,
        *,
        job: ResponseComponentJob,
        background_root: object,
        policy: NumericalPolicy,
    ) -> DeterminantPartials:
        sn = self._standard_sn(job, policy)
        omega = background_root.omega
        h = _DERIVATIVE_STEP * (1.0 + abs(omega))
        zero = HorizonPerturbation(0.0j, job.spin, job.mode.m)
        frequency = (
            self._determinant(sn, omega + h, zero, policy)
            - self._determinant(sn, omega - h, zero, policy)
        ) / (2.0 * h)
        outgoing, _ = sn.outgoing_at(omega, policy.readout_radius)
        outgoing_horizon = self._integrate_horizon_branch(
            sn, omega, +1, policy.readout_radius
        )
        reflectivity_partial = sn.wfac(policy.readout_radius) * (
            outgoing_horizon[0] * outgoing[1]
            - outgoing_horizon[1] * outgoing[0]
        )
        horizon_frequency = omega - job.mode.m * sn.OmH
        if horizon_frequency == 0.0j:
            coordinate = complex(math.nan, math.nan)
        else:
            coordinate = reflectivity_partial / (2.0j * horizon_frequency)
        return DeterminantPartials(
            frequency_derivative=frequency,
            coordinate_derivative=coordinate,
            simple_root_valid=(
                math.isfinite(abs(frequency))
                and frequency != 0.0j
                and math.isfinite(abs(coordinate))
            ),
        )
