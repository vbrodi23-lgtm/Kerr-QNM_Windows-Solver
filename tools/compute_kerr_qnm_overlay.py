"""Build the authenticated sparse 44-root Kerr QNM overlay for M02 B-prime.

This module is an offline numerical boundary.  The installed package consumes
only the generated CSV and receipt; NumPy and SciPy remain optional build-time
dependencies.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import argparse
import csv
from dataclasses import dataclass
from fractions import Fraction
import hashlib
from importlib import metadata
import io
import itertools
import json
import math
import os
from pathlib import Path
import platform
import tempfile
from types import MappingProxyType
from typing import Callable, Mapping

try:
    from . import kerr_angular, kerr_cf_solver
except ImportError:  # pragma: no cover - direct script execution
    import kerr_angular
    import kerr_cf_solver


DIRECT_SPINS = (
    Fraction(19, 20),
    Fraction(97, 100),
    Fraction(49, 50),
    Fraction(99, 100),
    Fraction(199, 200),
    Fraction(997, 1000),
    Fraction(999, 1000),
    Fraction(1999, 2000),
    Fraction(9999, 10000),
)
DEEP_SURFACE_GRAVITIES = (
    Fraction(1, 100),
    Fraction(1, 200),
    Fraction(1, 500),
    Fraction(1, 1000),
)

MAXIMUM_OPTIMIZER_RESIDUAL_ABS = 1e-8
MAXIMUM_CONTINUED_FRACTION_ERROR = 1e-9
MAXIMUM_ANGULAR_REFINEMENT_ABS = 1e-9
MAXIMUM_REPEAT_POLISH_DELTA_ABS = 1e-9
MAXIMUM_INDEPENDENT_PATH_DELTA_ABS = 1e-8
MAXIMUM_REVERSE_DELTA_ABS = 1e-8
MINIMUM_ASSIGNED_SEPARATION_ABS = 1e-6
MINIMUM_ASSIGNMENT_RELATIVE_GAP = 0.05
MAXIMUM_CORRECTION_OVER_SEPARATION = 0.24
MINIMUM_ADAPTIVE_STEP = 0.003
BASE_CATALOG_SHA256 = (
    "9ebae4271309cd45a1b26c90d31155602ed8ef33bb79069adb5897e8afe7a564"
)
BASE_RECEIPT_SHA256 = (
    "61a428a858de1eb7e42fe4cbbda37bf1fddcc808d98be2a62fd33ef4b5b74379"
)


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8") + b"\n"


OVERLAY_POLICY = MappingProxyType(
    {
        "angular_padding": 20,
        "angular_overlap_minimum": 0.9,
        "angular_refinement_padding": 24,
        "assignment_minimum_relative_gap": MINIMUM_ASSIGNMENT_RELATIVE_GAP,
        "branch_id": "schwarzschild-overtone-continuation",
        "canonical_repeat_root_tolerance": 1e-12,
        "canonical_root_tolerance": 1e-10,
        "continued_fraction_error_maximum": MAXIMUM_CONTINUED_FRACTION_ERROR,
        "formal_root_enclosure": False,
        "independent_path_delta_maximum": MAXIMUM_INDEPENDENT_PATH_DELTA_ABS,
        "minimum_adaptive_step": MINIMUM_ADAPTIVE_STEP,
        "minimum_assigned_separation_abs": MINIMUM_ASSIGNED_SEPARATION_ABS,
        "optimizer_residual_abs_maximum": MAXIMUM_OPTIMIZER_RESIDUAL_ABS,
        "predictor_correction_over_separation_maximum": (
            MAXIMUM_CORRECTION_OVER_SEPARATION
        ),
        "repeat_polish_delta_abs_maximum": MAXIMUM_REPEAT_POLISH_DELTA_ABS,
        "reverse_delta_abs_maximum": MAXIMUM_REVERSE_DELTA_ABS,
        "schedule_a_coordinate": "x=-log(sqrt((1-chi)(1+chi)))",
        "schedule_a_step_maximum_by_ell": {"2": 0.16, "3": 0.12, "4": 0.12},
        "schedule_b_coordinate": "y=-log(M-kappa)",
        "schedule_b_step_maximum_by_ell": {"2": 0.12, "3": 0.09, "4": 0.09},
        "spin_weight": -2,
    }
)
POLICY_SHA256 = hashlib.sha256(
    _canonical_json_bytes(dict(OVERLAY_POLICY))
).hexdigest()

OUTPUT_COLUMNS = (
    "s",
    "ell",
    "m",
    "n",
    "branch_id",
    "source_coordinate_id",
    "source_coordinate_numerator",
    "source_coordinate_denominator",
    "source_transformation_id",
    "spin_numerator",
    "spin_denominator",
    "spin_float",
    "spin_binary64_hex",
    "omega_re_M",
    "omega_im_M",
    "angular_A_re",
    "angular_A_im",
    "root_solver_success",
    "optimizer_residual_abs",
    "continued_fraction_error",
    "continued_fraction_terms",
    "angular_padding",
    "angular_refinement_padding",
    "angular_refinement_abs",
    "repeat_polish_delta_abs",
    "predictor_correction_abs",
    "predictor_correction_over_separation",
    "assigned_separation_abs",
    "assignment_relative_gap",
    "canonical_polish_delta_abs",
    "independent_path_delta_abs",
    "reverse_delta_abs",
    "angular_overlap_min",
    "schedule_a_steps",
    "schedule_b_steps",
    "minimum_adaptive_step",
)


def spin_from_surface_gravity(coordinate: Fraction) -> float:
    """Return the frozen stable binary64 prograde spin for exact ``M*kappa``."""

    value = float(coordinate)
    horizon_gap = 2.0 * value / (1.0 - 2.0 * value)
    return math.sqrt(1.0 - horizon_gap * horizon_gap)


@dataclass(frozen=True, slots=True)
class OverlayTarget:
    ell: int
    m: int
    n: int
    source_coordinate_id: str
    source_coordinate: Fraction
    source_transformation_id: str
    spin: float

    @property
    def spin_hex(self) -> str:
        return self.spin.hex()

    @property
    def selection_key(self) -> tuple[int, int, int, str]:
        return self.ell, self.m, self.n, self.spin_hex

    @property
    def order_key(self) -> tuple[int, int, int, float]:
        return self.ell, self.m, self.n, self.spin


def overlay_targets() -> tuple[OverlayTarget, ...]:
    """Enumerate exactly the 44 missing B-prime selectors in canonical order."""

    targets: list[OverlayTarget] = []
    direct_high = DIRECT_SPINS[-2:]
    for ell, m, overtones, spins in (
        (2, 2, (0, 1, 2), direct_high),
        (3, 3, (0, 1), direct_high),
        (4, 4, (0, 1), DIRECT_SPINS),
    ):
        for n in overtones:
            for coordinate in spins:
                targets.append(
                    OverlayTarget(
                        ell=ell,
                        m=m,
                        n=n,
                        source_coordinate_id="a-over-M",
                        source_coordinate=coordinate,
                        source_transformation_id="identity-a-over-M",
                        spin=float(coordinate),
                    )
                )
    for ell, m, n in ((2, 2, 0), (2, 2, 1), (2, 2, 2), (2, 1, 0)):
        for coordinate in DEEP_SURFACE_GRAVITIES:
            targets.append(
                OverlayTarget(
                    ell=ell,
                    m=m,
                    n=n,
                    source_coordinate_id="M-kappa",
                    source_coordinate=coordinate,
                    source_transformation_id=(
                        "kerr-prograde-spin-from-dimensionless-surface-gravity"
                    ),
                    spin=spin_from_surface_gravity(coordinate),
                )
            )
    return tuple(sorted(targets, key=lambda target: target.order_key))


@dataclass(frozen=True, slots=True)
class OverlayResult:
    target: OverlayTarget
    omega: complex
    angular_a: complex
    optimizer_residual_abs: float
    continued_fraction_error: float
    continued_fraction_terms: int
    angular_refinement_abs: float
    repeat_polish_delta_abs: float
    predictor_correction_abs: float
    predictor_correction_over_separation: float
    assigned_separation_abs: float
    assignment_relative_gap: float
    canonical_polish_delta_abs: float
    independent_path_delta_abs: float
    reverse_delta_abs: float
    angular_overlap_min: float
    schedule_a_steps: int
    schedule_b_steps: int
    minimum_adaptive_step: float


@dataclass(frozen=True, slots=True)
class BaseRoot:
    ell: int
    m: int
    n: int
    spin: float
    spin_hex: str
    omega: complex
    angular_a: complex
    optimizer_residual_abs: float

    @property
    def selection_key(self) -> tuple[int, int, int, str]:
        return self.ell, self.m, self.n, self.spin_hex


@dataclass(frozen=True, slots=True)
class OverlayBuild:
    catalog_bytes: bytes
    receipt_bytes: bytes
    checkpoint_bytes: bytes


@dataclass(frozen=True, slots=True)
class _ContinuationNode:
    coordinate: float
    spin: float
    roots: Mapping[int, CandidateRoot]


@dataclass(frozen=True, slots=True)
class _PathTarget:
    node: _ContinuationNode
    predictor_correction_abs: Mapping[int, float]
    correction_over_separation: Mapping[int, float]
    assigned_separation_abs: Mapping[int, float]
    assignment_relative_gap: float
    angular_overlap: Mapping[int, float]
    steps: int
    minimum_step: float


@dataclass(frozen=True, slots=True)
class _PolishedRoot:
    omega: complex
    angular_a: complex
    optimizer_residual_abs: float
    continued_fraction_error: float
    continued_fraction_terms: int
    angular_refinement_abs: float
    repeat_polish_delta_abs: float
    canonical_polish_delta_abs: float


def validate_results(
    results: tuple[OverlayResult, ...],
    *,
    expected_targets: tuple[OverlayTarget, ...] | None = None,
) -> None:
    """Fail closed unless every numerical and exact-target gate is satisfied."""

    targets = overlay_targets() if expected_targets is None else expected_targets
    if tuple(result.target for result in results) != targets:
        raise ValueError("overlay results do not match the exact target order")
    if len({result.target.selection_key for result in results}) != len(results):
        raise ValueError("overlay results contain duplicate selection keys")
    for index, result in enumerate(results, start=1):
        finite = (
            result.omega.real,
            result.omega.imag,
            result.angular_a.real,
            result.angular_a.imag,
            result.optimizer_residual_abs,
            result.continued_fraction_error,
            result.angular_refinement_abs,
            result.repeat_polish_delta_abs,
            result.predictor_correction_abs,
            result.predictor_correction_over_separation,
            result.assigned_separation_abs,
            result.assignment_relative_gap,
            result.canonical_polish_delta_abs,
            result.independent_path_delta_abs,
            result.reverse_delta_abs,
            result.angular_overlap_min,
            result.minimum_adaptive_step,
        )
        if not all(math.isfinite(value) for value in finite):
            raise ValueError(f"overlay result {index} contains non-finite evidence")
        if result.omega.imag >= 0.0:
            raise ValueError(f"overlay result {index} is not a damped root")
        nonnegative = finite[4:]
        if any(value < 0.0 for value in nonnegative):
            raise ValueError(f"overlay result {index} contains negative diagnostics")
        if result.optimizer_residual_abs > MAXIMUM_OPTIMIZER_RESIDUAL_ABS:
            raise ValueError(f"overlay result {index} optimizer residual exceeds ceiling")
        if result.continued_fraction_error > MAXIMUM_CONTINUED_FRACTION_ERROR:
            raise ValueError(f"overlay result {index} continued-fraction error exceeds ceiling")
        if result.angular_refinement_abs > MAXIMUM_ANGULAR_REFINEMENT_ABS:
            raise ValueError(f"overlay result {index} angular refinement exceeds ceiling")
        if result.repeat_polish_delta_abs > MAXIMUM_REPEAT_POLISH_DELTA_ABS:
            raise ValueError(f"overlay result {index} repeat polish exceeds ceiling")
        if result.independent_path_delta_abs > MAXIMUM_INDEPENDENT_PATH_DELTA_ABS:
            raise ValueError(f"overlay result {index} independent path delta exceeds ceiling")
        if result.reverse_delta_abs > MAXIMUM_REVERSE_DELTA_ABS:
            raise ValueError(f"overlay result {index} reverse delta exceeds ceiling")
        if result.assigned_separation_abs < MINIMUM_ASSIGNED_SEPARATION_ABS:
            raise ValueError(f"overlay result {index} assigned roots collide")
        if result.assignment_relative_gap < MINIMUM_ASSIGNMENT_RELATIVE_GAP:
            raise ValueError(f"overlay result {index} assignment gap is ambiguous")
        if (
            result.predictor_correction_over_separation
            > MAXIMUM_CORRECTION_OVER_SEPARATION
        ):
            raise ValueError(f"overlay result {index} predictor correction exceeds ceiling")
        if not 0.9 <= result.angular_overlap_min <= 1.0:
            raise ValueError(f"overlay result {index} angular overlap is invalid")
        if (
            isinstance(result.continued_fraction_terms, bool)
            or result.continued_fraction_terms < 1000
            or result.continued_fraction_terms >= 60000
            or isinstance(result.schedule_a_steps, bool)
            or isinstance(result.schedule_b_steps, bool)
            or result.schedule_a_steps <= 0
            or result.schedule_b_steps <= 0
            or result.minimum_adaptive_step < MINIMUM_ADAPTIVE_STEP
        ):
            raise ValueError(f"overlay result {index} numerical policy is invalid")


def _parse_canonical_json(data: bytes, subject: str) -> Mapping[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate {subject} key: {key}")
            value[key] = item
        return value

    def reject_nonfinite(value: str) -> object:
        raise ValueError(f"non-finite {subject} value: {value}")

    try:
        parsed = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{subject} is not canonical JSON") from error
    if not isinstance(parsed, Mapping) or data != _canonical_json_bytes(parsed):
        raise ValueError(f"{subject} is not canonical JSON")
    return parsed


def _authenticate_base_inputs(
    base_catalog_bytes: bytes, base_receipt_bytes: bytes
) -> tuple[BaseRoot, ...]:
    if hashlib.sha256(base_catalog_bytes).hexdigest() != BASE_CATALOG_SHA256:
        raise ValueError("base catalog SHA-256 does not match the admitted parent")
    if hashlib.sha256(base_receipt_bytes).hexdigest() != BASE_RECEIPT_SHA256:
        raise ValueError("base receipt SHA-256 does not match the admitted parent")
    receipt = _parse_canonical_json(base_receipt_bytes, "base receipt")
    catalog_binding = receipt.get("catalog")
    if not isinstance(catalog_binding, Mapping):
        raise ValueError("base receipt catalog binding is missing")
    if (
        catalog_binding.get("sha256") != BASE_CATALOG_SHA256
        or catalog_binding.get("row_count_excluding_header") != 2736
    ):
        raise ValueError("base receipt does not bind the admitted catalog")
    try:
        text = base_catalog_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("base catalog must be UTF-8") from error
    reader = csv.DictReader(io.StringIO(text), strict=True)
    roots: list[BaseRoot] = []
    try:
        for row in reader:
            spin = float(row["chi_float"])
            if row["chi_float_hex"] != spin.hex():
                raise ValueError("base catalog spin identity is invalid")
            roots.append(
                BaseRoot(
                    ell=int(row["ell"]),
                    m=int(row["m"]),
                    n=int(row["n"]),
                    spin=spin,
                    spin_hex=row["chi_float_hex"],
                    omega=complex(
                        float(row["omega_re_M"]), float(row["omega_im_M"])
                    ),
                    angular_a=complex(
                        float(row["angular_A_re"]),
                        float(row["angular_A_im"]),
                    ),
                    optimizer_residual_abs=float(
                        row["optimizer_residual_abs"]
                    ),
                )
            )
    except (csv.Error, KeyError, ValueError) as error:
        raise ValueError("base catalog cannot seed the overlay") from error
    if len(roots) != 2736 or len({root.selection_key for root in roots}) != 2736:
        raise ValueError("base catalog does not contain 2,736 unique roots")
    return tuple(roots)


def _target_mapping(target: OverlayTarget) -> dict[str, object]:
    spin_numerator, spin_denominator = target.spin.as_integer_ratio()
    return {
        "ell": target.ell,
        "m": target.m,
        "n": target.n,
        "source_coordinate_id": target.source_coordinate_id,
        "source_coordinate_numerator": target.source_coordinate.numerator,
        "source_coordinate_denominator": target.source_coordinate.denominator,
        "source_transformation_id": target.source_transformation_id,
        "spin_numerator": spin_numerator,
        "spin_denominator": spin_denominator,
        "spin_binary64_hex": target.spin_hex,
    }


def _target_from_mapping(value: object) -> OverlayTarget:
    if not isinstance(value, Mapping):
        raise ValueError("checkpoint target must be an object")
    expected = {
        "ell", "m", "n", "source_coordinate_id",
        "source_coordinate_numerator", "source_coordinate_denominator",
        "source_transformation_id", "spin_numerator", "spin_denominator",
        "spin_binary64_hex",
    }
    if set(value) != expected:
        raise ValueError("checkpoint target schema is invalid")
    source = Fraction(
        int(value["source_coordinate_numerator"]),
        int(value["source_coordinate_denominator"]),
    )
    spin = float.fromhex(str(value["spin_binary64_hex"]))
    if spin.as_integer_ratio() != (
        int(value["spin_numerator"]), int(value["spin_denominator"])
    ):
        raise ValueError("checkpoint target spin identity is invalid")
    return OverlayTarget(
        ell=int(value["ell"]),
        m=int(value["m"]),
        n=int(value["n"]),
        source_coordinate_id=str(value["source_coordinate_id"]),
        source_coordinate=source,
        source_transformation_id=str(value["source_transformation_id"]),
        spin=spin,
    )


_RESULT_FLOAT_FIELDS = (
    "optimizer_residual_abs",
    "continued_fraction_error",
    "angular_refinement_abs",
    "repeat_polish_delta_abs",
    "predictor_correction_abs",
    "predictor_correction_over_separation",
    "assigned_separation_abs",
    "assignment_relative_gap",
    "canonical_polish_delta_abs",
    "independent_path_delta_abs",
    "reverse_delta_abs",
    "angular_overlap_min",
    "minimum_adaptive_step",
)


def _result_mapping(result: OverlayResult) -> dict[str, object]:
    return {
        "target": _target_mapping(result.target),
        "omega_re_M": result.omega.real,
        "omega_im_M": result.omega.imag,
        "angular_A_re": result.angular_a.real,
        "angular_A_im": result.angular_a.imag,
        "continued_fraction_terms": result.continued_fraction_terms,
        "schedule_a_steps": result.schedule_a_steps,
        "schedule_b_steps": result.schedule_b_steps,
        **{field: getattr(result, field) for field in _RESULT_FLOAT_FIELDS},
    }


def _result_from_mapping(value: object) -> OverlayResult:
    if not isinstance(value, Mapping):
        raise ValueError("checkpoint result must be an object")
    expected = {
        "target", "omega_re_M", "omega_im_M", "angular_A_re",
        "angular_A_im", "continued_fraction_terms", "schedule_a_steps",
        "schedule_b_steps", *_RESULT_FLOAT_FIELDS,
    }
    if set(value) != expected:
        raise ValueError("checkpoint result schema is invalid")
    return OverlayResult(
        target=_target_from_mapping(value["target"]),
        omega=complex(float(value["omega_re_M"]), float(value["omega_im_M"])),
        angular_a=complex(
            float(value["angular_A_re"]), float(value["angular_A_im"])
        ),
        continued_fraction_terms=int(value["continued_fraction_terms"]),
        schedule_a_steps=int(value["schedule_a_steps"]),
        schedule_b_steps=int(value["schedule_b_steps"]),
        **{field: float(value[field]) for field in _RESULT_FLOAT_FIELDS},
    )


def _runtime_identity() -> dict[str, object]:
    dependencies: dict[str, str] = {}
    for name in ("numpy", "scipy"):
        try:
            dependencies[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            dependencies[name] = "not-installed"
    return {
        "dependencies": dependencies,
        "platform": platform.platform(),
        "python": platform.python_version(),
    }


def _generator_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _target_set_sha256() -> str:
    return hashlib.sha256(
        _canonical_json_bytes([_target_mapping(target) for target in overlay_targets()])
    ).hexdigest()


def _backend_identity(backend: object) -> dict[str, object]:
    identity = getattr(backend, "identity", None)
    if not isinstance(identity, Mapping) or not identity:
        raise ValueError("overlay backend identity is missing")
    value = dict(identity)
    _canonical_json_bytes(value)
    return value


def _checkpoint_bindings(backend: object) -> dict[str, object]:
    return {
        "backend": _backend_identity(backend),
        "generator_sha256": _generator_sha256(),
        "parents": {
            "base_catalog_sha256": BASE_CATALOG_SHA256,
            "base_receipt_sha256": BASE_RECEIPT_SHA256,
        },
        "policy_sha256": POLICY_SHA256,
        "runtime": _runtime_identity(),
        "target_set_sha256": _target_set_sha256(),
    }


def _checkpoint_bytes(
    results: tuple[OverlayResult, ...], backend: object
) -> bytes:
    result_mappings = [_result_mapping(result) for result in results]
    return _canonical_json_bytes(
        {
            "bindings": _checkpoint_bindings(backend),
            "complete": len(results) == len(overlay_targets()),
            "results": result_mappings,
            "results_sha256": hashlib.sha256(
                _canonical_json_bytes(result_mappings)
            ).hexdigest(),
            "schema_version": 1,
        }
    )


def _load_checkpoint(
    data: bytes, backend: object
) -> tuple[OverlayResult, ...]:
    checkpoint = _parse_canonical_json(data, "overlay checkpoint")
    if set(checkpoint) != {
        "bindings", "complete", "results", "results_sha256", "schema_version"
    }:
        raise ValueError("overlay checkpoint schema is invalid")
    if checkpoint["schema_version"] != 1:
        raise ValueError("overlay checkpoint schema version is invalid")
    if checkpoint["bindings"] != _checkpoint_bindings(backend):
        raise ValueError("overlay checkpoint parent, policy, or runtime is stale")
    raw_results = checkpoint["results"]
    if not isinstance(raw_results, list):
        raise ValueError("overlay checkpoint results are invalid")
    if checkpoint["results_sha256"] != hashlib.sha256(
        _canonical_json_bytes(raw_results)
    ).hexdigest():
        raise ValueError("overlay checkpoint result content SHA-256 is invalid")
    results = tuple(_result_from_mapping(item) for item in raw_results)
    canonical_targets = overlay_targets()
    if tuple(result.target for result in results) != canonical_targets[: len(results)]:
        raise ValueError("overlay checkpoint results are not a canonical prefix")
    if checkpoint["complete"] is not (len(results) == len(canonical_targets)):
        raise ValueError("overlay checkpoint completeness flag is invalid")
    if results:
        validate_results(results, expected_targets=canonical_targets[: len(results)])
    return results


def _catalog_bytes(results: tuple[OverlayResult, ...]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=OUTPUT_COLUMNS,
        lineterminator="\n",
        extrasaction="raise",
    )
    writer.writeheader()
    for result in results:
        target = result.target
        spin_numerator, spin_denominator = target.spin.as_integer_ratio()
        writer.writerow(
            {
                "s": -2,
                "ell": target.ell,
                "m": target.m,
                "n": target.n,
                "branch_id": "schwarzschild-overtone-continuation",
                "source_coordinate_id": target.source_coordinate_id,
                "source_coordinate_numerator": target.source_coordinate.numerator,
                "source_coordinate_denominator": target.source_coordinate.denominator,
                "source_transformation_id": target.source_transformation_id,
                "spin_numerator": spin_numerator,
                "spin_denominator": spin_denominator,
                "spin_float": repr(target.spin),
                "spin_binary64_hex": target.spin_hex,
                "omega_re_M": repr(result.omega.real),
                "omega_im_M": repr(result.omega.imag),
                "angular_A_re": repr(result.angular_a.real),
                "angular_A_im": repr(result.angular_a.imag),
                "root_solver_success": "true",
                "optimizer_residual_abs": repr(result.optimizer_residual_abs),
                "continued_fraction_error": repr(result.continued_fraction_error),
                "continued_fraction_terms": result.continued_fraction_terms,
                "angular_padding": 20,
                "angular_refinement_padding": 24,
                "angular_refinement_abs": repr(result.angular_refinement_abs),
                "repeat_polish_delta_abs": repr(result.repeat_polish_delta_abs),
                "predictor_correction_abs": repr(result.predictor_correction_abs),
                "predictor_correction_over_separation": repr(
                    result.predictor_correction_over_separation
                ),
                "assigned_separation_abs": repr(result.assigned_separation_abs),
                "assignment_relative_gap": repr(result.assignment_relative_gap),
                "canonical_polish_delta_abs": repr(
                    result.canonical_polish_delta_abs
                ),
                "independent_path_delta_abs": repr(
                    result.independent_path_delta_abs
                ),
                "reverse_delta_abs": repr(result.reverse_delta_abs),
                "angular_overlap_min": repr(result.angular_overlap_min),
                "schedule_a_steps": result.schedule_a_steps,
                "schedule_b_steps": result.schedule_b_steps,
                "minimum_adaptive_step": repr(result.minimum_adaptive_step),
            }
        )
    return output.getvalue().encode("utf-8")


def _receipt_bytes(
    results: tuple[OverlayResult, ...], catalog_bytes: bytes, backend: object
) -> bytes:
    maxima_fields = (
        "optimizer_residual_abs", "continued_fraction_error",
        "angular_refinement_abs", "repeat_polish_delta_abs",
        "predictor_correction_abs", "predictor_correction_over_separation",
        "canonical_polish_delta_abs", "independent_path_delta_abs",
        "reverse_delta_abs",
    )
    minima_fields = (
        "assigned_separation_abs", "assignment_relative_gap",
        "angular_overlap_min", "minimum_adaptive_step",
    )
    return _canonical_json_bytes(
        {
            "backend": _backend_identity(backend),
            "evidence_ceiling": (
                "numerical continuation and genealogy evidence only; no formal "
                "root enclosure, external comparator, or DM/ZDM classification"
            ),
            "generator": {
                "path": "tools/compute_kerr_qnm_overlay.py",
                "sha256": _generator_sha256(),
            },
            "overlay": {
                "columns": list(OUTPUT_COLUMNS),
                "line_endings": "LF",
                "ordering": ["ell", "m", "n", "spin_binary64"],
                "row_count_excluding_header": len(results),
                "sha256": hashlib.sha256(catalog_bytes).hexdigest(),
                "target_set_sha256": _target_set_sha256(),
            },
            "parents": {
                "base_catalog_sha256": BASE_CATALOG_SHA256,
                "base_receipt_sha256": BASE_RECEIPT_SHA256,
                "base_root_count": 2736,
                "base_independent_comparison_count": 392,
            },
            "policy": dict(OVERLAY_POLICY),
            "policy_sha256": POLICY_SHA256,
            "runtime": _runtime_identity(),
            "schema_version": 1,
            "validation": {
                "damped_count": len(results),
                "failure_count": 0,
                "finite_count": len(results),
                "observed_maxima": {
                    field: max(getattr(result, field) for result in results)
                    for field in maxima_fields
                },
                "observed_minima": {
                    field: min(getattr(result, field) for result in results)
                    for field in minima_fields
                },
                "scientific_state": "NOT_EVALUATED",
            },
        }
    )


def build_overlay(
    base_catalog_bytes: bytes,
    base_receipt_bytes: bytes,
    *,
    backend: object,
    workers: int = 1,
    checkpoint_bytes: bytes | None = None,
    checkpoint_callback: Callable[[bytes], None] | None = None,
) -> OverlayBuild:
    """Build complete deterministic bytes after authenticating both parents."""

    base_roots = _authenticate_base_inputs(base_catalog_bytes, base_receipt_bytes)
    if isinstance(workers, bool) or workers < 1:
        raise ValueError("workers must be a positive integer")
    completed = (
        _load_checkpoint(checkpoint_bytes, backend)
        if checkpoint_bytes is not None
        else ()
    )
    targets = overlay_targets()
    completed_keys = {result.target.selection_key for result in completed}
    groups: list[tuple[OverlayTarget, ...]] = []
    for cohort in sorted({(target.ell, target.m) for target in targets}):
        group = tuple(
            target
            for target in targets
            if (target.ell, target.m) == cohort
            and target.selection_key not in completed_keys
        )
        if group:
            if any(
                target.selection_key in completed_keys
                for target in targets
                if (target.ell, target.m) == cohort
            ):
                raise ValueError("overlay checkpoint splits a continuation cohort")
            groups.append(group)

    def solve(group: tuple[OverlayTarget, ...]) -> tuple[OverlayResult, ...]:
        values = backend.solve_cohort(group, base_roots, OVERLAY_POLICY)
        return tuple(values)

    if workers == 1:
        solved_iterator = map(solve, groups)
        executor = None
    else:
        executor = ThreadPoolExecutor(max_workers=workers)
        solved_iterator = executor.map(solve, groups)
    solved_groups: list[tuple[OverlayResult, ...]] = []
    try:
        for group, solved_group in zip(groups, solved_iterator):
            validate_results(solved_group, expected_targets=group)
            solved_groups.append(solved_group)
            if checkpoint_callback is not None:
                checkpoint_callback(
                    _checkpoint_bytes(
                        tuple(
                            sorted(
                                (
                                    *completed,
                                    *(item for solved in solved_groups for item in solved),
                                ),
                                key=lambda result: result.target.order_key,
                            )
                        ),
                        backend,
                    )
                )
    finally:
        if executor is not None:
            executor.shutdown(wait=True)
    results_by_key = {
        result.target.selection_key: result
        for result in (*completed, *(item for group in solved_groups for item in group))
    }
    results = tuple(results_by_key[target.selection_key] for target in targets)
    validate_results(results)
    final_checkpoint = _checkpoint_bytes(results, backend)
    if checkpoint_callback is not None and not groups:
        checkpoint_callback(final_checkpoint)
    catalog = _catalog_bytes(results)
    receipt = _receipt_bytes(results, catalog, backend)
    return OverlayBuild(catalog, receipt, final_checkpoint)


def _x_coordinate(spin: float) -> float:
    return -0.5 * math.log((1.0 - spin) * (1.0 + spin))


def _spin_from_x(value: float) -> float:
    return math.sqrt(-math.expm1(-2.0 * value))


def _surface_gravity_from_spin(spin: float) -> float:
    horizon_gap = math.sqrt((1.0 - spin) * (1.0 + spin))
    return horizon_gap / (2.0 * (1.0 + horizon_gap))


def _y_coordinate(spin: float) -> float:
    return -math.log(_surface_gravity_from_spin(spin))


def _spin_from_y(value: float) -> float:
    coordinate = math.exp(-value)
    horizon_gap = 2.0 * coordinate / (1.0 - 2.0 * coordinate)
    return math.sqrt(1.0 - horizon_gap * horizon_gap)


def _updated_minimum_adaptive_step(
    *, previous: float, planned_step: float, accepted_step: float
) -> float:
    """Record ambiguity-driven halving, not a successful exact-node remainder."""

    if accepted_step < planned_step * (1.0 - 1e-12):
        return min(previous, accepted_step)
    return previous


class CanonicalOverlayBackend:
    """Canonical coupled angular/Leaver cohort continuation backend."""

    @property
    def identity(self) -> Mapping[str, object]:
        return {
            "backend_id": "canonical-coupled-leaver-cohort-continuation",
            "canonical_angular": {
                "migrated_source_blob": kerr_angular.SOURCE_BLOB_SHA,
                "module_sha256": hashlib.sha256(
                    Path(kerr_angular.__file__).read_bytes()
                ).hexdigest(),
            },
            "canonical_continued_fraction": {
                "migrated_source_blob": kerr_cf_solver.SOURCE_BLOB_SHA,
                "module_sha256": hashlib.sha256(
                    Path(kerr_cf_solver.__file__).read_bytes()
                ).hexdigest(),
                "minimum_terms": (
                    kerr_cf_solver.CONTINUED_FRACTION_MINIMUM_TERMS
                ),
                "maximum_terms": (
                    kerr_cf_solver.CONTINUED_FRACTION_MAXIMUM_TERMS
                ),
                "tolerance": kerr_cf_solver.CONTINUED_FRACTION_TOLERANCE,
            },
            "candidate_bank": "all-cohort-predictors-cross-all-cohort-inversions",
            "version": 1,
        }

    @staticmethod
    def _angular_vector(
        spin: float, ell: int, m: int, omega: complex
    ) -> tuple[complex, tuple[complex, ...]]:
        angular_a, vector, _ = kerr_angular.eigenpair(
            -2, spin * omega, m, ell, ell + 20
        )
        return complex(angular_a), tuple(complex(item) for item in vector)

    @staticmethod
    def _parent_node(
        targets: tuple[OverlayTarget, ...],
        base_roots: tuple[BaseRoot, ...],
        overtones: tuple[int, ...],
        coordinate: Callable[[float], float],
    ) -> _ContinuationNode:
        ell, m = targets[0].ell, targets[0].m
        minimum_target = min(target.spin for target in targets)
        common_spins = set.intersection(
            *(
                {
                    root.spin
                    for root in base_roots
                    if (root.ell, root.m, root.n) == (ell, m, n)
                    and root.spin < minimum_target
                }
                for n in overtones
            )
        )
        if not common_spins:
            raise ValueError("authenticated base has no common cohort parent")
        parent_spin = max(common_spins)
        roots: dict[int, CandidateRoot] = {}
        for n in overtones:
            parent = next(
                root
                for root in base_roots
                if (root.ell, root.m, root.n, root.spin)
                == (ell, m, n, parent_spin)
            )
            angular_a, angular_vector = CanonicalOverlayBackend._angular_vector(
                parent_spin, ell, m, parent.omega
            )
            if abs(angular_a - parent.angular_a) > 1e-9:
                raise ValueError("authenticated parent angular eigenpair is inconsistent")
            roots[n] = CandidateRoot(
                omega=parent.omega,
                angular_a=angular_a,
                angular_vector=angular_vector,
                optimizer_residual_abs=parent.optimizer_residual_abs,
            )
        return _ContinuationNode(coordinate(parent_spin), parent_spin, roots)

    @staticmethod
    def _predictions(
        histories: Mapping[int, list[tuple[float, CandidateRoot]]],
        next_coordinate: float,
    ) -> tuple[BranchPrediction, ...]:
        predictions: list[BranchPrediction] = []
        for n in sorted(histories):
            history = histories[n]
            if len(history) == 1:
                predicted = history[-1][1].omega
            else:
                previous_coordinate, previous = history[-2]
                current_coordinate, current = history[-1]
                predicted = current.omega + (
                    (current.omega - previous.omega)
                    * (next_coordinate - current_coordinate)
                    / (current_coordinate - previous_coordinate)
                )
            predictions.append(
                BranchPrediction(
                    n=n,
                    omega=predicted,
                    angular_vector=history[-1][1].angular_vector,
                )
            )
        return tuple(predictions)

    @staticmethod
    def _candidate_bank(
        spin: float,
        ell: int,
        m: int,
        overtones: tuple[int, ...],
        predictions: tuple[BranchPrediction, ...],
    ) -> tuple[CandidateRoot, ...]:
        candidates: list[CandidateRoot] = []
        for prediction in predictions:
            for inversion in overtones:
                solved = kerr_cf_solver.solve_mode(
                    spin,
                    -2,
                    ell,
                    m,
                    inversion,
                    prediction.omega,
                    angular_padding=20,
                    tolerance=1e-10,
                )
                omega, angular_a, residual, cf_error, terms, success, _ = solved
                if (
                    not success
                    or not all(
                        math.isfinite(value)
                        for value in (
                            omega.real, omega.imag, angular_a.real,
                            angular_a.imag, residual, cf_error,
                        )
                    )
                    or omega.imag >= 0.0
                    or residual > MAXIMUM_OPTIMIZER_RESIDUAL_ABS
                    or cf_error > MAXIMUM_CONTINUED_FRACTION_ERROR
                ):
                    continue
                eigenvalue, vector = CanonicalOverlayBackend._angular_vector(
                    spin, ell, m, omega
                )
                if abs(eigenvalue - angular_a) > 1e-9:
                    continue
                candidates.append(
                    CandidateRoot(
                        omega=omega,
                        angular_a=complex(angular_a),
                        angular_vector=vector,
                        optimizer_residual_abs=float(residual),
                        continued_fraction_error=float(cf_error),
                        continued_fraction_terms=int(terms),
                        solver_success=bool(success),
                    )
                )
        return tuple(candidates)

    @classmethod
    def _advance_node(
        cls,
        node: _ContinuationNode,
        histories: Mapping[int, list[tuple[float, CandidateRoot]]],
        next_coordinate: float,
        inverse_coordinate: Callable[[float], float],
        ell: int,
        m: int,
        overtones: tuple[int, ...],
        exact_spin: float | None,
    ) -> tuple[_ContinuationNode, CohortAssignment]:
        spin = exact_spin if exact_spin is not None else inverse_coordinate(next_coordinate)
        predictions = cls._predictions(histories, next_coordinate)
        candidates = cls._candidate_bank(spin, ell, m, overtones, predictions)
        assignment = assign_candidate_clusters(predictions, candidates)
        roots = {
            assigned.prediction.n: assigned.candidate
            for assigned in assignment.assigned
        }
        return _ContinuationNode(next_coordinate, spin, roots), assignment

    @classmethod
    def _run_path(
        cls,
        start: _ContinuationNode,
        target_spins: tuple[float, ...],
        *,
        ell: int,
        m: int,
        overtones: tuple[int, ...],
        coordinate: Callable[[float], float],
        inverse_coordinate: Callable[[float], float],
        step_maximum: float,
    ) -> dict[str, _PathTarget]:
        histories: dict[int, list[tuple[float, CandidateRoot]]] = {
            n: [(start.coordinate, start.roots[n])] for n in overtones
        }
        current = start
        correction_max = {n: 0.0 for n in overtones}
        ratio_max = {n: 0.0 for n in overtones}
        separation_min = {n: math.inf for n in overtones}
        overlap_min = {n: 1.0 for n in overtones}
        assignment_gap_min = math.inf
        minimum_step = step_maximum
        steps = 0
        targets_by_coordinate = {
            coordinate(spin): spin for spin in target_spins
        }
        ordered_target_coordinates = sorted(
            targets_by_coordinate,
            reverse=(coordinate(target_spins[-1]) < start.coordinate),
        )
        captured: dict[str, _PathTarget] = {}
        for exact_coordinate in ordered_target_coordinates:
            target_spin = targets_by_coordinate[exact_coordinate]
            direction = 1.0 if exact_coordinate > current.coordinate else -1.0
            while direction * (exact_coordinate - current.coordinate) > 0.0:
                remaining = abs(exact_coordinate - current.coordinate)
                nominal = min(step_maximum, remaining)
                planned_coordinate = current.coordinate + direction * nominal
                planned_exact_spin = (
                    target_spin if planned_coordinate == exact_coordinate else None
                )

                def attempt(step_start: float, step_stop: float):
                    del step_start
                    return cls._advance_node(
                        current,
                        histories,
                        step_stop,
                        inverse_coordinate,
                        ell,
                        m,
                        overtones,
                        (
                            planned_exact_spin
                            if step_stop == exact_coordinate
                            else None
                        ),
                    )

                next_node, assignment = adaptive_advance(
                    current.coordinate,
                    planned_coordinate,
                    attempt,
                    minimum_step=MINIMUM_ADAPTIVE_STEP,
                )
                accepted_step = abs(next_node.coordinate - current.coordinate)
                minimum_step = _updated_minimum_adaptive_step(
                    previous=minimum_step,
                    planned_step=nominal,
                    accepted_step=accepted_step,
                )
                steps += 1
                current = next_node
                for assigned in assignment.assigned:
                    n = assigned.prediction.n
                    histories[n].append((current.coordinate, current.roots[n]))
                    correction_max[n] = max(
                        correction_max[n], assigned.predictor_correction_abs
                    )
                    ratio_max[n] = max(
                        ratio_max[n], assigned.correction_over_separation
                    )
                    separation_min[n] = min(
                        separation_min[n], assigned.assigned_separation_abs
                    )
                    overlap_min[n] = min(overlap_min[n], assigned.angular_overlap)
                assignment_gap_min = min(
                    assignment_gap_min, assignment.relative_gap
                )
            captured[target_spin.hex()] = _PathTarget(
                node=current,
                predictor_correction_abs=dict(correction_max),
                correction_over_separation=dict(ratio_max),
                assigned_separation_abs=dict(separation_min),
                assignment_relative_gap=assignment_gap_min,
                angular_overlap=dict(overlap_min),
                steps=steps,
                minimum_step=minimum_step,
            )
        return captured

    @staticmethod
    def _polish(
        spin: float,
        ell: int,
        m: int,
        n: int,
        assigned: CandidateRoot,
    ) -> _PolishedRoot:
        polished = kerr_cf_solver.solve_mode(
            spin,
            -2,
            ell,
            m,
            n,
            assigned.omega,
            angular_padding=20,
            tolerance=1e-10,
        )
        omega, angular_a, residual, cf_error, terms, success, _ = polished
        if not success:
            raise ValueError("canonical exact-target polish failed")
        repeat = kerr_cf_solver.solve_mode(
            spin,
            -2,
            ell,
            m,
            n,
            omega,
            angular_padding=20,
            tolerance=1e-12,
        )
        if not repeat[5]:
            raise ValueError("canonical repeat polish failed")
        canonical_value, _, canonical_cf_error, canonical_terms = (
            kerr_cf_solver.coupled_error(
                omega, spin, -2, ell, m, n, 20
            )
        )
        refined_value, refined_a, refined_cf_error, refined_terms = (
            kerr_cf_solver.coupled_error(
                omega, spin, -2, ell, m, n, 24
            )
        )
        cf_evidence = max(
            float(cf_error),
            float(canonical_cf_error),
            float(refined_cf_error),
            abs(refined_value - canonical_value),
        )
        return _PolishedRoot(
            omega=complex(omega),
            angular_a=complex(angular_a),
            optimizer_residual_abs=max(float(residual), abs(canonical_value)),
            continued_fraction_error=cf_evidence,
            continued_fraction_terms=max(
                int(terms), int(canonical_terms), int(refined_terms)
            ),
            angular_refinement_abs=abs(refined_a - angular_a),
            repeat_polish_delta_abs=abs(repeat[0] - omega),
            canonical_polish_delta_abs=abs(omega - assigned.omega),
        )

    @classmethod
    def solve_cohort(
        cls,
        targets: tuple[OverlayTarget, ...],
        base_roots: tuple[BaseRoot, ...],
        policy: Mapping[str, object],
    ) -> tuple[OverlayResult, ...]:
        if policy != OVERLAY_POLICY or not targets:
            raise ValueError("canonical overlay policy or cohort is invalid")
        ell, m = targets[0].ell, targets[0].m
        if any((target.ell, target.m) != (ell, m) for target in targets):
            raise ValueError("overlay backend received a mixed cohort")
        output_overtones = tuple(sorted({target.n for target in targets}))
        support_maximum = max(1, max(output_overtones))
        overtones = tuple(range(support_maximum + 1))
        unique_spins = tuple(sorted({target.spin for target in targets}))

        parent_a = cls._parent_node(targets, base_roots, overtones, _x_coordinate)
        path_a = cls._run_path(
            parent_a,
            unique_spins,
            ell=ell,
            m=m,
            overtones=overtones,
            coordinate=_x_coordinate,
            inverse_coordinate=_spin_from_x,
            step_maximum=float(
                policy["schedule_a_step_maximum_by_ell"][str(ell)]
            ),
        )
        parent_b = cls._parent_node(targets, base_roots, overtones, _y_coordinate)
        path_b = cls._run_path(
            parent_b,
            unique_spins,
            ell=ell,
            m=m,
            overtones=overtones,
            coordinate=_y_coordinate,
            inverse_coordinate=_spin_from_y,
            step_maximum=float(
                policy["schedule_b_step_maximum_by_ell"][str(ell)]
            ),
        )

        polished_a: dict[tuple[int, str], _PolishedRoot] = {}
        polished_b: dict[tuple[int, str], _PolishedRoot] = {}
        reverse_delta: dict[tuple[int, str], float] = {}
        for spin in unique_spins:
            spin_hex = spin.hex()
            for n in overtones:
                polished_a[n, spin_hex] = cls._polish(
                    spin, ell, m, n, path_a[spin_hex].node.roots[n]
                )
                polished_b[n, spin_hex] = cls._polish(
                    spin, ell, m, n, path_b[spin_hex].node.roots[n]
                )
            reverse_start = _ContinuationNode(
                _x_coordinate(spin),
                spin,
                {
                    n: CandidateRoot(
                        omega=polished_a[n, spin_hex].omega,
                        angular_a=polished_a[n, spin_hex].angular_a,
                        angular_vector=cls._angular_vector(
                            spin, ell, m, polished_a[n, spin_hex].omega
                        )[1],
                        optimizer_residual_abs=(
                            polished_a[n, spin_hex].optimizer_residual_abs
                        ),
                        continued_fraction_error=(
                            polished_a[n, spin_hex].continued_fraction_error
                        ),
                        continued_fraction_terms=(
                            polished_a[n, spin_hex].continued_fraction_terms
                        ),
                    )
                    for n in overtones
                },
            )
            reverse = cls._run_path(
                reverse_start,
                (parent_a.spin,),
                ell=ell,
                m=m,
                overtones=overtones,
                coordinate=_x_coordinate,
                inverse_coordinate=_spin_from_x,
                step_maximum=float(
                    policy["schedule_a_step_maximum_by_ell"][str(ell)]
                ),
            )[parent_a.spin.hex()]
            for n in overtones:
                reverse_delta[n, spin_hex] = abs(
                    reverse.node.roots[n].omega - parent_a.roots[n].omega
                )

        results: list[OverlayResult] = []
        for target in targets:
            key = target.n, target.spin_hex
            a = path_a[target.spin_hex]
            b = path_b[target.spin_hex]
            canonical = polished_a[key]
            independent = polished_b[key]
            results.append(
                OverlayResult(
                    target=target,
                    omega=canonical.omega,
                    angular_a=canonical.angular_a,
                    optimizer_residual_abs=canonical.optimizer_residual_abs,
                    continued_fraction_error=canonical.continued_fraction_error,
                    continued_fraction_terms=canonical.continued_fraction_terms,
                    angular_refinement_abs=canonical.angular_refinement_abs,
                    repeat_polish_delta_abs=canonical.repeat_polish_delta_abs,
                    predictor_correction_abs=max(
                        a.predictor_correction_abs[target.n],
                        b.predictor_correction_abs[target.n],
                    ),
                    predictor_correction_over_separation=max(
                        a.correction_over_separation[target.n],
                        b.correction_over_separation[target.n],
                    ),
                    assigned_separation_abs=min(
                        a.assigned_separation_abs[target.n],
                        b.assigned_separation_abs[target.n],
                    ),
                    assignment_relative_gap=min(
                        a.assignment_relative_gap, b.assignment_relative_gap
                    ),
                    canonical_polish_delta_abs=(
                        canonical.canonical_polish_delta_abs
                    ),
                    independent_path_delta_abs=abs(
                        canonical.omega - independent.omega
                    ),
                    reverse_delta_abs=reverse_delta[key],
                    angular_overlap_min=min(
                        a.angular_overlap[target.n],
                        b.angular_overlap[target.n],
                    ),
                    schedule_a_steps=a.steps,
                    schedule_b_steps=b.steps,
                    minimum_adaptive_step=min(a.minimum_step, b.minimum_step),
                )
            )
        return tuple(results)


def _write_temporary(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def _atomic_write(path: Path, data: bytes) -> None:
    temporary = _write_temporary(path, data)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_write_pair(
    catalog_path: Path,
    receipt_path: Path,
    catalog_bytes: bytes,
    receipt_bytes: bytes,
) -> None:
    if catalog_path.resolve() == receipt_path.resolve():
        raise ValueError("overlay catalog and receipt outputs must differ")
    old_catalog = catalog_path.read_bytes() if catalog_path.is_file() else None
    catalog_temporary = _write_temporary(catalog_path, catalog_bytes)
    receipt_temporary = _write_temporary(receipt_path, receipt_bytes)
    try:
        os.replace(catalog_temporary, catalog_path)
        try:
            os.replace(receipt_temporary, receipt_path)
        except BaseException:
            if old_catalog is None:
                catalog_path.unlink(missing_ok=True)
            else:
                _atomic_write(catalog_path, old_catalog)
            raise
    finally:
        catalog_temporary.unlink(missing_ok=True)
        receipt_temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compute the authenticated sparse 44-root M02 overlay."
    )
    parser.add_argument("--base-catalog", type=Path, required=True)
    parser.add_argument("--base-receipt", type=Path, required=True)
    parser.add_argument("--output-catalog", type=Path, required=True)
    parser.add_argument("--output-receipt", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--workers", type=int, default=1)
    arguments = parser.parse_args(argv)

    checkpoint_data = (
        arguments.checkpoint.read_bytes()
        if arguments.checkpoint is not None and arguments.checkpoint.is_file()
        else None
    )

    def persist_checkpoint(data: bytes) -> None:
        if arguments.checkpoint is not None:
            _atomic_write(arguments.checkpoint, data)

    build = build_overlay(
        arguments.base_catalog.read_bytes(),
        arguments.base_receipt.read_bytes(),
        backend=CanonicalOverlayBackend(),
        workers=arguments.workers,
        checkpoint_bytes=checkpoint_data,
        checkpoint_callback=persist_checkpoint,
    )
    _atomic_write_pair(
        arguments.output_catalog,
        arguments.output_receipt,
        build.catalog_bytes,
        build.receipt_bytes,
    )
    print(
        json.dumps(
            {
                "catalog_sha256": hashlib.sha256(build.catalog_bytes).hexdigest(),
                "receipt_sha256": hashlib.sha256(build.receipt_bytes).hexdigest(),
                "row_count": 44,
            },
            sort_keys=True,
        )
    )
    return 0


class GenealogyError(ValueError):
    """A continuation step cannot prove a unique, continuous branch assignment."""


@dataclass(frozen=True, slots=True)
class BranchPrediction:
    n: int
    omega: complex
    angular_vector: tuple[complex, ...]


@dataclass(frozen=True, slots=True)
class CandidateRoot:
    omega: complex
    angular_a: complex
    angular_vector: tuple[complex, ...]
    optimizer_residual_abs: float = 0.0
    continued_fraction_error: float = 0.0
    continued_fraction_terms: int = 1000
    solver_success: bool = True


@dataclass(frozen=True, slots=True)
class AssignedRoot:
    prediction: BranchPrediction
    candidate: CandidateRoot
    predictor_correction_abs: float
    correction_over_separation: float
    assigned_separation_abs: float
    angular_overlap: float


@dataclass(frozen=True, slots=True)
class CohortAssignment:
    assigned: tuple[AssignedRoot, ...]
    relative_gap: float


def _angular_overlap(
    left: tuple[complex, ...], right: tuple[complex, ...]
) -> float:
    if len(left) != len(right) or not left:
        raise GenealogyError("angular vectors have incompatible dimensions")
    left_norm = math.sqrt(sum(abs(item) ** 2 for item in left))
    right_norm = math.sqrt(sum(abs(item) ** 2 for item in right))
    if left_norm == 0.0 or right_norm == 0.0:
        raise GenealogyError("angular vector has zero norm")
    inner = sum(a.conjugate() * b for a, b in zip(left, right))
    return min(1.0, float(abs(inner) / (left_norm * right_norm)))


def _cluster_candidates(
    candidates: tuple[CandidateRoot, ...], *, tolerance: float = 1e-7
) -> tuple[CandidateRoot, ...]:
    clusters: list[list[CandidateRoot]] = []
    for candidate in sorted(
        candidates, key=lambda item: (item.omega.real, item.omega.imag)
    ):
        for cluster in clusters:
            if abs(candidate.omega - cluster[0].omega) <= tolerance:
                cluster.append(candidate)
                break
        else:
            clusters.append([candidate])
    return tuple(
        min(
            cluster,
            key=lambda item: (
                item.optimizer_residual_abs,
                item.continued_fraction_error,
                item.omega.real,
                item.omega.imag,
            ),
        )
        for cluster in clusters
    )


def assign_candidate_clusters(
    predictions: tuple[BranchPrediction, ...],
    candidates: tuple[CandidateRoot, ...],
) -> CohortAssignment:
    """Assign independently clustered candidate roots to a labelled cohort."""

    if not predictions:
        raise GenealogyError("branch assignment requires predictions")
    clusters = _cluster_candidates(candidates)
    if len(clusters) < len(predictions):
        raise GenealogyError("candidate bank has too few distinct root clusters")

    separations: dict[CandidateRoot, float] = {}
    for candidate in clusters:
        separation = min(
            (
                abs(candidate.omega - other.omega)
                for other in clusters
                if other is not candidate
            ),
            default=math.inf,
        )
        if separation < 1e-6:
            raise GenealogyError("assigned root separation is below 1e-6")
        separations[candidate] = separation

    ranked: list[
        tuple[float, tuple[CandidateRoot, ...], tuple[float, ...]]
    ] = []
    for chosen in itertools.permutations(clusters, len(predictions)):
        overlaps = tuple(
            _angular_overlap(prediction.angular_vector, candidate.angular_vector)
            for prediction, candidate in zip(predictions, chosen)
        )
        cost = sum(
            (
                abs(candidate.omega - prediction.omega)
                / separations[candidate]
                + (1.0 - overlap)
            )
            for prediction, candidate, overlap in zip(
                predictions, chosen, overlaps
            )
        )
        ranked.append((cost, chosen, overlaps))
    ranked.sort(
        key=lambda item: (
            item[0],
            tuple((root.omega.real, root.omega.imag) for root in item[1]),
        )
    )
    best_cost, chosen, overlaps = ranked[0]
    second_cost = ranked[1][0] if len(ranked) > 1 else math.inf
    relative_gap = (
        math.inf
        if math.isinf(second_cost)
        else (second_cost - best_cost) / max(best_cost, 1e-30)
    )
    if relative_gap < 0.05:
        raise GenealogyError("branch assignment gap is ambiguous")

    assigned: list[AssignedRoot] = []
    for prediction, candidate, overlap in zip(predictions, chosen, overlaps):
        separation = separations[candidate]
        correction = abs(candidate.omega - prediction.omega)
        ratio = 0.0 if math.isinf(separation) else correction / separation
        if ratio > 0.24:
            raise GenealogyError(
                "predictor correction exceeds 0.24 of local separation"
            )
        assigned.append(
            AssignedRoot(
                prediction=prediction,
                candidate=candidate,
                predictor_correction_abs=correction,
                correction_over_separation=ratio,
                assigned_separation_abs=separation,
                angular_overlap=overlap,
            )
        )
    return CohortAssignment(tuple(assigned), relative_gap)


def adaptive_advance(
    start: float,
    stop: float,
    attempt,
    *,
    minimum_step: float = 0.003,
):
    """Retry one continuation step with deterministic bisection or fail closed."""

    step = stop - start
    if step == 0.0:
        return attempt(start, stop)
    while True:
        try:
            return attempt(start, start + step)
        except GenealogyError as error:
            next_step = step / 2.0
            if abs(next_step) < minimum_step:
                raise ValueError(
                    "continuation fail-closed below the minimum adaptive step"
                ) from error
            step = next_step


if __name__ == "__main__":  # pragma: no cover - CLI boundary
    raise SystemExit(main())
