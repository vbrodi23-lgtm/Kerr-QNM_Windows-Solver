#!/usr/bin/env python3
"""Compute the exact 2,736-row pure-Kerr QNM lattice offline.

qnm supplies Schwarzschild-labelled branch continuation.  Every requested
branch seed is then polished by the project's canonical Leaver determinant;
only that canonical-backend result is serialized.  The installed solver never
imports this module or its numerical dependencies.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from fractions import Fraction
import hashlib
from importlib import metadata
from importlib import util as importlib_util
import io
import json
import math
import os
from pathlib import Path
import platform
import sys
import tempfile
from typing import Iterable, Mapping, Sequence
import zipfile

try:
    from . import kerr_angular, kerr_cf_solver
except ImportError:  # pragma: no cover - direct script execution
    import kerr_angular
    import kerr_cf_solver


ARCHIVE_NAME = "KerrQNMEFs-2.zip"
ARCHIVE_SIZE_BYTES = 60_243_941
ARCHIVE_MD5 = "4f14846fa2205f3409bf6f1e1ec3120c"
ARCHIVE_SHA256 = (
    "9a096cdcf873039baaac66fe0194f64c430df17125713a16d8f546129ef238fa"
)
SOURCE_RECORD_URL = "https://zenodo.org/records/14380191"
SOURCE_VERSION_DOI = "10.5281/zenodo.14380191"
SOURCE_CONCEPT_DOI = "10.5281/zenodo.12696857"
SOURCE_PUBLICATION_DOI = "10.1103/PhysRevLett.134.141401"
SOURCE_ARXIV = "2407.15191"
SOURCE_VERSION = "0.2.0"
SOURCE_LICENSE = "CC-BY-4.0"
MAXIMUM_SOURCE_MEMBER_BYTES = 1_000_000

CANONICAL_SOURCE_COMMIT = "0c1e8a3d3bca6e608c34e111476a4f6dcb73e86e"
CANONICAL_CF_SOURCE_BLOB = "ffb17a6be8e15da3bbce21f6c5f66420b251b077"
CANONICAL_ANGULAR_SOURCE_BLOB = "5d7641b349c4a1e1428629593cb2c81c441279a7"
CANONICAL_BACKEND_LICENSE = "MIT"
CANONICAL_BACKEND_LICENSE_SHA256 = (
    "9d077724a197b552d3fc7547b8f7ef8a781387fab6e687fc312f14e28a9928f4"
)
QNM_VERSION = "0.4.4"
QNM_WHEEL_SHA256 = (
    "63711c37ff4847c8cb59e6266da5baf81f88cc6ab728f40fc3fe39a3025f6252"
)
QNM_WHEEL_SIZE_BYTES = 95_563
QNM_SOURCE_URL = "https://github.com/duetosymmetry/qnm"
QNM_JOSS_DOI = "10.21105/joss.01683"
QNM_LICENSE = "MIT"
QNM_LICENSE_SHA256 = (
    "da080a799bd23a0d461e6a33896e4a40f2e5c033e15882a64a3f76f397d20731"
)

SPIN_WEIGHT = -2
BRANCH_ID = "schwarzschild-overtone-continuation"
ANGULAR_PADDING = 20
ANGULAR_REFINEMENT_PADDING = 24
ROOT_TOLERANCE = 1e-10
REPEAT_ROOT_TOLERANCE = 1e-12
QNM_ROOT_TOLERANCE = math.sqrt(sys.float_info.epsilon)
QNM_CF_TOLERANCE = 1e-14
QNM_MINIMUM_FRACTION_TERMS = 1000
QNM_MAXIMUM_FRACTION_TERMS = 60_000
QNM_ANGULAR_L_MAX = 24
QNM_CONTINUATION_STEP_MAXIMUM = 0.004
QNM_CONTINUATION_STEP_MINIMUM = 1e-5

MAXIMUM_OPTIMIZER_RESIDUAL_ABS = 1e-8
MAXIMUM_CONTINUED_FRACTION_ERROR = 1e-9
MAXIMUM_ANGULAR_REFINEMENT_ABS = 1e-9
MAXIMUM_REPEAT_POLISH_DELTA_ABS = 1e-9
MAXIMUM_BRANCH_SEED_DELTA_ABS = 5e-9
MAXIMUM_BRANCH_SEED_OPTIMIZER_RESIDUAL_ABS = 1e-8
MAXIMUM_REFERENCE_DELTA_OMEGA_M = 5e-9
MAXIMUM_REFERENCE_DELTA_A = 1e-8
MINIMUM_OVERTONE_SEPARATION_ABS = 1e-6

MODES = tuple(
    (ell, m, n)
    for ell in (2, 3, 4)
    for m in range(-ell, ell + 1)
    for n in range(3)
)

OUTPUT_COLUMNS = (
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


@dataclass(frozen=True, slots=True)
class LatticePoint:
    ell: int
    m: int
    n: int
    chi: Fraction
    grid_family: str
    grid_index: int

    @property
    def key(self) -> tuple[int, int, int, int, int]:
        return (
            self.ell,
            self.m,
            self.n,
            self.chi.numerator,
            self.chi.denominator,
        )


@dataclass(frozen=True, slots=True)
class BranchSeed:
    point: LatticePoint
    omega: complex
    angular_a: complex
    optimizer_residual_abs: float


@dataclass(frozen=True, slots=True)
class SourceValue:
    member: str
    row: int
    omega_m: complex
    angular_a: complex


def spins_for_ell(ell: int) -> tuple[Fraction, ...]:
    if ell in (2, 3):
        base = {Fraction(19 * index, 780) for index in range(40)}
        supplemental = {
            Fraction(97, 100),
            Fraction(49, 50),
            Fraction(99, 100),
            Fraction(199, 200),
            Fraction(997, 1000),
            Fraction(999, 1000),
        }
        return tuple(sorted(base | supplemental))
    if ell == 4:
        return tuple(Fraction(index, 52) for index in range(40))
    raise ValueError(f"unsupported ell: {ell}")


def _grid_identity(ell: int, chi: Fraction) -> tuple[str, int]:
    spins = spins_for_ell(ell)
    index = spins.index(chi)
    if ell in (2, 3) and chi not in {
        Fraction(19 * item, 780) for item in range(40)
    }:
        return "ell23-supplemental-high", index
    return ("ell23-uniform-40" if ell in (2, 3) else "ell4-uniform-40", index)


def lattice_points() -> tuple[LatticePoint, ...]:
    points: list[LatticePoint] = []
    for ell, m, n in MODES:
        for chi in spins_for_ell(ell):
            family, index = _grid_identity(ell, chi)
            points.append(LatticePoint(ell, m, n, chi, family, index))
    return tuple(points)


def _digest(data: bytes, algorithm: str = "sha256") -> str:
    return hashlib.new(algorithm, data).hexdigest()


def _member_name(ell: int, m: int, n: int) -> str:
    return f"KerrQNMEFs-2/l{ell}/s-2l{ell}m{m}n{n}.dat"


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8") + b"\n"


def _finite_complex(value: complex) -> bool:
    return math.isfinite(value.real) and math.isfinite(value.imag)


def _float_text(value: float) -> str:
    if not math.isfinite(value):
        raise ValueError("non-finite value cannot be serialized")
    return repr(float(value))


def _parse_source_member(
    data: bytes, member_name: str
) -> dict[Fraction, SourceValue]:
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as error:
        raise ValueError(f"source member is not ASCII: {member_name}") from error
    selected: dict[Fraction, SourceValue] = {}
    for row_number, line in enumerate(text.splitlines(), start=1):
        columns = tuple(item.strip() for item in line.split(","))
        if len(columns) != 9:
            raise ValueError(
                f"source member {member_name} row {row_number} has "
                f"{len(columns)} columns"
            )
        try:
            numeric = tuple(Decimal(item) for item in columns[:5])
        except InvalidOperation as error:
            raise ValueError(
                f"source member {member_name} row {row_number} is not decimal"
            ) from error
        if not all(value.is_finite() for value in numeric):
            raise ValueError(
                f"source member {member_name} row {row_number} is non-finite"
            )
        chi = Fraction(numeric[0])
        if chi in selected:
            raise ValueError(f"duplicate source spin {chi} in {member_name}")
        with localcontext() as context:
            context.prec = 80
            omega_m = complex(float(numeric[1] / 2), float(numeric[2] / 2))
        selected[chi] = SourceValue(
            member=member_name,
            row=row_number,
            omega_m=omega_m,
            angular_a=complex(float(numeric[3]), float(numeric[4])),
        )
    return selected


def _authenticate_source(
    archive_bytes: bytes,
) -> tuple[
    dict[tuple[int, int, int, Fraction], SourceValue],
    dict[str, str],
]:
    if len(archive_bytes) != ARCHIVE_SIZE_BYTES:
        raise ValueError("source archive size does not match release v0.2.0")
    if _digest(archive_bytes, "md5") != ARCHIVE_MD5:
        raise ValueError("source archive MD5 does not match release v0.2.0")
    if _digest(archive_bytes) != ARCHIVE_SHA256:
        raise ValueError("source archive SHA-256 does not match release v0.2.0")
    values: dict[tuple[int, int, int, Fraction], SourceValue] = {}
    member_hashes: dict[str, str] = {}
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        names = [item.filename for item in archive.infolist()]
        for ell, m, n in MODES:
            member_name = _member_name(ell, m, n)
            if names.count(member_name) != 1:
                raise ValueError(
                    f"source archive must contain {member_name} exactly once"
                )
            info = archive.getinfo(member_name)
            if info.flag_bits & 0x1:
                raise ValueError(f"source member is encrypted: {member_name}")
            if info.file_size > MAXIMUM_SOURCE_MEMBER_BYTES:
                raise ValueError(f"source member is oversized: {member_name}")
            data = archive.read(info)
            member_hashes[member_name] = _digest(data)
            for chi, source in _parse_source_member(data, member_name).items():
                values[(ell, m, n, chi)] = source
    return values, member_hashes


def _authenticate_qnm_installation(wheel_bytes: bytes) -> None:
    if _digest(wheel_bytes) != QNM_WHEEL_SHA256:
        raise ValueError("qnm wheel SHA-256 does not match the pinned release")
    try:
        distribution = metadata.distribution("qnm")
    except metadata.PackageNotFoundError as error:
        raise RuntimeError("qnm is not installed for offline generation") from error
    if distribution.version != QNM_VERSION:
        raise RuntimeError(
            f"qnm version {distribution.version} is not the pinned {QNM_VERSION}"
        )
    with zipfile.ZipFile(io.BytesIO(wheel_bytes)) as wheel:
        members = {
            name: wheel.read(name)
            for name in wheel.namelist()
            if name.startswith("qnm/") and not name.endswith("/")
        }
    if not members:
        raise ValueError("qnm wheel does not contain package files")
    for member, expected in members.items():
        installed = Path(distribution.locate_file(member)).resolve()
        if not installed.is_file() or installed.read_bytes() != expected:
            raise ValueError(f"installed qnm file does not match wheel: {member}")
    if any(name == "qnm" or name.startswith("qnm.") for name in sys.modules):
        raise ValueError("qnm must not be imported before package authentication")
    expected_init = Path(distribution.locate_file("qnm/__init__.py")).resolve()
    spec = importlib_util.find_spec("qnm")
    if spec is None or spec.origin is None:
        raise ValueError("authenticated qnm package has no import origin")
    actual_init = Path(spec.origin).resolve()
    locations = tuple(
        Path(location).resolve()
        for location in (spec.submodule_search_locations or ())
    )
    if actual_init != expected_init or locations != (expected_init.parent,):
        raise ValueError("qnm import origin resolves to a shadow package")


def _qnm_branch_seeds(wheel_bytes: bytes) -> tuple[BranchSeed, ...]:
    _authenticate_qnm_installation(wheel_bytes)
    try:
        import numpy as np
        from qnm import radial
        from qnm.spinsequence import KerrSpinSeq
    except ImportError as error:
        raise RuntimeError(
            "offline lattice generation requires qnm 0.4.4 and its dependencies"
        ) from error
    try:
        installed_qnm = metadata.version("qnm")
    except metadata.PackageNotFoundError as error:
        raise RuntimeError("qnm distribution metadata is unavailable") from error
    if installed_qnm != QNM_VERSION:
        raise RuntimeError(
            f"qnm version {installed_qnm} is not the pinned {QNM_VERSION}"
        )

    seeds: list[BranchSeed] = []
    for ell, m, n in MODES:
        targets = spins_for_ell(ell)
        sequence = KerrSpinSeq(
            a_max=float(targets[-1]),
            delta_a=QNM_CONTINUATION_STEP_MAXIMUM,
            delta_a_min=QNM_CONTINUATION_STEP_MINIMUM,
            delta_a_max=QNM_CONTINUATION_STEP_MAXIMUM,
            s=SPIN_WEIGHT,
            l=ell,
            m=m,
            n=n,
            l_max=QNM_ANGULAR_L_MAX,
            tol=QNM_ROOT_TOLERANCE,
            cf_tol=QNM_CF_TOLERANCE,
            Nr=QNM_MINIMUM_FRACTION_TERMS,
            Nr_max=QNM_MAXIMUM_FRACTION_TERMS,
        )
        sequence.solver.set_params(
            cf_tol=QNM_CF_TOLERANCE,
            Nr=QNM_MINIMUM_FRACTION_TERMS,
            Nr_min=QNM_MINIMUM_FRACTION_TERMS,
            Nr_max=QNM_MAXIMUM_FRACTION_TERMS,
        )
        sequence.do_find_sequence()
        for chi in targets:
            chi_float = float(chi)
            omega, angular_a, _ = sequence(
                chi_float,
                store=False,
                interp_only=False,
                resolve_if_found=True,
            )
            optimizer = sequence.solver.opt_res
            residual = math.hypot(
                float(optimizer.fun[0]), float(optimizer.fun[1])
            )
            radial_value, _, _ = radial.leaver_cf_inv_lentz(
                omega,
                chi_float,
                SPIN_WEIGHT,
                m,
                angular_a,
                n,
                QNM_CF_TOLERANCE,
                QNM_MINIMUM_FRACTION_TERMS,
                QNM_MAXIMUM_FRACTION_TERMS,
            )
            residual = max(residual, float(abs(radial_value)))
            family, index = _grid_identity(ell, chi)
            seeds.append(
                BranchSeed(
                    point=LatticePoint(ell, m, n, chi, family, index),
                    omega=complex(omega),
                    angular_a=complex(angular_a),
                    optimizer_residual_abs=residual,
                )
            )
    return tuple(seeds)


def _canonical_rows(seeds: Sequence[BranchSeed]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    by_tower: dict[tuple[int, int, Fraction], list[complex]] = {}
    for seed in seeds:
        point = seed.point
        chi_float = float(point.chi)
        solved = kerr_cf_solver.solve_mode(
            chi_float,
            SPIN_WEIGHT,
            point.ell,
            point.m,
            point.n,
            seed.omega,
            angular_padding=ANGULAR_PADDING,
            tolerance=ROOT_TOLERANCE,
        )
        (
            omega,
            angular_a,
            residual,
            cf_error,
            cf_terms,
            solver_success,
            _,
        ) = solved
        if not solver_success:
            raise ValueError(
                "canonical root solver did not report success for "
                f"(ell={point.ell}, m={point.m}, n={point.n}, chi={point.chi})"
            )
        _, refined_a, _, _ = kerr_cf_solver.coupled_error(
            omega,
            chi_float,
            SPIN_WEIGHT,
            point.ell,
            point.m,
            point.n,
            ANGULAR_REFINEMENT_PADDING,
        )
        repeat = kerr_cf_solver.solve_mode(
            chi_float,
            SPIN_WEIGHT,
            point.ell,
            point.m,
            point.n,
            omega,
            angular_padding=ANGULAR_PADDING,
            tolerance=REPEAT_ROOT_TOLERANCE,
        )
        if not repeat[5]:
            raise ValueError(
                "canonical repeat root solver did not report success for "
                f"(ell={point.ell}, m={point.m}, n={point.n}, chi={point.chi})"
            )
        tower_key = (point.ell, point.m, point.chi)
        earlier = by_tower.setdefault(tower_key, [])
        separation = min(
            (abs(omega - other) for other in earlier), default=math.inf
        )
        earlier.append(omega)
        rows.append(
            {
                "s": SPIN_WEIGHT,
                "ell": point.ell,
                "m": point.m,
                "n": point.n,
                "branch_id": BRANCH_ID,
                "chi_grid_family": point.grid_family,
                "chi_grid_index": point.grid_index,
                "chi_numerator": point.chi.numerator,
                "chi_denominator": point.chi.denominator,
                "chi_float": _float_text(chi_float),
                "chi_float_hex": chi_float.hex(),
                "omega_re_M": _float_text(omega.real),
                "omega_im_M": _float_text(omega.imag),
                "angular_A_re": _float_text(angular_a.real),
                "angular_A_im": _float_text(angular_a.imag),
                "root_solver_success": str(bool(solver_success)).lower(),
                "optimizer_residual_abs": _float_text(residual),
                "continued_fraction_error": _float_text(cf_error),
                "continued_fraction_terms": cf_terms,
                "angular_padding": ANGULAR_PADDING,
                "angular_refinement_padding": ANGULAR_REFINEMENT_PADDING,
                "angular_refinement_abs": _float_text(abs(refined_a - angular_a)),
                "repeat_polish_delta_abs": _float_text(abs(repeat[0] - omega)),
                "branch_seed_delta_abs": _float_text(abs(omega - seed.omega)),
                "branch_seed_optimizer_residual_abs": _float_text(
                    seed.optimizer_residual_abs
                ),
                "continuation_step_maximum": _float_text(
                    QNM_CONTINUATION_STEP_MAXIMUM
                ),
                "nearest_overtone_separation_abs": (
                    "" if math.isinf(separation) else _float_text(separation)
                ),
                "reference_member": "",
                "reference_row": "",
                "reference_abs_delta_omega_M": "",
                "reference_abs_delta_A": "",
            }
        )
    return rows


def _attach_source_comparisons(
    rows: list[dict[str, object]],
    source: Mapping[tuple[int, int, int, Fraction], SourceValue],
) -> dict[str, object]:
    comparisons = 0
    max_omega = 0.0
    max_a = 0.0
    by_ell = {2: 0, 3: 0, 4: 0}
    for row in rows:
        chi = Fraction(int(row["chi_numerator"]), int(row["chi_denominator"]))
        key = (int(row["ell"]), int(row["m"]), int(row["n"]), chi)
        reference = source.get(key)
        if reference is None:
            continue
        omega = complex(float(row["omega_re_M"]), float(row["omega_im_M"]))
        angular_a = complex(
            float(row["angular_A_re"]), float(row["angular_A_im"])
        )
        delta_omega = abs(omega - reference.omega_m)
        delta_a = abs(angular_a - reference.angular_a)
        row["reference_member"] = reference.member
        row["reference_row"] = reference.row
        row["reference_abs_delta_omega_M"] = _float_text(delta_omega)
        row["reference_abs_delta_A"] = _float_text(delta_a)
        comparisons += 1
        by_ell[int(row["ell"])] += 1
        max_omega = max(max_omega, delta_omega)
        max_a = max(max_a, delta_a)
    return {
        "comparison_count": comparisons,
        "comparisons_by_ell": {str(key): value for key, value in by_ell.items()},
        "maximum_abs_delta_omega_M": max_omega,
        "maximum_abs_delta_A": max_a,
    }


def _validate_rows(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    expected = tuple(point.key for point in lattice_points())
    keys: list[tuple[int, int, int, int, int]] = []
    maxima = {
        "optimizer_residual_abs": 0.0,
        "continued_fraction_error": 0.0,
        "angular_refinement_abs": 0.0,
        "repeat_polish_delta_abs": 0.0,
        "branch_seed_delta_abs": 0.0,
        "branch_seed_optimizer_residual_abs": 0.0,
    }
    for index, row in enumerate(rows, start=1):
        key = (
            int(row["ell"]),
            int(row["m"]),
            int(row["n"]),
            int(row["chi_numerator"]),
            int(row["chi_denominator"]),
        )
        chi = Fraction(key[3], key[4])
        if (chi.numerator, chi.denominator) != (key[3], key[4]):
            raise ValueError(f"row {index} chi is not a reduced rational")
        chi_float = float(chi)
        if float(row["chi_float"]) != chi_float:
            raise ValueError(f"row {index} chi float does not match rational key")
        if float.fromhex(str(row["chi_float_hex"])) != chi_float:
            raise ValueError(f"row {index} chi hex does not match rational key")
        values = (
            float(row["omega_re_M"]),
            float(row["omega_im_M"]),
            float(row["angular_A_re"]),
            float(row["angular_A_im"]),
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"row {index} contains a non-finite root field")
        if values[1] >= 0:
            raise ValueError(f"row {index} is not a damped QNM")
        if row["root_solver_success"] != "true":
            raise ValueError(f"row {index} did not pass the root solver gate")
        if int(row["s"]) != SPIN_WEIGHT or row["branch_id"] != BRANCH_ID:
            raise ValueError(f"row {index} has invalid mode metadata")
        expected_family, expected_grid_index = _grid_identity(int(row["ell"]), chi)
        if (
            row["chi_grid_family"] != expected_family
            or int(row["chi_grid_index"]) != expected_grid_index
        ):
            raise ValueError(f"row {index} has invalid spin-grid metadata")
        if (
            int(row["continued_fraction_terms"])
            < QNM_MINIMUM_FRACTION_TERMS
            or int(row["continued_fraction_terms"])
            >= QNM_MAXIMUM_FRACTION_TERMS
        ):
            raise ValueError(f"row {index} has invalid continued-fraction depth")
        seed_residual = float(row["branch_seed_optimizer_residual_abs"])
        if (
            not math.isfinite(seed_residual)
            or seed_residual < 0
            or seed_residual > MAXIMUM_BRANCH_SEED_OPTIMIZER_RESIDUAL_ABS
        ):
            raise ValueError(f"row {index} has an invalid branch-seed residual")
        if (
            int(row["angular_padding"]) != ANGULAR_PADDING
            or int(row["angular_refinement_padding"])
            != ANGULAR_REFINEMENT_PADDING
            or float(row["continuation_step_maximum"])
            != QNM_CONTINUATION_STEP_MAXIMUM
        ):
            raise ValueError(f"row {index} has invalid numerical-policy metadata")
        separation = row["nearest_overtone_separation_abs"]
        if int(row["n"]) == 0:
            if separation != "":
                raise ValueError(f"row {index} has an invalid overtone separation")
        elif (
            separation == ""
            or not math.isfinite(float(separation))
            or float(separation) < MINIMUM_OVERTONE_SEPARATION_ABS
        ):
            raise ValueError(f"row {index} has an overtone branch collision")
        for field in maxima:
            value = float(row[field])
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"row {index} has an invalid {field}")
            maxima[field] = max(maxima[field], value)
        keys.append(key)
    if tuple(keys) != expected:
        raise ValueError("computed rows do not match the canonical lattice order")
    if len(set(keys)) != 2736:
        raise ValueError("computed lattice does not contain 2,736 unique keys")
    ceilings = {
        "optimizer_residual_abs": MAXIMUM_OPTIMIZER_RESIDUAL_ABS,
        "continued_fraction_error": MAXIMUM_CONTINUED_FRACTION_ERROR,
        "angular_refinement_abs": MAXIMUM_ANGULAR_REFINEMENT_ABS,
        "repeat_polish_delta_abs": MAXIMUM_REPEAT_POLISH_DELTA_ABS,
        "branch_seed_delta_abs": MAXIMUM_BRANCH_SEED_DELTA_ABS,
        "branch_seed_optimizer_residual_abs": (
            MAXIMUM_BRANCH_SEED_OPTIMIZER_RESIDUAL_ABS
        ),
    }
    for field, ceiling in ceilings.items():
        if maxima[field] > ceiling:
            raise ValueError(
                f"computed lattice {field} exceeds its threshold: "
                f"{maxima[field]} > {ceiling}"
            )
    return {"observed_maxima": maxima, "ceilings": ceilings}


def _catalog_bytes(rows: Sequence[Mapping[str, object]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=OUTPUT_COLUMNS,
        lineterminator="\n",
        extrasaction="raise",
    )
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _dependency_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in ("numpy", "scipy", "numba", "qnm"):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = "not-installed"
    return versions


def compute_lattice(
    archive_bytes: bytes, *, qnm_wheel_bytes: bytes
) -> tuple[bytes, bytes]:
    """Return complete canonical CSV and receipt bytes or fail without output."""

    source, member_hashes = _authenticate_source(archive_bytes)
    seeds = _qnm_branch_seeds(qnm_wheel_bytes)
    if tuple(seed.point for seed in seeds) != lattice_points():
        raise ValueError("branch tracker did not return the exact lattice order")
    rows = _canonical_rows(seeds)
    comparison = _attach_source_comparisons(rows, source)
    validation = _validate_rows(rows)
    if comparison["comparison_count"] != 392:
        raise ValueError("independent comparison coverage is not 392 exact rows")
    if comparison["maximum_abs_delta_omega_M"] > MAXIMUM_REFERENCE_DELTA_OMEGA_M:
        raise ValueError("independent frequency comparison exceeds its threshold")
    if comparison["maximum_abs_delta_A"] > MAXIMUM_REFERENCE_DELTA_A:
        raise ValueError("independent angular comparison exceeds its threshold")
    catalog = _catalog_bytes(rows)
    generator_path = Path(__file__)
    receipt = {
        "backend": {
            "branch_tracker": {
                "name": "qnm",
                "version": QNM_VERSION,
                "wheel_sha256": QNM_WHEEL_SHA256,
                "role": "branch-labelled seed generation only",
                "angular_seed_role": (
                    "not used; catalog A is recomputed by the canonical backend "
                    "and compared at the 392 exact Motohashi overlaps"
                ),
                "package_files_authenticated_before_import": True,
                "source_url": QNM_SOURCE_URL,
                "joss_doi": QNM_JOSS_DOI,
                "license": QNM_LICENSE,
                "license_sha256": QNM_LICENSE_SHA256,
            },
            "canonical_angular": {
                "migrated_source_blob": CANONICAL_ANGULAR_SOURCE_BLOB,
                "module_sha256": _digest(Path(kerr_angular.__file__).read_bytes()),
            },
            "canonical_backend_license": {
                "license": CANONICAL_BACKEND_LICENSE,
                "path": (
                    "src/windows_solver/data/"
                    "LICENSE-CANONICAL-BACKEND-MIT.txt"
                ),
                "sha256": CANONICAL_BACKEND_LICENSE_SHA256,
                "scope": "offline canonical numerical backend only",
            },
            "canonical_continued_fraction": {
                "migrated_source_blob": CANONICAL_CF_SOURCE_BLOB,
                "module_sha256": _digest(Path(kerr_cf_solver.__file__).read_bytes()),
                "role": "stored exact-node determinant polish",
                "continued_fraction_tolerance": (
                    kerr_cf_solver.CONTINUED_FRACTION_TOLERANCE
                ),
                "continued_fraction_minimum_terms": (
                    kerr_cf_solver.CONTINUED_FRACTION_MINIMUM_TERMS
                ),
                "continued_fraction_maximum_terms": (
                    kerr_cf_solver.CONTINUED_FRACTION_MAXIMUM_TERMS
                ),
            },
            "canonical_source_commit": CANONICAL_SOURCE_COMMIT,
        },
        "catalog": {
            "columns": list(OUTPUT_COLUMNS),
            "line_endings": "LF",
            "row_count_excluding_header": len(rows),
            "sha256": _digest(catalog),
        },
        "generator": {
            "path": "tools/compute_kerr_qnm_lattice.py",
            "sha256": _digest(generator_path.read_bytes()),
        },
        "lattice": {
            "mode_rule": {
                "ell": [2, 3, 4],
                "m": "every integer from -ell through +ell",
                "n": [0, 1, 2],
            },
            "mode_count": 63,
            "ordering": ["ell", "m", "n", "chi_exact"],
            "root_count": 2736,
            "roots_by_ell": {"2": 690, "3": 966, "4": 1080},
            "spin_points_by_ell": {"2": 46, "3": 46, "4": 40},
            "spin_grid_rationals_by_ell": {
                str(ell): [
                    [spin.numerator, spin.denominator]
                    for spin in spins_for_ell(ell)
                ]
                for ell in (2, 3, 4)
            },
            "spin_weight": SPIN_WEIGHT,
        },
        "numerical_policy": {
            "angular_padding": ANGULAR_PADDING,
            "angular_refinement_padding": ANGULAR_REFINEMENT_PADDING,
            "branch_id": BRANCH_ID,
            "boundary_conditions": {
                "horizon": "ingoing",
                "infinity": "outgoing",
            },
            "canonical_root_tolerance": ROOT_TOLERANCE,
            "canonical_repeat_root_tolerance": REPEAT_ROOT_TOLERANCE,
            "frequency_units": "Momega",
            "formal_root_enclosure": False,
            "minimum_overtone_separation_abs": (
                MINIMUM_OVERTONE_SEPARATION_ABS
            ),
            "qnm_angular_l_max": QNM_ANGULAR_L_MAX,
            "qnm_cf_tolerance": QNM_CF_TOLERANCE,
            "qnm_continuation_step_maximum": QNM_CONTINUATION_STEP_MAXIMUM,
            "qnm_continuation_step_minimum": QNM_CONTINUATION_STEP_MINIMUM,
            "qnm_fraction_maximum_terms": QNM_MAXIMUM_FRACTION_TERMS,
            "qnm_fraction_minimum_terms": QNM_MINIMUM_FRACTION_TERMS,
            "qnm_root_tolerance": QNM_ROOT_TOLERANCE,
            "spin_weight": SPIN_WEIGHT,
            "stored_value_source": "canonical determinant polish",
            "time_dependence": "exp(-i omega t)",
        },
        "runtime": {
            "dependencies": _dependency_versions(),
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "schema_version": 1,
        "source_comparison": {
            **comparison,
            "archive_md5": ARCHIVE_MD5,
            "archive_sha256": ARCHIVE_SHA256,
            "associated_arxiv": SOURCE_ARXIV,
            "associated_publication_doi": SOURCE_PUBLICATION_DOI,
            "concept_doi": SOURCE_CONCEPT_DOI,
            "license": SOURCE_LICENSE,
            "acceptance_ceilings": {
                "absolute_delta_A": MAXIMUM_REFERENCE_DELTA_A,
                "absolute_delta_omega_M": MAXIMUM_REFERENCE_DELTA_OMEGA_M,
            },
            "member_sha256": member_hashes,
            "record_url": SOURCE_RECORD_URL,
            "version": SOURCE_VERSION,
            "version_doi": SOURCE_VERSION_DOI,
        },
        "validation": {
            **validation,
            "finite_count": 2736,
            "damped_count": 2736,
            "failure_count": 0,
            "independent_comparison": comparison,
            "scientific_state": "NOT_EVALUATED",
        },
    }
    return catalog, _canonical_json_bytes(receipt)


def compute_lattice_from_path(
    path: Path, qnm_wheel_path: Path
) -> tuple[bytes, bytes]:
    if path.stat().st_size != ARCHIVE_SIZE_BYTES:
        raise ValueError("source archive size does not match release v0.2.0")
    if qnm_wheel_path.stat().st_size != QNM_WHEEL_SIZE_BYTES:
        raise ValueError("qnm wheel size does not match the pinned release")
    return compute_lattice(
        path.read_bytes(), qnm_wheel_bytes=qnm_wheel_path.read_bytes()
    )


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


def _atomic_write_pair(
    catalog_path: Path,
    receipt_path: Path,
    catalog: bytes,
    receipt: bytes,
) -> None:
    if catalog_path.resolve() == receipt_path.resolve():
        raise ValueError("catalog and receipt outputs must be different paths")
    old_catalog = catalog_path.read_bytes() if catalog_path.is_file() else None
    catalog_temporary = _write_temporary(catalog_path, catalog)
    receipt_temporary: Path | None = None
    try:
        receipt_temporary = _write_temporary(receipt_path, receipt)
        os.replace(catalog_temporary, catalog_path)
        try:
            os.replace(receipt_temporary, receipt_path)
        except BaseException:
            if old_catalog is None:
                catalog_path.unlink(missing_ok=True)
            else:
                rollback = _write_temporary(catalog_path, old_catalog)
                os.replace(rollback, catalog_path)
            raise
    finally:
        catalog_temporary.unlink(missing_ok=True)
        if receipt_temporary is not None:
            receipt_temporary.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--qnm-wheel", type=Path, required=True)
    parser.add_argument("--catalog-output", type=Path, required=True)
    parser.add_argument("--receipt-output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    if arguments.catalog_output.resolve() == arguments.receipt_output.resolve():
        parser.error("catalog and receipt outputs must be different paths")
    catalog, receipt = compute_lattice_from_path(
        arguments.archive, arguments.qnm_wheel
    )
    _atomic_write_pair(
        arguments.catalog_output,
        arguments.receipt_output,
        catalog,
        receipt,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
