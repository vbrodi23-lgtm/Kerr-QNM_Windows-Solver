"""Deterministic B-prime campaign planning and selected orchestration.

This module is build-only infrastructure.  Planning resolves authenticated
installed roots but cannot start determinant work; execution always requires an
explicit injected component backend.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from contextvars import ContextVar
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
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
    ComponentStatus,
    NativeDeterminantAdapter,
    NativeResourceUnavailableError,
    NumericalConditioningEvidence,
    NumericalPolicy,
    RECORDED_REPLAY_BACKEND_ID,
    RecordedReplayBackend,
    ResponseComponentJob,
    VettedNativeDeterminantKernel,
    regularised_gsn_precision_policy,
    root_readout_preserves_authenticated_branch,
    run_component,
)
from .gsn_cache_producer import (
    GeneratedGsnCache,
    GsnCacheProductionError,
    ensure_generated_gsn_cache,
    parameter_pairs_for_selection,
)
from .julia_response_backend import (
    NUMERICAL_CONTROL_FAILURE_CODES,
    JuliaNumericalControlError,
    JuliaODEResourceLimitError,
    JuliaPrecisionRootBackend,
    JuliaRootReadoutResourceLimitError,
    JuliaResponseAdapter,
    JuliaResponseBackendError,
    JuliaWorkerTimeoutError,
    _validated_execution_resource_policy,
    _valid_numerical_control_diagnostics,
    worker_failure_payload as _julia_worker_failure_payload,
)
from .progress import PROGRESS_SCHEMA, ProgressEventKind, emit_progress, progress_scope
from .solved_leaf_cache import (
    SolvedLeafLookup,
    SolvedLeafLookupStatus,
    SolvedLeafStore,
)


CAMPAIGN_SCHEMA_VERSION = 2
CAMPAIGN_CHECKPOINT_SCHEMA_VERSION = 6
_LEGACY_CAMPAIGN_CHECKPOINT_SCHEMA_VERSION = 3
_HISTORICAL_CAMPAIGN_CHECKPOINT_SCHEMA_VERSIONS = frozenset({3, 4, 5})
_PRECISION_DIGITS = frozenset({64, 80, 120})
_FAILED_PREFLIGHT_COMPARISON_KIND = (
    "same-precision-120-base-vs-refinement/v1"
)
_FACTORED_HOMOGENEOUS_ODE_SCOPE_ID = "factored-homogeneous-gsn/v1"
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
_EXECUTION_ROLE_ORDER = {
    "primary": 0,
    "deep": 1,
    "control": 2,
}
_LEGACY_MIGRATION_LOCK_TIMEOUT_SECONDS = 1.0
_LEGACY_MIGRATION_LOCK_RETRY_SECONDS = 0.01
_BINARY64_ROOT_CORRECTION_TOLERANCE_ABS = 2.0e-11
_ACTIVE_CAMPAIGN_LEAF_CONTEXT: ContextVar[Mapping[str, object] | None] = ContextVar(
    "windows_solver_active_campaign_leaf_context", default=None
)
_EXECUTION_MECHANISM_ORDER = {
    "horizon-admittance": 0,
    "exterior-light-ring": 1,
    "exterior-throat-kappa": 2,
    "exterior-alpha-half": 3,
    "exterior-alpha-one": 3,
    "exterior-fixed-r3": 4,
}
_EXECUTION_MODE_ORDER = {
    "primary": {
        "220": 0, "440": 1, "330": 2, "221": 3,
        "441": 4, "331": 5, "222": 6,
    },
    "deep": {
        "220": 0, "221": 1, "222": 2, "210": 3,
    },
    "control": {
        "210": 0, "2-minus-2-0": 1, "320": 2, "3-minus-3-0": 3,
    },
}
PREDECLARED_CAMPAIGN_SMOKE_LEAF_IDS = (
    "b-prime-leaf-9e5777728144433e089f9559b92b6e139e16115a5a53099f40403a45297aa3c3",
    "b-prime-leaf-7ef38d6f95c161d0b4c6650d470898c0742ad6ae8440e89956312344c0db6aac",
    "b-prime-leaf-4eb508d767bea5cddc3f7c0eb120c1a9cc184122900f4d7ec86b56c98ddab596",
    "b-prime-leaf-3ee2b2dcdc5276cbcd51264f1210002314acd3ff845bb7a464f1e9333e9115c5",
    "b-prime-leaf-e0a48b72b4071c5c88c66955420dc2748cfeeac577b8fd1c399f171f5fa08475",
    "b-prime-leaf-fc5998bf989465575d276b6a1ad4758dbb1cdacc25e1c7554185f0c38e170332",
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
    not_applicable_families: frozenset[str] = frozenset(),
) -> tuple[Mapping[str, object], ...]:
    """Build a complete, explicitly signed ledger bound to one stage result."""

    if set(family_deltas) != set(STAGE_SIGNED_ERROR_FAMILIES):
        raise ValueError("explicit stage ledger requires every signed-error family")
    if not set(not_applicable_families).issubset(STAGE_SIGNED_ERROR_FAMILIES):
        raise ValueError("stage ledger not-applicable family is invalid")
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
                "derivation": (
                    f"not-applicable-{family}"
                    if family in not_applicable_families
                    else f"explicit-signed-{family}"
                ),
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
    *,
    precision_ladder_applicable: bool = True,
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
        not_applicable_families=(
            frozenset()
            if precision_ladder_applicable
            else frozenset({"precision-ladder-discrepancy"})
        ),
    )


def _component_stage_signed_error_channels(
    component_result: Mapping[str, object],
    result: ComponentResult,
    *,
    repeat_delta: complex = 0.0j,
    precision_delta: complex = 0.0j,
    precision_ladder_applicable: bool = True,
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
        not_applicable_families=(
            frozenset()
            if precision_ladder_applicable
            else frozenset({"precision-ladder-discrepancy"})
        ),
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


_CONTAINABLE_FAILURE_CODES = frozenset({
    "ODE_RESOURCE_LIMIT",
    "ROOT_READOUT_RESOURCE_INFEASIBLE",
    "WORKER_TIMEOUT",
}) | NUMERICAL_CONTROL_FAILURE_CODES
_CONTAINABLE_FAILURE_STATES = {
    "ODE_RESOURCE_LIMIT": "EXECUTION_RESOURCE_LIMITED",
    "ROOT_READOUT_RESOURCE_INFEASIBLE": "EXECUTION_RESOURCE_LIMITED",
    "WORKER_TIMEOUT": "WORKER_TIMEOUT",
    **{
        code: "NUMERICAL_CONTROL_FAILURE"
        for code in NUMERICAL_CONTROL_FAILURE_CODES
    },
}
_CONTAINABLE_EXCEPTION_TYPES = (
    JuliaODEResourceLimitError,
    JuliaRootReadoutResourceLimitError,
    JuliaWorkerTimeoutError,
    JuliaNumericalControlError,
)


def _validated_attempt_failure_receipt(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("campaign execution attempt receipt is invalid")
    probe = JuliaResponseBackendError("attempt receipt validation")
    probe.worker_failure = value  # type: ignore[attr-defined]
    bounded = _julia_worker_failure_payload(probe)
    if bounded is None or bounded != dict(value):
        raise ValueError("campaign execution attempt receipt is malformed")
    failure = bounded.get("failure")
    if not isinstance(failure, Mapping):
        raise ValueError("campaign execution attempt lacks a structured failure")
    code = failure.get("failure_code")
    if (
        code not in _CONTAINABLE_FAILURE_CODES
        or failure.get("failure_class") != "CONTROL"
        or not isinstance(failure.get("retryable"), bool)
    ):
        raise ValueError("campaign execution attempt is not containable")
    if code in NUMERICAL_CONTROL_FAILURE_CODES and (
        failure.get("retryable")
        is not (code == "INSUFFICIENT_ASYMPTOTIC_PRECISION")
        or not _valid_numerical_control_diagnostics(failure)
    ):
        raise ValueError(
            "campaign execution attempt receipt numerical-control diagnostics "
            "are invalid"
        )
    resource_policy = failure.get("execution_resource_policy")
    identity_fields = {"schema", "version", "sha256"}
    full_policy_fields = identity_fields | {
        "worker_request_wall_clock_seconds",
        "cooperative_request_deadline_seconds",
        "homogeneous_ode_maxiters",
        "max_accepted_steps_per_homogeneous_leg",
        "max_rhs_evaluations_per_homogeneous_leg",
        "homogeneous_leg_wall_clock_seconds",
    }
    resource_policy_fields = frozenset(resource_policy) if isinstance(
        resource_policy, Mapping
    ) else frozenset()
    if (
        not isinstance(resource_policy, Mapping)
        or resource_policy_fields
        not in {frozenset(identity_fields), frozenset(full_policy_fields)}
        or resource_policy.get("schema")
        != "windows-solver.execution-resource-policy/1"
        or resource_policy.get("version") != 1
        or not isinstance(resource_policy.get("sha256"), str)
        or len(resource_policy["sha256"]) != 64
        or any(
            character not in "0123456789abcdef"
            for character in resource_policy["sha256"]
        )
    ):
        raise ValueError(
            "campaign execution attempt resource-policy identity is invalid"
        )
    if resource_policy_fields == full_policy_fields:
        for name in (
            "worker_request_wall_clock_seconds",
            "cooperative_request_deadline_seconds",
            "homogeneous_ode_maxiters",
            "max_accepted_steps_per_homogeneous_leg",
            "max_rhs_evaluations_per_homogeneous_leg",
        ):
            item = resource_policy[name]
            if isinstance(item, bool) or not isinstance(item, int) or item < 1:
                raise ValueError(
                    "campaign execution attempt resource-policy limit is invalid"
                )
        leg_timeout = resource_policy["homogeneous_leg_wall_clock_seconds"]
        if leg_timeout is not None and (
            isinstance(leg_timeout, bool)
            or not isinstance(leg_timeout, int)
            or leg_timeout < 1
        ):
            raise ValueError(
                "campaign execution attempt resource-policy leg limit is invalid"
            )
        if (
            resource_policy["worker_request_wall_clock_seconds"] < 60
            or resource_policy["cooperative_request_deadline_seconds"]
            >= resource_policy["worker_request_wall_clock_seconds"]
        ):
            raise ValueError(
                "campaign execution attempt resource-policy deadline is invalid"
            )
        material = {
            key: item
            for key, item in resource_policy.items()
            if key != "sha256"
        }
        if resource_policy["sha256"] != _sha256(material):
            raise ValueError(
                "campaign execution attempt resource-policy digest is invalid"
            )
    return bounded


@dataclass(frozen=True, slots=True)
class CampaignExecutionAttempt:
    """One append-only operational attempt; never scientific evidence."""

    attempt_ordinal: int
    leaf_id: str
    leaf_index: int
    role: str
    state: str
    precision_digits: int
    failure_code: str
    failure_receipt: Mapping[str, object]
    created_at_utc: str

    def __post_init__(self) -> None:
        if self.attempt_ordinal < 1 or self.leaf_index < 1:
            raise ValueError("campaign execution attempt ordinal is invalid")
        if self.precision_digits not in {80, 120}:
            raise ValueError("campaign execution attempt precision is invalid")
        if self.failure_code not in _CONTAINABLE_FAILURE_CODES:
            raise ValueError("campaign execution attempt failure code is invalid")
        if self.state != _CONTAINABLE_FAILURE_STATES[self.failure_code]:
            raise ValueError("campaign execution attempt state is invalid")
        receipt = _validated_attempt_failure_receipt(self.failure_receipt)
        failure = receipt["failure"]
        assert isinstance(failure, Mapping)
        if failure["failure_code"] != self.failure_code:
            raise ValueError("campaign execution attempt code does not match receipt")
        if failure.get("precision_digits") != self.precision_digits:
            raise ValueError(
                "campaign execution attempt precision does not match receipt"
            )
        expected_decision = _numerical_failure_promotion_decision(
            failure, self.precision_digits
        )
        raw_decision = failure.get("promotion_decision")
        if expected_decision is None:
            if raw_decision is not None:
                raise ValueError(
                    "campaign execution attempt promotion decision is unexpected"
                )
        elif raw_decision is None or (
            _validated_promotion_decision(raw_decision) != expected_decision
        ):
            raise ValueError(
                "campaign execution attempt promotion decision is invalid"
            )
        try:
            parsed = datetime.fromisoformat(self.created_at_utc.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("campaign execution attempt timestamp is invalid") from error
        if parsed.tzinfo is None:
            raise ValueError("campaign execution attempt timestamp lacks timezone")
        object.__setattr__(self, "failure_receipt", receipt)

    @property
    def content(self) -> dict[str, object]:
        return {
            "attempt_ordinal": self.attempt_ordinal,
            "leaf_id": self.leaf_id,
            "leaf_index": self.leaf_index,
            "role": self.role,
            "state": self.state,
            "precision_digits": self.precision_digits,
            "failure_code": self.failure_code,
            "failure_receipt": dict(self.failure_receipt),
            "created_at_utc": self.created_at_utc,
        }

    @property
    def attempt_sha256(self) -> str:
        return _sha256(self.content)

    def to_mapping(self) -> dict[str, object]:
        return {**self.content, "attempt_sha256": self.attempt_sha256}

    @classmethod
    def from_mapping(cls, value: object) -> "CampaignExecutionAttempt":
        if not isinstance(value, Mapping) or set(value) != {
            "attempt_ordinal",
            "leaf_id",
            "leaf_index",
            "role",
            "state",
            "precision_digits",
            "failure_code",
            "failure_receipt",
            "created_at_utc",
            "attempt_sha256",
        }:
            raise ValueError("campaign execution attempt fields are invalid")
        for name in ("attempt_ordinal", "leaf_index", "precision_digits"):
            if isinstance(value[name], bool) or not isinstance(value[name], int):
                raise ValueError(
                    f"campaign execution attempt {name} is invalid"
                )
        for name in (
            "leaf_id",
            "role",
            "state",
            "failure_code",
            "created_at_utc",
            "attempt_sha256",
        ):
            if not isinstance(value[name], str) or not value[name]:
                raise ValueError(
                    f"campaign execution attempt {name} is invalid"
                )
        attempt = cls(
            attempt_ordinal=value["attempt_ordinal"],
            leaf_id=value["leaf_id"],
            leaf_index=value["leaf_index"],
            role=value["role"],
            state=value["state"],
            precision_digits=value["precision_digits"],
            failure_code=value["failure_code"],
            failure_receipt=value["failure_receipt"],
            created_at_utc=value["created_at_utc"],
        )
        if value["attempt_sha256"] != attempt.attempt_sha256:
            raise ValueError("campaign execution attempt digest is invalid")
        return attempt


def _validate_failed_preflight_attempt_request(
    attempt: CampaignExecutionAttempt,
    leaf: CampaignLeafPlan,
    *,
    precision_digits: int,
    allowed_refinement_levels: frozenset[int],
    required_failure_code: str | None,
) -> None:
    """Authenticate a preflight failure against its canonical worker request."""

    if (
        attempt.leaf_id != leaf.leaf_id
        or attempt.role != leaf.role
        or attempt.precision_digits != precision_digits
        or (
            required_failure_code is not None
            and attempt.failure_code != required_failure_code
        )
        or attempt.failure_code not in _CONTAINABLE_FAILURE_CODES
        or attempt.state != _CONTAINABLE_FAILURE_STATES[attempt.failure_code]
    ):
        raise ValueError("failed-preflight attempt identity is invalid")
    failure = attempt.failure_receipt.get("failure")
    if not isinstance(failure, Mapping):
        raise ValueError("failed-preflight attempt receipt is missing")
    refinement_level = failure.get("refinement_level")
    if (
        type(refinement_level) is not int
        or refinement_level not in allowed_refinement_levels
    ):
        raise ValueError("failed-preflight request refinement is invalid")
    identity = {
        "job_id": leaf.job.job_id,
        "leaf_id": leaf.leaf_id,
        "role": leaf.role,
        "job_policy_sha256": leaf.job.policy.identity_sha256,
        "backend_identity_sha256": leaf.job.backend_identity.identity_sha256,
        "refinement_level": refinement_level,
    }
    if any(failure.get(name) != expected for name, expected in identity.items()):
        raise ValueError("failed-preflight request/job identity is invalid")
    request_sha256 = failure.get("request_sha256")
    if (
        not isinstance(request_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", request_sha256) is None
    ):
        raise ValueError("failed-preflight request digest is invalid")
    request_binding = failure.get("request_binding")
    if (
        not isinstance(request_binding, Mapping)
        or _sha256(request_binding) != request_sha256
    ):
        raise ValueError(
            "failed-preflight request digest disagrees with canonical binding"
        )
    expected_request_identity = {
        "schema_version": 1,
        "operation": "root-readout",
        "job_id": leaf.job.job_id,
        "leaf_id": leaf.leaf_id,
        "role": leaf.role,
        "job_policy_sha256": leaf.job.policy.identity_sha256,
        "backend_identity_sha256": leaf.job.backend_identity.identity_sha256,
        "refinement_level": refinement_level,
        "mode": {
            "s": leaf.job.mode.s,
            "ell": leaf.job.mode.ell,
            "m": leaf.job.mode.m,
            "n": leaf.job.mode.n,
        },
        "spin": format(leaf.job.spin, ".17g"),
        "omega": {
            "real": format(leaf.job.root.omega.real, ".17g"),
            "imaginary": format(leaf.job.root.omega.imag, ".17g"),
        },
        "angular_A": {
            "real": format(
                leaf.job.root.angular_separation_constant.real, ".17g"
            ),
            "imaginary": format(
                leaf.job.root.angular_separation_constant.imag, ".17g"
            ),
        },
        "mechanism_id": leaf.job.mechanism_id,
        "precision_digits": precision_digits,
        "working_precision_bits": (
            math.ceil(precision_digits * math.log2(10)) + 32
        ),
    }
    if any(
        request_binding.get(name) != expected
        for name, expected in expected_request_identity.items()
    ):
        raise ValueError("failed-preflight canonical request identity is invalid")
    amplitude = request_binding.get("amplitude")
    if not isinstance(amplitude, Mapping) or set(amplitude) != {
        "real", "imaginary"
    }:
        raise ValueError("failed-preflight request amplitude is invalid")
    try:
        amplitude_parts = tuple(Decimal(amplitude[name]) for name in (
            "real", "imaginary"
        ))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError("failed-preflight request amplitude is invalid") from error
    if not all(part.is_finite() for part in amplitude_parts):
        raise ValueError("failed-preflight request amplitude is invalid")
    amplitude_value = complex(*(float(part) for part in amplitude_parts))
    allowed_amplitudes = {0.0j}
    for epsilon in leaf.job.policy.epsilons:
        allowed_amplitudes.update({
            complex(epsilon, 0.0),
            complex(-epsilon, 0.0),
            complex(0.0, epsilon),
            complex(0.0, -epsilon),
        })
    if amplitude_value not in allowed_amplitudes:
        raise ValueError("failed-preflight request amplitude is off schedule")
    raw_predictor = request_binding.get("primary_predictor")
    predictor_kind = request_binding.get("primary_predictor_kind")
    predictor_value: complex | None = None
    if raw_predictor is not None:
        if (
            not isinstance(raw_predictor, Mapping)
            or set(raw_predictor) != {"real", "imaginary"}
            or predictor_kind not in {
                "EPSILON_CONTINUATION", "SPIN_CONTINUATION"
            }
        ):
            raise ValueError("failed-preflight request predictor is invalid")
        try:
            predictor_value = complex(
                float(Decimal(raw_predictor["real"])),
                float(Decimal(raw_predictor["imaginary"])),
            )
        except (InvalidOperation, TypeError, ValueError) as error:
            raise ValueError(
                "failed-preflight request predictor is invalid"
            ) from error
        if not (
            math.isfinite(predictor_value.real)
            and math.isfinite(predictor_value.imag)
        ):
            raise ValueError("failed-preflight request predictor is invalid")
    elif predictor_kind is not None:
        raise ValueError("failed-preflight request predictor is invalid")
    resource = request_binding.get("execution_resource")
    failure_resource = failure.get("execution_resource_policy")
    try:
        validated_resource = _validated_execution_resource_policy(resource)
    except JuliaResponseBackendError as error:
        raise ValueError(
            "failed-preflight request resource binding is invalid"
        ) from error
    resource_identity = {
        "schema": validated_resource["schema"],
        "version": validated_resource["version"],
        "sha256": validated_resource["sha256"],
    }
    if not isinstance(failure_resource, Mapping) or dict(failure_resource) not in (
        resource_identity,
        validated_resource,
    ):
        raise ValueError("failed-preflight request resource binding is invalid")
    expected_request = JuliaPrecisionRootBackend(
        leaf.job.backend_identity,
        object(),
        precision_digits,
        refinement=refinement_level,
    )._request(
        leaf.job,
        amplitude_value,
        predictor_value,
        predictor_kind,
    )
    expected_request["execution_resource"] = validated_resource
    if dict(request_binding) != expected_request:
        raise ValueError("failed-preflight canonical request contract is invalid")
    if failure.get("precision_digits") != precision_digits:
        raise ValueError("failed-preflight request precision is invalid")
    if attempt.failure_code == "INSUFFICIENT_ASYMPTOTIC_PRECISION":
        diagnostics = failure.get("diagnostics")
        if (
            failure.get("retryable") is not True
            or not isinstance(diagnostics, Mapping)
            or diagnostics.get("asymptotic_preflight_avoided_ode") is not True
            or diagnostics.get("asymptotic_preflight_reason")
            != "INSUFFICIENT_ASYMPTOTIC_PRECISION"
            or diagnostics.get("factored_homogeneous_rhs_evaluations") != 0
            or diagnostics.get("avoided_ode_scope")
            != _FACTORED_HOMOGENEOUS_ODE_SCOPE_ID
        ):
            raise ValueError("failed-preflight zero-work evidence is invalid")
    decision = failure.get("promotion_decision")
    expected_decision = _numerical_failure_promotion_decision(
        failure, precision_digits
    )
    if expected_decision is None:
        if decision is not None:
            raise ValueError("failed-preflight promotion decision is unexpected")
    elif _validated_promotion_decision(decision) != expected_decision:
        raise ValueError("failed-preflight promotion decision is invalid")


def _validate_failed_preflight_predecessor(
    attempt: CampaignExecutionAttempt,
    leaf: CampaignLeafPlan,
) -> None:
    """Authenticate the sole 80-digit control predecessor for recovery."""

    _validate_failed_preflight_attempt_request(
        attempt,
        leaf,
        precision_digits=80,
        allowed_refinement_levels=frozenset({0}),
        required_failure_code="INSUFFICIENT_ASYMPTOTIC_PRECISION",
    )


def _validate_failed_preflight_recovery_failure(
    attempt: CampaignExecutionAttempt,
    leaf: CampaignLeafPlan,
) -> None:
    """Authenticate a contained failure from either 120-digit recovery pass."""

    _validate_failed_preflight_attempt_request(
        attempt,
        leaf,
        precision_digits=120,
        allowed_refinement_levels=frozenset({0, 1}),
        required_failure_code=None,
    )


def _failed_preflight_predecessor_for_leaf(
    attempts: Sequence[CampaignExecutionAttempt],
    leaf: CampaignLeafPlan,
) -> CampaignExecutionAttempt | None:
    candidates = tuple(
        attempt
        for attempt in attempts
        if (
            attempt.leaf_id == leaf.leaf_id
            and attempt.precision_digits == 80
            and attempt.failure_code
            == "INSUFFICIENT_ASYMPTOTIC_PRECISION"
        )
    )
    if len(candidates) > 1:
        raise ValueError("campaign has duplicate failed-preflight predecessors")
    if not candidates:
        return None
    _validate_failed_preflight_predecessor(candidates[0], leaf)
    return candidates[0]


def _failed_preflight_recovery_failure_for_leaf(
    attempts: Sequence[CampaignExecutionAttempt],
    leaf: CampaignLeafPlan,
) -> CampaignExecutionAttempt | None:
    """Return a durable failed 120-digit recovery, if one was recorded."""

    predecessor = _failed_preflight_predecessor_for_leaf(attempts, leaf)
    if predecessor is None:
        return None
    candidates = tuple(
        attempt
        for attempt in attempts
        if attempt.leaf_id == leaf.leaf_id and attempt.precision_digits == 120
    )
    if len(candidates) > 1:
        raise ValueError("campaign has duplicate failed-preflight recovery failures")
    if not candidates:
        return None
    if candidates[0].attempt_ordinal <= predecessor.attempt_ordinal:
        raise ValueError("failed-preflight recovery failure order is invalid")
    _validate_failed_preflight_recovery_failure(candidates[0], leaf)
    return candidates[0]


def _embedded_failed_preflight_predecessor(
    record: CampaignLeafRecord,
    leaf: CampaignLeafPlan,
) -> CampaignExecutionAttempt | None:
    """Recover the self-contained control predecessor from a cached stage."""

    if tuple(stage.outcome.digits for stage in record.stages) != (64, 120):
        return None
    raw = record.stages[-1].outcome.component_result.get(
        "failed_preflight_predecessor"
    )
    predecessor = CampaignExecutionAttempt.from_mapping(raw)
    _validate_failed_preflight_predecessor(predecessor, leaf)
    return predecessor


def _record_with_materialized_failed_preflight_predecessor(
    record: CampaignLeafRecord,
    predecessor: CampaignExecutionAttempt,
) -> CampaignLeafRecord:
    """Replace a cached predecessor mapping after local ledger renumbering."""

    stage = record.stages[-1]
    component = dict(stage.outcome.component_result)
    if component["failed_preflight_predecessor"] == predecessor.to_mapping():
        return record
    component["failed_preflight_predecessor"] = predecessor.to_mapping()
    source_sha256 = _sha256(component)
    channels: list[Mapping[str, object]] = []
    for raw_channel in stage.outcome.signed_error_channels:
        channel = dict(raw_channel)
        provenance = dict(channel["provenance"])
        provenance["source_sha256"] = source_sha256
        channel["provenance"] = provenance
        channels.append(channel)
    materialized_stage = CampaignStageRecord(
        replace(
            stage.outcome,
            component_result=component,
            signed_error_channels=tuple(channels),
        ),
        stage.runner_provenance,
    )
    return replace(record, stages=(*record.stages[:-1], materialized_stage))


@dataclass(frozen=True, slots=True)
class CampaignRunSummary:
    campaign_id: str
    selection_id: str
    state: str
    executed_stage_count: int
    reused_stage_count: int
    records: tuple[CampaignLeafRecord, ...]
    checkpoint_path: str
    attempts: tuple[CampaignExecutionAttempt, ...] = ()

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
            "attempts": [attempt.to_mapping() for attempt in self.attempts],
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
            for mechanism in dict.fromkeys(
                leaf.mechanism_id for leaf in self.leaves
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


def _previous_primary_recovery_precision_contract() -> dict[str, object]:
    """Return the exact PRIMARY recovery contract immediately before PR 33."""

    return {
        "binary64_trigger": {
            "component_status": ComponentStatus.NOT_CONVERGED.value,
            "requires_canonical_production_evidence": True,
        },
        "recovery_digits": [80, 120],
        "precision120_gates": {
            "component_status": ComponentStatus.NOT_CONVERGED.value,
            "self_refinement_enclosed": False,
            "discrepancy_enclosed": False,
        },
        "precision120_terminal_success": {
            "component_status": ComponentStatus.CONVERGED.value,
            "discrepancy_enclosed": True,
        },
    }


def _failed_preflight_recovery_precision_contract() -> dict[str, object]:
    """Bind the only admissible 80-preflight-to-120 alternate terminal gate."""

    return {
        "schema": "windows-solver.failed-preflight-recovery/1",
        "control_predecessor": {
            "precision_digits": 80,
            "failure_code": "INSUFFICIENT_ASYMPTOTIC_PRECISION",
            "failure_class": "CONTROL",
            "retryable": True,
            "request_binding_required": True,
            "asymptotic_preflight_avoided_ode": True,
            "factored_homogeneous_rhs_evaluations": 0,
            "avoided_ode_scope": _FACTORED_HOMOGENEOUS_ODE_SCOPE_ID,
        },
        "terminal_precision_sequence": [64, 120],
        "comparison_kind": _FAILED_PREFLIGHT_COMPARISON_KIND,
        "precision_ladder_discrepancy_applicable": False,
        "precision120_evidence": {
            "base_refinement_levels": [0, 1],
            "component_status": ComponentStatus.CONVERGED.value,
            "conditioning_precision_limited": False,
            "conditioning_required_digits_met": True,
            "same_precision_delta_enclosed": True,
        },
        "terminal_state": {
            "non_sentinel_when_all_gates_pass": "PRODUCED",
            "otherwise": "UNRESOLVED",
            "fixed_precision_sentinel": "UNRESOLVED",
        },
    }


def _primary_recovery_precision_contract() -> dict[str, object]:
    """Return the canonical PRIMARY promoted-precision policy fragment."""

    from .julia_response_backend import promoted_precision_numerical_controls

    return {
        **_previous_primary_recovery_precision_contract(),
        "promoted_numerical_controls": promoted_precision_numerical_controls(),
        "failed_preflight_alternate": (
            _failed_preflight_recovery_precision_contract()
        ),
    }


def _raw_residual_promoted_precision_numerical_controls() -> dict[str, object]:
    """Return the exact promoted controls immediately before this change."""

    return {
        "80": {
            "base": {
                "root_tolerance": "1e-18",
                "ode_relative_tolerance": "1e-18",
                "ode_absolute_tolerance": "1e-20",
                "frequency_step": "1e-6",
            },
            "refinement": {
                "root_tolerance": "1e-20",
                "ode_relative_tolerance": "1e-20",
                "ode_absolute_tolerance": "1e-20",
                "frequency_step": "1e-7",
            },
        },
        "120": {
            "base": {
                "root_tolerance": "1e-102",
                "ode_relative_tolerance": "1e-102",
                "ode_absolute_tolerance": "1e-104",
                "frequency_step": "1e-60",
            },
            "refinement": {
                "root_tolerance": "1e-106",
                "ode_relative_tolerance": "1e-106",
                "ode_absolute_tolerance": "1e-108",
                "frequency_step": "1e-60",
            },
        },
    }


def _raw_residual_primary_recovery_precision_contract() -> dict[str, object]:
    """Return the exact PRIMARY recovery contract on immediate main."""

    return {
        **_previous_primary_recovery_precision_contract(),
        "promoted_numerical_controls": (
            _raw_residual_promoted_precision_numerical_controls()
        ),
    }


def _root_convergence_precision_contract() -> dict[str, object]:
    """Bind the local estimator and its independent acceptance safeguards."""

    return {
        "version": 1,
        "metric": "newton_correction_estimate_abs",
        "definition": "determinant_residual_abs_over_derivative_abs",
        "binary64_tolerance_abs": _BINARY64_ROOT_CORRECTION_TOLERANCE_ABS,
        "derivative_requirement": "finite_strictly_positive",
        "required_phases": [
            "PRIMARY",
            "TRUNCATION",
            "RESOLUTION",
            "SEED-PATH",
        ],
        "branch_continuation_required": True,
        "evidence_ceiling": "local_estimate_not_root_enclosure",
    }


def _response_uncertainty_contract() -> dict[str, object]:
    """Bind the live diagnostic-root reduction used by every precision tier."""

    return {
        "version": 2,
        "primary_disk": "combined_signed_secant_two_finest_level_richardson",
        "diagnostic_phases": ["TRUNCATION", "RESOLUTION", "SEED-PATH"],
        "diagnostic_disk": "signed_phase_secants_two_finest_level_richardson",
        "containment_increment": (
            "max_axis_of_max_zero_control_distance_plus_control_radius_"
            "minus_primary_combined_radius"
        ),
        "baseline_diagnostic_displacement_excluded": True,
        "root_space_displacements": "branch_continuation_only",
        "units": "dimensionless_response",
    }


def _legacy_leaf_precision_contract(leaf: CampaignLeafPlan) -> dict[str, object]:
    """Return the base precision contract predating PRIMARY recovery."""

    return {
        "binary64_stage_required": True,
        "deep_leaf": leaf.role == "deep",
        "promotion_digits": [80, 120] if leaf.role == "deep" else [],
        "promotion_gates": list(B_PRIME_RELEASE_DOMAIN.precision_promotion_gates),
        "fixed_precision_sentinel": leaf.leaf_id in set(
            B_PRIME_RELEASE_DOMAIN.fixed_precision_sentinel_leaf_ids
        ),
    }


def _leaf_precision_contract(leaf: CampaignLeafPlan) -> dict[str, object]:
    contract = _legacy_leaf_precision_contract(leaf)
    if leaf.role == "primary":
        contract["primary_recovery"] = _primary_recovery_precision_contract()
    elif leaf.role == "deep":
        contract["failed_preflight_recovery"] = (
            _failed_preflight_recovery_precision_contract()
        )
    contract["root_convergence"] = _root_convergence_precision_contract()
    return contract


def _raw_residual_leaf_precision_contract(
    leaf: CampaignLeafPlan,
) -> dict[str, object]:
    """Return the exact leaf contract on immediate main."""

    contract = _legacy_leaf_precision_contract(leaf)
    if leaf.role == "primary":
        contract["primary_recovery"] = (
            _raw_residual_primary_recovery_precision_contract()
        )
    return contract


def _scientific_computation_identity_material(
    plan: CampaignPlan,
    leaf: CampaignLeafPlan,
    precision_contract: Mapping[str, object],
) -> dict[str, object]:
    return {
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
        "precision_contract": precision_contract,
        "response_uncertainty_contract": _response_uncertainty_contract(),
    }


def scientific_computation_identity_sha256(
    plan: CampaignPlan, leaf: CampaignLeafPlan
) -> str:
    """Bind one requested calculation without binding campaign presentation code."""

    if leaf.leaf_id not in {item.leaf_id for item in plan.leaves}:
        raise ValueError("solved-leaf scientific identity is outside the campaign plan")
    material = _scientific_computation_identity_material(
        plan, leaf, _leaf_precision_contract(leaf)
    )
    return _sha256(material)


def _legacy_primary_scientific_computation_identity_sha256(
    plan: CampaignPlan, leaf: CampaignLeafPlan
) -> str:
    """Derive the exact binary64-only PRIMARY predecessor identity."""

    if leaf.role != "primary":
        raise ValueError("legacy PRIMARY identity requires a PRIMARY leaf")
    if leaf.leaf_id not in {item.leaf_id for item in plan.leaves}:
        raise ValueError("legacy PRIMARY identity is outside the campaign plan")
    return _sha256(_scientific_computation_identity_material(
        plan, leaf, _legacy_leaf_precision_contract(leaf)
    ))


def _raw_residual_primary_scientific_computation_identity_sha256(
    plan: CampaignPlan, leaf: CampaignLeafPlan
) -> str:
    """Derive the exact PRIMARY identity from immediate main."""

    if leaf.role != "primary":
        raise ValueError("raw-residual identity requires a PRIMARY leaf")
    if leaf.leaf_id not in {item.leaf_id for item in plan.leaves}:
        raise ValueError("raw-residual identity is outside the campaign plan")
    return _sha256(_scientific_computation_identity_material(
        plan, leaf, _raw_residual_leaf_precision_contract(leaf)
    ))


def _previous_primary_scientific_computation_identity_sha256(
    plan: CampaignPlan, leaf: CampaignLeafPlan
) -> str:
    """Derive the exact PRIMARY identity immediately before PR 33."""

    if leaf.role != "primary":
        raise ValueError("previous PRIMARY identity requires a PRIMARY leaf")
    if leaf.leaf_id not in {item.leaf_id for item in plan.leaves}:
        raise ValueError("previous PRIMARY identity is outside the campaign plan")
    contract = _legacy_leaf_precision_contract(leaf)
    contract["primary_recovery"] = (
        _previous_primary_recovery_precision_contract()
    )
    return _sha256(
        _scientific_computation_identity_material(plan, leaf, contract)
    )


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


def _campaign_execution_leaf_ids(
    plan: CampaignPlan, selection: CampaignSelection
) -> tuple[str, ...]:
    """Order selected work without changing its authenticated selection order."""

    selected = set(selection.leaf_ids)
    canonical_index = {
        leaf.leaf_id: index for index, leaf in enumerate(plan.leaves)
    }

    def execution_key(leaf: CampaignLeafPlan) -> tuple[object, ...]:
        try:
            role_rank = _EXECUTION_ROLE_ORDER[leaf.role]
            mechanism_rank = _EXECUTION_MECHANISM_ORDER[leaf.mechanism_id]
            mode_rank = _EXECUTION_MODE_ORDER[leaf.role][leaf.leaf.mode_label]
        except KeyError as error:
            raise ValueError(
                "campaign execution order lacks a declared role, mechanism, or mode"
            ) from error
        return (
            role_rank,
            mechanism_rank,
            mode_rank,
            leaf.leaf.spin,
            canonical_index[leaf.leaf_id],
        )

    ordered = tuple(
        leaf.leaf_id
        for leaf in sorted(
            (leaf for leaf in plan.leaves if leaf.leaf_id in selected),
            key=execution_key,
        )
    )
    if len(ordered) != len(selection.leaf_ids) or set(ordered) != selected:
        raise ValueError("campaign execution traversal is off-selection")
    return ordered


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
        "precision_contract_sha256": _checkpoint_precision_contract_sha256(
            CAMPAIGN_CHECKPOINT_SCHEMA_VERSION
        ),
    }


def _checkpoint_precision_contract_sha256(schema_version: int) -> str:
    material: dict[str, object] = {
        "promotion_gates": list(B_PRIME_RELEASE_DOMAIN.precision_promotion_gates),
        "fixed_sentinel_leaf_ids": list(
            B_PRIME_RELEASE_DOMAIN.fixed_precision_sentinel_leaf_ids
        ),
    }
    if schema_version in {3, 4, 5}:
        historical_primary = dict(_primary_recovery_precision_contract())
        historical_primary.pop("failed_preflight_alternate")
        material.update(
            {
                "primary_recovery": historical_primary,
                "response_uncertainty": _response_uncertainty_contract(),
            }
        )
    elif schema_version == CAMPAIGN_CHECKPOINT_SCHEMA_VERSION:
        material.update(
            {
                "primary_recovery": _primary_recovery_precision_contract(),
                "failed_preflight_recovery": (
                    _failed_preflight_recovery_precision_contract()
                ),
                "response_uncertainty": _response_uncertainty_contract(),
            }
        )
    elif schema_version != _LEGACY_CAMPAIGN_CHECKPOINT_SCHEMA_VERSION:
        raise ValueError("campaign checkpoint precision contract schema is invalid")
    return _sha256(material)


def _historical_checkpoint_precision_contract_sha256s(
    schema_version: int,
) -> frozenset[str]:
    hashes = {_checkpoint_precision_contract_sha256(schema_version)}
    if schema_version == _LEGACY_CAMPAIGN_CHECKPOINT_SCHEMA_VERSION:
        hashes.add(_sha256({
            "promotion_gates": list(
                B_PRIME_RELEASE_DOMAIN.precision_promotion_gates
            ),
            "fixed_sentinel_leaf_ids": list(
                B_PRIME_RELEASE_DOMAIN.fixed_precision_sentinel_leaf_ids
            ),
        }))
    return frozenset(hashes)


def _checkpoint_bindings_match_schema(
    plan: CampaignPlan,
    selection: CampaignSelection,
    bindings: object,
    schema_version: int,
) -> bool:
    if not isinstance(bindings, Mapping):
        return False
    current = _checkpoint_bindings(plan, selection)
    if dict(bindings) == current:
        return True
    if schema_version not in _HISTORICAL_CAMPAIGN_CHECKPOINT_SCHEMA_VERSIONS:
        return False
    for precision_contract_sha256 in (
        _historical_checkpoint_precision_contract_sha256s(schema_version)
    ):
        historical = dict(current)
        historical["precision_contract_sha256"] = precision_contract_sha256
        if dict(bindings) == historical:
            return True
    return False


def _checkpoint_mapping(
    plan: CampaignPlan,
    selection: CampaignSelection,
    records: Sequence[CampaignLeafRecord],
    attempts: Sequence[CampaignExecutionAttempt] = (),
) -> dict[str, object]:
    values = [record.to_mapping() for record in records]
    attempt_values = [attempt.to_mapping() for attempt in attempts]
    complete = (
        len(records) == len(selection.leaf_ids)
        and all(record.state in {"PRODUCED", "UNRESOLVED"} for record in records)
    )
    return {
        "schema_version": CAMPAIGN_CHECKPOINT_SCHEMA_VERSION,
        "state": "COMPLETE" if complete else "PARTIAL",
        "bindings": _checkpoint_bindings(plan, selection),
        "records": values,
        "records_sha256": _sha256(values),
        "attempts": attempt_values,
        "attempts_sha256": _sha256(attempt_values),
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
) -> tuple[
    Mapping[str, object],
    Mapping[str, object],
    tuple[CampaignLeafRecord, ...],
    tuple[CampaignExecutionAttempt, ...],
]:
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
    if not isinstance(value, Mapping):
        raise ValueError("campaign checkpoint envelope fields are invalid")
    common_fields = {
        "schema_version",
        "state",
        "bindings",
        "records",
        "records_sha256",
        "release_admissible",
    }
    version = value.get("schema_version")
    expected_fields = (
        common_fields
        if version == _LEGACY_CAMPAIGN_CHECKPOINT_SCHEMA_VERSION
        else common_fields | {"attempts", "attempts_sha256"}
    )
    if set(value) != expected_fields:
        raise ValueError("campaign checkpoint envelope fields are invalid")
    if value["schema_version"] == 2:
        raise ValueError(
            "campaign checkpoint uses the legacy branch-authentication contract; "
            "preserve it as evidence and start with a fresh checkpoint path"
        )
    if version not in (
        _HISTORICAL_CAMPAIGN_CHECKPOINT_SCHEMA_VERSIONS
        | {CAMPAIGN_CHECKPOINT_SCHEMA_VERSION}
    ):
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
    if version == _LEGACY_CAMPAIGN_CHECKPOINT_SCHEMA_VERSION:
        attempts: tuple[CampaignExecutionAttempt, ...] = ()
    else:
        raw_attempts = value["attempts"]
        if (
            not isinstance(raw_attempts, list)
            or value["attempts_sha256"] != _sha256(raw_attempts)
        ):
            raise ValueError("campaign checkpoint attempts digest is invalid")
        attempts = tuple(
            CampaignExecutionAttempt.from_mapping(item) for item in raw_attempts
        )
    return value, bindings, records, attempts


def _load_checkpoint_with_attempts(
    plan: CampaignPlan, path: Path
) -> tuple[
    CampaignSelection,
    tuple[CampaignLeafRecord, ...],
    tuple[CampaignExecutionAttempt, ...],
    str,
    int,
]:
    value, bindings, records, attempts = _read_checkpoint_envelope(path)
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
    if not _checkpoint_bindings_match_schema(
        plan, selection, bindings, value["schema_version"]
    ):
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
    for record in records:
        leaf = leaf_by_id[record.leaf_id]
        if record.role != leaf.role:
            raise ValueError("campaign checkpoint record order or role is invalid")
        if not record.stages or record.stages[0].outcome.digits != 64:
            raise ValueError("campaign checkpoint precision stages are invalid")
        digits = tuple(stage.outcome.digits for stage in record.stages)
        if digits not in {(64,), (64, 80), (64, 120), (64, 80, 120)}:
            raise ValueError("campaign checkpoint precision stage order is invalid")
        _validate_record_semantics(
            leaf,
            record,
            plan.precision_factory_identity,
            checkpoint_schema_version=value["schema_version"],
        )
    if tuple(attempt.attempt_ordinal for attempt in attempts) != tuple(
        range(1, len(attempts) + 1)
    ):
        raise ValueError("campaign execution attempt order is invalid")
    selection_index = {
        leaf_id: index
        for index, leaf_id in enumerate(
            _campaign_execution_leaf_ids(plan, selection), start=1
        )
    }
    for attempt in attempts:
        if attempt.leaf_id not in selection_index:
            raise ValueError("campaign execution attempt is off-selection")
        leaf = leaf_by_id[attempt.leaf_id]
        if (
            attempt.leaf_index != selection_index[attempt.leaf_id]
            or attempt.role != leaf.role
        ):
            raise ValueError("campaign execution attempt leaf identity is invalid")
        record = next(
            (item for item in records if item.leaf_id == attempt.leaf_id), None
        )
        if record is None or not record.stages:
            raise ValueError("campaign execution attempt lacks prior stage evidence")
    for record in records:
        digits = tuple(stage.outcome.digits for stage in record.stages)
        leaf = leaf_by_id[record.leaf_id]
        predecessor = _failed_preflight_predecessor_for_leaf(
            attempts, leaf
        )
        pending_recovery = (
            digits == (64,)
            and record.state in {"IN_PROGRESS", "MISSING_PRECISION"}
            and (
                record.missing_precision_digits is None
                or record.missing_precision_digits == 120
            )
        )
        recovery_failure = _failed_preflight_recovery_failure_for_leaf(
            attempts, leaf
        )
        if predecessor is not None and not (
            pending_recovery or digits == (64, 120)
        ):
            raise ValueError(
                "failed-preflight predecessor has incompatible stage evidence"
            )
        if (
            record.missing_precision_digits == 120
            and digits == (64,)
            and predecessor is None
        ):
            raise ValueError(
                "missing 120-digit recovery lacks a failed-preflight predecessor"
            )
        if recovery_failure is not None and not pending_recovery:
            raise ValueError(
                "failed-preflight recovery failure has incompatible stage evidence"
            )
        if digits != (64, 120):
            continue
        embedded = record.stages[-1].outcome.component_result.get(
            "failed_preflight_predecessor"
        )
        if predecessor is None or predecessor.to_mapping() != embedded:
            raise ValueError(
                "failed-preflight recovery predecessor does not match checkpoint"
            )
    expected_state = (
        "COMPLETE"
        if len(records) == len(selection.leaf_ids)
        and all(record.state in {"PRODUCED", "UNRESOLVED"} for record in records)
        else "PARTIAL"
    )
    if value["state"] != expected_state or value["release_admissible"] is not False:
        raise ValueError("campaign checkpoint state is invalid")
    return (
        selection,
        records,
        attempts,
        expected_state,
        value["schema_version"],
    )


def _load_checkpoint(
    plan: CampaignPlan, path: Path
) -> tuple[CampaignSelection, tuple[CampaignLeafRecord, ...], str]:
    """Backward-compatible checkpoint loader omitting the operational ledger."""

    selection, records, _attempts, state, _version = (
        _load_checkpoint_with_attempts(plan, path)
    )
    return selection, records, state


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


def _primary_recovery_digits() -> tuple[int, int]:
    digits = _primary_recovery_precision_contract()["recovery_digits"]
    if not isinstance(digits, list) or len(digits) != 2:
        raise ValueError("PRIMARY recovery precision contract is invalid")
    return int(digits[0]), int(digits[1])


def _primary_binary64_promotes(
    outcome: StageOutcome, *, production: bool
) -> bool:
    trigger = _primary_recovery_precision_contract()["binary64_trigger"]
    if not isinstance(trigger, Mapping):
        raise ValueError("PRIMARY recovery trigger contract is invalid")
    return (
        production
        and outcome.numerical_state == trigger["component_status"]
        and trigger["requires_canonical_production_evidence"] is True
    )


_PROMOTION_DECISION_SCHEMA = "windows-solver.precision-promotion-decision/1"
_PROMOTION_DECISION_FIELDS = frozenset({
    "schema",
    "from_precision_digits",
    "to_precision_digits",
    "state",
    "reason",
    "predicted_reliable_digits",
    "required_reliable_digits",
    "precision_limited",
    "asymptotic_preflight_avoided_ode",
})


def _promotion_conditioning(
    outcome: StageOutcome,
) -> NumericalConditioningEvidence | None:
    raw_result = outcome.component_result.get("result")
    if not isinstance(raw_result, Mapping):
        return None
    result = ComponentResult.from_mapping(raw_result)
    return result.baseline.numerical_conditioning


def _promotion_decision(
    outcome: StageOutcome,
    *,
    existing_requested: bool,
    requested_reason: str,
    suppressed_reason: str,
) -> dict[str, object]:
    evidence = _promotion_conditioning(outcome)
    requested = existing_requested
    reason = requested_reason if requested else suppressed_reason
    if outcome.numerical_state == ComponentStatus.NOT_CONVERGED.value:
        if evidence is None:
            reason = "LEGACY_CONDITIONING_EVIDENCE_ABSENT"
        else:
            requested = evidence.precision_limited
            reason = (
                "INSUFFICIENT_RELIABLE_DIGITS"
                if requested
                else "PREDICTED_RELIABLE_DIGITS_ADEQUATE"
            )
    return {
        "schema": _PROMOTION_DECISION_SCHEMA,
        "from_precision_digits": 80,
        "to_precision_digits": 120,
        "state": "REQUESTED" if requested else "SUPPRESSED",
        "reason": reason,
        "predicted_reliable_digits": (
            None if evidence is None else str(evidence.predicted_reliable_digits)
        ),
        "required_reliable_digits": (
            None if evidence is None else str(evidence.required_reliable_digits)
        ),
        "precision_limited": (
            None if evidence is None else evidence.precision_limited
        ),
        "asymptotic_preflight_avoided_ode": (
            None
            if evidence is None
            else evidence.asymptotic_preflight_avoided_ode
        ),
    }


def _validated_promotion_decision(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _PROMOTION_DECISION_FIELDS:
        raise ValueError("precision promotion decision fields are invalid")
    if (
        value["schema"] != _PROMOTION_DECISION_SCHEMA
        or type(value["from_precision_digits"]) is not int
        or value["from_precision_digits"] != 80
        or type(value["to_precision_digits"]) is not int
        or value["to_precision_digits"] != 120
        or value["state"] not in {"REQUESTED", "SUPPRESSED"}
        or not isinstance(value["reason"], str)
        or not value["reason"]
    ):
        raise ValueError("precision promotion decision contract is invalid")
    predicted = value["predicted_reliable_digits"]
    required = value["required_reliable_digits"]
    limited = value["precision_limited"]
    preflight = value["asymptotic_preflight_avoided_ode"]
    if predicted is None or required is None:
        if not (
            predicted is None
            and required is None
            and limited is None
            and preflight is None
        ):
            raise ValueError("precision promotion evidence is incomplete")
    else:
        if (
            not isinstance(predicted, str)
            or not predicted
            or predicted.strip() != predicted
            or not isinstance(required, str)
            or not required
            or required.strip() != required
            or type(limited) is not bool
            or type(preflight) is not bool
        ):
            raise ValueError("precision promotion evidence types are invalid")
        try:
            predicted_decimal = Decimal(predicted)
            required_decimal = Decimal(required)
        except InvalidOperation as error:
            raise ValueError("precision promotion evidence is not decimal") from error
        if (
            not predicted_decimal.is_finite()
            or not required_decimal.is_finite()
            or required_decimal < 0
            or limited != (predicted_decimal < required_decimal)
        ):
            raise ValueError("precision promotion evidence is inconsistent")
    output = dict(value)
    if output["reason"] == "INSUFFICIENT_RELIABLE_DIGITS" and (
        output["state"] != "REQUESTED" or limited is not True
    ):
        raise ValueError("insufficient-digit promotion decision is inconsistent")
    if output["reason"] == "PREDICTED_RELIABLE_DIGITS_ADEQUATE" and (
        output["state"] != "SUPPRESSED" or limited is not False
    ):
        raise ValueError("adequate-digit promotion decision is inconsistent")
    return output


def _stage_with_promotion_decision(
    outcome: StageOutcome, decision: Mapping[str, object]
) -> StageOutcome:
    if "promotion_decision" in outcome.component_result:
        raise ValueError("stage component result already has a promotion decision")
    validated = _validated_promotion_decision(decision)
    component_result = dict(outcome.component_result)
    component_result["promotion_decision"] = validated
    source_sha256 = _sha256(component_result)
    channels: list[Mapping[str, object]] = []
    for raw in outcome.signed_error_channels:
        copied = dict(raw)
        provenance = dict(copied["provenance"])
        provenance["source_sha256"] = source_sha256
        copied["provenance"] = provenance
        channels.append(copied)
    return replace(
        outcome,
        component_result=component_result,
        signed_error_channels=tuple(channels),
    )


def _validate_attached_promotion_decision(
    outcome: StageOutcome,
    expected: Mapping[str, object],
    *,
    required: bool,
) -> None:
    raw = outcome.component_result.get("promotion_decision")
    if raw is None:
        if required:
            raise ValueError(
                "precision promotion decision is required for checkpoint "
                f"schema {CAMPAIGN_CHECKPOINT_SCHEMA_VERSION}"
            )
        # Schema 3/4 checkpoints predate the mandatory attached decision.
        return
    if _validated_promotion_decision(raw) != dict(expected):
        raise ValueError("precision promotion decision disagrees with stage evidence")


def _primary_existing_requires_precision120(outcome: StageOutcome) -> bool:
    gates = _primary_recovery_precision_contract()["precision120_gates"]
    if not isinstance(gates, Mapping):
        raise ValueError("PRIMARY 120-digit gate contract is invalid")
    if outcome.numerical_state == gates["component_status"]:
        return True
    if outcome.numerical_state != ComponentStatus.CONVERGED.value:
        return False
    return (
        outcome.self_refinement_enclosed
        is gates["self_refinement_enclosed"]
        or outcome.discrepancy_enclosed is gates["discrepancy_enclosed"]
    )


def _primary_precision120_decision(outcome: StageOutcome) -> dict[str, object]:
    existing_requested = _primary_existing_requires_precision120(outcome)
    return _promotion_decision(
        outcome,
        existing_requested=existing_requested,
        requested_reason="CONVERGED_REFINEMENT_OR_DISCREPANCY_GATE",
        suppressed_reason="CONVERGED_PROMOTION_GATES_SATISFIED",
    )


def _deep_precision120_decision(
    outcome: StageOutcome, *, sentinel_false_negative: bool
) -> dict[str, object]:
    existing_requested = (
        sentinel_false_negative or not bool(outcome.self_refinement_enclosed)
    )
    decision = _promotion_decision(
        outcome,
        existing_requested=existing_requested,
        requested_reason=(
            "SENTINEL_TRIGGER_FALSE_NEGATIVE"
            if sentinel_false_negative
            else "CONVERGED_REFINEMENT_OR_DISCREPANCY_GATE"
        ),
        suppressed_reason="CONVERGED_PROMOTION_GATES_SATISFIED",
    )
    if sentinel_false_negative:
        # This is an independent release-policy audit of the binary64 trigger,
        # not a claim that extra digits will repair 80-digit nonconvergence.
        decision["state"] = "REQUESTED"
        decision["reason"] = "SENTINEL_TRIGGER_FALSE_NEGATIVE"
    return decision


def _primary_requires_precision120(outcome: StageOutcome) -> bool:
    return _primary_precision120_decision(outcome)["state"] == "REQUESTED"


def _primary_precision120_terminal_state(outcome: StageOutcome) -> str:
    success = _primary_recovery_precision_contract()[
        "precision120_terminal_success"
    ]
    if not isinstance(success, Mapping):
        raise ValueError("PRIMARY 120-digit terminal contract is invalid")
    produced = (
        outcome.numerical_state == success["component_status"]
        and outcome.discrepancy_enclosed is success["discrepancy_enclosed"]
    )
    return "PRODUCED" if produced else "UNRESOLVED"


class _NonProductionSolvedLeafRecord(ValueError):
    """A valid orchestration record that is ineligible for scientific reuse."""


class _UnauthenticatedComponentEvidence(ValueError):
    """Well-formed component evidence that fails scientific authentication."""


def _validate_current_promoted_runtime(
    leaf: CampaignLeafPlan,
    outcome: StageOutcome,
    result: ComponentResult,
    *,
    runtime_key: str = "scientific_runtime",
    expected_refinement_level: int = 0,
    allow_historical_conditioning_absence: bool = True,
) -> None:
    """Bind schema-2 promoted evidence to its exact job and precision policy."""

    payload = outcome.component_result
    runtime = payload.get(runtime_key)
    package_promoted = (
        payload.get("evidence_kind")
        == "package-owned-julia-promoted-component-engine"
    )
    conditioned = tuple(
        readout.numerical_conditioning is not None
        for readout in result.raw_readouts
    )
    has_conditioning = any(conditioned)
    if (
        outcome.digits in (80, 120)
        and not allow_historical_conditioning_absence
        and not package_promoted
    ):
        raise _UnauthenticatedComponentEvidence(
            "campaign current promoted evidence kind is invalid"
        )
    if not package_promoted and not has_conditioning:
        return
    if not package_promoted or (has_conditioning and not all(conditioned)):
        raise _UnauthenticatedComponentEvidence(
            "campaign promoted scientific runtime identity is invalid"
        )
    if (
        outcome.digits not in (80, 120)
        or not isinstance(runtime, Mapping)
    ):
        raise _UnauthenticatedComponentEvidence(
            "campaign promoted scientific runtime identity is invalid"
        )
    expected_bits = math.ceil(outcome.digits * math.log2(10)) + 32
    if (
        type(runtime.get("precision_digits")) is not int
        or runtime["precision_digits"] != outcome.digits
        or type(runtime.get("working_precision_bits")) is not int
        or runtime["working_precision_bits"] != expected_bits
        or type(runtime.get("refinement_level")) is not int
        or runtime["refinement_level"] != expected_refinement_level
    ):
        raise _UnauthenticatedComponentEvidence(
            "campaign promoted scientific runtime precision is invalid"
        )
    if not has_conditioning:
        if "regularised_gsn_precision_policy" in runtime:
            raise _UnauthenticatedComponentEvidence(
                "campaign promoted scientific runtime lacks current conditioning"
            )
        if not allow_historical_conditioning_absence:
            raise _UnauthenticatedComponentEvidence(
                "campaign promoted scientific runtime lacks current "
                "conditioning evidence"
            )
        # Main-branch promoted checkpoints with a complete Julia precision
        # identity predate conditioning schema 2 and its mechanism policy.
        return
    observed_policy = runtime.get("regularised_gsn_precision_policy")
    expected_policy = dict(
        regularised_gsn_precision_policy(leaf.job.mechanism_id)
    )
    if not isinstance(observed_policy, Mapping) or dict(observed_policy) != (
        expected_policy
    ):
        raise _UnauthenticatedComponentEvidence(
            "campaign promoted scientific runtime policy disagrees with mechanism"
        )


def _validate_component_result(
    leaf: CampaignLeafPlan,
    outcome: StageOutcome,
    *,
    result_key: str = "result",
    runtime_key: str = "scientific_runtime",
    expected_refinement_level: int = 0,
    expected_numerical_state: str | None = None,
    allow_historical_conditioning_absence: bool = True,
) -> bool:
    payload = outcome.component_result
    raw_result = payload.get(result_key)
    if raw_result is None:
        if result_key != "result":
            raise ValueError("campaign refinement component result is missing")
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
    if result.status is ComponentStatus.CONVERGED:
        body_is_valid = (
            result.usable
            and result.response is not None
            and result.signed_root_crosscheck is not None
            and result.convergence_basis in {
                "ORDER_RESOLVED",
                "TRUNCATION_BELOW_ROOT_RESOLUTION",
            }
        )
    else:
        body_is_valid = (
            not result.usable
            and result.response is None
            and result.signed_root_crosscheck is None
            and result.closed_form_response is None
            and result.convergence_basis == "UNRESOLVED"
        )
    if not body_is_valid:
        raise ValueError(
            "campaign production component result status/body contract is invalid"
        )
    job = leaf.job
    if (
        result.job_id != job.job_id
        or result.leaf_id != leaf.leaf_id
        or result.mechanism_id != leaf.mechanism_id
        or result.status.value
        != (
            outcome.numerical_state
            if expected_numerical_state is None
            else expected_numerical_state
        )
    ):
        raise _UnauthenticatedComponentEvidence(
            "campaign production component identity is invalid"
        )
    _validate_current_promoted_runtime(
        leaf,
        outcome,
        result,
        runtime_key=runtime_key,
        expected_refinement_level=expected_refinement_level,
        allow_historical_conditioning_absence=(
            allow_historical_conditioning_absence
        ),
    )
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
        raise _UnauthenticatedComponentEvidence(
            "campaign production component lineage is invalid"
        )
    if job.backend_identity.backend_id != RECORDED_REPLAY_BACKEND_ID:
        if result.status is ComponentStatus.CONVERGED and len(result.levels) < 4:
            raise _UnauthenticatedComponentEvidence(
                "campaign production diagnostic root evidence is incomplete"
            )
        if any(
            not readout.diagnostic_readouts
            for readout in result.raw_readouts[1:]
        ):
            raise _UnauthenticatedComponentEvidence(
                "campaign production diagnostic root evidence is incomplete"
            )
    branch_loss_mismatch = False
    for readout_index, readout in enumerate(result.raw_readouts):
        identity_mismatch = (
            readout.root_reference_id != job.root.root_reference_id
            or readout.branch_id != job.root.branch_id
            or readout.equation_id != job.equation_id
        )
        if identity_mismatch:
            if result.status is not ComponentStatus.BRANCH_LOSS:
                raise _UnauthenticatedComponentEvidence(
                    "campaign production readout lineage is invalid"
                )
            branch_loss_mismatch = True
            continue
        if not root_readout_preserves_authenticated_branch(
            readout,
            job.root,
            equation_id=job.equation_id,
            source_root_mapping=job.source_root_mapping,
        ):
            kind = "baseline" if readout_index == 0 else "perturbed"
            raise _UnauthenticatedComponentEvidence(
                f"campaign production {kind} root readout evidence is invalid"
            )
    if (
        result.status is ComponentStatus.BRANCH_LOSS
        and not branch_loss_mismatch
    ):
        raise ValueError(
            "campaign production BRANCH_LOSS lacks an identity mismatch"
        )
    return True


def _component_conditioning_is_adequate(result: ComponentResult) -> bool:
    evidence = tuple(
        readout.numerical_conditioning for readout in result.raw_readouts
    )
    return bool(evidence) and all(
        item is not None
        and item.precision_limited is False
        and item.predicted_reliable_digits >= item.required_reliable_digits
        for item in evidence
    )


def _validate_failed_preflight_refinement_runtime(
    leaf: CampaignLeafPlan,
    value: object,
) -> None:
    if not isinstance(value, Mapping):
        raise ValueError("failed-preflight refinement runtime is missing")
    if (
        type(value.get("precision_digits")) is not int
        or value["precision_digits"] != 120
        or type(value.get("working_precision_bits")) is not int
        or value["working_precision_bits"]
        != math.ceil(120 * math.log2(10)) + 32
        or type(value.get("refinement_level")) is not int
        or value["refinement_level"] != 1
        or value.get("regularised_gsn_precision_policy")
        != dict(regularised_gsn_precision_policy(leaf.job.mechanism_id))
    ):
        raise ValueError("failed-preflight refinement runtime identity is invalid")


def _validate_failed_preflight_recovery_stage(
    leaf: CampaignLeafPlan,
    outcome: StageOutcome,
) -> tuple[CampaignExecutionAttempt, bool]:
    """Validate a self-contained 120-base/120-refinement recovery stage."""

    if (
        outcome.digits != 120
        or outcome.deep_diagnostics is not None
        or type(outcome.self_refinement_enclosed) is not bool
        or outcome.discrepancy_from_previous_abs is not None
        or outcome.discrepancy_enclosed is not None
    ):
        raise ValueError("failed-preflight recovery stage fields are invalid")
    component = outcome.component_result
    expected_component_fields = {
        "evidence_kind",
        "result",
        "self_refinement_result",
        "scientific_runtime",
        "self_refinement_scientific_runtime",
        "failed_preflight_predecessor",
        "comparison_kind",
        "precision_ladder_discrepancy_applicable",
        "same_precision_refinement_discrepancy_abs",
    }
    if set(component) != expected_component_fields:
        raise ValueError("failed-preflight recovery component fields are invalid")
    if (
        component.get("comparison_kind") != _FAILED_PREFLIGHT_COMPARISON_KIND
        or component.get("precision_ladder_discrepancy_applicable") is not False
    ):
        raise ValueError("failed-preflight comparison identity is invalid")
    precision_channel = next(
        channel
        for channel in outcome.signed_error_channels
        if channel["family"] == "precision-ladder-discrepancy"
    )
    if (
        precision_channel["provenance"]["derivation"]
        != "not-applicable-precision-ladder-discrepancy"
        or precision_channel["signed_delta"] != {"real": 0.0, "imaginary": 0.0}
    ):
        raise ValueError(
            "failed-preflight precision-ladder channel must be not-applicable"
        )
    raw_predecessor = component.get("failed_preflight_predecessor")
    predecessor = CampaignExecutionAttempt.from_mapping(raw_predecessor)
    _validate_failed_preflight_predecessor(predecessor, leaf)

    raw_base = component.get("result")
    raw_refinement = component.get("self_refinement_result")
    if not isinstance(raw_base, Mapping) or not isinstance(
        raw_refinement, Mapping
    ):
        raise ValueError("failed-preflight recovery component results are missing")
    base = ComponentResult.from_mapping(raw_base)
    refinement = ComponentResult.from_mapping(raw_refinement)
    if base.to_mapping() != raw_base or refinement.to_mapping() != raw_refinement:
        raise ValueError("failed-preflight recovery component is not canonical")
    if (
        refinement.job_id != leaf.job.job_id
        or refinement.leaf_id != leaf.leaf_id
        or refinement.mechanism_id != leaf.mechanism_id
        or refinement.lineage != base.lineage
    ):
        raise ValueError("failed-preflight refinement component identity is invalid")
    if not _validate_component_result(
        leaf,
        outcome,
        result_key="self_refinement_result",
        runtime_key="self_refinement_scientific_runtime",
        expected_refinement_level=1,
        expected_numerical_state=refinement.status.value,
        allow_historical_conditioning_absence=False,
    ):
        raise ValueError(
            "failed-preflight refinement lacks canonical production evidence"
        )
    base_runtime = component.get("scientific_runtime")
    refinement_runtime = component.get("self_refinement_scientific_runtime")
    if not isinstance(base_runtime, Mapping) or not isinstance(
        refinement_runtime, Mapping
    ):
        raise ValueError("failed-preflight paired runtime identity is missing")
    expected_refinement_runtime = dict(base_runtime)
    expected_refinement_runtime["refinement_level"] = 1
    if dict(refinement_runtime) != expected_refinement_runtime:
        raise ValueError("failed-preflight paired runtime identity is invalid")
    _validate_failed_preflight_refinement_runtime(
        leaf, refinement_runtime
    )

    raw_delta = component.get("same_precision_refinement_discrepancy_abs")
    if isinstance(raw_delta, bool) or not isinstance(raw_delta, (int, float)):
        raise ValueError("failed-preflight same-precision discrepancy is invalid")
    recorded_delta = float(raw_delta)
    expected_delta = abs(_component_result_delta(refinement, base))
    if (
        not math.isfinite(recorded_delta)
        or recorded_delta < 0.0
        or recorded_delta != expected_delta
    ):
        raise ValueError("failed-preflight same-precision discrepancy disagrees")
    base_radius = sum(base.error_channels.values())
    refinement_radius = sum(refinement.error_channels.values())
    enclosed = (
        base.status is ComponentStatus.CONVERGED
        and refinement.status is ComponentStatus.CONVERGED
        and expected_delta <= base_radius + refinement_radius
    )
    if outcome.self_refinement_enclosed is not enclosed:
        raise ValueError("failed-preflight refinement enclosure is inconsistent")
    produced = (
        enclosed
        and _component_conditioning_is_adequate(base)
        and _component_conditioning_is_adequate(refinement)
    )
    return predecessor, produced


def _validate_primary_record_semantics(
    record: CampaignLeafRecord,
    stages: tuple[StageOutcome, ...],
    production_flags: tuple[bool, ...],
    *,
    promotion_decision_required: bool,
    failed_preflight_pending_allowed: bool,
) -> bool:
    first = stages[0]
    precision80_digits, precision120_digits = _primary_recovery_digits()
    if (
        first.deep_diagnostics is not None
        or record.trigger_ids
        or record.sentinel
        or record.sentinel_comparison is not None
    ):
        raise ValueError("campaign PRIMARY role fields are inconsistent")

    promoted = _primary_binary64_promotes(
        first, production=production_flags[0]
    )
    if not promoted:
        if (
            len(stages) != 1
            or record.state != _terminal_state(first)
            or record.missing_precision_digits is not None
        ):
            raise ValueError("campaign unpromoted PRIMARY state is inconsistent")
        return all(production_flags)

    if len(stages) == 1:
        pending = (
            record.state == "IN_PROGRESS"
            and record.missing_precision_digits is None
        ) or (
            record.state == "MISSING_PRECISION"
            and record.missing_precision_digits == precision80_digits
        ) or (
            failed_preflight_pending_allowed
            and record.state == "MISSING_PRECISION"
            and record.missing_precision_digits == precision120_digits
        )
        if not pending:
            raise ValueError(
                "campaign promoted PRIMARY leaf is missing its 80-digit stage"
            )
        return all(production_flags)

    precision80 = stages[1]
    if (
        precision80.deep_diagnostics is not None
        or precision80.self_refinement_enclosed is None
        or precision80.discrepancy_from_previous_abs is None
        or precision80.discrepancy_enclosed is None
    ):
        raise ValueError("campaign PRIMARY 80-digit evidence is incomplete")
    if not production_flags[1]:
        raise ValueError(
            "campaign promoted PRIMARY stage lacks canonical production evidence"
        )

    _validate_attached_promotion_decision(
        precision80,
        _primary_precision120_decision(precision80),
        required=promotion_decision_required,
    )
    requires120 = _primary_requires_precision120(precision80)
    if not requires120:
        expected_state = _terminal_state(
            precision80,
            enclosed=(
                bool(precision80.self_refinement_enclosed)
                and bool(precision80.discrepancy_enclosed)
            ),
        )
        if (
            len(stages) != 2
            or record.state != expected_state
            or record.missing_precision_digits is not None
        ):
            raise ValueError("campaign terminal PRIMARY 80-digit state is inconsistent")
        return all(production_flags)

    if len(stages) == 2:
        pending = (
            record.state == "IN_PROGRESS"
            and record.missing_precision_digits is None
        ) or (
            record.state == "MISSING_PRECISION"
            and record.missing_precision_digits == precision120_digits
        )
        if not pending:
            raise ValueError(
                "campaign promoted PRIMARY leaf is missing its 120-digit stage"
            )
        return all(production_flags)

    precision120 = stages[2]
    _validate_precision120(precision120)
    if not production_flags[2]:
        raise ValueError(
            "campaign promoted PRIMARY stage lacks canonical production evidence"
        )
    if (
        record.state != _primary_precision120_terminal_state(precision120)
        or record.missing_precision_digits is not None
    ):
        raise ValueError("campaign PRIMARY 120-digit terminal state is inconsistent")
    return all(production_flags)


def _validate_record_semantics(
    leaf: CampaignLeafPlan,
    record: CampaignLeafRecord,
    factory_identity: PrecisionFactoryIdentity,
    *,
    checkpoint_schema_version: int = CAMPAIGN_CHECKPOINT_SCHEMA_VERSION,
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
    allow_historical_conditioning_absence = (
        checkpoint_schema_version
        in _HISTORICAL_CAMPAIGN_CHECKPOINT_SCHEMA_VERSIONS
    )
    production_flags = tuple(
        _validate_component_result(
            leaf,
            stage,
            allow_historical_conditioning_absence=(
                allow_historical_conditioning_absence
            ),
        )
        for stage in stages
    )
    production = all(production_flags)
    first = stages[0]
    if (
        first.self_refinement_enclosed is not None
        or first.discrepancy_from_previous_abs is not None
        or first.discrepancy_enclosed is not None
    ):
        raise ValueError("campaign binary64 stage refinement fields are invalid")

    digits = tuple(stage.digits for stage in stages)
    if digits == (64, 120):
        if checkpoint_schema_version != CAMPAIGN_CHECKPOINT_SCHEMA_VERSION:
            raise ValueError(
                "historical checkpoints cannot claim failed-preflight recovery"
            )
        if leaf.role == "control":
            raise ValueError("control leaves cannot use failed-preflight recovery")
        _, recovery_produced = _validate_failed_preflight_recovery_stage(
            leaf, stages[1]
        )
        if not all(production_flags):
            raise ValueError(
                "failed-preflight recovery lacks canonical production evidence"
            )
        if leaf.role == "primary":
            role_fields_valid = (
                _primary_binary64_promotes(
                    first, production=production_flags[0]
                )
                and not record.trigger_ids
                and not record.sentinel
                and record.sentinel_comparison is None
            )
        else:
            trigger_ids = _deep_trigger_ids(first)
            sentinel = leaf.leaf_id in set(
                B_PRIME_RELEASE_DOMAIN.fixed_precision_sentinel_leaf_ids
            )
            role_fields_valid = (
                (bool(trigger_ids) or sentinel)
                and record.trigger_ids == trigger_ids
                and record.sentinel is sentinel
                and record.sentinel_comparison is None
            )
            if sentinel:
                recovery_produced = False
        expected_state = "PRODUCED" if recovery_produced else "UNRESOLVED"
        if (
            not role_fields_valid
            or record.state != expected_state
            or record.missing_precision_digits is not None
        ):
            raise ValueError("failed-preflight recovery terminal state is invalid")
        return True

    if leaf.role == "control":
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

    if leaf.role == "primary":
        return _validate_primary_record_semantics(
            record,
            stages,
            production_flags,
            promotion_decision_required=(
                checkpoint_schema_version >= CAMPAIGN_CHECKPOINT_SCHEMA_VERSION
            ),
            failed_preflight_pending_allowed=(
                checkpoint_schema_version == CAMPAIGN_CHECKPOINT_SCHEMA_VERSION
            ),
        )

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
        ) or (
            checkpoint_schema_version == CAMPAIGN_CHECKPOINT_SCHEMA_VERSION
            and record.state == "MISSING_PRECISION"
            and record.missing_precision_digits == 120
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
    decision = _deep_precision120_decision(
        precision80, sentinel_false_negative=false_negative
    )
    _validate_attached_promotion_decision(
        precision80,
        decision,
        required=(
            checkpoint_schema_version >= CAMPAIGN_CHECKPOINT_SCHEMA_VERSION
        ),
    )
    requires120 = decision["state"] == "REQUESTED"
    if false_negative and requires120:
        if (
            record.state != "INVALID_SENTINEL_FALSE_NEGATIVE"
            or record.missing_precision_digits != 120
        ):
            raise ValueError("campaign sentinel false-negative state is invalid")
        if len(stages) == 3:
            _validate_precision120(stages[2])
        return production
    if not requires120:
        if (
            len(stages) != 2
            or record.state
            != _terminal_state(
                precision80,
                enclosed=(
                    bool(precision80.self_refinement_enclosed)
                    and bool(precision80.discrepancy_enclosed)
                ),
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
    if digits not in {(64,), (64, 80), (64, 120), (64, 80, 120)}:
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
        raise _NonProductionSolvedLeafRecord(
            "solved-leaf record lacks canonical production evidence"
        )


def _authenticate_solved_leaf_hit(
    plan: CampaignPlan,
    leaf: CampaignLeafPlan,
    store: SolvedLeafStore,
    lookup: SolvedLeafLookup,
) -> SolvedLeafLookup:
    if lookup.status is not SolvedLeafLookupStatus.HIT:
        return lookup
    try:
        if lookup.receipt is None:
            raise ValueError("solved-leaf cache hit has no receipt")
        record = CampaignLeafRecord.from_mapping(lookup.receipt["record"])
        if record.to_mapping() != lookup.receipt["record"]:
            raise ValueError("solved-leaf cache record is not canonical")
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


def _validate_legacy_primary_record_evidence(
    plan: CampaignPlan,
    leaf: CampaignLeafPlan,
    record: CampaignLeafRecord,
) -> bool:
    if (
        record.leaf_id != leaf.leaf_id
        or record.role != "primary"
        or leaf.role != "primary"
        or len(record.stages) != 1
        or record.trigger_ids
        or record.sentinel
        or record.missing_precision_digits is not None
        or record.sentinel_comparison is not None
    ):
        raise ValueError("legacy PRIMARY solved-leaf role fields are inconsistent")
    stage = record.stages[0]
    outcome = stage.outcome
    if (
        outcome.digits != 64
        or outcome.deep_diagnostics is not None
        or outcome.self_refinement_enclosed is not None
        or outcome.discrepancy_from_previous_abs is not None
        or outcome.discrepancy_enclosed is not None
    ):
        raise ValueError("legacy PRIMARY solved-leaf stage fields are inconsistent")
    provenance = stage.runner_provenance
    if (
        provenance["precision_factory_identity"]
        != plan.precision_factory_identity.to_mapping()
        or not set(provenance["available_precision_digits"]).issubset(
            set(plan.precision_capabilities.digits)
        )
    ):
        raise ValueError("legacy PRIMARY solved-leaf factory evidence is invalid")
    if not _validate_component_result(
        leaf, outcome, allow_historical_conditioning_absence=True
    ):
        raise _NonProductionSolvedLeafRecord(
            "legacy PRIMARY solved-leaf lacks canonical production evidence"
        )
    if record.state != _terminal_state(outcome):
        raise ValueError("legacy PRIMARY solved-leaf terminal state is inconsistent")
    raw_result = outcome.component_result.get("result")
    if not isinstance(raw_result, Mapping):
        raise ValueError("legacy PRIMARY solved-leaf result is missing")
    result = ComponentResult.from_mapping(raw_result)
    correction_evidence_passes = all(
        readout.converged
        and readout.newton_correction_estimate
        <= _BINARY64_ROOT_CORRECTION_TOLERANCE_ABS
        for readout in result.raw_readouts
    )
    return (
        record.state == "PRODUCED"
        and outcome.numerical_state == ComponentStatus.CONVERGED.value
        and correction_evidence_passes
    )


def _authenticated_solved_leaf_lookup(
    plan: CampaignPlan,
    leaf: CampaignLeafPlan,
    store: SolvedLeafStore,
) -> SolvedLeafLookup:
    identity = scientific_computation_identity_sha256(plan, leaf)
    current = _authenticate_solved_leaf_hit(
        plan, leaf, store, store.lookup(identity, leaf.leaf_id)
    )
    if current.status in {
        SolvedLeafLookupStatus.HIT,
        SolvedLeafLookupStatus.CORRUPT,
    }:
        return current
    if leaf.role != "primary":
        return current

    predecessor_identities = (
        _raw_residual_primary_scientific_computation_identity_sha256(
            plan, leaf
        ),
        _previous_primary_scientific_computation_identity_sha256(plan, leaf),
        _legacy_primary_scientific_computation_identity_sha256(plan, leaf),
    )
    for predecessor_identity in predecessor_identities:
        predecessor = store.lookup(predecessor_identity, leaf.leaf_id)
        if predecessor.status is SolvedLeafLookupStatus.CORRUPT:
            return predecessor
        if predecessor.status is not SolvedLeafLookupStatus.HIT:
            continue

        try:
            if predecessor.receipt is None:
                raise ValueError("legacy solved-leaf cache hit has no receipt")
            record_mapping = predecessor.receipt["record"]
            record = CampaignLeafRecord.from_mapping(record_mapping)
            if record.to_mapping() != record_mapping:
                raise ValueError("legacy solved-leaf cache record is not canonical")
        except (KeyError, TypeError, ValueError) as error:
            if predecessor.path is not None:
                store.quarantine(predecessor.path, str(error))
            return SolvedLeafLookup(
                SolvedLeafLookupStatus.CORRUPT,
                path=predecessor.path,
                reason=str(error),
            )

        # A prior-policy promoted or otherwise multi-stage receipt is valid
        # stale evidence, but it cannot cross the changed numerical controls.
        if len(record.stages) != 1:
            continue

        try:
            success = _validate_legacy_primary_record_evidence(
                plan, leaf, record
            )
        except (KeyError, TypeError, ValueError) as error:
            if predecessor.path is not None:
                store.quarantine(predecessor.path, str(error))
            return SolvedLeafLookup(
                SolvedLeafLookupStatus.CORRUPT,
                path=predecessor.path,
                reason=str(error),
            )
        if not success:
            continue

        try:
            _validate_cacheable_leaf_record(plan, leaf, record)
        except (KeyError, TypeError, ValueError) as error:
            if predecessor.path is not None:
                store.quarantine(predecessor.path, str(error))
            return SolvedLeafLookup(
                SolvedLeafLookupStatus.CORRUPT,
                path=predecessor.path,
                reason=str(error),
            )

        source_type = predecessor.receipt["source_type"]
        if source_type not in {
            "originating-campaign",
            "imported-authenticated-checkpoint",
        }:
            raise ValueError("legacy solved-leaf cache source type is invalid")
        deadline = time.monotonic() + _LEGACY_MIGRATION_LOCK_TIMEOUT_SECONDS
        while True:
            try:
                published = store.publish_if_missing(
                    scientific_identity_sha256=identity,
                    leaf_id=leaf.leaf_id,
                    record=record.to_mapping(),
                    source_type=source_type,
                )
                break
            except RuntimeError as error:
                if str(error) != "solved-leaf cache publication is locked":
                    raise
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    raise RuntimeError(
                        "timed out waiting for solved-leaf cache migration "
                        "publication lock"
                    ) from error
                time.sleep(min(
                    _LEGACY_MIGRATION_LOCK_RETRY_SECONDS, remaining
                ))
        if published.status is SolvedLeafLookupStatus.CORRUPT:
            return published
        if published.status is not SolvedLeafLookupStatus.HIT:
            return published
        return _authenticate_solved_leaf_hit(
            plan, leaf, store, store.lookup(identity, leaf.leaf_id)
        )
    return current


def _validate_precision120(outcome: StageOutcome) -> None:
    if (
        outcome.deep_diagnostics is not None
        or outcome.self_refinement_enclosed is not None
        or outcome.discrepancy_from_previous_abs is None
        or outcome.discrepancy_enclosed is None
    ):
        raise ValueError("campaign 120-digit evidence is incomplete")


def _ordered_selection_records(
    selection: CampaignSelection,
    records_by_id: Mapping[str, CampaignLeafRecord],
) -> tuple[CampaignLeafRecord, ...]:
    return tuple(
        records_by_id[leaf_id]
        for leaf_id in selection.leaf_ids
        if leaf_id in records_by_id
    )


def _continuation_chain_key(
    leaf: CampaignLeafPlan,
) -> tuple[str, str, str, str]:
    return (
        leaf.role,
        leaf.leaf.mode_label,
        leaf.mechanism_id,
        leaf.leaf.spin_role,
    )


def _produced_response(record: CampaignLeafRecord) -> complex | None:
    if record.state != "PRODUCED" or not record.stages:
        return None
    raw_result = record.stages[-1].outcome.component_result.get("result")
    if not isinstance(raw_result, Mapping):
        return None
    try:
        result = ComponentResult.from_mapping(raw_result)
    except (TypeError, ValueError):
        return None
    if result.response is None:
        return None
    response = complex(result.response)
    if not (math.isfinite(response.real) and math.isfinite(response.imag)):
        return None
    return response


def _campaign_stage_record(
    plan: CampaignPlan,
    available: PrecisionCapabilities,
    outcome: StageOutcome,
) -> CampaignStageRecord:
    return CampaignStageRecord(outcome, {
        "precision_factory_identity": plan.precision_factory_identity.to_mapping(),
        "available_precision_digits": list(available.digits),
    })


def _failed_preflight_recovery_record(
    plan: CampaignPlan,
    available: PrecisionCapabilities,
    leaf: CampaignLeafPlan,
    record: CampaignLeafRecord,
    outcome: StageOutcome,
    predecessor: CampaignExecutionAttempt,
) -> CampaignLeafRecord:
    if not isinstance(outcome, StageOutcome) or outcome.digits != 120:
        raise ValueError(
            "campaign backend returned invalid failed-preflight 120-digit evidence"
        )
    if not _validate_component_result(
        leaf, outcome, allow_historical_conditioning_absence=False
    ):
        raise ValueError(
            "failed-preflight recovery lacks canonical base evidence"
        )
    embedded, recovery_produced = _validate_failed_preflight_recovery_stage(
        leaf, outcome
    )
    if embedded.to_mapping() != predecessor.to_mapping():
        raise ValueError(
            "failed-preflight recovery embedded the wrong predecessor"
        )
    if leaf.role == "deep" and record.sentinel:
        recovery_produced = False
    return CampaignLeafRecord(
        leaf_id=record.leaf_id,
        role=record.role,
        state="PRODUCED" if recovery_produced else "UNRESOLVED",
        stages=(
            *record.stages,
            _campaign_stage_record(plan, available, outcome),
        ),
        trigger_ids=record.trigger_ids,
        sentinel=record.sentinel,
        sentinel_comparison=None,
    )


def _execute_campaign_stage(
    backend: object,
    leaf: CampaignLeafPlan,
    digits: int,
    previous_stages: Sequence[CampaignStageRecord] = (),
    response_predictor: complex | None = None,
) -> StageOutcome:
    """Execute a stage while preserving the promotion evidence on resume.

    Existing injected fixture/operator backends keep the original two-argument
    ``execute_stage`` contract.  A backend that computes promoted-precision
    discrepancy evidence can implement ``execute_promoted_stage`` and receives
    the already authenticated checkpoint outcomes, including in a fresh
    process after ``campaign-resume``.
    """

    if digits > 64:
        promoted_with_predictor = getattr(
            backend, "execute_promoted_stage_with_predictor", None
        )
        if promoted_with_predictor is not None:
            if not callable(promoted_with_predictor):
                raise ValueError(
                    "campaign promoted-stage predictor backend is invalid"
                )
            return promoted_with_predictor(
                leaf,
                digits,
                tuple(stage.outcome for stage in previous_stages),
                response_predictor,
            )
        promoted = getattr(backend, "execute_promoted_stage", None)
        if promoted is not None:
            if not callable(promoted):
                raise ValueError("campaign promoted-stage backend is invalid")
            return promoted(
                leaf,
                digits,
                tuple(stage.outcome for stage in previous_stages),
            )
    execute_with_predictor = getattr(
        backend, "execute_stage_with_predictor", None
    )
    if execute_with_predictor is not None:
        if not callable(execute_with_predictor):
            raise ValueError("campaign stage predictor backend is invalid")
        return execute_with_predictor(leaf, digits, response_predictor)
    execute = getattr(backend, "execute_stage", None)
    if not callable(execute):
        raise ValueError("campaign backend execute_stage is unavailable")
    return execute(leaf, digits)


def _execute_campaign_stage_after_failed_preflight(
    backend: object,
    leaf: CampaignLeafPlan,
    predecessor: CampaignExecutionAttempt,
    response_predictor: complex | None = None,
) -> StageOutcome:
    """Run the dedicated 120-base/120-refinement recovery boundary."""

    _validate_failed_preflight_predecessor(predecessor, leaf)
    with_predictor = getattr(
        backend,
        "execute_promoted_stage_after_failed_preflight_with_predictor",
        None,
    )
    if with_predictor is not None:
        if not callable(with_predictor):
            raise ValueError("failed-preflight predictor backend is invalid")
        return with_predictor(
            leaf, 120, predecessor, response_predictor
        )
    execute = getattr(
        backend, "execute_promoted_stage_after_failed_preflight", None
    )
    if not callable(execute):
        raise ValueError(
            "campaign backend lacks failed-preflight 120 refinement support"
        )
    return execute(leaf, 120, predecessor)


def worker_failure_payload(error: BaseException) -> dict[str, object] | None:
    """Preserve one bounded legacy-or-extended Julia worker diagnostic."""

    return _julia_worker_failure_payload(error)


def _worker_failure_payload(error: BaseException) -> dict[str, object] | None:
    """Backward-compatible internal spelling for the campaign failure path."""

    return worker_failure_payload(error)


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
    response_predictor: complex | None = None,
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
                backend,
                leaf,
                digits,
                previous_stages,
                response_predictor,
            )
        except KeyboardInterrupt:
            raise
        except BaseException as error:
            worker_failure = _worker_failure_payload(error)
            emit_progress(
                ProgressEventKind.LEAF_FAILED,
                precision_digits=digits,
                error_type=type(error).__name__,
                message=str(error),
                elapsed_seconds=time.monotonic() - started,
                **(
                    {} if worker_failure is None
                    else {"worker_failure": worker_failure}
                ),
            )
            raise
    return outcome, time.monotonic() - started


def _execute_failed_preflight_recovery_with_progress(
    backend: object,
    leaf: CampaignLeafPlan,
    predecessor: CampaignExecutionAttempt,
    context: Mapping[str, object],
    response_predictor: complex | None = None,
) -> tuple[StageOutcome, float]:
    started = time.monotonic()
    with progress_scope(
        **context,
        precision_digits=120,
        component_pass="promoted",
    ):
        emit_progress(ProgressEventKind.PRECISION_STAGE_STARTED)
        try:
            outcome = _execute_campaign_stage_after_failed_preflight(
                backend,
                leaf,
                predecessor,
                response_predictor,
            )
        except KeyboardInterrupt:
            raise
        except BaseException as error:
            worker_failure = _worker_failure_payload(error)
            emit_progress(
                ProgressEventKind.LEAF_FAILED,
                precision_digits=120,
                error_type=type(error).__name__,
                message=str(error),
                elapsed_seconds=time.monotonic() - started,
                **(
                    {} if worker_failure is None
                    else {"worker_failure": worker_failure}
                ),
            )
            raise
    return outcome, time.monotonic() - started


def _numerical_failure_promotion_decision(
    failure: Mapping[str, object], digits: int
) -> dict[str, object] | None:
    code = failure.get("failure_code")
    if digits != 80 or code not in NUMERICAL_CONTROL_FAILURE_CODES:
        return None
    predicted: str | None = None
    required: str | None = None
    limited: bool | None = None
    preflight: bool | None = None
    requested = code == "INSUFFICIENT_ASYMPTOTIC_PRECISION"
    if requested:
        diagnostics = failure.get("diagnostics")
        if not isinstance(diagnostics, Mapping):
            raise ValueError("asymptotic precision failure diagnostics are missing")
        predicted = diagnostics.get("predicted_reliable_digits")
        required = diagnostics.get("required_reliable_digits")
        preflight = diagnostics.get("asymptotic_preflight_avoided_ode")
        limited = True
    return _validated_promotion_decision({
        "schema": _PROMOTION_DECISION_SCHEMA,
        "from_precision_digits": 80,
        "to_precision_digits": 120,
        "state": "REQUESTED" if requested else "SUPPRESSED",
        "reason": code,
        "predicted_reliable_digits": predicted,
        "required_reliable_digits": required,
        "precision_limited": limited,
        "asymptotic_preflight_avoided_ode": preflight,
    })


def _execution_attempt_from_failure(
    error: BaseException,
    *,
    leaf: CampaignLeafPlan,
    context: Mapping[str, object],
    digits: int,
    attempt_ordinal: int,
) -> CampaignExecutionAttempt | None:
    """Return a durable control attempt only for exact, well-formed typed failures."""

    if not isinstance(error, _CONTAINABLE_EXCEPTION_TYPES):
        return None
    receipt = _worker_failure_payload(error)
    if receipt is None:
        return None
    try:
        receipt = _validated_attempt_failure_receipt(receipt)
    except ValueError:
        return None
    failure = receipt["failure"]
    assert isinstance(failure, Mapping)
    code = str(failure["failure_code"])
    expected_type: type[BaseException]
    if code == "ODE_RESOURCE_LIMIT":
        expected_type = JuliaODEResourceLimitError
    elif code == "ROOT_READOUT_RESOURCE_INFEASIBLE":
        expected_type = JuliaRootReadoutResourceLimitError
    elif code in NUMERICAL_CONTROL_FAILURE_CODES:
        expected_type = JuliaNumericalControlError
    else:
        expected_type = JuliaWorkerTimeoutError
    if type(error) is not expected_type:
        return None
    if (
        expected_type is JuliaNumericalControlError
        and error.failure_code != code
    ):
        return None
    if code == "WORKER_TIMEOUT" and receipt["worker_timed_out"] is not True:
        return None
    if code != "WORKER_TIMEOUT" and receipt["worker_timed_out"] is not False:
        return None
    leaf_index = context.get("leaf_index")
    if isinstance(leaf_index, bool) or not isinstance(leaf_index, int):
        return None
    promotion_decision = _numerical_failure_promotion_decision(failure, digits)
    if promotion_decision is not None:
        receipt = dict(receipt)
        enriched_failure = dict(failure)
        enriched_failure["promotion_decision"] = promotion_decision
        receipt["failure"] = enriched_failure
        receipt = _validated_attempt_failure_receipt(receipt)
    attempt = CampaignExecutionAttempt(
        attempt_ordinal=attempt_ordinal,
        leaf_id=leaf.leaf_id,
        leaf_index=leaf_index,
        role=leaf.role,
        state=_CONTAINABLE_FAILURE_STATES[code],
        precision_digits=digits,
        failure_code=code,
        failure_receipt=receipt,
        created_at_utc=(
            datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        ),
    )
    if code == "INSUFFICIENT_ASYMPTOTIC_PRECISION" and digits in {80, 120}:
        try:
            if digits == 80:
                _validate_failed_preflight_predecessor(attempt, leaf)
            else:
                _validate_failed_preflight_recovery_failure(attempt, leaf)
        except ValueError:
            return None
    return attempt


def _checkpoint_attempt_with_progress(
    path: Path,
    mapping: Mapping[str, object],
    *,
    context: Mapping[str, object],
    digits: int,
) -> None:
    with progress_scope(
        **context,
        precision_digits=digits,
        component_pass="promoted",
    ):
        emit_progress(ProgressEventKind.CHECKPOINT_WRITING)
        _atomic_json(path, mapping)
        emit_progress(ProgressEventKind.CHECKPOINT_WRITTEN)


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
            store_path=str(store.root),
        )
    except (OSError, RuntimeError, ValueError) as error:
        emit_progress(
            ProgressEventKind.LEAF_CACHE_PUBLICATION_FAILED,
            store_path=str(store.root),
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
    if resume:
        resume_path = Path(checkpoint_path)
        if not resume_path.exists():
            raise ValueError("campaign resume requires an existing checkpoint")
        _load_checkpoint(plan, resume_path)
    execution_leaf_ids = _campaign_execution_leaf_ids(plan, selection)
    cache_lookups: dict[str, SolvedLeafLookup] = {}
    if solved_leaf_store is not None:
        leaf_by_id = {leaf.leaf_id: leaf for leaf in plan.leaves}
        for leaf_id in execution_leaf_ids:
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
                for index, leaf_id in enumerate(execution_leaf_ids, start=1)
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
    except KeyboardInterrupt:
        interrupted_context = _ACTIVE_CAMPAIGN_LEAF_CONTEXT.get()
        if interrupted_context is not None:
            with progress_scope(**interrupted_context):
                emit_progress(
                    ProgressEventKind.LEAF_INTERRUPTED,
                    message="operator interrupt",
                )
        _ACTIVE_CAMPAIGN_LEAF_CONTEXT.set(None)
        emit_progress(
            ProgressEventKind.CAMPAIGN_INTERRUPTED,
            message="operator interrupt",
        )
        raise
    except BaseException as error:
        _ACTIVE_CAMPAIGN_LEAF_CONTEXT.set(None)
        worker_failure = _worker_failure_payload(error)
        emit_progress(
            ProgressEventKind.CAMPAIGN_FAILED,
            error_type=type(error).__name__,
            message=str(error),
            **(
                {} if worker_failure is None
                else {"worker_failure": worker_failure}
            ),
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
        loaded_selection, existing, loaded_attempts, loaded_state, loaded_schema_version = (
            _load_checkpoint_with_attempts(plan, path)
        )
        if loaded_selection != selection:
            raise ValueError("campaign checkpoint selection does not match request")
        if (
            loaded_schema_version != CAMPAIGN_CHECKPOINT_SCHEMA_VERSION
            and loaded_state == "PARTIAL"
        ):
            raise ValueError(
                "incomplete historical campaign checkpoint is read-only; "
                "preserve it as evidence and start with a fresh checkpoint path"
            )
        if loaded_schema_version != CAMPAIGN_CHECKPOINT_SCHEMA_VERSION:
            leaf_by_id = {leaf.leaf_id: leaf for leaf in plan.leaves}
            for record in existing:
                _validate_record_semantics(
                    leaf_by_id[record.leaf_id],
                    record,
                    plan.precision_factory_identity,
                    checkpoint_schema_version=(
                        CAMPAIGN_CHECKPOINT_SCHEMA_VERSION
                    ),
                )
        records_by_id = {record.leaf_id: record for record in existing}
        for record in existing:
            for stage in record.stages:
                prior = set(stage.runner_provenance["available_precision_digits"])
                if not prior.issubset(set(available.digits)):
                    raise ValueError(
                        "campaign backend precision availability is not a permitted superset"
                    )
        attempts = list(loaded_attempts)
    else:
        if resume:
            raise ValueError("campaign resume requires an existing checkpoint")
        records_by_id = {}
        attempts = []
    reused = sum(
        len(record.stages) for record in records_by_id.values()
    )
    executed = 0
    leaf_by_id = {leaf.leaf_id: leaf for leaf in plan.leaves}
    execution_leaf_ids = _campaign_execution_leaf_ids(plan, selection)
    continuation_responses: dict[tuple[str, str, str, str], complex] = {}
    for index, leaf_id in enumerate(execution_leaf_ids):
        leaf = leaf_by_id[leaf_id]
        continuation_key = _continuation_chain_key(leaf)
        response_predictor = continuation_responses.pop(
            continuation_key, None
        )
        context = _leaf_progress_context(leaf, index + 1, len(selection.leaf_ids))
        _ACTIVE_CAMPAIGN_LEAF_CONTEXT.set(context)
        record = records_by_id.get(leaf_id)
        if record is not None and record.state in {
            "PRODUCED", "UNRESOLVED"
        }:
            with progress_scope(**context):
                _publish_terminal_solved_leaf(
                    plan, leaf, record, solved_leaf_store
                )
                response = _produced_response(record)
                if response is not None:
                    continuation_responses[continuation_key] = response
                emit_progress(
                    ProgressEventKind.LEAF_REUSED,
                    state=record.state,
                    stage_count=len(record.stages),
                )
            continue
        if record is None and solved_leaf_store is not None:
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
                cached_predecessor = _embedded_failed_preflight_predecessor(
                    cached_record, leaf
                )
                if cached_predecessor is not None:
                    existing_predecessor = _failed_preflight_predecessor_for_leaf(
                        attempts, leaf
                    )
                    if existing_predecessor is None:
                        cached_predecessor = replace(
                            cached_predecessor,
                            attempt_ordinal=len(attempts) + 1,
                            leaf_index=index + 1,
                        )
                        attempts.append(cached_predecessor)
                    else:
                        cached_predecessor = existing_predecessor
                    cached_record = (
                        _record_with_materialized_failed_preflight_predecessor(
                            cached_record, cached_predecessor
                        )
                    )
                records_by_id[leaf_id] = cached_record
                with progress_scope(**context):
                    emit_progress(ProgressEventKind.CHECKPOINT_WRITING)
                    _atomic_json(
                        path,
                        _checkpoint_mapping(
                            plan,
                            selection,
                            _ordered_selection_records(selection, records_by_id),
                            attempts,
                        ),
                    )
                    emit_progress(ProgressEventKind.CHECKPOINT_WRITTEN)
                    emit_progress(
                        ProgressEventKind.LEAF_REUSED,
                        state=cached_record.state,
                        stage_count=len(cached_record.stages),
                        source="authenticated prior originating result",
                    )
                response = _produced_response(cached_record)
                if response is not None:
                    continuation_responses[continuation_key] = response
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
        if record is None:
            outcome, stage_duration = _execute_campaign_stage_with_progress(
                backend,
                leaf,
                64,
                context,
                response_predictor=response_predictor,
            )
            if not isinstance(outcome, StageOutcome) or outcome.digits != 64:
                raise ValueError("campaign backend returned an invalid binary64 stage")
            executed += 1
            if leaf.role == "control":
                record = CampaignLeafRecord(
                    leaf_id=leaf.leaf_id,
                    role=leaf.role,
                    state=_terminal_state(outcome),
                    stages=(_campaign_stage_record(plan, available, outcome),),
                )
            elif leaf.role == "primary":
                precision80_digits, _ = _primary_recovery_digits()
                try:
                    production = _validate_component_result(
                        leaf,
                        outcome,
                        allow_historical_conditioning_absence=False,
                    )
                except _UnauthenticatedComponentEvidence:
                    # Promotion is recovery for authenticated numerical
                    # nonconvergence, not a new fail-fast boundary for
                    # malformed or deliberately adverse evidence.  Keep the
                    # strict validator authoritative at checkpoint/cache
                    # authentication while refusing to promote this stage.
                    production = False
                promoted = _primary_binary64_promotes(
                    outcome, production=production
                )
                record = CampaignLeafRecord(
                    leaf_id=leaf.leaf_id,
                    role=leaf.role,
                    state=(
                        "MISSING_PRECISION"
                        if promoted and precision80_digits not in available.digits
                        else "IN_PROGRESS"
                        if promoted
                        else _terminal_state(outcome)
                    ),
                    stages=(_campaign_stage_record(plan, available, outcome),),
                    missing_precision_digits=(
                        precision80_digits
                        if promoted and precision80_digits not in available.digits
                        else None
                    ),
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
            records_by_id[leaf_id] = record
            _checkpoint_stage_with_progress(
                path,
                _checkpoint_mapping(
                    plan,
                    selection,
                    _ordered_selection_records(selection, records_by_id),
                    attempts,
                ),
                context=context,
                digits=64,
                duration_seconds=stage_duration,
                record=record,
            )

        if record.state in {"PRODUCED", "UNRESOLVED"}:
            with progress_scope(**context):
                _publish_terminal_solved_leaf(
                    plan, leaf, record, solved_leaf_store
                )
            response = _produced_response(record)
            if response is not None:
                continuation_responses[continuation_key] = response
            with progress_scope(**context):
                emit_progress(
                    ProgressEventKind.LEAF_COMPLETED,
                    state=record.state,
                    stage_count=len(record.stages),
                )
            continue
        if len(record.stages) == 1:
            failed_preflight_predecessor = (
                _failed_preflight_predecessor_for_leaf(attempts, leaf)
            )
            if failed_preflight_predecessor is not None:
                if _failed_preflight_recovery_failure_for_leaf(
                    attempts, leaf
                ) is not None:
                    continue
                if 120 not in available.digits:
                    continue
                try:
                    outcome120, recovery_duration = (
                        _execute_failed_preflight_recovery_with_progress(
                            backend,
                            leaf,
                            failed_preflight_predecessor,
                            context,
                            response_predictor,
                        )
                    )
                except _CONTAINABLE_EXCEPTION_TYPES as recovery_error:
                    recovery_attempt = _execution_attempt_from_failure(
                        recovery_error,
                        leaf=leaf,
                        context=context,
                        digits=120,
                        attempt_ordinal=len(attempts) + 1,
                    )
                    if recovery_attempt is None:
                        raise
                    attempts.append(recovery_attempt)
                    _checkpoint_attempt_with_progress(
                        path,
                        _checkpoint_mapping(
                            plan,
                            selection,
                            _ordered_selection_records(
                                selection, records_by_id
                            ),
                            attempts,
                        ),
                        context=context,
                        digits=120,
                    )
                    continue
                record = _failed_preflight_recovery_record(
                    plan,
                    available,
                    leaf,
                    record,
                    outcome120,
                    failed_preflight_predecessor,
                )
                records_by_id[leaf_id] = record
                executed += 1
                _checkpoint_stage_with_progress(
                    path,
                    _checkpoint_mapping(
                        plan,
                        selection,
                        _ordered_selection_records(selection, records_by_id),
                        attempts,
                    ),
                    context=context,
                    digits=120,
                    duration_seconds=recovery_duration,
                    record=record,
                )
                with progress_scope(**context):
                    _publish_terminal_solved_leaf(
                        plan, leaf, record, solved_leaf_store
                    )
                response = _produced_response(record)
                if response is not None:
                    continuation_responses[continuation_key] = response
                with progress_scope(**context):
                    emit_progress(
                        ProgressEventKind.LEAF_COMPLETED,
                        state=record.state,
                        stage_count=len(record.stages),
                    )
                continue
            precision80_digits = (
                _primary_recovery_digits()[0]
                if leaf.role == "primary"
                else 80
            )
            if precision80_digits not in available.digits:
                continue
            try:
                outcome80, stage_duration = _execute_campaign_stage_with_progress(
                    backend,
                    leaf,
                    precision80_digits,
                    context,
                    record.stages,
                    response_predictor,
                )
            except _CONTAINABLE_EXCEPTION_TYPES as error:
                attempt = _execution_attempt_from_failure(
                    error,
                    leaf=leaf,
                    context=context,
                    digits=precision80_digits,
                    attempt_ordinal=len(attempts) + 1,
                )
                if attempt is None:
                    raise
                attempts.append(attempt)
                failed_preflight = (
                    attempt.failure_code
                    == "INSUFFICIENT_ASYMPTOTIC_PRECISION"
                )
                if failed_preflight and 120 not in available.digits:
                    record = CampaignLeafRecord(
                        leaf_id=record.leaf_id,
                        role=record.role,
                        state="MISSING_PRECISION",
                        stages=record.stages,
                        trigger_ids=record.trigger_ids,
                        sentinel=record.sentinel,
                        missing_precision_digits=120,
                        sentinel_comparison=record.sentinel_comparison,
                    )
                    records_by_id[leaf_id] = record
                _checkpoint_attempt_with_progress(
                    path,
                    _checkpoint_mapping(
                        plan,
                        selection,
                        _ordered_selection_records(selection, records_by_id),
                        attempts,
                    ),
                    context=context,
                    digits=precision80_digits,
                )
                if not failed_preflight or 120 not in available.digits:
                    continue
                try:
                    outcome120, recovery_duration = (
                        _execute_failed_preflight_recovery_with_progress(
                            backend,
                            leaf,
                            attempt,
                            context,
                            response_predictor,
                        )
                    )
                except _CONTAINABLE_EXCEPTION_TYPES as recovery_error:
                    recovery_attempt = _execution_attempt_from_failure(
                        recovery_error,
                        leaf=leaf,
                        context=context,
                        digits=120,
                        attempt_ordinal=len(attempts) + 1,
                    )
                    if recovery_attempt is None:
                        raise
                    attempts.append(recovery_attempt)
                    _checkpoint_attempt_with_progress(
                        path,
                        _checkpoint_mapping(
                            plan,
                            selection,
                            _ordered_selection_records(
                                selection, records_by_id
                            ),
                            attempts,
                        ),
                        context=context,
                        digits=120,
                    )
                    continue
                if (
                    not isinstance(outcome120, StageOutcome)
                    or outcome120.digits != 120
                ):
                    raise ValueError(
                        "campaign backend returned invalid failed-preflight "
                        "120-digit evidence"
                    )
                if not _validate_component_result(
                    leaf,
                    outcome120,
                    allow_historical_conditioning_absence=False,
                ):
                    raise ValueError(
                        "failed-preflight recovery lacks canonical base evidence"
                    )
                embedded, recovery_produced = (
                    _validate_failed_preflight_recovery_stage(
                        leaf, outcome120
                    )
                )
                if embedded.to_mapping() != attempt.to_mapping():
                    raise ValueError(
                        "failed-preflight recovery embedded the wrong predecessor"
                    )
                if leaf.role == "deep" and record.sentinel:
                    recovery_produced = False
                record = CampaignLeafRecord(
                    leaf_id=record.leaf_id,
                    role=record.role,
                    state="PRODUCED" if recovery_produced else "UNRESOLVED",
                    stages=(
                        *record.stages,
                        _campaign_stage_record(plan, available, outcome120),
                    ),
                    trigger_ids=record.trigger_ids,
                    sentinel=record.sentinel,
                    sentinel_comparison=None,
                )
                records_by_id[leaf_id] = record
                executed += 1
                _checkpoint_stage_with_progress(
                    path,
                    _checkpoint_mapping(
                        plan,
                        selection,
                        _ordered_selection_records(selection, records_by_id),
                        attempts,
                    ),
                    context=context,
                    digits=120,
                    duration_seconds=recovery_duration,
                    record=record,
                )
                with progress_scope(**context):
                    _publish_terminal_solved_leaf(
                        plan, leaf, record, solved_leaf_store
                    )
                response = _produced_response(record)
                if response is not None:
                    continuation_responses[continuation_key] = response
                with progress_scope(**context):
                    emit_progress(
                        ProgressEventKind.LEAF_COMPLETED,
                        state=record.state,
                        stage_count=len(record.stages),
                    )
                continue
            if (
                not isinstance(outcome80, StageOutcome)
                or outcome80.digits != 80
                or outcome80.self_refinement_enclosed is None
                or outcome80.discrepancy_from_previous_abs is None
                or outcome80.discrepancy_enclosed is None
            ):
                raise ValueError("campaign backend returned incomplete 80-digit evidence")
            executed += 1
            if leaf.role == "primary":
                if not _validate_component_result(
                    leaf,
                    outcome80,
                    allow_historical_conditioning_absence=False,
                ):
                    raise ValueError(
                        "campaign promoted PRIMARY stage lacks canonical "
                        "production evidence"
                    )
                outcome80 = _stage_with_promotion_decision(
                    outcome80, _primary_precision120_decision(outcome80)
                )
                _, precision120_digits = _primary_recovery_digits()
                if _primary_requires_precision120(outcome80):
                    state = (
                        "MISSING_PRECISION"
                        if precision120_digits not in available.digits
                        else "IN_PROGRESS"
                    )
                    missing = (
                        precision120_digits
                        if precision120_digits not in available.digits
                        else None
                    )
                else:
                    state = _terminal_state(
                        outcome80,
                        enclosed=(
                            bool(outcome80.self_refinement_enclosed)
                            and bool(outcome80.discrepancy_enclosed)
                        ),
                    )
                    missing = None
                record = CampaignLeafRecord(
                    leaf_id=record.leaf_id,
                    role=record.role,
                    state=state,
                    stages=(
                        *record.stages,
                        _campaign_stage_record(plan, available, outcome80),
                    ),
                    missing_precision_digits=missing,
                )
                records_by_id[leaf_id] = record
                _checkpoint_stage_with_progress(
                    path,
                    _checkpoint_mapping(
                        plan,
                        selection,
                        _ordered_selection_records(selection, records_by_id),
                        attempts,
                    ),
                    context=context,
                    digits=precision80_digits,
                    duration_seconds=stage_duration,
                    record=record,
                )
            else:
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
                decision = _deep_precision120_decision(
                    outcome80, sentinel_false_negative=false_negative
                )
                outcome80 = _stage_with_promotion_decision(outcome80, decision)
                requires120 = decision["state"] == "REQUESTED"
                if false_negative and requires120:
                    state = "INVALID_SENTINEL_FALSE_NEGATIVE"
                    missing = 120
                elif not requires120:
                    state = _terminal_state(
                        outcome80,
                        enclosed=(
                            bool(outcome80.self_refinement_enclosed)
                            and bool(outcome80.discrepancy_enclosed)
                        ),
                    )
                    missing = None
                elif 120 not in available.digits:
                    state = "MISSING_PRECISION"
                    missing = 120
                else:
                    state = "IN_PROGRESS"
                    missing = None
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
                records_by_id[leaf_id] = record
                _checkpoint_stage_with_progress(
                    path,
                    _checkpoint_mapping(
                        plan,
                        selection,
                        _ordered_selection_records(
                            selection, records_by_id
                        ),
                        attempts,
                    ),
                    context=context,
                    digits=80,
                    duration_seconds=stage_duration,
                    record=record,
                )

        if record.state in {"PRODUCED", "UNRESOLVED"}:
            with progress_scope(**context):
                _publish_terminal_solved_leaf(
                    plan, leaf, record, solved_leaf_store
                )
            response = _produced_response(record)
            if response is not None:
                continuation_responses[continuation_key] = response
            with progress_scope(**context):
                emit_progress(
                    ProgressEventKind.LEAF_COMPLETED,
                    state=record.state,
                    stage_count=len(record.stages),
                )
            continue
        if len(record.stages) == 2:
            precision120_digits = (
                _primary_recovery_digits()[1]
                if leaf.role == "primary"
                else 120
            )
            if precision120_digits not in available.digits:
                continue
            try:
                outcome120, stage_duration = _execute_campaign_stage_with_progress(
                    backend,
                    leaf,
                    precision120_digits,
                    context,
                    record.stages,
                    response_predictor,
                )
            except _CONTAINABLE_EXCEPTION_TYPES as error:
                attempt = _execution_attempt_from_failure(
                    error,
                    leaf=leaf,
                    context=context,
                    digits=precision120_digits,
                    attempt_ordinal=len(attempts) + 1,
                )
                if attempt is None:
                    raise
                attempts.append(attempt)
                _checkpoint_attempt_with_progress(
                    path,
                    _checkpoint_mapping(
                        plan,
                        selection,
                        _ordered_selection_records(selection, records_by_id),
                        attempts,
                    ),
                    context=context,
                    digits=precision120_digits,
                )
                continue
            if (
                not isinstance(outcome120, StageOutcome)
                or outcome120.digits != 120
                or outcome120.discrepancy_from_previous_abs is None
                or outcome120.discrepancy_enclosed is None
            ):
                raise ValueError("campaign backend returned incomplete 120-digit evidence")
            executed += 1
            if leaf.role == "primary":
                _validate_precision120(outcome120)
                if not _validate_component_result(
                    leaf,
                    outcome120,
                    allow_historical_conditioning_absence=False,
                ):
                    raise ValueError(
                        "campaign promoted PRIMARY stage lacks canonical "
                        "production evidence"
                    )
                record = CampaignLeafRecord(
                    leaf_id=record.leaf_id,
                    role=record.role,
                    state=_primary_precision120_terminal_state(outcome120),
                    stages=(
                        *record.stages,
                        _campaign_stage_record(plan, available, outcome120),
                    ),
                )
            else:
                false_negative = (
                    record.state == "INVALID_SENTINEL_FALSE_NEGATIVE"
                )
                record = CampaignLeafRecord(
                    leaf_id=record.leaf_id,
                    role=record.role,
                    state=(
                        "INVALID_SENTINEL_FALSE_NEGATIVE"
                        if false_negative
                        else _terminal_state(
                            outcome120,
                            enclosed=bool(outcome120.discrepancy_enclosed),
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
            records_by_id[leaf_id] = record
            _checkpoint_stage_with_progress(
                path,
                _checkpoint_mapping(
                    plan,
                    selection,
                    _ordered_selection_records(selection, records_by_id),
                    attempts,
                ),
                context=context,
                digits=precision120_digits,
                duration_seconds=stage_duration,
                record=record,
            )
        if record.state in {"PRODUCED", "UNRESOLVED"}:
            with progress_scope(**context):
                _publish_terminal_solved_leaf(
                    plan, leaf, record, solved_leaf_store
                )
            response = _produced_response(record)
            if response is not None:
                continuation_responses[continuation_key] = response
            with progress_scope(**context):
                emit_progress(
                    ProgressEventKind.LEAF_COMPLETED,
                    state=record.state,
                    stage_count=len(record.stages),
                )
    records = _ordered_selection_records(selection, records_by_id)
    mapping = _checkpoint_mapping(plan, selection, records, attempts)
    _ACTIVE_CAMPAIGN_LEAF_CONTEXT.set(None)
    return CampaignRunSummary(
        campaign_id=plan.campaign_id,
        selection_id=selection.selection_id,
        state=str(mapping["state"]),
        executed_stage_count=executed,
        reused_stage_count=reused,
        records=tuple(records),
        checkpoint_path=str(path),
        attempts=tuple(attempts),
    )


def validate_campaign_checkpoint(
    plan: CampaignPlan,
    checkpoint_path: str | os.PathLike[str] | Path,
    *,
    require_complete_campaign: bool = False,
) -> CampaignRunSummary:
    path = Path(checkpoint_path)
    selection, records, attempts, state, checkpoint_schema_version = (
        _load_checkpoint_with_attempts(plan, path)
    )
    if require_complete_campaign:
        expected_ids = B_PRIME_RELEASE_DOMAIN.production_leaf_ids
        if selection.leaf_ids != expected_ids:
            raise ValueError(
                "full campaign requires the exact ordered "
                f"{len(expected_ids)} leaf IDs"
            )
        if tuple(record.leaf_id for record in records) != expected_ids:
            raise ValueError("full campaign has missing or extra leaf records")
        terminal_ids = {
            record.leaf_id
            for record in records
            if record.state in {"PRODUCED", "UNRESOLVED"}
        }
        deferred = tuple(
            attempt
            for attempt in attempts
            if attempt.leaf_id not in terminal_ids
        )
        if deferred:
            codes = ", ".join(
                f"{attempt.leaf_id}:{attempt.failure_code}"
                for attempt in deferred
            )
            raise ValueError(
                "full campaign has execution-resource-limited deferred leaves: "
                + codes
            )
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
                checkpoint_schema_version=checkpoint_schema_version,
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
        attempts=attempts,
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
        try:
            _validate_cacheable_leaf_record(plan, leaf, record)
        except _NonProductionSolvedLeafRecord:
            skipped += 1
            continue
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

    value, bindings, records, _attempts = _read_checkpoint_envelope(path)
    if (
        value["schema_version"] != CAMPAIGN_CHECKPOINT_SCHEMA_VERSION
        and value.get("state") == "PARTIAL"
    ):
        raise ValueError(
            "incomplete historical campaign checkpoint is read-only; "
            "it cannot publish current solved-leaf evidence"
        )
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
    for name in ("selection_jobs_sha256", "precision_factory_identity"):
        if bindings[name] != current_bindings[name]:
            raise ValueError(
                f"campaign checkpoint scientific binding {name} is incompatible"
            )
    allowed_precision_contracts = {
        current_bindings["precision_contract_sha256"],
        *_historical_checkpoint_precision_contract_sha256s(
            value["schema_version"]
        ),
    }
    if bindings["precision_contract_sha256"] not in allowed_precision_contracts:
        raise ValueError(
            "campaign checkpoint scientific binding "
            "precision_contract_sha256 is incompatible"
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
    leaf_by_id = {leaf.leaf_id: leaf for leaf in plan.leaves}
    for record in records:
        leaf = leaf_by_id[record.leaf_id]
        if record.role != leaf.role:
            raise ValueError("campaign checkpoint record role is invalid")
        _validate_record_semantics(
            leaf,
            record,
            plan.precision_factory_identity,
            checkpoint_schema_version=value["schema_version"],
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
    attempt_values: list[CampaignExecutionAttempt] = []
    seen_attempts: set[str] = set()
    for path in paths:
        selection, records, attempts, state, schema_version = (
            _load_checkpoint_with_attempts(plan, path)
        )
        if (
            schema_version != CAMPAIGN_CHECKPOINT_SCHEMA_VERSION
            and state == "PARTIAL"
        ):
            raise ValueError(
                "incomplete historical campaign checkpoint is read-only; "
                "it cannot be merged into schema 6"
            )
        selected_ids.update(selection.leaf_ids)
        for record in records:
            existing = record_by_leaf.get(record.leaf_id)
            if existing is not None and existing.to_mapping() != record.to_mapping():
                raise ValueError(
                    f"campaign checkpoint overlap disagrees for {record.leaf_id}"
                )
            record_by_leaf[record.leaf_id] = record
        for attempt in attempts:
            if attempt.attempt_sha256 not in seen_attempts:
                seen_attempts.add(attempt.attempt_sha256)
                attempt_values.append(attempt)
    canonical_ids = tuple(
        leaf.leaf_id for leaf in plan.leaves if leaf.leaf_id in selected_ids
    )
    selection = _merged_selection(plan, canonical_ids)
    records = tuple(
        record_by_leaf[leaf_id]
        for leaf_id in canonical_ids
        if leaf_id in record_by_leaf
    )
    leaf_by_id = {leaf.leaf_id: leaf for leaf in plan.leaves}
    for record in records:
        _validate_record_semantics(
            leaf_by_id[record.leaf_id],
            record,
            plan.precision_factory_identity,
            checkpoint_schema_version=CAMPAIGN_CHECKPOINT_SCHEMA_VERSION,
        )
    merged_index = {
        leaf_id: index
        for index, leaf_id in enumerate(
            _campaign_execution_leaf_ids(plan, selection), start=1
        )
    }
    attempts = tuple(
        CampaignExecutionAttempt(
            attempt_ordinal=ordinal,
            leaf_id=attempt.leaf_id,
            leaf_index=merged_index[attempt.leaf_id],
            role=attempt.role,
            state=attempt.state,
            precision_digits=attempt.precision_digits,
            failure_code=attempt.failure_code,
            failure_receipt=attempt.failure_receipt,
            created_at_utc=attempt.created_at_utc,
        )
        for ordinal, attempt in enumerate(attempt_values, start=1)
    )
    _atomic_json(output, _checkpoint_mapping(plan, selection, records, attempts))
    mapping = _checkpoint_mapping(plan, selection, records, attempts)
    return CampaignRunSummary(
        campaign_id=plan.campaign_id,
        selection_id=selection.selection_id,
        state=str(mapping["state"]),
        executed_stage_count=0,
        reused_stage_count=sum(len(record.stages) for record in records),
        records=records,
        checkpoint_path=str(output),
        attempts=attempts,
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
    job: ResponseComponentJob,
    backend: object,
    component_pass: str,
    response_predictor: complex | None = None,
) -> ComponentResult:
    started = time.monotonic()
    with progress_scope(component_pass=component_pass):
        emit_progress(ProgressEventKind.COMPONENT_PASS_STARTED)
        try:
            result = run_component(  # type: ignore[arg-type]
                job,
                backend,
                response_predictor=response_predictor,
            )
        except KeyboardInterrupt:
            raise
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
        return self.execute_stage_with_predictor(leaf, digits, None)

    def execute_stage_with_predictor(
        self,
        leaf: CampaignLeafPlan,
        digits: int,
        response_predictor: complex | None,
    ) -> StageOutcome:
        if digits != 64:
            raise NativeResourceUnavailableError(
                "promoted precision must use execute_promoted_stage"
            )
        result = _run_component_with_progress(
            leaf.job,
            self.adapter,
            "primary",
            response_predictor,
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
        return self.execute_promoted_stage_with_predictor(
            leaf, digits, previous_outcomes, None
        )

    def execute_promoted_stage_after_failed_preflight(
        self,
        leaf: CampaignLeafPlan,
        digits: int,
        predecessor: CampaignExecutionAttempt,
    ) -> StageOutcome:
        return self.execute_promoted_stage_after_failed_preflight_with_predictor(
            leaf, digits, predecessor, None
        )

    def execute_promoted_stage_after_failed_preflight_with_predictor(
        self,
        leaf: CampaignLeafPlan,
        digits: int,
        predecessor: CampaignExecutionAttempt,
        response_predictor: complex | None,
    ) -> StageOutcome:
        if digits != 120 or digits not in self.precision_capabilities.digits:
            raise NativeResourceUnavailableError(
                "failed-preflight recovery requires 120-digit capability"
            )
        if not isinstance(predecessor, CampaignExecutionAttempt):
            raise ValueError("failed-preflight predecessor type is invalid")
        _validate_failed_preflight_predecessor(predecessor, leaf)
        if self.julia_adapter is None:
            raise NativeResourceUnavailableError(
                "M02 Julia precision worker is unavailable"
            )
        base_backend = JuliaPrecisionRootBackend(
            self.identity, self.julia_adapter, 120
        )
        refinement_backend = JuliaPrecisionRootBackend(
            self.identity, self.julia_adapter, 120, refinement=1
        )
        base = _run_component_with_progress(
            leaf.job,
            base_backend,
            "primary",
            response_predictor,
        )
        refinement = _run_component_with_progress(
            leaf.job,
            refinement_backend,
            "self-refinement",
            response_predictor,
        )
        refinement_delta = _component_result_delta(refinement, base)
        base_radius = sum(base.error_channels.values())
        refinement_radius = sum(refinement.error_channels.values())
        refinement_enclosed = (
            base.status is ComponentStatus.CONVERGED
            and refinement.status is ComponentStatus.CONVERGED
            and abs(refinement_delta) <= base_radius + refinement_radius
        )
        component_result = {
            "evidence_kind": "package-owned-julia-promoted-component-engine",
            "result": base.to_mapping(),
            "self_refinement_result": refinement.to_mapping(),
            "scientific_runtime": base_backend.scientific_runtime_for(
                leaf.job
            ),
            "self_refinement_scientific_runtime": (
                refinement_backend.scientific_runtime_for(leaf.job)
            ),
            "failed_preflight_predecessor": predecessor.to_mapping(),
            "comparison_kind": _FAILED_PREFLIGHT_COMPARISON_KIND,
            "precision_ladder_discrepancy_applicable": False,
            "same_precision_refinement_discrepancy_abs": abs(
                refinement_delta
            ),
        }
        local_radius = base_radius + abs(refinement_delta)
        return StageOutcome(
            digits=120,
            numerical_state=base.status.value,
            component_result=component_result,
            local_disk_radius_abs=local_radius,
            signed_error_channels=_component_stage_signed_error_channels(
                component_result,
                base,
                repeat_delta=refinement_delta,
                precision_ladder_applicable=False,
            ),
            self_refinement_enclosed=refinement_enclosed,
            discrepancy_from_previous_abs=None,
            discrepancy_enclosed=None,
        )

    def execute_promoted_stage_with_predictor(
        self,
        leaf: CampaignLeafPlan,
        digits: int,
        previous_outcomes: Sequence[StageOutcome],
        response_predictor: complex | None,
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
            leaf.job,
            primary_backend,
            "primary",
            response_predictor,
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
        self_refinement_skipped_reason = None
        if digits == 80:
            if result.status is not ComponentStatus.CONVERGED:
                self_refinement_enclosed = False
                self_refinement_skipped_reason = "PRIMARY_NOT_CONVERGED"
            else:
                repeat_backend = JuliaPrecisionRootBackend(
                    self.identity, self.julia_adapter, digits, refinement=1
                )
                repeat_result = _run_component_with_progress(
                    leaf.job,
                    repeat_backend,
                    "self-refinement",
                    response_predictor,
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
            "scientific_runtime": primary_backend.scientific_runtime_for(
                leaf.job
            ),
        }
        if self_refinement_skipped_reason is not None:
            component_result["self_refinement_skipped_reason"] = (
                self_refinement_skipped_reason
            )
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
