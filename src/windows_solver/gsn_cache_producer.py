"""Package-owned Julia production boundary for GSN infinity-series inputs.

Development identity is mathematical and path based.  Each resolved ``(a, m)``
pair owns one short indexed artifact; measured digests are observations rather
than pre-known execution gates.  The Julia producer remains the sole owner of
the exact F/U coefficient algebra.
"""

from __future__ import annotations

import csv
from contextlib import contextmanager
from dataclasses import dataclass, field
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Callable, Iterable, Iterator, Mapping, Sequence

from .linear_response import spin_from_dimensionless_surface_gravity


GSN_INDEX_SCHEMA_VERSION = 2
GSN_RECORD_SCHEMA_VERSION = 2
GSN_PRODUCER_CONTRACT_VERSION = 1
GSN_CONSUMER_CONTRACT_VERSION = 1
GSN_EQUATION_CONVENTION = "generalized-sasaki-nakamura-spin-minus-two-sF-sU"
GSN_SPIN_WEIGHT = -2
GSN_MASS_NORMALIZATION = 1

_ARTIFACT_ID = re.compile(r"gsn-[0-9]{6}")
_DIGEST = re.compile(r"[0-9a-f]{64}")


class GsnCacheProductionError(RuntimeError):
    """The package-owned GSN input stage could not produce a trusted cache."""


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise GsnCacheProductionError(f"GSN JSON has duplicate key {key!r}")
        result[key] = value
    return result


@dataclass(frozen=True, slots=True, order=True)
class GsnSamplingOrigin:
    coordinate_id: str
    coordinate_numerator: int
    coordinate_denominator: int
    transformation_id: str

    def __post_init__(self) -> None:
        if not self.coordinate_id or not self.transformation_id:
            raise ValueError("GSN sampling origin names must be non-empty")
        if (
            isinstance(self.coordinate_numerator, bool)
            or not isinstance(self.coordinate_numerator, int)
            or isinstance(self.coordinate_denominator, bool)
            or not isinstance(self.coordinate_denominator, int)
            or self.coordinate_denominator <= 0
        ):
            raise ValueError("GSN sampling origin must have an exact rational value")
        reduced = Fraction(self.coordinate_numerator, self.coordinate_denominator)
        object.__setattr__(self, "coordinate_numerator", reduced.numerator)
        object.__setattr__(self, "coordinate_denominator", reduced.denominator)

    def to_mapping(self) -> dict[str, object]:
        return {
            "coordinate_id": self.coordinate_id,
            "coordinate_numerator": self.coordinate_numerator,
            "coordinate_denominator": self.coordinate_denominator,
            "transformation_id": self.transformation_id,
        }


@dataclass(frozen=True, slots=True)
class GsnParameterPair:
    spin_numerator: int
    spin_denominator: int
    azimuthal_index: int
    origins: tuple[GsnSamplingOrigin, ...] = field(
        default=(), compare=False, hash=False
    )

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
        object.__setattr__(self, "origins", tuple(sorted(set(self.origins))))

    @property
    def spin(self) -> Fraction:
        return Fraction(self.spin_numerator, self.spin_denominator)

    @property
    def spin_binary64_hex(self) -> str:
        return float(self.spin).hex()

    @property
    def cache_key(self) -> str:
        return f"m={self.azimuthal_index};a={float(self.spin):.15g}"

    def declared_mapping(self) -> dict[str, object]:
        return {
            "spin_numerator": self.spin_numerator,
            "spin_denominator": self.spin_denominator,
            "spin_binary64_hex": self.spin_binary64_hex,
            "azimuthal_index": self.azimuthal_index,
        }

    def logical_identity(self) -> dict[str, object]:
        return {
            "spin_weight": GSN_SPIN_WEIGHT,
            "resolved_spin_numerator": self.spin_numerator,
            "resolved_spin_denominator": self.spin_denominator,
            "resolved_spin_binary64_hex": self.spin_binary64_hex,
            "azimuthal_index": self.azimuthal_index,
            "mass_normalization": GSN_MASS_NORMALIZATION,
            "equation_convention": GSN_EQUATION_CONVENTION,
            "producer_contract_version": GSN_PRODUCER_CONTRACT_VERSION,
            "consumer_contract_version": GSN_CONSUMER_CONTRACT_VERSION,
        }

    def to_mapping(self) -> dict[str, object]:
        return {
            **self.declared_mapping(),
            "origin_coordinates": [origin.to_mapping() for origin in self.origins],
        }


