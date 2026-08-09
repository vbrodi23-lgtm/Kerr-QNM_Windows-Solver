"""Deterministic B-prime campaign planning and selected orchestration.

This module is build-only infrastructure.  Planning resolves authenticated
installed roots but cannot start determinant work; execution always requires an
explicit injected component backend.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path, PureWindowsPath
import re
import tempfile
import time
from typing import Mapping, Sequence

from .contracts import canonical_json_bytes
from .linear_response import B_PRIME_RELEASE_DOMAIN, BPrimeLeaf
from .response_engine import (
    BackendIdentity,
    ComponentResult,
    NativeDeterminantAdapter,
    NativeResourceUnavailableError,
    NumericalPolicy,
    RECORDED_REPLAY_BACKEND_ID,
    RecordedReplayBackend,
    ResponseComponentJob,
    VettedNativeDeterminantKernel,
    run_component,
)
from .gsn_cache_producer import (
    GeneratedGsnCache,
    GsnCacheProductionError,
    ensure_generated_gsn_cache,
    parameter_pairs_for_selection,
)
from .julia_response_backend import (
    JuliaPrecisionRootBackend,
    JuliaResponseAdapter,
    JuliaResponseBackendError,
)
from .progress import PROGRESS_SCHEMA, ProgressEventKind, emit_progress, progress_scope
from .solved_leaf_cache import (
    SolvedLeafLookup,
    SolvedLeafLookupStatus,
    SolvedLeafStore,
)


CAMPAIGN_SCHEMA_VERSION = 2
_PRECISION_DIGITS = frozenset({64, 80, 120})
STAGE_SIGNED_ERROR_FAMILIES = (
    "signed-root",
    "centred-step-amplitude",
    "refinement-holdout",
    "truncation",
    "resolution-angular-refinement",
    "continuation-seed-path",
    "repeat-polish",
    "precision-ladder-discrepancy",
)
PREDECLARED_CAMPAIGN_SMOKE_LEAF_IDS = (
    "b-prime-leaf-9e5777728144433e089f9559b92b6e139e16115a5a53099f40403a45297aa3c3",
    "b-prime-leaf-7ef38d6f95c161d0b4c6650d470898c0742ad6ae8440e89956312344c0db6aac",
    "b-prime-leaf-87cd3420fc56eca66218e7414d17fd2803d59e719f3ab7c05b52a997f5cf0895",
    "b-prime-leaf-65d0a36c9075d255c2e78a5d8c8098ba745da0b4228c309d210cf05bdb9696ea",
    "b-prime-leaf-e0a48b72b4071c5c88c66955420dc2748cfeeac577b8fd1c399f171f5fa08475",
    "b-prime-leaf-0b1d66162e12c8b4e5ae0d2d360bc3f22f5f18f09e75fb84cd90d435292fed34",
    "b-prime-leaf-29476bee7eab938f57ee149c682a367cd3e65f2b3337e90aeae91009998d08a2",
    "b-prime-leaf-bef33f29593b50014490d255e06e90e6e0fb4b94868a7906d7d10db62522cbbd",
    "b-prime-leaf-0784febf73878ce64ed23c8284325d2dc5ca30ce97cdccb543c0250371d39d7a",
    "b-prime-leaf-05897ef7c7de073f4ae158d8ebce3da469eaebb0985a54bf30e8ed102c533d5f",
)
_RECORDED_CAMPAIGN_SMOKE_IDS = frozenset(
    PREDECLARED_CAMPAIGN_SMOKE_LEAF_IDS[index] for index in (0, 1, 4)
)


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _campaign_source_sha256() -> str:
    return _sha256({
        "path": "src/windows_solver/response_batches.py",
        "contract_version": CAMPAIGN_SCHEMA_VERSION,
    })


def _campaign_engine_identity_sha256() -> str:
    return _sha256({
        "path": "src/windows_solver/response_engine.py",
        "contract_version": 1,
    })


def resolve_campaign_relative_path(
    base_directory: str | os.PathLike[str] | Path, relative_path: str
) -> Path:
    if not isinstance(relative_path, str) or not relative_path:
        raise ValueError("campaign manifest path must be a nonempty string")
    normalized = relative_path.replace("\\", "/")
    windows = PureWindowsPath(relative_path)
    if (
        Path(relative_path).is_absolute()
        or windows.is_absolute()
        or windows.drive
        or normalized.startswith("/")
        or normalized.startswith("//")
        or re.match(r"^[A-Za-z]:", relative_path)
        or ":" in relative_path
        or ".." in normalized.split("/")
    ):
        raise ValueError("campaign manifest path is unsafe")
    base = Path(base_directory).resolve()
    candidate = base.joinpath(*normalized.split("/"))
    current = base
    for part in normalized.split("/"):
        current = current / part
        if current.exists() and current.is_symlink():
            raise ValueError("campaign manifest path crosses a symlink")
    resolved = candidate.resolve(strict=False)
    if not resolved.is_relative_to(base):
        raise ValueError("campaign manifest path escapes its base directory")
    return resolved


@dataclass(frozen=True, slots=True)
class PrecisionCapabilities:
    digits: tuple[int, ...]

    def __post_init__(self) -> None:
        values = tuple(self.digits)
        if (
            not values
            or any(isinstance(value, bool) or value not in _PRECISION_DIGITS for value in values)
            or values != tuple(sorted(set(values)))
            or 64 not in values
        ):
            raise ValueError(
                "precision capabilities must be unique ordered digits including 64"
            )
        object.__setattr__(self, "digits", values)

    def to_mapping(self) -> dict[str, object]:
        return {"digits": list(self.digits)}

    @property
    def identity_sha256(self) -> str:
        return _sha256(self.to_mapping())


@dataclass(frozen=True, slots=True)
class PrecisionFactoryIdentity:
    factory: str
    module_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.factory, str) or not self.factory:
            raise ValueError("precision factory name must be nonempty")
        if (
            not isinstance(self.module_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", self.module_sha256) is None
        ):
            raise ValueError("precision factory module SHA-256 is invalid")

    def to_mapping(self) -> dict[str, str]:
        return {
            "factory": self.factory,
            "module_sha256": self.module_sha256,
        }

    @classmethod
    def from_mapping(cls, value: object) -> "PrecisionFactoryIdentity":
        if not isinstance(value, Mapping) or set(value) != {
            "factory", "module_sha256"
        }:
            raise ValueError("precision factory identity fields are invalid")
        identity = cls(value["factory"], value["module_sha256"])
        if identity.to_mapping() != value:
            raise ValueError("precision factory identity is not canonical")
        return identity


def _native_precision_factory_identity() -> PrecisionFactoryIdentity:
    return PrecisionFactoryIdentity(
        "windows_solver.response_batches:NativeCampaignStageBackend.from_selection",
        _campaign_source_sha256(),
    )


@dataclass(frozen=True, slots=True)
class CampaignCohort:
    cohort_id: str
    role: str
    mode_label: str
    leaf_ids: tuple[str, ...]

    def to_mapping(self) -> dict[str, object]:
        return {
            "cohort_id": self.cohort_id,
            "role": self.role,
            "mode_label": self.mode_label,
            "leaf_ids": list(self.leaf_ids),
        }


@dataclass(frozen=True, slots=True)
class CampaignLeafPlan:
    leaf: BPrimeLeaf
    job: ResponseComponentJob
    cohort_id: str

    @property
    def leaf_id(self) -> str:
        return self.leaf.leaf_id

    @property
    def role(self) -> str:
        return self.leaf.role

    @property
    def mechanism_id(self) -> str:
        return self.leaf.mechanism_id

    def to_mapping(self) -> dict[str, object]:
        return {
            "leaf_id": self.leaf.leaf_id,
            "role": self.leaf.role,
            "mode_label": self.leaf.mode_label,
            "mode": list(self.leaf.mode),
            "spin_role": self.leaf.spin_role,
            "coordinate_exact": {
                "numerator": self.leaf.coordinate.numerator,
                "denominator": self.leaf.coordinate.denominator,
            },
            "spin_binary64_hex": self.leaf.spin.hex(),
            "mechanism_id": self.leaf.mechanism_id,
            "cohort_id": self.cohort_id,
            "control_only": self.leaf.role == "control",
            "exploratory": self.leaf.role == "deep",
            "response_job": self.job.to_mapping(),
        }


@dataclass(frozen=True, slots=True)
class StageSignedErrorChannel:
    """One digest-bound signed numerical-error contribution from a stage."""

    channel_id: str
    family: str
    shared_group: str
    provenance: Mapping[str, object]
    units: str
    signed_delta: complex
    scope: str

    def __post_init__(self) -> None:
        for name in ("channel_id", "family", "shared_group", "units"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"stage signed channel {name} is invalid")
        if self.family not in STAGE_SIGNED_ERROR_FAMILIES:
            raise ValueError("stage signed channel family is invalid")
        if self.scope not in {"local", "shared"}:
            raise ValueError("stage signed channel scope is invalid")
        if not self.channel_id.startswith(f"{self.scope}:"):
            raise ValueError("stage signed channel ID does not match its scope")
        value = complex(self.signed_delta)
        if not math.isfinite(value.real) or not math.isfinite(value.imag):
            raise ValueError("stage signed channel delta is non-finite")
        object.__setattr__(self, "signed_delta", value)
        provenance = self.provenance
        if not isinstance(provenance, Mapping) or set(provenance) != {
            "source_kind", "source_id", "source_sha256", "derivation"
        }:
            raise ValueError("stage signed channel provenance fields are invalid")
        if any(
            not isinstance(provenance[name], str) or not provenance[name]
            for name in ("source_kind", "source_id", "derivation")
        ) or (
            not isinstance(provenance["source_sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", provenance["source_sha256"]) is None
        ):
            raise ValueError("stage signed channel provenance is invalid")
        object.__setattr__(self, "provenance", dict(provenance))

    def to_mapping(self) -> dict[str, object]:
        return {
            "channel_id": self.channel_id,
            "family": self.family,
            "shared_group": self.shared_group,
            "provenance": dict(self.provenance),
            "units": self.units,
            "signed_delta": {
                "real": self.signed_delta.real,
                "imaginary": self.signed_delta.imag,
            },
            "scope": self.scope,
        }

    @classmethod
    def from_mapping(cls, value: object) -> "StageSignedErrorChannel":
        if not isinstance(value, Mapping) or set(value) != {
            "channel_id", "family", "shared_group", "provenance", "units",
            "signed_delta", "scope",
        }:
            raise ValueError("stage signed channel fields are invalid")
        delta = value["signed_delta"]
        if not isinstance(delta, Mapping) or set(delta) != {"real", "imaginary"}:
            raise ValueError("stage signed channel delta fields are invalid")
        real, imaginary = delta["real"], delta["imaginary"]
        if (
            isinstance(real, bool) or isinstance(imaginary, bool)
            or not isinstance(real, (int, float))
            or not isinstance(imaginary, (int, float))
        ):
            raise ValueError("stage signed channel delta types are invalid")
        channel = cls(
            channel_id=value["channel_id"],
            family=value["family"],
            shared_group=value["shared_group"],
            provenance=value["provenance"],
            units=value["units"],
            signed_delta=complex(float(real), float(imaginary)),
            scope=value["scope"],
        )
        if channel.to_mapping() != value:
            raise ValueError("stage signed channel is not canonical")
        return channel


def _validate_stage_signed_error_channels(
    raw_channels: object,
    component_result: Mapping[str, object],
    local_disk_radius_abs: float,
) -> tuple[Mapping[str, object], ...]:
    if not isinstance(raw_channels, tuple):
        raise ValueError("stage signed error channels must be an ordered tuple")
    channels = tuple(
        item if isinstance(item, StageSignedErrorChannel)
        else StageSignedErrorChannel.from_mapping(item)
        for item in raw_channels
    )
    if tuple(item.family for item in channels) != STAGE_SIGNED_ERROR_FAMILIES:
        raise ValueError("stage signed error channels require the exact family order")
    if len({item.channel_id for item in channels}) != len(channels):
        raise ValueError("stage signed error channel IDs contain duplicates")
    units = {item.units for item in channels}
    if len(units) != 1:
        raise ValueError("stage signed error channel units disagree")
    source_sha256 = _sha256(component_result)
    if any(
        item.provenance["source_sha256"] != source_sha256 for item in channels
    ):
        raise ValueError("stage signed channel provenance is not component-bound")
    radius = sum(abs(item.signed_delta) for item in channels)
    tolerance = max(1.0e-15, local_disk_radius_abs * 1.0e-12)
    if abs(radius - local_disk_radius_abs) > tolerance:
        raise ValueError("stage signed channel ledger does not reproduce the local disk")
    return tuple(item.to_mapping() for item in channels)


def explicit_stage_signed_error_channels(
    component_result: Mapping[str, object],
    *,
    family_deltas: Mapping[str, complex],
    source_kind: str,
    source_id: str,
    units: str,
) -> tuple[Mapping[str, object], ...]:
    """Build a complete, explicitly signed ledger bound to one stage result."""

    if set(family_deltas) != set(STAGE_SIGNED_ERROR_FAMILIES):
        raise ValueError("explicit stage ledger requires every signed-error family")
    source_sha256 = _sha256(component_result)
    return tuple(
        StageSignedErrorChannel(
            channel_id=f"local:{source_id}:{family}",
            family=family,
            shared_group=source_id,
            provenance={
                "source_kind": source_kind,
                "source_id": source_id,
                "source_sha256": source_sha256,
                "derivation": f"explicit-signed-{family}",
            },
            units=units,
            signed_delta=family_deltas[family],
            scope="local",
        ).to_mapping()
        for family in STAGE_SIGNED_ERROR_FAMILIES
    )


def synthetic_stage_signed_error_channels(
    component_result: Mapping[str, object],
    local_disk_radius_abs: float,
) -> tuple[Mapping[str, object], ...]:
    """Supply an explicit non-physical ledger for orchestration-only stages."""

    source_id = str(component_result.get("leaf_id", "synthetic-stage"))
    deltas = {family: 0j for family in STAGE_SIGNED_ERROR_FAMILIES}
    deltas["refinement-holdout"] = complex(float(local_disk_radius_abs), 0.0)
    return explicit_stage_signed_error_channels(
        component_result,
        family_deltas=deltas,
        source_kind="synthetic-orchestration-contract",
        source_id=source_id,
        units="synthetic-dimensionless-response",
    )


def _component_stage_signed_error_channels(
    component_result: Mapping[str, object],
    result: ComponentResult,
    *,
    repeat_delta: complex = 0.0j,
    precision_delta: complex = 0.0j,
) -> tuple[Mapping[str, object], ...]:
    """Preserve the authenticated component engine's six error channels."""

    source = result.error_channels
    family_sources = {
        "signed-root": "signed-root",
        "centred-step-amplitude": "axis",
        "refinement-holdout": "amplitude",
        "truncation": "truncation",
        "resolution-angular-refinement": "resolution",
        "continuation-seed-path": "seed-path",
        "repeat-polish": None,
        "precision-ladder-discrepancy": None,
    }
    deltas = {
        family: complex(0.0 if channel is None else source[channel], 0.0)
        for family, channel in family_sources.items()
    }
    deltas["repeat-polish"] = complex(repeat_delta)
    deltas["precision-ladder-discrepancy"] = complex(precision_delta)
    return explicit_stage_signed_error_channels(
        component_result,
        family_deltas=deltas,
        source_kind="authenticated-component-error-channel",
        source_id=result.job_id,
        units="M-delta-omega-per-native-coordinate",
    )


