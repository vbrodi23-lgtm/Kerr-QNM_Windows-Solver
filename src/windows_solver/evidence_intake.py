"""Authenticated intake boundary for operator-produced linear-response evidence.

This module validates structure and byte lineage only.  It cannot admit the
linear-response provider and it never executes response or spectral solvers.
"""

from __future__ import annotations

from copy import deepcopy
import csv
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping

from .contracts import ModeKey, canonical_json_bytes
from .linear_response import (
    B_PRIME_RELEASE_DOMAIN,
    LINEAR_RESPONSE_DESCRIPTOR,
    baseline_root_reference_id,
)


BUNDLE_SCHEMA_VERSION = 1
_PRIVATE_SERIES = "v" + "2"
_LEGACY_PROTOCOL_VERSION = "v" + "1"
_LOCAL_LADDER_ORIGIN = "_".join(
    (_PRIVATE_SERIES.upper(), "COMPONENT", "LOCAL", "SIGNED", "AMPLITUDE", "LADDER")
)
PINNED_FIXTURE_SOURCE_REPOSITORY = (
    "vbrodi23-lgtm/Windows-Solver_" + _PRIVATE_SERIES.upper() + "-whiteboard"
)
PINNED_FIXTURE_SOURCE_COMMIT = (
    "0c1e8a3d3bca6e608c34e111476a4f6dcb73e86e"
)

_HEX_40 = re.compile(r"[0-9a-f]{40}")
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_ROOT_REFERENCE = re.compile(r"spectral-root-reference-[0-9a-f]{64}")
_WINDOWS_DRIVE = re.compile(r"[A-Za-z]:")
_RUNTIME_FINGERPRINT = re.compile(
    r"cpython-[0-9]+\.[0-9]+(?:\.[0-9]+)?-"
    r"(?:windows|linux|darwin)-(?:amd64|x86_64|arm64|aarch64)"
)
_BUNDLE_STATES = frozenset({"partial-smoke", "complete-operator"})
_NUMERICAL_STATES = frozenset({"ACCEPTED", "UNRESOLVED"})
_SOURCE_CODE_SUFFIXES = frozenset(
    {".py", ".pyc", ".pyo", ".ps1", ".bat", ".cmd", ".com", ".exe", ".dll", ".so", ".dylib", ".sh"}
)
_OPERATOR_SMOKE_LEAF_IDS = (
    "b-prime-leaf-9e5777728144433e089f9559b92b6e139e16115a5a53099f40403a45297aa3c3",
    "b-prime-leaf-59894e4af3913286bb06cb36d1f01f508f728588937fbc5a45eab6da2906b77d",
    "b-prime-leaf-3ee2b2dcdc5276cbcd51264f1210002314acd3ff845bb7a464f1e9333e9115c5",
    "b-prime-leaf-4eb508d767bea5cddc3f7c0eb120c1a9cc184122900f4d7ec86b56c98ddab596",
)

_CONTRACT_MATERIAL = {
    "contract_id": "m02-b-prime-212-leaf-linear-response",
    "required_leaf_ids": list(B_PRIME_RELEASE_DOMAIN.production_leaf_ids),
}
B_PRIME_CONTRACT_SHA256 = hashlib.sha256(
    canonical_json_bytes(_CONTRACT_MATERIAL)
).hexdigest()

_DATA_DIRECTORY = Path(__file__).resolve().parent / "data" / "evidence_intake"
_FIXTURE_BINDINGS = (
    (
        f"docs/evidence/{_PRIVATE_SERIES}-02/{_PRIVATE_SERIES}_local_response_protocol.json",
        "pilot/protocol.fixture",
        "ed729c8420b6c08abc534212dc2a593c1c65cf36",
        "421e0751f5a68f95cd69fc0b5cdb155c96fe5cbb83d81e59489bf9130636673b",
    ),
    (
        f"docs/evidence/{_PRIVATE_SERIES}-02/{_PRIVATE_SERIES}_local_response_reduction.json",
        "pilot/reduction.fixture",
        "3b9034df6eada7ec60ac347518a6f616d4f6683e",
        "b6a5018c1f4875ebea2f26d544c354896edb33c2bb176ccebc90a1d511c46203",
    ),
    (
        f"docs/evidence/{_PRIVATE_SERIES}-02/{_PRIVATE_SERIES}_local_response_components.csv",
        "pilot/components.fixture",
        "3f24cb859b4d13641bf0649d214dfd0ded498239",
        "20aa65b184e7866827f2283d64148fc68f2a0f16d02f701afc8cd516157b42f4",
    ),
    (
        f"docs/evidence/{_PRIVATE_SERIES}-07-physical-cubic-even/{_PRIVATE_SERIES}_07_physical_cubic_even_resolved.csv",
        "cubic/resolved.fixture",
        "b6a6620702ce264e0467d7daf0358bae83d5d5d4",
        "89f28eabdf0be247a1db87fb13c6f0c8a60bb9065518426b8a9d5a24630b0bd1",
    ),
    (
        f"docs/evidence/{_PRIVATE_SERIES}-07-physical-cubic-even/{_PRIVATE_SERIES}_07_physical_cubic_even_status.json",
        "cubic/status.fixture",
        "8924859018574c0eda7941a2024b03a6e971a012",
        "07b12e64fa22783a9429371facfc14990b70fbc28dcf60039c477ec3bdec1d9f",
    ),
)