@dataclass(frozen=True, slots=True)
class GeneratedGsnCache:
    record_artifact_ids: tuple[str, ...]
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
        resolved_spin = spin_from_dimensionless_surface_gravity(
            float(exact_coordinate)
        )
        spin = Fraction(*resolved_spin.as_integer_ratio())
    else:
        raise GsnCacheProductionError(
            f"unsupported campaign spin transformation {coordinate.transformation_id!r}"
        )
    if float(spin).hex() != leaf.job.spin.hex():
        raise GsnCacheProductionError(
            "exact campaign spin identity does not reproduce the binary64 job spin"
        )
    origin = GsnSamplingOrigin(
        coordinate.coordinate_id,
        numerator,
        denominator,
        coordinate.transformation_id,
    )
    return GsnParameterPair(
        spin.numerator, spin.denominator, leaf.job.mode.m, (origin,)
    )


def parameter_pairs_for_selection(
    plan: object, selection: object
) -> tuple[GsnParameterPair, ...]:
    leaf_by_id = {leaf.leaf_id: leaf for leaf in plan.leaves}
    accumulated: dict[tuple[int, int, int], set[GsnSamplingOrigin]] = {}
    order: list[tuple[int, int, int]] = []
    for leaf_id in selection.leaf_ids:
        try:
            pair = _parameter_pair_for_leaf(leaf_by_id[leaf_id])
        except KeyError as error:
            raise GsnCacheProductionError(
                f"campaign selection contains unknown leaf {leaf_id!r}"
            ) from error
        key = (
            pair.spin_numerator,
            pair.spin_denominator,
            pair.azimuthal_index,
        )
        if key not in accumulated:
            accumulated[key] = set()
            order.append(key)
        accumulated[key].update(pair.origins)
    if not order:
        raise GsnCacheProductionError("campaign selection has no GSN parameter pairs")
    return tuple(
        GsnParameterPair(*key, tuple(sorted(accumulated[key]))) for key in order
    )


def _validate_regular_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise GsnCacheProductionError(f"{label} is absent: {path}")
    if path.is_symlink():
        raise GsnCacheProductionError(f"{label} must not be a symlink: {path}")


