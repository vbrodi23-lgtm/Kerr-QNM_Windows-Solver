"""Selected linear-response execution behind the unavailable provider.

The engine owns identities, same-equation signed-amplitude refinement, and
authenticated resumability.  Numerical determinant evaluation is injected at
one typed boundary; importing this module cannot start a numerical solve.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from fractions import Fraction
import csv
import hashlib
from importlib import resources
import io
import json
import math
import os
from pathlib import Path
import platform
import re
import sys
import tempfile
from typing import Any, Callable, Mapping, Protocol, Sequence

from .contracts import (
    Capability,
    ModeKey,
    StudyRequest,
    canonical_json_bytes,
    canonical_text_sha256,
)
from .linear_response import (
    B_PRIME_RELEASE_DOMAIN,
    BPrimeLeaf,
    baseline_root_reference_id,
)
from .spectrum import (
    PUBLIC_BRANCH_ID,
    PUBLIC_CONVENTION_ID,
    PUBLIC_POLARIZATION_ID,
    PUBLIC_THEORY_ID,
    load_spectrum_catalog,
)


ENGINE_SCHEMA_VERSION = 1
ENGINE_EQUATION_ID = "same-equation-complex-amplitude-root-readout-" + "v" + str(1)
_HEX_40 = re.compile(r"[0-9a-f]{40}")
_EXTERIOR_PROFILE_IDS: Mapping[str, str] = {
    "exterior-fixed-r3": "fixed-r3",
    "exterior-light-ring": "light-ring",
    "exterior-throat-kappa": "throat-kappa",
    "exterior-alpha-zero": "alpha-zero",
    "exterior-alpha-half": "alpha-half",
    "exterior-alpha-one": "alpha-one",
}
ERROR_CHANNELS = (
    "signed-root",
    "truncation",
    "resolution",
    "seed-path",
    "axis",
    "amplitude",
)
_RECORDED_ROOT_MAPPING_TOLERANCE_ABS = 5.0e-9


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _finite_complex(value: complex, subject: str) -> complex:
    converted = complex(value)
    if not (math.isfinite(converted.real) and math.isfinite(converted.imag)):
        raise ValueError(f"{subject} must be finite")
    return converted


def _complex_mapping(value: complex) -> dict[str, float]:
    return {"real": value.real, "imaginary": value.imag}


def _complex_from_mapping(value: object, subject: str) -> complex:
    if not isinstance(value, Mapping) or set(value) != {"real", "imaginary"}:
        raise ValueError(f"{subject} must be a complex-number object")
    real = value["real"]
    imaginary = value["imaginary"]
    if (
        isinstance(real, bool)
        or isinstance(imaginary, bool)
        or not isinstance(real, (int, float))
        or not isinstance(imaginary, (int, float))
    ):
        raise ValueError(f"{subject} components must be numbers")
    return _finite_complex(complex(float(real), float(imaginary)), subject)


def _validated_source_root_mapping(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("source root mapping must be an object")
    expected_fields = {
        "schema_version",
        "mapping_protocol",
        "source_bundle_baselines_sha256",
        "source_root_reference_id",
        "source_root_identity_sha256",
        "source_branch_id",
        "source_omega",
        "installed_root_reference_id",
        "installed_root_identity_sha256",
        "installed_branch_id",
        "installed_omega",
        "mapping_tolerance_abs",
        "measured_delta_abs",
        "mapping_receipt_sha256",
    }
    if set(value) != expected_fields:
        raise ValueError("source root mapping fields are invalid")
    receipt = dict(value)
    digest = receipt.pop("mapping_receipt_sha256")
    if not isinstance(digest, str) or digest != _sha256(receipt):
        raise ValueError("source root mapping receipt SHA-256 is invalid")
    if (
        receipt["schema_version"] != 1
        or receipt["mapping_protocol"]
        != "authenticated-recorded-source-to-installed-spectral-root"
    ):
        raise ValueError("source root mapping protocol is invalid")
    tolerance = receipt["mapping_tolerance_abs"]
    measured = receipt["measured_delta_abs"]
    if (
        isinstance(tolerance, bool)
        or isinstance(measured, bool)
        or not isinstance(tolerance, (int, float))
        or not isinstance(measured, (int, float))
        or float(tolerance) != _RECORDED_ROOT_MAPPING_TOLERANCE_ABS
        or not math.isfinite(float(measured))
        or float(measured) < 0.0
        or float(measured) > float(tolerance)
    ):
        raise ValueError("source root mapping tolerance or delta is invalid")
    source = _complex_from_mapping(receipt["source_omega"], "source root mapping omega")
    installed = _complex_from_mapping(
        receipt["installed_omega"], "installed root mapping omega"
    )
    if float(measured) != abs(source - installed):
        raise ValueError("source root mapping measured delta is invalid")
    for key in (
        "source_bundle_baselines_sha256",
        "source_root_identity_sha256",
        "installed_root_identity_sha256",
    ):
        field = receipt[key]
        if not isinstance(field, str) or re.fullmatch(r"[0-9a-f]{64}", field) is None:
            raise ValueError("source root mapping digest field is invalid")
    for key in (
        "source_root_reference_id",
        "source_branch_id",
        "installed_root_reference_id",
        "installed_branch_id",
    ):
        if not isinstance(receipt[key], str) or not receipt[key]:
            raise ValueError("source root mapping identity field is invalid")
    receipt["mapping_receipt_sha256"] = digest
    return receipt


@dataclass(frozen=True, slots=True)
class BackendIdentity:
    backend_id: str
    implementation_version: str
    source_commit: str
    source_blobs: tuple[tuple[str, str], ...]
    runtime_fingerprint: str

    def __post_init__(self) -> None:
        if not self.backend_id or not self.implementation_version:
            raise ValueError("backend identity fields must be nonempty")
        if _HEX_40.fullmatch(self.source_commit) is None:
            raise ValueError("backend source_commit must be a Git SHA")
        if not self.source_blobs or len({name for name, _ in self.source_blobs}) != len(
            self.source_blobs
        ):
            raise ValueError("backend source blobs must be nonempty and unique")
        for name, digest in self.source_blobs:
            if not name or _HEX_40.fullmatch(digest) is None:
                raise ValueError("backend source blob identity is invalid")
        if not self.runtime_fingerprint:
            raise ValueError("backend runtime_fingerprint must be nonempty")

    def to_mapping(self) -> dict[str, object]:
        return {
            "backend_id": self.backend_id,
            "implementation_version": self.implementation_version,
            "source_commit": self.source_commit,
            "source_blobs": [
                {"path": name, "git_blob_sha": digest}
                for name, digest in self.source_blobs
            ],
            "runtime_fingerprint": self.runtime_fingerprint,
        }

    @property
    def identity_sha256(self) -> str:
        return _sha256(self.to_mapping())


@dataclass(frozen=True, slots=True)
class NumericalPolicy:
    epsilons: tuple[float, ...] = (
        4.0e-3,
        2.0e-3,
        1.0e-3,
        5.0e-4,
        2.5e-4,
        1.25e-4,
    )
    ode_relative_tolerance: float = 2.0e-10
    ode_absolute_tolerance: float = 2.0e-12
    endpoint_series_order: int = 28
    readout_radius: float = 6.0
    support_subinterval_count: int = 256
    order_tolerance: float = 0.45
    even_order_tolerance: float = 0.75
    signal_to_root_factor: float = 8.0
    axis_tolerance_factor: float = 2.0
    absolute_axis_floor: float = 1.0e-12

    def __post_init__(self) -> None:
        epsilons = tuple(float(value) for value in self.epsilons)
        if len(epsilons) < 4:
            raise ValueError("response refinement requires at least four amplitude levels")
        if any(not math.isfinite(value) or value <= 0.0 for value in epsilons):
            raise ValueError("response amplitudes must be finite and positive")
        if any(left <= right for left, right in zip(epsilons, epsilons[1:])):
            raise ValueError("response amplitudes must be strictly coarse-to-fine")
        for name in (
            "ode_relative_tolerance",
            "ode_absolute_tolerance",
            "order_tolerance",
            "even_order_tolerance",
            "absolute_axis_floor",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        if self.endpoint_series_order < 1 or self.support_subinterval_count < 32:
            raise ValueError("native numerical resolution is invalid")
        if not math.isfinite(self.readout_radius) or self.readout_radius <= 0.0:
            raise ValueError("readout_radius must be finite and positive")
        if self.signal_to_root_factor <= 1.0 or self.axis_tolerance_factor <= 0.0:
            raise ValueError("response refinement factors are invalid")
        object.__setattr__(self, "epsilons", epsilons)

    def to_mapping(self) -> dict[str, object]:
        return {
            "epsilons": list(self.epsilons),
            "ode_relative_tolerance": self.ode_relative_tolerance,
            "ode_absolute_tolerance": self.ode_absolute_tolerance,
            "endpoint_series_order": self.endpoint_series_order,
            "readout_radius": self.readout_radius,
            "support_subinterval_count": self.support_subinterval_count,
            "order_tolerance": self.order_tolerance,
            "even_order_tolerance": self.even_order_tolerance,
            "signal_to_root_factor": self.signal_to_root_factor,
            "axis_tolerance_factor": self.axis_tolerance_factor,
            "absolute_axis_floor": self.absolute_axis_floor,
        }

    @property
    def identity_sha256(self) -> str:
        return _sha256(self.to_mapping())


@dataclass(frozen=True, slots=True)
class SamplingCoordinate:
    coordinate_id: str
    exact: tuple[int, int]
    value: float
    transformation_id: str

    def to_mapping(self) -> dict[str, object]:
        return {
            "coordinate_id": self.coordinate_id,
            "exact": {"numerator": self.exact[0], "denominator": self.exact[1]},
            "value": self.value,
            "transformation_id": self.transformation_id,
        }


@dataclass(frozen=True, slots=True)
class BoundSpectralRoot:
    selector_id: str
    availability: str
    root_reference_id: str
    branch_id: str
    spin_binary64_hex: str
    omega: complex
    angular_separation_constant: complex
    owner_id: str
    owner_data_sha256: str
    owner_record: Mapping[str, object]

    def to_mapping(self) -> dict[str, object]:
        return {
            "selector_id": self.selector_id,
            "availability": self.availability,
            "root_reference_id": self.root_reference_id,
            "branch_id": self.branch_id,
            "spin_binary64_hex": self.spin_binary64_hex,
            "omega": _complex_mapping(self.omega),
            "angular_separation_constant": _complex_mapping(
                self.angular_separation_constant
            ),
            "owner_id": self.owner_id,
            "owner_data_sha256": self.owner_data_sha256,
            "owner_record": dict(self.owner_record),
        }

    @property
    def identity_sha256(self) -> str:
        return _sha256(self.to_mapping())


def _mode_for_leaf(leaf: BPrimeLeaf) -> ModeKey:
    return ModeKey(
        s=-2,
        ell=leaf.mode[0],
        m=leaf.mode[1],
        n=leaf.mode[2],
        branch=PUBLIC_BRANCH_ID,
        polarization=PUBLIC_POLARIZATION_ID,
    )


def _resolve_root(leaf: BPrimeLeaf, mode: ModeKey) -> BoundSpectralRoot:
    selector = next(
        (
            item
            for item in B_PRIME_RELEASE_DOMAIN.root_selectors
            if item.mode == leaf.mode and item.spin.hex() == leaf.spin.hex()
        ),
        None,
    )
    if selector is None:
        raise ValueError("B-prime leaf has no exact root selector")
    request = StudyRequest.from_mapping(
        {
            "schema_version": 1,
            "target": Capability.SPECTRAL_CORE.value,
            "theory_id": PUBLIC_THEORY_ID,
            "convention_id": PUBLIC_CONVENTION_ID,
            "modes": [mode.to_mapping()],
            "spins": [leaf.spin],
            "evidence_profile": "research",
            "numerical_policy": {},
        }
    )
    catalog = load_spectrum_catalog()
    root = catalog.select(request)[0]
    record = root.to_mapping()
    owner_id = type(root).__name__
    owner_sha = (
        catalog.overlay.data_sha256
        if owner_id == "SpectralOverlayRoot"
        else catalog.data_sha256
    )
    return BoundSpectralRoot(
        selector_id=selector.selector_id,
        availability=selector.availability,
        root_reference_id=baseline_root_reference_id(mode, leaf.spin),
        branch_id=root.branch_id,
        spin_binary64_hex=root.spin_hex,
        omega=complex(root.omega_re, root.omega_im),
        angular_separation_constant=complex(root.angular_A_re, root.angular_A_im),
        owner_id=owner_id,
        owner_data_sha256=owner_sha,
        owner_record=record,
    )


@dataclass(frozen=True, slots=True)
class ResponseComponentJob:
    leaf_id: str
    role: str
    mode_label: str
    mode: ModeKey
    spin: float
    mechanism_id: str
    sampling_coordinate: SamplingCoordinate
    root: BoundSpectralRoot
    policy: NumericalPolicy
    backend_identity: BackendIdentity
    source_root_mapping: Mapping[str, object] | None = None
    equation_id: str = ENGINE_EQUATION_ID

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_root_mapping",
            _validated_source_root_mapping(self.source_root_mapping),
        )

    @classmethod
    def from_leaf_id(
        cls,
        leaf_id: str,
        *,
        policy: NumericalPolicy,
        backend_identity: BackendIdentity,
    ) -> "ResponseComponentJob":
        leaf = next(
            (
                item
                for item in B_PRIME_RELEASE_DOMAIN.production_leaves
                if item.leaf_id == leaf_id
            ),
            None,
        )
        if leaf is None:
            raise ValueError("response job leaf_id is outside frozen B-prime")
        mode = _mode_for_leaf(leaf)
        if leaf.spin_role == "direct":
            coordinate = SamplingCoordinate(
                "a_over_M",
                (leaf.coordinate.numerator, leaf.coordinate.denominator),
                float(leaf.coordinate),
                "identity-a-over-M",
            )
        else:
            coordinate = SamplingCoordinate(
                "M-kappa",
                (leaf.coordinate.numerator, leaf.coordinate.denominator),
                float(leaf.coordinate),
                "kerr-prograde-spin-from-dimensionless-surface-gravity",
            )
        return cls(
            leaf_id=leaf.leaf_id,
            role=leaf.role,
            mode_label=leaf.mode_label,
            mode=mode,
            spin=leaf.spin,
            mechanism_id=leaf.mechanism_id,
            sampling_coordinate=coordinate,
            root=_resolve_root(leaf, mode),
            policy=policy,
            backend_identity=backend_identity,
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "leaf_id": self.leaf_id,
            "role": self.role,
            "mode_label": self.mode_label,
            "mode": self.mode.to_mapping(),
            "spin": self.spin,
            "spin_binary64_hex": self.spin.hex(),
            "mechanism_id": self.mechanism_id,
            "sampling_coordinate": self.sampling_coordinate.to_mapping(),
            "root": self.root.to_mapping(),
            "policy": self.policy.to_mapping(),
            "backend_identity": self.backend_identity.to_mapping(),
            "source_root_mapping": (
                None
                if self.source_root_mapping is None
                else dict(self.source_root_mapping)
            ),
            "equation_id": self.equation_id,
        }

    @property
    def job_id(self) -> str:
        return f"response-job-{_sha256(self.to_mapping())}"


@dataclass(frozen=True, slots=True)
class ExteriorSupport:
    lower: float
    upper: float
    centre: float
    half_width: float

    def to_mapping(self) -> dict[str, float]:
        return {
            "lower": self.lower,
            "upper": self.upper,
            "centre": self.centre,
            "half_width": self.half_width,
        }


def _exterior_support(spin: float, mechanism_id: str) -> ExteriorSupport:
    profile = _EXTERIOR_PROFILE_IDS.get(mechanism_id)
    if profile is None:
        raise ValueError(f"unsupported exterior mechanism: {mechanism_id}")
    horizon = 1.0 + math.sqrt(max(0.0, 1.0 - spin * spin))
    kappa = math.sqrt(max(0.0, 1.0 - spin * spin)) / (2.0 * horizon)
    if profile == "fixed-r3":
        centre, width = 3.0, 0.45
    elif profile == "light-ring":
        centre = 2.0 * (1.0 + math.cos((2.0 / 3.0) * math.acos(-spin)))
        width = max(0.012, 0.25 * max(centre - horizon, 1.0e-8))
    elif profile == "throat-kappa":
        centre, width = horizon + 3.0 * kappa, max(0.012, 0.6 * kappa)
    elif profile == "alpha-zero":
        centre, width = horizon + 2.0, 0.5
    elif profile == "alpha-half":
        scale = math.sqrt(max(kappa, 1.0e-300))
        centre, width = horizon + 2.0 * scale, max(0.012, 0.5 * scale)
    else:
        centre, width = horizon + 4.0 * kappa, max(0.012, kappa)
    width = min(width, centre - (horizon + 5.0e-4))
    if width <= 0.0:
        raise ValueError("exterior profile has no smooth support outside horizon")
    return ExteriorSupport(centre - width, centre + width, centre, width)


@dataclass(frozen=True, slots=True)
class HorizonPerturbation:
    amplitude: complex
    spin: float
    azimuthal_index: int
    coordinate_id: str = "unit-complex-deltaB"

    def reflectivity(self, trial_omega: complex) -> complex:
        horizon = 1.0 + math.sqrt(max(0.0, 1.0 - self.spin * self.spin))
        omega_h = self.spin / (2.0 * horizon)
        p_h = complex(trial_omega) - self.azimuthal_index * omega_h
        denominator = 2.0j * p_h - self.amplitude
        if denominator == 0.0j:
            raise ValueError("zero horizon chart denominator")
        return self.amplitude / denominator


@dataclass(frozen=True, slots=True)
class ExteriorPerturbation:
    amplitude: complex
    profile_id: str
    support: ExteriorSupport
    coordinate_id: str = "unit-complex-profile-amplitude"

    def profile_value(self, radius: float) -> complex:
        """Return the migrated L-infinity-normalized compact C-infinity bump."""

        value = float(radius)
        if not math.isfinite(value):
            raise ValueError("exterior profile radius must be finite")
        scaled = (value - self.support.centre) / self.support.half_width
        if abs(scaled) >= 1.0:
            return 0.0j
        return self.amplitude * math.exp(1.0 - 1.0 / (1.0 - scaled * scaled))


@dataclass(frozen=True, slots=True)
class DeterminantPartials:
    frequency_derivative: complex
    coordinate_derivative: complex
    simple_root_valid: bool

    def __post_init__(self) -> None:
        _finite_complex(self.frequency_derivative, "frequency derivative")
        _finite_complex(self.coordinate_derivative, "coordinate derivative")


@dataclass(frozen=True, slots=True)
class RootReadout:
    omega: complex
    determinant_residual_abs: float
    determinant_derivative_abs: float
    converged: bool
    root_reference_id: str
    branch_id: str
    equation_id: str
    truncation_radius: float = 0.0
    resolution_radius: float = 0.0
    seed_path_radius: float = 0.0
    source_root_mapping: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "omega", _finite_complex(self.omega, "root omega"))
        for name in (
            "determinant_residual_abs",
            "determinant_derivative_abs",
            "truncation_radius",
            "resolution_radius",
            "seed_path_radius",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and nonnegative")
            object.__setattr__(self, name, value)
        if self.determinant_derivative_abs <= 0.0:
            raise ValueError("determinant derivative must be positive")
        if not self.root_reference_id or not self.branch_id or not self.equation_id:
            raise ValueError("root readout identity fields must be nonempty")
        object.__setattr__(
            self,
            "source_root_mapping",
            _validated_source_root_mapping(self.source_root_mapping),
        )

    @property
    def newton_correction_estimate(self) -> float:
        return self.determinant_residual_abs / self.determinant_derivative_abs

    def to_mapping(self) -> dict[str, object]:
        return {
            "omega": _complex_mapping(self.omega),
            "determinant_residual_abs": self.determinant_residual_abs,
            "determinant_derivative_abs": self.determinant_derivative_abs,
            "newton_correction_estimate": self.newton_correction_estimate,
            "converged": self.converged,
            "root_reference_id": self.root_reference_id,
            "branch_id": self.branch_id,
            "equation_id": self.equation_id,
            "truncation_radius": self.truncation_radius,
            "resolution_radius": self.resolution_radius,
            "seed_path_radius": self.seed_path_radius,
            "source_root_mapping": (
                None
                if self.source_root_mapping is None
                else dict(self.source_root_mapping)
            ),
        }

    @classmethod
    def from_mapping(cls, value: object) -> "RootReadout":
        if not isinstance(value, Mapping):
            raise ValueError("root readout must be an object")
        return cls(
            omega=_complex_from_mapping(value.get("omega"), "root omega"),
            determinant_residual_abs=float(value["determinant_residual_abs"]),
            determinant_derivative_abs=float(value["determinant_derivative_abs"]),
            converged=bool(value["converged"]),
            root_reference_id=str(value["root_reference_id"]),
            branch_id=str(value["branch_id"]),
            equation_id=str(value["equation_id"]),
            truncation_radius=float(value.get("truncation_radius", 0.0)),
            resolution_radius=float(value.get("resolution_radius", 0.0)),
            seed_path_radius=float(value.get("seed_path_radius", 0.0)),
            source_root_mapping=_validated_source_root_mapping(
                value.get("source_root_mapping")
            ),
        )


class NativeDeterminantKernel(Protocol):
    def evaluate_root(
        self,
        *,
        job: ResponseComponentJob,
        background_root: BoundSpectralRoot,
        perturbation: HorizonPerturbation | ExteriorPerturbation,
        policy: NumericalPolicy,
    ) -> RootReadout: ...

    def horizon_partials(
        self,
        *,
        job: ResponseComponentJob,
        background_root: BoundSpectralRoot,
        policy: NumericalPolicy,
    ) -> DeterminantPartials: ...


class RootReadoutBackend(Protocol):
    identity: BackendIdentity

    def read_root(self, job: ResponseComponentJob, amplitude: complex) -> RootReadout: ...

    def closed_form_horizon_response(
        self, job: ResponseComponentJob
    ) -> complex | None: ...


@dataclass(slots=True)
class NativeDeterminantAdapter:
    identity: BackendIdentity
    kernel: NativeDeterminantKernel

    def _check_job(self, job: ResponseComponentJob) -> None:
        if job.backend_identity != self.identity:
            raise ValueError("response job backend identity does not match adapter")

    def read_root(self, job: ResponseComponentJob, amplitude: complex) -> RootReadout:
        self._check_job(job)
        value = _finite_complex(amplitude, "perturbation amplitude")
        if job.mechanism_id == "horizon-admittance":
            perturbation: HorizonPerturbation | ExteriorPerturbation = HorizonPerturbation(
                value, job.spin, job.mode.m
            )
        else:
            perturbation = ExteriorPerturbation(
                value,
                _EXTERIOR_PROFILE_IDS[job.mechanism_id],
                _exterior_support(job.spin, job.mechanism_id),
            )
        return self.kernel.evaluate_root(
            job=job,
            background_root=job.root,
            perturbation=perturbation,
            policy=job.policy,
        )

    def closed_form_horizon_response(
        self, job: ResponseComponentJob
    ) -> complex | None:
        self._check_job(job)
        if job.mechanism_id != "horizon-admittance":
            return None
        partials = self.kernel.horizon_partials(
            job=job,
            background_root=job.root,
            policy=job.policy,
        )
        frequency = _finite_complex(
            partials.frequency_derivative, "frequency derivative"
        )
        if not partials.simple_root_valid or frequency == 0.0j:
            return None
        return -partials.coordinate_derivative / frequency


@dataclass(frozen=True, slots=True)
class LadderLevel:
    epsilon: float
    real_plus: RootReadout
    real_minus: RootReadout
    imaginary_plus: RootReadout
    imaginary_minus: RootReadout

    @property
    def real_secant(self) -> complex:
        return (self.real_plus.omega - self.real_minus.omega) / (2.0 * self.epsilon)

    @property
    def imaginary_secant(self) -> complex:
        return (self.imaginary_plus.omega - self.imaginary_minus.omega) / (
            2.0j * self.epsilon
        )

    @property
    def combined_secant(self) -> complex:
        return 0.5 * (self.real_secant + self.imaginary_secant)

    @property
    def real_radius(self) -> float:
        return (
            self.real_plus.newton_correction_estimate
            + self.real_minus.newton_correction_estimate
        ) / (2.0 * self.epsilon)

    @property
    def imaginary_radius(self) -> float:
        return (
            self.imaginary_plus.newton_correction_estimate
            + self.imaginary_minus.newton_correction_estimate
        ) / (2.0 * self.epsilon)

    @property
    def even_remainder_abs(self) -> float:
        real = 0.5 * (self.real_plus.omega + self.real_minus.omega)
        imaginary = 0.5 * (
            self.imaginary_plus.omega + self.imaginary_minus.omega
        )
        return abs(real - imaginary)

    @property
    def even_remainder_noise(self) -> float:
        return 0.5 * sum(
            item.newton_correction_estimate
            for item in (
                self.real_plus,
                self.real_minus,
                self.imaginary_plus,
                self.imaginary_minus,
            )
        )

    def signal_resolved(self, factor: float) -> bool:
        real_signal = 0.5 * abs(self.real_plus.omega - self.real_minus.omega)
        imaginary_signal = 0.5 * abs(
            self.imaginary_plus.omega - self.imaginary_minus.omega
        )
        real_noise = factor * (
            self.real_plus.newton_correction_estimate
            + self.real_minus.newton_correction_estimate
        )
        imaginary_noise = factor * (
            self.imaginary_plus.newton_correction_estimate
            + self.imaginary_minus.newton_correction_estimate
        )
        return real_signal > real_noise and imaginary_signal > imaginary_noise

    def to_mapping(self) -> dict[str, object]:
        return {
            "epsilon": self.epsilon,
            "real_plus": self.real_plus.to_mapping(),
            "real_minus": self.real_minus.to_mapping(),
            "imaginary_plus": self.imaginary_plus.to_mapping(),
            "imaginary_minus": self.imaginary_minus.to_mapping(),
            "real_secant": _complex_mapping(self.real_secant),
            "imaginary_secant": _complex_mapping(self.imaginary_secant),
        }

    @classmethod
    def from_mapping(cls, value: object) -> "LadderLevel":
        if not isinstance(value, Mapping):
            raise ValueError("response level must be an object")
        return cls(
            epsilon=float(value["epsilon"]),
            real_plus=RootReadout.from_mapping(value["real_plus"]),
            real_minus=RootReadout.from_mapping(value["real_minus"]),
            imaginary_plus=RootReadout.from_mapping(value["imaginary_plus"]),
            imaginary_minus=RootReadout.from_mapping(value["imaginary_minus"]),
        )


class ComponentStatus(str, Enum):
    CONVERGED = "CONVERGED"
    NOISE_FLOOR = "NOISE_FLOOR"
    AXIS_MISMATCH = "AXIS_MISMATCH"
    BRANCH_LOSS = "BRANCH_LOSS"
    NOT_CONVERGED = "NOT_CONVERGED"


@dataclass(frozen=True, slots=True)
class _AxisEstimate:
    center: complex
    coefficient_c2: complex
    root_radius: float
    richardson_radius: float
    holdout_radius: float
    regression_radius: float

    @property
    def amplitude_radius(self) -> float:
        return max(
            self.richardson_radius,
            self.holdout_radius,
            self.regression_radius,
        )


def _richardson(
    coarse_epsilon: float,
    coarse_value: complex,
    coarse_radius: float,
    fine_epsilon: float,
    fine_value: complex,
    fine_radius: float,
) -> tuple[complex, complex, float]:
    denominator = coarse_epsilon**2 - fine_epsilon**2
    coefficient = (coarse_value - fine_value) / denominator
    center = fine_value - coefficient * fine_epsilon**2
    radius = (
        coarse_epsilon**2 * fine_radius
        + fine_epsilon**2 * coarse_radius
    ) / denominator
    return center, coefficient, radius


def _linear_even_fit(epsilons: Sequence[float], values: Sequence[complex]) -> tuple[complex, float]:
    x = [value * value for value in epsilons]
    mean_x = sum(x) / len(x)
    mean_y = sum(values) / len(values)
    denominator = sum((item - mean_x) ** 2 for item in x)
    if denominator == 0.0:
        raise ValueError("amplitude fit is singular")
    slope = sum(
        (item - mean_x) * (value - mean_y)
        for item, value in zip(x, values)
    ) / denominator
    intercept = mean_y - slope * mean_x
    residual = max(
        abs(value - (intercept + slope * item))
        for item, value in zip(x, values)
    )
    return intercept, residual


def _axis_estimate(levels: Sequence[LadderLevel], axis: str) -> _AxisEstimate:
    if len(levels) < 4:
        raise ValueError("axis estimate requires at least four levels")
    if axis == "real":
        values = [level.real_secant for level in levels]
        radii = [level.real_radius for level in levels]
    elif axis == "imaginary":
        values = [level.imaginary_secant for level in levels]
        radii = [level.imaginary_radius for level in levels]
    else:
        values = [level.combined_secant for level in levels]
        radii = [0.5 * (level.real_radius + level.imaginary_radius) for level in levels]
    epsilons = [level.epsilon for level in levels]
    center, coefficient, root_radius = _richardson(
        epsilons[-2], values[-2], radii[-2], epsilons[-1], values[-1], radii[-1]
    )
    coarse_center, _, _ = _richardson(
        epsilons[-4], values[-4], radii[-4], epsilons[-3], values[-3], radii[-3]
    )
    holdout = abs(values[-3] - (center + coefficient * epsilons[-3] ** 2))
    fit_center, fit_residual = _linear_even_fit(epsilons, values)
    return _AxisEstimate(
        center=center,
        coefficient_c2=coefficient,
        root_radius=root_radius,
        richardson_radius=abs(center - coarse_center),
        holdout_radius=holdout,
        regression_radius=max(fit_residual, abs(center - fit_center)),
    )


def _observed_orders(epsilons: Sequence[float], values: Sequence[complex]) -> tuple[float, ...]:
    output: list[float] = []
    differences = [abs(left - right) for left, right in zip(values, values[1:])]
    for index in range(len(differences) - 1):
        coarse, fine = differences[index], differences[index + 1]
        ratio = epsilons[index] / epsilons[index + 1]
        if coarse > 0.0 and fine > 0.0 and ratio > 1.0:
            output.append(math.log(coarse / fine) / math.log(ratio))
    return tuple(output)


def _positive_orders(epsilons: Sequence[float], values: Sequence[float]) -> tuple[float, ...]:
    output: list[float] = []
    for index in range(len(values) - 1):
        coarse, fine = values[index], values[index + 1]
        ratio = epsilons[index] / epsilons[index + 1]
        if coarse > 0.0 and fine > 0.0 and ratio > 1.0:
            output.append(math.log(coarse / fine) / math.log(ratio))
    return tuple(output)


@dataclass(frozen=True, slots=True)
class ComponentResult:
    job_id: str
    leaf_id: str
    mechanism_id: str
    status: ComponentStatus
    convergence_basis: str
    response: complex | None
    signed_root_crosscheck: complex | None
    closed_form_response: complex | None
    error_channels: Mapping[str, float]
    baseline: RootReadout
    levels: tuple[LadderLevel, ...]
    lineage: Mapping[str, object]

    @property
    def usable(self) -> bool:
        return self.status is ComponentStatus.CONVERGED and self.response is not None

    @property
    def raw_readouts(self) -> tuple[RootReadout, ...]:
        return (
            self.baseline,
            *(
                item
                for level in self.levels
                for item in (
                    level.real_plus,
                    level.real_minus,
                    level.imaginary_plus,
                    level.imaginary_minus,
                )
            ),
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "leaf_id": self.leaf_id,
            "mechanism_id": self.mechanism_id,
            "status": self.status.value,
            "convergence_basis": self.convergence_basis,
            "usable": self.usable,
            "response": None if self.response is None else _complex_mapping(self.response),
            "signed_root_crosscheck": (
                None
                if self.signed_root_crosscheck is None
                else _complex_mapping(self.signed_root_crosscheck)
            ),
            "closed_form_response": (
                None
                if self.closed_form_response is None
                else _complex_mapping(self.closed_form_response)
            ),
            "error_channels": dict(self.error_channels),
            "baseline": self.baseline.to_mapping(),
            "levels": [level.to_mapping() for level in self.levels],
            "lineage": dict(self.lineage),
        }

    @classmethod
    def from_mapping(cls, value: object) -> "ComponentResult":
        if not isinstance(value, Mapping):
            raise ValueError("component result must be an object")
        response = value.get("response")
        signed = value.get("signed_root_crosscheck")
        closed = value.get("closed_form_response")
        channels = value.get("error_channels")
        if not isinstance(channels, Mapping) or set(channels) != set(ERROR_CHANNELS):
            raise ValueError("component error channels are invalid")
        return cls(
            job_id=str(value["job_id"]),
            leaf_id=str(value["leaf_id"]),
            mechanism_id=str(value["mechanism_id"]),
            status=ComponentStatus(str(value["status"])),
            convergence_basis=str(value["convergence_basis"]),
            response=None if response is None else _complex_from_mapping(response, "response"),
            signed_root_crosscheck=(
                None if signed is None else _complex_from_mapping(signed, "signed root")
            ),
            closed_form_response=(
                None if closed is None else _complex_from_mapping(closed, "closed form")
            ),
            error_channels={key: float(channels[key]) for key in ERROR_CHANNELS},
            baseline=RootReadout.from_mapping(value["baseline"]),
            levels=tuple(LadderLevel.from_mapping(item) for item in value["levels"]),
            lineage=dict(value["lineage"]),
        )


def _unresolved_result(
    job: ResponseComponentJob,
    status: ComponentStatus,
    baseline: RootReadout,
    levels: Sequence[LadderLevel],
) -> ComponentResult:
    return ComponentResult(
        job_id=job.job_id,
        leaf_id=job.leaf_id,
        mechanism_id=job.mechanism_id,
        status=status,
        convergence_basis="UNRESOLVED",
        response=None,
        signed_root_crosscheck=None,
        closed_form_response=None,
        error_channels={name: 0.0 for name in ERROR_CHANNELS},
        baseline=baseline,
        levels=tuple(levels),
        lineage=_result_lineage(job),
    )


def _result_lineage(job: ResponseComponentJob) -> dict[str, object]:
    return {
        "leaf_id": job.leaf_id,
        "root_reference_id": job.root.root_reference_id,
        "root_identity_sha256": job.root.identity_sha256,
        "policy_sha256": job.policy.identity_sha256,
        "backend_identity_sha256": job.backend_identity.identity_sha256,
        "equation_id": job.equation_id,
        "sampling_coordinate": job.sampling_coordinate.to_mapping(),
        "source_root_mapping": (
            None
            if job.source_root_mapping is None
            else dict(job.source_root_mapping)
        ),
    }


def _identity_status(job: ResponseComponentJob, readout: RootReadout) -> ComponentStatus | None:
    if (
        readout.root_reference_id != job.root.root_reference_id
        or readout.branch_id != job.root.branch_id
        or readout.equation_id != job.equation_id
    ):
        return ComponentStatus.BRANCH_LOSS
    if not readout.converged:
        return ComponentStatus.NOT_CONVERGED
    return None


def _validated_result(
    backend: RootReadoutBackend, job: ResponseComponentJob, result: ComponentResult
) -> ComponentResult:
    validator = getattr(backend, "validate_reconstructed_result", None)
    if validator is not None:
        validator(job, result)
    return result


def run_component(
    job: ResponseComponentJob,
    backend: RootReadoutBackend,
) -> ComponentResult:
    """Run one job through same-equation zero and complex signed amplitudes."""

    if backend.identity != job.backend_identity:
        raise ValueError("response backend identity does not match job")
    binder = getattr(backend, "bind_job", None)
    if binder is not None:
        job = binder(job)
    baseline = backend.read_root(job, 0.0j)
    initial_status = _identity_status(job, baseline)
    if initial_status is not None:
        return _validated_result(
            backend, job, _unresolved_result(job, initial_status, baseline, ())
        )

    levels: list[LadderLevel] = []
    convergence_basis = "UNRESOLVED"
    real_estimate: _AxisEstimate | None = None
    imaginary_estimate: _AxisEstimate | None = None
    combined_estimate: _AxisEstimate | None = None
    for epsilon in job.policy.epsilons:
        level = LadderLevel(
            epsilon=epsilon,
            real_plus=backend.read_root(job, complex(epsilon, 0.0)),
            real_minus=backend.read_root(job, complex(-epsilon, 0.0)),
            imaginary_plus=backend.read_root(job, complex(0.0, epsilon)),
            imaginary_minus=backend.read_root(job, complex(0.0, -epsilon)),
        )
        levels.append(level)
        for readout in (
            level.real_plus,
            level.real_minus,
            level.imaginary_plus,
            level.imaginary_minus,
        ):
            status = _identity_status(job, readout)
            if status is not None:
                return _validated_result(
                    backend,
                    job,
                    _unresolved_result(job, status, baseline, levels),
                )
        if len(levels) < 4:
            continue

        real_estimate = _axis_estimate(levels, "real")
        imaginary_estimate = _axis_estimate(levels, "imaginary")
        combined_estimate = _axis_estimate(levels, "combined")
        axis_difference = abs(real_estimate.center - imaginary_estimate.center)
        axis_allowance = job.policy.axis_tolerance_factor * max(
            real_estimate.root_radius
            + imaginary_estimate.root_radius
            + real_estimate.amplitude_radius
            + imaginary_estimate.amplitude_radius,
            job.policy.absolute_axis_floor,
        )
        if axis_difference > axis_allowance:
            return _validated_result(
                backend,
                job,
                _unresolved_result(
                    job, ComponentStatus.AXIS_MISMATCH, baseline, levels
                ),
            )
        if not level.signal_resolved(job.policy.signal_to_root_factor):
            return _validated_result(
                backend,
                job,
                _unresolved_result(
                    job, ComponentStatus.NOISE_FLOOR, baseline, levels
                ),
            )

        epsilons = [item.epsilon for item in levels]
        real_values = [item.real_secant for item in levels]
        imaginary_values = [item.imaginary_secant for item in levels]
        real_orders = _observed_orders(epsilons, real_values)
        imaginary_orders = _observed_orders(epsilons, imaginary_values)
        even_orders = _positive_orders(
            epsilons, [item.even_remainder_abs for item in levels]
        )
        real_order_ok = bool(real_orders) and real_orders[-1] >= 2.0 - job.policy.order_tolerance
        imaginary_order_ok = (
            bool(imaginary_orders)
            and imaginary_orders[-1] >= 2.0 - job.policy.order_tolerance
        )
        even_order_ok = (
            not even_orders
            or even_orders[-1] >= 2.0 - job.policy.even_order_tolerance
        )
        root_limited = (
            abs(real_values[-1] - real_values[-2])
            <= levels[-1].real_radius + levels[-2].real_radius + 1.0e-15
            and abs(imaginary_values[-1] - imaginary_values[-2])
            <= levels[-1].imaginary_radius + levels[-2].imaginary_radius + 1.0e-15
        )
        even_resolved = level.even_remainder_abs <= level.even_remainder_noise + 1.0e-15
        if root_limited and (even_resolved or even_order_ok):
            convergence_basis = "TRUNCATION_BELOW_ROOT_RESOLUTION"
            break
        if real_order_ok and imaginary_order_ok and even_order_ok:
            convergence_basis = "ORDER_RESOLVED"
            break
    else:
        return _validated_result(
            backend,
            job,
            _unresolved_result(
                job, ComponentStatus.NOT_CONVERGED, baseline, levels
            ),
        )

    if real_estimate is None or imaginary_estimate is None or combined_estimate is None:
        return _validated_result(
            backend,
            job,
            _unresolved_result(
                job, ComponentStatus.NOT_CONVERGED, baseline, levels
            ),
        )
    signed_center = 0.5 * (real_estimate.center + imaginary_estimate.center)
    closed_form = backend.closed_form_horizon_response(job)
    response = signed_center if closed_form is None else closed_form
    axis_radius = abs(real_estimate.center - imaginary_estimate.center)
    amplitude_radius = max(
        real_estimate.amplitude_radius,
        imaginary_estimate.amplitude_radius,
        combined_estimate.amplitude_radius,
        0.0 if closed_form is None else abs(closed_form - signed_center),
    )
    raw = (baseline, *(item for level in levels for item in (
        level.real_plus,
        level.real_minus,
        level.imaginary_plus,
        level.imaginary_minus,
    )))
    channels = {
        "signed-root": combined_estimate.root_radius,
        "truncation": max(item.truncation_radius for item in raw),
        "resolution": max(item.resolution_radius for item in raw),
        "seed-path": max(item.seed_path_radius for item in raw),
        "axis": axis_radius,
        "amplitude": amplitude_radius,
    }
    return _validated_result(
        backend,
        job,
        ComponentResult(
            job_id=job.job_id,
            leaf_id=job.leaf_id,
            mechanism_id=job.mechanism_id,
            status=ComponentStatus.CONVERGED,
            convergence_basis=convergence_basis,
            response=response,
            signed_root_crosscheck=signed_center,
            closed_form_response=closed_form,
            error_channels=channels,
            baseline=baseline,
            levels=tuple(levels),
            lineage=_result_lineage(job),
        ),
    )


def _runtime_fingerprint() -> str:
    return (
        f"cpython-{platform.python_version()}-"
        f"{platform.system().lower()}-{platform.machine().lower()}"
    )


def _engine_source_sha256() -> str:
    return canonical_text_sha256(Path(__file__).read_bytes())


@dataclass(frozen=True, slots=True)
class ResponsePlan:
    jobs: tuple[ResponseComponentJob, ...]
    policy: NumericalPolicy
    backend_identity: BackendIdentity

    @property
    def plan_id(self) -> str:
        return f"response-plan-{_sha256([job.job_id for job in self.jobs])}"

    @property
    def bindings(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "job_set_sha256": _sha256([job.to_mapping() for job in self.jobs]),
            "engine_source_sha256": _engine_source_sha256(),
            "backend_identity_sha256": self.backend_identity.identity_sha256,
            "policy_sha256": self.policy.identity_sha256,
            "roots_sha256": _sha256([job.root.to_mapping() for job in self.jobs]),
            "runtime_fingerprint": _runtime_fingerprint(),
        }

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": ENGINE_SCHEMA_VERSION,
            "plan_id": self.plan_id,
            "backend_identity": self.backend_identity.to_mapping(),
            "policy": self.policy.to_mapping(),
            "jobs": [job.to_mapping() for job in self.jobs],
            "bindings": self.bindings,
        }


def build_response_plan(
    leaf_ids: Sequence[str],
    *,
    policy: NumericalPolicy,
    backend_identity: BackendIdentity,
    job_binder: Callable[[ResponseComponentJob], ResponseComponentJob] | None = None,
) -> ResponsePlan:
    requested = tuple(leaf_ids)
    if not requested or len(requested) != len(set(requested)):
        raise ValueError("selected response leaf IDs must be nonempty and unique")
    requested_set = set(requested)
    ordered = [
        leaf.leaf_id
        for leaf in B_PRIME_RELEASE_DOMAIN.production_leaves
        if leaf.leaf_id in requested_set
    ]
    if set(ordered) != requested_set:
        raise ValueError("selected response leaf ID is outside frozen B-prime")
    jobs = tuple(
        ResponseComponentJob.from_leaf_id(
            leaf_id, policy=policy, backend_identity=backend_identity
        )
        for leaf_id in ordered
    )
    if job_binder is not None:
        jobs = tuple(job_binder(job) for job in jobs)
    return ResponsePlan(jobs=jobs, policy=policy, backend_identity=backend_identity)


@dataclass(frozen=True, slots=True)
class SelectedRunSummary:
    plan_id: str
    state: str
    executed_count: int
    reused_count: int
    results: tuple[ComponentResult, ...]
    checkpoint_path: str

    def to_mapping(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "state": self.state,
            "executed_count": self.executed_count,
            "reused_count": self.reused_count,
            "result_count": len(self.results),
            "results": [result.to_mapping() for result in self.results],
            "checkpoint_path": self.checkpoint_path,
            "release_admissible": False,
        }


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _checkpoint_mapping(
    plan: ResponsePlan, results: Sequence[ComponentResult]
) -> dict[str, object]:
    records = [result.to_mapping() for result in results]
    return {
        "schema_version": ENGINE_SCHEMA_VERSION,
        "state": "COMPLETE" if len(results) == len(plan.jobs) else "PARTIAL",
        "bindings": plan.bindings,
        "results": records,
        "results_sha256": _sha256(records),
    }


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate checkpoint JSON key: {key}")
        result[key] = value
    return result


def _load_checkpoint(
    plan: ResponsePlan, path: Path
) -> tuple[ComponentResult, ...]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda item: (_ for _ in ()).throw(
                ValueError(f"checkpoint contains non-finite constant {item}")
            ),
        )
    except json.JSONDecodeError as error:
        raise ValueError("checkpoint is not valid JSON") from error
    if not isinstance(value, Mapping) or set(value) != {
        "schema_version",
        "state",
        "bindings",
        "results",
        "results_sha256",
    }:
        raise ValueError("checkpoint envelope fields are invalid")
    if value["schema_version"] != ENGINE_SCHEMA_VERSION:
        raise ValueError("checkpoint schema version is invalid")
    if value["bindings"] != plan.bindings:
        raise ValueError("checkpoint bindings are stale or forged")
    records = value["results"]
    if not isinstance(records, list) or _sha256(records) != value["results_sha256"]:
        raise ValueError("checkpoint results digest is invalid")
    results = tuple(ComponentResult.from_mapping(item) for item in records)
    if len(results) > len(plan.jobs):
        raise ValueError("checkpoint has excess component results")
    for job, result in zip(plan.jobs, results):
        if result.job_id != job.job_id or result.leaf_id != job.leaf_id:
            raise ValueError("checkpoint result order or identity is invalid")
        expected_lineage = _result_lineage(job)
        if result.lineage != expected_lineage or any(
            readout.source_root_mapping != job.source_root_mapping
            for readout in result.raw_readouts
        ):
            raise ValueError("checkpoint source root mapping or lineage is invalid")
        mapping = job.source_root_mapping
        installed_identity_matches = mapping is None or (
            mapping["installed_root_reference_id"] == job.root.root_reference_id
            and mapping["installed_root_identity_sha256"] == job.root.identity_sha256
            and mapping["installed_branch_id"] == job.root.branch_id
        )
        if not installed_identity_matches or any(
            readout.root_reference_id != job.root.root_reference_id
            or readout.branch_id != job.root.branch_id
            or readout.equation_id != job.equation_id
            for readout in result.raw_readouts
        ):
            raise ValueError("checkpoint raw readout installed identity is invalid")
        if mapping is not None and result.baseline.omega != _complex_from_mapping(
            mapping["source_omega"], "checkpoint source root mapping omega"
        ):
            raise ValueError("checkpoint raw readout baseline omega is invalid")
    expected_state = "COMPLETE" if len(results) == len(plan.jobs) else "PARTIAL"
    if value["state"] != expected_state:
        raise ValueError("checkpoint state does not match result completeness")
    return results


def run_response_plan(
    plan: ResponsePlan,
    backend: RootReadoutBackend,
    checkpoint_path: str | os.PathLike[str] | Path,
    *,
    resume: bool,
) -> SelectedRunSummary:
    path = Path(checkpoint_path)
    if backend.identity != plan.backend_identity:
        raise ValueError("selected response backend identity does not match plan")
    if path.exists():
        if not resume:
            raise ValueError("cold selected response run refuses an existing checkpoint")
        existing = list(_load_checkpoint(plan, path))
    else:
        if resume:
            raise ValueError("resume requires an existing response checkpoint")
        existing = []
        _atomic_json(path, _checkpoint_mapping(plan, existing))
    reused = len(existing)
    for job in plan.jobs[reused:]:
        result = run_component(job, backend)
        existing.append(result)
        _atomic_json(path, _checkpoint_mapping(plan, existing))
    return SelectedRunSummary(
        plan_id=plan.plan_id,
        state="COMPLETE",
        executed_count=len(existing) - reused,
        reused_count=reused,
        results=tuple(existing),
        checkpoint_path=str(path),
    )


def validate_response_checkpoint(
    plan: ResponsePlan,
    checkpoint_path: str | os.PathLike[str] | Path,
) -> SelectedRunSummary:
    path = Path(checkpoint_path)
    results = _load_checkpoint(plan, path)
    return SelectedRunSummary(
        plan_id=plan.plan_id,
        state="COMPLETE" if len(results) == len(plan.jobs) else "PARTIAL",
        executed_count=0,
        reused_count=len(results),
        results=results,
        checkpoint_path=str(path),
    )


RECORDED_REPLAY_BACKEND_ID = "recorded-response-risk-replay"
_PINNED_SOURCE_COMMIT = "0c1e8a3d3bca6e608c34e111476a4f6dcb73e86e"
_REPLAY_RESOURCES: Mapping[str, tuple[str, str]] = {
    "baselines": (
        "baselines.fixture",
        "b23966dca92d3ef4ecea9123e0ddef9eb70ee92ccd45acd8e0eab18f7924f5be",
    ),
    "components": (
        "components.fixture",
        "372f37cd8e69ab38fec577a4453a10c9a7972b52551d4f0acf96a85f3206bb19",
    ),
    "levels": (
        "levels.fixture",
        "cef7635465a6ad91ed37be52099308db2099779e1b87b916e8e491ee94201ab9",
    ),
    "protocol": (
        "protocol.fixture",
        "25172794cd1b16e6589690a29fc3809453cf3a58d0f252dd5055906666708c99",
    ),
    "reduction": (
        "reduction.fixture",
        "5a9e658948100436de9e514615a9d68d86b7961ce27f31f981aec965deb9e780",
    ),
    "repeats": (
        "repeats.fixture",
        "21e3910b4caa4c3c50df4e5cb7f1bce29712907b794b77081bcffe578d6193bd",
    ),
    "signed-roots": (
        "signed-roots.fixture",
        "60ac24ef74010ad3b07acdc5d730872bce527e55d08e92b10b1bd8dbd826362e",
    ),
    "summary": (
        "summary.fixture",
        "60d88305ce85e4182e69dda8f83b23f0be3a61d2773020d170f3ab15b3a08ba8",
    ),
}


@dataclass(frozen=True, slots=True)
class RecordedSmokeCase:
    leaf_id: str
    component_id: str


RECORDED_SMOKE_CASES = (
    RecordedSmokeCase(
        "b-prime-leaf-9e5777728144433e089f9559b92b6e139e16115a5a53099f40403a45297aa3c3",
        "a0.95-s-2-l2-m2-n0-unclassified-gravitational-horizon_admittance",
    ),
    RecordedSmokeCase(
        "b-prime-leaf-7ef38d6f95c161d0b4c6650d470898c0742ad6ae8440e89956312344c0db6aac",
        "a0.95-s-2-l3-m3-n0-unclassified-gravitational-fixed_r3",
    ),
    RecordedSmokeCase(
        "b-prime-leaf-7f12759244119c8e819ef09cc5f3ec2e76054d77b6a1e0b12e3bb742397b635e",
        "a0.95-s-2-l4-m4-n0-unclassified-gravitational-light_ring",
    ),
    RecordedSmokeCase(
        "b-prime-leaf-4c8594e4a59486a1c56206e41cd7f7f3ff1ab5193a5ff6b699cbe9492bc45355",
        "a0.999-s-2-l2-m2-n0-unclassified-gravitational-horizon_admittance",
    ),
    RecordedSmokeCase(
        "b-prime-leaf-e0a48b72b4071c5c88c66955420dc2748cfeeac577b8fd1c399f171f5fa08475",
        "a0.999-s-2-l4-m4-n0-unclassified-gravitational-light_ring",
    ),
)
_RECORDED_CASE_BY_LEAF = {case.leaf_id: case for case in RECORDED_SMOKE_CASES}


def _fixture_rows(data: bytes, subject: str) -> list[dict[str, str]]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"recorded {subject} is not UTF-8") from error
    rows = list(csv.DictReader(io.StringIO(text, newline="")))
    if not rows:
        raise ValueError(f"recorded {subject} is empty")
    return rows


class RecordedReplayBackend:
    """Byte-authenticated root-readout replay; never a scientific producer."""

    identity = BackendIdentity(
        backend_id=RECORDED_REPLAY_BACKEND_ID,
        implementation_version="1",
        source_commit=_PINNED_SOURCE_COMMIT,
        source_blobs=(
            ("determinant-backend", "b65f2236f828204aa21dfa8d9bc79c8a1c66ca3b"),
            ("local-response", "341ce9db7dda8108a96e3f7536380b9b45bd6c3b"),
            ("refinement", "69733ac4d0a74696445ff683aaaaeb5fd64e44c1"),
        ),
        runtime_fingerprint="recorded-replay-no-solver",
    )

    def __init__(
        self,
        *,
        bundle_sha256s: Mapping[str, str],
        baselines: Mapping[str, Mapping[str, str]],
        components: Mapping[str, Mapping[str, str]],
        signed_roots: Mapping[tuple[str, str, str], Mapping[str, str]],
        channel_radii: Mapping[str, Mapping[str, float]],
        level_counts: Mapping[str, int],
    ) -> None:
        self.bundle_sha256s = dict(bundle_sha256s)
        self._baselines = dict(baselines)
        self._components = dict(components)
        self._signed_roots = dict(signed_roots)
        self._channel_radii = {
            component_id: dict(channels)
            for component_id, channels in channel_radii.items()
        }
        self._level_counts = dict(level_counts)

    @classmethod
    def load(cls) -> "RecordedReplayBackend":
        directory = resources.files("windows_solver").joinpath(
            "data", "response_replay"
        )
        files: dict[str, bytes] = {}
        hashes: dict[str, str] = {}
        for label, (filename, expected_sha256) in _REPLAY_RESOURCES.items():
            data = directory.joinpath(filename).read_bytes()
            actual = hashlib.sha256(data).hexdigest()
            if actual != expected_sha256:
                raise ValueError(f"recorded replay {label} SHA-256 mismatch")
            files[label] = data
            hashes[label] = actual
        baselines = {
            row["component_id"]: row
            for row in _fixture_rows(files["baselines"], "baselines")
        }
        components = {
            row["component_id"]: row
            for row in _fixture_rows(files["components"], "components")
        }
        levels_by_component: dict[str, set[str]] = {}
        for row in _fixture_rows(files["levels"], "levels"):
            levels_by_component.setdefault(row["component_id"], set()).add(
                float(row["epsilon"]).hex()
            )
        repeat_channels: dict[str, dict[str, list[float]]] = {}
        repeat_labels = {
            "truncation": "truncation",
            "resolution": "resolution",
            "root": "seed-path",
        }
        for row in _fixture_rows(files["repeats"], "repeats"):
            try:
                channel = repeat_labels[row["error_channel"]]
            except KeyError as error:
                raise ValueError("recorded repeat error channel is invalid") from error
            contribution = float(row["channel_radius_contribution_abs"])
            if not math.isfinite(contribution) or contribution < 0.0:
                raise ValueError("recorded repeat channel radius is invalid")
            repeat_channels.setdefault(row["component_id"], {}).setdefault(
                channel, []
            ).append(contribution)
        signed: dict[tuple[str, str, str], Mapping[str, str]] = {}
        for row in _fixture_rows(files["signed-roots"], "signed roots"):
            key = (
                row["component_id"],
                float(row["amplitude_re"]).hex(),
                float(row["amplitude_im"]).hex(),
            )
            if key in signed:
                raise ValueError("recorded signed roots contain duplicate amplitudes")
            signed[key] = row
        expected_ids = {case.component_id for case in RECORDED_SMOKE_CASES}
        if not expected_ids <= set(baselines) or not expected_ids <= set(components):
            raise ValueError("recorded smoke components are incomplete")
        channel_radii: dict[str, dict[str, float]] = {}
        level_counts: dict[str, int] = {}
        for component_id in expected_ids:
            component = components[component_id]
            try:
                level_count = int(component["ladder_level_count"])
            except ValueError as error:
                raise ValueError("recorded component ladder count is invalid") from error
            actual_level_count = len(levels_by_component.get(component_id, ()))
            if actual_level_count != level_count:
                raise ValueError("recorded component and level counts disagree")
            level_counts[component_id] = level_count
            if component["status"] == ComponentStatus.CONVERGED.value:
                channels = repeat_channels.get(component_id, {})
                if set(channels) != {"truncation", "resolution", "seed-path"}:
                    raise ValueError("recorded converged component error channels are incomplete")
                channel_radii[component_id] = {
                    name: max(values) for name, values in channels.items()
                }
            else:
                channel_radii[component_id] = {
                    name: max(repeat_channels.get(component_id, {}).get(name, (0.0,)))
                    for name in ("truncation", "resolution", "seed-path")
                }
        return cls(
            bundle_sha256s=hashes,
            baselines=baselines,
            components=components,
            signed_roots=signed,
            channel_radii=channel_radii,
            level_counts=level_counts,
        )

    def _case(self, job: ResponseComponentJob) -> RecordedSmokeCase:
        if job.backend_identity != self.identity:
            raise ValueError("recorded replay backend identity does not match job")
        case = _RECORDED_CASE_BY_LEAF.get(job.leaf_id)
        if case is None:
            raise ValueError("selected leaf has no authenticated recorded replay")
        baseline = self._baselines[case.component_id]
        component = self._components[case.component_id]
        expected_mechanism = {
            "horizon-admittance": "horizon_admittance",
            "exterior-fixed-r3": "fixed_r3",
            "exterior-light-ring": "light_ring",
        }[job.mechanism_id]
        expected_mode_label = (
            f"s{job.mode.s}-l{job.mode.ell}-m{job.mode.m}-n{job.mode.n}-"
            f"unclassified-{job.mode.polarization}"
        )
        for row in (baseline, component):
            if (
                int(row["s"]) != job.mode.s
                or int(row["ell"]) != job.mode.ell
                or int(row["m"]) != job.mode.m
                or int(row["n"]) != job.mode.n
                or float(row["spin"]).hex() != job.spin.hex()
                or row["mechanism_id"] != expected_mechanism
                or row["mode_label"] != expected_mode_label
                or row["branch"] != "unclassified"
                or row["polarization"] != job.mode.polarization
            ):
                raise ValueError("recorded replay mode/spin/mechanism identity mismatch")
        recorded_root = complex(
            float(baseline["omega_re"]), float(baseline["omega_im"])
        )
        if abs(recorded_root - job.root.omega) > 5.0e-9:
            raise ValueError("recorded replay baseline does not correspond to bound root")
        return case

    def source_root_mapping(
        self, job: ResponseComponentJob
    ) -> dict[str, object]:
        """Authenticate the recorded source root and its installed-root mapping."""

        case = self._case(job)
        baseline = self._baselines[case.component_id]
        source_omega = complex(
            float(baseline["omega_re"]), float(baseline["omega_im"])
        )
        source_identity = {
            "source_bundle_baselines_sha256": self.bundle_sha256s["baselines"],
            "component_id": case.component_id,
            "mode": job.mode.to_mapping(),
            "spin_binary64_hex": job.spin.hex(),
            "mechanism_id": baseline["mechanism_id"],
            "branch_id": baseline["branch"],
            "polarization": baseline["polarization"],
            "omega": _complex_mapping(source_omega),
        }
        source_identity_sha256 = _sha256(source_identity)
        receipt: dict[str, object] = {
            "schema_version": 1,
            "mapping_protocol": (
                "authenticated-recorded-source-to-installed-spectral-root"
            ),
            "source_bundle_baselines_sha256": self.bundle_sha256s["baselines"],
            "source_root_reference_id": (
                f"recorded-source-root-{source_identity_sha256}"
            ),
            "source_root_identity_sha256": source_identity_sha256,
            "source_branch_id": baseline["branch"],
            "source_omega": _complex_mapping(source_omega),
            "installed_root_reference_id": job.root.root_reference_id,
            "installed_root_identity_sha256": job.root.identity_sha256,
            "installed_branch_id": job.root.branch_id,
            "installed_omega": _complex_mapping(job.root.omega),
            "mapping_tolerance_abs": _RECORDED_ROOT_MAPPING_TOLERANCE_ABS,
            "measured_delta_abs": abs(source_omega - job.root.omega),
        }
        receipt["mapping_receipt_sha256"] = _sha256(receipt)
        return _validated_source_root_mapping(receipt)  # type: ignore[return-value]

    def bind_job(self, job: ResponseComponentJob) -> ResponseComponentJob:
        receipt = self.source_root_mapping(job)
        if job.source_root_mapping is not None:
            if job.source_root_mapping != receipt:
                raise ValueError("recorded replay source root mapping is invalid")
            return job
        return replace(job, source_root_mapping=receipt)

    def read_root(self, job: ResponseComponentJob, amplitude: complex) -> RootReadout:
        case = self._case(job)
        expected_mapping = self.source_root_mapping(job)
        if job.source_root_mapping != expected_mapping:
            raise ValueError("recorded replay source root mapping is missing or invalid")
        value = _finite_complex(amplitude, "recorded replay amplitude")
        if value == 0.0j:
            row = self._baselines[case.component_id]
        else:
            row = self._signed_roots.get(
                (case.component_id, value.real.hex(), value.imag.hex())
            )
            if row is None:
                raise ValueError("recorded replay has no exact signed amplitude")
        channels = self._channel_radii[case.component_id]
        return RootReadout(
            omega=complex(float(row["omega_re"]), float(row["omega_im"])),
            determinant_residual_abs=float(row["determinant_residual_abs"]),
            determinant_derivative_abs=float(row["determinant_derivative_abs"]),
            converged=row["converged"] == "True",
            root_reference_id=job.root.root_reference_id,
            branch_id=job.root.branch_id,
            equation_id=job.equation_id,
            truncation_radius=channels["truncation"],
            resolution_radius=channels["resolution"],
            seed_path_radius=channels["seed-path"],
            source_root_mapping=expected_mapping,
        )

    def closed_form_horizon_response(
        self, job: ResponseComponentJob
    ) -> complex | None:
        self._case(job)
        return None

    def recorded_component(self, component_id: str) -> Mapping[str, str]:
        try:
            return dict(self._components[component_id])
        except KeyError as error:
            raise ValueError("unknown recorded component_id") from error

    def validate_reconstructed_result(
        self, job: ResponseComponentJob, result: ComponentResult
    ) -> None:
        job = self.bind_job(job)
        case = self._case(job)
        recorded = self._components[case.component_id]
        if (
            result.job_id != job.job_id
            or result.leaf_id != job.leaf_id
            or result.mechanism_id != job.mechanism_id
            or result.status.value != recorded["status"]
            or result.convergence_basis != recorded["convergence_basis"]
            or len(result.levels) != self._level_counts[case.component_id]
            or result.lineage != _result_lineage(job)
            or any(
                readout.source_root_mapping != job.source_root_mapping
                for readout in result.raw_readouts
            )
        ):
            raise ValueError("reconstructed replay component identity/outcome mismatch")
        if result.status is not ComponentStatus.CONVERGED:
            if result.response is not None or recorded["response_available"] != "False":
                raise ValueError("unresolved replay component fabricated a response")
            return
        if result.response is None or recorded["response_available"] != "True":
            raise ValueError("converged replay component is missing its response")

        def close(actual: float, expected: str) -> bool:
            return math.isclose(actual, float(expected), rel_tol=5.0e-13, abs_tol=5.0e-15)

        channels = result.error_channels
        complete_matches = (
            close(result.response.real, recorded["response_re"])
            and close(result.response.imag, recorded["response_im"])
            and close(channels["axis"], recorded["axis_radius_abs"])
            and close(channels["truncation"], recorded["truncation_radius_abs"])
            and close(channels["resolution"], recorded["resolution_radius_abs"])
            and close(
                channels["signed-root"] + channels["seed-path"],
                recorded["root_radius_abs"],
            )
            and close(
                channels["amplitude"] + channels["axis"],
                recorded["amplitude_radius_abs"],
            )
            and close(
                channels["signed-root"]
                + channels["seed-path"]
                + channels["truncation"]
                + channels["resolution"]
                + channels["amplitude"]
                + channels["axis"],
                recorded["uncertainty_radius_abs"],
            )
        )
        if not complete_matches:
            raise ValueError("reconstructed replay component disagrees with recorded evidence")


from .native_response_kernel import (  # noqa: E402 - types above form the boundary
    NativeResourceUnavailableError,
    VettedNativeDeterminantKernel,
)