@dataclass(frozen=True, slots=True)
class StageOutcome:
    digits: int
    numerical_state: str
    component_result: Mapping[str, object]
    local_disk_radius_abs: float
    signed_error_channels: tuple[Mapping[str, object], ...]
    deep_diagnostics: Mapping[str, object] | None = None
    self_refinement_enclosed: bool | None = None
    discrepancy_from_previous_abs: float | None = None
    discrepancy_enclosed: bool | None = None

    def __post_init__(self) -> None:
        if isinstance(self.digits, bool) or self.digits not in _PRECISION_DIGITS:
            raise ValueError("stage precision digits are invalid")
        if not self.numerical_state or not isinstance(self.component_result, Mapping):
            raise ValueError("stage outcome state/result is invalid")
        radius = float(self.local_disk_radius_abs)
        if not math.isfinite(radius) or radius < 0.0:
            raise ValueError("stage local disk radius must be finite and nonnegative")
        object.__setattr__(self, "local_disk_radius_abs", radius)
        object.__setattr__(
            self,
            "signed_error_channels",
            _validate_stage_signed_error_channels(
                self.signed_error_channels, self.component_result, radius
            ),
        )
        for name in ("discrepancy_from_previous_abs",):
            raw = getattr(self, name)
            if raw is not None:
                converted = float(raw)
                if not math.isfinite(converted) or converted < 0.0:
                    raise ValueError(f"stage {name} must be finite and nonnegative")
                object.__setattr__(self, name, converted)
        for name in ("self_refinement_enclosed", "discrepancy_enclosed"):
            raw = getattr(self, name)
            if raw is not None and not isinstance(raw, bool):
                raise ValueError(f"stage {name} must be boolean or null")

    def to_mapping(self) -> dict[str, object]:
        return {
            "digits": self.digits,
            "numerical_state": self.numerical_state,
            "component_result": dict(self.component_result),
            "local_disk_radius_abs": self.local_disk_radius_abs,
            "signed_error_channels": [
                dict(item) for item in self.signed_error_channels
            ],
            "deep_diagnostics": (
                None if self.deep_diagnostics is None else dict(self.deep_diagnostics)
            ),
            "self_refinement_enclosed": self.self_refinement_enclosed,
            "discrepancy_from_previous_abs": self.discrepancy_from_previous_abs,
            "discrepancy_enclosed": self.discrepancy_enclosed,
        }


@dataclass(frozen=True, slots=True)
class CampaignSelection:
    selection_id: str
    role: str
    leaf_ids: tuple[str, ...]
    cohort_ids: tuple[str, ...]

    def to_mapping(self) -> dict[str, object]:
        return {
            "selection_id": self.selection_id,
            "role": self.role,
            "leaf_ids": list(self.leaf_ids),
            "cohort_ids": list(self.cohort_ids),
        }


@dataclass(frozen=True, slots=True)
class CampaignStageRecord:
    outcome: StageOutcome
    runner_provenance: Mapping[str, object]

    def __post_init__(self) -> None:
        value = self.runner_provenance
        if not isinstance(value, Mapping) or set(value) != {
            "precision_factory_identity", "available_precision_digits"
        }:
            raise ValueError("campaign stage runner provenance is invalid")
        factory = PrecisionFactoryIdentity.from_mapping(
            value["precision_factory_identity"]
        )
        digits = value["available_precision_digits"]
        if not isinstance(digits, list):
            raise ValueError("campaign stage available precision is invalid")
        capabilities = PrecisionCapabilities(tuple(digits))
        if self.outcome.digits not in capabilities.digits:
            raise ValueError("campaign stage precision was not available")
        object.__setattr__(self, "runner_provenance", {
            "precision_factory_identity": factory.to_mapping(),
            "available_precision_digits": list(capabilities.digits),
        })

    @property
    def content(self) -> dict[str, object]:
        return {
            **self.outcome.to_mapping(),
            "runner_provenance": dict(self.runner_provenance),
        }

    @property
    def stage_sha256(self) -> str:
        return _sha256(self.content)

    def to_mapping(self) -> dict[str, object]:
        return {**self.content, "stage_sha256": self.stage_sha256}

    @classmethod
    def from_mapping(cls, value: object) -> "CampaignStageRecord":
        if not isinstance(value, Mapping):
            raise ValueError("campaign stage record must be an object")
        fields = {
            "digits",
            "numerical_state",
            "component_result",
            "local_disk_radius_abs",
            "signed_error_channels",
            "deep_diagnostics",
            "self_refinement_enclosed",
            "discrepancy_from_previous_abs",
            "discrepancy_enclosed",
            "runner_provenance",
            "stage_sha256",
        }
        if set(value) != fields:
            raise ValueError("campaign stage record fields are invalid")
        outcome = StageOutcome(
            digits=value["digits"],
            numerical_state=value["numerical_state"],
            component_result=value["component_result"],
            local_disk_radius_abs=value["local_disk_radius_abs"],
            signed_error_channels=tuple(value["signed_error_channels"]),
            deep_diagnostics=value["deep_diagnostics"],
            self_refinement_enclosed=value["self_refinement_enclosed"],
            discrepancy_from_previous_abs=value["discrepancy_from_previous_abs"],
            discrepancy_enclosed=value["discrepancy_enclosed"],
        )
        record = cls(outcome, value["runner_provenance"])
        if value["stage_sha256"] != record.stage_sha256:
            raise ValueError("campaign stage content digest is invalid")
        return record


@dataclass(frozen=True, slots=True)
class CampaignLeafRecord:
    leaf_id: str
    role: str
    state: str
    stages: tuple[CampaignStageRecord, ...]
    trigger_ids: tuple[str, ...] = ()
    sentinel: bool = False
    missing_precision_digits: int | None = None
    sentinel_comparison: Mapping[str, object] | None = None

    @property
    def content(self) -> dict[str, object]:
        return {
            "leaf_id": self.leaf_id,
            "role": self.role,
            "state": self.state,
            "stages": [stage.to_mapping() for stage in self.stages],
            "trigger_ids": list(self.trigger_ids),
            "sentinel": self.sentinel,
            "missing_precision_digits": self.missing_precision_digits,
            "sentinel_comparison": (
                None
                if self.sentinel_comparison is None
                else dict(self.sentinel_comparison)
            ),
            "computed": self.state in {"PRODUCED", "UNRESOLVED"},
        }

    @property
    def record_sha256(self) -> str:
        return _sha256(self.content)

    def to_mapping(self) -> dict[str, object]:
        return {**self.content, "record_sha256": self.record_sha256}

    @classmethod
    def from_mapping(cls, value: object) -> "CampaignLeafRecord":
        if not isinstance(value, Mapping):
            raise ValueError("campaign leaf record must be an object")
        fields = {
            "leaf_id",
            "role",
            "state",
            "stages",
            "trigger_ids",
            "sentinel",
            "missing_precision_digits",
            "sentinel_comparison",
            "computed",
            "record_sha256",
        }
        if set(value) != fields or not isinstance(value["stages"], list):
            raise ValueError("campaign leaf record fields are invalid")
        if (
            not isinstance(value["trigger_ids"], list)
            or any(not isinstance(item, str) for item in value["trigger_ids"])
        ):
            raise ValueError("campaign trigger IDs are invalid")
        if not isinstance(value["sentinel"], bool):
            raise ValueError("campaign sentinel identity is invalid")
        comparison = value["sentinel_comparison"]
        if comparison is not None and not isinstance(comparison, Mapping):
            raise ValueError("campaign sentinel comparison is invalid")
        record = cls(
            leaf_id=str(value["leaf_id"]),
            role=str(value["role"]),
            state=str(value["state"]),
            stages=tuple(
                CampaignStageRecord.from_mapping(item) for item in value["stages"]
            ),
            trigger_ids=tuple(value["trigger_ids"]),
            sentinel=value["sentinel"],
            missing_precision_digits=(
                None
                if value["missing_precision_digits"] is None
                else int(value["missing_precision_digits"])
            ),
            sentinel_comparison=(
                None if comparison is None else dict(comparison)
            ),
        )
        if record.state not in {
            "IN_PROGRESS", "PRODUCED", "UNRESOLVED", "MISSING_PRECISION",
            "INVALID_SENTINEL_FALSE_NEGATIVE",
        }:
            raise ValueError("campaign leaf record state is invalid")
        if value["computed"] != (record.state in {"PRODUCED", "UNRESOLVED"}):
            raise ValueError("campaign computed state is invalid")
        if value["record_sha256"] != record.record_sha256:
            raise ValueError("campaign leaf record content digest is invalid")
        return record


@dataclass(frozen=True, slots=True)
class CampaignRunSummary:
    campaign_id: str
    selection_id: str
    state: str
    executed_stage_count: int
    reused_stage_count: int
    records: tuple[CampaignLeafRecord, ...]
    checkpoint_path: str

    @property
    def result_count(self) -> int:
        return len(self.records)

    def to_mapping(self) -> dict[str, object]:
        return {
            "campaign_id": self.campaign_id,
            "selection_id": self.selection_id,
            "state": self.state,
            "executed_stage_count": self.executed_stage_count,
            "reused_stage_count": self.reused_stage_count,
            "result_count": self.result_count,
            "records": [record.to_mapping() for record in self.records],
            "checkpoint_path": self.checkpoint_path,
            "release_admissible": False,
        }


