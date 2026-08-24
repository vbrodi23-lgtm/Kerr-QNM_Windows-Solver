"""Concrete vetted GSN determinant kernel for selected response jobs.

Construction rehashes the generated coefficient cache before importing the
optional numerical stack.  The module never generates that cache and performs
no numerical work during import or validation.
"""

from __future__ import annotations

import cmath
from contextlib import contextmanager
from dataclasses import replace
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import platform
import re
import struct
import time
from typing import Callable, Mapping

from .response_engine import (
    BackendIdentity,
    Binary64FixedRootBatch,
    Binary64FixedRootSample,
    Binary64ReusedBackgroundBatch,
    BackgroundEquivalenceReceipt,
    CanonicalExteriorBackground,
    DiagnosticRootReadout,
    DeterminantPartials,
    ExteriorPerturbation,
    ExteriorBackgroundPerturbation,
    HorizonPerturbation,
    NumericalPolicy,
    ResponseComponentJob,
    RootReadout,
    _EXTERIOR_PROFILE_IDS,
    _exterior_support,
    build_exterior_background_reuse_key,
    exterior_background_reuse_admitted,
    mode_specific_branch_enclosure_radius,
)
from .progress import ProgressEventKind, emit_progress, progress_scope


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
_ROOT_CORRECTION_TOLERANCE = 2.0e-11
# Stable across source checkouts and wheels; source_commit/source_blobs below
# retain the authenticated upstream code identity.
_ADAPTED_SOURCE_CONTRACT_ID = "native-gsn-adapter-contract-2"
_GENERATED_INPUT_CONTRACT_ID = "julia-exact-f-u-cache-contract-1"
_POTENTIAL_SOURCE_PATH = (
    Path(__file__).resolve().parent / "data" / "native_kernel" / "potentials.fixture"
)


def _progress_complex(value: complex) -> dict[str, float]:
    converted = complex(value)
    return {"real": converted.real, "imaginary": converted.imag}


