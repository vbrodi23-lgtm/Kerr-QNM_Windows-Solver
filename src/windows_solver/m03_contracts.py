"""Fail-closed TASK-012 contracts for M03 spectral-field work.

This module adapts already-admitted spectral payloads.  It does not execute a
solver, compute a field, or admit an M03 scientific provider.
"""

from __future__ import annotations

from dataclasses import dataclass, fields as dataclass_fields
from enum import Enum
import hashlib
import json
import math
import re
from types import MappingProxyType
from typing import Mapping, TypeVar

from .precision_tiers import (
    PrecisionTierPresentation,
    precision_tier_presentation,
)


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_FLOAT_HEX = re.compile(
    r"-?0x[0-9a-f]+(?:\.[0-9a-f]+)?p[+-][0-9]+\Z"
)
_TERMINAL_M02_STATES = frozenset({"PRODUCED", "UNRESOLVED"})
_M02_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "scientific_computation_identity_sha256",
        "leaf_id",
        "record",
        "canonical_leaf_record_sha256",
        "terminal_state",
        "stage_count",
        "created_utc",
        "source_type",
        "receipt_sha256",
    }
)
_M02_RECEIPT_SOURCE_TYPES = frozenset(
    {"originating-campaign", "imported-authenticated-checkpoint"}
)


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("JSON object keys must be strings")
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return value
    raise TypeError(f"value is not JSON-compatible: {type(value).__name__}")


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("JSON object keys must be strings")
        return MappingProxyType(
            {key: _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return value
    raise TypeError(f"value is not JSON-compatible: {type(value).__name__}")


class _FactoryOnlyContract:
    __slots__ = ()

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise TypeError("contract records must be created by a validated factory")


_ContractT = TypeVar("_ContractT", bound=_FactoryOnlyContract)


def _construct_contract(
    contract_type: type[_ContractT], /, **values: object
) -> _ContractT:
    expected = {field.name for field in dataclass_fields(contract_type)}
    if set(values) != expected:
        raise RuntimeError("internal contract construction fields are invalid")
    instance = object.__new__(contract_type)
    for name, value in values.items():
        object.__setattr__(instance, name, value)
    return instance


def _mapping(value: object, subject: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{subject} must be an object")
    return value


def _exact_fields(
    value: Mapping[str, object], expected: frozenset[str], subject: str
) -> None:
    if set(value) != set(expected):
        raise ValueError(f"{subject} fields are invalid")


def _nonempty(value: object, subject: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{subject} must be a non-empty string")
    return value


def _hash(value: object, subject: str) -> str:
    value = _nonempty(value, subject)
    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"{subject} must be a lowercase SHA-256")
    return value


def _integer(value: object, subject: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{subject} must be an integer")
    return value


def _finite(value: object, subject: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{subject} must be finite")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{subject} must be finite")
    return result


def _ratio(value: object, subject: str) -> dict[str, int]:
    value = _mapping(value, subject)
    _exact_fields(value, frozenset({"numerator", "denominator"}), subject)
    numerator = _integer(value["numerator"], f"{subject} numerator")
    denominator = _integer(value["denominator"], f"{subject} denominator")
    if denominator <= 0:
        raise ValueError(f"{subject} denominator must be positive")
    divisor = math.gcd(numerator, denominator)
    if divisor != 1:
        raise ValueError(f"{subject} must be a reduced rational")
    return {"numerator": numerator, "denominator": denominator}


def _sampling_coordinate(value: object) -> dict[str, object]:
    coordinate = _mapping(value, "M02 sampling coordinate")
    _exact_fields(
        coordinate,
        frozenset({"coordinate_id", "exact", "value", "transformation_id"}),
        "M02 sampling coordinate",
    )
    return {
        "coordinate_id": _nonempty(
            coordinate["coordinate_id"], "M02 sampling coordinate ID"
        ),
        "exact": _ratio(
            coordinate["exact"], "M02 sampling coordinate exact value"
        ),
        "transformation_id": _nonempty(
            coordinate["transformation_id"],
            "M02 sampling coordinate transformation ID",
        ),
        "value": _finite(
            coordinate["value"], "M02 sampling coordinate value"
        ),
    }


class M03ArtifactKind(str, Enum):
    RADIAL_ANGULAR_FIELD = "radial-angular-field"
    COMODE_NORMALIZATION = "co-mode-normalization"
    POLE_RESIDUE = "pole-residue"
    KAPPA_GENEALOGY = "kappa-genealogy"
    BRANCH_CLASSIFICATION = "zdm-dm-classification"
    NHEK_MATCH = "nhek-match"
    PROVIDER_ADMISSION = "provider-admission"


class M03EvidenceState(str, Enum):
    NOT_RUN = "NOT_RUN"
    BLOCKED_HUMAN_MATH_REVIEW = "BLOCKED_HUMAN_MATH_REVIEW"
    PRODUCED = "PRODUCED"
    UNRESOLVED = "UNRESOLVED"
    REJECTED = "REJECTED"
    ADMITTED = "ADMITTED"


@dataclass(frozen=True, slots=True, init=False)
class M03RootSeed(_FactoryOnlyContract):
    mode: Mapping[str, object]
    source_realization: str
    spin: float
    spin_identity: Mapping[str, object]
    spin_binary64_hex: str
    frequency: Mapping[str, object]
    angular_separation_constant_A: Mapping[str, object]
    catalog_id: str
    catalog_data_sha256: str
    overlay_data_sha256: str
    identity_sha256: str

    @classmethod
    def from_spectral_root(
        cls,
        root: Mapping[str, object],
        *,
        catalog_id: str,
        catalog_data_sha256: str,
        overlay_data_sha256: str,
    ) -> "M03RootSeed":
        root = _mapping(root, "spectral root")
        catalog_id = _nonempty(catalog_id, "catalog ID")
        catalog_data_sha256 = _hash(
            catalog_data_sha256, "catalog data identity"
        )
        overlay_data_sha256 = _hash(
            overlay_data_sha256, "overlay data identity"
        )
        mode = _mapping(root.get("mode"), "spectral root mode")
        _exact_fields(
            mode,
            frozenset({"s", "ell", "m", "n", "branch", "polarization"}),
            "spectral root mode",
        )
        s = _integer(mode["s"], "mode s")
        ell = _integer(mode["ell"], "mode ell")
        m = _integer(mode["m"], "mode m")
        n = _integer(mode["n"], "mode n")
        branch = _nonempty(mode["branch"], "mode branch")
        polarization = _nonempty(mode["polarization"], "mode polarization")
        if (
            s != -2
            or ell not in (2, 3, 4)
            or abs(m) > ell
            or n not in (0, 1, 2)
            or branch != "schwarzschild-overtone-continuation"
            or polarization != "gravitational"
        ):
            raise ValueError(
                "spectral root mode is outside the admitted M03 catalogue domain"
            )
        normalized_mode = {
            "s": s,
            "ell": ell,
            "m": m,
            "n": n,
            "branch": branch,
            "polarization": polarization,
        }

        spin = _finite(root.get("spin"), "spectral root spin")
        if not -1.0 < spin < 1.0:
            raise ValueError("spectral root spin must satisfy -1 < a/M < 1")
        spin_hex = _nonempty(
            root.get("spin_binary64_hex"), "spectral root binary64 spin"
        )
        if _FLOAT_HEX.fullmatch(spin_hex) is None or spin_hex != spin.hex():
            raise ValueError("spectral root binary64 spin identity is invalid")

        has_base = "spin_exact" in root
        has_overlay = (
            "source_coordinate" in root or "spin_binary64_ratio" in root
        )
        if has_base == has_overlay:
            raise ValueError("ambiguous root realization")
        if has_base:
            source_realization = "base-catalogue"
            spin_exact = _ratio(root["spin_exact"], "base exact spin")
            if (
                spin_exact["numerator"] / spin_exact["denominator"]
                != spin
            ):
                raise ValueError(
                    "base exact spin is inconsistent with binary64 spin"
                )
            spin_identity: dict[str, object] = {"spin_exact": spin_exact}
        else:
            if not (
                "source_coordinate" in root and "spin_binary64_ratio" in root
            ):
                raise ValueError("overlay root identity is incomplete")
            source_realization = "exact-selector-overlay"
            coordinate = _mapping(
                root["source_coordinate"], "overlay source coordinate"
            )
            _exact_fields(
                coordinate,
                frozenset(
                    {
                        "coordinate_id",
                        "numerator",
                        "denominator",
                        "transformation_id",
                    }
                ),
                "overlay source coordinate",
            )
            coordinate_ratio = _ratio(
                {
                    "numerator": coordinate["numerator"],
                    "denominator": coordinate["denominator"],
                },
                "overlay source coordinate",
            )
            ratio = _ratio(
                root["spin_binary64_ratio"], "overlay binary64 spin ratio"
            )
            if (ratio["numerator"], ratio["denominator"]) != spin.as_integer_ratio():
                raise ValueError("overlay binary64 spin ratio is invalid")
            spin_identity = {
                "source_coordinate": {
                    "coordinate_id": _nonempty(
                        coordinate["coordinate_id"], "source coordinate ID"
                    ),
                    **coordinate_ratio,
                    "transformation_id": _nonempty(
                        coordinate["transformation_id"],
                        "source transformation ID",
                    ),
                },
                "spin_binary64_ratio": ratio,
            }

        frequency = _mapping(root.get("frequency"), "spectral root frequency")
        _exact_fields(
            frequency,
            frozenset({"real", "imaginary", "units"}),
            "spectral root frequency",
        )
        omega_real = _finite(frequency["real"], "frequency real part")
        omega_imaginary = _finite(
            frequency["imaginary"], "frequency imaginary part"
        )
        if frequency["units"] != "Momega" or omega_imaginary >= 0.0:
            raise ValueError("spectral root must be a damped Momega root")
        normalized_frequency = {
            "real": omega_real,
            "imaginary": omega_imaginary,
            "units": "Momega",
        }

        angular = _mapping(
            root.get("angular_separation_constant_A"),
            "spectral angular separation constant",
        )
        _exact_fields(
            angular,
            frozenset({"real", "imaginary"}),
            "spectral angular separation constant",
        )
        normalized_angular = {
            "real": _finite(angular["real"], "angular A real part"),
            "imaginary": _finite(
                angular["imaginary"], "angular A imaginary part"
            ),
        }

        identity = {
            "schema_version": 1,
            "mode": normalized_mode,
            "source_realization": source_realization,
            "spin": spin,
            "spin_identity": spin_identity,
            "spin_binary64_hex": spin_hex,
            "frequency": normalized_frequency,
            "angular_separation_constant_A": normalized_angular,
            "catalog_id": catalog_id,
            "catalog_data_sha256": catalog_data_sha256,
            "overlay_data_sha256": overlay_data_sha256,
        }
        digest = hashlib.sha256(_canonical_json_bytes(identity)).hexdigest()
        return _construct_contract(
            cls,
            mode=_freeze(normalized_mode),  # type: ignore[arg-type]
            source_realization=source_realization,
            spin=spin,
            spin_identity=_freeze(spin_identity),  # type: ignore[arg-type]
            spin_binary64_hex=spin_hex,
            frequency=_freeze(normalized_frequency),  # type: ignore[arg-type]
            angular_separation_constant_A=_freeze(  # type: ignore[arg-type]
                normalized_angular
            ),
            catalog_id=catalog_id,
            catalog_data_sha256=catalog_data_sha256,
            overlay_data_sha256=overlay_data_sha256,
            identity_sha256=digest,
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "mode": _plain(self.mode),
            "source_realization": self.source_realization,
            "spin": self.spin,
            "spin_identity": _plain(self.spin_identity),
            "spin_binary64_hex": self.spin_binary64_hex,
            "frequency": _plain(self.frequency),
            "angular_separation_constant_A": _plain(
                self.angular_separation_constant_A
            ),
            "catalog_id": self.catalog_id,
            "catalog_data_sha256": self.catalog_data_sha256,
            "overlay_data_sha256": self.overlay_data_sha256,
            "identity_sha256": self.identity_sha256,
        }


def adapt_spectral_payload(
    payload: Mapping[str, object],
) -> tuple[M03RootSeed, ...]:
    payload = _mapping(payload, "spectral payload")
    if payload.get("schema_version") != 1:
        raise ValueError("spectral payload schema version is invalid")
    catalog_id = _nonempty(payload.get("catalog_id"), "catalog ID")
    catalog_hash = _hash(
        payload.get("catalog_data_sha256"), "catalog data identity"
    )
    overlay_hash = _hash(
        payload.get("overlay_data_sha256"), "overlay data identity"
    )
    physics = _mapping(payload.get("physics_contract"), "spectral physics contract")
    if (
        physics.get("spin_weight") != -2
        or physics.get("time_dependence") != "exp(-i omega t)"
        or physics.get("frequency_units") != "Momega"
        or physics.get("angular_eigenvalue") != "A"
        or physics.get("pure_kerr") is not True
        or physics.get("boundary_conditions")
        != {"horizon": "ingoing", "infinity": "outgoing"}
    ):
        raise ValueError("spectral physics contract is incompatible with M03")
    roots = payload.get("roots")
    if not isinstance(roots, list):
        raise ValueError("spectral payload roots must be an array")
    count = _integer(
        payload.get("requested_root_count"), "requested spectral root count"
    )
    if count != len(roots):
        raise ValueError("requested spectral root count does not match roots")
    result = tuple(
        M03RootSeed.from_spectral_root(
            _mapping(root, "spectral root"),
            catalog_id=catalog_id,
            catalog_data_sha256=catalog_hash,
            overlay_data_sha256=overlay_hash,
        )
        for root in roots
    )
    identities = [item.identity_sha256 for item in result]
    if len(identities) != len(set(identities)):
        raise ValueError("duplicate M03 root seed")
    return result


@dataclass(frozen=True, slots=True, init=False)
class M02LineageAnchor(_FactoryOnlyContract):
    leaf_id: str
    terminal_state: str
    receipt_sha256: str
    canonical_leaf_record_sha256: str
    scientific_computation_identity_sha256: str
    root_identity_sha256: str | None
    root_reference_id: str | None
    equation_id: str | None
    backend_identity_sha256: str | None
    policy_sha256: str | None
    sampling_coordinate: Mapping[str, object] | None
    precision_tier: PrecisionTierPresentation
    reconciliation_state: str
    identity_sha256: str

    @classmethod
    def from_receipt(
        cls, receipt: Mapping[str, object]
    ) -> "M02LineageAnchor":
        receipt = _mapping(receipt, "M02 solved-leaf receipt")
        _exact_fields(receipt, _M02_RECEIPT_FIELDS, "M02 solved-leaf receipt")
        if receipt.get("schema_version") != 1:
            raise ValueError("M02 receipt schema version is invalid")
        terminal_state = _nonempty(
            receipt.get("terminal_state"), "M02 terminal state"
        )
        if terminal_state not in _TERMINAL_M02_STATES:
            raise ValueError("M02 solved-leaf receipt terminal state is invalid")
        if receipt.get("source_type") not in _M02_RECEIPT_SOURCE_TYPES:
            raise ValueError("M02 solved-leaf receipt source type is invalid")
        _nonempty(receipt.get("created_utc"), "M02 receipt creation timestamp")
        leaf_id = _nonempty(receipt.get("leaf_id"), "M02 leaf ID")
        record = _mapping(receipt.get("record"), "M02 leaf record")
        if (
            record.get("leaf_id") != leaf_id
            or record.get("state") != terminal_state
            or record.get("computed") is not True
        ):
            raise ValueError("M02 receipt and record identity do not match")
        stages = record.get("stages")
        if not isinstance(stages, list) or not stages:
            raise ValueError("M02 receipt must contain at least one stage")
        stage_count = _integer(receipt.get("stage_count"), "M02 stage count")
        if stage_count < 1 or stage_count != len(stages):
            raise ValueError("M02 receipt stage count is invalid")
        record_sha256 = _hash(
            record.get("record_sha256"), "M02 canonical leaf record identity"
        )
        canonical_record_sha256 = _hash(
            receipt.get("canonical_leaf_record_sha256"),
            "M02 canonical leaf record identity",
        )
        record_content = {
            key: item for key, item in record.items() if key != "record_sha256"
        }
        if (
            record_sha256 != canonical_record_sha256
            or hashlib.sha256(_canonical_json_bytes(record_content)).hexdigest()
            != canonical_record_sha256
        ):
            raise ValueError("M02 canonical record digest is invalid")
        receipt_sha256 = _hash(
            receipt.get("receipt_sha256"), "M02 receipt identity"
        )
        sealed_receipt = {
            key: item for key, item in receipt.items() if key != "receipt_sha256"
        }
        if (
            hashlib.sha256(_canonical_json_bytes(sealed_receipt)).hexdigest()
            != receipt_sha256
        ):
            raise ValueError("M02 outer receipt digest is invalid")
        last_stage = _mapping(stages[-1], "M02 terminal stage")
        precision_tier = precision_tier_presentation(last_stage.get("digits"))

        root_identity: str | None = None
        root_reference: str | None = None
        equation_id: str | None = None
        backend_hash: str | None = None
        policy_hash: str | None = None
        sampling_coordinate: Mapping[str, object] | None = None
        if terminal_state == "PRODUCED":
            component = _mapping(
                last_stage.get("component_result"), "M02 component result"
            )
            result = _mapping(component.get("result"), "M02 scientific result")
            lineage = _mapping(result.get("lineage"), "M02 result lineage")
            baseline = _mapping(result.get("baseline"), "M02 baseline")
            root_identity = _hash(
                lineage.get("root_identity_sha256"), "M02 root identity"
            )
            root_reference = _nonempty(
                lineage.get("root_reference_id"), "M02 root reference"
            )
            if baseline.get("root_reference_id") != root_reference:
                raise ValueError("M02 root references do not agree")
            equation_id = _nonempty(
                lineage.get("equation_id"), "M02 equation identity"
            )
            if baseline.get("equation_id") != equation_id:
                raise ValueError("M02 equation identities do not agree")
            backend_hash = _hash(
                lineage.get("backend_identity_sha256"), "M02 backend identity"
            )
            policy_hash = _hash(
                lineage.get("policy_sha256"), "M02 policy identity"
            )
            sampling_coordinate = _freeze(
                _sampling_coordinate(lineage.get("sampling_coordinate"))
            )  # type: ignore[assignment]

        material = {
            "schema_version": 1,
            "leaf_id": leaf_id,
            "terminal_state": terminal_state,
            "receipt_sha256": receipt_sha256,
            "canonical_leaf_record_sha256": canonical_record_sha256,
            "scientific_computation_identity_sha256": _hash(
                receipt.get("scientific_computation_identity_sha256"),
                "M02 scientific computation identity",
            ),
            "root_identity_sha256": root_identity,
            "root_reference_id": root_reference,
            "equation_id": equation_id,
            "backend_identity_sha256": backend_hash,
            "policy_sha256": policy_hash,
            "sampling_coordinate": _plain(sampling_coordinate),
            "precision_tier": precision_tier.to_mapping(),
            "reconciliation_state": "UNRECONCILED",
        }
        identity = hashlib.sha256(_canonical_json_bytes(material)).hexdigest()
        return _construct_contract(
            cls,
            leaf_id=leaf_id,
            terminal_state=terminal_state,
            receipt_sha256=material["receipt_sha256"],  # type: ignore[arg-type]
            canonical_leaf_record_sha256=material[
                "canonical_leaf_record_sha256"
            ],  # type: ignore[arg-type]
            scientific_computation_identity_sha256=material[
                "scientific_computation_identity_sha256"
            ],  # type: ignore[arg-type]
            root_identity_sha256=root_identity,
            root_reference_id=root_reference,
            equation_id=equation_id,
            backend_identity_sha256=backend_hash,
            policy_sha256=policy_hash,
            sampling_coordinate=sampling_coordinate,
            precision_tier=precision_tier,
            reconciliation_state="UNRECONCILED",
            identity_sha256=identity,
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "leaf_id": self.leaf_id,
            "terminal_state": self.terminal_state,
            "receipt_sha256": self.receipt_sha256,
            "canonical_leaf_record_sha256": (
                self.canonical_leaf_record_sha256
            ),
            "scientific_computation_identity_sha256": (
                self.scientific_computation_identity_sha256
            ),
            "root_identity_sha256": self.root_identity_sha256,
            "root_reference_id": self.root_reference_id,
            "equation_id": self.equation_id,
            "backend_identity_sha256": self.backend_identity_sha256,
            "policy_sha256": self.policy_sha256,
            "sampling_coordinate": _plain(self.sampling_coordinate),
            "precision_tier": self.precision_tier.to_mapping(),
            "reconciliation_state": self.reconciliation_state,
            "identity_sha256": self.identity_sha256,
        }


@dataclass(frozen=True, slots=True, init=False)
class M03CacheIdentity(_FactoryOnlyContract):
    seed_identity_sha256: str
    artifact_kind: M03ArtifactKind
    equation_version: str
    convention_version: str
    radial_grid: Mapping[str, object]
    angular_grid: Mapping[str, object]
    normalization_id: str
    pairing_id: str
    backend_revisions: Mapping[str, object]
    precision_tier: PrecisionTierPresentation
    validation_policy: Mapping[str, object]
    reconciled_m02_lineage_sha256: str | None
    cache_sha256: str

    @classmethod
    def build(
        cls,
        *,
        seed: M03RootSeed,
        artifact_kind: M03ArtifactKind,
        equation_version: str,
        convention_version: str,
        radial_grid: Mapping[str, object],
        angular_grid: Mapping[str, object],
        normalization_id: str,
        pairing_id: str,
        backend_revisions: Mapping[str, object],
        precision_tier: PrecisionTierPresentation,
        validation_policy: Mapping[str, object],
        m02_lineage: M02LineageAnchor | None,
    ) -> "M03CacheIdentity":
        if not isinstance(seed, M03RootSeed):
            raise TypeError("M03 cache identity requires an M03RootSeed")
        if not isinstance(artifact_kind, M03ArtifactKind):
            raise TypeError("M03 cache artifact kind is invalid")
        if not isinstance(precision_tier, PrecisionTierPresentation):
            raise TypeError("M03 cache precision tier is invalid")
        try:
            canonical_precision = precision_tier_presentation(
                precision_tier.legacy_tier_value
            )
        except ValueError as error:
            raise ValueError("M03 cache requires a canonical precision tier") from error
        if precision_tier != canonical_precision:
            raise ValueError("M03 cache requires a canonical precision tier")
        lineage_hash: str | None = None
        if m02_lineage is not None:
            if not isinstance(m02_lineage, M02LineageAnchor):
                raise TypeError("M02 lineage anchor is invalid")
            if m02_lineage.reconciliation_state != "RECONCILED":
                raise ValueError(
                    "M02 lineage must be explicitly reconciled before cache binding"
                )
            lineage_hash = m02_lineage.identity_sha256
        material = {
            "schema_version": 1,
            "seed_identity_sha256": seed.identity_sha256,
            "artifact_kind": artifact_kind.value,
            "equation_version": _nonempty(
                equation_version, "M03 equation version"
            ),
            "convention_version": _nonempty(
                convention_version, "M03 convention version"
            ),
            "radial_grid": _plain(_mapping(radial_grid, "M03 radial grid")),
            "angular_grid": _plain(_mapping(angular_grid, "M03 angular grid")),
            "normalization_id": _nonempty(
                normalization_id, "M03 normalization ID"
            ),
            "pairing_id": _nonempty(pairing_id, "M03 pairing ID"),
            "backend_revisions": _plain(
                _mapping(backend_revisions, "M03 backend revisions")
            ),
            "precision_tier": precision_tier.to_mapping(),
            "validation_policy": _plain(
                _mapping(validation_policy, "M03 validation policy")
            ),
            "reconciled_m02_lineage_sha256": lineage_hash,
        }
        try:
            digest = hashlib.sha256(_canonical_json_bytes(material)).hexdigest()
        except (TypeError, ValueError) as error:
            raise ValueError("M03 cache identity must be canonical JSON") from error
        return _construct_contract(
            cls,
            seed_identity_sha256=seed.identity_sha256,
            artifact_kind=artifact_kind,
            equation_version=material["equation_version"],  # type: ignore[arg-type]
            convention_version=material["convention_version"],  # type: ignore[arg-type]
            radial_grid=_freeze(material["radial_grid"]),  # type: ignore[arg-type]
            angular_grid=_freeze(material["angular_grid"]),  # type: ignore[arg-type]
            normalization_id=material["normalization_id"],  # type: ignore[arg-type]
            pairing_id=material["pairing_id"],  # type: ignore[arg-type]
            backend_revisions=_freeze(  # type: ignore[arg-type]
                material["backend_revisions"]
            ),
            precision_tier=precision_tier,
            validation_policy=_freeze(  # type: ignore[arg-type]
                material["validation_policy"]
            ),
            reconciled_m02_lineage_sha256=lineage_hash,
            cache_sha256=digest,
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "seed_identity_sha256": self.seed_identity_sha256,
            "artifact_kind": self.artifact_kind.value,
            "equation_version": self.equation_version,
            "convention_version": self.convention_version,
            "radial_grid": _plain(self.radial_grid),
            "angular_grid": _plain(self.angular_grid),
            "normalization_id": self.normalization_id,
            "pairing_id": self.pairing_id,
            "backend_revisions": _plain(self.backend_revisions),
            "precision_tier": self.precision_tier.to_mapping(),
            "validation_policy": _plain(self.validation_policy),
            "reconciled_m02_lineage_sha256": (
                self.reconciled_m02_lineage_sha256
            ),
            "cache_sha256": self.cache_sha256,
        }


_MATH_REVIEW_BLOCKERS = {
    M03ArtifactKind.COMODE_NORMALIZATION: (
        "HUMAN_MATH_REVIEW_REQUIRED: freeze the separated adjoint equation, "
        "pairing, phase convention, and normalization identity"
    ),
    M03ArtifactKind.POLE_RESIDUE: (
        "HUMAN_MATH_REVIEW_REQUIRED: derive the Green-function numerator, "
        "determinant derivative, source, and readout conventions"
    ),
    M03ArtifactKind.BRANCH_CLASSIFICATION: (
        "HUMAN_MATH_REVIEW_REQUIRED: freeze classification observables, "
        "κ-domain, uncertainty model, and transition policy"
    ),
    M03ArtifactKind.NHEK_MATCH: (
        "HUMAN_MATH_REVIEW_REQUIRED: supply the matched-asymptotic formula, "
        "overlap region, convention map, and error model"
    ),
    M03ArtifactKind.PROVIDER_ADMISSION: (
        "UPSTREAM_EVIDENCE_REQUIRED: TASK-012 defines contracts but cannot "
        "admit the M03 provider"
    ),
}

_REQUIRED_VALIDATION_FIELDS = {
    M03ArtifactKind.RADIAL_ANGULAR_FIELD: frozenset(
        {
            "field_equation_residual_abs",
            "boundary_residuals",
            "wronskian_relative_drift",
            "resolution_comparison",
        }
    ),
    M03ArtifactKind.KAPPA_GENEALOGY: frozenset(
        {
            "node_count",
            "edge_count",
            "overlap_guards",
            "continuation_invariants",
            "exact_node_polish",
        }
    ),
}

_FIELD_VALIDATION_POLICY_FIELDS = frozenset(
    {
        "field_equation_residual_abs_max",
        "horizon_boundary_residual_abs_max",
        "infinity_boundary_residual_abs_max",
        "wronskian_relative_drift_max",
        "resolution_relative_field_difference_max",
    }
)
_GENEALOGY_VALIDATION_POLICY_FIELDS = frozenset(
    {
        "minimum_overlap",
        "maximum_exact_node_residual_abs",
        "require_branch_resolved",
    }
)


@dataclass(frozen=True, slots=True, init=False)
class M03ArtifactEnvelope(_FactoryOnlyContract):
    kind: M03ArtifactKind
    seed_identity_sha256: str
    cache_sha256: str
    evidence_state: M03EvidenceState
    payload: Mapping[str, object]
    blockers: tuple[str, ...]
    envelope_sha256: str

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": self.kind.value,
            "seed_identity_sha256": self.seed_identity_sha256,
            "cache_sha256": self.cache_sha256,
            "evidence_state": self.evidence_state.value,
            "payload": _plain(self.payload),
            "blockers": list(self.blockers),
            "envelope_sha256": self.envelope_sha256,
        }


def _validate_produced_payload(
    kind: M03ArtifactKind,
    payload: Mapping[str, object],
    validation_policy: Mapping[str, object],
) -> None:
    required = _REQUIRED_VALIDATION_FIELDS.get(kind)
    if required is None:
        raise ValueError("M03 artifact remains blocked by human math review")
    validation = _mapping(payload.get("validation"), "M03 validation")
    missing = sorted(required - set(validation))
    if missing:
        raise ValueError(
            "missing validation fields: " + ", ".join(missing)
        )
    unknown = sorted(set(validation) - required)
    if unknown:
        raise ValueError(
            "unknown validation fields: " + ", ".join(unknown)
        )
    if kind is M03ArtifactKind.RADIAL_ANGULAR_FIELD:
        _exact_fields(
            validation_policy,
            _FIELD_VALIDATION_POLICY_FIELDS,
            "field validation policy",
        )
        thresholds = {
            name: _finite(validation_policy[name], name)
            for name in _FIELD_VALIDATION_POLICY_FIELDS
        }
        if any(value < 0.0 for value in thresholds.values()):
            raise ValueError("field validation policy thresholds must be nonnegative")
        field_residual = _finite(
            validation["field_equation_residual_abs"],
            "field equation residual",
        )
        wronskian_drift = _finite(
            validation["wronskian_relative_drift"],
            "Wronskian relative drift",
        )
        boundaries = _mapping(
            validation["boundary_residuals"], "field boundary residuals"
        )
        _exact_fields(
            boundaries,
            frozenset({"horizon", "infinity"}),
            "field boundary residuals",
        )
        horizon_residual = _finite(boundaries["horizon"], "horizon residual")
        infinity_residual = _finite(
            boundaries["infinity"], "infinity residual"
        )
        resolution = _mapping(
            validation["resolution_comparison"], "field resolution comparison"
        )
        _exact_fields(
            resolution,
            frozenset({"relative_field_difference"}),
            "field resolution comparison",
        )
        resolution_difference = _finite(
            resolution["relative_field_difference"],
            "resolution relative field difference",
        )
        observations = (
            (field_residual, thresholds["field_equation_residual_abs_max"]),
            (horizon_residual, thresholds["horizon_boundary_residual_abs_max"]),
            (infinity_residual, thresholds["infinity_boundary_residual_abs_max"]),
            (wronskian_drift, thresholds["wronskian_relative_drift_max"]),
            (
                resolution_difference,
                thresholds["resolution_relative_field_difference_max"],
            ),
        )
        if any(observed < 0.0 or observed > maximum for observed, maximum in observations):
            raise ValueError("field validation evidence exceeds validation policy")
    if kind is M03ArtifactKind.KAPPA_GENEALOGY:
        _exact_fields(
            validation_policy,
            _GENEALOGY_VALIDATION_POLICY_FIELDS,
            "genealogy validation policy",
        )
        minimum_overlap = _finite(
            validation_policy["minimum_overlap"], "minimum overlap policy"
        )
        maximum_polish = _finite(
            validation_policy["maximum_exact_node_residual_abs"],
            "maximum exact-node residual policy",
        )
        if (
            not 0.0 <= minimum_overlap <= 1.0
            or maximum_polish < 0.0
            or validation_policy["require_branch_resolved"] is not True
        ):
            raise ValueError("genealogy validation policy is invalid")
        nodes = _integer(validation["node_count"], "genealogy node count")
        edges = _integer(validation["edge_count"], "genealogy edge count")
        if nodes < 1 or edges < 1:
            raise ValueError("genealogy node/edge counts are invalid")
        overlap = _mapping(validation["overlap_guards"], "genealogy overlap guards")
        invariants = _mapping(
            validation["continuation_invariants"],
            "genealogy continuation invariants",
        )
        polish = _mapping(
            validation["exact_node_polish"], "genealogy exact-node polish"
        )
        _exact_fields(overlap, frozenset({"minimum"}), "genealogy overlap guards")
        _exact_fields(
            invariants,
            frozenset({"branch_resolved"}),
            "genealogy continuation invariants",
        )
        _exact_fields(
            polish,
            frozenset({"maximum_residual_abs"}),
            "genealogy exact-node polish",
        )
        observed_overlap = _finite(overlap["minimum"], "observed overlap")
        observed_polish = _finite(
            polish["maximum_residual_abs"], "observed exact-node residual"
        )
        if (
            not 0.0 <= observed_overlap <= 1.0
            or observed_overlap < minimum_overlap
            or invariants["branch_resolved"] is not True
            or observed_polish < 0.0
            or observed_polish > maximum_polish
        ):
            raise ValueError(
                "genealogy evidence does not satisfy validation policy"
            )


def build_m03_envelope(
    *,
    kind: M03ArtifactKind,
    seed: M03RootSeed,
    cache_identity: M03CacheIdentity,
    evidence_state: M03EvidenceState,
    payload: Mapping[str, object],
) -> M03ArtifactEnvelope:
    if not isinstance(kind, M03ArtifactKind):
        raise TypeError("M03 artifact kind is invalid")
    if not isinstance(seed, M03RootSeed):
        raise TypeError("M03 artifact seed is invalid")
    if not isinstance(cache_identity, M03CacheIdentity):
        raise TypeError("M03 artifact cache identity is invalid")
    if cache_identity.artifact_kind is not kind:
        raise ValueError("M03 cache artifact kind does not match envelope")
    if cache_identity.seed_identity_sha256 != seed.identity_sha256:
        raise ValueError("M03 cache seed does not match envelope")
    if not isinstance(evidence_state, M03EvidenceState):
        raise TypeError("M03 evidence state is invalid")
    payload = _mapping(payload, "M03 artifact payload")
    if evidence_state is M03EvidenceState.ADMITTED:
        raise ValueError("TASK-012 cannot admit an M03 artifact")
    blocker = _MATH_REVIEW_BLOCKERS.get(kind)
    if evidence_state is M03EvidenceState.PRODUCED:
        if blocker is not None:
            raise ValueError("M03 artifact remains blocked by human math review")
        _validate_produced_payload(
            kind,
            payload,
            cache_identity.validation_policy,
        )
    blockers = (blocker,) if blocker is not None else ()
    material = {
        "schema_version": 1,
        "kind": kind.value,
        "seed_identity_sha256": seed.identity_sha256,
        "cache_sha256": cache_identity.cache_sha256,
        "evidence_state": evidence_state.value,
        "payload": _plain(payload),
        "blockers": list(blockers),
    }
    digest = hashlib.sha256(_canonical_json_bytes(material)).hexdigest()
    return _construct_contract(
        M03ArtifactEnvelope,
        kind=kind,
        seed_identity_sha256=seed.identity_sha256,
        cache_sha256=cache_identity.cache_sha256,
        evidence_state=evidence_state,
        payload=_freeze(payload),  # type: ignore[arg-type]
        blockers=blockers,
        envelope_sha256=digest,
    )