@dataclass(frozen=True, slots=True)
class SolvedLeafImportSummary:
    imported_count: int
    skipped_count: int
    leaf_ids: tuple[str, ...]
    store_root: str

    def to_mapping(self) -> dict[str, object]:
        return {
            "imported_terminal_solved_leaves": self.imported_count,
            "skipped_records": self.skipped_count,
            "leaf_ids": list(self.leaf_ids),
            "store_root": self.store_root,
        }


@dataclass(frozen=True, slots=True)
class CampaignSmokeRecord:
    leaf_id: str
    evidence_kind: str
    record: CampaignLeafRecord

    def to_mapping(self) -> dict[str, object]:
        return {
            "leaf_id": self.leaf_id,
            "evidence_kind": self.evidence_kind,
            "record": self.record.to_mapping(),
        }


@dataclass(frozen=True, slots=True)
class CampaignSmokeSummary:
    records: tuple[CampaignSmokeRecord, ...]

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": CAMPAIGN_SCHEMA_VERSION,
            "smoke_case_count": len(self.records),
            "leaf_ids": [record.leaf_id for record in self.records],
            "records": [record.to_mapping() for record in self.records],
            "scientific_evidence": False,
            "release_admissible": False,
        }


@dataclass(frozen=True, slots=True)
class CampaignPlan:
    leaves: tuple[CampaignLeafPlan, ...]
    cohorts: tuple[CampaignCohort, ...]
    policy: NumericalPolicy
    backend_identity: BackendIdentity
    precision_capabilities: PrecisionCapabilities
    precision_factory_identity: PrecisionFactoryIdentity

    @property
    def role_counts(self) -> dict[str, int]:
        return {
            role: sum(leaf.role == role for leaf in self.leaves)
            for role in ("primary", "control", "deep")
        }

    @property
    def mechanism_counts(self) -> dict[str, int]:
        return {
            mechanism: sum(leaf.mechanism_id == mechanism for leaf in self.leaves)
            for mechanism in (
                "horizon-admittance",
                "exterior-fixed-r3",
                "exterior-light-ring",
                "exterior-throat-kappa",
                "exterior-alpha-zero",
                "exterior-alpha-half",
                "exterior-alpha-one",
            )
        }

    @property
    def ordered_leaf_set_sha256(self) -> str:
        return _sha256([leaf.leaf_id for leaf in self.leaves])

    @property
    def root_set_sha256(self) -> str:
        roots: dict[str, object] = {}
        for leaf in self.leaves:
            roots.setdefault(leaf.job.root.identity_sha256, leaf.job.root.to_mapping())
        return _sha256(list(roots.values()))

    @property
    def bindings(self) -> dict[str, object]:
        return {
            "schema_version": CAMPAIGN_SCHEMA_VERSION,
            "ordered_leaf_set_sha256": self.ordered_leaf_set_sha256,
            "root_set_sha256": self.root_set_sha256,
            "policy_sha256": self.policy.identity_sha256,
            "engine_source_sha256": _campaign_engine_identity_sha256(),
            "campaign_source_sha256": _campaign_source_sha256(),
            "backend_identity_sha256": self.backend_identity.identity_sha256,
            "precision_capabilities_sha256": self.precision_capabilities.identity_sha256,
            "precision_factory_identity": self.precision_factory_identity.to_mapping(),
            "cohort_set_sha256": _sha256(
                [cohort.to_mapping() for cohort in self.cohorts]
            ),
        }

    @property
    def campaign_id(self) -> str:
        return f"b-prime-campaign-{_sha256(self.bindings)}"

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": CAMPAIGN_SCHEMA_VERSION,
            "campaign_id": self.campaign_id,
            "leaf_count": len(self.leaves),
            "role_counts": self.role_counts,
            "mechanism_counts": self.mechanism_counts,
            "leaves": [leaf.to_mapping() for leaf in self.leaves],
            "cohorts": [cohort.to_mapping() for cohort in self.cohorts],
            "policy": self.policy.to_mapping(),
            "backend_identity": self.backend_identity.to_mapping(),
            "precision_capabilities": self.precision_capabilities.to_mapping(),
            "precision_factory_identity": self.precision_factory_identity.to_mapping(),
            "bindings": self.bindings,
            "release_admissible": False,
        }


def _leaf_precision_contract(leaf: CampaignLeafPlan) -> dict[str, object]:
    return {
        "binary64_stage_required": True,
        "deep_leaf": leaf.role == "deep",
        "promotion_digits": [80, 120] if leaf.role == "deep" else [],
        "promotion_gates": list(B_PRIME_RELEASE_DOMAIN.precision_promotion_gates),
        "fixed_precision_sentinel": leaf.leaf_id in set(
            B_PRIME_RELEASE_DOMAIN.fixed_precision_sentinel_leaf_ids
        ),
    }


def scientific_computation_identity_sha256(
    plan: CampaignPlan, leaf: CampaignLeafPlan
) -> str:
    """Bind one requested calculation without binding campaign presentation code."""

    if leaf.leaf_id not in {item.leaf_id for item in plan.leaves}:
        raise ValueError("solved-leaf scientific identity is outside the campaign plan")
    material = {
        "schema_version": 1,
        "leaf_id": leaf.leaf_id,
        "role": leaf.role,
        "mode_label": leaf.leaf.mode_label,
        "mode": list(leaf.leaf.mode),
        "spin_role": leaf.leaf.spin_role,
        "coordinate_exact": {
            "numerator": leaf.leaf.coordinate.numerator,
            "denominator": leaf.leaf.coordinate.denominator,
        },
        "spin_binary64_hex": leaf.leaf.spin.hex(),
        "mechanism_id": leaf.mechanism_id,
        "response_job": leaf.job.to_mapping(),
        "precision_factory_identity": plan.precision_factory_identity.to_mapping(),
        "precision_contract": _leaf_precision_contract(leaf),
    }
    return _sha256(material)


def _campaign_cohorts() -> tuple[CampaignCohort, ...]:
    grouped: dict[tuple[str, str], list[str]] = {}
    for leaf in B_PRIME_RELEASE_DOMAIN.production_leaves:
        grouped.setdefault((leaf.role, leaf.mode_label), []).append(leaf.leaf_id)
    output: list[CampaignCohort] = []
    for (role, mode_label), leaf_ids in grouped.items():
        material = {
            "role": role,
            "mode_label": mode_label,
            "leaf_ids": leaf_ids,
        }
        output.append(CampaignCohort(
            cohort_id=f"b-prime-cohort-{_sha256(material)}",
            role=role,
            mode_label=mode_label,
            leaf_ids=tuple(leaf_ids),
        ))
    return tuple(output)


def build_campaign_plan(
    *,
    policy: NumericalPolicy,
    backend_identity: BackendIdentity,
    precision_capabilities: PrecisionCapabilities,
    precision_factory_identity: PrecisionFactoryIdentity | None = None,
) -> CampaignPlan:
    cohorts = _campaign_cohorts()
    cohort_by_leaf = {
        leaf_id: cohort.cohort_id
        for cohort in cohorts
        for leaf_id in cohort.leaf_ids
    }
    leaves = tuple(
        CampaignLeafPlan(
            leaf=leaf,
            job=ResponseComponentJob.from_leaf_id(
                leaf.leaf_id,
                policy=policy,
                backend_identity=backend_identity,
            ),
            cohort_id=cohort_by_leaf[leaf.leaf_id],
        )
        for leaf in B_PRIME_RELEASE_DOMAIN.production_leaves
    )
    if tuple(leaf.leaf_id for leaf in leaves) != B_PRIME_RELEASE_DOMAIN.production_leaf_ids:
        raise ValueError("campaign plan does not exactly preserve the B-prime leaf order")
    return CampaignPlan(
        leaves=leaves,
        cohorts=cohorts,
        policy=policy,
        backend_identity=backend_identity,
        precision_capabilities=precision_capabilities,
        precision_factory_identity=(
            _native_precision_factory_identity()
            if precision_factory_identity is None
            else precision_factory_identity
        ),
    )


def build_campaign_selection(
    plan: CampaignPlan,
    *,
    role: str,
    leaf_ids: Sequence[str] | None = None,
    cohort_ids: Sequence[str] | None = None,
) -> CampaignSelection:
    if role == "all":
        if leaf_ids is not None or cohort_ids is not None:
            raise ValueError("full campaign selection does not accept subset IDs")
        selected = tuple(leaf.leaf_id for leaf in plan.leaves)
        selected_cohorts = tuple(cohort.cohort_id for cohort in plan.cohorts)
        material = {
            "campaign_id": plan.campaign_id,
            "role": role,
            "leaf_ids": list(selected),
            "cohort_ids": list(selected_cohorts),
        }
        return CampaignSelection(
            selection_id=f"campaign-selection-{_sha256(material)}",
            role=role,
            leaf_ids=selected,
            cohort_ids=selected_cohorts,
        )
    if role not in {"primary", "control", "deep"}:
        raise ValueError("campaign selection role is invalid")
    if (leaf_ids is None) == (cohort_ids is None):
        raise ValueError("select exactly one of leaf_ids or cohort_ids")
    canonical_by_id = {leaf.leaf_id: leaf for leaf in plan.leaves}
    selected_cohorts: tuple[str, ...] = ()
    if cohort_ids is not None:
        requested_cohorts = tuple(cohort_ids)
        canonical_cohorts = tuple(
            cohort.cohort_id for cohort in plan.cohorts if cohort.role == role
        )
        if (
            not requested_cohorts
            or len(requested_cohorts) != len(set(requested_cohorts))
            or tuple(item for item in canonical_cohorts if item in requested_cohorts)
            != requested_cohorts
        ):
            raise ValueError("campaign cohort selection is empty, unknown, or reordered")
        requested_set = set(requested_cohorts)
        selected = tuple(
            leaf.leaf_id
            for leaf in plan.leaves
            if leaf.cohort_id in requested_set
        )
        selected_cohorts = requested_cohorts
    else:
        selected = tuple(leaf_ids or ())
    if not selected or len(selected) != len(set(selected)):
        raise ValueError("campaign leaf selection must be nonempty and unique")
    if any(
        leaf_id not in canonical_by_id or canonical_by_id[leaf_id].role != role
        for leaf_id in selected
    ):
        raise ValueError("campaign leaf selection is off-domain or crosses roles")
    selected_set = set(selected)
    canonical = tuple(
        leaf.leaf_id
        for leaf in plan.leaves
        if leaf.role == role and leaf.leaf_id in selected_set
    )
    if canonical != selected:
        raise ValueError("campaign leaf selection is reordered")
    material = {
        "campaign_id": plan.campaign_id,
        "role": role,
        "leaf_ids": list(selected),
        "cohort_ids": list(selected_cohorts),
    }
    return CampaignSelection(
        selection_id=f"campaign-selection-{_sha256(material)}",
        role=role,
        leaf_ids=selected,
        cohort_ids=selected_cohorts,
    )


def _merged_selection(
    plan: CampaignPlan, leaf_ids: Sequence[str]
) -> CampaignSelection:
    requested = tuple(leaf_ids)
    if not requested or len(requested) != len(set(requested)):
        raise ValueError("merged campaign selection must be nonempty and unique")
    requested_set = set(requested)
    canonical = tuple(
        leaf.leaf_id for leaf in plan.leaves if leaf.leaf_id in requested_set
    )
    if canonical != requested:
        raise ValueError("merged campaign selection is off-domain or reordered")
    material = {
        "campaign_id": plan.campaign_id,
        "role": "merged",
        "leaf_ids": list(canonical),
        "cohort_ids": [],
    }
    return CampaignSelection(
        selection_id=f"campaign-selection-{_sha256(material)}",
        role="merged",
        leaf_ids=canonical,
        cohort_ids=(),
    )


