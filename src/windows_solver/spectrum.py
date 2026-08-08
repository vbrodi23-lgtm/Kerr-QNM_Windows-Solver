"""Authenticated exact-selection access to the computed Kerr QNM lattice."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
import hashlib
from importlib import resources
import io
import json
import math
import platform
import re
from types import MappingProxyType
from typing import Mapping

from .contracts import (
    Capability,
    CarrierState,
    EvidenceState,
    ExecutionState,
    ModeKey,
    NumericalState,
    ScientificState,
    StudyRequest,
    canonical_json_bytes,
)
from .providers import ProviderDescriptor, ProviderResult


CATALOG_ID = "pure-kerr-qnm-lattice-2736"
CATALOG_RESOURCE = resources.files("windows_solver").joinpath(
    "data", "kerr_qnm_roots_2736.csv"
)
CATALOG_DATA_SHA256 = (
    "9ebae4271309cd45a1b26c90d31155602ed8ef33bb79069adb5897e8afe7a564"
)
CATALOG_RECEIPT_RESOURCE = resources.files("windows_solver").joinpath(
    "data", "kerr_qnm_lattice_receipt.json"
)
CATALOG_RECEIPT_SHA256 = (
    "61a428a858de1eb7e42fe4cbbda37bf1fddcc808d98be2a62fd33ef4b5b74379"
)
OVERLAY_ID = "m02-b-prime-sparse-overlay-44"
OVERLAY_RESOURCE = resources.files("windows_solver").joinpath(
    "data", "kerr_qnm_m02_overlay_44.csv"
)
OVERLAY_DATA_SHA256 = (
    "c4c61a1b73e850d537dba5f5eb947af100449aa2a1958a1ec8ea086f60ffe8e8"
)
OVERLAY_RECEIPT_RESOURCE = resources.files("windows_solver").joinpath(
    "data", "kerr_qnm_m02_overlay_receipt.json"
)
OVERLAY_RECEIPT_SHA256 = (
    "93a2e7586878d9c84e32d19ed9e7ad44d03572a91640625c44501bfbc46a5525"
)

PUBLIC_THEORY_ID = "general-relativity"
PUBLIC_CONVENTION_ID = "kerr-mass-normalized-outgoing"
PUBLIC_BRANCH_ID = "schwarzschild-overtone-continuation"
PUBLIC_POLARIZATION_ID = "gravitational"

SPECTRAL_PROVIDER_ID = "kerr-qnm-computed-lattice-2736"
SPECTRAL_PROVIDER_IMPLEMENTATION_VERSION = "3"
SPECTRAL_EQUATIONS_ID = "teukolsky-leaver-coupled-angular-radial-cf"
SPECTRAL_OUTPUT_ARTIFACT_TYPE = "kerr-qnm-spectrum"
SPECTRAL_EVIDENCE_LEVEL = "full-lattice-numerically-accepted"

MAXIMUM_OPTIMIZER_RESIDUAL_ABS = 1.0e-8
MAXIMUM_CONTINUED_FRACTION_ERROR = 1.0e-9
MAXIMUM_ANGULAR_REFINEMENT_ABS = 1.0e-9
MAXIMUM_REPEAT_POLISH_DELTA_ABS = 1.0e-9
MAXIMUM_BRANCH_SEED_DELTA_ABS = 5.0e-9
MAXIMUM_BRANCH_SEED_OPTIMIZER_RESIDUAL_ABS = 1.0e-8
MAXIMUM_REFERENCE_DELTA_OMEGA_M = 5.0e-9
MAXIMUM_REFERENCE_DELTA_A = 1.0e-8
MINIMUM_OVERTONE_SEPARATION_ABS = 1.0e-6

SPECTRAL_POLICY_FINGERPRINT = (
    f"catalog-{CATALOG_DATA_SHA256}-receipt-{CATALOG_RECEIPT_SHA256}-"
    f"overlay-{OVERLAY_DATA_SHA256}-overlay-receipt-{OVERLAY_RECEIPT_SHA256}-"
    "residual-1e-8-cf-1e-9-angular-1e-9-repeat-1e-9-seed-5e-9"
)

_CATALOG_COLUMNS = (
    "s",
    "ell",
    "m",
    "n",
    "branch_id",
    "chi_grid_family",
    "chi_grid_index",
    "chi_numerator",
    "chi_denominator",
    "chi_float",
    "chi_float_hex",
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
    "branch_seed_delta_abs",
    "branch_seed_optimizer_residual_abs",
    "continuation_step_maximum",
    "nearest_overtone_separation_abs",
    "reference_member",
    "reference_row",
    "reference_abs_delta_omega_M",
    "reference_abs_delta_A",
)
_OVERLAY_COLUMNS = (
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
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_CANONICAL_SOURCE_COMMIT = "0c1e8a3d3bca6e608c34e111476a4f6dcb73e86e"
_CANONICAL_CF_SOURCE_BLOB = "ffb17a6be8e15da3bbce21f6c5f66420b251b077"
_CANONICAL_ANGULAR_SOURCE_BLOB = "5d7641b349c4a1e1428629593cb2c81c441279a7"
_QNM_WHEEL_SHA256 = (
    "63711c37ff4847c8cb59e6266da5baf81f88cc6ab728f40fc3fe39a3025f6252"
)
_MOTOHASHI_ARCHIVE_SHA256 = (
    "9a096cdcf873039baaac66fe0194f64c430df17125713a16d8f546129ef238fa"
)
_OVERLAY_GENERATOR_SHA256 = (
    "303f82877e4c557022a906f73b02d42ad44e2a3e1b821212183cbe8d8db1eacb"
)
_OVERLAY_TARGET_SET_SHA256 = (
    "e195928deccd6300b04fab28d60998511f0e788419c1832ee2cfbf28c83b7d90"
)
_OVERLAY_POLICY_SHA256 = (
    "5c62a1db00110ae3d3935f60d6e612acf1dae82fca52e2b6d81228e734824678"
)


def _spins_for_ell(ell: int) -> tuple[Fraction, ...]:
    if ell in (2, 3):
        base = {Fraction(19 * index, 780) for index in range(40)}
        high = {
            Fraction(97, 100),
            Fraction(49, 50),
            Fraction(99, 100),
            Fraction(199, 200),
            Fraction(997, 1000),
            Fraction(999, 1000),
        }
        return tuple(sorted(base | high))
    if ell == 4:
        return tuple(Fraction(index, 52) for index in range(40))
    raise ValueError(f"unsupported ell: {ell}")


def _expected_lattice_keys() -> tuple[tuple[int, int, int, int, int], ...]:
    return tuple(
        (ell, m, n, spin.numerator, spin.denominator)
        for ell in (2, 3, 4)
        for m in range(-ell, ell + 1)
        for n in range(3)
        for spin in _spins_for_ell(ell)
    )


_EXPECTED_LATTICE_KEYS = _expected_lattice_keys()
_EXPECTED_LATTICE_KEY_SET = frozenset(_EXPECTED_LATTICE_KEYS)


def _spin_from_surface_gravity(coordinate: Fraction) -> float:
    value = float(coordinate)
    horizon_gap = 2.0 * value / (1.0 - 2.0 * value)
    return math.sqrt(1.0 - horizon_gap * horizon_gap)


def _expected_overlay_targets() -> tuple[
    tuple[int, int, int, str, Fraction, str, float], ...
]:
    direct = (
        Fraction(19, 20), Fraction(97, 100), Fraction(49, 50),
        Fraction(99, 100), Fraction(199, 200), Fraction(997, 1000),
        Fraction(999, 1000), Fraction(1999, 2000), Fraction(9999, 10000),
    )
    targets: list[tuple[int, int, int, str, Fraction, str, float]] = []
    for ell, m, overtones, spins in (
        (2, 2, (0, 1, 2), direct[-2:]),
        (3, 3, (0, 1), direct[-2:]),
        (4, 4, (0, 1), direct),
    ):
        for n in overtones:
            for coordinate in spins:
                targets.append(
                    (
                        ell, m, n, "a-over-M", coordinate,
                        "identity-a-over-M", float(coordinate),
                    )
                )
    for ell, m, n in ((2, 2, 0), (2, 2, 1), (2, 2, 2), (2, 1, 0)):
        for coordinate in (
            Fraction(1, 100), Fraction(1, 200),
            Fraction(1, 500), Fraction(1, 1000),
        ):
            targets.append(
                (
                    ell, m, n, "M-kappa", coordinate,
                    "kerr-prograde-spin-from-dimensionless-surface-gravity",
                    _spin_from_surface_gravity(coordinate),
                )
            )
    return tuple(
        sorted(
            targets,
            key=lambda item: (*item[:3], item[6]),
        )
    )


_EXPECTED_OVERLAY_TARGETS = _expected_overlay_targets()


def _grid_identity(ell: int, spin: Fraction) -> tuple[str, int]:
    spins = _spins_for_ell(ell)
    try:
        index = spins.index(spin)
    except ValueError as error:
        raise ValueError("spin is outside the exact lattice") from error
    base = {Fraction(19 * item, 780) for item in range(40)}
    if ell in (2, 3) and spin not in base:
        return "ell23-supplemental-high", index
    return ("ell23-uniform-40" if ell in (2, 3) else "ell4-uniform-40", index)


def _reject_json_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate receipt JSON key: {key}")
        value[key] = item
    return value


def _reject_json_nonfinite(value: str) -> object:
    raise ValueError(f"non-finite receipt JSON number: {value}")


def _plain_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in value]
    return value


def _freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _parse_int(value: str, field: str, row_number: int) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise ValueError(
            f"catalog row {row_number} field {field} must be an integer"
        ) from error
    if str(parsed) != value:
        raise ValueError(
            f"catalog row {row_number} field {field} is not canonical"
        )
    return parsed


def _parse_float(value: str, field: str, row_number: int) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise ValueError(
            f"catalog row {row_number} field {field} must be numeric"
        ) from error
    if not math.isfinite(parsed):
        raise ValueError(
            f"catalog row {row_number} field {field} must be finite"
        )
    return parsed


def _parse_optional_float(value: str, field: str, row_number: int) -> float | None:
    if value == "":
        return None
    return _parse_float(value, field, row_number)


def _parse_optional_int(value: str, field: str, row_number: int) -> int | None:
    if value == "":
        return None
    return _parse_int(value, field, row_number)


def _read_canonical_json_resource(
    resource: object, *, expected_sha256: str, subject: str
) -> Mapping[str, object]:
    data = resource.read_bytes()  # type: ignore[attr-defined]
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError(f"{subject} SHA-256 does not match")
    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_reject_json_duplicate_keys,
            parse_constant=_reject_json_nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{subject} is not canonical JSON") from error
    if not isinstance(value, Mapping):
        raise ValueError(f"{subject} must be an object")
    if data != canonical_json_bytes(value) + b"\n":
        raise ValueError(f"{subject} is not canonical JSON")
    return value


def _mapping(value: object, subject: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{subject} must be an object")
    return value


@lru_cache(maxsize=1)
def load_catalog_receipt() -> Mapping[str, object]:
    value = _read_canonical_json_resource(
        CATALOG_RECEIPT_RESOURCE,
        expected_sha256=CATALOG_RECEIPT_SHA256,
        subject="lattice receipt",
    )
    if value.get("schema_version") != 1:
        raise ValueError("lattice receipt schema version is invalid")
    catalog = _mapping(value.get("catalog"), "receipt catalog")
    lattice = _mapping(value.get("lattice"), "receipt lattice")
    backend = _mapping(value.get("backend"), "receipt backend")
    policy = _mapping(value.get("numerical_policy"), "receipt numerical policy")
    validation = _mapping(value.get("validation"), "receipt validation")
    ceilings = _mapping(validation.get("ceilings"), "receipt ceilings")
    maxima = _mapping(validation.get("observed_maxima"), "receipt maxima")
    expected_scope = {
        "mode_count": 63,
        "root_count": 2736,
        "roots_by_ell": {"2": 690, "3": 966, "4": 1080},
        "spin_points_by_ell": {"2": 46, "3": 46, "4": 40},
        "spin_weight": -2,
    }
    if catalog.get("sha256") != CATALOG_DATA_SHA256:
        raise ValueError("lattice receipt does not bind the catalog")
    if (
        catalog.get("row_count_excluding_header") != 2736
        or catalog.get("columns") != list(_CATALOG_COLUMNS)
        or catalog.get("line_endings") != "LF"
    ):
        raise ValueError("lattice receipt row count is invalid")
    for key, expected in expected_scope.items():
        if lattice.get(key) != expected:
            raise ValueError(f"lattice receipt {key} is invalid")
    if lattice.get("ordering") != ["ell", "m", "n", "chi_exact"]:
        raise ValueError("lattice receipt ordering is invalid")
    if lattice.get("mode_rule") != {
        "ell": [2, 3, 4],
        "m": "every integer from -ell through +ell",
        "n": [0, 1, 2],
    }:
        raise ValueError("lattice receipt mode rule is invalid")
    expected_spins = {
        str(ell): [
            [spin.numerator, spin.denominator] for spin in _spins_for_ell(ell)
        ]
        for ell in (2, 3, 4)
    }
    if lattice.get("spin_grid_rationals_by_ell") != expected_spins:
        raise ValueError("lattice receipt exact spin grids are invalid")

    branch_tracker = _mapping(backend.get("branch_tracker"), "branch tracker")
    if branch_tracker != {
        "name": "qnm",
        "version": "0.4.4",
        "wheel_sha256": _QNM_WHEEL_SHA256,
        "role": "branch-labelled seed generation only",
        "angular_seed_role": (
            "not used; catalog A is recomputed by the canonical backend "
            "and compared at the 392 exact Motohashi overlaps"
        ),
        "package_files_authenticated_before_import": True,
        "source_url": "https://github.com/duetosymmetry/qnm",
        "joss_doi": "10.21105/joss.01683",
        "license": "MIT",
        "license_sha256": (
            "da080a799bd23a0d461e6a33896e4a40f2e5c033e15882a64a3f76f397d20731"
        ),
    }:
        raise ValueError("lattice receipt branch tracker is invalid")
    canonical_cf = _mapping(
        backend.get("canonical_continued_fraction"), "canonical fraction"
    )
    canonical_angular = _mapping(
        backend.get("canonical_angular"), "canonical angular solver"
    )
    canonical_license = _mapping(
        backend.get("canonical_backend_license"), "canonical backend license"
    )
    if (
        backend.get("canonical_source_commit") != _CANONICAL_SOURCE_COMMIT
        or canonical_cf.get("migrated_source_blob")
        != _CANONICAL_CF_SOURCE_BLOB
        or canonical_cf.get("role") != "stored exact-node determinant polish"
        or canonical_cf.get("continued_fraction_tolerance") != 1e-14
        or canonical_cf.get("continued_fraction_minimum_terms") != 1000
        or canonical_cf.get("continued_fraction_maximum_terms") != 60000
        or canonical_angular.get("migrated_source_blob")
        != _CANONICAL_ANGULAR_SOURCE_BLOB
        or _HEX_64.fullmatch(str(canonical_cf.get("module_sha256"))) is None
        or _HEX_64.fullmatch(str(canonical_angular.get("module_sha256"))) is None
        or canonical_license
        != {
            "license": "MIT",
            "path": (
                "src/windows_solver/data/"
                "LICENSE-CANONICAL-BACKEND-MIT.txt"
            ),
            "sha256": (
                "9d077724a197b552d3fc7547b8f7ef8a781387fab6e687fc312f14e28a9928f4"
            ),
            "scope": "offline canonical numerical backend only",
        }
    ):
        raise ValueError("lattice receipt canonical backend is invalid")

    expected_policy = {
        "angular_padding": 20,
        "angular_refinement_padding": 24,
        "branch_id": PUBLIC_BRANCH_ID,
        "boundary_conditions": {"horizon": "ingoing", "infinity": "outgoing"},
        "canonical_root_tolerance": 1e-10,
        "canonical_repeat_root_tolerance": 1e-12,
        "frequency_units": "Momega",
        "formal_root_enclosure": False,
        "minimum_overtone_separation_abs": MINIMUM_OVERTONE_SEPARATION_ABS,
        "qnm_angular_l_max": 24,
        "qnm_cf_tolerance": 1e-14,
        "qnm_continuation_step_maximum": 0.004,
        "qnm_continuation_step_minimum": 1e-5,
        "qnm_fraction_maximum_terms": 60000,
        "qnm_fraction_minimum_terms": 1000,
        "qnm_root_tolerance": math.sqrt(math.ulp(1.0)),
        "spin_weight": -2,
        "stored_value_source": "canonical determinant polish",
        "time_dependence": "exp(-i omega t)",
    }
    if dict(policy) != expected_policy:
        raise ValueError("lattice receipt numerical policy is invalid")
    expected_ceilings = {
        "optimizer_residual_abs": MAXIMUM_OPTIMIZER_RESIDUAL_ABS,
        "continued_fraction_error": MAXIMUM_CONTINUED_FRACTION_ERROR,
        "angular_refinement_abs": MAXIMUM_ANGULAR_REFINEMENT_ABS,
        "repeat_polish_delta_abs": MAXIMUM_REPEAT_POLISH_DELTA_ABS,
        "branch_seed_delta_abs": MAXIMUM_BRANCH_SEED_DELTA_ABS,
        "branch_seed_optimizer_residual_abs": (
            MAXIMUM_BRANCH_SEED_OPTIMIZER_RESIDUAL_ABS
        ),
    }
    if dict(ceilings) != expected_ceilings:
        raise ValueError("lattice receipt diagnostic ceilings are invalid")
    for field, ceiling in expected_ceilings.items():
        observed = maxima.get(field)
        if (
            isinstance(observed, bool)
            or not isinstance(observed, (int, float))
            or not math.isfinite(float(observed))
            or not 0 <= float(observed) <= ceiling
        ):
            raise ValueError(f"lattice receipt {field} maximum is invalid")
    if (
        validation.get("finite_count") != 2736
        or validation.get("damped_count") != 2736
        or validation.get("failure_count") != 0
        or validation.get("scientific_state") != "NOT_EVALUATED"
    ):
        raise ValueError("lattice receipt validation counts are invalid")
    comparison = _mapping(
        validation.get("independent_comparison"), "receipt comparison"
    )
    if (
        comparison.get("comparison_count") != 392
        or comparison.get("comparisons_by_ell")
        != {"2": 118, "3": 166, "4": 108}
        or float(comparison.get("maximum_abs_delta_omega_M", math.inf))
        > MAXIMUM_REFERENCE_DELTA_OMEGA_M
        or float(comparison.get("maximum_abs_delta_A", math.inf))
        > MAXIMUM_REFERENCE_DELTA_A
    ):
        raise ValueError("lattice receipt comparison gate is invalid")
    source_comparison = _mapping(
        value.get("source_comparison"), "receipt source comparison"
    )
    member_hashes = _mapping(
        source_comparison.get("member_sha256"), "receipt member hashes"
    )
    expected_members = {
        f"KerrQNMEFs-2/l{ell}/s-2l{ell}m{m}n{n}.dat"
        for ell in (2, 3, 4)
        for m in range(-ell, ell + 1)
        for n in range(3)
    }
    if (
        source_comparison.get("archive_sha256") != _MOTOHASHI_ARCHIVE_SHA256
        or source_comparison.get("license") != "CC-BY-4.0"
        or source_comparison.get("acceptance_ceilings")
        != {
            "absolute_delta_A": MAXIMUM_REFERENCE_DELTA_A,
            "absolute_delta_omega_M": MAXIMUM_REFERENCE_DELTA_OMEGA_M,
        }
        or set(member_hashes) != expected_members
        or any(_HEX_64.fullmatch(str(item)) is None for item in member_hashes.values())
    ):
        raise ValueError("lattice receipt source comparison is invalid")
    generator = _mapping(value.get("generator"), "receipt generator")
    runtime = _mapping(value.get("runtime"), "receipt runtime")
    dependencies = _mapping(runtime.get("dependencies"), "receipt dependencies")
    if (
        generator.get("path") != "tools/compute_kerr_qnm_lattice.py"
        or _HEX_64.fullmatch(str(generator.get("sha256"))) is None
        or dependencies.get("qnm") != "0.4.4"
        or not isinstance(runtime.get("platform"), str)
        or not isinstance(runtime.get("python"), str)
    ):
        raise ValueError("lattice receipt runtime provenance is invalid")
    return _freeze_json(value)  # type: ignore[return-value]


@lru_cache(maxsize=1)
def load_overlay_receipt() -> Mapping[str, object]:
    value = _read_canonical_json_resource(
        OVERLAY_RECEIPT_RESOURCE,
        expected_sha256=OVERLAY_RECEIPT_SHA256,
        subject="M02 overlay receipt",
    )
    if set(value) != {
        "backend", "evidence_ceiling", "generator", "overlay", "parents",
        "policy", "policy_sha256", "runtime", "schema_version", "validation",
    } or value.get("schema_version") != 1:
        raise ValueError("M02 overlay receipt schema is invalid")
    overlay = _mapping(value.get("overlay"), "overlay receipt catalog")
    parents = _mapping(value.get("parents"), "overlay receipt parents")
    generator = _mapping(value.get("generator"), "overlay receipt generator")
    backend = _mapping(value.get("backend"), "overlay receipt backend")
    angular = _mapping(backend.get("canonical_angular"), "overlay angular backend")
    fraction = _mapping(
        backend.get("canonical_continued_fraction"), "overlay CF backend"
    )
    policy = _mapping(value.get("policy"), "overlay numerical policy")
    validation = _mapping(value.get("validation"), "overlay validation")
    maxima = _mapping(validation.get("observed_maxima"), "overlay maxima")
    minima = _mapping(validation.get("observed_minima"), "overlay minima")
    runtime = _mapping(value.get("runtime"), "overlay runtime")
    dependencies = _mapping(runtime.get("dependencies"), "overlay dependencies")
    if overlay != {
        "columns": list(_OVERLAY_COLUMNS),
        "line_endings": "LF",
        "ordering": ["ell", "m", "n", "spin_binary64"],
        "row_count_excluding_header": 44,
        "sha256": OVERLAY_DATA_SHA256,
        "target_set_sha256": _OVERLAY_TARGET_SET_SHA256,
    }:
        raise ValueError("M02 overlay receipt catalog binding is invalid")
    if parents != {
        "base_catalog_sha256": CATALOG_DATA_SHA256,
        "base_independent_comparison_count": 392,
        "base_receipt_sha256": CATALOG_RECEIPT_SHA256,
        "base_root_count": 2736,
    }:
        raise ValueError("M02 overlay receipt parent binding is invalid")
    if generator != {
        "path": "tools/compute_kerr_qnm_overlay.py",
        "sha256": _OVERLAY_GENERATOR_SHA256,
    }:
        raise ValueError("M02 overlay generator identity is invalid")
    if (
        backend.get("backend_id")
        != "canonical-coupled-leaver-cohort-continuation"
        or backend.get("candidate_bank")
        != "all-cohort-predictors-cross-all-cohort-inversions"
        or backend.get("version") != 1
        or angular
        != {
            "migrated_source_blob": _CANONICAL_ANGULAR_SOURCE_BLOB,
            "module_sha256": (
                "109642519372736375c24b15a879fe15c2a06714b78d743f065497fdad50738a"
            ),
        }
        or fraction
        != {
            "maximum_terms": 60000,
            "migrated_source_blob": _CANONICAL_CF_SOURCE_BLOB,
            "minimum_terms": 1000,
            "module_sha256": (
                "8ad69fba84d1100ca4b4647760b595ee15ea4a13ffd0a1bfdd9fe635c119d2e4"
            ),
            "tolerance": 1e-14,
        }
    ):
        raise ValueError("M02 overlay backend identity is invalid")
    if value.get("policy_sha256") != _OVERLAY_POLICY_SHA256 or policy != {
        "angular_overlap_minimum": 0.9,
        "angular_padding": 20,
        "angular_refinement_padding": 24,
        "assignment_minimum_relative_gap": 0.05,
        "branch_id": PUBLIC_BRANCH_ID,
        "canonical_repeat_root_tolerance": 1e-12,
        "canonical_root_tolerance": 1e-10,
        "continued_fraction_error_maximum": 1e-9,
        "formal_root_enclosure": False,
        "independent_path_delta_maximum": 1e-8,
        "minimum_adaptive_step": 0.003,
        "minimum_assigned_separation_abs": 1e-6,
        "optimizer_residual_abs_maximum": 1e-8,
        "predictor_correction_over_separation_maximum": 0.24,
        "repeat_polish_delta_abs_maximum": 1e-9,
        "reverse_delta_abs_maximum": 1e-8,
        "schedule_a_coordinate": "x=-log(sqrt((1-chi)(1+chi)))",
        "schedule_a_step_maximum_by_ell": {"2": 0.16, "3": 0.12, "4": 0.12},
        "schedule_b_coordinate": "y=-log(M-kappa)",
        "schedule_b_step_maximum_by_ell": {"2": 0.12, "3": 0.09, "4": 0.09},
        "spin_weight": -2,
    }:
        raise ValueError("M02 overlay numerical policy is invalid")
    ceilings = {
        "optimizer_residual_abs": 1e-8,
        "continued_fraction_error": 1e-9,
        "angular_refinement_abs": 1e-9,
        "repeat_polish_delta_abs": 1e-9,
        "predictor_correction_over_separation": 0.24,
        "independent_path_delta_abs": 1e-8,
        "reverse_delta_abs": 1e-8,
    }
    for field, ceiling in ceilings.items():
        observed = maxima.get(field)
        if (
            isinstance(observed, bool)
            or not isinstance(observed, (int, float))
            or not math.isfinite(float(observed))
            or not 0 <= float(observed) <= ceiling
        ):
            raise ValueError(f"M02 overlay {field} maximum is invalid")
    floor_values = {
        "assigned_separation_abs": 1e-6,
        "assignment_relative_gap": 0.05,
        "angular_overlap_min": 0.9,
        "minimum_adaptive_step": 0.003,
    }
    for field, floor in floor_values.items():
        observed = minima.get(field)
        if (
            isinstance(observed, bool)
            or not isinstance(observed, (int, float))
            or not math.isfinite(float(observed))
            or float(observed) < floor
        ):
            raise ValueError(f"M02 overlay {field} minimum is invalid")
    if (
        validation.get("damped_count") != 44
        or validation.get("finite_count") != 44
        or validation.get("failure_count") != 0
        or validation.get("scientific_state") != "NOT_EVALUATED"
        or dependencies.get("numpy") != "2.3.5"
        or dependencies.get("scipy") != "1.17.0"
        or runtime.get("python") != "3.12.13"
        or not isinstance(runtime.get("platform"), str)
        or value.get("evidence_ceiling")
        != (
            "numerical continuation and genealogy evidence only; no formal "
            "root enclosure, external comparator, or DM/ZDM classification"
        )
    ):
        raise ValueError("M02 overlay validation or evidence ceiling is invalid")
    return _freeze_json(value)  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class SpectralRoot:
    s: int
    ell: int
    m: int
    n: int
    branch_id: str
    grid_family: str
    grid_index: int
    chi_numerator: int
    chi_denominator: int
    spin: float
    spin_hex: str
    omega_re: float
    omega_im: float
    angular_A_re: float
    angular_A_im: float
    optimizer_residual_abs: float
    continued_fraction_error: float
    continued_fraction_terms: int
    angular_padding: int
    angular_refinement_padding: int
    angular_refinement_abs: float
    repeat_polish_delta_abs: float
    branch_seed_delta_abs: float
    branch_seed_optimizer_residual_abs: float
    continuation_step_maximum: float
    nearest_overtone_separation_abs: float | None
    reference_member: str | None
    reference_row: int | None
    reference_abs_delta_omega_M: float | None
    reference_abs_delta_A: float | None

    @property
    def key(self) -> tuple[int, int, int, int, int]:
        return (
            self.ell,
            self.m,
            self.n,
            self.chi_numerator,
            self.chi_denominator,
        )

    @property
    def selection_key(self) -> tuple[int, int, int, str]:
        return (self.ell, self.m, self.n, self.spin_hex)

    def to_mapping(self) -> dict[str, object]:
        comparison: dict[str, object] | None = None
        if self.reference_member is not None:
            comparison = {
                "member": self.reference_member,
                "row": self.reference_row,
                "absolute_frequency_delta_Momega": (
                    self.reference_abs_delta_omega_M
                ),
                "absolute_angular_A_delta": self.reference_abs_delta_A,
            }
        return {
            "mode": {
                "s": self.s,
                "ell": self.ell,
                "m": self.m,
                "n": self.n,
                "branch": self.branch_id,
                "polarization": PUBLIC_POLARIZATION_ID,
            },
            "spin": self.spin,
            "spin_exact": {
                "numerator": self.chi_numerator,
                "denominator": self.chi_denominator,
            },
            "spin_binary64_hex": self.spin_hex,
            "frequency": {
                "real": self.omega_re,
                "imaginary": self.omega_im,
                "units": "Momega",
            },
            "angular_separation_constant_A": {
                "real": self.angular_A_re,
                "imaginary": self.angular_A_im,
            },
            "numerical_evidence": {
                "optimizer_residual_abs": self.optimizer_residual_abs,
                "continued_fraction_error": self.continued_fraction_error,
                "continued_fraction_terms": self.continued_fraction_terms,
                "angular_refinement_abs": self.angular_refinement_abs,
                "repeat_polish_delta_abs": self.repeat_polish_delta_abs,
                "branch_seed_delta_abs": self.branch_seed_delta_abs,
                "nearest_overtone_separation_abs": (
                    self.nearest_overtone_separation_abs
                ),
            },
            "independent_comparison": comparison,
        }


@dataclass(frozen=True, slots=True)
class SpectralOverlayRoot:
    ell: int
    m: int
    n: int
    source_coordinate_id: str
    source_coordinate: Fraction
    source_transformation_id: str
    spin_numerator: int
    spin_denominator: int
    spin: float
    spin_hex: str
    omega_re: float
    omega_im: float
    angular_A_re: float
    angular_A_im: float
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

    @property
    def s(self) -> int:
        return -2

    @property
    def branch_id(self) -> str:
        return PUBLIC_BRANCH_ID

    @property
    def selection_key(self) -> tuple[int, int, int, str]:
        return self.ell, self.m, self.n, self.spin_hex

    @property
    def target_identity(self) -> tuple[int, int, int, str, Fraction, str, float]:
        return (
            self.ell,
            self.m,
            self.n,
            self.source_coordinate_id,
            self.source_coordinate,
            self.source_transformation_id,
            self.spin,
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "mode": {
                "s": -2,
                "ell": self.ell,
                "m": self.m,
                "n": self.n,
                "branch": PUBLIC_BRANCH_ID,
                "polarization": PUBLIC_POLARIZATION_ID,
            },
            "source_coordinate": {
                "coordinate_id": self.source_coordinate_id,
                "numerator": self.source_coordinate.numerator,
                "denominator": self.source_coordinate.denominator,
                "transformation_id": self.source_transformation_id,
            },
            "spin": self.spin,
            "spin_binary64_ratio": {
                "numerator": self.spin_numerator,
                "denominator": self.spin_denominator,
            },
            "spin_binary64_hex": self.spin_hex,
            "frequency": {
                "real": self.omega_re,
                "imaginary": self.omega_im,
                "units": "Momega",
            },
            "angular_separation_constant_A": {
                "real": self.angular_A_re,
                "imaginary": self.angular_A_im,
            },
            "numerical_evidence": {
                "optimizer_residual_abs": self.optimizer_residual_abs,
                "continued_fraction_error": self.continued_fraction_error,
                "continued_fraction_terms": self.continued_fraction_terms,
                "angular_refinement_abs": self.angular_refinement_abs,
                "repeat_polish_delta_abs": self.repeat_polish_delta_abs,
                "predictor_correction_abs": self.predictor_correction_abs,
                "predictor_correction_over_separation": (
                    self.predictor_correction_over_separation
                ),
                "assigned_separation_abs": self.assigned_separation_abs,
                "assignment_relative_gap": self.assignment_relative_gap,
                "canonical_polish_delta_abs": self.canonical_polish_delta_abs,
                "independent_path_delta_abs": self.independent_path_delta_abs,
                "reverse_delta_abs": self.reverse_delta_abs,
                "angular_overlap_min": self.angular_overlap_min,
                "schedule_a_steps": self.schedule_a_steps,
                "schedule_b_steps": self.schedule_b_steps,
                "minimum_adaptive_step": self.minimum_adaptive_step,
                "formal_root_enclosure": False,
            },
            "independent_comparison": None,
        }


@dataclass(frozen=True, slots=True)
class SpectrumOverlayCatalog:
    roots: tuple[SpectralOverlayRoot, ...]
    data_sha256: str
    receipt: Mapping[str, object]

    @classmethod
    def from_csv_bytes(
        cls, data: bytes, *, expected_sha256: str
    ) -> "SpectrumOverlayCatalog":
        actual_sha256 = hashlib.sha256(data).hexdigest()
        if actual_sha256 != expected_sha256:
            raise ValueError("overlay SHA-256 does not match the admitted resource")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("overlay must be UTF-8") from error
        if not text.endswith("\n") or "\r" in text:
            raise ValueError("overlay bytes are not canonical UTF-8 CSV")
        reader = csv.DictReader(io.StringIO(text), strict=True)
        if tuple(reader.fieldnames or ()) != _OVERLAY_COLUMNS:
            raise ValueError("overlay column schema does not match")
        roots: list[SpectralOverlayRoot] = []
        try:
            for row_number, row in enumerate(reader, start=2):
                if set(row) != set(_OVERLAY_COLUMNS) or None in row:
                    raise ValueError(
                        f"overlay row {row_number} does not match the column schema"
                    )
                roots.append(cls._parse_root(row, row_number))
        except csv.Error as error:
            raise ValueError("overlay CSV is malformed") from error
        return cls._validated(tuple(roots), actual_sha256)

    @staticmethod
    def _parse_root(
        row: Mapping[str, str], row_number: int
    ) -> SpectralOverlayRoot:
        if (
            _parse_int(row["s"], "s", row_number) != -2
            or row["branch_id"] != PUBLIC_BRANCH_ID
            or row["root_solver_success"] != "true"
        ):
            raise ValueError(f"overlay row {row_number} mode or solver state is invalid")
        coordinate_numerator = _parse_int(
            row["source_coordinate_numerator"],
            "source_coordinate_numerator",
            row_number,
        )
        coordinate_denominator = _parse_int(
            row["source_coordinate_denominator"],
            "source_coordinate_denominator",
            row_number,
        )
        if coordinate_denominator <= 0:
            raise ValueError(f"overlay row {row_number} source denominator is invalid")
        coordinate = Fraction(coordinate_numerator, coordinate_denominator)
        if (coordinate.numerator, coordinate.denominator) != (
            coordinate_numerator,
            coordinate_denominator,
        ):
            raise ValueError(f"overlay row {row_number} source rational is not reduced")
        spin_numerator = _parse_int(
            row["spin_numerator"], "spin_numerator", row_number
        )
        spin_denominator = _parse_int(
            row["spin_denominator"], "spin_denominator", row_number
        )
        spin = _parse_float(row["spin_float"], "spin_float", row_number)
        if spin_denominator <= 0 or spin.as_integer_ratio() != (
            spin_numerator,
            spin_denominator,
        ):
            raise ValueError(f"overlay row {row_number} spin ratio is invalid")
        spin_hex = row["spin_binary64_hex"]
        if spin_hex != spin.hex() or float.fromhex(spin_hex) != spin:
            raise ValueError(f"overlay row {row_number} spin hex is invalid")
        integer_fields = {
            "continued_fraction_terms": _parse_int(
                row["continued_fraction_terms"],
                "continued_fraction_terms",
                row_number,
            ),
            "schedule_a_steps": _parse_int(
                row["schedule_a_steps"], "schedule_a_steps", row_number
            ),
            "schedule_b_steps": _parse_int(
                row["schedule_b_steps"], "schedule_b_steps", row_number
            ),
        }
        if (
            _parse_int(row["angular_padding"], "angular_padding", row_number) != 20
            or _parse_int(
                row["angular_refinement_padding"],
                "angular_refinement_padding",
                row_number,
            )
            != 24
        ):
            raise ValueError(f"overlay row {row_number} angular policy is invalid")
        float_fields = {
            field: _parse_float(row[field], field, row_number)
            for field in (
                "omega_re_M", "omega_im_M", "angular_A_re", "angular_A_im",
                "optimizer_residual_abs", "continued_fraction_error",
                "angular_refinement_abs", "repeat_polish_delta_abs",
                "predictor_correction_abs",
                "predictor_correction_over_separation",
                "assigned_separation_abs", "assignment_relative_gap",
                "canonical_polish_delta_abs", "independent_path_delta_abs",
                "reverse_delta_abs", "angular_overlap_min",
                "minimum_adaptive_step",
            )
        }
        root = SpectralOverlayRoot(
            ell=_parse_int(row["ell"], "ell", row_number),
            m=_parse_int(row["m"], "m", row_number),
            n=_parse_int(row["n"], "n", row_number),
            source_coordinate_id=row["source_coordinate_id"],
            source_coordinate=coordinate,
            source_transformation_id=row["source_transformation_id"],
            spin_numerator=spin_numerator,
            spin_denominator=spin_denominator,
            spin=spin,
            spin_hex=spin_hex,
            omega_re=float_fields.pop("omega_re_M"),
            omega_im=float_fields.pop("omega_im_M"),
            angular_A_re=float_fields.pop("angular_A_re"),
            angular_A_im=float_fields.pop("angular_A_im"),
            **integer_fields,
            **float_fields,
        )
        SpectrumOverlayCatalog._validate_root(root, row_number)
        return root

    @staticmethod
    def _validate_root(root: SpectralOverlayRoot, row_number: int) -> None:
        if root.omega_im >= 0.0:
            raise ValueError(f"overlay row {row_number} is not damped")
        ceilings = {
            "optimizer residual": (root.optimizer_residual_abs, 1e-8),
            "continued fraction": (root.continued_fraction_error, 1e-9),
            "angular refinement": (root.angular_refinement_abs, 1e-9),
            "repeat polish": (root.repeat_polish_delta_abs, 1e-9),
            "predictor ratio": (
                root.predictor_correction_over_separation, 0.24
            ),
            "independent path": (root.independent_path_delta_abs, 1e-8),
            "reverse": (root.reverse_delta_abs, 1e-8),
        }
        diagnostics = (
            root.predictor_correction_abs,
            root.assigned_separation_abs,
            root.assignment_relative_gap,
            root.canonical_polish_delta_abs,
            root.angular_overlap_min,
            root.minimum_adaptive_step,
        )
        if any(value < 0.0 for value in diagnostics):
            raise ValueError(f"overlay row {row_number} has negative diagnostics")
        for name, (value, ceiling) in ceilings.items():
            if value < 0.0 or value > ceiling:
                raise ValueError(
                    f"overlay row {row_number} diagnostic {name} exceeds threshold"
                )
        if (
            root.assigned_separation_abs < 1e-6
            or root.assignment_relative_gap < 0.05
            or root.angular_overlap_min < 0.9
            or root.angular_overlap_min > 1.0
            or root.minimum_adaptive_step < 0.003
            or root.continued_fraction_terms < 1000
            or root.continued_fraction_terms >= 60000
            or root.schedule_a_steps <= 0
            or root.schedule_b_steps <= 0
        ):
            raise ValueError(f"overlay row {row_number} numerical policy is invalid")

    @classmethod
    def _validated(
        cls, roots: tuple[SpectralOverlayRoot, ...], data_sha256: str
    ) -> "SpectrumOverlayCatalog":
        if len(roots) != 44:
            raise ValueError("overlay count must be exactly 44 roots")
        if tuple(root.target_identity for root in roots) != _EXPECTED_OVERLAY_TARGETS:
            identities = tuple(root.target_identity for root in roots)
            if set(identities) == set(_EXPECTED_OVERLAY_TARGETS):
                raise ValueError("overlay roots are not in canonical order")
            raise ValueError("overlay roots do not equal the exact 44-target set")
        keys = tuple(root.selection_key for root in roots)
        if len(set(keys)) != 44:
            raise ValueError("overlay contains duplicate selection keys")
        receipt = load_overlay_receipt()
        overlay = _mapping(receipt.get("overlay"), "overlay receipt catalog")
        if overlay.get("sha256") != data_sha256:
            raise ValueError("overlay receipt does not bind the catalog bytes")
        validation = _mapping(receipt.get("validation"), "overlay validation")
        receipt_maxima = _mapping(
            validation.get("observed_maxima"), "overlay maxima"
        )
        receipt_minima = _mapping(
            validation.get("observed_minima"), "overlay minima"
        )
        maxima_fields = (
            "optimizer_residual_abs", "continued_fraction_error",
            "angular_refinement_abs", "repeat_polish_delta_abs",
            "predictor_correction_abs",
            "predictor_correction_over_separation",
            "canonical_polish_delta_abs", "independent_path_delta_abs",
            "reverse_delta_abs",
        )
        minima_fields = (
            "assigned_separation_abs", "assignment_relative_gap",
            "angular_overlap_min", "minimum_adaptive_step",
        )
        if any(
            float(receipt_maxima[field])
            != max(getattr(root, field) for root in roots)
            for field in maxima_fields
        ) or any(
            float(receipt_minima[field])
            != min(getattr(root, field) for root in roots)
            for field in minima_fields
        ):
            raise ValueError("overlay row diagnostics do not match the receipt")
        return cls(roots=roots, data_sha256=data_sha256, receipt=receipt)


@dataclass(frozen=True, slots=True)
class SpectrumScope:
    def to_mapping(self) -> dict[str, object]:
        return {
            "computed_lattice": {
                "mode_count": 63,
                "root_count": 2736,
                "roots_by_ell": {"2": 690, "3": 966, "4": 1080},
                "spin_points_by_ell": {"2": 46, "3": 46, "4": 40},
            }
        }


@dataclass(frozen=True, slots=True)
class SpectrumValidation:
    observed_maxima: Mapping[str, float]
    comparison_count: int
    comparison_maximum_frequency_delta: float
    comparison_maximum_angular_delta: float

    def to_mapping(self) -> dict[str, object]:
        return {
            "full_grid_diagnostics": {
                "maximum_optimizer_residual_abs": (
                    MAXIMUM_OPTIMIZER_RESIDUAL_ABS
                ),
                "observed_maximum_optimizer_residual_abs": (
                    self.observed_maxima["optimizer_residual_abs"]
                ),
                "maximum_continued_fraction_error": (
                    MAXIMUM_CONTINUED_FRACTION_ERROR
                ),
                "observed_maximum_continued_fraction_error": (
                    self.observed_maxima["continued_fraction_error"]
                ),
                "maximum_angular_refinement_abs": (
                    MAXIMUM_ANGULAR_REFINEMENT_ABS
                ),
                "observed_maximum_angular_refinement_abs": (
                    self.observed_maxima["angular_refinement_abs"]
                ),
                "maximum_repeat_polish_delta_abs": (
                    MAXIMUM_REPEAT_POLISH_DELTA_ABS
                ),
                "observed_maximum_repeat_polish_delta_abs": (
                    self.observed_maxima["repeat_polish_delta_abs"]
                ),
                "maximum_branch_seed_delta_abs": MAXIMUM_BRANCH_SEED_DELTA_ABS,
                "observed_maximum_branch_seed_delta_abs": (
                    self.observed_maxima["branch_seed_delta_abs"]
                ),
                "maximum_branch_seed_optimizer_residual_abs": (
                    MAXIMUM_BRANCH_SEED_OPTIMIZER_RESIDUAL_ABS
                ),
                "observed_maximum_branch_seed_optimizer_residual_abs": (
                    self.observed_maxima[
                        "branch_seed_optimizer_residual_abs"
                    ]
                ),
                "formal_root_enclosure": False,
            },
            "independent_comparison": {
                "comparison_count": self.comparison_count,
                "maximum_frequency_delta_Momega": (
                    self.comparison_maximum_frequency_delta
                ),
                "maximum_angular_A_delta": self.comparison_maximum_angular_delta,
                "frequency_tolerance_abs": MAXIMUM_REFERENCE_DELTA_OMEGA_M,
                "angular_A_tolerance_abs": MAXIMUM_REFERENCE_DELTA_A,
            },
        }


@dataclass(frozen=True, slots=True)
class SpectrumCatalog:
    roots: tuple[SpectralRoot, ...]
    scope: SpectrumScope
    validation: SpectrumValidation
    data_sha256: str

    @property
    def keys(self) -> frozenset[tuple[int, int, int, int, int]]:
        return frozenset(root.key for root in self.roots)

    @classmethod
    def from_csv_bytes(
        cls, data: bytes, *, expected_sha256: str
    ) -> "SpectrumCatalog":
        actual_sha256 = hashlib.sha256(data).hexdigest()
        if actual_sha256 != expected_sha256:
            raise ValueError(
                "catalog SHA-256 does not match the admitted resource"
            )
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("catalog must be UTF-8") from error
        if not text.endswith("\n") or "\r" in text:
            raise ValueError("catalog bytes are not canonical UTF-8 CSV")
        reader = csv.DictReader(io.StringIO(text), strict=True)
        if tuple(reader.fieldnames or ()) != _CATALOG_COLUMNS:
            raise ValueError("catalog column schema does not match")

        roots: list[SpectralRoot] = []
        try:
            for row_number, row in enumerate(reader, start=2):
                if set(row) != set(_CATALOG_COLUMNS) or None in row:
                    raise ValueError(
                        f"catalog row {row_number} does not match the column schema"
                    )
                root = cls._parse_root(row, row_number)
                cls._validate_root(root, row_number)
                roots.append(root)
        except csv.Error as error:
            raise ValueError("catalog CSV is malformed") from error
        return cls._validated(tuple(roots), actual_sha256)

    @staticmethod
    def _parse_root(row: Mapping[str, str], row_number: int) -> SpectralRoot:
        numerator = _parse_int(row["chi_numerator"], "chi_numerator", row_number)
        denominator = _parse_int(
            row["chi_denominator"], "chi_denominator", row_number
        )
        if denominator <= 0:
            raise ValueError(f"catalog row {row_number} rational denominator is invalid")
        spin_fraction = Fraction(numerator, denominator)
        if (spin_fraction.numerator, spin_fraction.denominator) != (
            numerator,
            denominator,
        ):
            raise ValueError(
                f"catalog row {row_number} spin rational is not reduced"
            )
        spin = _parse_float(row["chi_float"], "chi_float", row_number)
        if spin != float(spin_fraction):
            raise ValueError(
                f"catalog row {row_number} spin float does not match rational"
            )
        spin_hex = row["chi_float_hex"]
        if spin_hex != spin.hex():
            raise ValueError(
                f"catalog row {row_number} spin binary64 hex is not canonical"
            )
        success = row["root_solver_success"]
        if success not in {"true", "false"}:
            raise ValueError(f"catalog row {row_number} solver flag is invalid")
        if success != "true":
            raise ValueError(
                f"catalog row {row_number} root solver did not report success"
            )
        return SpectralRoot(
            s=_parse_int(row["s"], "s", row_number),
            ell=_parse_int(row["ell"], "ell", row_number),
            m=_parse_int(row["m"], "m", row_number),
            n=_parse_int(row["n"], "n", row_number),
            branch_id=row["branch_id"],
            grid_family=row["chi_grid_family"],
            grid_index=_parse_int(row["chi_grid_index"], "chi_grid_index", row_number),
            chi_numerator=numerator,
            chi_denominator=denominator,
            spin=spin,
            spin_hex=spin_hex,
            omega_re=_parse_float(row["omega_re_M"], "omega_re_M", row_number),
            omega_im=_parse_float(row["omega_im_M"], "omega_im_M", row_number),
            angular_A_re=_parse_float(
                row["angular_A_re"], "angular_A_re", row_number
            ),
            angular_A_im=_parse_float(
                row["angular_A_im"], "angular_A_im", row_number
            ),
            optimizer_residual_abs=_parse_float(
                row["optimizer_residual_abs"], "optimizer_residual_abs", row_number
            ),
            continued_fraction_error=_parse_float(
                row["continued_fraction_error"],
                "continued_fraction_error",
                row_number,
            ),
            continued_fraction_terms=_parse_int(
                row["continued_fraction_terms"],
                "continued_fraction_terms",
                row_number,
            ),
            angular_padding=_parse_int(
                row["angular_padding"], "angular_padding", row_number
            ),
            angular_refinement_padding=_parse_int(
                row["angular_refinement_padding"],
                "angular_refinement_padding",
                row_number,
            ),
            angular_refinement_abs=_parse_float(
                row["angular_refinement_abs"],
                "angular_refinement_abs",
                row_number,
            ),
            repeat_polish_delta_abs=_parse_float(
                row["repeat_polish_delta_abs"],
                "repeat_polish_delta_abs",
                row_number,
            ),
            branch_seed_delta_abs=_parse_float(
                row["branch_seed_delta_abs"],
                "branch_seed_delta_abs",
                row_number,
            ),
            branch_seed_optimizer_residual_abs=_parse_float(
                row["branch_seed_optimizer_residual_abs"],
                "branch_seed_optimizer_residual_abs",
                row_number,
            ),
            continuation_step_maximum=_parse_float(
                row["continuation_step_maximum"],
                "continuation_step_maximum",
                row_number,
            ),
            nearest_overtone_separation_abs=_parse_optional_float(
                row["nearest_overtone_separation_abs"],
                "nearest_overtone_separation_abs",
                row_number,
            ),
            reference_member=row["reference_member"] or None,
            reference_row=_parse_optional_int(
                row["reference_row"], "reference_row", row_number
            ),
            reference_abs_delta_omega_M=_parse_optional_float(
                row["reference_abs_delta_omega_M"],
                "reference_abs_delta_omega_M",
                row_number,
            ),
            reference_abs_delta_A=_parse_optional_float(
                row["reference_abs_delta_A"],
                "reference_abs_delta_A",
                row_number,
            ),
        )

    @staticmethod
    def _validate_root(root: SpectralRoot, row_number: int) -> None:
        if (
            root.s != -2
            or root.ell not in (2, 3, 4)
            or abs(root.m) > root.ell
            or root.n not in (0, 1, 2)
            or root.branch_id != PUBLIC_BRANCH_ID
        ):
            raise ValueError(f"catalog row {row_number} has an invalid mode")
        spin = Fraction(root.chi_numerator, root.chi_denominator)
        try:
            expected_family, expected_index = _grid_identity(root.ell, spin)
        except ValueError as error:
            raise ValueError(
                f"catalog row {row_number} has an invalid lattice spin"
            ) from error
        if (root.grid_family, root.grid_index) != (
            expected_family,
            expected_index,
        ):
            raise ValueError(
                f"catalog row {row_number} has an invalid lattice spin grid"
            )
        if root.omega_im >= 0.0:
            raise ValueError(f"catalog row {row_number} is not damped")
        diagnostics = {
            "optimizer residual": (
                root.optimizer_residual_abs,
                MAXIMUM_OPTIMIZER_RESIDUAL_ABS,
            ),
            "continued fraction error": (
                root.continued_fraction_error,
                MAXIMUM_CONTINUED_FRACTION_ERROR,
            ),
            "angular refinement": (
                root.angular_refinement_abs,
                MAXIMUM_ANGULAR_REFINEMENT_ABS,
            ),
            "repeat polish": (
                root.repeat_polish_delta_abs,
                MAXIMUM_REPEAT_POLISH_DELTA_ABS,
            ),
            "branch seed": (
                root.branch_seed_delta_abs,
                MAXIMUM_BRANCH_SEED_DELTA_ABS,
            ),
            "branch seed optimizer residual": (
                root.branch_seed_optimizer_residual_abs,
                MAXIMUM_BRANCH_SEED_OPTIMIZER_RESIDUAL_ABS,
            ),
        }
        for name, (value, ceiling) in diagnostics.items():
            if value < 0 or value > ceiling:
                raise ValueError(
                    f"catalog row {row_number} diagnostic {name} exceeds threshold"
                )
        if (
            root.continued_fraction_terms < 1000
            or root.continued_fraction_terms >= 60000
            or root.angular_padding != 20
            or root.angular_refinement_padding != 24
            or root.continuation_step_maximum != 0.004
        ):
            raise ValueError(f"catalog row {row_number} numerical policy is invalid")
        if root.n == 0:
            if root.nearest_overtone_separation_abs is not None:
                raise ValueError(
                    f"catalog row {row_number} overtone separation is invalid"
                )
        elif (
            root.nearest_overtone_separation_abs is None
            or root.nearest_overtone_separation_abs
            < MINIMUM_OVERTONE_SEPARATION_ABS
        ):
            raise ValueError(
                f"catalog row {row_number} overtone branches collide"
            )
        reference_values = (
            root.reference_member,
            root.reference_row,
            root.reference_abs_delta_omega_M,
            root.reference_abs_delta_A,
        )
        if any(item is None for item in reference_values) and not all(
            item is None for item in reference_values
        ):
            raise ValueError(
                f"catalog row {row_number} reference comparison is incomplete"
            )
        if root.reference_member is not None:
            expected_member = (
                f"KerrQNMEFs-2/l{root.ell}/"
                f"s-2l{root.ell}m{root.m}n{root.n}.dat"
            )
            if (
                root.reference_member != expected_member
                or root.reference_row is None
                or root.reference_row <= 0
                or root.reference_abs_delta_omega_M is None
                or root.reference_abs_delta_omega_M
                > MAXIMUM_REFERENCE_DELTA_OMEGA_M
                or root.reference_abs_delta_A is None
                or root.reference_abs_delta_A > MAXIMUM_REFERENCE_DELTA_A
            ):
                raise ValueError(
                    f"catalog row {row_number} reference comparison is invalid"
                )

    @classmethod
    def _validated(
        cls, roots: tuple[SpectralRoot, ...], data_sha256: str
    ) -> "SpectrumCatalog":
        if len(roots) != 2736:
            raise ValueError("catalog count must be exactly 2,736 roots")
        keys = tuple(root.key for root in roots)
        if len(set(keys)) != len(keys):
            raise ValueError("catalog contains duplicate lattice keys")
        if keys != _EXPECTED_LATTICE_KEYS:
            if set(keys) == _EXPECTED_LATTICE_KEY_SET:
                raise ValueError("catalog roots are not in canonical order")
            raise ValueError("catalog keys do not equal the exact lattice")

        receipt = load_catalog_receipt()
        receipt_catalog = _mapping(receipt.get("catalog"), "receipt catalog")
        if receipt_catalog.get("sha256") != data_sha256:
            raise ValueError("catalog receipt does not bind the catalog bytes")

        maxima = {
            "optimizer_residual_abs": max(
                root.optimizer_residual_abs for root in roots
            ),
            "continued_fraction_error": max(
                root.continued_fraction_error for root in roots
            ),
            "angular_refinement_abs": max(
                root.angular_refinement_abs for root in roots
            ),
            "repeat_polish_delta_abs": max(
                root.repeat_polish_delta_abs for root in roots
            ),
            "branch_seed_delta_abs": max(
                root.branch_seed_delta_abs for root in roots
            ),
            "branch_seed_optimizer_residual_abs": max(
                root.branch_seed_optimizer_residual_abs for root in roots
            ),
        }
        comparisons = [root for root in roots if root.reference_member is not None]
        if len(comparisons) != 392:
            raise ValueError("catalog comparison coverage is not exactly 392 roots")
        validation_receipt = _mapping(
            receipt.get("validation"), "receipt validation"
        )
        receipt_maxima = _mapping(
            validation_receipt.get("observed_maxima"), "receipt maxima"
        )
        if any(float(receipt_maxima[field]) != value for field, value in maxima.items()):
            raise ValueError("catalog row diagnostics do not match the receipt")
        comparison_receipt = _mapping(
            validation_receipt.get("independent_comparison"),
            "receipt comparison",
        )
        comparison_maximum_frequency = max(
            root.reference_abs_delta_omega_M or 0.0 for root in comparisons
        )
        comparison_maximum_angular = max(
            root.reference_abs_delta_A or 0.0 for root in comparisons
        )
        if (
            float(comparison_receipt["maximum_abs_delta_omega_M"])
            != comparison_maximum_frequency
            or float(comparison_receipt["maximum_abs_delta_A"])
            != comparison_maximum_angular
        ):
            raise ValueError("catalog comparisons do not match the receipt")
        return cls(
            roots=roots,
            scope=SpectrumScope(),
            validation=SpectrumValidation(
                observed_maxima=MappingProxyType(maxima),
                comparison_count=len(comparisons),
                comparison_maximum_frequency_delta=comparison_maximum_frequency,
                comparison_maximum_angular_delta=comparison_maximum_angular,
            ),
            data_sha256=data_sha256,
        )

    def select(self, request: StudyRequest) -> tuple[SpectralRoot, ...]:
        if request.target is not Capability.SPECTRAL_CORE:
            raise ValueError("spectral catalog requires target spectral-core")
        if request.theory_id != PUBLIC_THEORY_ID:
            raise ValueError(
                f"spectral catalog does not support theory_id {request.theory_id!r}"
            )
        if request.convention_id != PUBLIC_CONVENTION_ID:
            raise ValueError(
                "spectral catalog does not support convention_id "
                f"{request.convention_id!r}"
            )
        if request.numerical_policy:
            raise ValueError("spectral catalog does not accept numerical policy overrides")
        by_key = {root.selection_key: root for root in self.roots}
        selected: list[SpectralRoot] = []
        requested: set[tuple[int, int, int, str]] = set()
        for mode in request.modes:
            if (
                mode.s != -2
                or mode.branch != PUBLIC_BRANCH_ID
                or mode.polarization != PUBLIC_POLARIZATION_ID
            ):
                raise ValueError("catalog has no exact root for the requested mode")
            for spin in request.spins:
                key = (mode.ell, mode.m, mode.n, float(spin).hex())
                if key in requested:
                    raise ValueError("duplicate mode-spin pair in spectral request")
                requested.add(key)
                root = by_key.get(key)
                if root is None:
                    raise ValueError("catalog has no exact root for requested mode-spin pair")
                selected.append(root)
        return tuple(selected)


@lru_cache(maxsize=1)
def load_base_spectrum_catalog() -> SpectrumCatalog:
    return SpectrumCatalog.from_csv_bytes(
        CATALOG_RESOURCE.read_bytes(), expected_sha256=CATALOG_DATA_SHA256
    )


@lru_cache(maxsize=1)
def load_overlay_catalog() -> SpectrumOverlayCatalog:
    return SpectrumOverlayCatalog.from_csv_bytes(
        OVERLAY_RESOURCE.read_bytes(), expected_sha256=OVERLAY_DATA_SHA256
    )


@dataclass(frozen=True, slots=True)
class SpectralCatalogUnion:
    base: SpectrumCatalog
    overlay: SpectrumOverlayCatalog

    def __post_init__(self) -> None:
        base_keys = {root.selection_key for root in self.base.roots}
        overlay_keys = {root.selection_key for root in self.overlay.roots}
        if len(base_keys) != len(self.base.roots):
            raise ValueError("base catalog has ambiguous selection keys")
        if len(overlay_keys) != len(self.overlay.roots):
            raise ValueError("overlay catalog has ambiguous selection keys")
        if base_keys & overlay_keys:
            raise ValueError("base and overlay contain duplicate ambiguous selectors")

    @property
    def roots(self) -> tuple[SpectralRoot, ...]:
        """Retain the immutable base carrier surface for existing consumers."""

        return self.base.roots

    @property
    def keys(self) -> frozenset[tuple[int, int, int, int, int]]:
        return self.base.keys

    @property
    def scope(self) -> SpectrumScope:
        return self.base.scope

    @property
    def validation(self) -> SpectrumValidation:
        return self.base.validation

    @property
    def data_sha256(self) -> str:
        return self.base.data_sha256

    def select(
        self, request: StudyRequest
    ) -> tuple[SpectralRoot | SpectralOverlayRoot, ...]:
        if request.target is not Capability.SPECTRAL_CORE:
            raise ValueError("spectral catalog requires target spectral-core")
        if request.theory_id != PUBLIC_THEORY_ID:
            raise ValueError(
                f"spectral catalog does not support theory_id {request.theory_id!r}"
            )
        if request.convention_id != PUBLIC_CONVENTION_ID:
            raise ValueError(
                "spectral catalog does not support convention_id "
                f"{request.convention_id!r}"
            )
        all_roots: tuple[SpectralRoot | SpectralOverlayRoot, ...] = (
            *self.base.roots,
            *self.overlay.roots,
        )
        by_key = {root.selection_key: root for root in all_roots}
        if len(by_key) != len(all_roots):
            raise ValueError("spectral union contains ambiguous selection keys")
        selected: list[SpectralRoot | SpectralOverlayRoot] = []
        requested: set[tuple[int, int, int, str]] = set()
        policy = request.numerical_policy
        if policy:
            if set(policy) != {"exact-spectral-selection"}:
                raise ValueError(
                    "spectral catalog does not accept numerical policy overrides"
                )
            selection = policy["exact-spectral-selection"]
            if not isinstance(selection, Mapping) or set(selection) != {"pairs"}:
                raise ValueError("exact spectral selection fields are invalid")
            pairs = selection["pairs"]
            if not isinstance(pairs, list) or not pairs:
                raise ValueError("exact spectral selection pairs are invalid")
            requested_pairs: tuple[tuple[ModeKey, str], ...] = tuple(
                (
                    ModeKey.from_mapping(pair["mode"]),
                    pair["spin_binary64_hex"],
                )
                for pair in pairs
                if isinstance(pair, Mapping)
                and set(pair) == {"mode", "spin_binary64_hex"}
                and isinstance(pair["spin_binary64_hex"], str)
            )
            if len(requested_pairs) != len(pairs):
                raise ValueError("exact spectral selection pair is invalid")
            allowed_modes = {canonical_json_bytes(mode.to_mapping()) for mode in request.modes}
            allowed_spins = {float(spin).hex() for spin in request.spins}
            if any(
                canonical_json_bytes(mode.to_mapping()) not in allowed_modes
                or spin_hex not in allowed_spins
                for mode, spin_hex in requested_pairs
            ):
                raise ValueError("exact spectral selection is outside the request")
        else:
            requested_pairs = tuple(
                (mode, float(spin).hex())
                for mode in request.modes
                for spin in request.spins
            )
        for mode, spin_hex in requested_pairs:
            if (
                mode.s != -2
                or mode.branch != PUBLIC_BRANCH_ID
                or mode.polarization != PUBLIC_POLARIZATION_ID
            ):
                raise ValueError("catalog has no exact root for the requested mode")
            key = (mode.ell, mode.m, mode.n, spin_hex)
            if key in requested:
                raise ValueError("duplicate mode-spin pair in spectral request")
            requested.add(key)
            root = by_key.get(key)
            if root is None:
                raise ValueError("catalog has no exact root for requested mode-spin pair")
            selected.append(root)
        return tuple(selected)


@lru_cache(maxsize=1)
def load_spectrum_catalog() -> SpectralCatalogUnion:
    return SpectralCatalogUnion(
        base=load_base_spectrum_catalog(), overlay=load_overlay_catalog()
    )


def build_spectral_payload(request: StudyRequest) -> dict[str, object]:
    catalog = load_spectrum_catalog()
    selected = catalog.select(request)
    provenance = _plain_json(load_catalog_receipt())
    if not isinstance(provenance, dict):
        raise ValueError("lattice provenance receipt must be an object")
    overlay_provenance = _plain_json(load_overlay_receipt())
    if not isinstance(overlay_provenance, dict):
        raise ValueError("overlay provenance receipt must be an object")
    provenance["m02_sparse_overlay"] = overlay_provenance
    scope = catalog.scope.to_mapping()
    scope["m02_sparse_overlay"] = {
        "root_count": 44,
        "selection_union_count_for_b_prime": 87,
        "external_comparison_count": 0,
        "base_root_count": 2736,
    }
    validation = catalog.validation.to_mapping()
    validation["m02_sparse_overlay"] = _plain_json(
        _mapping(
            load_overlay_receipt().get("validation"), "overlay validation"
        )
    )
    return {
        "schema_version": 1,
        "catalog_id": f"{CATALOG_ID}-plus-{OVERLAY_ID}",
        "delivery_mode": "computed-base-plus-sparse-overlay-exact-selection",
        "catalog_data_sha256": catalog.data_sha256,
        "overlay_data_sha256": catalog.overlay.data_sha256,
        "physics_contract": {
            "spin_weight": -2,
            "boundary_conditions": {
                "horizon": "ingoing",
                "infinity": "outgoing",
            },
            "time_dependence": "exp(-i omega t)",
            "frequency_units": "Momega",
            "angular_eigenvalue": "A",
            "pure_kerr": True,
        },
        "provenance": provenance,
        "scope": scope,
        "validation": validation,
        "requested_root_count": len(selected),
        "roots": [root.to_mapping() for root in selected],
    }


def validate_spectral_payload(
    request: StudyRequest,
    provider: Mapping[str, object],
    payload: Mapping[str, object],
) -> None:
    try:
        actual_provider = canonical_json_bytes(_plain_json(provider))
        expected_provider = canonical_json_bytes(
            SpectralCatalogProvider.descriptor.to_mapping()
        )
    except (RecursionError, TypeError, ValueError) as error:
        raise ValueError("spectral artifact provider contract is invalid") from error
    if actual_provider != expected_provider:
        raise ValueError("spectral artifact provider contract is invalid")
    try:
        actual_payload = canonical_json_bytes(_plain_json(payload))
        expected_payload = canonical_json_bytes(build_spectral_payload(request))
    except (RecursionError, TypeError, ValueError) as error:
        raise ValueError("spectral artifact payload is not canonical JSON") from error
    if actual_payload != expected_payload:
        raise ValueError(
            "spectral artifact payload does not match the admitted catalog"
        )


class SpectralCatalogProvider:
    descriptor = ProviderDescriptor(
        capability=Capability.SPECTRAL_CORE,
        provider_id=SPECTRAL_PROVIDER_ID,
        implementation_version=SPECTRAL_PROVIDER_IMPLEMENTATION_VERSION,
        equations_id=SPECTRAL_EQUATIONS_ID,
        conventions_id=PUBLIC_CONVENTION_ID,
        runtime_fingerprint=f"cpython-{platform.python_version()}-stdlib-csv",
        numerical_policy_fingerprint=SPECTRAL_POLICY_FINGERPRINT,
        upstream_artifact_types=("problem-contract",),
        output_artifact_type=SPECTRAL_OUTPUT_ARTIFACT_TYPE,
        available=True,
        evidence_level=SPECTRAL_EVIDENCE_LEVEL,
    )

    def execute(
        self, request: StudyRequest, upstream: Mapping[Capability, object]
    ) -> ProviderResult:
        if set(upstream) != {Capability.PROBLEM_CONTRACT}:
            raise ValueError(
                "spectral catalog requires one problem-contract artifact"
            )
        return ProviderResult(
            payload=build_spectral_payload(request),
            evidence=EvidenceState(
                carrier=CarrierState.VALID,
                execution=ExecutionState.SUCCEEDED,
                numerical=NumericalState.ACCEPTED,
                scientific=ScientificState.NOT_EVALUATED,
            ),
        )
