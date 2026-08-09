"""Package-owned Julia production boundary for GSN infinity-series inputs.

This module performs orchestration and authentication only.  The mathematical
F/U expressions are produced by the packaged Julia stage from the packaged
GeneralizedSasakiNakamura.jl source equations.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Callable, Iterable, Mapping, Sequence


class GsnCacheProductionError(RuntimeError):
    """The package-owned GSN input stage could not produce a trusted cache."""


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise GsnCacheProductionError(
                f"generated GSN cache has duplicate key {key!r}"
            )
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class GsnParameterPair:
    spin_numerator: int
    spin_denominator: int
    azimuthal_index: int

    def __post_init__(self) -> None:
        if isinstance(self.spin_numerator, bool) or not isinstance(
            self.spin_numerator, int
        ):
            raise ValueError("GSN spin numerator must be an integer")
        if isinstance(self.spin_denominator, bool) or not isinstance(
            self.spin_denominator, int
        ):
            raise ValueError("GSN spin denominator must be an integer")
        if self.spin_denominator <= 0:
            raise ValueError("GSN spin denominator must be positive")
        if isinstance(self.azimuthal_index, bool) or not isinstance(
            self.azimuthal_index, int
        ):
            raise ValueError("GSN azimuthal index must be an integer")
        reduced = Fraction(self.spin_numerator, self.spin_denominator)
        if reduced < -1 or reduced > 1:
            raise ValueError("GSN spin must lie in [-1, 1]")
        object.__setattr__(self, "spin_numerator", reduced.numerator)
        object.__setattr__(self, "spin_denominator", reduced.denominator)

    @property
    def spin(self) -> Fraction:
        return Fraction(self.spin_numerator, self.spin_denominator)

    @property
    def cache_key(self) -> str:
        return f"m={self.azimuthal_index};a={float(self.spin):.15g}"

    def to_mapping(self) -> dict[str, int]:
        return {
            "spin_numerator": self.spin_numerator,
            "spin_denominator": self.spin_denominator,
            "azimuthal_index": self.azimuthal_index,
        }


@dataclass(frozen=True, slots=True)
class GeneratedGsnCache:
    artifact_id: str
    path: Path
    sha256: str
    parameter_pairs: tuple[GsnParameterPair, ...]


def _parameter_pair_for_leaf(leaf: object) -> GsnParameterPair:
    coordinate = leaf.job.sampling_coordinate
    numerator, denominator = coordinate.exact
    exact_coordinate = Fraction(numerator, denominator)
    if coordinate.transformation_id == "identity-a-over-M":
        spin = exact_coordinate
    elif coordinate.transformation_id == (
        "kerr-prograde-spin-from-dimensionless-surface-gravity"
    ):
        spin = 2 * exact_coordinate / (1 + exact_coordinate * exact_coordinate)
    else:
        raise GsnCacheProductionError(
            f"unsupported campaign spin transformation {coordinate.transformation_id!r}"
        )
    if float(spin).hex() != leaf.job.spin.hex():
        raise GsnCacheProductionError(
            "exact campaign spin identity does not reproduce the binary64 job spin"
        )
    return GsnParameterPair(spin.numerator, spin.denominator, leaf.job.mode.m)


def parameter_pairs_for_selection(
    plan: object, selection: object
) -> tuple[GsnParameterPair, ...]:
    leaf_by_id = {leaf.leaf_id: leaf for leaf in plan.leaves}
    pairs: list[GsnParameterPair] = []
    seen: set[GsnParameterPair] = set()
    for leaf_id in selection.leaf_ids:
        try:
            pair = _parameter_pair_for_leaf(leaf_by_id[leaf_id])
        except KeyError as error:
            raise GsnCacheProductionError(
                f"campaign selection contains unknown leaf {leaf_id!r}"
            ) from error
        if pair not in seen:
            pairs.append(pair)
            seen.add(pair)
    if not pairs:
        raise GsnCacheProductionError("campaign selection has no GSN parameter pairs")
    return tuple(pairs)


def _parameter_set_sha256(pairs: Sequence[GsnParameterPair]) -> str:
    value = {
        "schema_version": 1,
        "parameter_pairs": [pair.to_mapping() for pair in pairs],
    }
    raw = json.dumps(
        value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    return hashlib.sha256(raw).hexdigest()


def _parameter_set_mapping(
    pairs: Sequence[GsnParameterPair],
) -> list[dict[str, int]]:
    return [pair.to_mapping() for pair in pairs]


def _load_artifact_index(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"schema_version": 1, "artifacts": []}
    _validate_regular_file(path, "GSN artifact index")
    try:
        value = json.loads(
            path.read_bytes(),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda item: (_ for _ in ()).throw(
                GsnCacheProductionError(
                    f"GSN artifact index contains non-finite constant {item}"
                )
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GsnCacheProductionError("GSN artifact index is invalid JSON") from error
    if (
        not isinstance(value, Mapping)
        or set(value) != {"schema_version", "artifacts"}
        or value["schema_version"] != 1
        or not isinstance(value["artifacts"], list)
    ):
        raise GsnCacheProductionError("GSN artifact index schema is invalid")
    ids: set[str] = set()
    parameter_sets: set[str] = set()
    for row in value["artifacts"]:
        if not isinstance(row, Mapping) or set(row) != {
            "artifact_id",
            "parameter_pairs",
            "cache_path",
            "status_path",
            "journal_path",
            "receipt_path",
            "pairs_path",
            "status",
            "cache_sha256_observed",
        }:
            raise GsnCacheProductionError("GSN artifact index row is invalid")
        artifact_id = row["artifact_id"]
        if (
            not isinstance(artifact_id, str)
            or re.fullmatch(r"gsn-set-[0-9]{6}", artifact_id) is None
            or artifact_id in ids
        ):
            raise GsnCacheProductionError("GSN artifact index ID is invalid")
        ids.add(artifact_id)
        if not isinstance(row["parameter_pairs"], list):
            raise GsnCacheProductionError("GSN artifact index parameter set is invalid")
        parameter_key = json.dumps(
            row["parameter_pairs"], sort_keys=True, separators=(",", ":")
        )
        if parameter_key in parameter_sets:
            raise GsnCacheProductionError("GSN artifact index parameter set is duplicated")
        parameter_sets.add(parameter_key)
        for name in (
            "cache_path", "status_path", "journal_path", "receipt_path", "pairs_path"
        ):
            filename = row[name]
            if (
                not isinstance(filename, str)
                or Path(filename).name != filename
                or not filename.startswith(artifact_id)
            ):
                raise GsnCacheProductionError("GSN artifact index path is invalid")
        if row["status"] != "accepted":
            raise GsnCacheProductionError("GSN artifact index status is invalid")
        observed = row["cache_sha256_observed"]
        if observed is not None and (
            not isinstance(observed, str)
            or re.fullmatch(r"[0-9a-f]{64}", observed) is None
        ):
            raise GsnCacheProductionError("GSN artifact index digest metadata is invalid")
    return {"schema_version": 1, "artifacts": [dict(row) for row in value["artifacts"]]}


def _write_json(path: Path, value: Mapping[str, object]) -> None:
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(
        json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="ascii",
    )
    temporary.replace(path)


def _artifact_row(
    artifact_id: str,
    pairs: Sequence[GsnParameterPair],
    *,
    cache_sha256: str | None,
) -> dict[str, object]:
    return {
        "artifact_id": artifact_id,
        "parameter_pairs": _parameter_set_mapping(pairs),
        "cache_path": f"{artifact_id}.json",
        "status_path": f"{artifact_id}-status.csv",
        "journal_path": f"{artifact_id}-journal.jsonl",
        "receipt_path": f"{artifact_id}-receipt.json",
        "pairs_path": f"{artifact_id}-pairs.csv",
        "status": "accepted",
        "cache_sha256_observed": cache_sha256,
    }


def _validate_regular_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise GsnCacheProductionError(f"{label} is absent: {path}")
    if path.is_symlink():
        raise GsnCacheProductionError(f"{label} must not be a symlink: {path}")


def _validate_coefficient_record(value: object, key: str) -> None:
    if not isinstance(value, Mapping) or set(value) != {"F", "U"}:
        raise GsnCacheProductionError(
            f"generated GSN cache record {key!r} has invalid F/U fields"
        )
    fields = {
        "numerator_coefficients_ascending",
        "denominator_coefficients_ascending",
    }
    for name in ("F", "U"):
        series = value[name]
        if not isinstance(series, Mapping) or set(series) != fields:
            raise GsnCacheProductionError(
                f"generated GSN cache record {key!r} {name} fields are invalid"
            )
        for field in sorted(fields):
            coefficients = series[field]
            if (
                not isinstance(coefficients, list)
                or not coefficients
                or any(not isinstance(item, str) or not item for item in coefficients)
            ):
                raise GsnCacheProductionError(
                    f"generated GSN cache record {key!r} {name} {field} is invalid"
                )


def _validate_generated_cache(
    path: Path,
    pairs: Sequence[GsnParameterPair],
    potentials: Path,
) -> str:
    _validate_regular_file(path, "generated GSN infinity-series cache")
    raw = path.read_bytes()
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda item: (_ for _ in ()).throw(
                GsnCacheProductionError(
                    f"generated GSN cache contains non-finite constant {item}"
                )
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GsnCacheProductionError(
            "generated GSN infinity-series cache is invalid JSON"
        ) from error
    expected_fields = {
        "schema_version",
        "spin_weight",
        "mass_normalization",
        "source_relative_path",
        "source_sha256",
        "declared_parameter_pairs",
        "records",
    }
    if not isinstance(value, Mapping) or set(value) != expected_fields:
        raise GsnCacheProductionError("generated GSN cache document fields are invalid")
    if (
        value["schema_version"] != 1
        or value["spin_weight"] != -2
        or value["mass_normalization"] != 1
    ):
        raise GsnCacheProductionError("generated GSN cache contract is invalid")
    if value["source_relative_path"] != "src/Homogeneous/Potentials.jl":
        raise GsnCacheProductionError(
            "generated GSN cache source path is not the packaged Potentials.jl"
        )
    if (
        not isinstance(value["source_sha256"], str)
        or re.fullmatch(r"[0-9a-f]{64}", value["source_sha256"]) is None
    ):
        raise GsnCacheProductionError(
            "generated GSN cache source digest metadata is invalid"
        )
    records = value["records"]
    if not isinstance(records, Mapping) or set(records) != {
        pair.cache_key for pair in pairs
    }:
        raise GsnCacheProductionError(
            "generated GSN cache records do not exactly match the requested pairs"
        )
    declared = value["declared_parameter_pairs"]
    expected_declared = [
        {"spin": float(pair.spin), "azimuthal_index": pair.azimuthal_index}
        for pair in pairs
    ]
    if declared != expected_declared:
        raise GsnCacheProductionError(
            "generated GSN cache declared pairs do not match the request"
        )
    for pair in pairs:
        _validate_coefficient_record(records[pair.cache_key], pair.cache_key)
    return hashlib.sha256(raw).hexdigest()


def _validate_status(path: Path, expected_count: int) -> None:
    _validate_regular_file(path, "GSN producer status")
    with path.open("r", encoding="ascii", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 1:
        raise GsnCacheProductionError("GSN producer status must contain one record")
    expected_validation_count = expected_count * 2 * 3
    expected = {
        "status_code": "0",
        "expected_parameter_pair_count": str(expected_count),
        "computed_parameter_pair_count": str(expected_count),
        "accepted_parameter_pair_count": str(expected_count),
        "rejected_parameter_pair_count": "0",
        "expected_validation_sample_count": str(expected_validation_count),
        "computed_validation_sample_count": str(expected_validation_count),
        "accepted_validation_sample_count": str(expected_validation_count),
        "rejected_validation_sample_count": "0",
        "source_equations_executed": "true",
        "exact_symbolic_algebra_used": "true",
        "maximum_scaled_validation_error_finite": "true",
        "validation_tolerance_satisfied": "true",
        "all_accepted": "true",
    }
    if rows[0] != expected:
        raise GsnCacheProductionError("GSN producer rejected its generated cache")


def _cache_receipt(
    *,
    parameter_set_sha256: str,
    cache_sha256: str,
    pairs: Sequence[GsnParameterPair],
    julia: Path,
    script: Path,
    kerr: Path,
    potentials: Path,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "parameter_set_sha256_observed": parameter_set_sha256,
        "cache_sha256": cache_sha256,
        "parameter_pairs": [pair.to_mapping() for pair in pairs],
        "julia_executable_sha256": hashlib.sha256(julia.read_bytes()).hexdigest(),
        "producer_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
        "kerr_sha256": hashlib.sha256(kerr.read_bytes()).hexdigest(),
        "potentials_sha256": hashlib.sha256(potentials.read_bytes()).hexdigest(),
    }


def _load_receipt(path: Path) -> object:
    _validate_regular_file(path, "generated GSN cache receipt")
    try:
        return json.loads(
            path.read_bytes(),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda item: (_ for _ in ()).throw(
                GsnCacheProductionError(
                    f"generated GSN receipt contains non-finite constant {item}"
                )
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GsnCacheProductionError(
            "generated GSN cache receipt is invalid JSON"
        ) from error


def _write_receipt(path: Path, value: Mapping[str, object]) -> None:
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(
        json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="ascii",
    )
    temporary.replace(path)


def ensure_generated_gsn_cache(
    parameter_pairs: Iterable[GsnParameterPair],
    *,
    runtime_root: Path | None = None,
    julia_executable: Path | None = None,
    producer_script: Path | None = None,
    gsn_source_root: Path | None = None,
    runner: Callable[..., object] = subprocess.run,
) -> GeneratedGsnCache:
    """Generate, validate, and digest the exact cache needed by a selection."""

    pairs = tuple(sorted(
        dict.fromkeys(parameter_pairs),
        key=lambda pair: (
            pair.spin,
            pair.azimuthal_index,
            pair.spin_numerator,
            pair.spin_denominator,
        ),
    ))
    if not pairs:
        raise GsnCacheProductionError("at least one GSN parameter pair is required")
    package_data = Path(__file__).resolve().parent / "data" / "julia"
    script = Path(producer_script or package_data / "generate_gsn_cache.jl")
    source_root = Path(
        gsn_source_root or package_data / "GeneralizedSasakiNakamura.jl"
    )
    homogeneous = source_root / "src" / "Homogeneous"
    kerr = homogeneous / "Kerr.jl"
    potentials = homogeneous / "Potentials.jl"
    runtime = Path(runtime_root or Path.cwd() / ".runtime")
    declared_julia = os.environ.get("KERR_QNM_JULIA_EXE")
    julia = Path(
        julia_executable
        or (Path(declared_julia) if declared_julia else runtime / "julia" / "bin" / "julia.exe")
    )
    _validate_regular_file(julia, "package-local Julia executable")
    _validate_regular_file(script, "package-owned GSN cache producer")
    _validate_regular_file(kerr, "packaged GeneralizedSasakiNakamura.jl Kerr")
    _validate_regular_file(potentials, "packaged GeneralizedSasakiNakamura.jl Potentials")
    parameter_set_sha256 = _parameter_set_sha256(pairs)
    output_directory = runtime / "generated" / "gsn"
    output_directory.mkdir(parents=True, exist_ok=True)
    index_path = output_directory / "gsn-index.json"
    index = _load_artifact_index(index_path)
    expected_pairs = _parameter_set_mapping(pairs)
    row = next(
        (
            item
            for item in index["artifacts"]
            if item["parameter_pairs"] == expected_pairs
        ),
        None,
    )
    if row is None:
        sequence = max(
            (
                int(item["artifact_id"].rsplit("-", 1)[1])
                for item in index["artifacts"]
            ),
            default=0,
        ) + 1
        artifact_id = f"gsn-set-{sequence:06d}"
        row = _artifact_row(artifact_id, pairs, cache_sha256=None)
    else:
        artifact_id = str(row["artifact_id"])
    pairs_path = output_directory / str(row["pairs_path"])
    cache_path = output_directory / str(row["cache_path"])
    status_path = output_directory / str(row["status_path"])
    journal_path = output_directory / str(row["journal_path"])
    receipt_path = output_directory / str(row["receipt_path"])
    for output_path in (
        pairs_path,
        cache_path,
        status_path,
        journal_path,
        receipt_path,
        receipt_path.with_name(f"{receipt_path.name}.tmp"),
    ):
        if output_path.is_symlink():
            raise GsnCacheProductionError(
                f"generated GSN output path must not be a symlink: {output_path}"
            )
    pairs_path.write_text(
        "".join(
            f"{pair.spin_numerator},{pair.spin_denominator},{pair.azimuthal_index}\n"
            for pair in pairs
        ),
        encoding="ascii",
    )
    if cache_path.is_file() and status_path.is_file():
        try:
            _validate_status(status_path, len(pairs))
            cached_digest = _validate_generated_cache(cache_path, pairs, potentials)
            return GeneratedGsnCache(
                artifact_id, cache_path.resolve(), cached_digest, pairs
            )
        except (GsnCacheProductionError, OSError):
            pass
    command = (
        str(julia),
        "--startup-file=no",
        str(script),
        "--gsn-source-root",
        str(source_root),
        "--pairs-file",
        str(pairs_path),
        "--output-cache",
        str(cache_path),
        "--status-output",
        str(status_path),
        "--journal-output",
        str(journal_path),
    )
    completed = runner(
        command,
        cwd=output_directory,
        capture_output=True,
        text=True,
        check=False,
        timeout=1800,
    )
    returncode = getattr(completed, "returncode", None)
    if returncode != 0:
        stderr = str(getattr(completed, "stderr", ""))[-2000:]
        raise GsnCacheProductionError(
            f"package-owned Julia GSN producer failed with code {returncode}: {stderr}"
        )
    _validate_status(status_path, len(pairs))
    digest = _validate_generated_cache(cache_path, pairs, potentials)
    _write_receipt(
        receipt_path,
        _cache_receipt(
            parameter_set_sha256=parameter_set_sha256,
            cache_sha256=digest,
            pairs=pairs,
            julia=julia,
            script=script,
            kerr=kerr,
            potentials=potentials,
        ),
    )
    accepted_row = _artifact_row(artifact_id, pairs, cache_sha256=digest)
    artifacts = [
        accepted_row if item["artifact_id"] == artifact_id else item
        for item in index["artifacts"]
    ]
    if not any(item["artifact_id"] == artifact_id for item in artifacts):
        artifacts.append(accepted_row)
    _write_json(index_path, {"schema_version": 1, "artifacts": artifacts})
    return GeneratedGsnCache(artifact_id, cache_path.resolve(), digest, pairs)