def _checkpoint_bindings(
    plan: CampaignPlan, selection: CampaignSelection
) -> dict[str, object]:
    jobs = {
        leaf.leaf_id: leaf.job.to_mapping()
        for leaf in plan.leaves
        if leaf.leaf_id in set(selection.leaf_ids)
    }
    return {
        "campaign_id": plan.campaign_id,
        "campaign_bindings": plan.bindings,
        "selection": selection.to_mapping(),
        "selection_jobs_sha256": _sha256(jobs),
        "precision_factory_identity": plan.precision_factory_identity.to_mapping(),
        "precision_contract_sha256": _sha256({
            "promotion_gates": list(B_PRIME_RELEASE_DOMAIN.precision_promotion_gates),
            "fixed_sentinel_leaf_ids": list(
                B_PRIME_RELEASE_DOMAIN.fixed_precision_sentinel_leaf_ids
            ),
        }),
    }


def _checkpoint_mapping(
    plan: CampaignPlan,
    selection: CampaignSelection,
    records: Sequence[CampaignLeafRecord],
) -> dict[str, object]:
    values = [record.to_mapping() for record in records]
    complete = (
        len(records) == len(selection.leaf_ids)
        and all(record.state in {"PRODUCED", "UNRESOLVED"} for record in records)
    )
    return {
        "schema_version": CAMPAIGN_SCHEMA_VERSION,
        "state": "COMPLETE" if complete else "PARTIAL",
        "bindings": _checkpoint_bindings(plan, selection),
        "records": values,
        "records_sha256": _sha256(values),
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


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate campaign checkpoint JSON key: {key}")
        result[key] = value
    return result


def _read_checkpoint_envelope(
    path: Path,
) -> tuple[Mapping[str, object], Mapping[str, object], tuple[CampaignLeafRecord, ...]]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda item: (_ for _ in ()).throw(
                ValueError(f"campaign checkpoint contains non-finite constant {item}")
            ),
        )
    except json.JSONDecodeError as error:
        raise ValueError("campaign checkpoint is not valid JSON") from error
    if not isinstance(value, Mapping) or set(value) != {
        "schema_version",
        "state",
        "bindings",
        "records",
        "records_sha256",
        "release_admissible",
    }:
        raise ValueError("campaign checkpoint envelope fields are invalid")
    if value["schema_version"] != CAMPAIGN_SCHEMA_VERSION:
        raise ValueError("campaign checkpoint schema is invalid")
    bindings = value["bindings"]
    if not isinstance(bindings, Mapping):
        raise ValueError("campaign checkpoint bindings are invalid")
    raw_records = value["records"]
    if (
        not isinstance(raw_records, list)
        or value["records_sha256"] != _sha256(raw_records)
    ):
        raise ValueError("campaign checkpoint records digest is invalid")
    records = tuple(CampaignLeafRecord.from_mapping(item) for item in raw_records)
    return value, bindings, records


def _load_checkpoint(
    plan: CampaignPlan, path: Path
) -> tuple[CampaignSelection, tuple[CampaignLeafRecord, ...], str]:
    value, bindings, records = _read_checkpoint_envelope(path)
    selection_value = bindings.get("selection")
    if not isinstance(selection_value, Mapping) or set(selection_value) != {
        "selection_id", "role", "leaf_ids", "cohort_ids"
    }:
        raise ValueError("campaign checkpoint selection is invalid")
    if selection_value["role"] == "all":
        selection = build_campaign_selection(
            plan, role="all", leaf_ids=None, cohort_ids=None
        )
    elif selection_value["role"] == "merged":
        if selection_value["cohort_ids"]:
            raise ValueError("merged campaign checkpoint cannot name cohorts")
        selection = _merged_selection(plan, selection_value["leaf_ids"])
    elif selection_value["cohort_ids"]:
        selection = build_campaign_selection(
            plan,
            role=str(selection_value["role"]),
            cohort_ids=selection_value["cohort_ids"],
        )
    else:
        selection = build_campaign_selection(
            plan,
            role=str(selection_value["role"]),
            leaf_ids=selection_value["leaf_ids"],
        )
    if selection.to_mapping() != selection_value:
        raise ValueError("campaign checkpoint selection identity is invalid")
    if bindings != _checkpoint_bindings(plan, selection):
        raise ValueError("campaign checkpoint bindings are stale or forged")
    if len(records) > len(selection.leaf_ids):
        raise ValueError("campaign checkpoint has excess records")
    leaf_by_id = {leaf.leaf_id: leaf for leaf in plan.leaves}
    record_ids = tuple(record.leaf_id for record in records)
    if len(record_ids) != len(set(record_ids)):
        raise ValueError("campaign checkpoint contains duplicate leaf records")
    record_id_set = set(record_ids)
    expected_record_order = tuple(
        leaf_id for leaf_id in selection.leaf_ids if leaf_id in record_id_set
    )
    if record_ids != expected_record_order:
        raise ValueError("campaign checkpoint record order is invalid")
    if selection.role != "merged" and record_ids != selection.leaf_ids[:len(records)]:
        raise ValueError("selected campaign checkpoint records are not a prefix")
    for record in records:
        leaf = leaf_by_id[record.leaf_id]
        if record.role != leaf.role:
            raise ValueError("campaign checkpoint record order or role is invalid")
        if not record.stages or record.stages[0].outcome.digits != 64:
            raise ValueError("campaign checkpoint precision stages are invalid")
        digits = tuple(stage.outcome.digits for stage in record.stages)
        if digits not in {(64,), (64, 80), (64, 80, 120)}:
            raise ValueError("campaign checkpoint precision stage order is invalid")
        _validate_record_semantics(
            leaf, record, plan.precision_factory_identity
        )
    expected_state = (
        "COMPLETE"
        if len(records) == len(selection.leaf_ids)
        and all(record.state in {"PRODUCED", "UNRESOLVED"} for record in records)
        else "PARTIAL"
    )
    if value["state"] != expected_state or value["release_admissible"] is not False:
        raise ValueError("campaign checkpoint state is invalid")
    return selection, records, expected_state


_DEEP_DIAGNOSTIC_FIELDS = {
    "condition_amplifier_abs",
    "predicted_reliable_decimal_digits",
    "step_richardson_disagreement_abs",
    "repeat_polish_delta_abs",
    "angular_refinement_delta_abs",
    "independent_path_delta_abs",
    "diagnostic_ceiling_abs",
    "denominator_or_calibration_disk_contains_zero",
}


def _deep_trigger_ids(outcome: StageOutcome) -> tuple[str, ...]:
    diagnostics = outcome.deep_diagnostics
    if not isinstance(diagnostics, Mapping) or set(diagnostics) != _DEEP_DIAGNOSTIC_FIELDS:
        raise ValueError("deep diagnostics are missing or invalid")
    numbers: dict[str, float] = {}
    for name in _DEEP_DIAGNOSTIC_FIELDS - {
        "denominator_or_calibration_disk_contains_zero"
    }:
        raw = diagnostics[name]
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValueError("deep diagnostics must contain numeric channels")
        value = float(raw)
        if not math.isfinite(value) or value < 0.0:
            raise ValueError("deep diagnostics must be finite and nonnegative")
        numbers[name] = value
    if numbers["condition_amplifier_abs"] <= 0.0:
        raise ValueError("deep condition amplifier must be positive")
    zero = diagnostics["denominator_or_calibration_disk_contains_zero"]
    if not isinstance(zero, bool):
        raise ValueError("deep denominator/calibration diagnostic must be boolean")
    gates = B_PRIME_RELEASE_DOMAIN.precision_promotion_gates
    triggered: list[str] = []
    if numbers["predicted_reliable_decimal_digits"] < 10.0:
        triggered.append(gates[0])
    if (
        numbers["step_richardson_disagreement_abs"]
        > 0.25 * outcome.local_disk_radius_abs
    ):
        triggered.append(gates[1])
    if max(
        numbers["repeat_polish_delta_abs"],
        numbers["angular_refinement_delta_abs"],
        numbers["independent_path_delta_abs"],
    ) > numbers["diagnostic_ceiling_abs"]:
        triggered.append(gates[2])
    if zero:
        triggered.append(gates[3])
    return tuple(triggered)


def _terminal_state(outcome: StageOutcome, *, enclosed: bool = True) -> str:
    if outcome.numerical_state != "CONVERGED" or not enclosed:
        return "UNRESOLVED"
    return "PRODUCED"