@contextmanager
def _progress_suboperation(name: str, **payload: object):
    started = time.monotonic()
    with progress_scope(suboperation=name):
        emit_progress(
            ProgressEventKind.SUBOPERATION_STARTED,
            suboperation=name,
            **payload,
        )
        try:
            yield
        except KeyboardInterrupt:
            raise
        except BaseException as error:
            emit_progress(
                ProgressEventKind.ERROR,
                suboperation=name,
                error_type=type(error).__name__,
                message=str(error),
                elapsed_seconds=time.monotonic() - started,
                **payload,
            )
            raise
        else:
            emit_progress(
                ProgressEventKind.SUBOPERATION_COMPLETED,
                suboperation=name,
                elapsed_seconds=time.monotonic() - started,
                **payload,
            )


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
        implementation_version="3",
        source_commit=_SOURCE_COMMIT,
        source_blobs=_SOURCE_BLOBS,
        runtime_fingerprint=(
            f"cpython-{platform.python_version()}-{platform.system().lower()}-"
            f"python-{8 * struct.calcsize('P')}bit-"
            f"gsn-input-{_GENERATED_INPUT_CONTRACT_ID}-"
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
    def from_generated_resource(
        cls,
        cache_path: str | os.PathLike[str] | Path,
        expected_sha256: str,
    ) -> "VettedNativeDeterminantKernel":
        """Bind a just-produced cache using its measured content identity."""

        if re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
            raise NativeResourceUnavailableError(
                "generated GSN infinity-series resource digest is invalid"
            )
        return cls._from_resource(cache_path, expected_sha256)

    @classmethod
    def _from_resource(
        cls,
        cache_path: str | os.PathLike[str] | Path,
        expected_sha256: str,
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
        if actual != expected_sha256:
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

        potentials = _POTENTIAL_SOURCE_PATH
        if not potentials.is_file() or potentials.is_symlink():
            raise NativeResourceUnavailableError(
                "GSN potential expression source is absent or not a regular file"
            )
        try:
            potential_source = potentials.read_bytes()
        except OSError as error:
            raise NativeResourceUnavailableError(
                "GSN potential expression source is unreadable"
            ) from error
        if not potential_source:
            raise NativeResourceUnavailableError(
                "GSN potential expression source is empty"
            )

        os.environ["GSN_INFINITY_SERIES_CACHE"] = str(path.resolve())
        os.environ["GSN_INFINITY_SERIES_CACHE_SHA256"] = expected_sha256
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
        with _progress_suboperation("angular"):
            separation, _ = sn.lambda_phys(omega)
        radius = sn.rp + min(2.0e-4, 0.02 * (sn.rp - sn.rm))
        seed = cls._horizon_seed_branch(
            sn, omega, separation, sign, radius
        )
        branch = "Xin" if sign < 0 else "Xup"
        with _progress_suboperation(branch):
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
        perturbation: ExteriorPerturbation | ExteriorBackgroundPerturbation,
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
        support = (
            perturbation.support
            if isinstance(perturbation, ExteriorPerturbation)
            else None
        )
        if support is not None:
            boundaries.extend(
                value
                for value in (support.lower, support.upper)
                if lower < value < upper
            )
        boundaries = sorted(set(boundaries), reverse=stop < start)
        state = np.asarray(seed, dtype=complex)
        segment_count = len(boundaries) - 1
        for segment_index, (left, right) in enumerate(
            zip(boundaries[:-1], boundaries[1:]), start=1
        ):
            midpoint = 0.5 * (left + right)
            inside = (
                support is not None
                and support.lower <= midpoint <= support.upper
            )
            step = 0.2
            if inside:
                step = min(
                    step,
                    (support.upper - support.lower)
                    / policy.support_subinterval_count,
                )
            with _progress_suboperation(
                "perturbed integration",
                segment_index=segment_index,
                segment_count=segment_count,
                start_radius=left,
                stop_radius=right,
            ):
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
        perturbation: (
            HorizonPerturbation
            | ExteriorPerturbation
            | ExteriorBackgroundPerturbation
        ),
        policy: NumericalPolicy,
    ) -> complex:
        readout = policy.readout_radius
        if isinstance(perturbation, HorizonPerturbation):
            with _progress_suboperation("Xup"):
                outgoing, _ = sn.outgoing_at(omega, readout)
            ingoing = cls._integrate_horizon_branch(sn, omega, -1, readout)
            outgoing_horizon = cls._integrate_horizon_branch(
                sn, omega, +1, readout
            )
            reflectivity = perturbation.reflectivity(omega)
            horizon = ingoing + reflectivity * outgoing_horizon
            with _progress_suboperation("Wronskian"):
                return sn.wfac(readout) * (
                    horizon[0] * outgoing[1] - horizon[1] * outgoing[0]
                )

        with _progress_suboperation("angular"):
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
        with _progress_suboperation("Wronskian"):
            return sn.wfac(readout) * (
                horizon[0] * infinity[1] - horizon[1] * infinity[0]
            )

    @staticmethod
    def _bounded_newton(
        determinant: Callable[[complex], complex], guess: complex
    ) -> tuple[complex, float, float | None, bool]:
        value = complex(guess)

        def evaluated(
            omega: complex, purpose: str, current: complex
        ) -> complex:
            candidate = complex(omega)
            started = time.monotonic()
            with progress_scope(
                determinant_purpose=purpose,
                current_omega=_progress_complex(current),
                candidate_omega=_progress_complex(candidate),
            ):
                emit_progress(
                    ProgressEventKind.DETERMINANT_STARTED,
                    purpose=purpose,
                    omega=_progress_complex(candidate),
                )
                result = determinant(candidate)
                emit_progress(
                    ProgressEventKind.DETERMINANT_COMPLETED,
                    purpose=purpose,
                    omega=_progress_complex(candidate),
                    determinant_real=complex(result).real,
                    determinant_imag=complex(result).imag,
                    determinant_abs=abs(result),
                    elapsed_seconds=time.monotonic() - started,
                )
                return result

        initial_residual = evaluated(value, "initial best", value)
        carried: tuple[complex, complex] | None = (value, initial_residual)
        best = (value, abs(initial_residual))
        for iteration in range(1, 13):
            iteration_started = time.monotonic()
            if carried is not None and carried[0] == value:
                residual = carried[1]
            else:
                residual = evaluated(value, "residual", value)
            carried = None
            magnitude = abs(residual)
            if magnitude < best[1]:
                best = value, magnitude
            with progress_scope(
                newton_index=iteration,
                newton_limit=12,
                current_omega=_progress_complex(value),
            ):
                emit_progress(
                    ProgressEventKind.NEWTON_ITERATION_STARTED,
                    current_omega=_progress_complex(value),
                    determinant_abs=magnitude,
                    best_determinant_abs=best[1],
                    acceptance_metric="newton_correction_estimate_abs",
                    acceptance_threshold=_ROOT_CORRECTION_TOLERANCE,
                )
                h = _DERIVATIVE_STEP * (1.0 + abs(value))
                derivative = (
                    evaluated(value + h, "derivative +h", value)
                    - evaluated(value - h, "derivative -h", value)
                ) / (2.0 * h)
                derivative_abs = abs(derivative)
                if not math.isfinite(derivative_abs) or derivative == 0.0j:
                    emit_progress(
                        ProgressEventKind.NEWTON_ITERATION_COMPLETED,
                        derivative_abs=derivative_abs,
                        raw_step=None,
                        applied_step=None,
                        step_abs=0.0,
                        clipped=False,
                        damping=0.0,
                        accepted=False,
                        resulting_omega=_progress_complex(value),
                        resulting_determinant_abs=magnitude,
                        elapsed_seconds=time.monotonic() - iteration_started,
                    )
                    break
                raw_step = residual / derivative
                correction_abs = abs(raw_step)
                if correction_abs <= _ROOT_CORRECTION_TOLERANCE:
                    emit_progress(
                        ProgressEventKind.NEWTON_ITERATION_COMPLETED,
                        derivative_abs=derivative_abs,
                        raw_step=_progress_complex(raw_step),
                        correction_abs=correction_abs,
                        applied_step=_progress_complex(0.0j),
                        step_abs=0.0,
                        clipped=False,
                        damping=0.0,
                        accepted=True,
                        resulting_omega=_progress_complex(value),
                        resulting_determinant_abs=magnitude,
                        elapsed_seconds=time.monotonic() - iteration_started,
                    )
                    return value, magnitude, derivative_abs, True
                step = raw_step
                clipped = abs(step) > 6.0e-3
                if clipped:
                    step *= 6.0e-3 / abs(step)
                accepted = False
                selected_damping = 0.125
                resulting_abs = magnitude
                for damping in (1.0, 0.5, 0.25, 0.125):
                    candidate = value - damping * step
                    candidate_residual = evaluated(
                        candidate, f"damping {damping:g}", value
                    )
                    candidate_abs = abs(candidate_residual)
                    emit_progress(
                        ProgressEventKind.DAMPING_DECIDED,
                        damping=damping,
                        candidate_omega=_progress_complex(candidate),
                        candidate_determinant_abs=candidate_abs,
                        accepted=candidate_abs < magnitude,
                    )
                    if candidate_abs < magnitude:
                        value = candidate
                        carried = (candidate, candidate_residual)
                        selected_damping = damping
                        resulting_abs = candidate_abs
                        accepted = True
                        break
                if not accepted:
                    value -= 0.125 * step
                    carried = (value, candidate_residual)
                    resulting_abs = candidate_abs
                applied_step = selected_damping * step
                emit_progress(
                    ProgressEventKind.NEWTON_ITERATION_COMPLETED,
                    derivative_abs=derivative_abs,
                    raw_step=_progress_complex(raw_step),
                    applied_step=_progress_complex(applied_step),
                    step_abs=abs(applied_step),
                    clipped=clipped,
                    damping=selected_damping,
                    accepted=accepted,
                    resulting_omega=_progress_complex(value),
                    resulting_determinant_abs=resulting_abs,
                    elapsed_seconds=time.monotonic() - iteration_started,
                )
        return best[0], best[1], None, False

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
        root, residual, accepted_derivative, _ = self._bounded_newton(
            determinant, guess
        )
        h = _DERIVATIVE_STEP * (1.0 + abs(root))

        def final_determinant(omega: complex, purpose: str) -> complex:
            started = time.monotonic()
            with progress_scope(
                determinant_purpose=purpose,
                current_omega=_progress_complex(root),
                candidate_omega=_progress_complex(omega),
            ):
                emit_progress(
                    ProgressEventKind.DETERMINANT_STARTED,
                    purpose=purpose,
                    omega=_progress_complex(omega),
                )
                result = determinant(omega)
                emit_progress(
                    ProgressEventKind.DETERMINANT_COMPLETED,
                    purpose=purpose,
                    omega=_progress_complex(omega),
                    determinant_real=result.real,
                    determinant_imag=result.imag,
                    determinant_abs=abs(result),
                    elapsed_seconds=time.monotonic() - started,
                )
                return result

        derivative = accepted_derivative
        if derivative is None:
            derivative = abs(
                (
                    final_determinant(root + h, "final derivative +h")
                    - final_determinant(root - h, "final derivative -h")
                )
                / (2.0 * h)
            )
        if not math.isfinite(derivative) or derivative <= 0.0:
            raise NativeResourceUnavailableError(
                "native determinant frequency derivative is not usable"
            )
        converged = bool(
            residual / derivative <= _ROOT_CORRECTION_TOLERANCE
        )
        return root, residual, derivative, converged

    def evaluate_root(
        self,
        *,
        job: ResponseComponentJob,
        background_root: object,
        perturbation: HorizonPerturbation | ExteriorPerturbation,
        policy: NumericalPolicy,
        primary_predictor: complex | None = None,
        primary_predictor_kind: str | None = None,
    ) -> RootReadout:
        if primary_predictor_kind not in {
            None,
            "EPSILON_CONTINUATION",
            "SPIN_CONTINUATION",
        }:
            raise ValueError("primary predictor kind is invalid")
        requested_predictor_kind = (
            primary_predictor_kind or "EPSILON_CONTINUATION"
        )
        def solve_phase(
            name,
            sn,
            phase_policy,
            guess,
            *,
            seed_kind,
            requested_seed_kind=None,
            fallback_guess=None,
            fallback_used=False,
            fallback_reason=None,
        ):
            started = time.monotonic()
            requested_kind = requested_seed_kind or seed_kind

            def solve_with_seed(
                selected_guess,
                selected_kind,
                used,
                reason,
                error_type=None,
            ):
                with progress_scope(
                    seed_omega=_progress_complex(selected_guess),
                    current_omega=_progress_complex(selected_guess),
                    seed_kind=selected_kind,
                    fallback_used=used,
                ):
                    emit_progress(
                        ProgressEventKind.ROOT_SEED_SELECTED,
                        requested_seed_kind=requested_kind,
                        seed_kind=selected_kind,
                        seed_omega=_progress_complex(selected_guess),
                        fallback_used=used,
                        fallback_reason=reason,
                        fallback_error_type=error_type,
                    )
                    return self._solve_once(
                        sn=sn,
                        job=job,
                        perturbation=perturbation,
                        policy=phase_policy,
                        guess=selected_guess,
                    )

            with progress_scope(
                phase=name,
                seed_omega=_progress_complex(guess),
                current_omega=_progress_complex(guess),
            ):
                emit_progress(
                    ProgressEventKind.ROOT_PHASE_STARTED,
                    seed_omega=_progress_complex(guess),
                    current_omega=_progress_complex(guess),
                )
                fallback_error_type = None
                try:
                    result = solve_with_seed(
                        guess, seed_kind, fallback_used, fallback_reason
                    )
                except Exception as error:
                    if fallback_guess is None:
                        raise
                    fallback_reason = "PREDICTOR_SOLVE_ERROR"
                    fallback_error_type = type(error).__name__
                    seed_kind = "FALLBACK_BACKGROUND"
                    fallback_used = True
                    result = solve_with_seed(
                        fallback_guess,
                        seed_kind,
                        fallback_used,
                        fallback_reason,
                        fallback_error_type,
                    )
                else:
                    if fallback_guess is not None and (
                        not result[3]
                        or abs(result[0] - fallback_guess)
                        > branch_radius
                    ):
                        fallback_reason = (
                            "PREDICTOR_NEWTON_FAILED"
                            if not result[3]
                            else "PREDICTOR_BRANCH_ESCAPE"
                        )
                        seed_kind = "FALLBACK_BACKGROUND"
                        fallback_used = True
                        result = solve_with_seed(
                            fallback_guess,
                            seed_kind,
                            fallback_used,
                            fallback_reason,
                        )
                with progress_scope(
                    seed_omega=_progress_complex(
                        fallback_guess
                        if fallback_used and fallback_guess is not None
                        else guess
                    ),
                    current_omega=_progress_complex(result[0]),
                    seed_kind=seed_kind,
                    fallback_used=fallback_used,
                ):
                    emit_progress(
                        ProgressEventKind.ROOT_PHASE_COMPLETED,
                        resulting_omega=_progress_complex(result[0]),
                        resulting_determinant_abs=result[1],
                        derivative_abs=result[2],
                        converged=result[3],
                        elapsed_seconds=time.monotonic() - started,
                    )
                return result

        branch_radius = mode_specific_branch_enclosure_radius(background_root)
        primary_sn = self._standard_sn(job, policy)
        background_omega = complex(background_root.omega)
        predictor = None
        primary_seed_kind = "AUTHENTICATED_BACKGROUND"
        primary_fallback_used = False
        primary_fallback_reason = None
        if primary_predictor is not None:
            candidate = complex(primary_predictor)
            if (
                math.isfinite(candidate.real)
                and math.isfinite(candidate.imag)
                and abs(candidate - background_omega)
                <= branch_radius
            ):
                predictor = candidate
                primary_seed_kind = requested_predictor_kind
            else:
                primary_seed_kind = "FALLBACK_BACKGROUND"
                primary_fallback_used = True
                primary_fallback_reason = (
                    "PREDICTOR_INVALID"
                    if not (
                        math.isfinite(candidate.real)
                        and math.isfinite(candidate.imag)
                    )
                    else "PREDICTOR_OUTSIDE_BRANCH"
                )
        root, residual, derivative, primary_converged = solve_phase(
            "PRIMARY",
            primary_sn,
            policy,
            background_omega if predictor is None else predictor,
            seed_kind=primary_seed_kind,
            requested_seed_kind=(
                requested_predictor_kind
                if primary_predictor is not None
                else "AUTHENTICATED_BACKGROUND"
            ),
            fallback_guess=(background_omega if predictor is not None else None),
            fallback_used=primary_fallback_used,
            fallback_reason=primary_fallback_reason,
        )

        truncation_policy = replace(
            policy, endpoint_series_order=policy.endpoint_series_order + 8
        )
        truncation_root, truncation_residual, truncation_derivative, truncation_converged = solve_phase(
            "TRUNCATION",
            self._standard_sn(job, truncation_policy),
            truncation_policy,
            root,
            seed_kind="ACCEPTED_PRIMARY",
        )

        resolution_policy = replace(
            policy,
            ode_relative_tolerance=policy.ode_relative_tolerance / 2.0,
            ode_absolute_tolerance=policy.ode_absolute_tolerance / 2.0,
            support_subinterval_count=policy.support_subinterval_count * 2,
        )
        resolution_root, resolution_residual, resolution_derivative, resolution_converged = solve_phase(
            "RESOLUTION",
            self._standard_sn(job, resolution_policy),
            resolution_policy,
            root,
            seed_kind="ACCEPTED_PRIMARY",
        )

        alternate_guess = background_omega + complex(2.5e-4, 1.25e-4) * (
            1.0 + abs(background_omega)
        )
        seed_path_root, seed_path_residual, seed_path_derivative, seed_path_converged = solve_phase(
            "SEED-PATH",
            primary_sn,
            policy,
            alternate_guess,
            seed_kind="INDEPENDENT_SEED_PATH",
        )
        diagnostic_roots = (truncation_root, resolution_root, seed_path_root)
        branch_continuation_valid = (
            abs(root - background_omega)
            <= branch_radius
            and all(
                abs(candidate - root)
                <= branch_radius
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
                if branch_continuation_valid
                else "nonmatching-native-continuation"
            ),
            equation_id=job.equation_id,
            truncation_radius=abs(truncation_root - root),
            resolution_radius=abs(resolution_root - root),
            seed_path_radius=abs(seed_path_root - root),
            diagnostic_readouts={
                "truncation": DiagnosticRootReadout(
                    truncation_root - root,
                    truncation_residual,
                    truncation_derivative,
                    truncation_converged,
                ),
                "resolution": DiagnosticRootReadout(
                    resolution_root - root,
                    resolution_residual,
                    resolution_derivative,
                    resolution_converged,
                ),
                "seed-path": DiagnosticRootReadout(
                    seed_path_root - root,
                    seed_path_residual,
                    seed_path_derivative,
                    seed_path_converged,
                ),
            },
        )

    def evaluate_root_with_predictor_kind(
        self,
        *,
        job: ResponseComponentJob,
        background_root: object,
        perturbation: HorizonPerturbation | ExteriorPerturbation,
        policy: NumericalPolicy,
        primary_predictor: complex,
        primary_predictor_kind: str,
    ) -> RootReadout:
        return self.evaluate_root(
            job=job,
            background_root=background_root,
            perturbation=perturbation,
            policy=policy,
            primary_predictor=primary_predictor,
            primary_predictor_kind=primary_predictor_kind,
        )

    def fixed_root_survey_batch(
        self,
        *,
        job: ResponseComponentJob,
        fixed_root: complex,
        branch_identity: str,
    ) -> Binary64FixedRootBatch:
        """Evaluate the binary64 nine-sample exterior survey at one fixed root."""

        if job.mechanism_id not in _EXTERIOR_PROFILE_IDS:
            raise ValueError("binary64 fixed-root survey requires an exterior job")
        root = complex(fixed_root)
        if not math.isfinite(root.real) or not math.isfinite(root.imag):
            raise ValueError("binary64 fixed-root survey root must be finite")
        if branch_identity != job.root.branch_id:
            raise ValueError("binary64 fixed-root survey branch identity mismatch")
        support = _exterior_support(job.spin, job.mechanism_id)
        profile_id = _EXTERIOR_PROFILE_IDS[job.mechanism_id]
        frequency_step = _DERIVATIVE_STEP * (1.0 + abs(root))
        coordinate_step = job.policy.epsilons[0]
        planned = (
            ("D0", root, 0.0j),
            ("DOMEGA_REAL_PLUS_H", root + frequency_step, 0.0j),
            ("DOMEGA_REAL_MINUS_H", root - frequency_step, 0.0j),
            ("DOMEGA_REAL_PLUS_HALF_H", root + frequency_step / 2.0, 0.0j),
            ("DOMEGA_REAL_MINUS_HALF_H", root - frequency_step / 2.0, 0.0j),
            ("DC_PLUS_EPSILON", root, complex(coordinate_step, 0.0)),
            ("DC_MINUS_EPSILON", root, complex(-coordinate_step, 0.0)),
            ("DC_PLUS_HALF_EPSILON", root, complex(coordinate_step / 2.0, 0.0)),
            ("DC_MINUS_HALF_EPSILON", root, complex(-coordinate_step / 2.0, 0.0)),
        )
        if len(planned) > 9:
            raise RuntimeError("binary64 fixed-root sample budget exceeded")
        sn = self._standard_sn(job, job.policy)
        samples = []
        for index, (role, omega, amplitude) in enumerate(planned):
            perturbation = (
                ExteriorBackgroundPerturbation()
                if index < 5
                else ExteriorPerturbation(
                    amplitude=amplitude,
                    profile_id=profile_id,
                    support=support,
                )
            )
            determinant = self._determinant(sn, omega, perturbation, job.policy)
            samples.append(
                Binary64FixedRootSample(
                    role=role,
                    omega=omega,
                    amplitude=amplitude,
                    determinant=determinant,
                )
            )
        return Binary64FixedRootBatch(
            leaf_id=job.leaf_id,
            job_id=job.job_id,
            mechanism_id=job.mechanism_id,
            fixed_root=root,
            branch_identity=branch_identity,
            frequency_step=frequency_step,
            coordinate_step=coordinate_step,
            support=support,
            samples=tuple(samples),
        )

    def fixed_root_reused_background_batch(
        self,
        *,
        job: ResponseComponentJob,
        fixed_root: complex,
        branch_identity: str,
        background: CanonicalExteriorBackground,
        equivalence_receipt: BackgroundEquivalenceReceipt | None,
    ) -> Binary64ReusedBackgroundBatch:
        """Evaluate only D_c after strict authenticated Dω reuse admission."""

        if equivalence_receipt is None:
            raise ValueError("background equivalence receipt is required")
        if job.mechanism_id not in _EXTERIOR_PROFILE_IDS:
            raise ValueError("background reuse requires an exterior job")
        root = complex(fixed_root)
        if root != background.fixed_root or branch_identity != job.root.branch_id:
            raise ValueError("background reuse root or branch mismatch")
        expected_key = build_exterior_background_reuse_key(
            job,
            root_seal_sha256=background.reuse_key.root_seal_sha256,
            fixed_root=background.fixed_root,
        )
        if background.reuse_key != expected_key:
            raise ValueError("background reuse key mismatch")
        if (
            equivalence_receipt.reuse_key != expected_key
            or equivalence_receipt.mechanism_id != job.mechanism_id
            or equivalence_receipt.canonical_background_sha256
            != background.sha256
        ):
            raise ValueError("background equivalence receipt mismatch")
        expected_receipt = BackgroundEquivalenceReceipt.issue(
            reuse_key=expected_key,
            job=job,
            canonical_background_sha256=background.sha256,
            fixed_root=background.fixed_root,
        )
        if equivalence_receipt.to_mapping() != expected_receipt.to_mapping():
            raise ValueError("background equivalence proof mismatch")
        support = _exterior_support(job.spin, job.mechanism_id)
        profile_id = _EXTERIOR_PROFILE_IDS[job.mechanism_id]
        coordinate_step = job.policy.epsilons[0]
        planned = (
            ("DC_PLUS_EPSILON", complex(coordinate_step, 0.0)),
            ("DC_MINUS_EPSILON", complex(-coordinate_step, 0.0)),
            ("DC_PLUS_HALF_EPSILON", complex(coordinate_step / 2.0, 0.0)),
            ("DC_MINUS_HALF_EPSILON", complex(-coordinate_step / 2.0, 0.0)),
        )
        sn = self._standard_sn(job, job.policy)
        samples = tuple(
            Binary64FixedRootSample(
                role=role,
                omega=root,
                amplitude=amplitude,
                determinant=self._determinant(
                    sn,
                    root,
                    ExteriorPerturbation(amplitude, profile_id, support),
                    job.policy,
                ),
            )
            for role, amplitude in planned
        )
        return Binary64ReusedBackgroundBatch(
            leaf_id=job.leaf_id,
            job_id=job.job_id,
            mechanism_id=job.mechanism_id,
            fixed_root=root,
            branch_identity=branch_identity,
            coordinate_step=coordinate_step,
            support=support,
            background_sha256=background.sha256,
            equivalence_receipt_sha256=equivalence_receipt.sha256,
            samples=samples,
        )

    def fixed_root_survey_with_optional_background(
        self,
        *,
        job: ResponseComponentJob,
        fixed_root: complex,
        branch_identity: str,
        background: CanonicalExteriorBackground | None,
        equivalence_receipt: BackgroundEquivalenceReceipt | None,
    ) -> Binary64FixedRootBatch | Binary64ReusedBackgroundBatch:
        """Use four samples only when the exact equivalence gate is satisfied."""

        if exterior_background_reuse_admitted(
            job, background, equivalence_receipt
        ):
            assert background is not None
            return self.fixed_root_reused_background_batch(
                job=job,
                fixed_root=fixed_root,
                branch_identity=branch_identity,
                background=background,
                equivalence_receipt=equivalence_receipt,
            )
        return self.fixed_root_survey_batch(
            job=job,
            fixed_root=fixed_root,
            branch_identity=branch_identity,
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

        def partial_determinant(candidate: complex, purpose: str) -> complex:
            started = time.monotonic()
            with progress_scope(
                phase="CLOSED-FORM-PARTIALS",
                determinant_purpose=purpose,
                seed_omega=_progress_complex(omega),
                current_omega=_progress_complex(omega),
                candidate_omega=_progress_complex(candidate),
            ):
                emit_progress(
                    ProgressEventKind.DETERMINANT_STARTED,
                    purpose=purpose,
                    omega=_progress_complex(candidate),
                )
                result = self._determinant(sn, candidate, zero, policy)
                emit_progress(
                    ProgressEventKind.DETERMINANT_COMPLETED,
                    purpose=purpose,
                    omega=_progress_complex(candidate),
                    determinant_real=result.real,
                    determinant_imag=result.imag,
                    determinant_abs=abs(result),
                    elapsed_seconds=time.monotonic() - started,
                )
                return result

        frequency_coarse = (
            partial_determinant(omega + h, "closed-form derivative +h")
            - partial_determinant(omega - h, "closed-form derivative -h")
        ) / (2.0 * h)
        half_h = 0.5 * h
        frequency = (
            partial_determinant(omega + half_h, "closed-form derivative +h/2")
            - partial_determinant(omega - half_h, "closed-form derivative -h/2")
        ) / (2.0 * half_h)
        frequency_error = abs(frequency - frequency_coarse) + math.ulp(
            max(abs(frequency), abs(frequency_coarse), 1.0)
        )
        with _progress_suboperation("Xup"):
            outgoing, _ = sn.outgoing_at(omega, policy.readout_radius)
        outgoing_horizon = self._integrate_horizon_branch(
            sn, omega, +1, policy.readout_radius
        )
        with _progress_suboperation("Wronskian"):
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
            frequency_derivative_error_abs=frequency_error,
        )