@dataclass(frozen=True, slots=True)
class EvidenceBundleSummary:
    """Stable machine-readable result of structural evidence validation."""

    bundle_state: str
    bundle_sha256: str
    produced_count: int
    missing_count: int
    comparator_count: int
    sampled_ids: tuple[str, ...]
    validation_status: str = "STRUCTURALLY_VALID"
    release_admissible: bool = False

    def to_mapping(self) -> dict[str, object]:
        return {
            "bundle_state": self.bundle_state,
            "bundle_sha256": self.bundle_sha256,
            "produced_count": self.produced_count,
            "missing_count": self.missing_count,
            "comparator_count": self.comparator_count,
            "sampled_ids": list(self.sampled_ids),
            "validation_status": self.validation_status,
            "release_admissible": False,
        }


def _mapping(value: object, subject: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{subject} must be an object with string keys")
    return value


def _array(value: object, subject: str) -> list[Any]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{subject} must be an array")
    return list(value)


def _string(value: object, subject: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{subject} must be a non-empty string")
    return value


def _integer(value: object, subject: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{subject} must be an integer")
    return value


def _digest(value: object, subject: str, pattern: re.Pattern[str] = _HEX_64) -> str:
    text = _string(value, subject)
    if pattern.fullmatch(text) is None:
        raise ValueError(f"{subject} must be a lowercase hexadecimal digest")
    return text


def _exact_fields(mapping: Mapping[str, Any], expected: frozenset[str], subject: str) -> None:
    unknown = sorted(set(mapping) - expected)
    if unknown:
        raise ValueError(f"unknown {subject} fields: {', '.join(unknown)}")
    missing = sorted(expected - set(mapping))
    if missing:
        raise ValueError(f"missing {subject} fields: {', '.join(missing)}")


def _finite_tree(value: object, subject: str = "evidence bundle") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{subject} contains a non-finite value")
    if isinstance(value, Mapping):
        for key, item in value.items():
            _finite_tree(item, f"{subject}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _finite_tree(item, f"{subject}[{index}]")


def _reject_duplicate_json_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    mapping: dict[str, object] = {}
    for key, value in pairs:
        if key in mapping:
            raise ValueError(f"duplicate evidence JSON key: {key}")
        mapping[key] = value
    return mapping


def _safe_relative_path(value: object, subject: str) -> str:
    text = _string(value, subject).replace("\\", "/")
    if (
        text.startswith("/")
        or _WINDOWS_DRIVE.match(text)
        or ":" in text
    ):
        raise ValueError(f"{subject} must be a safe relative path")
    path = PurePosixPath(text)
    if not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{subject} must be a safe relative path")
    return path.as_posix()


def _normalized_digest_mapping(manifest: Mapping[str, object]) -> dict[str, object]:
    normalized = deepcopy(dict(manifest))
    normalized.pop("bundle_sha256", None)
    source_files = normalized.get("source_files")
    if isinstance(source_files, list):
        for item in source_files:
            if isinstance(item, dict) and "path" in item:
                item["path"] = _safe_relative_path(item["path"], "source file path")
    records = normalized.get("produced_records")
    if isinstance(records, list):
        for item in records:
            if isinstance(item, dict):
                if "payload_path" in item:
                    item["payload_path"] = _safe_relative_path(item["payload_path"], "payload path")
                if "source_reference" in item:
                    item["source_reference"] = _safe_relative_path(item["source_reference"], "source reference")
    comparators = normalized.get("comparator_fixtures")
    if isinstance(comparators, list):
        for item in comparators:
            if isinstance(item, dict) and "source_path" in item:
                item["source_path"] = _safe_relative_path(item["source_path"], "comparator source path")
    return normalized


def evidence_bundle_digest(manifest: Mapping[str, object]) -> str:
    """Return the separator-normalized canonical digest for one manifest."""

    return hashlib.sha256(
        canonical_json_bytes(_normalized_digest_mapping(manifest))
    ).hexdigest()


def _bound_file_bytes(directory: Path, relative: str, subject: str) -> tuple[bytes, Path]:
    root = directory.resolve()
    candidate = (root / Path(*PurePosixPath(relative).parts)).resolve(strict=True)
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise ValueError(f"{subject} must remain inside the bundle directory")
    return candidate.read_bytes(), candidate


def _validate_source_files(value: object, directory: Path) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for index, raw in enumerate(_array(value, "source_files")):
        item = _mapping(raw, f"source_files[{index}]")
        _exact_fields(
            item,
            frozenset({"path", "byte_size", "sha256", "media_type", "purpose"}),
            f"source_files[{index}]",
        )
        path = _safe_relative_path(item["path"], f"source_files[{index}] path")
        if path in result:
            raise ValueError("source_files contains duplicate normalized paths")
        byte_size = _integer(item["byte_size"], f"source_files[{index}] byte_size")
        if byte_size < 0:
            raise ValueError("source file byte_size must not be negative")
        sha256 = _digest(item["sha256"], f"source_files[{index}] sha256")
        _string(item["media_type"], f"source_files[{index}] media_type")
        _string(item["purpose"], f"source_files[{index}] purpose")
        data, _ = _bound_file_bytes(directory, path, f"source_files[{index}]")
        if len(data) != byte_size or hashlib.sha256(data).hexdigest() != sha256:
            raise ValueError(f"source_files[{index}] byte size or SHA-256 mismatch")
        result[path] = {**dict(item), "_git_blob_sha": _git_blob_sha(data)}
    if not result:
        raise ValueError("source_files must not be empty")
    return result


def _validate_contract(value: object) -> Mapping[str, object]:
    contract = _mapping(value, "contract")
    _exact_fields(
        contract,
        frozenset({
            "release_domain_fingerprint", "numerical_policy_fingerprint",
            "required_leaf_ids", "campaign_spectral_receipt",
        }),
        "contract",
    )
    if _digest(contract["release_domain_fingerprint"], "release_domain_fingerprint") != B_PRIME_CONTRACT_SHA256:
        raise ValueError("release-domain fingerprint does not match frozen B′")
    if _string(contract["numerical_policy_fingerprint"], "numerical_policy_fingerprint") != LINEAR_RESPONSE_DESCRIPTOR.numerical_policy_fingerprint:
        raise ValueError("numerical-policy fingerprint does not match frozen B′")
    required = [_string(item, "required leaf ID") for item in _array(contract["required_leaf_ids"], "required_leaf_ids")]
    if required != list(B_PRIME_RELEASE_DOMAIN.production_leaf_ids):
        raise ValueError(
            "required_leaf_ids must equal the ordered frozen "
            f"{len(B_PRIME_RELEASE_DOMAIN.production_leaf_ids)}-leaf B′ contract"
        )
    receipt = _mapping(
        contract["campaign_spectral_receipt"], "campaign spectral receipt"
    )
    _exact_fields(
        receipt,
        frozenset({"provider", "root_count", "root_set_sha256"}),
        "campaign spectral receipt",
    )
    provider = _mapping(receipt["provider"], "campaign spectral provider")
    if not provider:
        raise ValueError("campaign spectral provider must not be empty")
    expected_root_count = len(B_PRIME_RELEASE_DOMAIN.root_selectors)
    if _integer(receipt["root_count"], "campaign spectral root_count") != expected_root_count:
        raise ValueError(
            "campaign spectral receipt must bind exactly "
            f"{expected_root_count} roots"
        )
    _digest(receipt["root_set_sha256"], "campaign spectral root-set SHA-256")
    return receipt


def _validate_producer(
    value: object,
    sources: Mapping[str, Mapping[str, object]],
) -> None:
    producer = _mapping(value, "producer")
    _exact_fields(
        producer,
        frozenset({"producer_id", "runtime_fingerprint", "source_repository", "source_commit", "source_sha256s"}),
        "producer",
    )
    _string(producer["producer_id"], "producer_id")
    runtime = _string(producer["runtime_fingerprint"], "runtime_fingerprint")
    if _RUNTIME_FINGERPRINT.fullmatch(runtime) is None:
        raise ValueError(
            "runtime_fingerprint must use "
            "cpython-MAJOR.MINOR[.PATCH]-SYSTEM-ARCH identity"
        )
    _string(producer["source_repository"], "source_repository")
    _digest(producer["source_commit"], "source_commit", _HEX_40)
    hashes = [_digest(item, "producer source SHA-256") for item in _array(producer["source_sha256s"], "source_sha256s")]
    if not hashes or len(hashes) != len(set(hashes)):
        raise ValueError("source_sha256s must be nonempty and unique")
    byte_verified_hashes = {str(item["sha256"]) for item in sources.values()}
    if set(hashes) != byte_verified_hashes:
        raise ValueError(
            "producer source_sha256s must exactly bind all byte-verified source_files"
        )


def _comparator_identity_sha256(
    *,
    fixture_id: str,
    fixture_kind: str,
    disposition: str,
    source_path: str,
    source_blob_sha: str,
    source_sha256: str,
) -> str:
    material = {
        "fixture_id": fixture_id,
        "fixture_kind": fixture_kind,
        "disposition": disposition,
        "source_path": source_path,
        "source_blob_sha": source_blob_sha,
        "source_sha256": source_sha256,
    }
    return hashlib.sha256(canonical_json_bytes(material)).hexdigest()


def _validate_comparators(
    value: object,
    sources: Mapping[str, Mapping[str, object]],
) -> tuple[str, ...]:
    fixture_ids: list[str] = []
    for index, raw in enumerate(_array(value, "comparator_fixtures")):
        item = _mapping(raw, f"comparator_fixtures[{index}]")
        _exact_fields(
            item,
            frozenset({"fixture_id", "fixture_kind", "disposition", "source_path", "source_blob_sha", "source_sha256", "identity_sha256"}),
            f"comparator_fixtures[{index}]",
        )
        fixture_id = _string(item["fixture_id"], "comparator fixture_id")
        if fixture_id in fixture_ids:
            raise ValueError("comparator_fixtures contains duplicate IDs")
        kind = _string(item["fixture_kind"], "comparator fixture_kind")
        disposition = _string(item["disposition"], "comparator disposition")
        expected_disposition = {
            "legacy-gr-pilot": "migration-only",
            "cubic-comparator": "comparator-only",
        }.get(kind)
        if expected_disposition is None or disposition != expected_disposition:
            raise ValueError("comparator fixture kind/disposition is invalid")
        source_path = _safe_relative_path(item["source_path"], "comparator source_path")
        if source_path not in sources:
            raise ValueError("comparator source_path is not a declared source file")
        source_blob = _digest(
            item["source_blob_sha"], "comparator source_blob_sha", _HEX_40
        )
        if source_blob != sources[source_path]["_git_blob_sha"]:
            raise ValueError("comparator Git blob SHA does not match source file bytes")
        source_sha = _digest(item["source_sha256"], "comparator source_sha256")
        if source_sha != sources[source_path]["sha256"]:
            raise ValueError("comparator source SHA-256 does not match source file")
        identity_sha = _digest(
            item["identity_sha256"], "comparator identity_sha256"
        )
        expected_identity_sha = _comparator_identity_sha256(
            fixture_id=fixture_id,
            fixture_kind=kind,
            disposition=disposition,
            source_path=source_path,
            source_blob_sha=source_blob,
            source_sha256=source_sha,
        )
        if identity_sha != expected_identity_sha:
            raise ValueError(
                "comparator identity_sha256 does not authenticate canonical identity"
            )
        fixture_ids.append(fixture_id)
    return tuple(fixture_ids)


def _validate_json_payload(data: bytes, subject: str) -> None:
    def reject_constant(value: str) -> object:
        raise ValueError(f"{subject} contains non-finite JSON constant {value}")

    try:
        payload = json.loads(
            data,
            parse_constant=reject_constant,
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{subject} is not valid UTF-8 JSON") from error
    _finite_tree(payload, subject)


def _validate_records(
    value: object,
    directory: Path,
    sources: Mapping[str, Mapping[str, object]],
) -> tuple[tuple[str, ...], tuple[Mapping[str, object], ...]]:
    expected_by_id = {
        leaf.leaf_id: leaf for leaf in B_PRIME_RELEASE_DOMAIN.production_leaves
    }
    produced: list[str] = []
    payload_paths: set[str] = set()
    roots: dict[str, Mapping[str, object]] = {}
    for index, raw in enumerate(_array(value, "produced_records")):
        record = _mapping(raw, f"produced_records[{index}]")
        _exact_fields(
            record,
            frozenset({
                "leaf_id", "role", "mode", "sampling_coordinate", "mechanism_id",
                "numerical_state", "payload_path", "payload_size", "payload_sha256",
                "source_reference", "root_reference_id", "root_identity",
                "root_identity_sha256", "uncertainty_scope",
            }),
            f"produced_records[{index}]",
        )
        leaf_id = _string(record["leaf_id"], "produced leaf_id")
        if leaf_id in produced:
            raise ValueError("produced_records contains duplicate leaf IDs")
        leaf = expected_by_id.get(leaf_id)
        if leaf is None:
            raise ValueError("produced record contains an off-domain leaf ID")
        if record["role"] != leaf.role or _array(record["mode"], "record mode") != list(leaf.mode):
            raise ValueError("produced record role or mode does not match its leaf ID")
        coordinate = _mapping(record["sampling_coordinate"], "sampling_coordinate")
        _exact_fields(coordinate, frozenset({"coordinate_id", "exact", "spin_binary64_hex"}), "sampling_coordinate")
        expected_coordinate_id = "a-over-M" if leaf.spin_role == "direct" else "M-kappa"
        exact = _array(coordinate["exact"], "sampling coordinate exact identity")
        if coordinate["coordinate_id"] != expected_coordinate_id or exact != [leaf.coordinate.numerator, leaf.coordinate.denominator] or coordinate["spin_binary64_hex"] != leaf.spin.hex():
            raise ValueError("produced record coordinate does not match its leaf ID")
        if record["mechanism_id"] != leaf.mechanism_id:
            raise ValueError("produced record mechanism does not match its leaf ID")
        numerical_state = _string(
            record["numerical_state"], "produced record numerical_state"
        )
        if numerical_state not in _NUMERICAL_STATES:
            raise ValueError("produced record numerical_state is invalid")
        if record["uncertainty_scope"] != "component-local":
            raise ValueError("global uncertainty substitution is forbidden")
        payload_path = _safe_relative_path(record["payload_path"], "produced payload path")
        if payload_path in payload_paths:
            raise ValueError("produced_records contains duplicate payload paths")
        suffix = PurePosixPath(payload_path).suffix.lower()
        if suffix in _SOURCE_CODE_SUFFIXES:
            raise ValueError("source-code or executable files cannot be production evidence")
        data, physical_path = _bound_file_bytes(directory, payload_path, "produced payload")
        if physical_path.stat().st_mode & 0o111:
            raise ValueError("executable files cannot be production evidence")
        byte_size = _integer(record["payload_size"], "payload_size")
        sha256 = _digest(record["payload_sha256"], "payload_sha256")
        if len(data) != byte_size or hashlib.sha256(data).hexdigest() != sha256:
            raise ValueError("produced payload byte size or SHA-256 mismatch")
        if suffix == ".json":
            _validate_json_payload(data, f"payload {payload_path}")
        source_reference = _safe_relative_path(record["source_reference"], "source_reference")
        if source_reference not in sources:
            raise ValueError("produced record source_reference is undeclared")
        root_reference_id = _string(record["root_reference_id"], "root_reference_id")
        if _ROOT_REFERENCE.fullmatch(root_reference_id) is None:
            raise ValueError("root_reference_id is malformed")
        mode = ModeKey(
            s=-2,
            ell=leaf.mode[0],
            m=leaf.mode[1],
            n=leaf.mode[2],
            branch="schwarzschild-overtone-continuation",
            polarization="gravitational",
        )
        if root_reference_id != baseline_root_reference_id(mode, leaf.spin):
            raise ValueError("root_reference_id does not match the exact B′ leaf")
        root_identity = _mapping(record["root_identity"], "campaign root identity")
        _exact_fields(
            root_identity,
            frozenset({
                "selector_id", "availability", "root_reference_id", "branch_id",
                "spin_binary64_hex", "omega", "angular_separation_constant",
                "owner_id", "owner_data_sha256", "owner_record",
            }),
            "campaign root identity",
        )
        for name in ("selector_id", "availability", "branch_id", "owner_id"):
            _string(root_identity[name], f"campaign root {name}")
        _digest(root_identity["owner_data_sha256"], "campaign root owner SHA-256")
        _mapping(root_identity["omega"], "campaign root omega")
        _mapping(
            root_identity["angular_separation_constant"],
            "campaign root angular separation constant",
        )
        _mapping(root_identity["owner_record"], "campaign root owner record")
        if (
            root_identity["root_reference_id"] != root_reference_id
            or root_identity["spin_binary64_hex"] != leaf.spin.hex()
            or root_identity["branch_id"]
            != "schwarzschild-overtone-continuation"
        ):
            raise ValueError("campaign root identity does not match its leaf")
        root_identity_sha256 = _digest(
            record["root_identity_sha256"], "campaign root identity SHA-256"
        )
        if hashlib.sha256(canonical_json_bytes(root_identity)).hexdigest() != root_identity_sha256:
            raise ValueError("campaign root identity SHA-256 is invalid")
        roots.setdefault(root_identity_sha256, root_identity)
        produced.append(leaf_id)
        payload_paths.add(payload_path)
    if not produced:
        raise ValueError("produced_records must contain a nonempty valid subset")
    expected_order = [item for item in B_PRIME_RELEASE_DOMAIN.production_leaf_ids if item in set(produced)]
    if produced != expected_order:
        raise ValueError("produced_records must follow frozen B′ leaf order")
    return tuple(produced), tuple(roots.values())


def validate_evidence_bundle(
    manifest: Mapping[str, object],
    *,
    bundle_directory: str | os.PathLike[str] | Path,
) -> EvidenceBundleSummary:
    """Validate an operator bundle structurally without admitting the provider."""

    mapping = _mapping(manifest, "evidence bundle")
    _finite_tree(mapping)
    _exact_fields(
        mapping,
        frozenset({
            "schema_version", "bundle_state", "contract", "producer", "source_files",
            "produced_records", "missing_leaf_ids", "comparator_fixtures", "bundle_sha256",
        }),
        "evidence bundle",
    )
    if _integer(mapping["schema_version"], "schema_version") != BUNDLE_SCHEMA_VERSION:
        raise ValueError("unsupported evidence-bundle schema_version")
    bundle_state = _string(mapping["bundle_state"], "bundle_state")
    if bundle_state not in _BUNDLE_STATES:
        raise ValueError("bundle_state must be partial-smoke or complete-operator")
    bundle_sha256 = _digest(mapping["bundle_sha256"], "bundle_sha256")
    if evidence_bundle_digest(mapping) != bundle_sha256:
        raise ValueError("bundle_sha256 does not authenticate canonical bundle content")
    campaign_spectral_receipt = _validate_contract(mapping["contract"])
    directory = Path(bundle_directory)
    sources = _validate_source_files(mapping["source_files"], directory)
    _validate_producer(mapping["producer"], sources)
    produced, campaign_roots = _validate_records(
        mapping["produced_records"], directory, sources
    )
    comparator_ids = _validate_comparators(mapping["comparator_fixtures"], sources)
    missing = [_string(item, "missing leaf ID") for item in _array(mapping["missing_leaf_ids"], "missing_leaf_ids")]
    if len(missing) != len(set(missing)):
        raise ValueError("missing_leaf_ids contains duplicates")
    required = list(B_PRIME_RELEASE_DOMAIN.production_leaf_ids)
    produced_set = set(produced)
    if produced_set & set(missing):
        raise ValueError("produced and missing leaf partitions overlap")
    expected_missing = [item for item in required if item not in produced_set]
    if missing != expected_missing:
        raise ValueError("produced and missing IDs must exactly partition frozen B′")
    expected_leaf_count = len(B_PRIME_RELEASE_DOMAIN.production_leaf_ids)
    if bundle_state == "complete-operator" and (
        len(produced) != expected_leaf_count or missing
    ):
        raise ValueError(
            "complete-operator requires exactly "
            f"{expected_leaf_count} produced and zero missing IDs"
        )
    if bundle_state == "complete-operator" and (
        len(campaign_roots) != campaign_spectral_receipt["root_count"]
        or hashlib.sha256(canonical_json_bytes(list(campaign_roots))).hexdigest()
        != campaign_spectral_receipt["root_set_sha256"]
    ):
        raise ValueError(
            "complete-operator campaign roots do not match the spectral receipt"
        )
    sampled = tuple(item for item in _OPERATOR_SMOKE_LEAF_IDS if item in produced_set)
    sampled += tuple(item for item in comparator_ids if item not in sampled)
    return EvidenceBundleSummary(
        bundle_state=bundle_state,
        bundle_sha256=bundle_sha256,
        produced_count=len(produced),
        missing_count=len(missing),
        comparator_count=len(comparator_ids),
        sampled_ids=sampled,
    )


def load_evidence_bundle(path: str | os.PathLike[str] | Path) -> EvidenceBundleSummary:
    """Load and validate a bundle directory or its manifest path."""

    requested = Path(path)
    manifest_path = requested / "evidence-bundle.json" if requested.is_dir() else requested

    def reject_constant(value: str) -> object:
        raise ValueError(f"manifest contains non-finite JSON constant {value}")

    try:
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8"),
            parse_constant=reject_constant,
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except UnicodeDecodeError as error:
        raise ValueError("evidence manifest must be UTF-8 JSON") from error
    return validate_evidence_bundle(
        _mapping(manifest, "evidence bundle"),
        bundle_directory=manifest_path.parent,
    )


def _git_blob_sha(data: bytes) -> str:
    material = f"blob {len(data)}\0".encode("ascii") + data
    return hashlib.sha1(material, usedforsecurity=False).hexdigest()


def _authenticated_fixture_bytes() -> tuple[list[dict[str, object]], dict[str, bytes]]:
    source_records: list[dict[str, object]] = []
    by_name: dict[str, bytes] = {}
    for repository_path, packaged_path, expected_blob, expected_sha256 in _FIXTURE_BINDINGS:
        data = (_DATA_DIRECTORY / packaged_path).read_bytes()
        actual_blob = _git_blob_sha(data)
        actual_sha256 = hashlib.sha256(data).hexdigest()
        if (actual_blob, actual_sha256) != (expected_blob, expected_sha256):
            raise ValueError(f"pinned fixture bytes failed authentication: {repository_path}")
        source_records.append({
            "repository": PINNED_FIXTURE_SOURCE_REPOSITORY,
            "repository_commit": PINNED_FIXTURE_SOURCE_COMMIT,
            "repository_path": repository_path,
            "git_blob_sha": expected_blob,
            "byte_size": len(data),
            "sha256": expected_sha256,
        })
        by_name[Path(packaged_path).name] = data
    return source_records, by_name


def _json_bytes(data: bytes, subject: str) -> object:
    try:
        value = json.loads(data, object_pairs_hook=_reject_duplicate_json_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"authenticated {subject} is not valid JSON") from error
    _finite_tree(value, subject)
    return value


def _pilot_components(files: Mapping[str, bytes]) -> list[dict[str, object]]:
    protocol = _mapping(_json_bytes(files["protocol.fixture"], "pilot protocol"), "pilot protocol")
    reductions = _array(_json_bytes(files["reduction.fixture"], "pilot reduction"), "pilot reduction")
    if protocol.get("component_count") != 9 or protocol.get("producer_protocol") != f"component-local-signed-amplitude-ladder-{_LEGACY_PROTOCOL_VERSION}":
        raise ValueError("pilot protocol identity is invalid")
    if len(reductions) != 2 or any(_mapping(item, "pilot reduction").get("uncertainty_origin") != _LOCAL_LADDER_ORIGIN for item in reductions):
        raise ValueError("pilot reductions do not preserve component-local evidence")
    mechanism_ids = {
        "horizon_admittance": "horizon-admittance",
        "fixed_r3": "exterior-fixed-r3",
        "light_ring": "exterior-light-ring",
    }
    expected_leaves = {
        (leaf.mode_label, leaf.coordinate, leaf.mechanism_id): leaf
        for leaf in B_PRIME_RELEASE_DOMAIN.production_leaves
        if leaf.role == "primary"
    }
    rows = list(csv.DictReader(io.StringIO(files["components.fixture"].decode("utf-8"), newline="")))
    result: list[dict[str, object]] = []
    for row in rows:
        mode = (int(row["ell"]), int(row["m"]), int(row["n"]))
        mode_label = f"{mode[0]}{mode[1]}{mode[2]}"
        spin = Fraction(row["spin"])
        mechanism_id = mechanism_ids.get(row["mechanism_id"])
        leaf = expected_leaves.get((mode_label, spin, mechanism_id or ""))
        if leaf is None or row["s"] != "-2" or row["polarization"] != "gravitational":
            raise ValueError("pilot component identity is outside the migration subset")
        for field in ("response_re", "response_im", "uncertainty_radius_abs", "root_radius_abs"):
            if not math.isfinite(float(row[field])):
                raise ValueError("pilot component contains a non-finite value")
        if row["uncertainty_origin"] != _LOCAL_LADDER_ORIGIN:
            raise ValueError("pilot component lost its local-ladder claim ceiling")
        result.append({
            "fixture_id": f"pilot:{mode_label}:{spin.numerator}/{spin.denominator}:{mechanism_id}",
            "b_prime_leaf_id": leaf.leaf_id,
            "mode_label": mode_label,
            "spin_exact": (spin.numerator, spin.denominator),
            "mechanism_id": mechanism_id,
            "numerical_state": row["status"],
            "uncertainty_origin": row["uncertainty_origin"],
            "disposition": "migration-only-not-operator-evidence",
        })
    expected = {
        (mode, mechanism)
        for mode in ("220", "330", "440")
        for mechanism in mechanism_ids.values()
    }
    if len(result) != 9 or {(item["mode_label"], item["mechanism_id"]) for item in result} != expected:
        raise ValueError("authenticated pilot must contain exactly nine components")
    return result


def _cubic_rows(files: Mapping[str, bytes]) -> list[dict[str, object]]:
    status = _mapping(_json_bytes(files["status.fixture"], "cubic status"), "cubic status")
    benchmark = _mapping(status.get("benchmark"), "cubic benchmark")
    if (
        status.get("resolved_benchmark_row_count") != 8
        or benchmark.get("theory") != "parity-even-cubic-higher-curvature-eft"
        or benchmark.get("polarizations") != ["plus", "minus"]
        or benchmark.get("spins") != [0.0, 0.3, 0.5, 0.7]
    ):
        raise ValueError("cubic status does not bind the exact comparator set")
    rows = list(csv.DictReader(io.StringIO(files["resolved.fixture"].decode("utf-8"), newline="")))
    result: list[dict[str, object]] = []
    for row in rows:
        mode = (int(row["ell"]), int(row["m"]), int(row["overtone_branch"]))
        spin = Fraction(row["spin_over_mass"])
        polarization = row["polarization"]
        if mode != (2, 2, 0) or spin not in {Fraction(0), Fraction(3, 10), Fraction(1, 2), Fraction(7, 10)} or polarization not in {"plus", "minus"}:
            raise ValueError("cubic row identity is outside the comparator-only set")
        for field in ("calculated_shift_centre_real", "calculated_shift_centre_imag", "calculated_disk_radius"):
            if not math.isfinite(float(row[field])):
                raise ValueError("cubic comparator contains a non-finite value")
        result.append({
            "fixture_id": f"cubic:220:{spin.numerator}/{spin.denominator}:{polarization}",
            "mode": mode,
            "spin_exact": (spin.numerator, spin.denominator),
            "polarization": polarization,
            "theory_id": "parity-even-cubic-higher-curvature-eft",
            "disposition": "comparator-only",
        })
    expected = {
        (spin, polarization)
        for spin in (Fraction(0), Fraction(3, 10), Fraction(1, 2), Fraction(7, 10))
        for polarization in ("plus", "minus")
    }
    if len(result) != 8 or {(Fraction(*item["spin_exact"]), item["polarization"]) for item in result} != expected:
        raise ValueError("authenticated cubic comparator must contain exactly eight rows")
    return result


def _legacy_local_ladder_ledger(pilot: list[dict[str, object]]) -> list[dict[str, object]]:
    pilot_by_identity = {
        (item["mode_label"], item["spin_exact"], item["mechanism_id"]): item
        for item in pilot
    }
    spins = (
        Fraction(19, 20), Fraction(97, 100), Fraction(49, 50), Fraction(99, 100),
        Fraction(199, 200), Fraction(997, 1000), Fraction(999, 1000),
    )
    mechanisms = (
        "horizon-admittance", "exterior-fixed-r3", "exterior-light-ring",
        "exterior-throat-kappa", "exterior-alpha-zero", "exterior-alpha-half",
        "exterior-alpha-one",
    )
    result: list[dict[str, object]] = []
    for mode_label in ("220", "330", "440"):
        for spin in spins:
            spin_exact = (spin.numerator, spin.denominator)
            for mechanism_id in mechanisms:
                identity = (mode_label, spin_exact, mechanism_id)
                base: dict[str, object] = {
                    "mode_label": mode_label,
                    "spin_exact": spin_exact,
                    "mechanism_id": mechanism_id,
                }
                if identity in pilot_by_identity:
                    base.update({
                        "state": "AUTHENTICATED_PILOT_SUBSET",
                        "fixture_id": pilot_by_identity[identity]["fixture_id"],
                        "uncertainty_origin": _LOCAL_LADDER_ORIGIN,
                    })
                else:
                    base["state"] = "MISSING_SOURCE_EVIDENCE"
                result.append(base)
    return result


def load_representative_fixture_receipt() -> dict[str, object]:
    """Authenticate and normalize only the pinned migration/comparator fixtures."""

    source_files, files = _authenticated_fixture_bytes()
    pilot = _pilot_components(files)
    cubic = _cubic_rows(files)
    receipt: dict[str, object] = {
        "schema_version": 1,
        "source_repository": PINNED_FIXTURE_SOURCE_REPOSITORY,
        "source_commit": PINNED_FIXTURE_SOURCE_COMMIT,
        "source_files": source_files,
        "pilot_claim_ceiling": "legacy-component-local-migration-only-not-operator-evidence",
        "pilot_components": pilot,
        "cubic_claim_ceiling": "comparator-only-never-production-completeness",
        "cubic_comparator_rows": cubic,
        "legacy_local_ladder_ledger": _legacy_local_ladder_ledger(pilot),
        "operator_smoke_leaf_ids": list(_OPERATOR_SMOKE_LEAF_IDS),
        "fixture_smoke_ids": [
            "pilot:220:19/20:exterior-light-ring",
            "pilot:440:19/20:horizon-admittance",
            "cubic:220:0/1:plus",
            "cubic:220:7/10:minus",
        ],
        "release_admissible": False,
    }
    receipt["receipt_sha256"] = hashlib.sha256(canonical_json_bytes(receipt)).hexdigest()
    return receipt