def _load_json(path: Path, label: str) -> object:
    _validate_regular_file(path, label)
    try:
        return json.loads(
            path.read_bytes(),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda item: (_ for _ in ()).throw(
                GsnCacheProductionError(
                    f"{label} contains non-finite constant {item}"
                )
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GsnCacheProductionError(f"{label} is invalid JSON") from error


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _atomic_write(path: Path, data: bytes) -> None:
    if path.is_symlink():
        raise GsnCacheProductionError(f"GSN output path must not be a symlink: {path}")
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    if temporary.is_symlink():
        raise GsnCacheProductionError(
            f"GSN temporary path must not be a symlink: {temporary}"
        )
    with temporary.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _write_json(path: Path, value: Mapping[str, object]) -> None:
    _atomic_write(path, (_canonical_json(value) + "\n").encode("ascii"))


@contextmanager
def _index_lock(
    directory: Path,
    *,
    timeout_seconds: float = 1900.0,
    stale_seconds: float = 7200.0,
) -> Iterator[None]:
    lock = directory / ".gsn-index.lock"
    owner = lock / "owner.json"
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            lock.mkdir()
            owner.write_text(
                _canonical_json({"pid": os.getpid(), "created_unix": time.time()})
                + "\n",
                encoding="ascii",
            )
            break
        except FileExistsError:
            try:
                age = time.time() - lock.stat().st_mtime
                if age > stale_seconds:
                    try:
                        owner.unlink()
                    except FileNotFoundError:
                        pass
                    lock.rmdir()
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() >= deadline:
                raise GsnCacheProductionError(
                    f"timed out waiting for GSN index lock: {lock}"
                )
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            owner.unlink()
        except FileNotFoundError:
            pass
        try:
            lock.rmdir()
        except FileNotFoundError:
            pass


def _validate_origin(value: object) -> None:
    fields = {
        "coordinate_id",
        "coordinate_numerator",
        "coordinate_denominator",
        "transformation_id",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise GsnCacheProductionError("GSN index origin coordinate is invalid")
    try:
        GsnSamplingOrigin(
            value["coordinate_id"],
            value["coordinate_numerator"],
            value["coordinate_denominator"],
            value["transformation_id"],
        )
    except (TypeError, ValueError) as error:
        raise GsnCacheProductionError(
            "GSN index origin coordinate is invalid"
        ) from error


def _pair_from_identity(value: object) -> GsnParameterPair:
    fields = {
        "spin_weight",
        "resolved_spin_numerator",
        "resolved_spin_denominator",
        "resolved_spin_binary64_hex",
        "azimuthal_index",
        "mass_normalization",
        "equation_convention",
        "producer_contract_version",
        "consumer_contract_version",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise GsnCacheProductionError("GSN index logical identity is invalid")
    if (
        isinstance(value["spin_weight"], bool)
        or not isinstance(value["spin_weight"], int)
        or isinstance(value["mass_normalization"], bool)
        or not isinstance(value["mass_normalization"], int)
        or value["mass_normalization"] <= 0
        or not isinstance(value["equation_convention"], str)
        or not value["equation_convention"]
        or isinstance(value["producer_contract_version"], bool)
        or not isinstance(value["producer_contract_version"], int)
        or value["producer_contract_version"] <= 0
        or isinstance(value["consumer_contract_version"], bool)
        or not isinstance(value["consumer_contract_version"], int)
        or value["consumer_contract_version"] <= 0
    ):
        raise GsnCacheProductionError("GSN index logical contract is invalid")
    try:
        pair = GsnParameterPair(
            value["resolved_spin_numerator"],
            value["resolved_spin_denominator"],
            value["azimuthal_index"],
        )
    except (TypeError, ValueError) as error:
        raise GsnCacheProductionError("GSN index logical identity is invalid") from error
    if value["resolved_spin_binary64_hex"] != pair.spin_binary64_hex:
        raise GsnCacheProductionError(
            "GSN index exact and binary64 spin identities disagree"
        )
    return pair


def _blank_index() -> dict[str, object]:
    return {"schema_version": GSN_INDEX_SCHEMA_VERSION, "records": []}


def _load_artifact_index(path: Path) -> dict[str, object]:
    if not path.exists():
        return _blank_index()
    value = _load_json(path, "GSN artifact index")
    if (
        not isinstance(value, Mapping)
        or set(value) != {"schema_version", "records"}
        or value["schema_version"] != GSN_INDEX_SCHEMA_VERSION
        or not isinstance(value["records"], list)
    ):
        raise GsnCacheProductionError("GSN artifact index schema is invalid")
    ids: set[str] = set()
    identities: set[str] = set()
    rows: list[dict[str, object]] = []
    expected_row_fields = {
        "artifact_id",
        "logical_identity",
        "origin_coordinates",
        "cache_path",
        "status_path",
        "journal_path",
        "receipt_path",
        "request_path",
        "status",
        "observations",
    }
    for item in value["records"]:
        if not isinstance(item, Mapping) or set(item) != expected_row_fields:
            raise GsnCacheProductionError("GSN artifact index row is invalid")
        row = dict(item)
        artifact_id = row["artifact_id"]
        if (
            not isinstance(artifact_id, str)
            or _ARTIFACT_ID.fullmatch(artifact_id) is None
            or artifact_id in ids
        ):
            raise GsnCacheProductionError(
                "GSN artifact index ID is invalid or duplicated"
            )
        ids.add(artifact_id)
        _pair_from_identity(row["logical_identity"])
        identity_key = _canonical_json(row["logical_identity"])
        if identity_key in identities:
            raise GsnCacheProductionError(
                "GSN artifact index logical identity is duplicated"
            )
        identities.add(identity_key)
        if not isinstance(row["origin_coordinates"], list):
            raise GsnCacheProductionError("GSN index origin coordinates are invalid")
        for origin in row["origin_coordinates"]:
            _validate_origin(origin)
        expected_paths = {
            "cache_path": f"{artifact_id}.json",
            "status_path": f"{artifact_id}-status.csv",
            "journal_path": f"{artifact_id}-journal.jsonl",
            "receipt_path": f"{artifact_id}-receipt.json",
            "request_path": f"{artifact_id}-request.csv",
        }
        if any(row[name] != expected for name, expected in expected_paths.items()):
            raise GsnCacheProductionError(
                "GSN artifact index has an inconsistent artifact binding"
            )
        if row["status"] != "accepted":
            raise GsnCacheProductionError("GSN artifact index status is invalid")
        observations = row["observations"]
        expected_observations = {
            "cache_sha256",
            "julia_executable_sha256",
            "producer_sha256",
            "kerr_sha256",
            "potentials_sha256",
        }
        if (
            not isinstance(observations, Mapping)
            or set(observations) != expected_observations
            or any(
                not isinstance(observations[name], str)
                or _DIGEST.fullmatch(observations[name]) is None
                for name in expected_observations
            )
        ):
            raise GsnCacheProductionError("GSN artifact observations are invalid")
        rows.append(row)
    return {"schema_version": GSN_INDEX_SCHEMA_VERSION, "records": rows}


def _write_index(path: Path, value: Mapping[str, object]) -> None:
    if path.exists():
        previous = path.with_name("gsn-index.previous.json")
        _atomic_write(previous, path.read_bytes())
    _write_json(path, value)


def _next_artifact_id(index: Mapping[str, object], directory: Path) -> str:
    sequences = [
        int(row["artifact_id"].split("-")[1]) for row in index["records"]
    ]
    for path in directory.iterdir():
        match = re.match(r"gsn-([0-9]{6})(?:[.-]|$)", path.name)
        if match is not None:
            sequences.append(int(match.group(1)))
    return f"gsn-{max(sequences, default=0) + 1:06d}"


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
        for coefficient_field in sorted(fields):
            coefficients = series[coefficient_field]
            if (
                not isinstance(coefficients, list)
                or not coefficients
                or any(not isinstance(item, str) or not item for item in coefficients)
            ):
                raise GsnCacheProductionError(
                    f"generated GSN cache record {key!r} {name} "
                    f"{coefficient_field} is invalid"
                )


def _validate_generated_record(path: Path, pair: GsnParameterPair) -> tuple[str, dict[str, object]]:
    raw = path.read_bytes() if path.is_file() and not path.is_symlink() else b""
    value = _load_json(path, "generated GSN pair artifact")
    expected_fields = {
        "schema_version",
        "producer_contract_version",
        "consumer_contract_version",
        "equation_convention",
        "spin_weight",
        "mass_normalization",
        "source_relative_path",
        "source_sha256",
        "declared_parameter_pairs",
        "records",
    }
    if not isinstance(value, Mapping) or set(value) != expected_fields:
        raise GsnCacheProductionError("generated GSN pair artifact fields are invalid")
    if (
        value["schema_version"] != GSN_RECORD_SCHEMA_VERSION
        or value["producer_contract_version"] != GSN_PRODUCER_CONTRACT_VERSION
        or value["consumer_contract_version"] != GSN_CONSUMER_CONTRACT_VERSION
        or value["equation_convention"] != GSN_EQUATION_CONVENTION
        or value["spin_weight"] != GSN_SPIN_WEIGHT
        or value["mass_normalization"] != GSN_MASS_NORMALIZATION
    ):
        raise GsnCacheProductionError("generated GSN pair contract is incompatible")
    if value["source_relative_path"] != "src/Homogeneous/Potentials.jl":
        raise GsnCacheProductionError("generated GSN source path is invalid")
    if (
        not isinstance(value["source_sha256"], str)
        or _DIGEST.fullmatch(value["source_sha256"]) is None
    ):
        raise GsnCacheProductionError("generated GSN source observation is invalid")
    if value["declared_parameter_pairs"] != [pair.declared_mapping()]:
        raise GsnCacheProductionError(
            "generated GSN pair declaration does not match its indexed identity"
        )
    records = value["records"]
    if not isinstance(records, Mapping) or set(records) != {pair.cache_key}:
        raise GsnCacheProductionError(
            "generated GSN pair artifact has the wrong coefficient record"
        )
    _validate_coefficient_record(records[pair.cache_key], pair.cache_key)
    return hashlib.sha256(raw).hexdigest(), dict(value)


def _validate_status(path: Path) -> None:
    _validate_regular_file(path, "GSN producer status")
    with path.open("r", encoding="ascii", newline="") as stream:
        rows = list(csv.DictReader(stream))
    expected = {
        "status_code": "0",
        "expected_parameter_pair_count": "1",
        "computed_parameter_pair_count": "1",
        "accepted_parameter_pair_count": "1",
        "rejected_parameter_pair_count": "0",
        "expected_validation_sample_count": "6",
        "computed_validation_sample_count": "6",
        "accepted_validation_sample_count": "6",
        "rejected_validation_sample_count": "0",
        "source_equations_executed": "true",
        "exact_symbolic_algebra_used": "true",
        "maximum_scaled_validation_error_finite": "true",
        "validation_tolerance_satisfied": "true",
        "all_accepted": "true",
    }
    if rows != [expected]:
        raise GsnCacheProductionError("GSN producer rejected its generated pair")


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _observations(
    *, cache_sha256: str, julia: Path, script: Path, kerr: Path, potentials: Path
) -> dict[str, str]:
    return {
        "cache_sha256": cache_sha256,
        "julia_executable_sha256": _hash_file(julia),
        "producer_sha256": _hash_file(script),
        "kerr_sha256": _hash_file(kerr),
        "potentials_sha256": _hash_file(potentials),
    }


def _artifact_row(
    artifact_id: str,
    pair: GsnParameterPair,
    observations: Mapping[str, str],
    prior_origins: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    origin_values = {
        _canonical_json(origin): dict(origin) for origin in prior_origins
    }
    for origin in pair.origins:
        mapping = origin.to_mapping()
        origin_values[_canonical_json(mapping)] = mapping
    return {
        "artifact_id": artifact_id,
        "logical_identity": pair.logical_identity(),
        "origin_coordinates": [origin_values[key] for key in sorted(origin_values)],
        "cache_path": f"{artifact_id}.json",
        "status_path": f"{artifact_id}-status.csv",
        "journal_path": f"{artifact_id}-journal.jsonl",
        "receipt_path": f"{artifact_id}-receipt.json",
        "request_path": f"{artifact_id}-request.csv",
        "status": "accepted",
        "observations": dict(observations),
    }


def _replace_row(index: dict[str, object], row: Mapping[str, object]) -> None:
    rows = [
        dict(row) if item["artifact_id"] == row["artifact_id"] else item
        for item in index["records"]
    ]
    if not any(item["artifact_id"] == row["artifact_id"] for item in rows):
        rows.append(dict(row))
    rows.sort(key=lambda item: item["artifact_id"])
    index["records"] = rows


def _generate_pair(
    *,
    pair: GsnParameterPair,
    row: Mapping[str, object],
    directory: Path,
    julia: Path,
    script: Path,
    source_root: Path,
    kerr: Path,
    potentials: Path,
    runner: Callable[..., object],
) -> tuple[dict[str, object], dict[str, object]]:
    request_path = directory / str(row["request_path"])
    cache_path = directory / str(row["cache_path"])
    status_path = directory / str(row["status_path"])
    journal_path = directory / str(row["journal_path"])
    receipt_path = directory / str(row["receipt_path"])
    for output_path in (request_path, cache_path, status_path, journal_path, receipt_path):
        if output_path.is_symlink():
            raise GsnCacheProductionError(
                f"generated GSN output path must not be a symlink: {output_path}"
            )
    _atomic_write(
        request_path,
        (
            f"{pair.spin_numerator},{pair.spin_denominator},"
            f"{pair.azimuthal_index}\n"
        ).encode("ascii"),
    )
    command = (
        str(julia),
        "--startup-file=no",
        str(script),
        "--gsn-source-root",
        str(source_root),
        "--pairs-file",
        str(request_path),
        "--output-cache",
        str(cache_path),
        "--status-output",
        str(status_path),
        "--journal-output",
        str(journal_path),
    )
    completed = runner(
        command,
        cwd=directory,
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
    _validate_status(status_path)
    digest, document = _validate_generated_record(cache_path, pair)
    observed = _observations(
        cache_sha256=digest,
        julia=julia,
        script=script,
        kerr=kerr,
        potentials=potentials,
    )
    accepted_row = _artifact_row(
        str(row["artifact_id"]),
        pair,
        observed,
        row.get("origin_coordinates", ()),
    )
    _write_json(
        receipt_path,
        {
            "schema_version": 1,
            "artifact_id": row["artifact_id"],
            "logical_identity": pair.logical_identity(),
            "observations": observed,
        },
    )
    return accepted_row, document


def _reuse_pair(
    row: Mapping[str, object], pair: GsnParameterPair, directory: Path
) -> tuple[dict[str, object], dict[str, object]]:
    _validate_status(directory / str(row["status_path"]))
    digest, document = _validate_generated_record(
        directory / str(row["cache_path"]), pair
    )
    observations = dict(row["observations"])
    observations["cache_sha256"] = digest
    return (
        _artifact_row(
            str(row["artifact_id"]),
            pair,
            observations,
            row["origin_coordinates"],
        ),
        document,
    )


def _assemble_selection_cache(
    directory: Path,
    records: Sequence[tuple[str, GsnParameterPair, Mapping[str, object]]],
) -> tuple[Path, str]:
    identities = [
        {"artifact_id": artifact_id, "logical_identity": pair.logical_identity()}
        for artifact_id, pair, _ in records
    ]
    selection_digest = hashlib.sha256(
        _canonical_json(identities).encode("ascii")
    ).hexdigest()
    path = directory / f"gsn-selection-{selection_digest[:12]}.json"
    combined_records: dict[str, object] = {}
    for _, pair, document in records:
        combined_records[pair.cache_key] = document["records"][pair.cache_key]
    document = {
        "schema_version": GSN_RECORD_SCHEMA_VERSION,
        "producer_contract_version": GSN_PRODUCER_CONTRACT_VERSION,
        "consumer_contract_version": GSN_CONSUMER_CONTRACT_VERSION,
        "equation_convention": GSN_EQUATION_CONVENTION,
        "spin_weight": GSN_SPIN_WEIGHT,
        "mass_normalization": GSN_MASS_NORMALIZATION,
        "record_artifact_ids": [item[0] for item in records],
        "declared_parameter_pairs": [item[1].declared_mapping() for item in records],
        "records": combined_records,
    }
    _write_json(path, document)
    raw = path.read_bytes()
    return path.resolve(), hashlib.sha256(raw).hexdigest()


def ensure_generated_gsn_cache(
    parameter_pairs: Iterable[GsnParameterPair],
    *,
    runtime_root: Path | None = None,
    julia_executable: Path | None = None,
    producer_script: Path | None = None,
    gsn_source_root: Path | None = None,
    runner: Callable[..., object] = subprocess.run,
) -> GeneratedGsnCache:
    """Return a structurally validated assembled cache for the requested pairs.

    Pair identity is exact and order-independent.  Each missing or invalid pair
    is regenerated independently and immediately committed to the runtime index.
    """

    origin_sets: dict[tuple[int, int, int], set[GsnSamplingOrigin]] = {}
    for item in parameter_pairs:
        pair = GsnParameterPair(
            item.spin_numerator,
            item.spin_denominator,
            item.azimuthal_index,
            item.origins,
        )
        key = (pair.spin_numerator, pair.spin_denominator, pair.azimuthal_index)
        origin_sets.setdefault(key, set()).update(pair.origins)
    pairs = tuple(
        GsnParameterPair(*key, tuple(sorted(origins)))
        for key, origins in sorted(
            origin_sets.items(),
            key=lambda item: (Fraction(item[0][0], item[0][1]), item[0][2]),
        )
    )
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
        or (
            Path(declared_julia)
            if declared_julia
            else runtime / "julia" / "bin" / "julia.exe"
        )
    )
    _validate_regular_file(julia, "package-local Julia executable")
    _validate_regular_file(script, "package-owned GSN cache producer")
    _validate_regular_file(kerr, "packaged GeneralizedSasakiNakamura.jl Kerr")
    _validate_regular_file(
        potentials, "packaged GeneralizedSasakiNakamura.jl Potentials"
    )

    directory = runtime / "generated" / "gsn"
    directory.mkdir(parents=True, exist_ok=True)
    index_path = directory / "gsn-index.json"
    resolved: list[tuple[str, GsnParameterPair, Mapping[str, object]]] = []
    with _index_lock(directory):
        index = _load_artifact_index(index_path)
        for pair in pairs:
            identity = pair.logical_identity()
            row = next(
                (
                    item
                    for item in index["records"]
                    if item["logical_identity"] == identity
                ),
                None,
            )
            if row is None:
                artifact_id = _next_artifact_id(index, directory)
                row = {
                    "artifact_id": artifact_id,
                    "logical_identity": identity,
                    "origin_coordinates": [],
                    "cache_path": f"{artifact_id}.json",
                    "status_path": f"{artifact_id}-status.csv",
                    "journal_path": f"{artifact_id}-journal.jsonl",
                    "receipt_path": f"{artifact_id}-receipt.json",
                    "request_path": f"{artifact_id}-request.csv",
                }
            try:
                accepted_row, document = _reuse_pair(row, pair, directory)
            except (GsnCacheProductionError, OSError, KeyError, TypeError):
                accepted_row, document = _generate_pair(
                    pair=pair,
                    row=row,
                    directory=directory,
                    julia=julia,
                    script=script,
                    source_root=source_root,
                    kerr=kerr,
                    potentials=potentials,
                    runner=runner,
                )
            _replace_row(index, accepted_row)
            _write_index(index_path, index)
            resolved.append((str(accepted_row["artifact_id"]), pair, document))

    assembled_path, assembled_sha256 = _assemble_selection_cache(directory, resolved)
    return GeneratedGsnCache(
        tuple(item[0] for item in resolved),
        assembled_path,
        assembled_sha256,
        pairs,
    )