def _validate_component_result(
    leaf: CampaignLeafPlan, outcome: StageOutcome
) -> bool:
    payload = outcome.component_result
    raw_result = payload.get("result")
    if raw_result is None:
        if payload.get("leaf_id") != leaf.leaf_id:
            raise ValueError("campaign component lineage leaf is invalid")
        optional_bindings = {
            "role": leaf.role,
            "mechanism_id": leaf.mechanism_id,
            "job_id": leaf.job.job_id,
            "root_identity_sha256": leaf.job.root.identity_sha256,
            "policy_sha256": leaf.job.policy.identity_sha256,
            "backend_identity_sha256": leaf.job.backend_identity.identity_sha256,
        }
        for name, expected in optional_bindings.items():
            if name in payload and payload[name] != expected:
                raise ValueError(f"campaign component lineage {name} is invalid")
        if "digits" in payload and payload["digits"] != outcome.digits:
            raise ValueError("campaign component precision lineage is invalid")
        return False

    result = ComponentResult.from_mapping(raw_result)
    if result.to_mapping() != raw_result:
        raise ValueError("campaign component result is not canonical")
    job = leaf.job
    if (
        result.job_id != job.job_id
        or result.leaf_id != leaf.leaf_id
        or result.mechanism_id != leaf.mechanism_id
        or result.status.value != outcome.numerical_state
    ):
        raise ValueError("campaign production component identity is invalid")
    expected_lineage = {
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
    if dict(result.lineage) != expected_lineage:
        raise ValueError("campaign production component lineage is invalid")
    for readout in result.raw_readouts:
        if (
            readout.root_reference_id != job.root.root_reference_id
            or readout.branch_id != job.root.branch_id
            or readout.equation_id != job.equation_id
        ):
            raise ValueError("campaign production readout lineage is invalid")
    if result.baseline.omega != job.root.omega:
        raise ValueError("campaign production baseline root is invalid")
    return True


def _validate_record_semantics(
    leaf: CampaignLeafPlan,
    record: CampaignLeafRecord,
    factory_identity: PrecisionFactoryIdentity,
) -> bool:
    previous_available: set[int] = set()
    for stage in record.stages:
        provenance = stage.runner_provenance
        if provenance["precision_factory_identity"] != factory_identity.to_mapping():
            raise ValueError("campaign stage precision factory provenance is invalid")
        available = set(provenance["available_precision_digits"])
        if not previous_available.issubset(available):
            raise ValueError("campaign stage precision availability regressed")
        previous_available = available
    stages = tuple(stage.outcome for stage in record.stages)
    production_flags = tuple(
        _validate_component_result(leaf, stage) for stage in stages
    )
    production = all(production_flags)
    first = stages[0]
    if (
        first.self_refinement_enclosed is not None
        or first.discrepancy_from_previous_abs is not None
        or first.discrepancy_enclosed is not None
    ):
        raise ValueError("campaign binary64 stage refinement fields are invalid")

    if leaf.role != "deep":
        expected_state = _terminal_state(first)
        if (
            len(stages) != 1
            or first.deep_diagnostics is not None
            or record.trigger_ids
            or record.sentinel
            or record.missing_precision_digits is not None
            or record.sentinel_comparison is not None
            or record.state != expected_state
        ):
            raise ValueError("campaign role or component state is inconsistent")
        return production

    trigger_ids = _deep_trigger_ids(first)
    sentinel = leaf.leaf_id in set(
        B_PRIME_RELEASE_DOMAIN.fixed_precision_sentinel_leaf_ids
    )
    if record.trigger_ids != trigger_ids or record.sentinel is not sentinel:
        raise ValueError("campaign deep trigger or sentinel identity is invalid")
    promoted = bool(trigger_ids) or sentinel
    if not promoted:
        if (
            len(stages) != 1
            or record.state != _terminal_state(first)
            or record.missing_precision_digits is not None
            or record.sentinel_comparison is not None
        ):
            raise ValueError("campaign unpromoted deep state is inconsistent")
        return production
    if len(stages) == 1:
        pending = (
            record.state == "IN_PROGRESS"
            and record.missing_precision_digits is None
        ) or (
            record.state == "MISSING_PRECISION"
            and record.missing_precision_digits == 80
        )
        if not pending or record.sentinel_comparison is not None:
            raise ValueError("campaign promoted deep leaf is missing its 80-digit stage")
        return production

    precision80 = stages[1]
    if (
        precision80.deep_diagnostics is not None
        or precision80.self_refinement_enclosed is None
        or precision80.discrepancy_from_previous_abs is None
        or precision80.discrepancy_enclosed is None
    ):
        raise ValueError("campaign 80-digit evidence is incomplete")
    expected_comparison = None
    false_negative = False
    if sentinel:
        threshold = 0.25 * first.local_disk_radius_abs
        false_negative = (
            not trigger_ids
            and precision80.discrepancy_from_previous_abs > threshold
        )
        expected_comparison = {
            "binary64_to_80_discrepancy_abs": (
                precision80.discrepancy_from_previous_abs
            ),
            "trigger_threshold_abs": threshold,
            "trigger_policy_false_negative": false_negative,
        }
    if record.sentinel_comparison != expected_comparison:
        raise ValueError("campaign sentinel comparison is invalid")
    if false_negative:
        if (
            record.state != "INVALID_SENTINEL_FALSE_NEGATIVE"
            or record.missing_precision_digits != 120
        ):
            raise ValueError("campaign sentinel false-negative state is invalid")
        if len(stages) == 3:
            _validate_precision120(stages[2])
        return production
    if precision80.self_refinement_enclosed:
        if (
            len(stages) != 2
            or record.state
            != _terminal_state(
                precision80, enclosed=bool(precision80.discrepancy_enclosed)
            )
            or record.missing_precision_digits is not None
        ):
            raise ValueError("campaign enclosed 80-digit state is inconsistent")
        return production
    if len(stages) == 2:
        pending = (
            record.state == "IN_PROGRESS"
            and record.missing_precision_digits is None
        ) or (
            record.state == "MISSING_PRECISION"
            and record.missing_precision_digits == 120
        )
        if not pending:
            raise ValueError("campaign promoted deep leaf is missing its 120-digit stage")
        return production
    precision120 = stages[2]
    _validate_precision120(precision120)
    if (
        record.state
        != _terminal_state(
            precision120, enclosed=bool(precision120.discrepancy_enclosed)
        )
        or record.missing_precision_digits is not None
    ):
        raise ValueError("campaign 120-digit terminal state is inconsistent")
    return production


def _validate_cacheable_leaf_record(
    plan: CampaignPlan,
    leaf: CampaignLeafPlan,
    record: CampaignLeafRecord,
) -> None:
    if record.leaf_id != leaf.leaf_id or record.role != leaf.role:
        raise ValueError("solved-leaf record identity or role is invalid")
    if record.state not in {"PRODUCED", "UNRESOLVED"}:
        raise ValueError("solved-leaf record is not terminal and cacheable")
    if not record.stages or record.stages[0].outcome.digits != 64:
        raise ValueError("solved-leaf precision stages are incomplete")
    digits = tuple(stage.outcome.digits for stage in record.stages)
    if digits not in {(64,), (64, 80), (64, 80, 120)}:
        raise ValueError("solved-leaf precision stage order is invalid")
    if not set(digits).issubset(set(plan.precision_capabilities.digits)):
        raise ValueError("solved-leaf precision stages exceed the current contract")
    for stage in record.stages:
        prior_available = set(
            stage.runner_provenance["available_precision_digits"]
        )
        if not prior_available.issubset(set(plan.precision_capabilities.digits)):
            raise ValueError(
                "solved-leaf precision availability exceeds the current contract"
            )
    if not _validate_record_semantics(
        leaf, record, plan.precision_factory_identity
    ):
        raise ValueError("solved-leaf record lacks canonical production evidence")


def _authenticated_solved_leaf_lookup(
    plan: CampaignPlan,
    leaf: CampaignLeafPlan,
    store: SolvedLeafStore,
) -> SolvedLeafLookup:
    identity = scientific_computation_identity_sha256(plan, leaf)
    lookup = store.lookup(identity, leaf.leaf_id)
    if lookup.status is not SolvedLeafLookupStatus.HIT:
        return lookup
    try:
        if lookup.receipt is None:
            raise ValueError("solved-leaf cache hit has no receipt")
        record = CampaignLeafRecord.from_mapping(lookup.receipt["record"])
        _validate_cacheable_leaf_record(plan, leaf, record)
    except (KeyError, TypeError, ValueError) as error:
        if lookup.path is not None:
            store.quarantine(lookup.path, str(error))
        return SolvedLeafLookup(
            SolvedLeafLookupStatus.CORRUPT,
            path=lookup.path,
            reason=str(error),
        )
    return SolvedLeafLookup(
        SolvedLeafLookupStatus.HIT,
        path=lookup.path,
        receipt={**dict(lookup.receipt), "record": record.to_mapping()},
    )


def _validate_precision120(outcome: StageOutcome) -> None:
    if (
        outcome.deep_diagnostics is not None
        or outcome.self_refinement_enclosed is not None
        or outcome.discrepancy_from_previous_abs is None
        or outcome.discrepancy_enclosed is None
    ):
        raise ValueError("campaign 120-digit evidence is incomplete")


def _replace_record(
    records: list[CampaignLeafRecord], index: int, record: CampaignLeafRecord
) -> None:
    if index < len(records):
        records[index] = record
    else:
        records.append(record)


def _campaign_stage_record(
    plan: CampaignPlan,
    available: PrecisionCapabilities,
    outcome: StageOutcome,
) -> CampaignStageRecord:
    return CampaignStageRecord(outcome, {
        "precision_factory_identity": plan.precision_factory_identity.to_mapping(),
        "available_precision_digits": list(available.digits),
    })


def _execute_campaign_stage(
    backend: object,
    leaf: CampaignLeafPlan,
    digits: int,
    previous_stages: Sequence[CampaignStageRecord] = (),
) -> StageOutcome:
    """Execute a stage while preserving the promotion evidence on resume.

    Existing injected fixture/operator backends keep the original two-argument
    ``execute_stage`` contract.  A backend that computes promoted-precision
    discrepancy evidence can implement ``execute_promoted_stage`` and receives
    the already authenticated checkpoint outcomes, including in a fresh
    process after ``campaign-resume``.
    """

    if digits > 64:
        promoted = getattr(backend, "execute_promoted_stage", None)
        if promoted is not None:
            if not callable(promoted):
                raise ValueError("campaign promoted-stage backend is invalid")
            return promoted(
                leaf,
                digits,
                tuple(stage.outcome for stage in previous_stages),
            )
    execute = getattr(backend, "execute_stage", None)
    if not callable(execute):
        raise ValueError("campaign backend execute_stage is unavailable")
    return execute(leaf, digits)


def _complex_progress(value: complex) -> dict[str, float]:
    return {"real": complex(value).real, "imaginary": complex(value).imag}


def _leaf_progress_context(
    leaf: CampaignLeafPlan, index: int, count: int
) -> dict[str, object]:
    return {
        "leaf_index": index,
        "leaf_count": count,
        "leaf_id": leaf.leaf_id,
        "role": leaf.role,
        "mode": {
            "s": leaf.job.mode.s,
            "ell": leaf.job.mode.ell,
            "m": leaf.job.mode.m,
            "n": leaf.job.mode.n,
        },
        "spin": leaf.job.spin,
        "sampling_coordinate": leaf.job.sampling_coordinate.to_mapping(),
        "mechanism_id": leaf.mechanism_id,
        "bound_omega": _complex_progress(leaf.job.root.omega),
        "seed_omega": _complex_progress(leaf.job.root.omega),
    }


def _execute_campaign_stage_with_progress(
    backend: object,
    leaf: CampaignLeafPlan,
    digits: int,
    context: Mapping[str, object],
    previous_stages: Sequence[CampaignStageRecord] = (),
) -> tuple[StageOutcome, float]:
    component_pass = "primary" if digits == 64 else "promoted"
    started = time.monotonic()
    with progress_scope(
        **context,
        precision_digits=digits,
        component_pass=component_pass,
    ):
        emit_progress(ProgressEventKind.PRECISION_STAGE_STARTED)
        try:
            outcome = _execute_campaign_stage(
                backend, leaf, digits, previous_stages
            )
        except BaseException as error:
            emit_progress(
                ProgressEventKind.LEAF_FAILED,
                precision_digits=digits,
                error_type=type(error).__name__,
                message=str(error),
                elapsed_seconds=time.monotonic() - started,
            )
            raise
    return outcome, time.monotonic() - started


def _checkpoint_stage_with_progress(
    path: Path,
    mapping: Mapping[str, object],
    *,
    context: Mapping[str, object],
    digits: int,
    duration_seconds: float,
    record: CampaignLeafRecord,
) -> None:
    component_pass = "primary" if digits == 64 else "promoted"
    with progress_scope(
        **context,
        precision_digits=digits,
        component_pass=component_pass,
    ):
        emit_progress(ProgressEventKind.CHECKPOINT_WRITING)
        _atomic_json(path, mapping)
        emit_progress(ProgressEventKind.CHECKPOINT_WRITTEN)
        emit_progress(
            ProgressEventKind.PRECISION_STAGE_COMPLETED,
            duration_seconds=duration_seconds,
            numerical_state=record.stages[-1].outcome.numerical_state,
            leaf_state=record.state,
        )


def _publish_terminal_solved_leaf(
    plan: CampaignPlan,
    leaf: CampaignLeafPlan,
    record: CampaignLeafRecord,
    store: SolvedLeafStore | None,
) -> None:
    if store is None or record.state not in {"PRODUCED", "UNRESOLVED"}:
        return
    try:
        _validate_cacheable_leaf_record(plan, leaf, record)
        store.publish(
            scientific_identity_sha256=scientific_computation_identity_sha256(
                plan, leaf
            ),
            leaf_id=leaf.leaf_id,
            record=record.to_mapping(),
            source_type="originating-campaign",
        )
        emit_progress(
            ProgressEventKind.LEAF_CACHE_PUBLISHED,
            state=record.state,
            stage_count=len(record.stages),
        )
    except (OSError, RuntimeError, ValueError) as error:
        emit_progress(
            ProgressEventKind.LEAF_CACHE_PUBLICATION_FAILED,
            error_type=type(error).__name__,
            message=str(error),
        )


def run_campaign_selection(
    plan: CampaignPlan,
    selection: CampaignSelection,
    backend: object,
    checkpoint_path: str | os.PathLike[str] | Path,
    *,
    resume: bool,
    solved_leaf_store: SolvedLeafStore | None = None,
) -> CampaignRunSummary:
    cache_lookups: dict[str, SolvedLeafLookup] = {}
    if solved_leaf_store is not None:
        leaf_by_id = {leaf.leaf_id: leaf for leaf in plan.leaves}
        for leaf_id in selection.leaf_ids:
            cache_lookups[leaf_id] = _authenticated_solved_leaf_lookup(
                plan, leaf_by_id[leaf_id], solved_leaf_store
            )
        compatible = sum(
            lookup.status is SolvedLeafLookupStatus.HIT
            for lookup in cache_lookups.values()
        )
        next_unsolved = next(
            (
                index
                for index, leaf_id in enumerate(selection.leaf_ids, start=1)
                if cache_lookups[leaf_id].status
                is not SolvedLeafLookupStatus.HIT
            ),
            None,
        )
        emit_progress(
            ProgressEventKind.SOLVED_LEAF_CACHE_SCANNED,
            compatible_count=compatible,
            stored_count=solved_leaf_store.stored_count,
            reusing_count=compatible,
            next_unsolved_index=next_unsolved,
            leaf_count=len(selection.leaf_ids),
            store_root=str(solved_leaf_store.root),
        )
    emit_progress(
        ProgressEventKind.CAMPAIGN_STARTED,
        campaign_id=plan.campaign_id,
        selection_id=selection.selection_id,
        leaf_count=len(selection.leaf_ids),
        resume=resume,
    )
    try:
        summary = _run_campaign_selection_active(
            plan,
            selection,
            backend,
            checkpoint_path,
            resume=resume,
            solved_leaf_store=solved_leaf_store,
            cache_lookups=cache_lookups,
        )
    except BaseException as error:
        emit_progress(
            ProgressEventKind.CAMPAIGN_FAILED,
            error_type=type(error).__name__,
            message=str(error),
        )
        raise
    emit_progress(
        ProgressEventKind.CAMPAIGN_COMPLETED,
        state=summary.state,
        executed_stage_count=summary.executed_stage_count,
        reused_stage_count=summary.reused_stage_count,
        result_count=summary.result_count,
        checkpoint_path=summary.checkpoint_path,
    )
    return summary


def _run_campaign_selection_active(
    plan: CampaignPlan,
    selection: CampaignSelection,
    backend: object,
    checkpoint_path: str | os.PathLike[str] | Path,
    *,
    resume: bool,
    solved_leaf_store: SolvedLeafStore | None,
    cache_lookups: Mapping[str, SolvedLeafLookup],
) -> CampaignRunSummary:
    if getattr(backend, "identity", None) != plan.backend_identity:
        raise ValueError("campaign backend identity does not match plan")
    available = getattr(backend, "precision_capabilities", None)
    if not isinstance(available, PrecisionCapabilities):
        raise ValueError("campaign backend precision capabilities are invalid")
    path = Path(checkpoint_path)
    if path.exists():
        if not resume:
            raise ValueError("campaign cold execution refuses an existing checkpoint")
        loaded_selection, existing, _ = _load_checkpoint(plan, path)
        if loaded_selection != selection:
            raise ValueError("campaign checkpoint selection does not match request")
        records = list(existing)
        for record in records:
            for stage in record.stages:
                prior = set(stage.runner_provenance["available_precision_digits"])
                if not prior.issubset(set(available.digits)):
                    raise ValueError(
                        "campaign backend precision availability is not a permitted superset"
                    )
    else:
        if resume:
            raise ValueError("campaign resume requires an existing checkpoint")
        records = []
    reused = sum(len(record.stages) for record in records)
    executed = 0
    leaf_by_id = {leaf.leaf_id: leaf for leaf in plan.leaves}
    for index, leaf_id in enumerate(selection.leaf_ids):
        leaf = leaf_by_id[leaf_id]
        context = _leaf_progress_context(leaf, index + 1, len(selection.leaf_ids))
        if index < len(records) and records[index].state in {
            "PRODUCED", "UNRESOLVED"
        }:
            with progress_scope(**context):
                emit_progress(
                    ProgressEventKind.LEAF_REUSED,
                    state=records[index].state,
                    stage_count=len(records[index].stages),
                )
            continue
        if index >= len(records) and solved_leaf_store is not None:
            lookup = cache_lookups.get(leaf.leaf_id)
            if lookup is None:
                lookup = _authenticated_solved_leaf_lookup(
                    plan, leaf, solved_leaf_store
                )
            if lookup.status is SolvedLeafLookupStatus.HIT:
                assert lookup.receipt is not None
                cached_record = CampaignLeafRecord.from_mapping(
                    lookup.receipt["record"]
                )
                _replace_record(records, index, cached_record)
                with progress_scope(**context):
                    emit_progress(ProgressEventKind.CHECKPOINT_WRITING)
                    _atomic_json(
                        path, _checkpoint_mapping(plan, selection, records)
                    )
                    emit_progress(ProgressEventKind.CHECKPOINT_WRITTEN)
                    emit_progress(
                        ProgressEventKind.LEAF_REUSED,
                        state=cached_record.state,
                        stage_count=len(cached_record.stages),
                        source="authenticated prior originating result",
                    )
                reused += len(cached_record.stages)
                continue
            if lookup.status is SolvedLeafLookupStatus.STALE:
                with progress_scope(**context):
                    emit_progress(
                        ProgressEventKind.LEAF_CACHE_STALE,
                        message=lookup.reason or "scientific identity changed",
                    )
            elif lookup.status is SolvedLeafLookupStatus.CORRUPT:
                with progress_scope(**context):
                    emit_progress(
                        ProgressEventKind.LEAF_CACHE_CORRUPT,
                        message=lookup.reason or "authentication failed",
                    )
        with progress_scope(**context):
            emit_progress(ProgressEventKind.LEAF_STARTED)
        record = records[index] if index < len(records) else None
        if record is None:
            outcome, stage_duration = _execute_campaign_stage_with_progress(
                backend, leaf, 64, context
            )
            if not isinstance(outcome, StageOutcome) or outcome.digits != 64:
                raise ValueError("campaign backend returned an invalid binary64 stage")
            executed += 1
            if leaf.role != "deep":
                record = CampaignLeafRecord(
                    leaf_id=leaf.leaf_id,
                    role=leaf.role,
                    state=_terminal_state(outcome),
                    stages=(_campaign_stage_record(plan, available, outcome),),
                )
            else:
                trigger_ids = _deep_trigger_ids(outcome)
                sentinel = leaf.leaf_id in set(
                    B_PRIME_RELEASE_DOMAIN.fixed_precision_sentinel_leaf_ids
                )
                promoted = bool(trigger_ids) or sentinel
                record = CampaignLeafRecord(
                    leaf_id=leaf.leaf_id,
                    role=leaf.role,
                    state=(
                        "MISSING_PRECISION"
                        if promoted and 80 not in available.digits
                        else "IN_PROGRESS" if promoted else _terminal_state(outcome)
                    ),
                    stages=(_campaign_stage_record(plan, available, outcome),),
                    trigger_ids=trigger_ids,
                    sentinel=sentinel,
                    missing_precision_digits=(
                        80
                        if promoted and 80 not in available.digits
                        else None
                    ),
                )
            _replace_record(records, index, record)
            _checkpoint_stage_with_progress(
                path,
                _checkpoint_mapping(plan, selection, records),
                context=context,
                digits=64,
                duration_seconds=stage_duration,
                record=record,
            )

        if record.state in {"PRODUCED", "UNRESOLVED"}:
            _publish_terminal_solved_leaf(
                plan, leaf, record, solved_leaf_store
            )
            with progress_scope(**context):
                emit_progress(
                    ProgressEventKind.LEAF_COMPLETED,
                    state=record.state,
                    stage_count=len(record.stages),
                )
            continue
        if len(record.stages) == 1:
            if 80 not in available.digits:
                continue
            outcome80, stage_duration = _execute_campaign_stage_with_progress(
                backend, leaf, 80, context, record.stages
            )
            if (
                not isinstance(outcome80, StageOutcome)
                or outcome80.digits != 80
                or outcome80.self_refinement_enclosed is None
                or outcome80.discrepancy_from_previous_abs is None
                or outcome80.discrepancy_enclosed is None
            ):
                raise ValueError("campaign backend returned incomplete 80-digit evidence")
            executed += 1
            comparison = None
            false_negative = False
            if record.sentinel:
                threshold = 0.25 * record.stages[0].outcome.local_disk_radius_abs
                false_negative = (
                    not record.trigger_ids
                    and outcome80.discrepancy_from_previous_abs > threshold
                )
                comparison = {
                    "binary64_to_80_discrepancy_abs": (
                        outcome80.discrepancy_from_previous_abs
                    ),
                    "trigger_threshold_abs": threshold,
                    "trigger_policy_false_negative": false_negative,
                }
                if false_negative:
                    record = CampaignLeafRecord(
                        leaf_id=record.leaf_id,
                        role=record.role,
                        state="INVALID_SENTINEL_FALSE_NEGATIVE",
                        stages=(
                            *record.stages,
                            _campaign_stage_record(plan, available, outcome80),
                        ),
                        trigger_ids=record.trigger_ids,
                        sentinel=True,
                        missing_precision_digits=120,
                        sentinel_comparison=comparison,
                    )
                    _replace_record(records, index, record)
                    _checkpoint_stage_with_progress(
                        path,
                        _checkpoint_mapping(plan, selection, records),
                        context=context,
                        digits=80,
                        duration_seconds=stage_duration,
                        record=record,
                    )
            if false_negative:
                pass
            elif outcome80.self_refinement_enclosed:
                state = _terminal_state(
                    outcome80, enclosed=bool(outcome80.discrepancy_enclosed)
                )
                missing = None
            elif 120 not in available.digits:
                state = "MISSING_PRECISION"
                missing = 120
            else:
                state = "IN_PROGRESS"
                missing = None
            if not false_negative:
                record = CampaignLeafRecord(
                    leaf_id=record.leaf_id,
                    role=record.role,
                    state=state,
                    stages=(
                        *record.stages,
                        _campaign_stage_record(plan, available, outcome80),
                    ),
                    trigger_ids=record.trigger_ids,
                    sentinel=record.sentinel,
                    missing_precision_digits=missing,
                    sentinel_comparison=comparison,
                )
                _replace_record(records, index, record)
                _checkpoint_stage_with_progress(
                    path,
                    _checkpoint_mapping(plan, selection, records),
                    context=context,
                    digits=80,
                    duration_seconds=stage_duration,
                    record=record,
                )

        if record.state in {"PRODUCED", "UNRESOLVED"}:
            _publish_terminal_solved_leaf(
                plan, leaf, record, solved_leaf_store
            )
            with progress_scope(**context):
                emit_progress(
                    ProgressEventKind.LEAF_COMPLETED,
                    state=record.state,
                    stage_count=len(record.stages),
                )
            continue
        if len(record.stages) == 2:
            if 120 not in available.digits:
                continue
            outcome120, stage_duration = _execute_campaign_stage_with_progress(
                backend, leaf, 120, context, record.stages
            )
            if (
                not isinstance(outcome120, StageOutcome)
                or outcome120.digits != 120
                or outcome120.discrepancy_from_previous_abs is None
                or outcome120.discrepancy_enclosed is None
            ):
                raise ValueError("campaign backend returned incomplete 120-digit evidence")
            executed += 1
            false_negative = record.state == "INVALID_SENTINEL_FALSE_NEGATIVE"
            record = CampaignLeafRecord(
                leaf_id=record.leaf_id,
                role=record.role,
                state=(
                    "INVALID_SENTINEL_FALSE_NEGATIVE"
                    if false_negative
                    else _terminal_state(
                        outcome120, enclosed=bool(outcome120.discrepancy_enclosed)
                    )
                ),
                stages=(
                    *record.stages,
                    _campaign_stage_record(plan, available, outcome120),
                ),
                trigger_ids=record.trigger_ids,
                sentinel=record.sentinel,
                missing_precision_digits=120 if false_negative else None,
                sentinel_comparison=record.sentinel_comparison,
            )
            _replace_record(records, index, record)
            _checkpoint_stage_with_progress(
                path,
                _checkpoint_mapping(plan, selection, records),
                context=context,
                digits=120,
                duration_seconds=stage_duration,
                record=record,
            )
        if record.state in {"PRODUCED", "UNRESOLVED"}:
            _publish_terminal_solved_leaf(
                plan, leaf, record, solved_leaf_store
            )
            with progress_scope(**context):
                emit_progress(
                    ProgressEventKind.LEAF_COMPLETED,
                    state=record.state,
                    stage_count=len(record.stages),
                )
    mapping = _checkpoint_mapping(plan, selection, records)
    return CampaignRunSummary(
        campaign_id=plan.campaign_id,
        selection_id=selection.selection_id,
        state=str(mapping["state"]),
        executed_stage_count=executed,
        reused_stage_count=reused,
        records=tuple(records),
        checkpoint_path=str(path),
    )


def validate_campaign_checkpoint(
    plan: CampaignPlan,
    checkpoint_path: str | os.PathLike[str] | Path,
    *,
    require_complete_campaign: bool = False,
) -> CampaignRunSummary:
    path = Path(checkpoint_path)
    selection, records, state = _load_checkpoint(plan, path)
    if require_complete_campaign:
        expected_ids = B_PRIME_RELEASE_DOMAIN.production_leaf_ids
        if selection.leaf_ids != expected_ids:
            raise ValueError("full campaign requires the exact ordered 553 leaf IDs")
        if tuple(record.leaf_id for record in records) != expected_ids:
            raise ValueError("full campaign has missing or extra leaf records")
        if any(record.state not in {"PRODUCED", "UNRESOLVED"} for record in records):
            raise ValueError("full campaign has an unexecuted or missing-precision leaf")
        if state != "COMPLETE":
            raise ValueError("full campaign checkpoint is not complete")
        leaf_by_id = {leaf.leaf_id: leaf for leaf in plan.leaves}
        if not all(
            _validate_record_semantics(
                leaf_by_id[record.leaf_id],
                record,
                plan.precision_factory_identity,
            )
            for record in records
        ):
            raise ValueError(
                "full campaign requires canonical production component results"
            )
    return CampaignRunSummary(
        campaign_id=plan.campaign_id,
        selection_id=selection.selection_id,
        state=state,
        executed_stage_count=0,
        reused_stage_count=sum(len(record.stages) for record in records),
        records=records,
        checkpoint_path=str(path),
    )


def import_campaign_checkpoint_to_solved_leaf_store(
    plan: CampaignPlan,
    checkpoint_path: str | os.PathLike[str] | Path,
    store: SolvedLeafStore,
) -> SolvedLeafImportSummary:
    """Import independently valid terminal records; never infer progress."""

    path = Path(checkpoint_path)
    try:
        diagnostic = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (json.JSONDecodeError, OSError, ValueError):
        diagnostic = None
    if (
        isinstance(diagnostic, Mapping)
        and diagnostic.get("schema") == PROGRESS_SCHEMA
        and "records" not in diagnostic
    ):
        return SolvedLeafImportSummary(0, 0, (), str(store.root))
    _, records, _ = _load_checkpoint_for_solved_leaf_import(
        plan, path
    )
    leaf_by_id = {leaf.leaf_id: leaf for leaf in plan.leaves}
    imported: list[str] = []
    skipped = 0
    for record in records:
        if record.state not in {"PRODUCED", "UNRESOLVED"}:
            skipped += 1
            continue
        leaf = leaf_by_id[record.leaf_id]
        _validate_cacheable_leaf_record(plan, leaf, record)
        store.publish(
            scientific_identity_sha256=scientific_computation_identity_sha256(
                plan, leaf
            ),
            leaf_id=leaf.leaf_id,
            record=record.to_mapping(),
            source_type="imported-authenticated-checkpoint",
        )
        imported.append(leaf.leaf_id)
    return SolvedLeafImportSummary(
        imported_count=len(imported),
        skipped_count=skipped,
        leaf_ids=tuple(imported),
        store_root=str(store.root),
    )


def _load_checkpoint_for_solved_leaf_import(
    plan: CampaignPlan, path: Path
) -> tuple[CampaignSelection, tuple[CampaignLeafRecord, ...], str]:
    """Authenticate an old checkpoint while permitting operational campaign drift."""

    value, bindings, records = _read_checkpoint_envelope(path)
    if set(bindings) != {
        "campaign_id",
        "campaign_bindings",
        "selection",
        "selection_jobs_sha256",
        "precision_factory_identity",
        "precision_contract_sha256",
    }:
        raise ValueError("campaign checkpoint binding fields are invalid")
    campaign_bindings = bindings["campaign_bindings"]
    if not isinstance(campaign_bindings, Mapping) or set(campaign_bindings) != set(
        plan.bindings
    ):
        raise ValueError("campaign checkpoint campaign bindings are invalid")
    stored_campaign_id = bindings["campaign_id"]
    if stored_campaign_id != f"b-prime-campaign-{_sha256(campaign_bindings)}":
        raise ValueError("campaign checkpoint campaign binding digest is invalid")
    for name in (
        "schema_version",
        "ordered_leaf_set_sha256",
        "root_set_sha256",
        "policy_sha256",
        "backend_identity_sha256",
        "precision_capabilities_sha256",
        "precision_factory_identity",
        "cohort_set_sha256",
    ):
        if campaign_bindings[name] != plan.bindings[name]:
            raise ValueError(
                f"campaign checkpoint scientific binding {name} is incompatible"
            )
    selection_value = bindings["selection"]
    if not isinstance(selection_value, Mapping) or set(selection_value) != {
        "selection_id", "role", "leaf_ids", "cohort_ids"
    }:
        raise ValueError("campaign checkpoint selection is invalid")
    role = selection_value["role"]
    leaf_ids = selection_value["leaf_ids"]
    cohort_ids = selection_value["cohort_ids"]
    if not isinstance(leaf_ids, list) or not isinstance(cohort_ids, list):
        raise ValueError("campaign checkpoint selection arrays are invalid")
    material = {
        "campaign_id": stored_campaign_id,
        "role": role,
        "leaf_ids": leaf_ids,
        "cohort_ids": cohort_ids,
    }
    if selection_value["selection_id"] != f"campaign-selection-{_sha256(material)}":
        raise ValueError("campaign checkpoint selection binding digest is invalid")
    if role == "all":
        selection = build_campaign_selection(
            plan, role="all", leaf_ids=None, cohort_ids=None
        )
    elif role == "merged":
        if cohort_ids:
            raise ValueError("merged campaign checkpoint cannot name cohorts")
        selection = _merged_selection(plan, leaf_ids)
    elif cohort_ids:
        selection = build_campaign_selection(
            plan, role=str(role), cohort_ids=cohort_ids
        )
    else:
        selection = build_campaign_selection(
            plan, role=str(role), leaf_ids=leaf_ids
        )
    if list(selection.leaf_ids) != leaf_ids or list(selection.cohort_ids) != cohort_ids:
        raise ValueError("campaign checkpoint selection is outside the current domain")
    current_bindings = _checkpoint_bindings(plan, selection)
    for name in (
        "selection_jobs_sha256",
        "precision_factory_identity",
        "precision_contract_sha256",
    ):
        if bindings[name] != current_bindings[name]:
            raise ValueError(
                f"campaign checkpoint scientific binding {name} is incompatible"
            )
    if len(records) > len(selection.leaf_ids):
        raise ValueError("campaign checkpoint has excess records")
    record_ids = tuple(record.leaf_id for record in records)
    if len(record_ids) != len(set(record_ids)):
        raise ValueError("campaign checkpoint contains duplicate leaf records")
    record_set = set(record_ids)
    expected_order = tuple(
        leaf_id for leaf_id in selection.leaf_ids if leaf_id in record_set
    )
    if record_ids != expected_order:
        raise ValueError("campaign checkpoint record order is invalid")
    if selection.role != "merged" and record_ids != selection.leaf_ids[:len(records)]:
        raise ValueError("selected campaign checkpoint records are not a prefix")
    leaf_by_id = {leaf.leaf_id: leaf for leaf in plan.leaves}
    for record in records:
        leaf = leaf_by_id[record.leaf_id]
        if record.role != leaf.role:
            raise ValueError("campaign checkpoint record role is invalid")
        _validate_record_semantics(
            leaf, record, plan.precision_factory_identity
        )
    expected_state = (
        "COMPLETE"
        if len(records) == len(selection.leaf_ids)
        and all(record.state in {"PRODUCED", "UNRESOLVED"} for record in records)
        else "PARTIAL"
    )
    if value["state"] != expected_state or value["release_admissible"] is not False:
        raise ValueError("campaign checkpoint state is invalid")
    return selection, records, expected_state


def merge_campaign_checkpoints(
    plan: CampaignPlan,
    checkpoint_paths: Sequence[str | os.PathLike[str] | Path],
    output_path: str | os.PathLike[str] | Path,
) -> CampaignRunSummary:
    paths = tuple(Path(path) for path in checkpoint_paths)
    if not paths:
        raise ValueError("campaign merge requires at least one checkpoint")
    output = Path(output_path)
    if output.exists():
        raise ValueError("campaign merge refuses an existing output")
    selected_ids: set[str] = set()
    record_by_leaf: dict[str, CampaignLeafRecord] = {}
    for path in paths:
        selection, records, _ = _load_checkpoint(plan, path)
        selected_ids.update(selection.leaf_ids)
        for record in records:
            existing = record_by_leaf.get(record.leaf_id)
            if existing is not None and existing.to_mapping() != record.to_mapping():
                raise ValueError(
                    f"campaign checkpoint overlap disagrees for {record.leaf_id}"
                )
            record_by_leaf[record.leaf_id] = record
    canonical_ids = tuple(
        leaf.leaf_id for leaf in plan.leaves if leaf.leaf_id in selected_ids
    )
    selection = _merged_selection(plan, canonical_ids)
    records = tuple(
        record_by_leaf[leaf_id]
        for leaf_id in canonical_ids
        if leaf_id in record_by_leaf
    )
    _atomic_json(output, _checkpoint_mapping(plan, selection, records))
    mapping = _checkpoint_mapping(plan, selection, records)
    return CampaignRunSummary(
        campaign_id=plan.campaign_id,
        selection_id=selection.selection_id,
        state=str(mapping["state"]),
        executed_stage_count=0,
        reused_stage_count=sum(len(record.stages) for record in records),
        records=records,
        checkpoint_path=str(output),
    )


_SMOKE_BACKEND_IDENTITY = BackendIdentity(
    backend_id="campaign-replay-and-synthetic-orchestration",
    implementation_version="1",
    source_commit="0c1e8a3d3bca6e608c34e111476a4f6dcb73e86e",
    source_blobs=(
        ("recorded-replay", "341ce9db7dda8108a96e3f7536380b9b45bd6c3b"),
        ("refinement", "69733ac4d0a74696445ff683aaaaeb5fd64e44c1"),
    ),
    runtime_fingerprint="authenticated-recorded-replay-plus-synthetic-contract-no-solver",
)


def _smoke_deep_diagnostics(*, predicted_digits: float) -> dict[str, object]:
    return {
        "condition_amplifier_abs": 10.0,
        "predicted_reliable_decimal_digits": predicted_digits,
        "step_richardson_disagreement_abs": 0.0,
        "repeat_polish_delta_abs": 0.0,
        "angular_refinement_delta_abs": 0.0,
        "independent_path_delta_abs": 0.0,
        "diagnostic_ceiling_abs": 1.0e-8,
        "denominator_or_calibration_disk_contains_zero": False,
    }


class _OrchestrationSmokeBackend:
    identity = _SMOKE_BACKEND_IDENTITY

    def __init__(self, precision_capabilities: PrecisionCapabilities) -> None:
        self.precision_capabilities = precision_capabilities
        self._replay = RecordedReplayBackend.load()

    def evidence_kind(self, leaf_id: str) -> str:
        return (
            "authenticated-recorded-replay"
            if leaf_id in _RECORDED_CAMPAIGN_SMOKE_IDS
            else "synthetic-orchestration-contract"
        )

    def execute_stage(self, leaf: CampaignLeafPlan, digits: int) -> StageOutcome:
        if digits not in self.precision_capabilities.digits:
            raise ValueError("smoke backend lacks requested precision capability")
        if leaf.leaf_id in _RECORDED_CAMPAIGN_SMOKE_IDS:
            if digits != 64:
                raise ValueError("recorded replay has binary64 evidence only")
            replay_job = ResponseComponentJob.from_leaf_id(
                leaf.leaf_id,
                policy=leaf.job.policy,
                backend_identity=self._replay.identity,
            )
            result = run_component(replay_job, self._replay)
            component_result = {
                "evidence_kind": "authenticated-recorded-replay",
                "recorded_backend_id": RECORDED_REPLAY_BACKEND_ID,
                "result": result.to_mapping(),
            }
            return StageOutcome(
                digits=64,
                numerical_state=result.status.value,
                component_result=component_result,
                local_disk_radius_abs=sum(result.error_channels.values()),
                signed_error_channels=_component_stage_signed_error_channels(
                    component_result, result
                ),
            )

        payload = {
            "evidence_kind": "synthetic-orchestration-contract",
            "leaf_id": leaf.leaf_id,
            "role": leaf.role,
            "mechanism_id": leaf.mechanism_id,
            "digits": digits,
        }
        if leaf.leaf_id == PREDECLARED_CAMPAIGN_SMOKE_LEAF_IDS[7]:
            if digits == 64:
                return StageOutcome(
                    digits=64,
                    numerical_state="CONVERGED",
                    component_result=payload,
                    local_disk_radius_abs=1.0e-6,
                    signed_error_channels=synthetic_stage_signed_error_channels(
                        payload, 1.0e-6
                    ),
                    deep_diagnostics=_smoke_deep_diagnostics(
                        predicted_digits=12.0
                    ),
                )
            return StageOutcome(
                digits=80,
                numerical_state="CONVERGED",
                component_result=payload,
                local_disk_radius_abs=1.0e-6,
                signed_error_channels=synthetic_stage_signed_error_channels(
                    payload, 1.0e-6
                ),
                self_refinement_enclosed=True,
                discrepancy_from_previous_abs=1.0e-8,
                discrepancy_enclosed=True,
            )
        if leaf.leaf_id == PREDECLARED_CAMPAIGN_SMOKE_LEAF_IDS[8]:
            if digits == 64:
                return StageOutcome(
                    digits=64,
                    numerical_state="CONVERGED",
                    component_result=payload,
                    local_disk_radius_abs=1.0e-6,
                    signed_error_channels=synthetic_stage_signed_error_channels(
                        payload, 1.0e-6
                    ),
                    deep_diagnostics=_smoke_deep_diagnostics(predicted_digits=8.0),
                )
            if digits == 80:
                return StageOutcome(
                    digits=80,
                    numerical_state="CONVERGED",
                    component_result=payload,
                    local_disk_radius_abs=1.0e-6,
                    signed_error_channels=synthetic_stage_signed_error_channels(
                        payload, 1.0e-6
                    ),
                    self_refinement_enclosed=False,
                    discrepancy_from_previous_abs=1.0e-7,
                    discrepancy_enclosed=False,
                )
            return StageOutcome(
                digits=120,
                numerical_state="CONVERGED",
                component_result=payload,
                local_disk_radius_abs=1.0e-6,
                signed_error_channels=synthetic_stage_signed_error_channels(
                    payload, 1.0e-6
                ),
                discrepancy_from_previous_abs=1.0e-8,
                discrepancy_enclosed=True,
            )
        if leaf.leaf_id == PREDECLARED_CAMPAIGN_SMOKE_LEAF_IDS[9]:
            return StageOutcome(
                digits=64,
                numerical_state="NOT_CONVERGED",
                component_result=payload,
                local_disk_radius_abs=1.0e-6,
                signed_error_channels=synthetic_stage_signed_error_channels(
                    payload, 1.0e-6
                ),
                deep_diagnostics=_smoke_deep_diagnostics(predicted_digits=8.0),
            )
        return StageOutcome(
            digits=64,
            numerical_state="CONVERGED",
            component_result=payload,
            local_disk_radius_abs=1.0e-6,
            signed_error_channels=synthetic_stage_signed_error_channels(
                payload, 1.0e-6
            ),
        )


def run_predeclared_campaign_smoke() -> CampaignSmokeSummary:
    if len(PREDECLARED_CAMPAIGN_SMOKE_LEAF_IDS) != 10 or len(
        set(PREDECLARED_CAMPAIGN_SMOKE_LEAF_IDS)
    ) != 10:
        raise ValueError("campaign smoke selection must contain exactly ten leaves")
    full_capabilities = PrecisionCapabilities((64, 80, 120))
    full_plan = build_campaign_plan(
        policy=NumericalPolicy(),
        backend_identity=_SMOKE_BACKEND_IDENTITY,
        precision_capabilities=full_capabilities,
    )
    binary64_capabilities = PrecisionCapabilities((64,))
    binary64_plan = build_campaign_plan(
        policy=NumericalPolicy(),
        backend_identity=_SMOKE_BACKEND_IDENTITY,
        precision_capabilities=binary64_capabilities,
    )
    leaf_by_id = {leaf.leaf_id: leaf for leaf in full_plan.leaves}
    records: list[CampaignSmokeRecord] = []
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        for index, leaf_id in enumerate(PREDECLARED_CAMPAIGN_SMOKE_LEAF_IDS):
            tail = index == len(PREDECLARED_CAMPAIGN_SMOKE_LEAF_IDS) - 1
            plan = binary64_plan if tail else full_plan
            capabilities = binary64_capabilities if tail else full_capabilities
            backend = _OrchestrationSmokeBackend(capabilities)
            leaf = leaf_by_id[leaf_id]
            selection = build_campaign_selection(
                plan, role=leaf.role, leaf_ids=(leaf_id,)
            )
            summary = run_campaign_selection(
                plan,
                selection,
                backend,
                directory / f"smoke-{index:02d}.json",
                resume=False,
            )
            records.append(CampaignSmokeRecord(
                leaf_id=leaf_id,
                evidence_kind=backend.evidence_kind(leaf_id),
                record=summary.records[0],
            ))
    return CampaignSmokeSummary(tuple(records))


def _component_result_delta(
    left: ComponentResult, right: ComponentResult
) -> complex:
    if left.response is not None and right.response is not None:
        return left.response - right.response
    return left.baseline.omega - right.baseline.omega


def _native_deep_diagnostics(
    leaf: CampaignLeafPlan,
    result: ComponentResult,
    local_radius: float,
) -> dict[str, object]:
    baseline = result.baseline
    condition = max(1.0, 1.0 / baseline.determinant_derivative_abs)
    response_scale = max(
        abs(result.response) if result.response is not None else abs(baseline.omega),
        1.0e-300,
    )
    uncertainty = max(
        local_radius,
        baseline.newton_correction_estimate,
        1.0e-300,
    )
    predicted_digits = max(
        0.0,
        min(300.0, -math.log10(uncertainty / response_scale)),
    )
    denominator_contains_zero = False
    if leaf.mechanism_id == "horizon-admittance":
        horizon = 1.0 + math.sqrt(max(0.0, 1.0 - leaf.job.spin**2))
        horizon_frequency = leaf.job.spin / (2.0 * horizon)
        calibration = 2.0j * (
            baseline.omega - leaf.job.mode.m * horizon_frequency
        )
        denominator_contains_zero = abs(calibration) <= (
            2.0 * baseline.newton_correction_estimate + local_radius
        )
    else:
        denominator_contains_zero = (
            baseline.determinant_derivative_abs
            <= baseline.determinant_residual_abs + 1.0e-300
        )
    return {
        "condition_amplifier_abs": condition,
        "predicted_reliable_decimal_digits": predicted_digits,
        "step_richardson_disagreement_abs": result.error_channels["amplitude"],
        "repeat_polish_delta_abs": max(
            baseline.newton_correction_estimate,
            result.error_channels["signed-root"],
        ),
        "angular_refinement_delta_abs": result.error_channels["resolution"],
        "independent_path_delta_abs": result.error_channels["seed-path"],
        "diagnostic_ceiling_abs": max(
            0.25 * local_radius,
            4.0 * baseline.newton_correction_estimate,
            1.0e-300,
        ),
        "denominator_or_calibration_disk_contains_zero": denominator_contains_zero,
    }


def _run_component_with_progress(
    job: ResponseComponentJob, backend: object, component_pass: str
) -> ComponentResult:
    started = time.monotonic()
    with progress_scope(component_pass=component_pass):
        emit_progress(ProgressEventKind.COMPONENT_PASS_STARTED)
        try:
            result = run_component(job, backend)  # type: ignore[arg-type]
        except BaseException as error:
            emit_progress(
                ProgressEventKind.ERROR,
                component_pass=component_pass,
                error_type=type(error).__name__,
                message=str(error),
                elapsed_seconds=time.monotonic() - started,
            )
            raise
        emit_progress(
            ProgressEventKind.COMPONENT_PASS_COMPLETED,
            component_pass=component_pass,
            status=result.status.value,
            readout_count=len(result.raw_readouts),
            elapsed_seconds=time.monotonic() - started,
        )
        return result


class NativeCampaignStageBackend:
    """Package-owned binary64 and Julia BigFloat M02 campaign backend."""

    identity = VettedNativeDeterminantKernel.identity

    def __init__(
        self,
        adapter: NativeDeterminantAdapter,
        precision_capabilities: PrecisionCapabilities,
        generated_cache: GeneratedGsnCache,
        julia_adapter: JuliaResponseAdapter | None = None,
    ) -> None:
        if any(
            digits > 64 for digits in precision_capabilities.digits
        ) and julia_adapter is None:
            raise NativeResourceUnavailableError(
                "promoted precision was selected but the Julia worker is unavailable"
            )
        self.adapter = adapter
        self.precision_capabilities = precision_capabilities
        self.generated_cache = generated_cache
        self.julia_adapter = julia_adapter

    @classmethod
    def from_selection(
        cls, plan: CampaignPlan, selection: CampaignSelection
    ) -> "NativeCampaignStageBackend":
        try:
            pairs = parameter_pairs_for_selection(plan, selection)
            generated = ensure_generated_gsn_cache(pairs)
        except GsnCacheProductionError as error:
            raise NativeResourceUnavailableError(str(error)) from error
        kernel = VettedNativeDeterminantKernel.from_generated_resource(
            generated.path, generated.sha256
        )
        julia_adapter = None
        if any(digits > 64 for digits in plan.precision_capabilities.digits):
            try:
                julia_adapter = JuliaResponseAdapter.from_runtime_receipt()
            except JuliaResponseBackendError as error:
                raise NativeResourceUnavailableError(str(error)) from error
        return cls(
            NativeDeterminantAdapter(identity=kernel.identity, kernel=kernel),
            plan.precision_capabilities,
            generated,
            julia_adapter,
        )

    def _cache_runtime(self) -> dict[str, object]:
        return {
            "backend": "python-binary64-gsn",
            "record_artifact_ids": list(
                self.generated_cache.record_artifact_ids
            ),
            "cache_path": str(self.generated_cache.path),
            "cache_sha256_observed": self.generated_cache.sha256,
            "parameter_pairs": [
                pair.to_mapping() for pair in self.generated_cache.parameter_pairs
            ],
        }

    def execute_stage(self, leaf: CampaignLeafPlan, digits: int) -> StageOutcome:
        if digits != 64:
            raise NativeResourceUnavailableError(
                "promoted precision must use execute_promoted_stage"
            )
        result = _run_component_with_progress(
            leaf.job, self.adapter, "primary"
        )
        component_result = {
            "evidence_kind": "native-task-008-component-engine",
            "result": result.to_mapping(),
            "scientific_runtime": self._cache_runtime(),
        }
        local_radius = sum(result.error_channels.values())
        return StageOutcome(
            digits=64,
            numerical_state=result.status.value,
            component_result=component_result,
            local_disk_radius_abs=local_radius,
            signed_error_channels=_component_stage_signed_error_channels(
                component_result, result
            ),
            deep_diagnostics=(
                _native_deep_diagnostics(leaf, result, local_radius)
                if leaf.role == "deep"
                else None
            ),
        )

    def execute_promoted_stage(
        self,
        leaf: CampaignLeafPlan,
        digits: int,
        previous_outcomes: Sequence[StageOutcome],
    ) -> StageOutcome:
        if digits not in self.precision_capabilities.digits or digits not in (80, 120):
            raise NativeResourceUnavailableError(
                f"native campaign backend lacks {digits}-digit capability"
            )
        expected_previous = (64,) if digits == 80 else (64, 80)
        if tuple(stage.digits for stage in previous_outcomes) != expected_previous:
            raise ValueError("promoted precision prior-stage sequence is invalid")
        if self.julia_adapter is None:
            raise NativeResourceUnavailableError("M02 Julia precision worker is unavailable")
        primary_backend = JuliaPrecisionRootBackend(
            self.identity, self.julia_adapter, digits
        )
        result = _run_component_with_progress(
            leaf.job, primary_backend, "primary"
        )
        previous_result = ComponentResult.from_mapping(
            previous_outcomes[-1].component_result["result"]
        )
        precision_delta = _component_result_delta(result, previous_result)
        base_radius = sum(result.error_channels.values())
        discrepancy_enclosed = (
            abs(precision_delta)
            <= base_radius + previous_outcomes[-1].local_disk_radius_abs
        )
        repeat_delta = 0.0j
        repeat_result = None
        self_refinement_enclosed = None
        if digits == 80:
            repeat_backend = JuliaPrecisionRootBackend(
                self.identity, self.julia_adapter, digits, refinement=1
            )
            repeat_result = _run_component_with_progress(
                leaf.job, repeat_backend, "self-refinement"
            )
            repeat_delta = _component_result_delta(repeat_result, result)
            repeat_radius = sum(repeat_result.error_channels.values())
            self_refinement_enclosed = (
                result.status == repeat_result.status
                and abs(repeat_delta) <= base_radius + repeat_radius
            )
        component_result = {
            "evidence_kind": "package-owned-julia-promoted-component-engine",
            "result": result.to_mapping(),
            "self_refinement_result": (
                None if repeat_result is None else repeat_result.to_mapping()
            ),
            "scientific_runtime": primary_backend.scientific_runtime,
        }
        local_radius = base_radius + abs(repeat_delta) + abs(precision_delta)
        return StageOutcome(
            digits=digits,
            numerical_state=result.status.value,
            component_result=component_result,
            local_disk_radius_abs=local_radius,
            signed_error_channels=_component_stage_signed_error_channels(
                component_result,
                result,
                repeat_delta=repeat_delta,
                precision_delta=precision_delta,
            ),
            self_refinement_enclosed=self_refinement_enclosed,
            discrepancy_from_previous_abs=abs(precision_delta),
            discrepancy_enclosed=discrepancy_enclosed,
        )
