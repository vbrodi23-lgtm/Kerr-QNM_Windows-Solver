"""Deterministic B-prime campaign planning and selected orchestration.

This module is build-only infrastructure.  Planning resolves authenticated
installed roots but cannot start determinant work; execution always requires an
explicit injected component backend.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from contextvars import ContextVar
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
import hashlib
import json
import math
import os
from pathlib import Path, PureWindowsPath
import re
import tempfile
import time
from typing import Callable, Mapping, Sequence

from .contracts import canonical_json_bytes
from .adaptive_controls import (
    ODE_CALIBRATION_BLOCKER,
    MissingODECalibrationError,
    ODEErrorBudget,
)
from .linear_response import B_PRIME_RELEASE_DOMAIN, BPrimeLeaf
from .response_engine import (
    BackendIdentity,
    ComponentResult,
    ComponentStatus,
    ERROR_CHANNELS,
    FixedRootDeterminantSample,
    NativeDeterminantAdapter,
    NativeResourceUnavailableError,
    NumericalConditioningEvidence,
    HISTORICAL_NUMERICAL_CONDITIONING_SCHEMA,
    NUMERICAL_CONDITIONING_SCHEMA,
    NumericalPolicy,
    HISTORICAL_PROMOTED_ROOT_READOUT_POLICY,
    BOUNDED_ANALYTIC_RESPONSE,
    BOUNDED_DERIVATIVE_RESPONSE,
    EXTERIOR_SUPPORT_POLICY_ID,
    EXTERIOR_DERIVATIVE_COMPONENT_IDENTITY,
    EXTERIOR_DERIVATIVE_RESPONSE_DISK_IDENTITY,
    EXTERIOR_DERIVATIVE_METHOD,
    FIXED_ROOT_AXIS_VALIDATION_IDENTITY,
    FIXED_ROOT_DERIVATIVE_CONDITIONING_IDENTITY,
    FULL_COMPLEX_LADDER_VALIDATION_IDENTITY,
    PROMOTED_HORIZON_COMPONENT_IDENTITY,
    PROMOTED_HORIZON_COMPONENT_V2_IDENTITY,
    PROMOTED_HORIZON_COMPONENT_V3_IDENTITY,
    PROMOTED_HORIZON_RESPONSE_METHOD,
    PROMOTED_HORIZON_RESPONSE_METHOD_V2,
    PROMOTED_HORIZON_RESPONSE_METHOD_V3,
    PromotedRootSeal,
    ROOT_SEALED_RESPONSE_REPAIR_IDENTITY,
    PROMOTED_ROOT_READOUT_POLICY,
    RECORDED_REPLAY_BACKEND_ID,
    RecordedReplayBackend,
    ResponseComponentJob,
    RootReadout,
    VettedNativeDeterminantKernel,
    WORKER_RESPONSE_RECEIPT_SCHEMA,
    UNCALIBRATED_ANALYTIC_RESPONSE,
    regularised_gsn_precision_policy,
    root_readout_preserves_authenticated_branch,
    regularised_gsn_mechanism_contract,
    _response_ladder_recovery,
    _response_ladder_recovery_record,
    _journaled_promoted_exterior_response_backend,
    _validate_promoted_horizon_checkpoint_evidence_for_job,
    run_component,
    run_promoted_exterior_component,
    run_promoted_exterior_response_from_seal,
    run_promoted_horizon_component,
    run_promoted_horizon_response_from_seal,
    run_selective_readout_promotion,
)
from .response_uncertainty import ComplexDisk, ZeroContainingDiskError, horizon_response_disk
from .partial_component_checkpoint import PartialComponentJournal
from .promoted_control_calibration import (
    EmpiricalControlProfile,
    PromotedControlCalibrationReceipt,
    load_default_calibration_receipt,
)
from .precision_tiers import (
    PrecisionTier,
    nominal_decimal_digits,
    precision_tier,
    working_precision_bits,
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
    _execution_resource_policy,
    _exterior_support,
    _mode_specific_branch_enclosure_radius,
    _validated_execution_resource_policy,
    _valid_numerical_control_diagnostics,
    horizon_geometry_controls,
    promoted_request_preflight_documents,
    promoted_precision_numerical_controls,
    worker_failure_payload as _julia_worker_failure_payload,
)

# Keep checkpoint authentication independent of campaign-test/backend injection.
# Execution may replace ``JuliaPrecisionRootBackend`` with a fake at the stage
# boundary; canonical request reconstruction must always use the real builder.
_CanonicalRequestJuliaPrecisionRootBackend = JuliaPrecisionRootBackend
from .root_readout_cache import runtime_identity_sha256
from .progress import PROGRESS_SCHEMA, ProgressEventKind, emit_progress, progress_scope
from .solved_leaf_cache import (
    SolvedLeafLookup,
    SolvedLeafLookupStatus,
    SolvedLeafStore,
)


CAMPAIGN_SCHEMA_VERSION = 3
CAMPAIGN_CHECKPOINT_SCHEMA_VERSION = 9
_LEGACY_CAMPAIGN_CHECKPOINT_SCHEMA_VERSION = 3
_HISTORICAL_CAMPAIGN_CHECKPOINT_SCHEMA_VERSIONS = frozenset({3, 4, 5, 6, 7, 8})
_SCHEMA8_PRECISION_CONTRACT_SHA256 = (
    "6aed848e453a4a4b81331e857982447631d152a43521b9397dec250a42e5cb7b"
)
_SCHEMA7_CAMPAIGN_ID = (
    "b-prime-campaign-0e93d89e98650d1e2db109d41ca0b68919067f6627ccd320fddc1e83f4720024"
)
_SCHEMA7_CAMPAIGN_SOURCE_SHA256 = (
    "504133318d896d436f92399dd8ea95424bbac3889fa8043ba3ed89bfab65d968"
)
_SCHEMA7_ENGINE_SOURCE_SHA256 = (
    "6bc9938b91d7de59669574b89b58a6bec8335d48f8b0678815350b0fba977be4"
)
_SCHEMA7_PRECISION_CONTRACT_SHA256 = (
    "3f6364f6fc28eebeeb788af20524f8ada3c97f23e41fb68f4ead3da365368dcb"
)
_SCHEMA7_ORDERED_LEAF_SET_SHA256 = (
    "b84cbba359285dae8f283d11dff1c5ff63f4e7a03c5b77f5f0ebc09703016599"
)
_SCHEMA7_ROOT_SET_SHA256 = (
    "477a3bcb8d629ba890bbb320723e365743685bdb89f23382d5ce22fbbbcc0a3f"
)
_SCHEMA7_POLICY_SHA256 = (
    "2d7cee336c6126a11bccd652ee35e73de60837e9418476849b9026cd27bf6171"
)
_SCHEMA7_BACKEND_IDENTITY_SHA256 = (
    "035f123f04d02079c6e7d7bed5255069c6152d53be266185b303af8c48c36f5c"
)
_SCHEMA7_PRECISION_CAPABILITIES_SHA256 = (
    "7b4eda35c340dc53cf8a11bd5c657cddb1b04faa55a991ea874a13be6ee09b78"
)
_SCHEMA7_COHORT_SET_SHA256 = (
    "ec538cf3ae5a11b4a16808e779a5721dc713ea9e1c67e6d94bdd248815d5f421"
)
_PROMOTION_DECISION_CHECKPOINT_SCHEMA_VERSION = 6
_FAILED_PREFLIGHT_CHECKPOINT_SCHEMA_VERSION = 6
_PRECISION_DIGITS = frozenset({64, 80, 120})
_FAILED_PREFLIGHT_COMPARISON_KIND = (
    "same-precision-120-base-vs-refinement/v1"
)
_FAILED_PREFLIGHT_SINGLE_HORIZON_KIND = (
    "single-promoted-horizon-root-after-80-preflight/v1"
)
_FAILED_PREFLIGHT_FIXED_ROOT_EXTERIOR_KIND = (
    "failed-preflight-120-fixed-root-exterior-derivative/v1"
)
_FIXED_ROOT_EXTERIOR_SELF_REFINEMENT_SKIPPED_REASON = (
    "NOT_REQUIRED_BY_FIXED_ROOT_DERIVATIVE_POLICY"
)
_BINARY64_RESPONSE_UNAVAILABLE_REASON = (
    "BINARY64_COMPONENT_RESPONSE_UNAVAILABLE"
)
_PREVIOUS_PROMOTED_RESPONSE_UNAVAILABLE_REASON = (
    "PREVIOUS_PROMOTED_COMPONENT_RESPONSE_UNAVAILABLE"
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
        "contract_version": 2,
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
    repeat_applicable: bool = True,
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
    applicability = result.error_channel_applicability
    not_applicable = {
        family
        for family, channel in family_sources.items()
        if channel is not None and not applicability[channel]
    }
    identityless_fixed_readout_failure = (
        component_result.get("evidence_kind")
        in {
            _ANALYTIC_HORIZON_EVIDENCE_KIND,
            _FIXED_ROOT_EXTERIOR_EVIDENCE_KIND,
        }
        and result.component_scientific_identity is None
        and result.status in _TYPED_FIXED_READOUT_FAILURE_STATUSES
    )
    if identityless_fixed_readout_failure:
        # A baseline-only fixed-readout failure did not execute any response
        # uncertainty phase.  ComponentResult's legacy unresolved defaults mark
        # the six channels applicable, so override that transport default here
        # instead of recording fabricated applicable zeroes.
        not_applicable.update(
            family for family, channel in family_sources.items()
            if channel is not None
        )
    if not repeat_applicable:
        not_applicable.add("repeat-polish")
    if not precision_ladder_applicable:
        not_applicable.add("precision-ladder-discrepancy")
    for family in not_applicable:
        deltas[family] = 0.0j
    return explicit_stage_signed_error_channels(
        component_result,
        family_deltas=deltas,
        source_kind="authenticated-component-error-channel",
        source_id=result.job_id,
        units="M-delta-omega-per-native-coordinate",
        not_applicable_families=frozenset(not_applicable),
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
_RETRYABLE_NUMERICAL_CONTROL_FAILURE_CODES = frozenset({
    "INSUFFICIENT_ASYMPTOTIC_PRECISION",
    "HORIZON_ARITHMETIC_INADEQUATE",
})


def _validated_attempt_failure_receipt(
    value: object,
    *,
    checkpoint_schema_version: int = CAMPAIGN_CHECKPOINT_SCHEMA_VERSION,
) -> dict[str, object]:
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
        is not (code in _RETRYABLE_NUMERICAL_CONTROL_FAILURE_CODES)
        or not _valid_numerical_control_diagnostics(
            failure,
            allow_historical_schema7_policy=(
                checkpoint_schema_version == 7
            ),
        )
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
        "coordinate_stall_rhs_threshold",
        "coordinate_stall_minimum_span_fraction",
        "coordinate_stall_minimum_step_fraction",
    }
    legacy_full_policy_fields = full_policy_fields - {
        "coordinate_stall_rhs_threshold",
        "coordinate_stall_minimum_span_fraction",
        "coordinate_stall_minimum_step_fraction",
    }
    resource_policy_fields = frozenset(resource_policy) if isinstance(
        resource_policy, Mapping
    ) else frozenset()
    if (
        not isinstance(resource_policy, Mapping)
        or resource_policy_fields
        not in {
            frozenset(identity_fields),
            frozenset(legacy_full_policy_fields),
            frozenset(full_policy_fields),
        }
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
    if resource_policy_fields in {
        frozenset(legacy_full_policy_fields),
        frozenset(full_policy_fields),
    }:
        integer_limits = [
            "worker_request_wall_clock_seconds",
            "cooperative_request_deadline_seconds",
            "homogeneous_ode_maxiters",
            "max_accepted_steps_per_homogeneous_leg",
            "max_rhs_evaluations_per_homogeneous_leg",
        ]
        if resource_policy_fields == full_policy_fields:
            integer_limits.append("coordinate_stall_rhs_threshold")
        for name in integer_limits:
            item = resource_policy[name]
            if isinstance(item, bool) or not isinstance(item, int) or item < 1:
                raise ValueError(
                    "campaign execution attempt resource-policy limit is invalid"
                )
        if resource_policy_fields == full_policy_fields:
            for name in (
                "coordinate_stall_minimum_span_fraction",
                "coordinate_stall_minimum_step_fraction",
            ):
                fraction = resource_policy[name]
                if not isinstance(fraction, str):
                    raise ValueError(
                        "campaign execution attempt resource-policy stall "
                        "fraction is invalid"
                    )
                try:
                    parsed = float(fraction)
                except ValueError as error:
                    raise ValueError(
                        "campaign execution attempt resource-policy stall "
                        "fraction is invalid"
                    ) from error
                if not 0.0 < parsed < 1.0:
                    raise ValueError(
                        "campaign execution attempt resource-policy stall "
                        "fraction is invalid"
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
    _checkpoint_schema_version: int = field(
        default=CAMPAIGN_CHECKPOINT_SCHEMA_VERSION,
        compare=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        if self.attempt_ordinal < 1 or self.leaf_index < 1:
            raise ValueError("campaign execution attempt ordinal is invalid")
        if self.precision_digits not in {80, 120}:
            raise ValueError("campaign execution attempt precision is invalid")
        if self.failure_code not in _CONTAINABLE_FAILURE_CODES:
            raise ValueError("campaign execution attempt failure code is invalid")
        if self.state != _CONTAINABLE_FAILURE_STATES[self.failure_code]:
            raise ValueError("campaign execution attempt state is invalid")
        receipt = _validated_attempt_failure_receipt(
            self.failure_receipt,
            checkpoint_schema_version=self._checkpoint_schema_version,
        )
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
            _validated_promotion_decision(
                raw_decision,
                allow_historical=(
                    self._checkpoint_schema_version
                    < CAMPAIGN_CHECKPOINT_SCHEMA_VERSION
                ),
            )
            != expected_decision
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
    def from_mapping(
        cls,
        value: object,
        *,
        checkpoint_schema_version: int = CAMPAIGN_CHECKPOINT_SCHEMA_VERSION,
    ) -> "CampaignExecutionAttempt":
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
            _checkpoint_schema_version=checkpoint_schema_version,
        )
        if value["attempt_sha256"] != attempt.attempt_sha256:
            raise ValueError("campaign execution attempt digest is invalid")
        return attempt


def _schema7_precision_policy(
    job: ResponseComponentJob,
    digits: int,
    refinement: int,
) -> dict[str, object]:
    """Reconstruct the exact promoted policy emitted by checkpoint schema 7."""

    level = "base" if refinement == 0 else "refinement"
    regularised = dict(regularised_gsn_precision_policy(job.mechanism_id))
    regularised["promoted_root_readout_policy"] = (
        HISTORICAL_PROMOTED_ROOT_READOUT_POLICY
    )
    return {
        "readout_radius": format(job.policy.readout_radius, ".17g"),
        **promoted_precision_numerical_controls()[str(digits)][level],
        **horizon_geometry_controls(),
        # Frozen schema-7 wire bytes predate the mechanism-owned split.
        "determinant_error_safety_factor": "64",
        **regularised,
        "endpoint_series_order": job.policy.endpoint_series_order + 8 * refinement,
        "support_subinterval_count": (
            job.policy.support_subinterval_count * (2 ** refinement)
        ),
        "angular_pad": 18 + 8 * refinement,
        "rho_in": "-5000",
        "rho_out": "5000",
        "branch_enclosure_radius_abs": format(
            _mode_specific_branch_enclosure_radius(job), ".17g"
        ),
        "max_newton_iterations": 16,
    }


def _schema7_julia_root_request(
    job: ResponseComponentJob,
    digits: int,
    refinement: int,
    amplitude: complex,
    predictor: complex | None,
    predictor_kind: str | None,
) -> dict[str, object]:
    """Reconstruct an origin/main schema-7 request byte-for-byte."""

    request: dict[str, object] = {
        "schema_version": 1,
        "operation": "root-readout",
        "job_id": job.job_id,
        "leaf_id": job.leaf_id,
        "role": job.role,
        "job_policy_sha256": job.policy.identity_sha256,
        "backend_identity_sha256": job.backend_identity.identity_sha256,
        "refinement_level": refinement,
        "mode": {
            "s": job.mode.s,
            "ell": job.mode.ell,
            "m": job.mode.m,
            "n": job.mode.n,
        },
        "spin": format(job.spin, ".17g"),
        "omega": {
            "real": format(job.root.omega.real, ".17g"),
            "imaginary": format(job.root.omega.imag, ".17g"),
        },
        "angular_A": {
            "real": format(
                job.root.angular_separation_constant.real, ".17g"
            ),
            "imaginary": format(
                job.root.angular_separation_constant.imag, ".17g"
            ),
        },
        "mechanism_id": job.mechanism_id,
        "amplitude": {
            "real": format(complex(amplitude).real, ".17g"),
            "imaginary": format(complex(amplitude).imag, ".17g"),
        },
        "precision_digits": digits,
        "working_precision_bits": math.ceil(digits * math.log2(10)) + 32,
        "policy": _schema7_precision_policy(job, digits, refinement),
        "execution_resource": _execution_resource_policy(),
    }
    if predictor is not None:
        request["primary_predictor"] = {
            "real": format(predictor.real, ".17g"),
            "imaginary": format(predictor.imag, ".17g"),
        }
        if predictor_kind is not None:
            request["primary_predictor_kind"] = predictor_kind
    if job.mechanism_id != "horizon-admittance":
        support = _exterior_support(job.spin, job.mechanism_id)
        request["support"] = {
            name: format(value, ".17g")
            for name, value in support.to_mapping().items()
        }
    return request


def _validate_failed_preflight_attempt_request(
    attempt: CampaignExecutionAttempt,
    leaf: CampaignLeafPlan,
    *,
    precision_digits: int,
    allowed_refinement_levels: frozenset[int],
    required_failure_code: str | None,
    checkpoint_schema_version: int = CAMPAIGN_CHECKPOINT_SCHEMA_VERSION,
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
        dedicated_baseline_predictor = (
            precision_digits in (80, 120)
            and refinement_level == 0
            and amplitude_value == 0.0j
            and predictor_kind is None
        )
        if (
            not isinstance(raw_predictor, Mapping)
            or set(raw_predictor) != {"real", "imaginary"}
            or (
                not dedicated_baseline_predictor
                and predictor_kind not in {
                    "EPSILON_CONTINUATION", "SPIN_CONTINUATION"
                }
            )
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
    if checkpoint_schema_version == 7:
        expected_request = _schema7_julia_root_request(
            leaf.job,
            precision_digits,
            refinement_level,
            amplitude_value,
            predictor_value,
            predictor_kind,
        )
    else:
        request_policy = request_binding.get("policy")
        request_budget = (
            request_policy.get("ode_error_budget")
            if isinstance(request_policy, Mapping)
            else None
        )
        validated_budget = _ode_error_budget_from_mapping(request_budget)
        if validated_budget is not None:
            expected_request = _CanonicalRequestJuliaPrecisionRootBackend(
                leaf.job.backend_identity,
                object(),
                precision_digits,
                refinement=refinement_level,
                ode_error_budget=validated_budget,
            )._request(
                leaf.job,
                amplitude_value,
                predictor_value,
                predictor_kind,
            )
        elif isinstance(request_policy, Mapping):
            receipt = load_default_calibration_receipt()
            family = (
                "horizon-scattering/v1"
                if leaf.mechanism_id == "horizon-admittance"
                else "exterior-wronskian/v1"
            )
            profile = receipt.budget_for(family, precision_digits)
            profile_mapping = profile.to_mapping()
            if (
                request_policy.get(
                    "promoted_control_calibration_receipt_sha256"
                )
                != receipt.sha256
                or request_policy.get("empirical_control_profile_sha256")
                != _sha256(profile_mapping)
            ):
                raise ValueError(
                    "failed-preflight empirical control binding is invalid"
                )
            expected_request = _CanonicalRequestJuliaPrecisionRootBackend(
                leaf.job.backend_identity,
                object(),
                precision_digits,
                refinement=refinement_level,
                empirical_control_profile=profile,
                calibration_receipt=receipt,
            )._request(
                leaf.job,
                amplitude_value,
                predictor_value,
                predictor_kind,
            )
        else:
            raise ValueError("failed-preflight request ODE budget is invalid")
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
    elif _validated_promotion_decision(
        decision,
        allow_historical=(
            checkpoint_schema_version < CAMPAIGN_CHECKPOINT_SCHEMA_VERSION
        ),
    ) != expected_decision:
        raise ValueError("failed-preflight promotion decision is invalid")


def _validate_failed_preflight_predecessor(
    attempt: CampaignExecutionAttempt,
    leaf: CampaignLeafPlan,
    *,
    checkpoint_schema_version: int = CAMPAIGN_CHECKPOINT_SCHEMA_VERSION,
) -> None:
    """Authenticate the sole 80-digit control predecessor for recovery."""

    _validate_failed_preflight_attempt_request(
        attempt,
        leaf,
        precision_digits=80,
        allowed_refinement_levels=frozenset({0}),
        required_failure_code="INSUFFICIENT_ASYMPTOTIC_PRECISION",
        checkpoint_schema_version=checkpoint_schema_version,
    )


def _failed_preflight_primary_root_predictor(
    attempt: CampaignExecutionAttempt,
) -> complex:
    """Recover the binary64 baseline predictor bound into the failed request."""

    failure = attempt.failure_receipt.get("failure")
    request = (
        None if not isinstance(failure, Mapping) else failure.get("request_binding")
    )
    raw = None if not isinstance(request, Mapping) else request.get(
        "primary_predictor"
    )
    if not isinstance(raw, Mapping) or set(raw) != {"real", "imaginary"}:
        raise ValueError(
            "failed-preflight promoted horizon predictor evidence is missing"
        )
    try:
        predictor = complex(
            float(Decimal(raw["real"])),
            float(Decimal(raw["imaginary"])),
        )
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError(
            "failed-preflight promoted horizon predictor evidence is invalid"
        ) from error
    if not math.isfinite(predictor.real) or not math.isfinite(predictor.imag):
        raise ValueError(
            "failed-preflight promoted horizon predictor evidence is invalid"
        )
    return predictor


def _failed_preflight_exterior_root_predictor(
    attempt: CampaignExecutionAttempt,
) -> complex:
    """Recover the exact predictor or authenticated request root for exterior."""

    failure = attempt.failure_receipt.get("failure")
    request = (
        None if not isinstance(failure, Mapping) else failure.get("request_binding")
    )
    if not isinstance(request, Mapping):
        raise ValueError("failed-preflight exterior request evidence is missing")
    raw = request.get("primary_predictor", request.get("omega"))
    if not isinstance(raw, Mapping) or set(raw) != {"real", "imaginary"}:
        raise ValueError("failed-preflight exterior predictor evidence is missing")
    try:
        predictor = complex(float(Decimal(raw["real"])), float(Decimal(raw["imaginary"])))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError("failed-preflight exterior predictor evidence is invalid") from error
    if not (math.isfinite(predictor.real) and math.isfinite(predictor.imag)):
        raise ValueError("failed-preflight exterior predictor evidence is invalid")
    return predictor


def _validate_failed_preflight_recovery_failure(
    attempt: CampaignExecutionAttempt,
    leaf: CampaignLeafPlan,
    *,
    checkpoint_schema_version: int = CAMPAIGN_CHECKPOINT_SCHEMA_VERSION,
) -> None:
    """Authenticate a contained failure from either 120-digit recovery pass."""

    _validate_failed_preflight_attempt_request(
        attempt,
        leaf,
        precision_digits=120,
        allowed_refinement_levels=frozenset({0, 1}),
        required_failure_code=None,
        checkpoint_schema_version=checkpoint_schema_version,
    )


def _failed_preflight_predecessor_for_leaf(
    attempts: Sequence[CampaignExecutionAttempt],
    leaf: CampaignLeafPlan,
    *,
    checkpoint_schema_version: int = CAMPAIGN_CHECKPOINT_SCHEMA_VERSION,
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
    _validate_failed_preflight_predecessor(
        candidates[0],
        leaf,
        checkpoint_schema_version=checkpoint_schema_version,
    )
    return candidates[0]


def _endpoint_arithmetic_predecessor_for_leaf(
    attempts: Sequence[CampaignExecutionAttempt],
    leaf: CampaignLeafPlan,
    *,
    checkpoint_schema_version: int = CAMPAIGN_CHECKPOINT_SCHEMA_VERSION,
) -> CampaignExecutionAttempt | None:
    candidates = tuple(
        attempt
        for attempt in attempts
        if (
            attempt.leaf_id == leaf.leaf_id
            and attempt.precision_digits == 80
            and attempt.failure_code == "HORIZON_ARITHMETIC_INADEQUATE"
        )
    )
    if len(candidates) > 1:
        raise ValueError("campaign has duplicate endpoint-arithmetic predecessors")
    if not candidates:
        return None
    _validate_endpoint_arithmetic_predecessor(
        candidates[0],
        leaf,
        checkpoint_schema_version=checkpoint_schema_version,
    )
    return candidates[0]


def _validate_endpoint_arithmetic_predecessor(
    attempt: CampaignExecutionAttempt,
    leaf: CampaignLeafPlan,
    *,
    checkpoint_schema_version: int = CAMPAIGN_CHECKPOINT_SCHEMA_VERSION,
) -> None:
    """Authenticate an 80-digit endpoint arithmetic retry predecessor."""

    _validate_failed_preflight_attempt_request(
        attempt,
        leaf,
        precision_digits=80,
        allowed_refinement_levels=frozenset({0}),
        required_failure_code="HORIZON_ARITHMETIC_INADEQUATE",
        checkpoint_schema_version=checkpoint_schema_version,
    )


def _failed_preflight_recovery_failure_for_leaf(
    attempts: Sequence[CampaignExecutionAttempt],
    leaf: CampaignLeafPlan,
    *,
    checkpoint_schema_version: int = CAMPAIGN_CHECKPOINT_SCHEMA_VERSION,
) -> CampaignExecutionAttempt | None:
    """Return a durable failed 120-digit recovery, if one was recorded."""

    predecessor = _failed_preflight_predecessor_for_leaf(
        attempts,
        leaf,
        checkpoint_schema_version=checkpoint_schema_version,
    )
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
    _validate_failed_preflight_recovery_failure(
        candidates[0],
        leaf,
        checkpoint_schema_version=checkpoint_schema_version,
    )
    return candidates[0]


def _ordinary_fixed_readout_precision120_failure_for_leaf(
    attempts: Sequence[CampaignExecutionAttempt],
    leaf: CampaignLeafPlan,
    record: CampaignLeafRecord,
    *,
    checkpoint_schema_version: int = CAMPAIGN_CHECKPOINT_SCHEMA_VERSION,
) -> CampaignExecutionAttempt | None:
    """Return one durable max-precision failure after an admitted 80 stage."""

    stages = tuple(stage.outcome for stage in record.stages)
    if tuple(stage.digits for stage in stages) != (64, 80):
        return None
    if stages[1].component_result.get("evidence_kind") not in {
        _ANALYTIC_HORIZON_EVIDENCE_KIND,
        _FIXED_ROOT_EXTERIOR_EVIDENCE_KIND,
    }:
        return None
    semantics = _promoted_stage_semantics(
        stages[1], predecessor=stages[0]
    )
    if semantics.kind not in {
        _PromotedStageKind.ANALYTIC_HORIZON,
        _PromotedStageKind.FIXED_ROOT_EXTERIOR_DERIVATIVE,
    }:
        return None
    candidates = tuple(
        attempt
        for attempt in attempts
        if attempt.leaf_id == leaf.leaf_id
        and attempt.precision_digits == 120
    )
    if len(candidates) > 1:
        raise ValueError(
            "campaign has duplicate ordinary 120-digit failures"
        )
    if not candidates:
        return None
    _validate_failed_preflight_attempt_request(
        candidates[0],
        leaf,
        precision_digits=120,
        allowed_refinement_levels=frozenset({0}),
        required_failure_code=None,
        checkpoint_schema_version=checkpoint_schema_version,
    )
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


def _multi_readout_failed_preflight_recovery_precision_contract(
) -> dict[str, object]:
    """Return the exact paired recovery contract from checkpoint schema 6."""

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


def _failed_preflight_recovery_precision_contract() -> dict[str, object]:
    """Bind recovery, with the primary horizon single-readout override."""

    return {
        **_multi_readout_failed_preflight_recovery_precision_contract(),
        "primary_horizon_override": {
            "component_scientific_identity": (
                PROMOTED_HORIZON_COMPONENT_V2_IDENTITY
            ),
            "base_refinement_levels": [0],
            "amplitude_readout_count": 1,
            "self_refinement_required": False,
            "precision_ladder_discrepancy_applicable": False,
            "terminal_gate": (
                "root-phases-branch-and-conditioning-adequate"
            ),
        },
        "exterior_override": _exterior_derivative_component_contract(),
    }


def _mechanism_failed_preflight_recovery_precision_contract(
    mechanism_id: str,
) -> dict[str, object]:
    """Bind a deep leaf only to the promoted component it can execute."""

    contract = _failed_preflight_recovery_precision_contract()
    if mechanism_id == "horizon-admittance":
        contract.pop("exterior_override")
    else:
        contract.pop("primary_horizon_override")
    return contract


def _primary_recovery_precision_contract() -> dict[str, object]:
    """Return the canonical PRIMARY promoted-precision policy fragment."""

    from .julia_response_backend import promoted_precision_numerical_controls

    return {
        **_previous_primary_recovery_precision_contract(),
        "promoted_numerical_controls": promoted_precision_numerical_controls(),
        "promoted_horizon_component": {
            "component_scientific_identity": (
                PROMOTED_HORIZON_COMPONENT_V2_IDENTITY
            ),
            "response_method": PROMOTED_HORIZON_RESPONSE_METHOD_V2,
            "amplitude_readout_count": 1,
            "amplitudes": [
                {"real": 0.0, "imaginary": 0.0},
            ],
            "finite_amplitude_readout_count": 0,
            "self_refinement_required": False,
            "primary_root_predictor": "previous-stage-baseline-omega",
            "response_uncertainty_status": (
                BOUNDED_ANALYTIC_RESPONSE
            ),
        },
        "precision120_gates": {
            "root_not_converged": True,
            "primary_rejected": True,
            "truncation_rejected": True,
            "resolution_rejected": True,
            "branch_invalid": True,
            "conditioning_precision_limited": True,
            "required_reliable_digits_not_met": True,
            "typed_retryable_control_failure": True,
            "self_refinement_required": False,
            "response_discrepancy_required": False,
        },
        "precision120_terminal_success": {
            "component_status": ComponentStatus.CONVERGED.value,
            "primary_accepted": True,
            "truncation_accepted": True,
            "resolution_accepted": True,
            "branch_valid": True,
            "conditioning_precision_limited": False,
            "required_reliable_digits_met": True,
        },
        "failed_preflight_alternate": (
            _failed_preflight_recovery_precision_contract()
        ),
    }


def _multi_readout_primary_recovery_precision_contract() -> dict[str, object]:
    """Return the exact PRIMARY contract before the single-readout component."""

    from .julia_response_backend import promoted_precision_numerical_controls

    return {
        **_previous_primary_recovery_precision_contract(),
        "promoted_numerical_controls": promoted_precision_numerical_controls(),
        "failed_preflight_alternate": (
            _multi_readout_failed_preflight_recovery_precision_contract()
        ),
    }


def _exterior_derivative_component_contract() -> dict[str, object]:
    return {
            "component_scientific_identity": (
                EXTERIOR_DERIVATIVE_COMPONENT_IDENTITY
            ),
            "response_method": EXTERIOR_DERIVATIVE_METHOD,
            "response_uncertainty_status": BOUNDED_DERIVATIVE_RESPONSE,
            "response_disk": EXTERIOR_DERIVATIVE_RESPONSE_DISK_IDENTITY,
            "derivative_conditioning": (
                FIXED_ROOT_DERIVATIVE_CONDITIONING_IDENTITY
            ),
            "axis_validation": FIXED_ROOT_AXIS_VALIDATION_IDENTITY,
            "full_validation": FULL_COMPLEX_LADDER_VALIDATION_IDENTITY,
            "perturbed_root_ladder_required": False,
    }


def _exterior_derivative_primary_recovery_precision_contract() -> dict[str, object]:
    """Bind promoted exterior work to fixed-root derivative evidence."""

    from .julia_response_backend import promoted_precision_numerical_controls

    return {
        **_previous_primary_recovery_precision_contract(),
        "promoted_numerical_controls": promoted_precision_numerical_controls(),
        "promoted_exterior_component": (
            _exterior_derivative_component_contract()
        ),
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
        "version": 2,
        "metric": "abs-determinant-over-abs-complex-derivative/v1",
        "definition": "abs_D_over_abs_complex_PRIMARY_Dprime",
        "tolerance_abs": _BINARY64_ROOT_CORRECTION_TOLERANCE_ABS,
        "precision_tiers": ["binary64", "julia80", "julia120"],
        "derivative_requirement": "finite_strictly_positive",
        "promoted": {
            "policy_id": PROMOTED_ROOT_READOUT_POLICY,
            "required_phases": [
                "PRIMARY",
                "TRUNCATION",
                "RESOLUTION",
            ],
            "primary_post_newton_determinant_count": 0,
            "truncation_determinant_count": 1,
            "resolution_determinant_count": 1,
            "fixed_root_diagnostics_reuse_complex_primary_derivative": True,
            "seed_path_required": False,
        },
        "binary64_required_phases": [
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
        "version": 5,
        "promoted_root_readout_policy": PROMOTED_ROOT_READOUT_POLICY,
        "promoted_primary_horizon_component_identity": (
            PROMOTED_HORIZON_COMPONENT_V2_IDENTITY
        ),
        "promoted_primary_horizon_response_method": (
            PROMOTED_HORIZON_RESPONSE_METHOD_V2
        ),
        "promoted_primary_horizon_finite_amplitude_ladder": (
            "not-required-not-executed"
        ),
        "promoted_primary_horizon_response_uncertainty": (
            BOUNDED_ANALYTIC_RESPONSE
        ),
        "promoted_exterior_component_identity": (
            EXTERIOR_DERIVATIVE_COMPONENT_IDENTITY
        ),
        "promoted_exterior_response_method": EXTERIOR_DERIVATIVE_METHOD,
        "promoted_exterior_response_uncertainty": BOUNDED_DERIVATIVE_RESPONSE,
        "promoted_exterior_response_disk": (
            EXTERIOR_DERIVATIVE_RESPONSE_DISK_IDENTITY
        ),
        "promoted_exterior_derivative_conditioning": (
            FIXED_ROOT_DERIVATIVE_CONDITIONING_IDENTITY
        ),
        "promoted_exterior_axis_validation": FIXED_ROOT_AXIS_VALIDATION_IDENTITY,
        "promoted_exterior_full_validation": (
            FULL_COMPLEX_LADDER_VALIDATION_IDENTITY
        ),
        "primary_disk": "combined_signed_secant_two_finest_level_richardson",
        "diagnostic_phases": {
            "binary64": ["TRUNCATION", "RESOLUTION", "SEED-PATH"],
            "promoted": ["TRUNCATION", "RESOLUTION"],
        },
        "diagnostic_disk": "signed_phase_secants_two_finest_level_richardson",
        "containment_increment": (
            "max_axis_of_max_zero_control_distance_plus_control_radius_"
            "minus_primary_combined_radius"
        ),
        "baseline_diagnostic_displacement_excluded": True,
        "promoted_seed_path": "omitted-not-required",
        "promoted_seed_path_error_channel": (
            "explicitly-not-applicable"
        ),
        "root_space_displacements": "branch_continuation_only",
        "units": "dimensionless_response",
    }


def _schema7_failed_preflight_recovery_precision_contract() -> dict[str, object]:
    contract = _failed_preflight_recovery_precision_contract()
    contract.pop("exterior_override")
    override = dict(contract["primary_horizon_override"])
    override["component_scientific_identity"] = (
        PROMOTED_HORIZON_COMPONENT_IDENTITY
    )
    contract["primary_horizon_override"] = override
    return contract


def _schema7_primary_recovery_precision_contract() -> dict[str, object]:
    contract = _primary_recovery_precision_contract()
    horizon = dict(contract["promoted_horizon_component"])
    horizon.update({
        "component_scientific_identity": PROMOTED_HORIZON_COMPONENT_IDENTITY,
        "response_method": PROMOTED_HORIZON_RESPONSE_METHOD,
        "response_uncertainty_status": UNCALIBRATED_ANALYTIC_RESPONSE,
    })
    contract["promoted_horizon_component"] = horizon
    contract["failed_preflight_alternate"] = (
        _schema7_failed_preflight_recovery_precision_contract()
    )
    return contract


def _schema7_response_uncertainty_contract() -> dict[str, object]:
    contract = _response_uncertainty_contract()
    contract["version"] = 4
    contract["promoted_root_readout_policy"] = (
        HISTORICAL_PROMOTED_ROOT_READOUT_POLICY
    )
    contract["promoted_primary_horizon_component_identity"] = (
        PROMOTED_HORIZON_COMPONENT_IDENTITY
    )
    contract["promoted_primary_horizon_response_method"] = (
        PROMOTED_HORIZON_RESPONSE_METHOD
    )
    contract["promoted_primary_horizon_response_uncertainty"] = (
        UNCALIBRATED_ANALYTIC_RESPONSE
    )
    for name in tuple(contract):
        if name.startswith("promoted_exterior_"):
            contract.pop(name)
    return contract


def _multi_readout_response_uncertainty_contract() -> dict[str, object]:
    """Return the exact response contract from checkpoint schema 6."""

    return {
        "version": 3,
        "promoted_root_readout_policy": PROMOTED_ROOT_READOUT_POLICY,
        "primary_disk": "combined_signed_secant_two_finest_level_richardson",
        "diagnostic_phases": {
            "binary64": ["TRUNCATION", "RESOLUTION", "SEED-PATH"],
            "promoted": ["TRUNCATION", "RESOLUTION"],
        },
        "diagnostic_disk": "signed_phase_secants_two_finest_level_richardson",
        "containment_increment": (
            "max_axis_of_max_zero_control_distance_plus_control_radius_"
            "minus_primary_combined_radius"
        ),
        "baseline_diagnostic_displacement_excluded": True,
        "promoted_seed_path": "omitted-not-required",
        "promoted_seed_path_error_channel": (
            "schema-retained-zero-not-applicable"
        ),
        "root_space_displacements": "branch_continuation_only",
        "units": "dimensionless_response",
    }


def _previous_response_uncertainty_contract() -> dict[str, object]:
    """Return the exact uncertainty contract used by predecessor receipts."""

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
        contract["primary_recovery"] = (
            _primary_recovery_precision_contract()
            if leaf.mechanism_id == "horizon-admittance"
            else _exterior_derivative_primary_recovery_precision_contract()
        )
    elif leaf.role == "deep":
        contract["failed_preflight_recovery"] = (
            _mechanism_failed_preflight_recovery_precision_contract(
                leaf.mechanism_id
            )
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
    *,
    response_uncertainty_contract: Mapping[str, object] | None = None,
) -> dict[str, object]:
    material: dict[str, object] = {
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
        "response_uncertainty_contract": (
            (
                _response_uncertainty_contract()
                if leaf.role in {"primary", "deep"}
                else _multi_readout_response_uncertainty_contract()
            )
            if response_uncertainty_contract is None
            else dict(response_uncertainty_contract)
        ),
    }
    if leaf.mechanism_id != "horizon-admittance":
        material["exterior_support"] = {
            "policy_identity": EXTERIOR_SUPPORT_POLICY_ID,
            "realised_mapping": _exterior_support(
                leaf.job.spin, leaf.mechanism_id
            ).to_mapping(),
        }
    return material


def scientific_computation_identity_sha256(
    plan: CampaignPlan,
    leaf: CampaignLeafPlan,
    *,
    scientific_execution_contract: Mapping[str, object] | None = None,
) -> str:
    """Bind one requested calculation without binding campaign presentation code."""

    if leaf.leaf_id not in {item.leaf_id for item in plan.leaves}:
        raise ValueError("solved-leaf scientific identity is outside the campaign plan")
    material = _scientific_computation_identity_material(
        plan, leaf, _leaf_precision_contract(leaf)
    )
    if scientific_execution_contract is not None:
        try:
            canonical_contract = json.loads(
                canonical_json_bytes(dict(scientific_execution_contract))
            )
        except (TypeError, ValueError) as error:
            raise ValueError(
                "solved-leaf scientific execution contract is invalid"
            ) from error
        if not isinstance(canonical_contract, dict):
            raise ValueError(
                "solved-leaf scientific execution contract is invalid"
            )
        material["scientific_execution_contract"] = canonical_contract
    return _sha256(material)


def _backend_scientific_execution_contract(
    backend: object,
    leaf: CampaignLeafPlan,
) -> dict[str, object] | None:
    """Return one canonical backend-owned contract for cache/reuse identity."""

    provider = getattr(backend, "scientific_execution_contract_for", None)
    if not callable(provider):
        return None
    contract = provider(leaf)
    if contract is None:
        return None
    if not isinstance(contract, Mapping):
        raise ValueError("campaign scientific execution contract is invalid")
    try:
        canonical = json.loads(canonical_json_bytes(dict(contract)))
    except (TypeError, ValueError) as error:
        raise ValueError(
            "campaign scientific execution contract is invalid"
        ) from error
    if not isinstance(canonical, dict) or canonical != dict(contract):
        raise ValueError("campaign scientific execution contract is not canonical")
    return canonical


def _legacy_primary_scientific_computation_identity_sha256(
    plan: CampaignPlan, leaf: CampaignLeafPlan
) -> str:
    """Derive the exact binary64-only PRIMARY predecessor identity."""

    if leaf.role != "primary":
        raise ValueError("legacy PRIMARY identity requires a PRIMARY leaf")
    if leaf.leaf_id not in {item.leaf_id for item in plan.leaves}:
        raise ValueError("legacy PRIMARY identity is outside the campaign plan")
    return _sha256(_scientific_computation_identity_material(
        plan,
        leaf,
        _legacy_leaf_precision_contract(leaf),
        response_uncertainty_contract=(
            _previous_response_uncertainty_contract()
        ),
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
        plan,
        leaf,
        _raw_residual_leaf_precision_contract(leaf),
        response_uncertainty_contract=(
            _previous_response_uncertainty_contract()
        ),
    ))


def _multi_readout_primary_scientific_computation_identity_sha256(
    plan: CampaignPlan,
    leaf: CampaignLeafPlan,
) -> str:
    """Derive the immediate predecessor PRIMARY multi-readout identity."""

    if leaf.role != "primary":
        raise ValueError("multi-readout identity requires a PRIMARY leaf")
    contract = _legacy_leaf_precision_contract(leaf)
    contract["primary_recovery"] = (
        _multi_readout_primary_recovery_precision_contract()
    )
    contract["root_convergence"] = _root_convergence_precision_contract()
    return _sha256(_scientific_computation_identity_material(
        plan,
        leaf,
        contract,
        response_uncertainty_contract=(
            _multi_readout_response_uncertainty_contract()
        ),
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
        _scientific_computation_identity_material(
            plan,
            leaf,
            contract,
            response_uncertainty_contract=(
                _previous_response_uncertainty_contract()
            ),
        )
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


def _schema7_precision_factory_identity() -> PrecisionFactoryIdentity:
    return PrecisionFactoryIdentity(
        "windows_solver.response_batches:NativeCampaignStageBackend.from_selection",
        _SCHEMA7_CAMPAIGN_SOURCE_SHA256,
    )


def _schema7_campaign_bindings(_plan: CampaignPlan) -> dict[str, object]:
    return {
        "schema_version": 2,
        "ordered_leaf_set_sha256": _SCHEMA7_ORDERED_LEAF_SET_SHA256,
        "root_set_sha256": _SCHEMA7_ROOT_SET_SHA256,
        "policy_sha256": _SCHEMA7_POLICY_SHA256,
        "engine_source_sha256": _SCHEMA7_ENGINE_SOURCE_SHA256,
        "campaign_source_sha256": _SCHEMA7_CAMPAIGN_SOURCE_SHA256,
        "backend_identity_sha256": _SCHEMA7_BACKEND_IDENTITY_SHA256,
        "precision_capabilities_sha256": (
            _SCHEMA7_PRECISION_CAPABILITIES_SHA256
        ),
        "precision_factory_identity": (
            _schema7_precision_factory_identity().to_mapping()
        ),
        "cohort_set_sha256": _SCHEMA7_COHORT_SET_SHA256,
    }


def _schema7_selection_mapping(
    selection: CampaignSelection,
) -> dict[str, object]:
    material = {
        "campaign_id": _SCHEMA7_CAMPAIGN_ID,
        "role": selection.role,
        "leaf_ids": list(selection.leaf_ids),
        "cohort_ids": list(selection.cohort_ids),
    }
    return {
        "selection_id": f"campaign-selection-{_sha256(material)}",
        "role": selection.role,
        "leaf_ids": list(selection.leaf_ids),
        "cohort_ids": list(selection.cohort_ids),
    }


def _schema7_checkpoint_bindings(
    plan: CampaignPlan,
    selection: CampaignSelection,
) -> dict[str, object]:
    current = _checkpoint_bindings(plan, selection)
    return {
        **current,
        "campaign_id": _SCHEMA7_CAMPAIGN_ID,
        "campaign_bindings": _schema7_campaign_bindings(plan),
        "selection": _schema7_selection_mapping(selection),
        "precision_factory_identity": (
            _schema7_precision_factory_identity().to_mapping()
        ),
        "precision_contract_sha256": _SCHEMA7_PRECISION_CONTRACT_SHA256,
    }


def _checkpoint_precision_contract_sha256(schema_version: int) -> str:
    if schema_version == 8:
        # Schema 8 used the pre-root-seal promotion contract.  It remains
        # readable only so the narrowly authenticated Leaf-42 recovery below
        # can retain its already-paid-for root evidence.
        return _SCHEMA8_PRECISION_CONTRACT_SHA256
    material: dict[str, object] = {
        "promotion_gates": list(B_PRIME_RELEASE_DOMAIN.precision_promotion_gates),
        "fixed_sentinel_leaf_ids": list(
            B_PRIME_RELEASE_DOMAIN.fixed_precision_sentinel_leaf_ids
        ),
    }
    if schema_version in {3, 4, 5}:
        historical_primary = dict(
            _multi_readout_primary_recovery_precision_contract()
        )
        historical_primary.pop("failed_preflight_alternate")
        material.update(
            {
                "primary_recovery": historical_primary,
                "response_uncertainty": (
                    _previous_response_uncertainty_contract()
                ),
            }
        )
    elif schema_version == 6:
        historical_primary = (
            _multi_readout_primary_recovery_precision_contract()
        )
        historical_primary["failed_preflight_alternate"] = (
            _multi_readout_failed_preflight_recovery_precision_contract()
        )
        material.update({
            "primary_recovery": historical_primary,
            "failed_preflight_recovery": (
                _multi_readout_failed_preflight_recovery_precision_contract()
            ),
            "response_uncertainty": (
                _multi_readout_response_uncertainty_contract()
            ),
        })
    elif schema_version == 7:
        material.update({
            "primary_recovery": _schema7_primary_recovery_precision_contract(),
            "failed_preflight_recovery": (
                _schema7_failed_preflight_recovery_precision_contract()
            ),
            "response_uncertainty": _schema7_response_uncertainty_contract(),
        })
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
    digest = _sha256(material)
    if schema_version == 7 and digest != _SCHEMA7_PRECISION_CONTRACT_SHA256:
        raise RuntimeError("frozen schema-7 precision contract drifted")
    return digest


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
    if schema_version == 7:
        return dict(bindings) == _schema7_checkpoint_bindings(plan, selection)
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
            CampaignExecutionAttempt.from_mapping(
                item, checkpoint_schema_version=version
            )
            for item in raw_attempts
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
    expected_selection_value = (
        _schema7_selection_mapping(selection)
        if value["schema_version"] == 7
        else selection.to_mapping()
    )
    if expected_selection_value != selection_value:
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
        if digits not in {
            (64,),
            (64, 80),
            (64, 120),
            (64, 80, 80),
            (64, 80, 120),
        }:
            raise ValueError("campaign checkpoint precision stage order is invalid")
        factory_identity = (
            _schema7_precision_factory_identity()
            if value["schema_version"] == 7
            else plan.precision_factory_identity
        )
        if (
            value["schema_version"] == 8
            and _schema8_leaf42_root_seal_candidate(leaf, record) is not None
        ):
            # This exact pre-root-seal response failure is migrated by the
            # active runner.  Do not reinterpret its obsolete promotion
            # decision under the new root-only decision law while loading it.
            continue
        _validate_record_semantics(
            leaf,
            record,
            factory_identity,
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
            attempts,
            leaf,
            checkpoint_schema_version=value["schema_version"],
        )
        endpoint_arithmetic = _endpoint_arithmetic_predecessor_for_leaf(
            attempts,
            leaf,
            checkpoint_schema_version=value["schema_version"],
        )
        if predecessor is not None and endpoint_arithmetic is not None:
            raise ValueError("campaign has conflicting 80-digit retry predecessors")
        pending_recovery = (
            digits == (64,)
            and record.state in {"IN_PROGRESS", "MISSING_PRECISION"}
            and (
                record.missing_precision_digits is None
                or record.missing_precision_digits == 120
            )
        )
        recovery_failure = _failed_preflight_recovery_failure_for_leaf(
            attempts,
            leaf,
            checkpoint_schema_version=value["schema_version"],
        )
        ordinary_precision120_failure = (
            _ordinary_fixed_readout_precision120_failure_for_leaf(
                attempts,
                leaf,
                record,
                checkpoint_schema_version=value["schema_version"],
            )
        )
        if predecessor is not None and not (
            pending_recovery or digits == (64, 120)
        ):
            raise ValueError(
                "failed-preflight predecessor has incompatible stage evidence"
            )
        if endpoint_arithmetic is not None and not (
            pending_recovery or digits == (64, 120)
        ):
            raise ValueError(
                "endpoint-arithmetic predecessor has incompatible stage evidence"
            )
        if (
            record.missing_precision_digits == 120
            and digits == (64,)
            and predecessor is None
            and endpoint_arithmetic is None
        ):
            raise ValueError(
                "missing 120-digit recovery lacks a failed-preflight predecessor"
            )
        if recovery_failure is not None and not pending_recovery:
            raise ValueError(
                "failed-preflight recovery failure has incompatible stage evidence"
            )
        if ordinary_precision120_failure is not None and (
            digits != (64, 80)
            or record.state
            not in {"IN_PROGRESS", "INVALID_SENTINEL_FALSE_NEGATIVE"}
            or record.missing_precision_digits is not None
        ):
            raise ValueError(
                "ordinary 120-digit failure has incompatible stage evidence"
            )
        if digits != (64, 120):
            continue
        if endpoint_arithmetic is not None:
            embedded = record.stages[-1].outcome.component_result.get(
                "endpoint_arithmetic_predecessor"
            )
            if endpoint_arithmetic.to_mapping() != embedded:
                raise ValueError(
                    "endpoint-arithmetic predecessor does not match checkpoint"
                )
        else:
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


HORIZON_SCREENING_STAGE_SCHEMA = "windows-solver.horizon-screening-stage/1"
HORIZON_PROMOTION_TRIGGER_RECEIPT_SCHEMA = (
    "windows-solver.horizon-promotion-trigger/v1"
)
HORIZON_PROMOTED_COMPARISON_RECEIPT_SCHEMA = (
    "windows-solver.promoted-horizon-survey-comparison/v1"
)
HORIZON_TRIGGER_POLICY_VERSION = "windows-solver.deep-trigger-policy/v1"
HORIZON_FIXED_SENTINEL_SET_SCHEMA = "windows-solver.fixed-sentinel-set/v1"
_SCHEMA11_NUMERICAL_RECORD = "windows-solver.schema11-numerical-record/1"


@dataclass(frozen=True, slots=True)
class HorizonPromotionDecision:
    """The sole owner of horizon trigger/sentinel promotion semantics."""

    trigger_ids: tuple[str, ...]
    sentinel: bool
    promotion_required: bool
    reason_code: str | None


def derive_horizon_promotion_decision(
    leaf: CampaignLeafPlan,
    binary64_stage: StageOutcome,
) -> HorizonPromotionDecision:
    """Derive horizon promotion only from the real leaf and binary64 stage."""

    if leaf.mechanism_id != "horizon-admittance":
        raise ValueError(
            "SYSTEM_FAILURE horizon promotion requires horizon-admittance"
        )
    if binary64_stage.digits != 64:
        raise ValueError(
            "SYSTEM_FAILURE horizon promotion requires a binary64 stage"
        )
    trigger_ids = (
        _deep_trigger_ids(binary64_stage)
        if leaf.role == "deep"
        else ()
    )
    sentinel = leaf.leaf_id in set(
        B_PRIME_RELEASE_DOMAIN.fixed_precision_sentinel_leaf_ids
    )
    promotion_required = bool(trigger_ids) or sentinel
    reason_code = (
        "DEEP_TRIGGER_AND_FIXED_SENTINEL"
        if trigger_ids and sentinel
        else "DEEP_DIAGNOSTIC_PROMOTION"
        if trigger_ids
        else "FIXED_PRECISION_SENTINEL_PROMOTION"
        if sentinel
        else None
    )
    return HorizonPromotionDecision(
        trigger_ids=trigger_ids,
        sentinel=sentinel,
        promotion_required=promotion_required,
        reason_code=reason_code,
    )


def _horizon_trigger_policy_identity() -> str:
    return _sha256({
        "schema": HORIZON_TRIGGER_POLICY_VERSION,
        "diagnostic_fields": sorted(_DEEP_DIAGNOSTIC_FIELDS),
        "promotion_gates": list(B_PRIME_RELEASE_DOMAIN.precision_promotion_gates),
    })


def _horizon_fixed_sentinel_set_identity() -> str:
    return _sha256({
        "schema": HORIZON_FIXED_SENTINEL_SET_SCHEMA,
        "leaf_ids": list(B_PRIME_RELEASE_DOMAIN.fixed_precision_sentinel_leaf_ids),
    })


def build_horizon_promotion_trigger_receipt(
    plan: CampaignPlan,
    leaf: CampaignLeafPlan,
    binary64_stage: StageOutcome,
    stage: Mapping[str, object],
) -> dict[str, object]:
    """Authenticate a recomputed horizon promotion decision."""

    decision = derive_horizon_promotion_decision(leaf, binary64_stage)
    if (
        set(stage) != {
            "schema",
            "operation_identity",
            "precision_tier",
            "component_result",
            "response_disk",
            "numerical_state",
            "stage_sha256",
        }
        or stage["schema"] != HORIZON_SCREENING_STAGE_SCHEMA
        or stage["precision_tier"] != "binary64"
    ):
        raise ValueError("horizon trigger receipt stage is invalid")
    stage_content = {
        key: value for key, value in stage.items() if key != "stage_sha256"
    }
    stage_sha256 = stage.get("stage_sha256")
    if stage_sha256 != _sha256(stage_content):
        raise ValueError("horizon trigger receipt stage digest is invalid")
    operation_identity = stage.get("operation_identity")
    if not isinstance(operation_identity, str) or not operation_identity:
        raise ValueError("horizon trigger receipt operation identity is invalid")
    staged_component_result = stage.get("component_result")
    if not isinstance(staged_component_result, Mapping):
        raise ValueError("horizon trigger receipt stage payload is invalid")
    expected_component_result = dict(binary64_stage.component_result)
    if binary64_stage.deep_diagnostics is not None:
        expected_component_result["deep_diagnostics"] = dict(
            binary64_stage.deep_diagnostics
        )
    if (
        stage.get("numerical_state") != binary64_stage.numerical_state
        or dict(staged_component_result) != expected_component_result
    ):
        raise ValueError(
            "horizon trigger receipt stage payload does not match the binary64 stage"
        )
    content = {
        "schema": HORIZON_PROMOTION_TRIGGER_RECEIPT_SCHEMA,
        "leaf_id": leaf.leaf_id,
        "scientific_computation_identity": (
            scientific_computation_identity_sha256(plan, leaf)
        ),
        "binary64_stage_sha256": stage_sha256,
        "binary64_operation_identity": operation_identity,
        "trigger_ids": list(decision.trigger_ids),
        "sentinel": decision.sentinel,
        "promotion_required": decision.promotion_required,
        "reason_code": decision.reason_code,
        "fixed_precision_sentinel_set_identity": (
            _horizon_fixed_sentinel_set_identity()
        ),
        "trigger_policy_identity": _horizon_trigger_policy_identity(),
        "trigger_policy_version": HORIZON_TRIGGER_POLICY_VERSION,
        "deep_diagnostics": (
            None
            if binary64_stage.deep_diagnostics is None
            else dict(binary64_stage.deep_diagnostics)
        ),
    }
    return {**content, "receipt_sha256": _sha256(content)}


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


# Version 2 makes the decision's meaning explicit: this document authorizes
# *root* arithmetic promotion only.  A sealed response repair has a separate
# identity and must never be smuggled through this decision.
_PROMOTION_DECISION_SCHEMA = "windows-solver.precision-promotion-decision/2"
_HISTORICAL_PROMOTION_DECISION_SCHEMA = (
    "windows-solver.precision-promotion-decision/1"
)
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


def _single_promoted_horizon_result(
    outcome: StageOutcome,
) -> ComponentResult | None:
    raw_result = outcome.component_result.get("result")
    if not isinstance(raw_result, Mapping):
        return None
    result = ComponentResult.from_mapping(raw_result)
    if result.component_scientific_identity not in {
        PROMOTED_HORIZON_COMPONENT_IDENTITY,
        PROMOTED_HORIZON_COMPONENT_V2_IDENTITY,
        PROMOTED_HORIZON_COMPONENT_V3_IDENTITY,
    }:
        return None
    if result.to_mapping() != raw_result:
        raise ValueError("promoted horizon component result is not canonical")
    return result


_SELECTIVE_STAGE_EVIDENCE_KIND = "package-owned-selective-readout-promotion"
_LEGACY_FULL_LADDER_EVIDENCE_KIND = (
    "package-owned-julia-promoted-component-engine"
)
_ANALYTIC_HORIZON_EVIDENCE_KIND = (
    "package-owned-julia-single-promoted-horizon-component"
)
_FIXED_ROOT_EXTERIOR_EVIDENCE_KIND = (
    "package-owned-julia-fixed-root-exterior-derivative-component"
)
_ROOT_SEALED_RESPONSE_REPAIR_EVIDENCE_KIND = (
    "package-owned-julia-root-sealed-response-repair"
)
_ROOT_SEAL_RESPONSE_MIGRATION_IDENTITY = (
    "root-sealed-stale-exterior-response-discarded/v1"
)
_ROOT_SEAL_RESPONSE_MIGRATION_SCHEMA = (
    "windows-solver.root-sealed-response-migration/1"
)
_SELECTIVE_TIER_SEQUENCE = (
    "bigfloat-40",
    "bigfloat-80",
    "bigfloat-120",
)
_TYPED_FIXED_READOUT_FAILURE_STATUSES = frozenset({
    ComponentStatus.BRANCH_LOSS,
    ComponentStatus.NOT_CONVERGED,
})


class _PromotedStageKind(str, Enum):
    LEGACY_FULL_LADDER = "LEGACY_FULL_LADDER"
    SELECTIVE_READOUT = "SELECTIVE_READOUT"
    ANALYTIC_HORIZON = "ANALYTIC_HORIZON"
    FIXED_ROOT_EXTERIOR_DERIVATIVE = (
        "FIXED_ROOT_EXTERIOR_DERIVATIVE"
    )


@dataclass(frozen=True, slots=True)
class _PromotedStageSemantics:
    kind: _PromotedStageKind
    result: ComponentResult
    repeat_applicable: bool
    precision_ladder_applicable: bool
    root_sealed: bool
    root_requires_precision120: bool
    response_terminal_admissible: bool
    response_requires_precision120: bool
    response_repair_precision_digits: int | None
    response_repair_families: frozenset[str]
    terminal_admissible: bool
    requires_precision120: bool


def _claims_specialized_promoted_semantics(result: ComponentResult) -> bool:
    """Return whether an identity-less result still claims a special path."""

    return (
        result.derivative_evidence is not None
        or result.analytic_horizon_evidence is not None
        or result.response_method in {
            EXTERIOR_DERIVATIVE_METHOD,
            PROMOTED_HORIZON_RESPONSE_METHOD,
            PROMOTED_HORIZON_RESPONSE_METHOD_V2,
            PROMOTED_HORIZON_RESPONSE_METHOD_V3,
        }
        or result.response_uncertainty_status in {
            BOUNDED_ANALYTIC_RESPONSE,
            "UNBOUNDED_ANALYTIC_RESPONSE",
            BOUNDED_DERIVATIVE_RESPONSE,
            "UNBOUNDED_DERIVATIVE_RESPONSE",
            UNCALIBRATED_ANALYTIC_RESPONSE,
        }
        or result.convergence_basis in {
            "PRIMARY_TRUNCATION_RESOLUTION_FIXED_ROOT",
            "FIXED_ROOT_REAL_H_H2_DERIVATIVE_DISK",
            "UNRESOLVED_FIXED_ROOT_DERIVATIVE",
        }
        or result.status is ComponentStatus.DERIVATIVE_UNRESOLVED
        or result.finite_amplitude_ladder_required is False
        or result.finite_amplitude_ladder_executed is False
    )


def _classify_promoted_stage(
    outcome: StageOutcome,
) -> tuple[_PromotedStageKind, ComponentResult]:
    """Authenticate a promoted wrapper against its component identity."""

    if outcome.digits not in (80, 120):
        raise _UnauthenticatedComponentEvidence(
            "campaign promoted stage precision is invalid"
        )
    raw_result = outcome.component_result.get("result")
    if not isinstance(raw_result, Mapping):
        raise _UnauthenticatedComponentEvidence(
            "campaign promoted stage component result is missing"
        )
    result = ComponentResult.from_mapping(raw_result)
    if result.to_mapping() != raw_result:
        raise _UnauthenticatedComponentEvidence(
            "campaign promoted stage component result is not canonical"
        )
    evidence_kind = outcome.component_result.get("evidence_kind")
    identity = result.component_scientific_identity
    specialized_identity_claim = _claims_specialized_promoted_semantics(
        result
    )

    if evidence_kind == _SELECTIVE_STAGE_EVIDENCE_KIND:
        if identity is not None or specialized_identity_claim:
            raise _UnauthenticatedComponentEvidence(
                "campaign selective evidence disagrees with component identity"
            )
        return _PromotedStageKind.SELECTIVE_READOUT, result

    analytic_identity = identity in {
        PROMOTED_HORIZON_COMPONENT_IDENTITY,
        PROMOTED_HORIZON_COMPONENT_V2_IDENTITY,
        PROMOTED_HORIZON_COMPONENT_V3_IDENTITY,
    }
    typed_analytic_failure = (
        evidence_kind == _ANALYTIC_HORIZON_EVIDENCE_KIND
        and identity is None
        and result.mechanism_id == "horizon-admittance"
        and result.status in _TYPED_FIXED_READOUT_FAILURE_STATUSES
        and not specialized_identity_claim
    )
    if analytic_identity or typed_analytic_failure:
        if evidence_kind not in {
            _ANALYTIC_HORIZON_EVIDENCE_KIND,
            _ROOT_SEALED_RESPONSE_REPAIR_EVIDENCE_KIND,
        } or (
            evidence_kind == _ROOT_SEALED_RESPONSE_REPAIR_EVIDENCE_KIND
            and identity != PROMOTED_HORIZON_COMPONENT_V3_IDENTITY
        ):
            raise _UnauthenticatedComponentEvidence(
                "campaign analytic evidence disagrees with component identity"
            )
        return _PromotedStageKind.ANALYTIC_HORIZON, result
    if evidence_kind == _ANALYTIC_HORIZON_EVIDENCE_KIND:
        raise _UnauthenticatedComponentEvidence(
            "campaign analytic evidence lacks its component identity"
        )

    if identity == EXTERIOR_DERIVATIVE_COMPONENT_IDENTITY:
        if evidence_kind not in {
            _FIXED_ROOT_EXTERIOR_EVIDENCE_KIND,
            _ROOT_SEALED_RESPONSE_REPAIR_EVIDENCE_KIND,
        }:
            raise _UnauthenticatedComponentEvidence(
                "campaign fixed-root exterior evidence kind is invalid"
            )
        return _PromotedStageKind.FIXED_ROOT_EXTERIOR_DERIVATIVE, result
    typed_exterior_failure = (
        evidence_kind == _FIXED_ROOT_EXTERIOR_EVIDENCE_KIND
        and identity is None
        and result.mechanism_id.startswith("exterior-")
        and result.status in _TYPED_FIXED_READOUT_FAILURE_STATUSES
        and not specialized_identity_claim
    )
    if typed_exterior_failure:
        return _PromotedStageKind.FIXED_ROOT_EXTERIOR_DERIVATIVE, result
    if evidence_kind == _FIXED_ROOT_EXTERIOR_EVIDENCE_KIND:
        raise _UnauthenticatedComponentEvidence(
            "campaign fixed-root exterior evidence lacks its component identity"
        )

    if (
        evidence_kind == _LEGACY_FULL_LADDER_EVIDENCE_KIND
        and identity is None
        and not specialized_identity_claim
    ):
        return _PromotedStageKind.LEGACY_FULL_LADDER, result
    raise _UnauthenticatedComponentEvidence(
        "campaign promoted stage kind is unrecognized"
    )

_SELECTIVE_TIER_JOURNAL_SCHEMA = (
    "windows-solver.selective-tier-journal-evidence/1"
)
_SELECTIVE_JOURNAL_WRAPPER_SCHEMA = (
    "windows-solver.promoted-component-journal-receipt/1"
)
_EMPIRICAL_SELECTIVE_TIER_JOURNAL_SCHEMA = (
    "windows-solver.selective-tier-journal-evidence/2"
)


@dataclass(frozen=True, slots=True)
class _EmpiricalCalibrationBindingView:
    sha256: str
    certificate_identity: str
    certificate_safety_factor: int
    profile: EmpiricalControlProfile

    def budget_for(
        self, determinant_family: str, nominal_decimal_digits: int
    ) -> EmpiricalControlProfile:
        if (
            determinant_family != self.profile.determinant_family
            or nominal_decimal_digits != self.profile.nominal_decimal_digits
        ):
            raise ValueError(
                "empirical calibration binding does not cover request"
            )
        return self.profile


def _ode_error_budget_from_mapping(value: object) -> ODEErrorBudget | None:
    if not isinstance(value, Mapping):
        return None
    try:
        budget = ODEErrorBudget(
            required_root_correction_abs=value["required_root_correction_abs"],
            determinant_derivative_lower_bound_abs=value[
                "determinant_derivative_lower_bound_abs"
            ],
            determinant_error_budget_abs=value["determinant_error_budget_abs"],
            determinant_allocations=value["determinant_allocations"],
            coordinate_reltol=value["coordinate_reltol"],
            coordinate_abstol=value["coordinate_abstol"],
            homogeneous_reltol=value["homogeneous_reltol"],
            homogeneous_abstol=value["homogeneous_abstol"],
            precision_tier=value["precision_tier"],
            calibration_identity=value["calibration_identity"],
        )
    except (KeyError, TypeError, ValueError):
        return None
    return budget if budget.to_mapping() == dict(value) else None


_SCIENTIFIC_EXECUTION_CONTRACT_SCHEMA = (
    "windows-solver.m02-scientific-execution-contract/1"
)
_EMPIRICAL_SCIENTIFIC_EXECUTION_CONTRACT_SCHEMA = (
    "windows-solver.m02-scientific-execution-contract/2"
)


def _scientific_execution_contract_budgets(
    contract: Mapping[str, object] | None,
) -> dict[int, dict[str, object]] | None:
    if contract is None or contract.get("schema") != (
        _SCIENTIFIC_EXECUTION_CONTRACT_SCHEMA
    ):
        return None
    expected_fields = {
        "schema", "ode_error_budgets_by_nominal_decimal_digits"
    }
    raw_budgets = contract.get(
        "ode_error_budgets_by_nominal_decimal_digits"
    )
    if set(contract) != expected_fields or not isinstance(raw_budgets, Mapping):
        raise ValueError("campaign scientific execution contract is invalid")
    budgets: dict[int, dict[str, object]] = {}
    for raw_digits, raw_budget in raw_budgets.items():
        if not isinstance(raw_digits, str) or raw_digits not in {
            "40", "80", "120"
        }:
            raise ValueError("campaign scientific execution budget tier is invalid")
        digits = int(raw_digits)
        budget = _ode_error_budget_from_mapping(raw_budget)
        if (
            budget is None
            or budget.to_mapping().get("nominal_decimal_digits") != digits
        ):
            raise ValueError("campaign scientific execution budget is invalid")
        budgets[digits] = budget.to_mapping()
    if not budgets:
        raise ValueError("campaign scientific execution budgets are missing")
    return budgets


def _scientific_execution_contract_empirical_profiles(
    contract: Mapping[str, object] | None,
) -> tuple[
    Mapping[str, object],
    Mapping[str, object],
    str,
    dict[int, dict[str, object]],
] | None:
    if contract is None or contract.get("schema") != (
        _EMPIRICAL_SCIENTIFIC_EXECUTION_CONTRACT_SCHEMA
    ):
        return None
    if set(contract) != {
        "schema",
        "calibration_receipt",
        "determinant_certificate",
        "determinant_family",
        "empirical_control_profiles_by_nominal_decimal_digits",
    }:
        raise ValueError("campaign scientific execution contract is invalid")
    receipt = contract.get("calibration_receipt")
    certificate = contract.get("determinant_certificate")
    family = contract.get("determinant_family")
    raw_profiles = contract.get(
        "empirical_control_profiles_by_nominal_decimal_digits"
    )
    if (
        not isinstance(receipt, Mapping)
        or set(receipt) != {
            "identity", "sha256", "execution_status", "source_audit_sha256"
        }
        or receipt.get("identity")
        != "promoted-control-empirical-calibration/v1"
        or not isinstance(receipt.get("sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", receipt["sha256"]) is None
        or not isinstance(receipt.get("execution_status"), str)
        or not receipt["execution_status"]
        or not isinstance(receipt.get("source_audit_sha256"), str)
        or re.fullmatch(
            r"[0-9a-f]{64}", receipt["source_audit_sha256"]
        ) is None
        or not isinstance(certificate, Mapping)
        or set(certificate) != {"identity", "safety_factor"}
        or certificate.get("identity")
        != "exterior-determinant-absolute-error-certificate/empirical-v1"
        or certificate.get("safety_factor") != 64
        or family not in {
            "exterior-wronskian/v1", "horizon-scattering/v1"
        }
        or not isinstance(raw_profiles, Mapping)
        or not raw_profiles
    ):
        raise ValueError("campaign scientific execution contract is invalid")
    allowed_digits = (
        {40, 80, 120}
        if family == "exterior-wronskian/v1"
        else {80, 120}
    )
    profiles: dict[int, dict[str, object]] = {}
    for raw_digits, raw_profile in raw_profiles.items():
        if (
            not isinstance(raw_digits, str)
            or not raw_digits.isdigit()
            or int(raw_digits) not in allowed_digits
            or not isinstance(raw_profile, Mapping)
            or set(raw_profile) != {
                "base_controls",
                "determinant_family",
                "nominal_decimal_digits",
                "precision_tier",
                "refinement_controls",
            }
        ):
            raise ValueError(
                "campaign empirical scientific execution profile is invalid"
            )
        digits = int(raw_digits)
        if (
            raw_profile.get("determinant_family") != family
            or raw_profile.get("nominal_decimal_digits") != digits
            or raw_profile.get("precision_tier") != f"bigfloat-{digits}"
            or not isinstance(raw_profile.get("base_controls"), Mapping)
            or not isinstance(raw_profile.get("refinement_controls"), Mapping)
        ):
            raise ValueError(
                "campaign empirical scientific execution profile is invalid"
            )
        profiles[digits] = dict(raw_profile)
    return receipt, certificate, family, profiles


class _PromotedExecutionContractMismatch(ValueError):
    """Authenticated promoted evidence belongs to another control identity."""


def _invalidate_promoted_record(
    record: CampaignLeafRecord,
) -> CampaignLeafRecord:
    """Retain binary64 evidence and restart at the first promoted tier."""

    if not any(stage.outcome.digits in {80, 120} for stage in record.stages):
        return record
    retained = tuple(
        stage for stage in record.stages if stage.outcome.digits == 64
    )
    if len(retained) != 1 or retained[0] is not record.stages[0]:
        raise ValueError(
            "campaign promoted invalidation lacks one leading binary64 stage"
        )
    return CampaignLeafRecord(
        leaf_id=record.leaf_id,
        role=record.role,
        state="IN_PROGRESS",
        stages=retained,
        trigger_ids=record.trigger_ids,
        sentinel=record.sentinel,
        missing_precision_digits=None,
        sentinel_comparison=None,
    )


def _validate_record_scientific_execution_contract(
    leaf: CampaignLeafPlan,
    record: CampaignLeafRecord,
    contract: Mapping[str, object] | None,
) -> None:
    """Reject promoted checkpoint/cache evidence from another ODE budget."""

    budgets = _scientific_execution_contract_budgets(contract)
    empirical = _scientific_execution_contract_empirical_profiles(contract)
    if budgets is None and empirical is None:
        return

    def validate_budget_evidence(value: object) -> None:
        if isinstance(value, Mapping):
            has_budget = "ode_error_budget" in value
            has_digest = "ode_error_budget_sha256" in value
            if has_budget or has_digest:
                if budgets is None:
                    raise _PromotedExecutionContractMismatch(
                        "campaign promoted ODE budget disagrees with active "
                        "scientific execution contract"
                    )
                if not has_budget:
                    raise ValueError(
                        "campaign promoted ODE budget evidence is invalid"
                    )
                raw_budget = value.get("ode_error_budget")
                budget = _ode_error_budget_from_mapping(raw_budget)
                if budget is None or not isinstance(raw_budget, Mapping):
                    raise ValueError(
                        "campaign promoted ODE budget evidence is invalid"
                    )
                mapping = budget.to_mapping()
                digits = mapping["nominal_decimal_digits"]
                expected = budgets.get(digits)
                if (
                    expected is None
                    or dict(raw_budget) != expected
                    or (
                        has_digest
                        and value.get("ode_error_budget_sha256")
                        != _sha256(expected)
                    )
                ):
                    raise _PromotedExecutionContractMismatch(
                        "campaign promoted ODE budget disagrees with active "
                        "scientific execution contract"
                    )
            for nested in value.values():
                validate_budget_evidence(nested)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                validate_budget_evidence(nested)

    for stage in record.stages:
        payload = stage.outcome.component_result
        promoted_runtimes = tuple(
            payload.get(key)
            for key in (
                "scientific_runtime", "self_refinement_scientific_runtime"
            )
            if isinstance(payload.get(key), Mapping)
            and payload[key].get("precision_digits") in {40, 80, 120}
        )
        if stage.outcome.digits in {80, 120} and not promoted_runtimes:
            raise _PromotedExecutionContractMismatch(
                "campaign promoted scientific runtime is missing from the "
                "active execution contract"
            )
        for runtime in promoted_runtimes:
            assert isinstance(runtime, Mapping)
            if empirical is not None:
                receipt, certificate, family, profiles = empirical
                digits = runtime.get("precision_digits")
                profile = runtime.get("empirical_control_profile")
                binding = runtime.get("promoted_control_calibration")
                expected_profile = (
                    profiles.get(digits) if type(digits) is int else None
                )
                expected_binding = {
                    "schema": (
                        "windows-solver.promoted-control-calibration-binding/1"
                    ),
                    "receipt_identity": receipt["identity"],
                    "receipt_sha256": receipt["sha256"],
                    "execution_status": receipt["execution_status"],
                    "source_audit_sha256": receipt["source_audit_sha256"],
                    "determinant_family": family,
                    "determinant_certificate_identity": certificate["identity"],
                    "determinant_certificate_safety_factor": (
                        certificate["safety_factor"]
                    ),
                    "derivative_floor_status": (
                        "ARCHIVED_AUTHENTICATED_LOWER_BOUND_UNAVAILABLE"
                    ),
                }
                if (
                    expected_profile is None
                    or not isinstance(profile, Mapping)
                    or dict(profile) != expected_profile
                    or runtime.get("empirical_control_profile_sha256")
                    != _sha256(expected_profile)
                    or not isinstance(binding, Mapping)
                    or dict(binding) != expected_binding
                    or "ode_error_budget" in runtime
                    or "ode_error_budget_sha256" in runtime
                ):
                    raise _PromotedExecutionContractMismatch(
                        "campaign promoted empirical controls disagree with "
                        "active scientific execution contract"
                    )
                continue
            if (
                "ode_error_budget" not in runtime
                or "ode_error_budget_sha256" not in runtime
            ):
                raise _PromotedExecutionContractMismatch(
                    "campaign promoted scientific runtime lacks its ODE budget"
                )
            runtime_budget = _ode_error_budget_from_mapping(
                runtime.get("ode_error_budget")
            )
            if (
                runtime_budget is None
                or runtime_budget.to_mapping()["nominal_decimal_digits"]
                != runtime.get("precision_digits")
            ):
                raise _PromotedExecutionContractMismatch(
                    "campaign promoted runtime ODE budget tier disagrees with "
                    "the active scientific execution contract"
                )
        validate_budget_evidence(payload)


def _validate_selective_tier_journal(
    leaf: CampaignLeafPlan,
    tier_label: str,
    plan: object,
    evidence: object,
    predecessor_readouts: Mapping[complex, RootReadout],
) -> tuple[Mapping[str, object], dict[complex, RootReadout]]:
    """Authenticate one semantic tier from canonical requests, not labels."""

    legacy_fields = {
        "schema", "configured", "component_identity", "precision_tier",
        "journal", "journal_sha256", "promoted_work_unit_ids",
        "scientific_runtime", "scientific_runtime_sha256",
        "ode_error_budget", "ode_error_budget_sha256",
    }
    empirical_fields = {
        "schema", "configured", "component_identity", "precision_tier",
        "journal", "journal_sha256", "promoted_work_unit_ids",
        "scientific_runtime", "scientific_runtime_sha256",
        "promoted_control_calibration", "empirical_control_profile",
        "empirical_control_profile_sha256",
    }
    if not isinstance(evidence, Mapping) or set(evidence) not in {
        frozenset(legacy_fields), frozenset(empirical_fields)
    }:
        raise _UnauthenticatedComponentEvidence(
            "campaign selective tier journal evidence is invalid"
        )
    tier = precision_tier(tier_label)
    digits = nominal_decimal_digits(tier)
    bits = working_precision_bits(tier)
    component_identity = (
        f"selective-signed-root-promotion-component/v1/{tier_label}"
    )
    runtime = evidence.get("scientific_runtime")
    budget = evidence.get("ode_error_budget")
    runtime_sha256 = evidence.get("scientific_runtime_sha256")
    empirical = evidence.get("schema") == (
        _EMPIRICAL_SELECTIVE_TIER_JOURNAL_SCHEMA
    )
    validated_budget: ODEErrorBudget | None = None
    empirical_profile: EmpiricalControlProfile | None = None
    empirical_receipt: _EmpiricalCalibrationBindingView | None = None
    if (
        evidence.get("configured") is not True
        or evidence.get("component_identity") != component_identity
        or evidence.get("precision_tier") != tier_label
        or not isinstance(runtime, Mapping)
        or runtime_sha256 != _sha256(dict(runtime))
        or runtime.get("precision_digits") != digits
        or runtime.get("working_precision_bits") != bits
        or runtime.get("semantic_precision_tier") != tier_label
        or runtime.get("refinement_level") != 0
        or runtime.get("regularised_gsn_precision_policy")
        != dict(regularised_gsn_precision_policy(leaf.job.mechanism_id))
    ):
        raise _UnauthenticatedComponentEvidence(
            "campaign selective tier runtime or ODE budget is invalid"
        )
    if empirical:
        raw_binding = evidence.get("promoted_control_calibration")
        raw_profile = evidence.get("empirical_control_profile")
        raw_profile_sha256 = evidence.get(
            "empirical_control_profile_sha256"
        )
        if (
            set(evidence) != empirical_fields
            or not isinstance(raw_binding, Mapping)
            or set(raw_binding) != {
                "schema",
                "receipt_identity",
                "receipt_sha256",
                "execution_status",
                "source_audit_sha256",
                "determinant_family",
                "determinant_certificate_identity",
                "determinant_certificate_safety_factor",
                "derivative_floor_status",
            }
            or raw_binding.get("schema")
            != "windows-solver.promoted-control-calibration-binding/1"
            or raw_binding.get("receipt_identity")
            != "promoted-control-empirical-calibration/v1"
            or not isinstance(raw_binding.get("receipt_sha256"), str)
            or re.fullmatch(
                r"[0-9a-f]{64}", raw_binding["receipt_sha256"]
            ) is None
            or raw_binding.get("determinant_family")
            != "exterior-wronskian/v1"
            or raw_binding.get("determinant_certificate_identity")
            != (
                "exterior-determinant-absolute-error-certificate/empirical-v1"
            )
            or raw_binding.get("determinant_certificate_safety_factor") != 64
            or raw_binding.get("derivative_floor_status")
            != "ARCHIVED_AUTHENTICATED_LOWER_BOUND_UNAVAILABLE"
            or runtime.get("promoted_control_calibration") != dict(raw_binding)
            or not isinstance(raw_profile, Mapping)
            or set(raw_profile) != {
                "base_controls",
                "determinant_family",
                "nominal_decimal_digits",
                "precision_tier",
                "refinement_controls",
            }
            or raw_profile.get("determinant_family")
            != "exterior-wronskian/v1"
            or raw_profile.get("nominal_decimal_digits") != digits
            or raw_profile.get("precision_tier") != tier_label
            or not isinstance(raw_profile.get("base_controls"), Mapping)
            or not isinstance(raw_profile.get("refinement_controls"), Mapping)
            or raw_profile_sha256 != _sha256(dict(raw_profile))
            or runtime.get("empirical_control_profile") != dict(raw_profile)
            or runtime.get("empirical_control_profile_sha256")
            != raw_profile_sha256
            or "ode_error_budget" in runtime
            or "ode_error_budget_sha256" in runtime
        ):
            raise _UnauthenticatedComponentEvidence(
                "campaign selective tier empirical calibration is invalid"
            )
        empirical_profile = EmpiricalControlProfile(
            determinant_family="exterior-wronskian/v1",
            precision_tier=tier,
            nominal_decimal_digits=digits,
            base_controls=dict(raw_profile["base_controls"]),
            refinement_controls=dict(raw_profile["refinement_controls"]),
        )
        empirical_receipt = _EmpiricalCalibrationBindingView(
            sha256=str(raw_binding["receipt_sha256"]),
            certificate_identity=str(
                raw_binding["determinant_certificate_identity"]
            ),
            certificate_safety_factor=64,
            profile=empirical_profile,
        )
    else:
        budget_sha256 = evidence.get("ode_error_budget_sha256")
        validated_budget = _ode_error_budget_from_mapping(budget)
        if (
            evidence.get("schema") != _SELECTIVE_TIER_JOURNAL_SCHEMA
            or set(evidence) != legacy_fields
            or not isinstance(budget, Mapping)
            or validated_budget is None
            or validated_budget.to_mapping() != dict(budget)
            or budget_sha256 != _sha256(dict(budget))
            or budget.get("schema") != "windows-solver.ode-error-budget/1"
            or budget.get("precision_tier") != tier_label
            or budget.get("nominal_decimal_digits") != digits
            or budget.get("working_precision_bits") != bits
            or not isinstance(budget.get("calibration_identity"), str)
            or not budget["calibration_identity"]
        ):
            raise _UnauthenticatedComponentEvidence(
                "campaign selective tier runtime or ODE budget is invalid"
            )
    raw_journal = evidence.get("journal")
    try:
        journal = PartialComponentJournal.from_mapping(raw_journal)
    except ValueError as error:
        raise _UnauthenticatedComponentEvidence(
            "campaign selective tier journal is invalid"
        ) from error
    promoted_ids = evidence.get("promoted_work_unit_ids")
    if (
        not isinstance(promoted_ids, list)
        or not promoted_ids
        or len(promoted_ids) != len(set(promoted_ids))
        or tuple(promoted_ids) != journal.expected_work_unit_ids
        or set(journal.entries) != set(promoted_ids)
        or not journal.complete
        or evidence.get("journal_sha256")
        != journal.to_mapping()["journal_sha256"]
    ):
        raise _UnauthenticatedComponentEvidence(
            "campaign selective tier journal plan is invalid"
        )
    if not isinstance(plan, list) or len(plan) != len(promoted_ids):
        raise _UnauthenticatedComponentEvidence(
            "campaign selective tier readout plan is invalid"
        )
    expected_readouts: dict[tuple[str, float], complex] = {}
    for item in plan:
        if not isinstance(item, Mapping):
            raise _UnauthenticatedComponentEvidence(
                "campaign selective tier readout plan is invalid"
            )
        role = item.get("readout_role")
        epsilon = item.get("epsilon")
        if (
            role not in {
                "real_plus", "real_minus", "imaginary_plus", "imaginary_minus"
            }
            or isinstance(epsilon, bool)
            or not isinstance(epsilon, (int, float))
            or not math.isfinite(float(epsilon))
            or float(epsilon) <= 0.0
        ):
            raise _UnauthenticatedComponentEvidence(
                "campaign selective tier readout plan is invalid"
            )
        value = float(epsilon)
        amplitude = {
            "real_plus": complex(value, 0.0),
            "real_minus": complex(-value, 0.0),
            "imaginary_plus": complex(0.0, value),
            "imaginary_minus": complex(0.0, -value),
        }[role]
        expected_readouts[(role.replace("_", "-"), value)] = amplitude
    contract = regularised_gsn_mechanism_contract(leaf.job.mechanism_id)
    observed_readouts: dict[tuple[str, float], complex] = {}
    promoted_readouts: dict[complex, RootReadout] = {}
    request_backend = JuliaPrecisionRootBackend(
        leaf.job.backend_identity,
        object(),
        digits,
        ode_error_budget=validated_budget,
        empirical_control_profile=empirical_profile,
        calibration_receipt=empirical_receipt,
    )
    for work_unit_id in promoted_ids:
        entry = journal.entries[work_unit_id]
        wrapper = entry.to_mapping()["worker_response_receipt"]
        if (
            set(wrapper) != {"schema", "kind", "output"}
            or wrapper.get("schema") != _SELECTIVE_JOURNAL_WRAPPER_SCHEMA
            or wrapper.get("kind") != "root-readout"
            or not isinstance(wrapper.get("output"), Mapping)
        ):
            raise _UnauthenticatedComponentEvidence(
                "campaign selective tier journal output wrapper is invalid"
            )
        try:
            readout = RootReadout.from_mapping(wrapper["output"])
        except ValueError as error:
            raise _UnauthenticatedComponentEvidence(
                "campaign selective tier root readout is invalid"
            ) from error
        receipt = readout.worker_response_receipt
        request = None if receipt is None else receipt.get("request_binding")
        role, _, epsilon_text = entry.readout_role.partition("@")
        observed_readouts[(role, entry.epsilon)] = entry.amplitude
        request_amplitude = (
            request.get("amplitude") if isinstance(request, Mapping) else None
        )
        predecessor = predecessor_readouts.get(entry.amplitude)
        expected_request = (
            None
            if predecessor is None
            else request_backend.preview_root_request(
                leaf.job,
                entry.amplitude,
                predecessor.omega,
                None,
                entry.readout_role,
            )
        )
        expected_request_fields = {
            "schema_version", "operation", "job_id", "leaf_id", "role",
            "job_policy_sha256", "backend_identity_sha256",
            "refinement_level", "mode", "spin", "omega", "angular_A",
            "mechanism_id", "amplitude", "precision_digits",
            "working_precision_bits", "semantic_precision_tier", "policy",
            "execution_resource", "primary_predictor",
        }
        if leaf.job.mechanism_id != "horizon-admittance":
            expected_request_fields.add("support")
        if (
            entry.component_scientific_identity != component_identity
            or entry.leaf_id != leaf.leaf_id
            or entry.job_id != leaf.job.job_id
            or entry.policy_sha256 != leaf.job.policy.identity_sha256
            or entry.backend_identity
            != leaf.job.backend_identity.identity_sha256
            or entry.determinant_family != contract["determinant_family"]
            or entry.determinant_normalisation
            != contract["determinant_normalisation"]
            or entry.precision_tier is not tier
            or entry.mpfr_bits != bits
            or entry.refinement_level != 0
            or not epsilon_text
            or float(epsilon_text) != entry.epsilon
            or abs(entry.amplitude) != entry.epsilon
            or receipt is None
            or receipt.get("schema") != WORKER_RESPONSE_RECEIPT_SCHEMA
            or receipt.get("request_sha256") != entry.request_sha256
            or receipt.get("scientific_runtime_sha256") != runtime_sha256
            or not isinstance(request, Mapping)
            or expected_request is None
            or dict(request) != expected_request
            or set(request) != expected_request_fields
            or request.get("schema_version") != 1
            or request.get("operation") != "root-readout"
            or _sha256(dict(request)) != entry.request_sha256
            or request.get("job_id") != leaf.job.job_id
            or request.get("leaf_id") != leaf.leaf_id
            or request.get("role") != leaf.role
            or request.get("mechanism_id") != leaf.job.mechanism_id
            or request.get("job_policy_sha256")
            != leaf.job.policy.identity_sha256
            or request.get("backend_identity_sha256")
            != leaf.job.backend_identity.identity_sha256
            or request.get("precision_digits") != digits
            or request.get("working_precision_bits") != bits
            or request.get("semantic_precision_tier") != tier_label
            or request.get("refinement_level") != 0
            or request.get("mode") != {
                "s": leaf.job.mode.s,
                "ell": leaf.job.mode.ell,
                "m": leaf.job.mode.m,
                "n": leaf.job.mode.n,
            }
            or request.get("spin") != format(leaf.job.spin, ".17g")
            or request.get("omega") != {
                "real": format(leaf.job.root.omega.real, ".17g"),
                "imaginary": format(leaf.job.root.omega.imag, ".17g"),
            }
            or request.get("angular_A") != {
                "real": format(
                    leaf.job.root.angular_separation_constant.real, ".17g"
                ),
                "imaginary": format(
                    leaf.job.root.angular_separation_constant.imag, ".17g"
                ),
            }
            or not isinstance(request.get("execution_resource"), Mapping)
            or not isinstance(request.get("primary_predictor"), Mapping)
            or not isinstance(request_amplitude, Mapping)
            or float(request_amplitude.get("real", "nan"))
            != entry.amplitude.real
            or float(request_amplitude.get("imaginary", "nan"))
            != entry.amplitude.imag
            or not isinstance(request.get("policy"), Mapping)
            or (
                not empirical
                and request["policy"].get("ode_error_budget") != dict(budget)
            )
            or (
                empirical
                and (
                    "ode_error_budget" in request["policy"]
                    or request["policy"].get(
                        "promoted_control_calibration_receipt_sha256"
                    ) != raw_binding["receipt_sha256"]
                    or request["policy"].get(
                        "empirical_control_profile_sha256"
                    ) != raw_profile_sha256
                    or request["policy"].get("determinant_error_model")
                    != raw_binding["determinant_certificate_identity"]
                    or request["policy"].get(
                        "determinant_error_safety_factor"
                    )
                    != raw_binding[
                        "determinant_certificate_safety_factor"
                    ]
                    or type(
                        request["policy"].get(
                            "determinant_error_safety_factor"
                        )
                    )
                    is not int
                )
            )
            or not root_readout_preserves_authenticated_branch(
                readout,
                leaf.job.root,
                equation_id=leaf.job.equation_id,
                source_root_mapping=leaf.job.source_root_mapping,
            )
        ):
            raise _UnauthenticatedComponentEvidence(
                "campaign selective tier canonical worker request or receipt "
                "identity is invalid"
            )
        promoted_readouts[entry.amplitude] = readout
    if observed_readouts != expected_readouts:
        raise _UnauthenticatedComponentEvidence(
            "campaign selective tier journal work units are invalid"
        )
    return runtime, promoted_readouts


def _selective_predecessor_readouts(
    leaf: CampaignLeafPlan,
    predecessor: StageOutcome | None,
) -> dict[complex, RootReadout]:
    if predecessor is None or predecessor.digits != 64:
        raise _UnauthenticatedComponentEvidence(
            "campaign selective binary predecessor is missing"
        )
    raw_result = predecessor.component_result.get("result")
    if not isinstance(raw_result, Mapping):
        raise _UnauthenticatedComponentEvidence(
            "campaign selective binary predecessor is invalid"
        )
    result = ComponentResult.from_mapping(raw_result)
    if (
        result.to_mapping() != raw_result
        or result.job_id != leaf.job.job_id
        or result.leaf_id != leaf.leaf_id
    ):
        raise _UnauthenticatedComponentEvidence(
            "campaign selective binary predecessor is invalid"
        )
    return _component_readouts_by_amplitude(result)


def _component_readouts_by_amplitude(
    result: ComponentResult,
) -> dict[complex, RootReadout]:
    readouts = {0.0j: result.baseline}
    for level in result.levels:
        readouts.update({
            complex(level.epsilon, 0.0): level.real_plus,
            complex(-level.epsilon, 0.0): level.real_minus,
            complex(0.0, level.epsilon): level.imaginary_plus,
            complex(0.0, -level.epsilon): level.imaginary_minus,
        })
    return readouts


def _validate_selective_stage(
    leaf: CampaignLeafPlan,
    outcome: StageOutcome,
    predecessor: StageOutcome | None = None,
) -> tuple[ComponentResult, bool] | None:
    """Validate terminal semantic-tier evidence without legacy stage claims."""

    payload = outcome.component_result
    if payload.get("evidence_kind") != _SELECTIVE_STAGE_EVIDENCE_KIND:
        return None
    expected_fields = {
        "evidence_kind",
        "result",
        "scientific_runtime",
        "legacy_campaign_stage_digits",
        "semantic_precision_tier",
        "semantic_selective_tier_trace",
        "whole_component_promotion_used",
    }
    raw_result = payload.get("result")
    trace = payload.get("semantic_selective_tier_trace")
    if (
        set(payload) != expected_fields
        or outcome.digits != 80
        or payload.get("legacy_campaign_stage_digits") != 80
        or payload.get("whole_component_promotion_used") is not False
        or not isinstance(trace, list)
        or tuple(trace) not in {
            _SELECTIVE_TIER_SEQUENCE[:1],
            _SELECTIVE_TIER_SEQUENCE[:2],
            _SELECTIVE_TIER_SEQUENCE,
        }
        or payload.get("semantic_precision_tier") != trace[-1]
        or outcome.self_refinement_enclosed is not None
        or outcome.discrepancy_from_previous_abs is not None
        or outcome.discrepancy_enclosed is not None
        or outcome.deep_diagnostics is not None
        or not isinstance(raw_result, Mapping)
    ):
        raise _UnauthenticatedComponentEvidence(
            "campaign selective stage execution contract is invalid"
        )
    runtime = payload.get("scientific_runtime")
    if (
        not isinstance(runtime, Mapping)
        or runtime.get("semantic_precision_tier") != trace[-1]
    ):
        raise _UnauthenticatedComponentEvidence(
            "campaign selective stage runtime tier is invalid"
        )
    result = ComponentResult.from_mapping(raw_result)
    classified_kind, classified_result = _classify_promoted_stage(outcome)
    if (
        classified_kind is not _PromotedStageKind.SELECTIVE_READOUT
        or classified_result.to_mapping() != result.to_mapping()
        or result.to_mapping() != raw_result
        or result.job_id != leaf.job.job_id
        or result.leaf_id != leaf.leaf_id
        or result.mechanism_id != leaf.mechanism_id
        or result.status.value != outcome.numerical_state
        or dict(result.lineage) != {
            "leaf_id": leaf.job.leaf_id,
            "root_reference_id": leaf.job.root.root_reference_id,
            "root_identity_sha256": leaf.job.root.identity_sha256,
            "policy_sha256": leaf.job.policy.identity_sha256,
            "backend_identity_sha256": leaf.job.backend_identity.identity_sha256,
            "equation_id": leaf.job.equation_id,
            "sampling_coordinate": leaf.job.sampling_coordinate.to_mapping(),
            "source_root_mapping": leaf.job.source_root_mapping,
        }
    ):
        raise _UnauthenticatedComponentEvidence(
            "campaign selective stage component identity is invalid"
        )
    window = result.resolved_window
    if not isinstance(window, Mapping):
        raise _UnauthenticatedComponentEvidence(
            "campaign selective stage recovery evidence is missing"
        )
    current_plan = window.get("executed_readout_specific_promotion_plan")
    promoted_counts = window.get("promoted_readout_count_by_tier")
    prior = window.get("prior_tier_recovery_evidence")
    journal = window.get("journal_evidence")
    if (
        window.get("selective_promotion_policy")
        != "readout-specific-semantic-tier/v1"
        or window.get("executed_precision_tier") != trace[-1]
        or not isinstance(current_plan, list)
        or not current_plan
        or not isinstance(promoted_counts, Mapping)
        or set(promoted_counts) != set(trace)
        or any(type(count) is not int or count < 1 for count in promoted_counts.values())
        or not isinstance(prior, list)
        or len(prior) != len(trace) - 1
        or not isinstance(journal, Mapping)
    ):
        raise _UnauthenticatedComponentEvidence(
            "campaign selective stage tier evidence is invalid"
        )

    def valid_plan(value: object) -> bool:
        return (
            isinstance(value, list)
            and bool(value)
            and all(
                isinstance(item, Mapping)
                and set(item) == {"epsilon", "readout_role"}
                and item["readout_role"] in {
                    "real_plus", "real_minus",
                    "imaginary_plus", "imaginary_minus",
                }
                and isinstance(item["epsilon"], (int, float))
                and not isinstance(item["epsilon"], bool)
                and math.isfinite(float(item["epsilon"]))
                and float(item["epsilon"]) > 0.0
                for item in value
            )
        )

    if not valid_plan(current_plan):
        raise _UnauthenticatedComponentEvidence(
            "campaign selective stage readout plan is invalid"
        )
    predecessor_readouts = _selective_predecessor_readouts(leaf, predecessor)
    expected_terminal_readouts = dict(predecessor_readouts)
    for index, evidence in enumerate(prior):
        if (
            not isinstance(evidence, Mapping)
            or evidence.get("executed_precision_tier") != trace[index]
            or not valid_plan(
                evidence.get("executed_readout_specific_promotion_plan")
            )
            or not isinstance(evidence.get("journal_evidence"), Mapping)
        ):
            raise _UnauthenticatedComponentEvidence(
                "campaign selective prior-tier evidence is invalid"
            )
        _, promoted_readouts = _validate_selective_tier_journal(
            leaf,
            trace[index],
            evidence["executed_readout_specific_promotion_plan"],
            evidence["journal_evidence"],
            predecessor_readouts,
        )
        expected_terminal_readouts.update(promoted_readouts)
        predecessor_readouts = dict(expected_terminal_readouts)
    current_runtime, promoted_readouts = _validate_selective_tier_journal(
        leaf, trace[-1], current_plan, journal, predecessor_readouts
    )
    expected_terminal_readouts.update(promoted_readouts)
    if dict(runtime) != dict(current_runtime):
        raise _UnauthenticatedComponentEvidence(
            "campaign selective stage runtime disagrees with tier evidence"
        )
    terminal_readouts = _component_readouts_by_amplitude(result)
    if terminal_readouts != expected_terminal_readouts:
        raise _UnauthenticatedComponentEvidence(
            "campaign selective terminal readouts disagree with tier journals "
            f"(terminal={sorted(map(str, terminal_readouts))}, "
            f"expected={sorted(map(str, expected_terminal_readouts))})"
        )
    recovery_projection = _response_ladder_recovery(leaf.job, result.levels)
    expected_window_projection = _response_ladder_recovery_record(
        leaf.job, result.levels, recovery_projection
    )
    if result.status is not ComponentStatus.CONVERGED:
        expected_window_projection["next_precision_tier"] = {
            PrecisionTier.BIGFLOAT_40.value: PrecisionTier.BIGFLOAT_80.value,
            PrecisionTier.BIGFLOAT_80.value: PrecisionTier.BIGFLOAT_120.value,
            PrecisionTier.BIGFLOAT_120.value: None,
        }[trace[-1]]
        if not expected_window_projection.get(
            "readout_specific_promotion_plan"
        ):
            expected_window_projection[
                "readout_specific_promotion_plan"
            ] = [dict(item) for item in current_plan]
    projection_fields = {
        "recovery_disposition",
        "candidate_windows",
        "signal_noise_ratios",
        "selected_window",
        "excluded_fine_levels",
        "window_diagnostics",
        "branch_margins",
        "exact_added_epsilons",
        "amplitudes_to_add",
        "readout_specific_promotion_plan",
        "next_precision_tier",
    }
    if any(
        window.get(field) != expected_window_projection.get(field)
        for field in projection_fields
    ):
        mismatched_projection_fields = sorted(
            field
            for field in projection_fields
            if window.get(field) != expected_window_projection.get(field)
        )
        raise _UnauthenticatedComponentEvidence(
            "campaign selective resolved-window projection is invalid: "
            + ", ".join(mismatched_projection_fields)
        )
    for readout in result.raw_readouts:
        if not root_readout_preserves_authenticated_branch(
            readout,
            leaf.job.root,
            equation_id=leaf.job.equation_id,
            source_root_mapping=leaf.job.source_root_mapping,
        ):
            raise _UnauthenticatedComponentEvidence(
                "campaign selective root evidence is invalid"
            )
    semantics = _promoted_stage_semantics(outcome)
    if semantics.kind is not _PromotedStageKind.SELECTIVE_READOUT:
        raise _UnauthenticatedComponentEvidence(
            "campaign selective stage changed classification"
        )
    produced = semantics.terminal_admissible
    if produced != result.usable:
        raise _UnauthenticatedComponentEvidence(
            "campaign selective terminal result body is invalid"
        )
    if not produced and (
        tuple(trace) != _SELECTIVE_TIER_SEQUENCE
        or window.get("next_precision_tier") is not None
    ):
        raise _UnauthenticatedComponentEvidence(
            "campaign selective exhaustion evidence is invalid"
        )
    return result, produced


def _validate_fixed_readout_predictor_binding(
    previous: StageOutcome,
    promoted: StageOutcome,
) -> None:
    """Bind an analytic/fixed-root request to the preceding baseline root."""

    if not isinstance(promoted.component_result.get("result"), Mapping):
        return
    kind, result = _classify_promoted_stage(promoted)
    if kind not in {
        _PromotedStageKind.ANALYTIC_HORIZON,
        _PromotedStageKind.FIXED_ROOT_EXTERIOR_DERIVATIVE,
    }:
        return
    if (
        promoted.component_result.get("evidence_kind")
        == _ROOT_SEALED_RESPONSE_REPAIR_EVIDENCE_KIND
    ):
        raw_previous = previous.component_result.get("result")
        if not isinstance(raw_previous, Mapping):
            raise _UnauthenticatedComponentEvidence(
                "root-sealed response repair predecessor is missing"
            )
        previous_result = ComponentResult.from_mapping(raw_previous)
        if previous_result.to_mapping() != raw_previous:
            raise _UnauthenticatedComponentEvidence(
                "root-sealed response repair predecessor is not canonical"
            )
        seal = _sealed_root_for_result(result)
        if (
            seal is None
            or seal.root_readout.to_mapping()
            != previous_result.baseline.to_mapping()
        ):
            raise _UnauthenticatedComponentEvidence(
                "root-sealed response repair changed its persisted root"
            )
        return
    _validate_promoted_result_predictor_binding(previous, result)


def _validate_promoted_result_predictor_binding(
    previous: StageOutcome,
    result: ComponentResult,
) -> None:
    """Authenticate one promoted baseline predictor against its predecessor."""

    raw_previous = previous.component_result.get("result")
    if not isinstance(raw_previous, Mapping):
        raise _UnauthenticatedComponentEvidence(
            "promoted fixed-readout predictor predecessor is missing"
        )
    previous_result = ComponentResult.from_mapping(raw_previous)
    if previous_result.to_mapping() != raw_previous:
        raise _UnauthenticatedComponentEvidence(
            "promoted fixed-readout predictor predecessor is not canonical"
        )
    receipt = result.baseline.worker_response_receipt
    request = (
        None if not isinstance(receipt, Mapping)
        else receipt.get("request_binding")
    )
    expected_predictor = {
        "real": format(previous_result.baseline.omega.real, ".17g"),
        "imaginary": format(previous_result.baseline.omega.imag, ".17g"),
    }
    if (
        not isinstance(request, Mapping)
        or request.get("amplitude") != {"real": "0", "imaginary": "0"}
        or request.get("primary_predictor") != expected_predictor
        or "primary_predictor_kind" in request
    ):
        raise _UnauthenticatedComponentEvidence(
            "promoted fixed-readout PRIMARY predictor binding is invalid"
        )


def _validate_single_promoted_horizon_predictor_binding(
    previous: StageOutcome,
    promoted: StageOutcome,
) -> None:
    """Compatibility name for the now-shared fixed-readout binding gate."""

    result = _single_promoted_horizon_result(promoted)
    if result is not None:
        _validate_promoted_result_predictor_binding(previous, result)


def _promotion_decision(
    outcome: StageOutcome,
    *,
    existing_requested: bool,
    requested_reason: str,
    suppressed_reason: str,
    allow_nonconvergence_suppression: bool = True,
) -> dict[str, object]:
    evidence = _promotion_conditioning(outcome)
    requested = existing_requested
    reason = requested_reason if requested else suppressed_reason
    if (
        allow_nonconvergence_suppression
        and outcome.numerical_state == ComponentStatus.NOT_CONVERGED.value
    ):
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


def _validated_promotion_decision(
    value: object,
    *,
    allow_historical: bool = False,
) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _PROMOTION_DECISION_FIELDS:
        raise ValueError("precision promotion decision fields are invalid")
    if (
        value["schema"]
        not in (
            {_PROMOTION_DECISION_SCHEMA}
            if not allow_historical
            else {
                _PROMOTION_DECISION_SCHEMA,
                _HISTORICAL_PROMOTION_DECISION_SCHEMA,
            }
        )
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
    # Historical schema 1 encoded the same fields but predated the explicit
    # root-only contract.  It is readable only while authenticating an old
    # checkpoint; normalize it for semantic comparison and never emit it.
    if output["schema"] == _HISTORICAL_PROMOTION_DECISION_SCHEMA:
        output["schema"] = _PROMOTION_DECISION_SCHEMA
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


def _stage_with_endpoint_arithmetic_predecessor(
    outcome: StageOutcome, predecessor: CampaignExecutionAttempt
) -> StageOutcome:
    component_result = dict(outcome.component_result)
    if "endpoint_arithmetic_predecessor" in component_result:
        raise ValueError("endpoint-arithmetic predecessor is already attached")
    component_result["endpoint_arithmetic_predecessor"] = (
        predecessor.to_mapping()
    )
    source_sha256 = _sha256(component_result)
    channels = []
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


def _embedded_endpoint_arithmetic_predecessor(
    outcome: StageOutcome, leaf: CampaignLeafPlan
) -> CampaignExecutionAttempt | None:
    raw = outcome.component_result.get("endpoint_arithmetic_predecessor")
    if raw is None:
        return None
    predecessor = CampaignExecutionAttempt.from_mapping(raw)
    _validate_endpoint_arithmetic_predecessor(predecessor, leaf)
    return predecessor


def _validate_attached_promotion_decision(
    outcome: StageOutcome,
    expected: Mapping[str, object],
    *,
    required: bool,
    allow_historical: bool = False,
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
    if _validated_promotion_decision(
        raw, allow_historical=allow_historical
    ) != dict(expected):
        raise ValueError("precision promotion decision disagrees with stage evidence")


def _primary_existing_requires_precision120(
    outcome: StageOutcome,
    *,
    predecessor: StageOutcome | None = None,
) -> bool:
    if not isinstance(outcome.component_result.get("result"), Mapping):
        gates = _previous_primary_recovery_precision_contract()[
            "precision120_gates"
        ]
        if outcome.numerical_state == gates["component_status"]:
            return True
        if outcome.numerical_state != ComponentStatus.CONVERGED.value:
            return False
        return (
            outcome.self_refinement_enclosed
            is gates["self_refinement_enclosed"]
            or outcome.discrepancy_enclosed is gates["discrepancy_enclosed"]
        )
    return _promoted_stage_semantics(
        outcome, predecessor=predecessor
    ).requires_precision120


def _primary_precision120_decision(
    outcome: StageOutcome,
    *,
    predecessor: StageOutcome | None = None,
) -> dict[str, object]:
    raw_result = outcome.component_result.get("result")
    if isinstance(raw_result, Mapping):
        semantics = _promoted_stage_semantics(
            outcome, predecessor=predecessor
        )
        existing_requested = semantics.requires_precision120
        promoted_horizon_stage = (
            semantics.kind is _PromotedStageKind.ANALYTIC_HORIZON
        )
        fixed_root_exterior = semantics.kind is (
            _PromotedStageKind.FIXED_ROOT_EXTERIOR_DERIVATIVE
        )
        root_reason = _root_precision120_reason(
            outcome,
            semantics.result,
            _sealed_root_for_result(semantics.result),
        )
    else:
        existing_requested = _primary_existing_requires_precision120(outcome)
        promoted_horizon_stage = False
        fixed_root_exterior = False
        root_reason = None
    return _promotion_decision(
        outcome,
        existing_requested=existing_requested,
        requested_reason=(
            root_reason or "PROMOTED_ROOT_OR_CONDITIONING_GATE"
            if promoted_horizon_stage
            else root_reason or "ROOT_TYPED_RETRY_REQUIRED"
            if fixed_root_exterior
            else "CONVERGED_REFINEMENT_OR_DISCREPANCY_GATE"
        ),
        suppressed_reason=(
            "ROOT_EVIDENCE_ACCEPTED"
            if promoted_horizon_stage
            else "ROOT_EVIDENCE_ACCEPTED"
            if fixed_root_exterior
            else "CONVERGED_PROMOTION_GATES_SATISFIED"
        ),
        allow_nonconvergence_suppression=(
            not promoted_horizon_stage and not fixed_root_exterior
        ),
    )


def _deep_precision120_decision(
    outcome: StageOutcome,
    *,
    sentinel_false_negative: bool,
    predecessor: StageOutcome | None = None,
) -> dict[str, object]:
    raw_result = outcome.component_result.get("result")
    semantics = (
        _promoted_stage_semantics(outcome, predecessor=predecessor)
        if isinstance(raw_result, Mapping)
        else None
    )
    fixed_root_exterior = semantics is not None and semantics.kind is (
        _PromotedStageKind.FIXED_ROOT_EXTERIOR_DERIVATIVE
    )
    analytic_horizon = semantics is not None and semantics.kind is (
        _PromotedStageKind.ANALYTIC_HORIZON
    )
    if semantics is None or semantics.kind is (
        _PromotedStageKind.LEGACY_FULL_LADDER
    ):
        stage_requested = not bool(outcome.self_refinement_enclosed)
        root_reason = None
    else:
        stage_requested = semantics.requires_precision120
        root_reason = _root_precision120_reason(
            outcome,
            semantics.result,
            _sealed_root_for_result(semantics.result),
        )
    existing_requested = sentinel_false_negative or stage_requested
    decision = _promotion_decision(
        outcome,
        existing_requested=existing_requested,
        requested_reason=(
            "SENTINEL_TRIGGER_FALSE_NEGATIVE"
            if sentinel_false_negative
            else root_reason or "PROMOTED_ROOT_OR_CONDITIONING_GATE"
            if analytic_horizon
            else root_reason or "ROOT_TYPED_RETRY_REQUIRED"
            if fixed_root_exterior
            else "CONVERGED_REFINEMENT_OR_DISCREPANCY_GATE"
        ),
        suppressed_reason=(
            "ROOT_EVIDENCE_ACCEPTED"
            if analytic_horizon
            else "ROOT_EVIDENCE_ACCEPTED"
            if fixed_root_exterior
            else "CONVERGED_PROMOTION_GATES_SATISFIED"
        ),
        allow_nonconvergence_suppression=(
            not fixed_root_exterior and not analytic_horizon
        ),
    )
    if sentinel_false_negative:
        # This is an independent release-policy audit of the binary64 trigger,
        # not a claim that extra digits will repair 80-digit nonconvergence.
        decision["state"] = "REQUESTED"
        decision["reason"] = "SENTINEL_TRIGGER_FALSE_NEGATIVE"
    return decision


def _primary_requires_precision120(
    outcome: StageOutcome,
    *,
    predecessor: StageOutcome | None = None,
) -> bool:
    return _primary_precision120_decision(
        outcome, predecessor=predecessor
    )["state"] == "REQUESTED"


def _primary_precision120_terminal_state(
    outcome: StageOutcome,
    *,
    predecessor: StageOutcome | None = None,
) -> str:
    if not isinstance(outcome.component_result.get("result"), Mapping):
        success = _previous_primary_recovery_precision_contract()[
            "precision120_terminal_success"
        ]
        produced = (
            outcome.numerical_state == success["component_status"]
            and outcome.discrepancy_enclosed
            is success["discrepancy_enclosed"]
        )
        return "PRODUCED" if produced else "UNRESOLVED"
    semantics = _promoted_stage_semantics(
        outcome, predecessor=predecessor
    )
    return "PRODUCED" if semantics.terminal_admissible else "UNRESOLVED"


def _endpoint_arithmetic_terminal_state(
    leaf: CampaignLeafPlan,
    outcome: StageOutcome,
    *,
    predecessor: StageOutcome,
    sentinel: bool,
) -> str:
    """Apply the promoted component's terminal rule after endpoint loss."""

    state = _primary_precision120_terminal_state(
        outcome, predecessor=predecessor
    )
    if leaf.role == "deep" and sentinel:
        return "UNRESOLVED"
    return state


class _NonProductionSolvedLeafRecord(ValueError):
    """A valid orchestration record that is ineligible for scientific reuse."""


class _UnauthenticatedComponentEvidence(ValueError):
    """Well-formed component evidence that fails scientific authentication."""


def _historical_regularised_gsn_precision_policy(
    mechanism_id: str,
) -> dict[str, object]:
    policy = dict(regularised_gsn_precision_policy(mechanism_id))
    for field in (
        "promoted_root_readout_policy",
        "human_math_review_receipt_status",
        "human_math_review_receipt_sha256",
        "independent_reference_fixture_receipt_status",
        "independent_reference_fixture_receipt_sha256",
    ):
        policy.pop(field)
    policy["regularised_gsn_activation_status"] = (
        "blocked-pending-human-math-review-and-independent-reference/v1"
    )
    return policy


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
    evidence_kind = payload.get("evidence_kind")
    package_promoted = evidence_kind in {
        _LEGACY_FULL_LADDER_EVIDENCE_KIND,
        _ANALYTIC_HORIZON_EVIDENCE_KIND,
        _FIXED_ROOT_EXTERIOR_EVIDENCE_KIND,
        _ROOT_SEALED_RESPONSE_REPAIR_EVIDENCE_KIND,
    }
    response_repair = (
        evidence_kind == _ROOT_SEALED_RESPONSE_REPAIR_EVIDENCE_KIND
    )
    classified_kind: _PromotedStageKind | None = None
    raw_primary_result = payload.get("result")
    if (
        outcome.digits in (80, 120)
        and isinstance(raw_primary_result, Mapping)
        and raw_primary_result == result.to_mapping()
        and evidence_kind in {
            _SELECTIVE_STAGE_EVIDENCE_KIND,
            _LEGACY_FULL_LADDER_EVIDENCE_KIND,
            _ANALYTIC_HORIZON_EVIDENCE_KIND,
            _FIXED_ROOT_EXTERIOR_EVIDENCE_KIND,
            _ROOT_SEALED_RESPONSE_REPAIR_EVIDENCE_KIND,
        }
    ):
        classified_kind, classified_result = _classify_promoted_stage(outcome)
        assert classified_result.to_mapping() == result.to_mapping()
    single_horizon = evidence_kind == _ANALYTIC_HORIZON_EVIDENCE_KIND or (
        evidence_kind == _ROOT_SEALED_RESPONSE_REPAIR_EVIDENCE_KIND
        and result.component_scientific_identity
        == PROMOTED_HORIZON_COMPONENT_V3_IDENTITY
    )
    result_is_single_horizon = (
        classified_kind is _PromotedStageKind.ANALYTIC_HORIZON
        or result.component_scientific_identity in {
            PROMOTED_HORIZON_COMPONENT_IDENTITY,
            PROMOTED_HORIZON_COMPONENT_V2_IDENTITY,
            PROMOTED_HORIZON_COMPONENT_V3_IDENTITY,
        }
        or (
            single_horizon
            and result.component_scientific_identity is None
            and result.mechanism_id == "horizon-admittance"
            and result.status in _TYPED_FIXED_READOUT_FAILURE_STATUSES
            and not _claims_specialized_promoted_semantics(result)
        )
    )
    if single_horizon != result_is_single_horizon:
        raise _UnauthenticatedComponentEvidence(
            "campaign promoted component identity disagrees with evidence kind"
        )
    fixed_exterior = (
        evidence_kind == _FIXED_ROOT_EXTERIOR_EVIDENCE_KIND
        or (
            evidence_kind == _ROOT_SEALED_RESPONSE_REPAIR_EVIDENCE_KIND
            and result.component_scientific_identity
            == EXTERIOR_DERIVATIVE_COMPONENT_IDENTITY
        )
    )
    result_is_fixed_exterior = (
        classified_kind is _PromotedStageKind.FIXED_ROOT_EXTERIOR_DERIVATIVE
        or result.component_scientific_identity
        == EXTERIOR_DERIVATIVE_COMPONENT_IDENTITY
        or (
            evidence_kind == _FIXED_ROOT_EXTERIOR_EVIDENCE_KIND
            and result.component_scientific_identity is None
            and result.mechanism_id.startswith("exterior-")
            and result.status in _TYPED_FIXED_READOUT_FAILURE_STATUSES
            and not _claims_specialized_promoted_semantics(result)
        )
    )
    if fixed_exterior != result_is_fixed_exterior:
        raise _UnauthenticatedComponentEvidence(
            "campaign fixed-root exterior identity disagrees with evidence kind"
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
    raw_budget = runtime.get("ode_error_budget")
    raw_budget_sha256 = runtime.get("ode_error_budget_sha256")
    validated_budget = _ode_error_budget_from_mapping(raw_budget)
    raw_empirical_binding = runtime.get("promoted_control_calibration")
    raw_empirical_profile = runtime.get("empirical_control_profile")
    raw_empirical_profile_sha256 = runtime.get(
        "empirical_control_profile_sha256"
    )
    empirical_present = any(value is not None for value in (
        raw_empirical_binding,
        raw_empirical_profile,
        raw_empirical_profile_sha256,
    ))
    empirical_profile: EmpiricalControlProfile | None = None
    empirical_receipt: _EmpiricalCalibrationBindingView | None = None
    if empirical_present:
        expected_family = (
            "horizon-scattering/v1"
            if leaf.mechanism_id == "horizon-admittance"
            else "exterior-wronskian/v1"
        )
        if (
            not isinstance(raw_empirical_binding, Mapping)
            or set(raw_empirical_binding) != {
                "schema",
                "receipt_identity",
                "receipt_sha256",
                "execution_status",
                "source_audit_sha256",
                "determinant_family",
                "determinant_certificate_identity",
                "determinant_certificate_safety_factor",
                "derivative_floor_status",
            }
            or raw_empirical_binding.get("schema")
            != "windows-solver.promoted-control-calibration-binding/1"
            or raw_empirical_binding.get("receipt_identity")
            != "promoted-control-empirical-calibration/v1"
            or not isinstance(
                raw_empirical_binding.get("receipt_sha256"), str
            )
            or re.fullmatch(
                r"[0-9a-f]{64}", raw_empirical_binding["receipt_sha256"]
            ) is None
            or raw_empirical_binding.get("determinant_family")
            != expected_family
            or raw_empirical_binding.get(
                "determinant_certificate_identity"
            ) != (
                "exterior-determinant-absolute-error-certificate/empirical-v1"
            )
            or raw_empirical_binding.get(
                "determinant_certificate_safety_factor"
            ) != 64
            or raw_empirical_binding.get("derivative_floor_status")
            != "ARCHIVED_AUTHENTICATED_LOWER_BOUND_UNAVAILABLE"
            or not isinstance(raw_empirical_profile, Mapping)
            or set(raw_empirical_profile) != {
                "base_controls",
                "determinant_family",
                "nominal_decimal_digits",
                "precision_tier",
                "refinement_controls",
            }
            or raw_empirical_profile.get("determinant_family")
            != expected_family
            or raw_empirical_profile.get("nominal_decimal_digits")
            != outcome.digits
            or raw_empirical_profile.get("precision_tier")
            != f"bigfloat-{outcome.digits}"
            or not isinstance(
                raw_empirical_profile.get("base_controls"), Mapping
            )
            or not isinstance(
                raw_empirical_profile.get("refinement_controls"), Mapping
            )
            or raw_empirical_profile_sha256
            != _sha256(dict(raw_empirical_profile))
            or raw_budget is not None
            or raw_budget_sha256 is not None
        ):
            raise _UnauthenticatedComponentEvidence(
                "campaign promoted empirical calibration is invalid"
            )
        tier = precision_tier(f"bigfloat-{outcome.digits}")
        empirical_profile = EmpiricalControlProfile(
            determinant_family=expected_family,
            precision_tier=tier,
            nominal_decimal_digits=outcome.digits,
            base_controls=dict(raw_empirical_profile["base_controls"]),
            refinement_controls=dict(
                raw_empirical_profile["refinement_controls"]
            ),
        )
        empirical_receipt = _EmpiricalCalibrationBindingView(
            sha256=str(raw_empirical_binding["receipt_sha256"]),
            certificate_identity=str(
                raw_empirical_binding["determinant_certificate_identity"]
            ),
            certificate_safety_factor=64,
            profile=empirical_profile,
        )
    elif package_promoted and (
        raw_budget is not None
        or raw_budget_sha256 is not None
        or not allow_historical_conditioning_absence
    ):
        if (
            not isinstance(raw_budget, Mapping)
            or validated_budget is None
            or validated_budget.to_mapping() != dict(raw_budget)
            or raw_budget.get("nominal_decimal_digits") != outcome.digits
            or raw_budget_sha256 != _sha256(dict(raw_budget))
        ):
            raise _UnauthenticatedComponentEvidence(
                "campaign promoted scientific runtime ODE budget is invalid"
            )
    fixed_sample_evidence = (
        result.derivative_evidence
        if result.component_scientific_identity
        == EXTERIOR_DERIVATIVE_COMPONENT_IDENTITY
        else result.analytic_horizon_evidence
        if result.component_scientific_identity
        == PROMOTED_HORIZON_COMPONENT_V3_IDENTITY
        else None
    )
    if isinstance(fixed_sample_evidence, Mapping):
        raw_fixed_samples = fixed_sample_evidence.get("fixed_root_samples")
        if not isinstance(raw_fixed_samples, list):
            raise _UnauthenticatedComponentEvidence(
                "campaign fixed-root sample evidence is invalid"
            )
        runtime_provenance = {
            name: value
            for name, value in runtime.items()
            if name not in {
                "precision_digits",
                "working_precision_bits",
                "semantic_precision_tier",
                "refinement_level",
                "regularised_gsn_precision_policy",
                "ode_error_budget",
                "ode_error_budget_sha256",
                "promoted_control_calibration",
                "empirical_control_profile",
                "empirical_control_profile_sha256",
            }
        }
        expected_sample_runtime = runtime_identity_sha256(runtime_provenance)
        expected_scientific_runtime = hashlib.sha256(
            canonical_json_bytes(dict(runtime))
        ).hexdigest()
        expected_sample_tier = runtime.get("semantic_precision_tier")
        expected_sample_bits = runtime.get("working_precision_bits")
        if (
            not isinstance(expected_sample_tier, str)
            or expected_sample_tier != f"bigfloat-{outcome.digits}"
        ):
            raise _UnauthenticatedComponentEvidence(
                "campaign fixed-root sample precision tier is invalid"
            )
        reused_sample_families: frozenset[str] = frozenset()
        if (
            response_repair
            and result.component_scientific_identity
            == EXTERIOR_DERIVATIVE_COMPONENT_IDENTITY
        ):
            scope = fixed_sample_evidence.get("response_repair_scope")
            if not isinstance(scope, Mapping):
                raise _UnauthenticatedComponentEvidence(
                    "campaign root-sealed response repair scope is invalid"
                )
            reused = scope.get("reused_families")
            recomputed = scope.get("recomputed_families")
            if (
                not isinstance(reused, list)
                or not isinstance(recomputed, list)
                or any(
                    item not in {"frequency", "coordinate"}
                    for item in (*reused, *recomputed)
                )
                or set(reused) & set(recomputed)
            ):
                raise _UnauthenticatedComponentEvidence(
                    "campaign root-sealed response repair scope is invalid"
                )
            reused_sample_families = frozenset(reused)
        for raw_sample in raw_fixed_samples:
            sample = FixedRootDeterminantSample.from_mapping(raw_sample)
            family = (
                "frequency"
                if sample.readout_role.startswith("frequency-")
                else "coordinate"
                if sample.readout_role.startswith("coordinate-")
                else None
            )
            if family is None:
                raise _UnauthenticatedComponentEvidence(
                    "campaign fixed-root sample family is invalid"
                )
            if family not in reused_sample_families:
                if (
                    sample.precision_tier.value != expected_sample_tier
                    or sample.working_precision_bits != expected_sample_bits
                ):
                    raise _UnauthenticatedComponentEvidence(
                        "campaign fixed-root sample precision is invalid"
                    )
                if (
                    sample.worker_response_receipt.get("runtime_identity_sha256")
                    != expected_sample_runtime
                    or sample.worker_response_receipt.get(
                        "scientific_runtime_sha256"
                    )
                    != expected_scientific_runtime
                ):
                    raise _UnauthenticatedComponentEvidence(
                        "campaign fixed-root sample runtime identity is invalid"
                    )
            elif not all(
                isinstance(
                    sample.worker_response_receipt.get(field), str
                )
                and re.fullmatch(
                    r"[0-9a-f]{64}",
                    sample.worker_response_receipt[field],
                ) is not None
                for field in (
                    "runtime_identity_sha256",
                    "scientific_runtime_sha256",
                )
            ):
                raise _UnauthenticatedComponentEvidence(
                    "campaign reused fixed-root sample runtime is invalid"
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
    conditioning_schemas = {
        readout.numerical_conditioning.schema
        for readout in result.raw_readouts
        if readout.numerical_conditioning is not None
    }
    if conditioning_schemas == {NUMERICAL_CONDITIONING_SCHEMA}:
        expected_policy = dict(
            regularised_gsn_precision_policy(leaf.job.mechanism_id)
        )
        allowed_readout_policies = (
            {HISTORICAL_PROMOTED_ROOT_READOUT_POLICY}
            if result.component_scientific_identity
            == PROMOTED_HORIZON_COMPONENT_IDENTITY
            else {PROMOTED_ROOT_READOUT_POLICY}
        )
        if any(
            readout.promoted_root_readout_policy
            not in allowed_readout_policies
            for readout in result.raw_readouts
        ):
            raise _UnauthenticatedComponentEvidence(
                "campaign promoted root-readout policy identity is invalid"
            )
    elif (
        allow_historical_conditioning_absence
        and conditioning_schemas
        == {HISTORICAL_NUMERICAL_CONDITIONING_SCHEMA}
    ):
        expected_policy = _historical_regularised_gsn_precision_policy(
            leaf.job.mechanism_id
        )
    else:
        raise _UnauthenticatedComponentEvidence(
            "campaign promoted numerical conditioning schema is invalid"
        )
    observed_policy = runtime.get("regularised_gsn_precision_policy")
    if not isinstance(observed_policy, Mapping) or dict(observed_policy) != (
        expected_policy
    ):
        raise _UnauthenticatedComponentEvidence(
            "campaign promoted scientific runtime policy disagrees with mechanism"
        )
    # A response-only repair is intentionally evaluated under a newer sample
    # runtime while retaining an older sealed root receipt.  Validating that
    # root receipt as if it belonged to this response tier would force a
    # re-root, exactly the coupling this boundary removes.
    receipts = (
        ()
        if response_repair
        else tuple(
            readout.worker_response_receipt for readout in result.raw_readouts
        )
    )
    has_receipts = any(receipt is not None for receipt in receipts)
    if (
        not allow_historical_conditioning_absence
        and not has_receipts
        and not response_repair
    ):
        raise _UnauthenticatedComponentEvidence(
            "campaign current promoted worker response receipt is missing"
        )
    if has_receipts:
        if not all(receipt is not None for receipt in receipts):
            raise _UnauthenticatedComponentEvidence(
                "campaign promoted worker response receipts are incomplete"
            )
        expected_runtime_sha256 = hashlib.sha256(
            canonical_json_bytes(dict(runtime))
        ).hexdigest()
        for receipt in receipts:
            assert receipt is not None
            binding = receipt["request_binding"]
            if (
                receipt["scientific_runtime_sha256"]
                != expected_runtime_sha256
                or binding.get("job_id") != leaf.job.job_id
                or binding.get("leaf_id") != leaf.leaf_id
                or binding.get("role") != leaf.role
                or binding.get("mechanism_id") != leaf.job.mechanism_id
                or binding.get("job_policy_sha256")
                != leaf.job.policy.identity_sha256
                or binding.get("backend_identity_sha256")
                != leaf.job.backend_identity.identity_sha256
                or binding.get("precision_digits") != outcome.digits
                or binding.get("refinement_level")
                != expected_refinement_level
            ):
                raise _UnauthenticatedComponentEvidence(
                    "campaign promoted worker response receipt identity is invalid"
                )
            if (
                receipt.get("schema") == WORKER_RESPONSE_RECEIPT_SCHEMA
                and conditioning_schemas == {NUMERICAL_CONDITIONING_SCHEMA}
            ):
                if validated_budget is None and empirical_profile is None:
                    raise _UnauthenticatedComponentEvidence(
                        "campaign current promoted canonical request lacks an "
                        "authenticated control profile"
                    )

                def request_complex(
                    raw: object, subject: str
                ) -> complex:
                    if not isinstance(raw, Mapping) or set(raw) != {
                        "real", "imaginary"
                    }:
                        raise _UnauthenticatedComponentEvidence(
                            f"campaign promoted {subject} is invalid"
                        )
                    try:
                        parts = tuple(
                            Decimal(raw[name]) for name in ("real", "imaginary")
                        )
                    except (InvalidOperation, TypeError, ValueError) as error:
                        raise _UnauthenticatedComponentEvidence(
                            f"campaign promoted {subject} is invalid"
                        ) from error
                    if not all(part.is_finite() for part in parts):
                        raise _UnauthenticatedComponentEvidence(
                            f"campaign promoted {subject} is invalid"
                        )
                    return complex(*(float(part) for part in parts))

                amplitude = request_complex(
                    binding.get("amplitude"), "request amplitude"
                )
                raw_predictor = binding.get("primary_predictor")
                predictor = (
                    None
                    if raw_predictor is None
                    else request_complex(raw_predictor, "request predictor")
                )
                predictor_kind = binding.get("primary_predictor_kind")
                if predictor_kind is not None and not isinstance(
                    predictor_kind, str
                ):
                    raise _UnauthenticatedComponentEvidence(
                        "campaign promoted request predictor kind is invalid"
                    )
                try:
                    observed_resource = _validated_execution_resource_policy(
                        binding.get("execution_resource")
                    )
                    expected_request = _CanonicalRequestJuliaPrecisionRootBackend(
                        leaf.job.backend_identity,
                        object(),
                        outcome.digits,
                        refinement=expected_refinement_level,
                        ode_error_budget=validated_budget,
                        empirical_control_profile=empirical_profile,
                        calibration_receipt=empirical_receipt,
                    ).preview_root_request(
                        leaf.job,
                        amplitude,
                        predictor,
                        predictor_kind,
                    )
                except (JuliaResponseBackendError, ValueError) as error:
                    raise _UnauthenticatedComponentEvidence(
                        "campaign promoted canonical worker request is invalid"
                    ) from error
                expected_request["execution_resource"] = observed_resource
                if dict(binding) != expected_request:
                    raise _UnauthenticatedComponentEvidence(
                        "campaign promoted canonical worker request disagrees "
                        "with the active job"
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
    classified_kind: _PromotedStageKind | None = None
    if result_key == "result" and outcome.digits in (80, 120) and (
        payload.get("evidence_kind")
        in {
            _SELECTIVE_STAGE_EVIDENCE_KIND,
            _LEGACY_FULL_LADDER_EVIDENCE_KIND,
            _ANALYTIC_HORIZON_EVIDENCE_KIND,
            _FIXED_ROOT_EXTERIOR_EVIDENCE_KIND,
            _ROOT_SEALED_RESPONSE_REPAIR_EVIDENCE_KIND,
        }
        or result.component_scientific_identity
        in {
            PROMOTED_HORIZON_COMPONENT_IDENTITY,
            PROMOTED_HORIZON_COMPONENT_V2_IDENTITY,
            PROMOTED_HORIZON_COMPONENT_V3_IDENTITY,
            EXTERIOR_DERIVATIVE_COMPONENT_IDENTITY,
        }
    ):
        classified_kind, classified_result = _classify_promoted_stage(outcome)
        if classified_result.to_mapping() != result.to_mapping():
            raise _UnauthenticatedComponentEvidence(
                "campaign promoted stage classification changed its result"
            )
    historical_horizon = result.component_scientific_identity == (
        PROMOTED_HORIZON_COMPONENT_IDENTITY
    )
    bounded_horizon = result.component_scientific_identity in {
        PROMOTED_HORIZON_COMPONENT_V2_IDENTITY,
        PROMOTED_HORIZON_COMPONENT_V3_IDENTITY,
    }
    analytic_horizon = historical_horizon or bounded_horizon
    promoted_horizon_stage = analytic_horizon or (
        payload.get("evidence_kind")
        == "package-owned-julia-single-promoted-horizon-component"
        and result.mechanism_id == "horizon-admittance"
        and result.status is not ComponentStatus.CONVERGED
    )
    exterior_derivative = result.component_scientific_identity == (
        EXTERIOR_DERIVATIVE_COMPONENT_IDENTITY
    )
    fixed_root_exterior_stage = classified_kind is (
        _PromotedStageKind.FIXED_ROOT_EXTERIOR_DERIVATIVE
    )
    response_repair_stage = (
        payload.get("evidence_kind")
        == _ROOT_SEALED_RESPONSE_REPAIR_EVIDENCE_KIND
    )
    if exterior_derivative and classified_kind is not (
        _PromotedStageKind.FIXED_ROOT_EXTERIOR_DERIVATIVE
    ):
        raise _UnauthenticatedComponentEvidence(
            "campaign promoted exterior stage classification is invalid"
        )
    if historical_horizon and not (
        leaf.role == "primary"
        and leaf.mechanism_id == "horizon-admittance"
        and outcome.digits in (80, 120)
        and result.response_method == PROMOTED_HORIZON_RESPONSE_METHOD
        and result.response_uncertainty_status
        == UNCALIBRATED_ANALYTIC_RESPONSE
        and result.finite_amplitude_ladder_required is False
        and result.finite_amplitude_ladder_executed is False
        and result.finite_amplitude_readout_count == 0
        and not any(result.error_channel_applicability.values())
    ):
        raise _UnauthenticatedComponentEvidence(
            "campaign promoted analytic horizon identity is invalid"
        )
    if bounded_horizon and not (
        leaf.role in {"primary", "deep"}
        and leaf.mechanism_id == "horizon-admittance"
        and outcome.digits in (80, 120)
        and result.response_method in {
            PROMOTED_HORIZON_RESPONSE_METHOD_V2,
            PROMOTED_HORIZON_RESPONSE_METHOD_V3,
        }
        and result.response_uncertainty_status
        in {BOUNDED_ANALYTIC_RESPONSE, "UNBOUNDED_ANALYTIC_RESPONSE"}
        and result.finite_amplitude_ladder_required is False
        and result.finite_amplitude_ladder_executed is False
        and result.finite_amplitude_readout_count == 0
        and result.error_channel_applicability["resolution"]
        == (result.status is ComponentStatus.CONVERGED)
        and not any(
            applicable
            for name, applicable in result.error_channel_applicability.items()
            if name != "resolution"
        )
    ):
        raise _UnauthenticatedComponentEvidence(
            "campaign bounded promoted horizon identity is invalid"
        )
    if bounded_horizon:
        _validate_promoted_horizon_checkpoint_evidence_for_job(
            result, leaf.job
        )
    if exterior_derivative and not (
        leaf.mechanism_id.startswith("exterior-")
        and outcome.digits in (80, 120)
        and result.response_method == EXTERIOR_DERIVATIVE_METHOD
        and result.response_uncertainty_status
        in {BOUNDED_DERIVATIVE_RESPONSE, "UNBOUNDED_DERIVATIVE_RESPONSE"}
        and result.finite_amplitude_ladder_required is False
        and result.finite_amplitude_ladder_executed is False
        and result.finite_amplitude_readout_count == 0
    ):
        raise _UnauthenticatedComponentEvidence(
            "campaign promoted exterior derivative identity is invalid"
        )
    if result.status is ComponentStatus.CONVERGED:
        if analytic_horizon:
            body_is_valid = (
                result.usable
                and result.response is not None
                and result.signed_root_crosscheck is None
                and result.closed_form_response == result.response
                and result.convergence_basis
                == "PRIMARY_TRUNCATION_RESOLUTION_FIXED_ROOT"
                and not result.levels
            )
        elif exterior_derivative:
            body_is_valid = (
                result.usable
                and result.response is not None
                and result.signed_root_crosscheck is None
                and result.closed_form_response is None
                and result.convergence_basis
                == "FIXED_ROOT_REAL_H_H2_DERIVATIVE_DISK"
                and not result.levels
            )
        else:
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
            and result.convergence_basis in {
                "UNRESOLVED",
                "UNRESOLVED_FIXED_ROOT_DERIVATIVE",
            }
        )
    if not body_is_valid:
        raise ValueError(
            "campaign production component result status/body contract is invalid"
        )
    if promoted_horizon_stage and not response_repair_stage:
        required_payload_fields = {
            "evidence_kind",
            "result",
            "self_refinement_result",
            "self_refinement_skipped_reason",
            "scientific_runtime",
            "primary_root_predictor_source",
            "precision_ladder_discrepancy_applicable",
            "precision_ladder_discrepancy_reason",
        }
        failed_preflight_fields = {
            "failed_preflight_predecessor",
            "comparison_kind",
        }
        endpoint_arithmetic_fields = {"endpoint_arithmetic_predecessor"}
        if frozenset(payload) not in {
            frozenset(required_payload_fields),
            frozenset(required_payload_fields | {"promotion_decision"}),
            frozenset(required_payload_fields | failed_preflight_fields),
            frozenset(required_payload_fields | endpoint_arithmetic_fields),
        }:
            raise _UnauthenticatedComponentEvidence(
                "campaign promoted analytic horizon payload fields are invalid"
            )
        discrepancy_applicable = payload.get(
            "precision_ladder_discrepancy_applicable"
        )
        if (
            payload.get("self_refinement_result") is not None
            or payload.get("self_refinement_skipped_reason")
            != "NOT_REQUIRED_BY_V1_4_PROMOTED_ROOT_POLICY"
            or payload.get("primary_root_predictor_source")
            not in {
                "PREVIOUS_STAGE_BASELINE_OMEGA",
                "FAILED_80_REQUEST_BINARY64_BASELINE_OMEGA",
            }
            or type(discrepancy_applicable) is not bool
            or outcome.self_refinement_enclosed is not None
            or outcome.deep_diagnostics is not None
        ):
            raise _UnauthenticatedComponentEvidence(
                "campaign promoted analytic horizon execution evidence is invalid"
            )
        failed_preflight = "failed_preflight_predecessor" in payload
        endpoint_arithmetic = "endpoint_arithmetic_predecessor" in payload
        failed_request = failed_preflight or endpoint_arithmetic
        if failed_request != (
            payload.get("primary_root_predictor_source")
            == "FAILED_80_REQUEST_BINARY64_BASELINE_OMEGA"
        ) or (
            failed_preflight
            and payload.get("comparison_kind")
            != _FAILED_PREFLIGHT_SINGLE_HORIZON_KIND
        ) or (
            endpoint_arithmetic and "comparison_kind" in payload
        ):
            raise _UnauthenticatedComponentEvidence(
                "campaign promoted analytic predictor provenance is invalid"
            )
        discrepancy_reason = payload.get(
            "precision_ladder_discrepancy_reason"
        )
        if discrepancy_applicable:
            discrepancy_valid = (
                discrepancy_reason is None
                and result.response is not None
                and outcome.discrepancy_from_previous_abs is not None
                and type(outcome.discrepancy_enclosed) is bool
            )
        else:
            discrepancy_valid = (
                discrepancy_reason
                in {
                    "BINARY64_COMPONENT_RESPONSE_UNAVAILABLE",
                    "PREVIOUS_PROMOTED_COMPONENT_RESPONSE_UNAVAILABLE",
                }
                and outcome.discrepancy_from_previous_abs is None
                and outcome.discrepancy_enclosed is None
            )
        if not discrepancy_valid:
            raise _UnauthenticatedComponentEvidence(
                "campaign promoted analytic discrepancy evidence is invalid"
            )
        applicable_stage_families = set()
        if discrepancy_applicable:
            applicable_stage_families.add("precision-ladder-discrepancy")
        if bounded_horizon and result.status is ComponentStatus.CONVERGED:
            applicable_stage_families.add("resolution-angular-refinement")
        for channel in outcome.signed_error_channels:
            expected_derivation = (
                f"explicit-signed-{channel['family']}"
                if channel["family"] in applicable_stage_families
                else f"not-applicable-{channel['family']}"
            )
            if channel["provenance"]["derivation"] != expected_derivation:
                raise _UnauthenticatedComponentEvidence(
                    "campaign promoted analytic uncertainty applicability is invalid"
                )
    if response_repair_stage:
        required_payload_fields = {
            "evidence_kind",
            "result",
            "self_refinement_result",
            "self_refinement_skipped_reason",
            "scientific_runtime",
            "root_seal_sha256",
            "response_repair_scope",
            "precision_ladder_discrepancy_applicable",
            "precision_ladder_discrepancy_reason",
        }
        if (
            outcome.digits not in (80, 120)
            or frozenset(payload) != frozenset(required_payload_fields)
            or payload.get("self_refinement_result") is not None
            or payload.get("self_refinement_skipped_reason")
            != _FIXED_ROOT_EXTERIOR_SELF_REFINEMENT_SKIPPED_REASON
            or payload.get("response_repair_scope")
            not in {
                "fixed-root-domega-stencil-only/v1",
                "fixed-root-dc-stencil-only/v1",
                "fixed-root-domega-dc-stencils-only/v1",
            }
            or type(payload.get("precision_ladder_discrepancy_applicable"))
            is not bool
            or outcome.self_refinement_enclosed is not None
            or outcome.deep_diagnostics is not None
        ):
            raise _UnauthenticatedComponentEvidence(
                "campaign root-sealed response repair payload is invalid"
            )
        seal = _sealed_root_for_result(result)
        if seal is None:
            raise _UnauthenticatedComponentEvidence(
                "campaign root-sealed response repair lacks a root seal"
            )
        try:
            seal.validate_for(leaf.job)
        except ValueError as error:
            raise _UnauthenticatedComponentEvidence(
                "campaign root-sealed response repair seal is not admissible"
            ) from error
        if payload.get("root_seal_sha256") != seal.sha256:
            raise _UnauthenticatedComponentEvidence(
                "campaign root-sealed response repair digest is invalid"
            )
        if result.component_scientific_identity == EXTERIOR_DERIVATIVE_COMPONENT_IDENTITY:
            evidence = result.derivative_evidence
            scope = None if not isinstance(evidence, Mapping) else evidence.get(
                "response_repair_scope"
            )
            if not isinstance(scope, Mapping):
                raise _UnauthenticatedComponentEvidence(
                    "campaign root-sealed exterior repair scope is missing"
                )
            recomputed = scope.get("recomputed_families")
            reused = scope.get("reused_families")
            if not isinstance(recomputed, list) or not isinstance(reused, list):
                raise _UnauthenticatedComponentEvidence(
                    "campaign root-sealed exterior repair scope is invalid"
                )
            families = frozenset(recomputed)
            expected_scope = (
                "fixed-root-domega-stencil-only/v1"
                if families == {"frequency"}
                else "fixed-root-dc-stencil-only/v1"
                if families == {"coordinate"}
                else "fixed-root-domega-dc-stencils-only/v1"
                if families == {"frequency", "coordinate"}
                else None
            )
            if payload.get("response_repair_scope") != expected_scope:
                raise _UnauthenticatedComponentEvidence(
                    "campaign root-sealed exterior repair scope disagrees with samples"
                )
    if fixed_root_exterior_stage and not response_repair_stage:
        required_payload_fields = {
            "evidence_kind",
            "result",
            "self_refinement_result",
            "self_refinement_skipped_reason",
            "scientific_runtime",
            "primary_root_predictor_source",
            "precision_ladder_discrepancy_applicable",
            "precision_ladder_discrepancy_reason",
        }
        failed_preflight_fields = {
            "failed_preflight_predecessor",
            "comparison_kind",
        }
        allowed_payload_fields = {
            frozenset(required_payload_fields),
            frozenset(required_payload_fields | {"promotion_decision"}),
            frozenset(required_payload_fields | failed_preflight_fields),
        }
        if frozenset(payload) not in allowed_payload_fields:
            raise _UnauthenticatedComponentEvidence(
                "campaign fixed-root exterior payload fields are invalid"
            )
        failed_preflight = "failed_preflight_predecessor" in payload
        discrepancy_applicable = payload.get(
            "precision_ladder_discrepancy_applicable"
        )
        predictor_source = payload.get("primary_root_predictor_source")
        if (
            payload.get("self_refinement_result") is not None
            or payload.get("self_refinement_skipped_reason")
            != _FIXED_ROOT_EXTERIOR_SELF_REFINEMENT_SKIPPED_REASON
            or outcome.self_refinement_enclosed is not None
            or outcome.deep_diagnostics is not None
            or type(discrepancy_applicable) is not bool
            or predictor_source
            != (
                "FAILED_80_REQUEST_BINARY64_BASELINE_OMEGA"
                if failed_preflight
                else "PREVIOUS_STAGE_BASELINE_OMEGA"
            )
            or (
                failed_preflight
                and payload.get("comparison_kind")
                != _FAILED_PREFLIGHT_FIXED_ROOT_EXTERIOR_KIND
            )
        ):
            raise _UnauthenticatedComponentEvidence(
                "campaign fixed-root exterior execution evidence is invalid"
            )
        discrepancy_reason = payload.get(
            "precision_ladder_discrepancy_reason"
        )
        if discrepancy_applicable:
            discrepancy_valid = (
                discrepancy_reason is None
                and result.response is not None
                and outcome.discrepancy_from_previous_abs is not None
                and type(outcome.discrepancy_enclosed) is bool
            )
        else:
            discrepancy_valid = (
                discrepancy_reason
                in {
                    _BINARY64_RESPONSE_UNAVAILABLE_REASON,
                    _PREVIOUS_PROMOTED_RESPONSE_UNAVAILABLE_REASON,
                }
                and outcome.discrepancy_from_previous_abs is None
                and outcome.discrepancy_enclosed is None
            )
        if not discrepancy_valid:
            raise _UnauthenticatedComponentEvidence(
                "campaign fixed-root exterior discrepancy evidence is invalid"
            )
        family_sources = {
            "signed-root": "signed-root",
            "centred-step-amplitude": "axis",
            "refinement-holdout": "amplitude",
            "truncation": "truncation",
            "resolution-angular-refinement": "resolution",
            "continuation-seed-path": "seed-path",
        }
        precision_channel_abs = None
        identityless_typed_failure = (
            result.component_scientific_identity is None
            and result.status in _TYPED_FIXED_READOUT_FAILURE_STATUSES
        )
        for channel in outcome.signed_error_channels:
            family = channel["family"]
            if family in family_sources:
                applicable = (
                    False
                    if identityless_typed_failure
                    else result.error_channel_applicability[
                        family_sources[family]
                    ]
                )
            elif family == "precision-ladder-discrepancy":
                applicable = discrepancy_applicable
            else:
                applicable = False
            expected_derivation = (
                f"explicit-signed-{family}"
                if applicable
                else f"not-applicable-{family}"
            )
            if channel["provenance"]["derivation"] != expected_derivation:
                raise _UnauthenticatedComponentEvidence(
                    "campaign fixed-root exterior uncertainty applicability is invalid"
                )
            signed = complex(
                channel["signed_delta"]["real"],
                channel["signed_delta"]["imaginary"],
            )
            if not applicable and signed != 0.0j:
                raise _UnauthenticatedComponentEvidence(
                    "campaign fixed-root exterior not-applicable channel is nonzero"
                )
            if family == "precision-ladder-discrepancy":
                precision_channel_abs = abs(signed)
        expected_precision_abs = (
            None
            if not discrepancy_applicable
            else outcome.discrepancy_from_previous_abs
        )
        if (
            precision_channel_abs is None
            or (
                discrepancy_applicable
                and precision_channel_abs != expected_precision_abs
            )
        ):
            raise _UnauthenticatedComponentEvidence(
                "campaign fixed-root exterior precision channel is invalid"
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
    if analytic_horizon or exterior_derivative:
        expected_lineage["component_scientific_identity"] = (
            result.component_scientific_identity
        )
    if dict(result.lineage) != expected_lineage:
        raise _UnauthenticatedComponentEvidence(
            "campaign production component lineage is invalid"
        )
    if job.backend_identity.backend_id != RECORDED_REPLAY_BACKEND_ID:
        if (
            not analytic_horizon
            and not exterior_derivative
            and result.status is ComponentStatus.CONVERGED
            and len(result.levels) < 4
        ):
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


def _validate_fixed_readout_precision_comparison(
    outcome: StageOutcome,
    result: ComponentResult,
    predecessor: StageOutcome | None,
) -> bool:
    """Authenticate a promoted response comparison in response space."""

    component = outcome.component_result
    applicable = component.get(
        "precision_ladder_discrepancy_applicable"
    )
    if type(applicable) is not bool:
        raise _UnauthenticatedComponentEvidence(
            "fixed-readout precision applicability is invalid"
        )
    precision_channel = next(
        channel
        for channel in outcome.signed_error_channels
        if channel["family"] == "precision-ladder-discrepancy"
    )
    recorded_delta = complex(
        precision_channel["signed_delta"]["real"],
        precision_channel["signed_delta"]["imaginary"],
    )
    if predecessor is None:
        if applicable:
            raise _UnauthenticatedComponentEvidence(
                "fixed-readout response comparison predecessor is missing"
            )
        if (
            component.get("precision_ladder_discrepancy_reason")
            not in {
                _BINARY64_RESPONSE_UNAVAILABLE_REASON,
                _PREVIOUS_PROMOTED_RESPONSE_UNAVAILABLE_REASON,
            }
            or recorded_delta != 0.0j
            or outcome.discrepancy_from_previous_abs is not None
            or outcome.discrepancy_enclosed is not None
        ):
            raise _UnauthenticatedComponentEvidence(
                "fixed-readout inapplicable discrepancy is inconsistent"
            )
        return False

    raw_previous = predecessor.component_result.get("result")
    if not isinstance(raw_previous, Mapping):
        raise _UnauthenticatedComponentEvidence(
            "fixed-readout predecessor result is missing"
        )
    previous_result = ComponentResult.from_mapping(raw_previous)
    if previous_result.to_mapping() != raw_previous:
        raise _UnauthenticatedComponentEvidence(
            "fixed-readout predecessor is not canonical"
        )
    expected_applicable = (
        result.response is not None
        and previous_result.response is not None
    )
    if applicable is not expected_applicable:
        raise _UnauthenticatedComponentEvidence(
            "fixed-readout precision applicability is inconsistent"
        )
    expected_reason = (
        None
        if expected_applicable
        else (
            _BINARY64_RESPONSE_UNAVAILABLE_REASON
            if predecessor.digits == 64
            else _PREVIOUS_PROMOTED_RESPONSE_UNAVAILABLE_REASON
        )
    )
    if component.get("precision_ladder_discrepancy_reason") != expected_reason:
        raise _UnauthenticatedComponentEvidence(
            "fixed-readout precision reason is inconsistent"
        )
    if expected_applicable:
        assert result.response is not None
        assert previous_result.response is not None
        expected_delta = result.response - previous_result.response
        expected_abs = abs(expected_delta)
        expected_enclosed = expected_abs <= (
            sum(result.error_channels.values())
            + predecessor.local_disk_radius_abs
        )
        if (
            recorded_delta != expected_delta
            or outcome.discrepancy_from_previous_abs != expected_abs
            or outcome.discrepancy_enclosed is not expected_enclosed
        ):
            raise _UnauthenticatedComponentEvidence(
                "fixed-readout response discrepancy is inconsistent"
            )
    elif (
        recorded_delta != 0.0j
        or outcome.discrepancy_from_previous_abs is not None
        or outcome.discrepancy_enclosed is not None
    ):
        raise _UnauthenticatedComponentEvidence(
            "fixed-readout inapplicable discrepancy is nonzero"
        )
    return applicable


def _sealed_root_for_result(result: ComponentResult) -> PromotedRootSeal | None:
    """Return the persisted seal only when it exactly owns this baseline."""

    evidence = (
        result.derivative_evidence
        if result.derivative_evidence is not None
        else result.analytic_horizon_evidence
    )
    if not isinstance(evidence, Mapping):
        return None
    raw = evidence.get("root_seal")
    if raw is None:
        return None
    try:
        seal = PromotedRootSeal.from_mapping(raw)
    except ValueError as error:
        raise _UnauthenticatedComponentEvidence(
            "promoted root seal is invalid"
        ) from error
    if (
        evidence.get("root_seal_sha256") != seal.sha256
        or seal.root_readout.to_mapping() != result.baseline.to_mapping()
        or seal.leaf_id != result.leaf_id
        or seal.job_id != result.job_id
        or seal.mechanism_id != result.mechanism_id
    ):
        raise _UnauthenticatedComponentEvidence(
            "promoted root seal does not bind the component result"
        )
    return seal


def _root_sealed_response_migration_pending(
    result: ComponentResult,
) -> bool:
    """Recognize the sole schema-8 salvage marker without trusting response data."""

    evidence = result.derivative_evidence
    if not isinstance(evidence, Mapping):
        return False
    raw = evidence.get("stale_response_evidence")
    if not isinstance(raw, Mapping) or set(raw) != {
        "schema",
        "identity",
        "source_checkpoint_schema_version",
        "source_stage_sha256",
        "source_response_status",
    }:
        return False
    return (
        raw.get("schema") == _ROOT_SEAL_RESPONSE_MIGRATION_SCHEMA
        and raw.get("identity") == _ROOT_SEAL_RESPONSE_MIGRATION_IDENTITY
        and raw.get("source_checkpoint_schema_version") == 8
        and isinstance(raw.get("source_stage_sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", raw["source_stage_sha256"])
        is not None
        and raw.get("source_response_status")
        == ComponentStatus.DERIVATIVE_UNRESOLVED.value
        and result.status is ComponentStatus.DERIVATIVE_UNRESOLVED
        and result.response is None
        and evidence.get("determinant_count") == 0
        and evidence.get("fixed_root_samples") == []
        and evidence.get("failure_code")
        == "STALE_RESPONSE_EVIDENCE_DISCARDED"
        and _sealed_root_for_result(result) is not None
    )


_ROOT_PRECISION_PROMOTION_REASONS = frozenset({
    "ROOT_CONDITIONING_PRECISION_LIMITED",
    "ROOT_NOT_CONVERGED",
    "ROOT_PRIMARY_REJECTED",
    "ROOT_CORRECTION_EXCEEDS_TOLERANCE",
})


def _root_precision120_reason(
    outcome: StageOutcome,
    result: ComponentResult,
    root_seal: PromotedRootSeal | None,
) -> str | None:
    """Return an allowlisted root-only reason for an ordinary 120 root read.

    This intentionally reads only the persisted root readout.  Component
    status, response fields, derivative samples, response disks, validation,
    and checkpoint/persistence state are not inputs to the decision.  A
    branch mismatch remains fail-closed rather than being treated as an
    arithmetic retry request.
    """

    if outcome.digits != 80 or root_seal is not None:
        return None
    baseline = result.baseline
    if result.status is ComponentStatus.BRANCH_LOSS:
        return None
    if (
        baseline.root_reference_id != result.lineage.get("root_reference_id")
        or baseline.equation_id != result.lineage.get("equation_id")
    ):
        return None
    conditioning = baseline.numerical_conditioning
    if conditioning is not None and conditioning.precision_limited:
        return "ROOT_CONDITIONING_PRECISION_LIMITED"
    if not baseline.converged:
        return "ROOT_NOT_CONVERGED"
    primary = baseline.primary_acceptance
    if primary is None or not primary.accepted:
        return "ROOT_PRIMARY_REJECTED"
    if primary.correction_abs > primary.root_correction_tolerance:
        return "ROOT_CORRECTION_EXCEEDS_TOLERANCE"
    return None


def _root_requires_precision120(
    outcome: StageOutcome,
    result: ComponentResult,
    root_seal: PromotedRootSeal | None,
) -> bool:
    """Whether an ordinary root solve is authorized by root evidence alone."""

    reason = _root_precision120_reason(outcome, result, root_seal)
    if reason is not None and reason not in _ROOT_PRECISION_PROMOTION_REASONS:
        raise AssertionError("root promotion reason escaped its allowlist")
    return reason is not None


_FIXED_ROOT_FREQUENCY_STENCIL_ROLES = frozenset({
    "frequency-real-plus-h",
    "frequency-real-minus-h",
    "frequency-real-plus-h2",
    "frequency-real-minus-h2",
})
_FIXED_ROOT_COORDINATE_STENCIL_ROLES = frozenset({
    "coordinate-real-plus-h",
    "coordinate-real-minus-h",
    "coordinate-real-plus-h2",
    "coordinate-real-minus-h2",
})


def _validate_root_sealed_response_reuse_binding(
    predecessor: ComponentResult,
    repair: ComponentResult,
) -> None:
    """Bind every reused derivative family to its exact predecessor samples.

    A root seal authenticates where fixed-root work may occur.  It is not a
    licence to import a different historical response sample merely because it
    happens to be attached to the same root.  The repair record therefore has
    to retain byte-for-byte canonical samples from the immediately preceding
    promoted result for each family it says it reused.
    """

    if (
        predecessor.component_scientific_identity
        != EXTERIOR_DERIVATIVE_COMPONENT_IDENTITY
        or repair.component_scientific_identity
        != EXTERIOR_DERIVATIVE_COMPONENT_IDENTITY
    ):
        raise ValueError("root-sealed response reuse has an invalid component")
    predecessor_seal = _sealed_root_for_result(predecessor)
    repair_seal = _sealed_root_for_result(repair)
    if (
        predecessor_seal is None
        or repair_seal is None
        or predecessor_seal.to_mapping() != repair_seal.to_mapping()
    ):
        raise ValueError("root-sealed response reuse changed the sealed root")
    predecessor_evidence = predecessor.derivative_evidence
    repair_evidence = repair.derivative_evidence
    if not isinstance(predecessor_evidence, Mapping) or not isinstance(
        repair_evidence, Mapping
    ):
        raise ValueError("root-sealed response reuse evidence is missing")
    scope = repair_evidence.get("response_repair_scope")
    if not isinstance(scope, Mapping):
        raise ValueError("root-sealed response reuse scope is missing")
    reused = scope.get("reused_families")
    if not isinstance(reused, list):
        raise ValueError("root-sealed response reuse scope is invalid")
    roles_by_family = {
        "frequency": _FIXED_ROOT_FREQUENCY_STENCIL_ROLES,
        "coordinate": _FIXED_ROOT_COORDINATE_STENCIL_ROLES,
    }
    if any(family not in roles_by_family for family in reused):
        raise ValueError("root-sealed response reuse family is invalid")
    if not reused:
        return

    def samples_by_role(
        evidence: Mapping[str, object],
        *,
        subject: str,
    ) -> dict[str, dict[str, object]]:
        raw_samples = evidence.get("fixed_root_samples")
        if not isinstance(raw_samples, list):
            raise ValueError(
                f"root-sealed response {subject} samples are missing"
            )
        try:
            samples = tuple(
                FixedRootDeterminantSample.from_mapping(raw)
                for raw in raw_samples
            )
        except ValueError as error:
            raise ValueError(
                f"root-sealed response {subject} samples are invalid"
            ) from error
        canonical = [sample.to_mapping() for sample in samples]
        if canonical != raw_samples:
            raise ValueError(
                f"root-sealed response {subject} samples are not canonical"
            )
        by_role = {
            sample.readout_role: mapping
            for sample, mapping in zip(samples, canonical, strict=True)
        }
        if len(by_role) != len(samples):
            raise ValueError(
                f"root-sealed response {subject} samples have duplicate roles"
            )
        return by_role

    predecessor_by_role = samples_by_role(
        predecessor_evidence, subject="predecessor"
    )
    repair_by_role = samples_by_role(repair_evidence, subject="repair")
    for family in reused:
        for role in roles_by_family[family]:
            if (
                role not in predecessor_by_role
                or role not in repair_by_role
                or repair_by_role[role] != predecessor_by_role[role]
            ):
                raise ValueError(
                    "root-sealed response reused samples do not match "
                    "their predecessor"
                )


def _response_precision_limited_families(
    result: ComponentResult,
) -> frozenset[str]:
    """Return only complete fixed-root stencils that request more precision.

    A derivative estimate is an atomic h/h2 family.  We deliberately do not
    infer a response retry from an incomplete stencil, a zero disk, a missing
    determinant error model, or any component-level failure; those cases are
    terminal response evidence, not arithmetic authority for the root.
    """

    evidence = (
        result.derivative_evidence
        if result.derivative_evidence is not None
        else result.analytic_horizon_evidence
    )
    if not isinstance(evidence, Mapping):
        return frozenset()
    raw_samples = evidence.get("fixed_root_samples")
    if not isinstance(raw_samples, list):
        return frozenset()
    try:
        samples = tuple(
            FixedRootDeterminantSample.from_mapping(item)
            for item in raw_samples
        )
    except ValueError:
        return frozenset()
    by_role = {sample.readout_role: sample for sample in samples}
    if len(by_role) != len(samples):
        return frozenset()
    families: dict[str, frozenset[str]] = {
        "frequency": _FIXED_ROOT_FREQUENCY_STENCIL_ROLES,
        "coordinate": _FIXED_ROOT_COORDINATE_STENCIL_ROLES,
    }
    limited: set[str] = set()
    for family, roles in families.items():
        members = tuple(by_role.get(role) for role in roles)
        if any(member is None for member in members):
            continue
        typed_members = tuple(member for member in members if member is not None)
        if all(
            member.numerical_conditioning is not None
            and member.numerical_conditioning.precision_limited
            for member in typed_members
        ):
            limited.add(family)
    return frozenset(limited)


def _response_requires_precision120(
    outcome: StageOutcome,
    result: ComponentResult,
    *,
    root_sealed: bool,
    response_terminal: bool,
) -> bool:
    """Escalate response samples only on their own current-tier telemetry."""

    if (
        outcome.digits != 80
        or not root_sealed
        or response_terminal
    ):
        return False
    return bool(_response_precision_limited_families(result))


def _promoted_stage_semantics(
    outcome: StageOutcome,
    *,
    predecessor: StageOutcome | None = None,
) -> _PromotedStageSemantics:
    """Return the single authenticated interpretation of a promoted stage."""

    kind, result = _classify_promoted_stage(outcome)
    if kind is _PromotedStageKind.SELECTIVE_READOUT:
        return _PromotedStageSemantics(
            kind=kind,
            result=result,
            repeat_applicable=False,
            precision_ladder_applicable=False,
            root_sealed=False,
            root_requires_precision120=False,
            response_terminal_admissible=(
                result.status is ComponentStatus.CONVERGED
            ),
            response_requires_precision120=False,
            response_repair_precision_digits=None,
            response_repair_families=frozenset(),
            terminal_admissible=(result.status is ComponentStatus.CONVERGED),
            requires_precision120=False,
        )
    if kind is _PromotedStageKind.ANALYTIC_HORIZON:
        discrepancy_applicable = (
            _validate_fixed_readout_precision_comparison(
                outcome, result, predecessor
            )
        )
        root_seal = _sealed_root_for_result(result)
        response_families = _response_precision_limited_families(result)
        response_terminal = (
            result.status is ComponentStatus.CONVERGED
            and result.usable
            and result.response is not None
            and not response_families
        )
        root_requires = _root_requires_precision120(
            outcome, result, root_seal
        )
        response_requires = _response_requires_precision120(
            outcome,
            result,
            root_sealed=root_seal is not None,
            response_terminal=response_terminal,
        )
        return _PromotedStageSemantics(
            kind=kind,
            result=result,
            repeat_applicable=False,
            precision_ladder_applicable=discrepancy_applicable,
            root_sealed=root_seal is not None,
            root_requires_precision120=root_requires,
            response_terminal_admissible=response_terminal,
            response_requires_precision120=response_requires,
            response_repair_precision_digits=(
                120 if response_requires else None
            ),
            response_repair_families=(
                response_families if response_requires else frozenset()
            ),
            terminal_admissible=(root_seal is not None and response_terminal),
            requires_precision120=root_requires,
        )
    if kind is _PromotedStageKind.LEGACY_FULL_LADDER:
        terminal = (
            result.status is ComponentStatus.CONVERGED
            and (
                outcome.digits == 120
                or outcome.self_refinement_enclosed is True
            )
            and outcome.discrepancy_enclosed is True
        )
        requires120 = (
            outcome.digits == 80
            and (
                result.status is ComponentStatus.NOT_CONVERGED
                or (
                    result.status is ComponentStatus.CONVERGED
                    and (
                        outcome.self_refinement_enclosed is False
                        or outcome.discrepancy_enclosed is False
                    )
                )
            )
        )
        return _PromotedStageSemantics(
            kind=kind,
            result=result,
            repeat_applicable=(outcome.digits == 80),
            precision_ladder_applicable=True,
            root_sealed=False,
            root_requires_precision120=requires120,
            response_terminal_admissible=terminal,
            response_requires_precision120=False,
            response_repair_precision_digits=None,
            response_repair_families=frozenset(),
            terminal_admissible=terminal,
            requires_precision120=requires120,
        )

    discrepancy_applicable = _validate_fixed_readout_precision_comparison(
        outcome, result, predecessor
    )

    root_seal = _sealed_root_for_result(result)
    response_families = _response_precision_limited_families(result)
    response_terminal = (
        result.status is ComponentStatus.CONVERGED
        and result.usable
        and result.response is not None
        and result.response_uncertainty_status == BOUNDED_DERIVATIVE_RESPONSE
        and not response_families
        and (
            not discrepancy_applicable
            or outcome.discrepancy_enclosed is True
        )
    )
    root_requires = _root_requires_precision120(outcome, result, root_seal)
    response_requires = _response_requires_precision120(
        outcome,
        result,
        root_sealed=root_seal is not None,
        response_terminal=response_terminal,
    )
    migration_repair = _root_sealed_response_migration_pending(result)
    return _PromotedStageSemantics(
        kind=kind,
        result=result,
        repeat_applicable=False,
        precision_ladder_applicable=discrepancy_applicable,
        root_sealed=root_seal is not None,
        root_requires_precision120=root_requires,
        response_terminal_admissible=response_terminal,
        response_requires_precision120=response_requires,
        response_repair_precision_digits=(
            80 if migration_repair else 120 if response_requires else None
        ),
        response_repair_families=(
            frozenset({"frequency", "coordinate"})
            if migration_repair
            else response_families if response_requires else frozenset()
        ),
        terminal_admissible=(root_seal is not None and response_terminal),
        requires_precision120=root_requires,
    )


def _bind_fixed_readout_precision_comparison(
    outcome: StageOutcome,
    predecessor: StageOutcome,
) -> StageOutcome:
    """Derive the response-tier comparison from the two persisted results."""

    if outcome.component_result.get("evidence_kind") not in {
        _ANALYTIC_HORIZON_EVIDENCE_KIND,
        _FIXED_ROOT_EXTERIOR_EVIDENCE_KIND,
        _ROOT_SEALED_RESPONSE_REPAIR_EVIDENCE_KIND,
    }:
        return outcome
    raw_result = outcome.component_result.get("result")
    if not isinstance(raw_result, Mapping):
        raise _UnauthenticatedComponentEvidence(
            "fixed-readout result is missing"
        )
    result = ComponentResult.from_mapping(raw_result)
    if result.to_mapping() != raw_result:
        raise _UnauthenticatedComponentEvidence(
            "fixed-readout result is not canonical"
        )
    raw_previous = predecessor.component_result.get("result")
    if not isinstance(raw_previous, Mapping):
        raise _UnauthenticatedComponentEvidence(
            "fixed-readout predecessor result is missing"
        )
    previous_result = ComponentResult.from_mapping(raw_previous)
    if previous_result.to_mapping() != raw_previous:
        raise _UnauthenticatedComponentEvidence(
            "fixed-readout predecessor is not canonical"
        )
    applicable = (
        result.response is not None and previous_result.response is not None
    )
    delta = (
        result.response - previous_result.response
        if applicable
        else None
    )
    discrepancy = None if delta is None else abs(delta)
    enclosed = (
        None
        if discrepancy is None
        else discrepancy
        <= sum(result.error_channels.values())
        + predecessor.local_disk_radius_abs
    )
    component = dict(outcome.component_result)
    component.update({
        "precision_ladder_discrepancy_applicable": applicable,
        "precision_ladder_discrepancy_reason": (
            None
            if applicable
            else (
                _BINARY64_RESPONSE_UNAVAILABLE_REASON
                if predecessor.digits == 64
                else _PREVIOUS_PROMOTED_RESPONSE_UNAVAILABLE_REASON
            )
        ),
    })
    return replace(
        outcome,
        component_result=component,
        local_disk_radius_abs=(
            sum(result.error_channels.values())
            + (0.0 if discrepancy is None else discrepancy)
        ),
        signed_error_channels=_component_stage_signed_error_channels(
            component,
            result,
            repeat_applicable=False,
            precision_delta=0.0j if delta is None else delta,
            precision_ladder_applicable=applicable,
        ),
        self_refinement_enclosed=None,
        discrepancy_from_previous_abs=discrepancy,
        discrepancy_enclosed=enclosed,
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
    stage_predecessor: StageOutcome | None = None,
) -> tuple[CampaignExecutionAttempt, bool]:
    """Validate a self-contained 120-base/120-refinement recovery stage."""

    kind, classified_result = _classify_promoted_stage(outcome)
    if kind is _PromotedStageKind.ANALYTIC_HORIZON:
        analytic = classified_result
        component = outcome.component_result
        if (
            outcome.digits != 120
            or outcome.deep_diagnostics is not None
            or outcome.self_refinement_enclosed is not None
            or component.get("comparison_kind")
            != _FAILED_PREFLIGHT_SINGLE_HORIZON_KIND
        ):
            raise ValueError(
                "failed-preflight promoted horizon recovery fields are invalid"
            )
        predecessor = CampaignExecutionAttempt.from_mapping(
            component.get("failed_preflight_predecessor")
        )
        _validate_failed_preflight_predecessor(predecessor, leaf)
        predictor = _failed_preflight_primary_root_predictor(predecessor)
        request = predecessor.failure_receipt["failure"]["request_binding"]
        expected_predictor = {
            "real": format(predictor.real, ".17g"),
            "imaginary": format(predictor.imag, ".17g"),
        }
        if request.get("primary_predictor") != expected_predictor:
            raise ValueError(
                "failed-preflight promoted horizon predictor binding is invalid"
            )
        semantics = _promoted_stage_semantics(
            outcome, predecessor=stage_predecessor
        )
        if semantics.result != analytic:
            raise ValueError(
                "failed-preflight promoted horizon result changed"
            )
        return predecessor, semantics.terminal_admissible

    if kind is _PromotedStageKind.FIXED_ROOT_EXTERIOR_DERIVATIVE:
        fixed_result = classified_result
        component = outcome.component_result
        if (
            outcome.digits != 120
            or component.get("comparison_kind")
            != _FAILED_PREFLIGHT_FIXED_ROOT_EXTERIOR_KIND
        ):
            raise ValueError(
                "failed-preflight fixed-root exterior recovery fields are invalid"
            )
        predecessor = CampaignExecutionAttempt.from_mapping(
            component.get("failed_preflight_predecessor")
        )
        _validate_failed_preflight_predecessor(predecessor, leaf)
        predictor = _failed_preflight_exterior_root_predictor(predecessor)
        expected_predictor = {
            "real": format(predictor.real, ".17g"),
            "imaginary": format(predictor.imag, ".17g"),
        }
        receipt = fixed_result.baseline.worker_response_receipt
        request = (
            None
            if not isinstance(receipt, Mapping)
            else receipt.get("request_binding")
        )
        if (
            not isinstance(request, Mapping)
            or request.get("amplitude")
            != {"real": "0", "imaginary": "0"}
            or request.get("primary_predictor") != expected_predictor
            or "primary_predictor_kind" in request
        ):
            raise ValueError(
                "failed-preflight fixed-root exterior predictor binding is invalid"
            )
        semantics = _promoted_stage_semantics(
            outcome, predecessor=stage_predecessor
        )
        if semantics.result != fixed_result:
            raise ValueError(
                "failed-preflight fixed-root exterior result changed"
            )
        return predecessor, semantics.terminal_admissible

    if kind is _PromotedStageKind.SELECTIVE_READOUT:
        raise ValueError(
            "selective evidence cannot satisfy failed-preflight recovery"
        )

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
    leaf: CampaignLeafPlan,
    record: CampaignLeafRecord,
    stages: tuple[StageOutcome, ...],
    production_flags: tuple[bool, ...],
    *,
    promotion_decision_required: bool,
    failed_preflight_pending_allowed: bool,
    allow_historical_promotion_decision: bool,
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
    semantics80 = (
        _promoted_stage_semantics(precision80, predecessor=first)
        if isinstance(precision80.component_result.get("result"), Mapping)
        else None
    )
    fixed_readout80 = (
        semantics80 is not None
        and semantics80.kind
        in {
            _PromotedStageKind.ANALYTIC_HORIZON,
            _PromotedStageKind.FIXED_ROOT_EXTERIOR_DERIVATIVE,
        }
    )
    if fixed_readout80:
        if (
            precision80.deep_diagnostics is not None
            or precision80.self_refinement_enclosed is not None
        ):
            raise ValueError(
                "campaign promoted fixed-readout PRIMARY 80-digit evidence is incomplete"
            )
    elif (
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
        _primary_precision120_decision(
            precision80, predecessor=first
        ),
        required=promotion_decision_required,
        allow_historical=allow_historical_promotion_decision,
    )
    root_requires120 = _primary_requires_precision120(
        precision80, predecessor=first
    )
    response_repair_digits = (
        None
        if semantics80 is None
        else semantics80.response_repair_precision_digits
    )
    response_requires_repair = bool(
        semantics80 is not None
        and semantics80.root_sealed
        and not semantics80.root_requires_precision120
        and response_repair_digits is not None
    )
    required_next_digits = (
        precision120_digits if root_requires120 else response_repair_digits
    )
    if not (root_requires120 or response_requires_repair):
        expected_state = (
            "PRODUCED"
            if (
                semantics80.terminal_admissible
                if semantics80 is not None
                else (
                    bool(precision80.self_refinement_enclosed)
                    and bool(precision80.discrepancy_enclosed)
                )
            )
            else "UNRESOLVED"
        )
        if (
            len(stages) != 2
            or record.state != expected_state
            or record.missing_precision_digits is not None
        ):
            raise ValueError("campaign terminal PRIMARY 80-digit state is inconsistent")
        return all(production_flags)

    if len(stages) == 2:
        assert required_next_digits is not None
        pending = (
            record.state == "IN_PROGRESS"
            and record.missing_precision_digits is None
        ) or (
            record.state == "MISSING_PRECISION"
            and record.missing_precision_digits == required_next_digits
        )
        if not pending:
            raise ValueError(
                "campaign promoted PRIMARY leaf is missing its root/response repair"
            )
        return all(production_flags)

    assert required_next_digits is not None
    repair = stages[2]
    if repair.digits != required_next_digits:
        raise ValueError("campaign PRIMARY repair precision is invalid")
    if repair.digits == 120:
        _validate_precision120(repair, predecessor=precision80)
    if not production_flags[2]:
        raise ValueError(
            "campaign promoted PRIMARY repair lacks canonical production evidence"
        )
    if response_requires_repair and (
        repair.component_result.get("evidence_kind")
        != _ROOT_SEALED_RESPONSE_REPAIR_EVIDENCE_KIND
    ):
        raise ValueError("campaign PRIMARY response repair used a root stage")
    if (
        response_requires_repair
        and semantics80 is not None
        and semantics80.kind
        is _PromotedStageKind.FIXED_ROOT_EXTERIOR_DERIVATIVE
    ):
        raw_predecessor = precision80.component_result.get("result")
        raw_repair = repair.component_result.get("result")
        if not isinstance(raw_predecessor, Mapping) or not isinstance(
            raw_repair, Mapping
        ):
            raise ValueError(
                "campaign PRIMARY root-sealed response results are missing"
            )
        _validate_root_sealed_response_reuse_binding(
            ComponentResult.from_mapping(raw_predecessor),
            ComponentResult.from_mapping(raw_repair),
        )
    if (
        record.state != _primary_precision120_terminal_state(
            repair, predecessor=precision80
        )
        or record.missing_precision_digits is not None
    ):
        raise ValueError("campaign PRIMARY repair terminal state is inconsistent")
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
        provenance_identity = provenance["precision_factory_identity"]
        current_factory = provenance_identity == factory_identity.to_mapping()
        preserved_schema7_binary64 = (
            checkpoint_schema_version == CAMPAIGN_CHECKPOINT_SCHEMA_VERSION
            and stage.outcome.digits == 64
            and provenance_identity
            == _schema7_precision_factory_identity().to_mapping()
        )
        if not (current_factory or preserved_schema7_binary64):
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
    selective_validations = tuple(
        _validate_selective_stage(
            leaf,
            stage,
            stages[0] if index > 0 else None,
        )
        for index, stage in enumerate(stages)
    )
    production_flags = tuple(
        validation is not None
        or _validate_component_result(
            leaf,
            stage,
            allow_historical_conditioning_absence=(
                allow_historical_conditioning_absence
            ),
        )
        for stage, validation in zip(stages, selective_validations)
    )
    for previous, promoted in zip(stages, stages[1:]):
        _validate_fixed_readout_predictor_binding(
            previous,
            promoted,
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
    if len(stages) == 2 and selective_validations[1] is not None:
        _, selective_produced = selective_validations[1]
        if (
            leaf.role != "primary"
            or not _primary_binary64_promotes(
                first, production=production_flags[0]
            )
            or record.state
            != ("PRODUCED" if selective_produced else "UNRESOLVED")
            or record.missing_precision_digits is not None
            or record.trigger_ids
            or record.sentinel
            or record.sentinel_comparison is not None
        ):
            raise ValueError(
                "campaign selective semantic terminal state is inconsistent"
            )
        return all(production_flags)
    if digits == (64, 120):
        endpoint_predecessor = _embedded_endpoint_arithmetic_predecessor(
            stages[1], leaf
        )
        if endpoint_predecessor is not None:
            _validate_precision120(stages[1], predecessor=stages[0])
            if not all(production_flags):
                raise ValueError(
                    "endpoint-arithmetic recovery lacks canonical production "
                    "evidence"
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
                    leaf.role == "deep"
                    and record.trigger_ids == trigger_ids
                    and record.sentinel is sentinel
                    and record.sentinel_comparison is None
                )
            expected_state = _endpoint_arithmetic_terminal_state(
                leaf,
                stages[1],
                predecessor=stages[0],
                sentinel=record.sentinel,
            )
            if (
                not role_fields_valid
                or record.state != expected_state
                or record.missing_precision_digits is not None
            ):
                raise ValueError(
                    "endpoint-arithmetic recovery terminal state is invalid"
                )
            return True
        if checkpoint_schema_version < _FAILED_PREFLIGHT_CHECKPOINT_SCHEMA_VERSION:
            raise ValueError(
                "historical checkpoints cannot claim failed-preflight recovery"
            )
        if leaf.role == "control":
            raise ValueError("control leaves cannot use failed-preflight recovery")
        _, recovery_produced = _validate_failed_preflight_recovery_stage(
            leaf, stages[1], stages[0]
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
            leaf,
            record,
            stages,
            production_flags,
            promotion_decision_required=(
                checkpoint_schema_version
                >= _PROMOTION_DECISION_CHECKPOINT_SCHEMA_VERSION
            ),
            failed_preflight_pending_allowed=(
                checkpoint_schema_version
                >= _FAILED_PREFLIGHT_CHECKPOINT_SCHEMA_VERSION
            ),
            allow_historical_promotion_decision=(
                checkpoint_schema_version
                < CAMPAIGN_CHECKPOINT_SCHEMA_VERSION
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
            checkpoint_schema_version
            >= _FAILED_PREFLIGHT_CHECKPOINT_SCHEMA_VERSION
            and record.state == "MISSING_PRECISION"
            and record.missing_precision_digits == 120
        )
        if not pending or record.sentinel_comparison is not None:
            raise ValueError("campaign promoted deep leaf is missing its 80-digit stage")
        return production

    precision80 = stages[1]
    semantics80 = (
        _promoted_stage_semantics(precision80, predecessor=first)
        if isinstance(precision80.component_result.get("result"), Mapping)
        else None
    )
    fixed_readout80 = (
        semantics80 is not None
        and semantics80.kind
        in {
            _PromotedStageKind.ANALYTIC_HORIZON,
            _PromotedStageKind.FIXED_ROOT_EXTERIOR_DERIVATIVE,
        }
    )
    if fixed_readout80:
        _validate_precision120(precision80, predecessor=first)
    elif (
        precision80.deep_diagnostics is not None
        or precision80.self_refinement_enclosed is None
        or precision80.discrepancy_from_previous_abs is None
        or precision80.discrepancy_enclosed is None
    ):
        raise ValueError("campaign 80-digit evidence is incomplete")
    expected_comparison = None
    false_negative = False
    if sentinel:
        if precision80.discrepancy_from_previous_abs is not None:
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
    decision = (
        _deep_precision120_decision(
            precision80,
            sentinel_false_negative=True,
            predecessor=first,
        )
        if false_negative
        else _primary_precision120_decision(
            precision80, predecessor=first
        )
        if (
            semantics80 is not None
            and semantics80.kind is _PromotedStageKind.ANALYTIC_HORIZON
        )
        else _deep_precision120_decision(
            precision80,
            sentinel_false_negative=False,
            predecessor=first,
        )
    )
    _validate_attached_promotion_decision(
        precision80,
        decision,
        required=(
            checkpoint_schema_version
            >= _PROMOTION_DECISION_CHECKPOINT_SCHEMA_VERSION
        ),
        allow_historical=(
            checkpoint_schema_version < CAMPAIGN_CHECKPOINT_SCHEMA_VERSION
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
            _validate_precision120(stages[2], predecessor=precision80)
        return production
    if not requires120:
        if (
            len(stages) != 2
            or record.state
            != (
                "PRODUCED"
                if (
                    semantics80.terminal_admissible
                    if semantics80 is not None
                    else (
                        bool(precision80.self_refinement_enclosed)
                        and bool(precision80.discrepancy_enclosed)
                    )
                )
                else "UNRESOLVED"
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
    _validate_precision120(precision120, predecessor=precision80)
    semantics120 = (
        _promoted_stage_semantics(
            precision120, predecessor=precision80
        )
        if isinstance(precision120.component_result.get("result"), Mapping)
        else None
    )
    if (
        record.state
        != (
            _primary_precision120_terminal_state(
                precision120, predecessor=precision80
            )
            if semantics120 is not None
            else _terminal_state(
                precision120, enclosed=bool(precision120.discrepancy_enclosed)
            )
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


def validate_campaign_recovery_record(
    plan: CampaignPlan,
    leaf_id: str,
    value: Mapping[str, object],
) -> None:
    """Authenticate one terminal recovery candidate against the current plan."""

    leaf_by_id = {leaf.leaf_id: leaf for leaf in plan.leaves}
    leaf = leaf_by_id.get(leaf_id)
    if leaf is None:
        raise ValueError("recovery record is outside the campaign plan")
    if value.get("schema") == "windows-solver.schema11-numerical-record/1":
        if leaf.mechanism_id == "horizon-admittance":
            validate_schema11_horizon_record(plan, leaf, value)
        else:
            _validate_schema11_survey_record(plan, leaf, value)
        return
    record = CampaignLeafRecord.from_mapping(value)
    if record.to_mapping() != value:
        raise ValueError("recovery record is not canonical")
    _validate_cacheable_leaf_record(plan, leaf, record)


def _horizon_complex_from_mapping(value: object, subject: str) -> complex:
    if not isinstance(value, Mapping) or set(value) != {"real", "imaginary"}:
        raise ValueError(f"{subject} is invalid")
    try:
        converted = complex(float(value["real"]), float(value["imaginary"]))
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"{subject} is invalid") from error
    if not math.isfinite(converted.real) or not math.isfinite(converted.imag):
        raise ValueError(f"{subject} is invalid")
    return converted


def _validate_schema11_horizon_stage(
    plan: CampaignPlan,
    leaf: CampaignLeafPlan,
    stage: Mapping[str, object],
) -> tuple[ComponentResult, Mapping[str, object] | None]:
    expected_fields = {
        "schema",
        "operation_identity",
        "precision_tier",
        "component_result",
        "response_disk",
        "numerical_state",
        "stage_sha256",
    }
    if set(stage) != expected_fields:
        raise ValueError("schema-11 horizon stage fields are invalid")
    if stage["schema"] != HORIZON_SCREENING_STAGE_SCHEMA:
        raise ValueError("schema-11 horizon stage schema is invalid")
    if stage["precision_tier"] not in {"binary64", "BF80"}:
        raise ValueError("schema-11 horizon precision tier is invalid")
    if (
        not isinstance(stage["operation_identity"], str)
        or not stage["operation_identity"]
        or not isinstance(stage["numerical_state"], str)
        or not stage["numerical_state"]
    ):
        raise ValueError("schema-11 horizon stage identity is invalid")
    content = {
        key: value for key, value in stage.items() if key != "stage_sha256"
    }
    if stage["stage_sha256"] != _sha256(content):
        raise ValueError("schema-11 horizon stage digest is invalid")
    payload = stage["component_result"]
    if not isinstance(payload, Mapping):
        raise ValueError("schema-11 horizon component result is invalid")
    raw_result = payload.get("result")
    if not isinstance(raw_result, Mapping):
        raise ValueError("schema-11 horizon component result body is invalid")
    try:
        result = ComponentResult.from_mapping(raw_result)
    except (TypeError, ValueError) as error:
        raise ValueError("schema-11 horizon component result is invalid") from error
    if result.to_mapping() != raw_result:
        raise ValueError("schema-11 horizon component result is not canonical")
    if (
        result.leaf_id != leaf.leaf_id
        or result.job_id != leaf.job.job_id
        or result.mechanism_id != leaf.mechanism_id
        or stage["numerical_state"] != result.status.value
    ):
        raise ValueError("schema-11 horizon component identity is invalid")
    expected_lineage = {
        "leaf_id": leaf.job.leaf_id,
        "root_reference_id": leaf.job.root.root_reference_id,
        "root_identity_sha256": leaf.job.root.identity_sha256,
        "policy_sha256": leaf.job.policy.identity_sha256,
        "backend_identity_sha256": leaf.job.backend_identity.identity_sha256,
        "equation_id": leaf.job.equation_id,
        "sampling_coordinate": leaf.job.sampling_coordinate.to_mapping(),
        "source_root_mapping": (
            None
            if leaf.job.source_root_mapping is None
            else dict(leaf.job.source_root_mapping)
        ),
    }
    observed_lineage = dict(result.lineage)
    if "component_scientific_identity" in observed_lineage:
        expected_lineage["component_scientific_identity"] = (
            result.component_scientific_identity
        )
    if observed_lineage != expected_lineage:
        raise ValueError("schema-11 horizon component lineage is invalid")
    precision_tier = stage["precision_tier"]
    if precision_tier == "binary64":
        if (
            result.component_scientific_identity
            != "binary64-horizon-analytic-component/v1"
            or result.response_method
            != "binary64-fixed-root-horizon-response/v1"
            or payload.get("evidence_kind")
            != "package-owned-binary64-horizon-analytic-component"
        ):
            raise ValueError(
                "schema-11 horizon precision tier component identity is invalid"
            )
    else:
        promoted_methods = dict((
            (
                PROMOTED_HORIZON_COMPONENT_V2_IDENTITY,
                PROMOTED_HORIZON_RESPONSE_METHOD_V2,
            ),
            (
                PROMOTED_HORIZON_COMPONENT_V3_IDENTITY,
                PROMOTED_HORIZON_RESPONSE_METHOD_V3,
            ),
        ))
        if (
            promoted_methods.get(result.component_scientific_identity)
            != result.response_method
            or payload.get("evidence_kind")
            != "package-owned-julia-promoted-horizon-survey"
        ):
            raise ValueError(
                "schema-11 horizon precision tier component identity is invalid"
            )
    expected_source_root_mapping = (
        None
        if leaf.job.source_root_mapping is None
        else dict(leaf.job.source_root_mapping)
    )
    for readout in result.raw_readouts:
        if (
            readout.root_reference_id != leaf.job.root.root_reference_id
            or readout.branch_id != leaf.job.root.branch_id
            or readout.equation_id != leaf.job.equation_id
            or readout.source_root_mapping != expected_source_root_mapping
        ):
            raise ValueError(
                "schema-11 horizon component root readout identity is invalid"
            )
    disk = stage["response_disk"]
    if result.response is None:
        if disk is not None:
            raise ValueError("unbounded horizon stage cannot contain a response disk")
    else:
        if not isinstance(disk, Mapping) or set(disk) != {
            "centre", "radius", "exact_zero_radius"
        }:
            raise ValueError("schema-11 horizon response disk is invalid")
        centre = _horizon_complex_from_mapping(
            disk["centre"], "schema-11 horizon response disk centre"
        )
        try:
            radius = float(disk["radius"])
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError("schema-11 horizon response disk radius is invalid") from error
        if not math.isfinite(radius) or radius < 0.0:
            raise ValueError("schema-11 horizon response disk radius is invalid")
        if not isinstance(disk["exact_zero_radius"], bool):
            raise ValueError("schema-11 horizon response disk zero flag is invalid")
        if centre != result.response:
            raise ValueError("schema-11 horizon response disk centre is not result-bound")
        if radius == 0.0 and disk["exact_zero_radius"] is not True:
            raise ValueError("schema-11 horizon zero-radius provenance is invalid")
        if radius != 0.0 and disk["exact_zero_radius"] is not False:
            raise ValueError("schema-11 horizon exact-zero provenance is invalid")
    return result, disk


def validate_schema11_horizon_stage(
    plan: CampaignPlan,
    leaf: CampaignLeafPlan,
    value: Mapping[str, object],
) -> None:
    """Validate one durable schema-11 horizon stage independently."""

    _validate_schema11_horizon_stage(plan, leaf, value)


def validate_schema11_horizon_record(
    plan: CampaignPlan,
    leaf: CampaignLeafPlan,
    value: Mapping[str, object],
) -> None:
    """Authenticate a new schema-11 horizon record without legacy fields."""

    expected_fields = {
        "schema",
        "leaf_id",
        "role",
        "state",
        "scientific_computation_identity",
        "retained_centre",
        "stages",
        "record_sha256",
    }
    if set(value) != expected_fields:
        raise ValueError("schema-11 horizon record fields are invalid")
    if leaf.mechanism_id != "horizon-admittance":
        raise ValueError("schema-11 horizon record leaf mechanism is invalid")
    if (
        value["schema"] != _SCHEMA11_NUMERICAL_RECORD
        or value["leaf_id"] != leaf.leaf_id
        or value["role"] != leaf.role
        or value["scientific_computation_identity"]
        != scientific_computation_identity_sha256(plan, leaf)
        or value["state"] not in {"PRODUCED", "UNRESOLVED", "REJECTED"}
    ):
        raise ValueError("schema-11 horizon record identity is invalid")
    content = {key: item for key, item in value.items() if key != "record_sha256"}
    if value["record_sha256"] != _sha256(content):
        raise ValueError("schema-11 horizon record digest is invalid")
    retained = value["retained_centre"]
    retained_centre = (
        None
        if retained is None
        else _horizon_complex_from_mapping(retained, "schema-11 horizon retained centre")
    )
    stages = value["stages"]
    if not isinstance(stages, list) or not stages or len(stages) > 2:
        raise ValueError("schema-11 horizon stages are invalid")
    stage_values = tuple(
        _validate_schema11_horizon_stage(plan, leaf, stage)
        for stage in stages
        if isinstance(stage, Mapping)
    )
    if len(stage_values) != len(stages):
        raise ValueError("schema-11 horizon stage is invalid")
    tiers = tuple(str(stage["precision_tier"]) for stage in stages)
    if tiers not in {("binary64",), ("BF80",), ("binary64", "BF80")}:
        raise ValueError("schema-11 horizon precision order is invalid")
    terminal_result, terminal_disk = stage_values[-1]
    bounded = terminal_result.response is not None
    expected_state = "PRODUCED" if bounded else "UNRESOLVED"
    if value["state"] == "PRODUCED" and not bounded:
        raise ValueError("schema-11 horizon produced state lacks a response")
    if value["state"] in {"UNRESOLVED", "REJECTED"} and bounded:
        raise ValueError("schema-11 horizon nonterminal state has a response")
    if value["state"] == "PRODUCED" and expected_state != value["state"]:
        raise ValueError("schema-11 horizon terminal state is invalid")
    if terminal_disk is None:
        if retained_centre is not None:
            raise ValueError("schema-11 horizon retained centre is not null")
    elif retained_centre != _horizon_complex_from_mapping(
        terminal_disk["centre"], "schema-11 horizon terminal centre"
    ):
        raise ValueError("schema-11 horizon retained centre is not terminal-bound")


def _validate_schema11_survey_record(
    plan: CampaignPlan,
    leaf: CampaignLeafPlan,
    value: Mapping[str, object],
) -> None:
    fields = {
        "schema",
        "leaf_id",
        "role",
        "state",
        "scientific_computation_identity",
        "retained_centre",
        "stages",
        "record_sha256",
    }
    if set(value) != fields:
        raise ValueError("schema-11 survey record fields are invalid")
    if (
        value["leaf_id"] != leaf.leaf_id
        or value["role"] != leaf.role
        or value["state"] != "PRODUCED"
        or value["scientific_computation_identity"]
        != scientific_computation_identity_sha256(plan, leaf)
    ):
        raise ValueError("schema-11 survey record identity is invalid")
    content = {key: value[key] for key in value if key != "record_sha256"}
    if value["record_sha256"] != _sha256(content):
        raise ValueError("schema-11 survey record digest is invalid")
    centre = value["retained_centre"]
    if not isinstance(centre, Mapping) or set(centre) != {"real", "imaginary"}:
        raise ValueError("schema-11 survey centre is invalid")
    try:
        response = complex(float(centre["real"]), float(centre["imaginary"]))
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("schema-11 survey centre is invalid") from error
    if not math.isfinite(response.real) or not math.isfinite(response.imag):
        raise ValueError("schema-11 survey centre is invalid")
    stages = value["stages"]
    if not isinstance(stages, list) or len(stages) != 1:
        raise ValueError("schema-11 survey stage is invalid")
    stage = stages[0]
    if not isinstance(stage, Mapping):
        raise ValueError("schema-11 survey stage is invalid")
    expected_stage_fields = {
        "schema",
        "operation_identity",
        "precision_tier",
        "fixed_root",
        "root_seal_sha256",
        "branch_identity",
        "batch",
        "response_disk",
        "frequency_derivative_disk",
        "coordinate_derivative_disk",
        "root_correction_upper_bound",
        "determinant_certificate_status",
        "stage_sha256",
    }
    if (
        set(stage) != expected_stage_fields
        or stage["schema"] != "windows-solver.fixed-root-screening-stage/1"
        or stage["branch_identity"] != leaf.job.root.branch_id
        or stage["determinant_certificate_status"] != "not-claimed"
    ):
        raise ValueError("schema-11 survey stage contract is invalid")
    stage_content = {key: stage[key] for key in stage if key != "stage_sha256"}
    if stage["stage_sha256"] != _sha256(stage_content):
        raise ValueError("schema-11 survey stage digest is invalid")
    if not isinstance(stage["root_seal_sha256"], str) or re.fullmatch(
        r"[0-9a-f]{64}", stage["root_seal_sha256"]
    ) is None:
        raise ValueError("schema-11 survey root seal is invalid")
    batch = stage["batch"]
    response_disk = stage["response_disk"]
    if (
        not isinstance(batch, Mapping)
        or batch.get("leaf_id") != leaf.leaf_id
        or batch.get("job_id") != leaf.job.job_id
        or batch.get("mechanism_id") != leaf.mechanism_id
        or batch.get("branch_identity") != leaf.job.root.branch_id
        or not isinstance(response_disk, Mapping)
        or response_disk.get("centre") != centre
    ):
        raise ValueError("schema-11 survey batch binding is invalid")


def _authenticate_solved_leaf_hit(
    plan: CampaignPlan,
    leaf: CampaignLeafPlan,
    store: SolvedLeafStore,
    lookup: SolvedLeafLookup,
    *,
    scientific_execution_contract: Mapping[str, object] | None = None,
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
        _validate_record_scientific_execution_contract(
            leaf, record, scientific_execution_contract
        )
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
    *,
    scientific_execution_contract: Mapping[str, object] | None = None,
) -> SolvedLeafLookup:
    identity = scientific_computation_identity_sha256(
        plan,
        leaf,
        scientific_execution_contract=scientific_execution_contract,
    )
    current = _authenticate_solved_leaf_hit(
        plan,
        leaf,
        store,
        store.lookup(identity, leaf.leaf_id),
        scientific_execution_contract=scientific_execution_contract,
    )
    if current.status in {
        SolvedLeafLookupStatus.HIT,
        SolvedLeafLookupStatus.CORRUPT,
    }:
        return current
    if scientific_execution_contract is not None:
        # Budget-free predecessor identities are valid historical evidence but
        # cannot be migrated across an explicitly trusted execution contract.
        return current
    if leaf.role != "primary":
        return current

    predecessor_identities = (
        _multi_readout_primary_scientific_computation_identity_sha256(
            plan, leaf
        ),
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


def _validate_precision120(
    outcome: StageOutcome,
    *,
    predecessor: StageOutcome | None = None,
) -> None:
    if not isinstance(outcome.component_result.get("result"), Mapping):
        if (
            outcome.deep_diagnostics is not None
            or outcome.self_refinement_enclosed is not None
            or outcome.discrepancy_from_previous_abs is None
            or outcome.discrepancy_enclosed is None
        ):
            raise ValueError("campaign 120-digit evidence is incomplete")
        return
    semantics = _promoted_stage_semantics(
        outcome, predecessor=predecessor
    )
    if semantics.kind in {
        _PromotedStageKind.ANALYTIC_HORIZON,
        _PromotedStageKind.FIXED_ROOT_EXTERIOR_DERIVATIVE,
    }:
        applicable = outcome.component_result.get(
            "precision_ladder_discrepancy_applicable"
        )
        if (
            outcome.deep_diagnostics is not None
            or outcome.self_refinement_enclosed is not None
            or type(applicable) is not bool
            or (
                applicable
                and (
                    outcome.discrepancy_from_previous_abs is None
                    or outcome.discrepancy_enclosed is None
                )
            )
            or (
                not applicable
                and (
                    outcome.discrepancy_from_previous_abs is not None
                    or outcome.discrepancy_enclosed is not None
                )
            )
        ):
            raise ValueError(
                "campaign promoted fixed-readout evidence is incomplete"
            )
        return
    if semantics.kind is _PromotedStageKind.SELECTIVE_READOUT:
        raise ValueError("selective promoted evidence cannot be a 120-digit stage")
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
    if outcome.component_result.get("evidence_kind") in {
        _ANALYTIC_HORIZON_EVIDENCE_KIND,
        _FIXED_ROOT_EXTERIOR_EVIDENCE_KIND,
    }:
        outcome = _bind_fixed_readout_precision_comparison(
            outcome, record.stages[0].outcome
        )
    if not _validate_component_result(
        leaf, outcome, allow_historical_conditioning_absence=False
    ):
        raise ValueError(
            "failed-preflight recovery lacks canonical base evidence"
        )
    embedded, recovery_produced = _validate_failed_preflight_recovery_stage(
        leaf, outcome, record.stages[0].outcome
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


def _endpoint_arithmetic_recovery_record(
    plan: CampaignPlan,
    available: PrecisionCapabilities,
    leaf: CampaignLeafPlan,
    record: CampaignLeafRecord,
    outcome: StageOutcome,
    predecessor: CampaignExecutionAttempt,
) -> CampaignLeafRecord:
    """Validate a direct 120-digit retry after typed endpoint arithmetic loss."""

    if not isinstance(outcome, StageOutcome) or outcome.digits != 120:
        raise ValueError(
            "campaign backend returned invalid endpoint-arithmetic "
            "120-digit evidence"
        )
    outcome = _stage_with_endpoint_arithmetic_predecessor(
        outcome, predecessor
    )
    outcome = _bind_fixed_readout_precision_comparison(
        outcome, record.stages[0].outcome
    )
    embedded = _embedded_endpoint_arithmetic_predecessor(outcome, leaf)
    if embedded is None or embedded.to_mapping() != predecessor.to_mapping():
        raise ValueError("endpoint-arithmetic recovery embedded the wrong attempt")
    _validate_precision120(
        outcome, predecessor=record.stages[0].outcome
    )
    if not _validate_component_result(
        leaf, outcome, allow_historical_conditioning_absence=False
    ):
        raise ValueError(
            "endpoint-arithmetic recovery lacks canonical production evidence"
        )
    state = _endpoint_arithmetic_terminal_state(
        leaf,
        outcome,
        predecessor=record.stages[0].outcome,
        sentinel=record.sentinel,
    )
    return CampaignLeafRecord(
        leaf_id=record.leaf_id,
        role=record.role,
        state=state,
        stages=(
            *record.stages,
            _campaign_stage_record(plan, available, outcome),
        ),
        trigger_ids=record.trigger_ids,
        sentinel=record.sentinel,
        sentinel_comparison=record.sentinel_comparison,
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


def _execute_promoted_response_repair(
    backend: object,
    leaf: CampaignLeafPlan,
    digits: int,
    previous_stages: Sequence[CampaignStageRecord],
) -> StageOutcome:
    """Execute the root-forbidden promoted response repair boundary."""

    execute = getattr(backend, "execute_promoted_response_repair", None)
    if not callable(execute):
        raise ValueError(
            "campaign backend lacks root-sealed response repair support"
        )
    return execute(
        leaf,
        digits,
        tuple(stage.outcome for stage in previous_stages),
    )


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


def _execute_campaign_stage_after_endpoint_arithmetic(
    backend: object,
    leaf: CampaignLeafPlan,
    predecessor: CampaignExecutionAttempt,
    response_predictor: complex | None = None,
) -> StageOutcome:
    """Run exact 120-digit recovery without fabricating an 80 stage."""

    _validate_endpoint_arithmetic_predecessor(predecessor, leaf)
    with_predictor = getattr(
        backend,
        "execute_promoted_stage_after_endpoint_arithmetic_with_predictor",
        None,
    )
    if with_predictor is not None:
        if not callable(with_predictor):
            raise ValueError("endpoint-arithmetic predictor backend is invalid")
        return with_predictor(leaf, 120, predecessor, response_predictor)
    execute = getattr(
        backend, "execute_promoted_stage_after_endpoint_arithmetic", None
    )
    if not callable(execute):
        raise ValueError(
            "campaign backend lacks endpoint-arithmetic 120 recovery support"
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


def _execute_promoted_response_repair_with_progress(
    backend: object,
    leaf: CampaignLeafPlan,
    digits: int,
    context: Mapping[str, object],
    previous_stages: Sequence[CampaignStageRecord],
) -> tuple[StageOutcome, float]:
    """Execute only seal-bound determinant stencil recovery work."""

    started = time.monotonic()
    with progress_scope(
        **context,
        precision_digits=digits,
        component_pass="promoted-response-repair",
    ):
        emit_progress(ProgressEventKind.PRECISION_STAGE_STARTED)
        try:
            outcome = _execute_promoted_response_repair(
                backend,
                leaf,
                digits,
                previous_stages,
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


def _execute_endpoint_arithmetic_recovery_with_progress(
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
            outcome = _execute_campaign_stage_after_endpoint_arithmetic(
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
    requested = code in _RETRYABLE_NUMERICAL_CONTROL_FAILURE_CODES
    if code == "INSUFFICIENT_ASYMPTOTIC_PRECISION":
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
    leaf: CampaignLeafPlan,
    factory_identity: PrecisionFactoryIdentity,
    scientific_execution_contract: Mapping[str, object] | None,
) -> None:
    if any(
        stage.outcome.component_result.get("evidence_kind")
        in {
            _SELECTIVE_STAGE_EVIDENCE_KIND,
            _ANALYTIC_HORIZON_EVIDENCE_KIND,
            _FIXED_ROOT_EXTERIOR_EVIDENCE_KIND,
        }
        for stage in record.stages[1:]
    ):
        # Close the live-admission -> durable-record join for every specialized
        # promoted contract before replacing the last authenticated checkpoint.
        _validate_record_semantics(leaf, record, factory_identity)
    _validate_record_scientific_execution_contract(
        leaf, record, scientific_execution_contract
    )
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
    *,
    scientific_execution_contract: Mapping[str, object] | None = None,
) -> None:
    if store is None or record.state not in {"PRODUCED", "UNRESOLVED"}:
        return
    try:
        _validate_cacheable_leaf_record(plan, leaf, record)
        _validate_record_scientific_execution_contract(
            leaf, record, scientific_execution_contract
        )
        store.publish(
            scientific_identity_sha256=scientific_computation_identity_sha256(
                plan,
                leaf,
                scientific_execution_contract=scientific_execution_contract,
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
    leaf_by_id = {leaf.leaf_id: leaf for leaf in plan.leaves}
    scientific_execution_contracts = {
        leaf_id: _backend_scientific_execution_contract(
            backend, leaf_by_id[leaf_id]
        )
        for leaf_id in execution_leaf_ids
    }
    cache_lookups: dict[str, SolvedLeafLookup] = {}
    if solved_leaf_store is not None:
        for leaf_id in execution_leaf_ids:
            cache_lookups[leaf_id] = _authenticated_solved_leaf_lookup(
                plan,
                leaf_by_id[leaf_id],
                solved_leaf_store,
                scientific_execution_contract=(
                    scientific_execution_contracts[leaf_id]
                ),
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
            scientific_execution_contracts=scientific_execution_contracts,
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


def _migrate_schema6_single_promoted_horizon_checkpoint(
    plan: CampaignPlan,
    selection: CampaignSelection,
    records: Sequence[CampaignLeafRecord],
    attempts: Sequence[CampaignExecutionAttempt],
    available: PrecisionCapabilities,
) -> tuple[
    tuple[CampaignLeafRecord, ...],
    tuple[CampaignExecutionAttempt, ...],
]:
    """Retain canonical binary64 work and discard stale horizon promotion.

    Inputs have already passed the complete schema-6 authentication path.  The
    migration changes no binary64 stage bytes: it removes only stages and
    attempts belonging to primary horizon leaves whose binary64 baseline
    requested promotion under the predecessor component architecture.
    """

    leaf_by_id = {leaf.leaf_id: leaf for leaf in plan.leaves}
    affected_leaf_ids: set[str] = set()
    migrated_records: list[CampaignLeafRecord] = []
    for record in records:
        leaf = leaf_by_id[record.leaf_id]
        first = record.stages[0].outcome
        production = _validate_component_result(
            leaf,
            first,
            allow_historical_conditioning_absence=True,
        )
        affected = (
            leaf.role == "primary"
            and leaf.mechanism_id == "horizon-admittance"
            and _primary_binary64_promotes(first, production=production)
        )
        if not affected:
            migrated_records.append(record)
            continue
        affected_leaf_ids.add(record.leaf_id)
        missing = 80 if 80 not in available.digits else None
        migrated_records.append(CampaignLeafRecord(
            leaf_id=record.leaf_id,
            role=record.role,
            state=("MISSING_PRECISION" if missing is not None else "IN_PROGRESS"),
            stages=(record.stages[0],),
            missing_precision_digits=missing,
        ))

    retained_attempts = tuple(
        attempt
        for attempt in attempts
        if attempt.leaf_id not in affected_leaf_ids
    )
    renumbered_attempts = tuple(
        replace(attempt, attempt_ordinal=index)
        for index, attempt in enumerate(retained_attempts, start=1)
    )
    predecessor_by_leaf = {
        attempt.leaf_id: attempt
        for attempt in renumbered_attempts
        if (
            attempt.precision_digits == 80
            and attempt.failure_code == "INSUFFICIENT_ASYMPTOTIC_PRECISION"
        )
    }
    materialized_records: list[CampaignLeafRecord] = []
    for record in migrated_records:
        if tuple(stage.outcome.digits for stage in record.stages) == (64, 120):
            predecessor = predecessor_by_leaf.get(record.leaf_id)
            if predecessor is None:
                raise ValueError(
                    "schema-6 migration lost a retained preflight predecessor"
                )
            record = _record_with_materialized_failed_preflight_predecessor(
                record,
                predecessor,
            )
        materialized_records.append(record)
    return tuple(materialized_records), renumbered_attempts


def _schema8_leaf42_root_seal_candidate(
    leaf: CampaignLeafPlan,
    record: CampaignLeafRecord,
) -> tuple[ComponentResult, PromotedRootSeal] | None:
    """Authenticate the one historical exterior shape safe to salvage.

    Schema 8 coupled a missing PRIMARY Dω error certificate to a root retry.
    Its stage hash is not enough to authorize reuse; this deliberately derives
    a new seal from the full persisted root readout and accepts no derivative
    estimate, sample, or uncertainty claim from the historical response.
    """

    if (
        leaf.role != "primary"
        or leaf.mechanism_id != "exterior-light-ring"
        or tuple(stage.outcome.digits for stage in record.stages) != (64, 80)
        or record.state not in {"IN_PROGRESS", "MISSING_PRECISION"}
        or record.missing_precision_digits not in {None, 120}
    ):
        return None
    binary, promoted = (stage.outcome for stage in record.stages)
    if not _validate_component_result(
        leaf, binary, allow_historical_conditioning_absence=True
    ):
        return None
    raw = promoted.component_result.get("result")
    if not isinstance(raw, Mapping):
        return None
    result = ComponentResult.from_mapping(raw)
    if result.to_mapping() != raw:
        return None
    evidence = result.derivative_evidence
    primary = result.baseline.primary_acceptance
    authentication = (
        None if primary is None else primary.derivative_authentication
    )
    if (
        promoted.component_result.get("evidence_kind")
        != _FIXED_ROOT_EXTERIOR_EVIDENCE_KIND
        or promoted.numerical_state != ComponentStatus.DERIVATIVE_UNRESOLVED.value
        or result.component_scientific_identity
        != EXTERIOR_DERIVATIVE_COMPONENT_IDENTITY
        or result.status is not ComponentStatus.DERIVATIVE_UNRESOLVED
        or result.response is not None
        or not isinstance(evidence, Mapping)
        or evidence.get("determinant_count") != 0
        or evidence.get("fixed_root_samples") != []
        or evidence.get("root_seal") is not None
        or primary is None
        or not primary.accepted
        or (
            authentication is not None
            and authentication.determinant_error_status
            == "available/v1"
        )
    ):
        return None
    try:
        return result, PromotedRootSeal.derive(leaf.job, result.baseline)
    except ValueError:
        return None


def _migrate_schema8_root_sealed_exterior_checkpoint(
    plan: CampaignPlan,
    records: Sequence[CampaignLeafRecord],
    attempts: Sequence[CampaignExecutionAttempt],
) -> tuple[
    tuple[CampaignLeafRecord, ...],
    tuple[CampaignExecutionAttempt, ...],
    bool,
]:
    """Convert only the Leaf-42 stale-response shape into a seal-bound repair.

    The returned 80-digit stage retains the exact historical baseline but
    deliberately replaces its stale Dω material with a pending-response
    marker.  The campaign then appends a current-runtime, root-forbidden
    response-only 80 stage; it never relabels old response evidence as new.
    """

    leaf_by_id = {leaf.leaf_id: leaf for leaf in plan.leaves}
    migrated = False
    affected_leaf_ids: set[str] = set()
    output: list[CampaignLeafRecord] = []
    for record in records:
        leaf = leaf_by_id[record.leaf_id]
        candidate = _schema8_leaf42_root_seal_candidate(leaf, record)
        if candidate is None:
            output.append(record)
            continue
        old_result, seal = candidate
        old_stage = record.stages[1]
        stale_evidence = {
            "schema": _ROOT_SEAL_RESPONSE_MIGRATION_SCHEMA,
            "identity": _ROOT_SEAL_RESPONSE_MIGRATION_IDENTITY,
            "source_checkpoint_schema_version": 8,
            "source_stage_sha256": old_stage.stage_sha256,
            "source_response_status": old_result.status.value,
        }
        replacement_evidence = {
            "conditioning_decision": {
                "accepted": False,
                "identity": FIXED_ROOT_DERIVATIVE_CONDITIONING_IDENTITY,
                "rejection_reason": "STALE_RESPONSE_EVIDENCE_DISCARDED",
                "selected_candidate": None,
            },
            "determinant_count": 0,
            "failure_code": "STALE_RESPONSE_EVIDENCE_DISCARDED",
            "fixed_root_samples": [],
            "response_disk_identity": EXTERIOR_DERIVATIVE_RESPONSE_DISK_IDENTITY,
            "response_repair_identity": ROOT_SEALED_RESPONSE_REPAIR_IDENTITY,
            "root_seal": seal.to_mapping(),
            "root_seal_sha256": seal.sha256,
            "stale_response_evidence": stale_evidence,
        }
        replacement_result = replace(
            old_result,
            derivative_evidence=replacement_evidence,
        )
        component = dict(old_stage.outcome.component_result)
        component.pop("promotion_decision", None)
        component["result"] = replacement_result.to_mapping()
        unbound = replace(
            old_stage.outcome,
            numerical_state=replacement_result.status.value,
            component_result=component,
            local_disk_radius_abs=sum(replacement_result.error_channels.values()),
            signed_error_channels=_component_stage_signed_error_channels(
                component,
                replacement_result,
                repeat_applicable=False,
                precision_ladder_applicable=False,
            ),
            self_refinement_enclosed=None,
            discrepancy_from_previous_abs=None,
            discrepancy_enclosed=None,
        )
        replacement = _stage_with_promotion_decision(
            unbound,
            _primary_precision120_decision(
                unbound, predecessor=record.stages[0].outcome
            ),
        )
        output.append(CampaignLeafRecord(
            leaf_id=record.leaf_id,
            role=record.role,
            state="IN_PROGRESS",
            stages=(
                record.stages[0],
                CampaignStageRecord(replacement, old_stage.runner_provenance),
            ),
            trigger_ids=record.trigger_ids,
            sentinel=record.sentinel,
            missing_precision_digits=None,
            sentinel_comparison=record.sentinel_comparison,
        ))
        affected_leaf_ids.add(record.leaf_id)
        migrated = True
    if not migrated:
        return tuple(output), tuple(attempts), False
    retained_attempts = tuple(
        attempt
        for attempt in attempts
        if attempt.leaf_id not in affected_leaf_ids
    )
    # The migrated record now carries no old root retry authorization.  Any
    # historical response-triggered 120 attempt is stale operational history,
    # so keep only attempts for unaffected leaves and renumber append-only IDs.
    retained_attempts = tuple(
        replace(attempt, attempt_ordinal=index)
        for index, attempt in enumerate(retained_attempts, start=1)
    )
    return tuple(output), retained_attempts, True


def _run_campaign_selection_active(
    plan: CampaignPlan,
    selection: CampaignSelection,
    backend: object,
    checkpoint_path: str | os.PathLike[str] | Path,
    *,
    resume: bool,
    solved_leaf_store: SolvedLeafStore | None,
    cache_lookups: Mapping[str, SolvedLeafLookup],
    scientific_execution_contracts: Mapping[
        str, Mapping[str, object] | None
    ],
) -> CampaignRunSummary:
    if getattr(backend, "identity", None) != plan.backend_identity:
        raise ValueError("campaign backend identity does not match plan")
    available = getattr(backend, "precision_capabilities", None)
    if not isinstance(available, PrecisionCapabilities):
        raise ValueError("campaign backend precision capabilities are invalid")
    leaf_by_id = {leaf.leaf_id: leaf for leaf in plan.leaves}
    path = Path(checkpoint_path)
    if path.exists():
        if not resume:
            raise ValueError("campaign cold execution refuses an existing checkpoint")
        loaded_selection, existing, loaded_attempts, loaded_state, loaded_schema_version = (
            _load_checkpoint_with_attempts(plan, path)
        )
        if loaded_selection != selection:
            raise ValueError("campaign checkpoint selection does not match request")
        migrated_schema6 = loaded_schema_version == 6
        migrated_schema8 = False
        if migrated_schema6:
            existing, loaded_attempts = (
                _migrate_schema6_single_promoted_horizon_checkpoint(
                    plan,
                    selection,
                    existing,
                    loaded_attempts,
                    available,
                )
            )
            loaded_schema_version = CAMPAIGN_CHECKPOINT_SCHEMA_VERSION
            loaded_state = (
                "COMPLETE"
                if len(existing) == len(selection.leaf_ids)
                and all(
                    record.state in {"PRODUCED", "UNRESOLVED"}
                    for record in existing
                )
                else "PARTIAL"
            )
        elif loaded_schema_version == 8 and loaded_state == "PARTIAL":
            existing, loaded_attempts, migrated_schema8 = (
                _migrate_schema8_root_sealed_exterior_checkpoint(
                    plan,
                    existing,
                    loaded_attempts,
                )
            )
            if not migrated_schema8:
                raise ValueError(
                    "incomplete historical campaign checkpoint is read-only; "
                    "preserve it as evidence and start with a fresh checkpoint path"
                )
            loaded_schema_version = CAMPAIGN_CHECKPOINT_SCHEMA_VERSION
            loaded_state = "PARTIAL"
        elif (
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
        invalidated_leaf_ids: set[str] = set()
        validated_existing: list[CampaignLeafRecord] = []
        for record in existing:
            for stage in record.stages:
                prior = set(stage.runner_provenance["available_precision_digits"])
                if not prior.issubset(set(available.digits)):
                    raise ValueError(
                        "campaign backend precision availability is not a permitted superset"
                    )
            try:
                _validate_record_scientific_execution_contract(
                    leaf_by_id[record.leaf_id],
                    record,
                    scientific_execution_contracts.get(record.leaf_id),
                )
            except _PromotedExecutionContractMismatch:
                invalidated = _invalidate_promoted_record(record)
                if invalidated is record:
                    raise
                record = invalidated
                invalidated_leaf_ids.add(record.leaf_id)
            validated_existing.append(record)
        existing = tuple(validated_existing)
        if invalidated_leaf_ids:
            retained_attempts = tuple(
                attempt
                for attempt in loaded_attempts
                if attempt.leaf_id not in invalidated_leaf_ids
            )
            loaded_attempts = tuple(
                replace(attempt, attempt_ordinal=index)
                for index, attempt in enumerate(retained_attempts, start=1)
            )
            loaded_state = "PARTIAL"
        records_by_id = {record.leaf_id: record for record in existing}
        if migrated_schema6 or migrated_schema8 or invalidated_leaf_ids:
            leaf_by_id = {leaf.leaf_id: leaf for leaf in plan.leaves}
            for record in existing:
                _validate_record_semantics(
                    leaf_by_id[record.leaf_id],
                    record,
                    plan.precision_factory_identity,
                )
            _atomic_json(
                path,
                _checkpoint_mapping(
                    plan,
                    selection,
                    existing,
                    loaded_attempts,
                ),
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
    execution_leaf_ids = _campaign_execution_leaf_ids(plan, selection)
    continuation_responses: dict[tuple[str, str, str, str], complex] = {}
    for index, leaf_id in enumerate(execution_leaf_ids):
        leaf = leaf_by_id[leaf_id]
        scientific_execution_contract = scientific_execution_contracts.get(
            leaf_id
        )
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
                    plan,
                    leaf,
                    record,
                    solved_leaf_store,
                    scientific_execution_contract=scientific_execution_contract,
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
                    plan,
                    leaf,
                    solved_leaf_store,
                    scientific_execution_contract=scientific_execution_contract,
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
                leaf=leaf,
                factory_identity=plan.precision_factory_identity,
                scientific_execution_contract=scientific_execution_contract,
            )

        if record.state in {"PRODUCED", "UNRESOLVED"}:
            with progress_scope(**context):
                _publish_terminal_solved_leaf(
                    plan,
                    leaf,
                    record,
                    solved_leaf_store,
                    scientific_execution_contract=scientific_execution_contract,
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
                    leaf=leaf,
                    factory_identity=plan.precision_factory_identity,
                    scientific_execution_contract=scientific_execution_contract,
                )
                with progress_scope(**context):
                    _publish_terminal_solved_leaf(
                        plan,
                        leaf,
                        record,
                        solved_leaf_store,
                        scientific_execution_contract=(
                            scientific_execution_contract
                        ),
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
                endpoint_arithmetic = (
                    attempt.failure_code == "HORIZON_ARITHMETIC_INADEQUATE"
                )
                retry_at_120 = failed_preflight or endpoint_arithmetic
                if retry_at_120 and 120 not in available.digits:
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
                if not retry_at_120 or 120 not in available.digits:
                    continue
                try:
                    if failed_preflight:
                        outcome120, recovery_duration = (
                            _execute_failed_preflight_recovery_with_progress(
                                backend,
                                leaf,
                                attempt,
                                context,
                                response_predictor,
                            )
                        )
                    else:
                        outcome120, recovery_duration = (
                            _execute_endpoint_arithmetic_recovery_with_progress(
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
                if endpoint_arithmetic:
                    record = _endpoint_arithmetic_recovery_record(
                        plan, available, leaf, record, outcome120, attempt
                    )
                    records_by_id[leaf_id] = record
                    executed += 1
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
                        digits=120,
                        duration_seconds=recovery_duration,
                        record=record,
                        leaf=leaf,
                        factory_identity=plan.precision_factory_identity,
                        scientific_execution_contract=(
                            scientific_execution_contract
                        ),
                    )
                    with progress_scope(**context):
                        _publish_terminal_solved_leaf(
                            plan,
                            leaf,
                            record,
                            solved_leaf_store,
                            scientific_execution_contract=(
                                scientific_execution_contract
                            ),
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
                    not isinstance(outcome120, StageOutcome)
                    or outcome120.digits != 120
                ):
                    raise ValueError(
                        "campaign backend returned invalid failed-preflight "
                        "120-digit evidence"
                    )
                if outcome120.component_result.get("evidence_kind") in {
                    _ANALYTIC_HORIZON_EVIDENCE_KIND,
                    _FIXED_ROOT_EXTERIOR_EVIDENCE_KIND,
                }:
                    outcome120 = (
                        _bind_fixed_readout_precision_comparison(
                            outcome120, record.stages[0].outcome
                        )
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
                        leaf, outcome120, record.stages[0].outcome
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
                    leaf=leaf,
                    factory_identity=plan.precision_factory_identity,
                    scientific_execution_contract=scientific_execution_contract,
                )
                with progress_scope(**context):
                    _publish_terminal_solved_leaf(
                        plan,
                        leaf,
                        record,
                        solved_leaf_store,
                        scientific_execution_contract=(
                            scientific_execution_contract
                        ),
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
            if not isinstance(outcome80, StageOutcome) or outcome80.digits != 80:
                raise ValueError("campaign backend returned incomplete 80-digit evidence")
            selective80 = _validate_selective_stage(
                leaf, outcome80, record.stages[0].outcome
            )
            semantics80: _PromotedStageSemantics | None = None
            if selective80 is not None:
                pass
            else:
                production80 = _validate_component_result(
                    leaf,
                    outcome80,
                    allow_historical_conditioning_absence=False,
                )
                smoke80 = outcome80.component_result.get(
                    "evidence_kind"
                ) == "synthetic-orchestration-contract"
                if not production80 and not smoke80:
                    raise ValueError(
                        "campaign promoted stage lacks canonical production evidence"
                    )
                if isinstance(
                    outcome80.component_result.get("result"), Mapping
                ):
                    semantics80 = _promoted_stage_semantics(
                        outcome80, predecessor=record.stages[0].outcome
                    )
                    if semantics80.kind in {
                        _PromotedStageKind.ANALYTIC_HORIZON,
                        _PromotedStageKind.FIXED_ROOT_EXTERIOR_DERIVATIVE,
                    }:
                        _validate_precision120(
                            outcome80,
                            predecessor=record.stages[0].outcome,
                        )
                if semantics80 is None and (
                    outcome80.self_refinement_enclosed is None
                    or outcome80.discrepancy_from_previous_abs is None
                    or outcome80.discrepancy_enclosed is None
                ):
                    raise ValueError(
                        "campaign backend returned incomplete 80-digit evidence"
                    )
            _validate_fixed_readout_predictor_binding(
                record.stages[0].outcome,
                outcome80,
            )
            executed += 1
            if selective80 is not None:
                if leaf.role != "primary":
                    raise ValueError(
                        "selective semantic recovery requires a PRIMARY leaf"
                    )
                _, selective_produced = selective80
                record = CampaignLeafRecord(
                    leaf_id=record.leaf_id,
                    role=record.role,
                    state="PRODUCED" if selective_produced else "UNRESOLVED",
                    stages=(
                        *record.stages,
                        _campaign_stage_record(plan, available, outcome80),
                    ),
                    missing_precision_digits=None,
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
                    digits=precision80_digits,
                    duration_seconds=stage_duration,
                    record=record,
                    leaf=leaf,
                    factory_identity=plan.precision_factory_identity,
                    scientific_execution_contract=scientific_execution_contract,
                )
            elif leaf.role == "primary":
                outcome80 = _stage_with_promotion_decision(
                    outcome80,
                    _primary_precision120_decision(
                        outcome80,
                        predecessor=record.stages[0].outcome,
                    ),
                )
                semantics80 = (
                    _promoted_stage_semantics(
                        outcome80, predecessor=record.stages[0].outcome
                    )
                    if isinstance(
                        outcome80.component_result.get("result"), Mapping
                    )
                    else None
                )
                _, precision120_digits = _primary_recovery_digits()
                root_requires120 = _primary_requires_precision120(
                    outcome80, predecessor=record.stages[0].outcome
                )
                response_repair_digits = (
                    None
                    if semantics80 is None
                    else semantics80.response_repair_precision_digits
                )
                response_requires_repair = bool(
                    semantics80 is not None
                    and semantics80.root_sealed
                    and not semantics80.root_requires_precision120
                    and response_repair_digits is not None
                )
                required_next_digits = (
                    precision120_digits
                    if root_requires120
                    else response_repair_digits
                )
                if root_requires120 or response_requires_repair:
                    assert required_next_digits is not None
                    state = (
                        "MISSING_PRECISION"
                        if required_next_digits not in available.digits
                        else "IN_PROGRESS"
                    )
                    missing = (
                        required_next_digits
                        if required_next_digits not in available.digits
                        else None
                    )
                else:
                    state = (
                        "PRODUCED"
                        if (
                            semantics80.terminal_admissible
                            if semantics80 is not None
                            else (
                                bool(outcome80.self_refinement_enclosed)
                                and bool(outcome80.discrepancy_enclosed)
                            )
                        )
                        else "UNRESOLVED"
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
                    leaf=leaf,
                    factory_identity=plan.precision_factory_identity,
                    scientific_execution_contract=scientific_execution_contract,
                )
            else:
                comparison = None
                false_negative = False
                if record.sentinel:
                    if outcome80.discrepancy_from_previous_abs is not None:
                        threshold = (
                            0.25
                            * record.stages[0].outcome.local_disk_radius_abs
                        )
                        false_negative = (
                            not record.trigger_ids
                            and outcome80.discrepancy_from_previous_abs
                            > threshold
                        )
                        comparison = {
                            "binary64_to_80_discrepancy_abs": (
                                outcome80.discrepancy_from_previous_abs
                            ),
                            "trigger_threshold_abs": threshold,
                            "trigger_policy_false_negative": false_negative,
                        }
                decision = (
                    _deep_precision120_decision(
                        outcome80,
                        sentinel_false_negative=True,
                        predecessor=record.stages[0].outcome,
                    )
                    if false_negative
                    else _primary_precision120_decision(
                        outcome80,
                        predecessor=record.stages[0].outcome,
                    )
                    if (
                        semantics80 is not None
                        and semantics80.kind
                        is _PromotedStageKind.ANALYTIC_HORIZON
                    )
                    else _deep_precision120_decision(
                        outcome80,
                        sentinel_false_negative=False,
                        predecessor=record.stages[0].outcome,
                    )
                )
                outcome80 = _stage_with_promotion_decision(outcome80, decision)
                semantics80 = (
                    _promoted_stage_semantics(
                        outcome80, predecessor=record.stages[0].outcome
                    )
                    if isinstance(
                        outcome80.component_result.get("result"), Mapping
                    )
                    else None
                )
                requires120 = decision["state"] == "REQUESTED"
                if false_negative and requires120:
                    state = "INVALID_SENTINEL_FALSE_NEGATIVE"
                    missing = 120
                elif not requires120:
                    state = (
                        "PRODUCED"
                        if (
                            semantics80.terminal_admissible
                            if semantics80 is not None
                            else (
                                bool(outcome80.self_refinement_enclosed)
                                and bool(outcome80.discrepancy_enclosed)
                            )
                        )
                        else "UNRESOLVED"
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
                    leaf=leaf,
                    factory_identity=plan.precision_factory_identity,
                    scientific_execution_contract=scientific_execution_contract,
                )

        if record.state in {"PRODUCED", "UNRESOLVED"}:
            with progress_scope(**context):
                _publish_terminal_solved_leaf(
                    plan,
                    leaf,
                    record,
                    solved_leaf_store,
                    scientific_execution_contract=scientific_execution_contract,
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
            promoted_semantics = (
                _promoted_stage_semantics(
                    record.stages[1].outcome,
                    predecessor=record.stages[0].outcome,
                )
                if isinstance(
                    record.stages[1].outcome.component_result.get("result"),
                    Mapping,
                )
                else None
            )
            response_repair_digits = (
                None
                if promoted_semantics is None
                else promoted_semantics.response_repair_precision_digits
            )
            response_repair = bool(
                leaf.role == "primary"
                and promoted_semantics is not None
                and promoted_semantics.root_sealed
                and not promoted_semantics.root_requires_precision120
                and response_repair_digits is not None
            )
            if (
                not response_repair
                and _ordinary_fixed_readout_precision120_failure_for_leaf(
                    attempts, leaf, record
                ) is not None
            ):
                # A contained failure at the maximum configured tier is a
                # durable operational outcome.  Preserve its append-only
                # receipt and do not repeat the same expensive request on
                # every resume.
                continue
            root_precision_digits = (
                _primary_recovery_digits()[1]
                if leaf.role == "primary"
                else 120
            )
            next_digits = (
                response_repair_digits if response_repair else root_precision_digits
            )
            assert next_digits is not None
            if next_digits not in available.digits:
                continue
            try:
                if response_repair:
                    next_outcome, stage_duration = (
                        _execute_promoted_response_repair_with_progress(
                            backend,
                            leaf,
                            next_digits,
                            context,
                            record.stages,
                        )
                    )
                else:
                    next_outcome, stage_duration = (
                        _execute_campaign_stage_with_progress(
                            backend,
                            leaf,
                            next_digits,
                            context,
                            record.stages,
                            response_predictor,
                        )
                    )
            except _CONTAINABLE_EXCEPTION_TYPES as error:
                attempt = _execution_attempt_from_failure(
                    error,
                    leaf=leaf,
                    context=context,
                    digits=next_digits,
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
                    digits=next_digits,
                )
                continue
            if (
                not isinstance(next_outcome, StageOutcome)
                or next_outcome.digits != next_digits
            ):
                raise ValueError("campaign backend returned incomplete response/root evidence")
            production120 = _validate_component_result(
                leaf,
                next_outcome,
                allow_historical_conditioning_absence=False,
            )
            smoke120 = next_outcome.component_result.get(
                "evidence_kind"
            ) == "synthetic-orchestration-contract"
            if not production120 and not smoke120:
                raise ValueError(
                    "campaign promoted repair stage lacks canonical "
                    "production evidence"
                )
            if next_digits == 120:
                _validate_precision120(
                    next_outcome, predecessor=record.stages[1].outcome
                )
            semantics120 = (
                _promoted_stage_semantics(
                    next_outcome, predecessor=record.stages[1].outcome
                )
                if isinstance(
                    next_outcome.component_result.get("result"), Mapping
                )
                else None
            )
            _validate_fixed_readout_predictor_binding(
                record.stages[1].outcome,
                next_outcome,
            )
            executed += 1
            if leaf.role == "primary":
                record = CampaignLeafRecord(
                    leaf_id=record.leaf_id,
                    role=record.role,
                    state=_primary_precision120_terminal_state(
                        next_outcome,
                        predecessor=record.stages[1].outcome,
                    ),
                    stages=(
                        *record.stages,
                        _campaign_stage_record(plan, available, next_outcome),
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
                        else (
                            _primary_precision120_terminal_state(
                                next_outcome,
                                predecessor=record.stages[1].outcome,
                            )
                            if semantics120 is not None
                            else _terminal_state(
                                next_outcome,
                                enclosed=bool(next_outcome.discrepancy_enclosed),
                            )
                        )
                    ),
                    stages=(
                        *record.stages,
                        _campaign_stage_record(plan, available, next_outcome),
                    ),
                    trigger_ids=record.trigger_ids,
                    sentinel=record.sentinel,
                    missing_precision_digits=next_digits if false_negative else None,
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
                digits=next_digits,
                duration_seconds=stage_duration,
                record=record,
                leaf=leaf,
                factory_identity=plan.precision_factory_identity,
                scientific_execution_contract=scientific_execution_contract,
            )
        if record.state in {"PRODUCED", "UNRESOLVED"}:
            with progress_scope(**context):
                _publish_terminal_solved_leaf(
                    plan,
                    leaf,
                    record,
                    solved_leaf_store,
                    scientific_execution_contract=scientific_execution_contract,
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
    _, records, _, checkpoint_schema_version = (
        _load_checkpoint_for_solved_leaf_import(
        plan, path
        )
    )
    leaf_by_id = {leaf.leaf_id: leaf for leaf in plan.leaves}
    imported: list[str] = []
    skipped = 0
    for record in records:
        if record.state not in {"PRODUCED", "UNRESOLVED"}:
            skipped += 1
            continue
        leaf = leaf_by_id[record.leaf_id]
        if (
            checkpoint_schema_version == 6
            and leaf.role == "primary"
            and leaf.mechanism_id == "horizon-admittance"
            and len(record.stages) > 1
        ):
            # Schema 6 promoted horizon stages used the multiplied component
            # engine.  They remain authenticated history, never current cache
            # evidence.  A campaign resume performs the lossless binary64
            # migration and recomputes promotion under the new identity.
            skipped += 1
            continue
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
) -> tuple[CampaignSelection, tuple[CampaignLeafRecord, ...], str, int]:
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
    return selection, records, expected_state, value["schema_version"]


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
        if schema_version == 6:
            records, attempts = (
                _migrate_schema6_single_promoted_horizon_checkpoint(
                    plan,
                    selection,
                    records,
                    attempts,
                    plan.precision_capabilities,
                )
            )
            state = (
                "COMPLETE"
                if len(records) == len(selection.leaf_ids)
                and all(
                    record.state in {"PRODUCED", "UNRESOLVED"}
                    for record in records
                )
                else "PARTIAL"
            )
        if (
            schema_version != CAMPAIGN_CHECKPOINT_SCHEMA_VERSION
            and schema_version != 6
            and state == "PARTIAL"
        ):
            raise ValueError(
                "incomplete historical campaign checkpoint is read-only; "
                "it cannot be merged into the current checkpoint schema"
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


def _run_promoted_horizon_component_with_progress(
    job: ResponseComponentJob,
    backend: object,
    primary_root_predictor: complex,
) -> ComponentResult:
    """Run the one-readout promoted horizon boundary with pass telemetry."""

    started = time.monotonic()
    with progress_scope(component_pass="promoted"):
        emit_progress(ProgressEventKind.COMPONENT_PASS_STARTED)
        try:
            result = run_promoted_horizon_component(
                job,
                backend,  # type: ignore[arg-type]
                primary_root_predictor,
            )
        except KeyboardInterrupt:
            raise
        except BaseException as error:
            emit_progress(
                ProgressEventKind.ERROR,
                component_pass="promoted",
                error_type=type(error).__name__,
                message=str(error),
                elapsed_seconds=time.monotonic() - started,
            )
            raise
        emit_progress(
            ProgressEventKind.COMPONENT_PASS_COMPLETED,
            component_pass="promoted",
            status=result.status.value,
            readout_count=len(result.raw_readouts),
            elapsed_seconds=time.monotonic() - started,
        )
        return result


def _run_promoted_exterior_component_with_progress(
    job: ResponseComponentJob,
    backend: object,
    primary_root_predictor: complex,
) -> ComponentResult:
    """Run one baseline plus fixed-root determinant derivative samples."""

    started = time.monotonic()
    with progress_scope(component_pass="promoted"):
        emit_progress(ProgressEventKind.COMPONENT_PASS_STARTED)
        try:
            result = run_promoted_exterior_component(
                job,
                backend,  # type: ignore[arg-type]
                primary_root_predictor,
                derivative_step=job.policy.epsilons[0],
            )
        except KeyboardInterrupt:
            raise
        except BaseException as error:
            emit_progress(
                ProgressEventKind.ERROR,
                component_pass="promoted",
                error_type=type(error).__name__,
                message=str(error),
                elapsed_seconds=time.monotonic() - started,
            )
            raise
        emit_progress(
            ProgressEventKind.COMPONENT_PASS_COMPLETED,
            component_pass="promoted",
            status=result.status.value,
            readout_count=len(result.raw_readouts),
            fixed_root_determinant_count=(
                0
                if result.derivative_evidence is None
                else result.derivative_evidence["determinant_count"]
            ),
            elapsed_seconds=time.monotonic() - started,
        )
        return result


def _run_promoted_exterior_response_repair_with_progress(
    job: ResponseComponentJob,
    backend: object,
    seal: PromotedRootSeal,
    *,
    repair_families: frozenset[str],
    reusable_result: ComponentResult,
) -> ComponentResult:
    """Run only fixed-root response work; this path has no root operation."""

    started = time.monotonic()
    with progress_scope(component_pass="promoted-response-repair"):
        emit_progress(ProgressEventKind.COMPONENT_PASS_STARTED)
        try:
            result = run_promoted_exterior_response_from_seal(
                job,
                backend,  # type: ignore[arg-type]
                seal,
                derivative_step=job.policy.epsilons[0],
                repair_families=repair_families,
                reusable_result=reusable_result,
            )
        except KeyboardInterrupt:
            raise
        except BaseException as error:
            emit_progress(
                ProgressEventKind.ERROR,
                component_pass="promoted-response-repair",
                error_type=type(error).__name__,
                message=str(error),
                elapsed_seconds=time.monotonic() - started,
            )
            raise
        emit_progress(
            ProgressEventKind.COMPONENT_PASS_COMPLETED,
            component_pass="promoted-response-repair",
            status=result.status.value,
            readout_count=0,
            fixed_root_determinant_count=(
                0
                if result.derivative_evidence is None
                else result.derivative_evidence["determinant_count"]
            ),
            elapsed_seconds=time.monotonic() - started,
        )
        return result


def _is_single_promoted_horizon_stage(
    leaf: CampaignLeafPlan,
    digits: int,
) -> bool:
    return (
        leaf.mechanism_id == "horizon-admittance"
        and digits in (80, 120)
    )


def _preflight_promoted_request_contracts(
    plan: CampaignPlan,
    adapter: JuliaResponseAdapter,
    calibration_receipt: PromotedControlCalibrationReceipt,
):
    jobs = {
        leaf.mechanism_id: leaf.job
        for leaf in plan.leaves
        if leaf.role == "primary"
        and leaf.mechanism_id in {
            "exterior-light-ring", "horizon-admittance"
        }
        and (leaf.job.mode.ell, leaf.job.mode.m, leaf.job.mode.n) == (2, 2, 1)
        and leaf.job.spin == 0.95
    }
    if set(jobs) != {
        "exterior-light-ring",
        "horizon-admittance",
    }:
        raise JuliaResponseBackendError(
            "M02 promoted-request preflight jobs are absent from the campaign plan"
        )
    requests = promoted_request_preflight_documents(
        jobs["exterior-light-ring"],
        jobs["horizon-admittance"],
        adapter,
        calibration_receipt,
    )
    return adapter.preflight_promoted_requests(
        requests,
        calibration_receipt_sha256=calibration_receipt.sha256,
        policy_sha256=plan.policy.identity_sha256,
        precision_capabilities_sha256=(
            plan.precision_capabilities.identity_sha256
        ),
    )


class NativeCampaignStageBackend:
    """Package-owned binary64 and Julia BigFloat M02 campaign backend."""

    identity = VettedNativeDeterminantKernel.identity

    def __init__(
        self,
        adapter: NativeDeterminantAdapter,
        precision_capabilities: PrecisionCapabilities,
        generated_cache: GeneratedGsnCache,
        julia_adapter: JuliaResponseAdapter | None = None,
        ode_error_budget: ODEErrorBudget | None = None,
        ode_error_budgets: (
            Mapping[int, ODEErrorBudget]
            | Callable[[int], ODEErrorBudget | None]
            | None
        ) = None,
        calibration_receipt: PromotedControlCalibrationReceipt | None = None,
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
        if ode_error_budget is not None and ode_error_budgets is not None:
            raise ValueError("ODE error budget sources are mutually exclusive")
        self.ode_error_budget = ode_error_budget
        self.ode_error_budgets = ode_error_budgets
        self.calibration_receipt = (
            calibration_receipt
            if calibration_receipt is not None
            else (
                None
                if ode_error_budget is not None or ode_error_budgets is not None
                else load_default_calibration_receipt()
            )
        )

    def _ode_error_budget_for_digits(self, digits: int) -> ODEErrorBudget:
        source = self.ode_error_budgets
        budget = (
            source(digits)
            if callable(source)
            else (None if source is None else source.get(digits))
        )
        if budget is None:
            budget = self.ode_error_budget
        if budget is None:
            raise MissingODECalibrationError(ODE_CALIBRATION_BLOCKER)
        mapping = budget.to_mapping()
        if mapping.get("nominal_decimal_digits") != digits:
            raise MissingODECalibrationError(ODE_CALIBRATION_BLOCKER)
        return budget

    def _julia_precision_backend_for(
        self,
        job: ResponseComponentJob,
        digits: int,
        *,
        refinement: int = 0,
    ) -> JuliaPrecisionRootBackend:
        if self.julia_adapter is None:
            raise NativeResourceUnavailableError(
                "M02 Julia precision worker is unavailable"
            )
        receipt = self.calibration_receipt
        if receipt is not None:
            determinant_family = (
                "horizon-scattering/v1"
                if job.mechanism_id == "horizon-admittance"
                else "exterior-wronskian/v1"
            )
            return JuliaPrecisionRootBackend(
                self.identity,
                self.julia_adapter,
                digits,
                refinement=refinement,
                empirical_control_profile=receipt.budget_for(
                    determinant_family, digits
                ),
                calibration_receipt=receipt,
            )
        return JuliaPrecisionRootBackend(
            self.identity,
            self.julia_adapter,
            digits,
            refinement=refinement,
            ode_error_budget=self._ode_error_budget_for_digits(digits),
        )

    def scientific_execution_contract_for(
        self, leaf: CampaignLeafPlan
    ) -> dict[str, object] | None:
        """Bind every calibrated ODE budget reachable by this campaign leaf."""

        if leaf.job.backend_identity != self.identity:
            raise ValueError(
                "campaign leaf backend identity does not match native backend"
            )
        if leaf.role == "control":
            return None
        promoted_digits = tuple(
            digits
            for digits in self.precision_capabilities.digits
            if digits in (80, 120)
        )
        if not promoted_digits:
            return None
        reachable_digits = list(promoted_digits)
        if (
            leaf.role == "primary"
            and leaf.mechanism_id == "exterior-light-ring"
        ):
            reachable_digits.insert(0, 40)
        receipt = self.calibration_receipt
        if receipt is not None:
            determinant_family = (
                "horizon-scattering/v1"
                if leaf.mechanism_id == "horizon-admittance"
                else "exterior-wronskian/v1"
            )
            profiles = {
                str(digits): receipt.budget_for(
                    determinant_family, digits
                ).to_mapping()
                for digits in reachable_digits
            }
            return {
                "schema": "windows-solver.m02-scientific-execution-contract/2",
                "calibration_receipt": {
                    "identity": receipt.identity,
                    "sha256": receipt.sha256,
                    "execution_status": receipt.execution_status,
                    "source_audit_sha256": receipt.source_audit_sha256,
                },
                "determinant_certificate": {
                    "identity": receipt.certificate_identity,
                    "safety_factor": receipt.certificate_safety_factor,
                },
                "determinant_family": determinant_family,
                "empirical_control_profiles_by_nominal_decimal_digits": profiles,
            }
        return {
            "schema": "windows-solver.m02-scientific-execution-contract/1",
            "ode_error_budgets_by_nominal_decimal_digits": {
                str(digits): self._ode_error_budget_for_digits(
                    digits
                ).to_mapping()
                for digits in reachable_digits
            },
        }

    @classmethod
    def from_selection(
        cls,
        plan: CampaignPlan,
        selection: CampaignSelection,
        *,
        calibration_receipt: PromotedControlCalibrationReceipt | None = None,
    ) -> "NativeCampaignStageBackend":
        effective_calibration_receipt = calibration_receipt
        julia_adapter = None
        if any(digits > 64 for digits in plan.precision_capabilities.digits):
            try:
                if effective_calibration_receipt is None:
                    effective_calibration_receipt = (
                        load_default_calibration_receipt()
                    )
                julia_adapter = JuliaResponseAdapter.from_runtime_receipt()
                _preflight_promoted_request_contracts(
                    plan, julia_adapter, effective_calibration_receipt
                )
            except (JuliaResponseBackendError, OSError, ValueError) as error:
                raise NativeResourceUnavailableError(
                    f"promoted request preflight failed: {error}"
                ) from error
        try:
            pairs = parameter_pairs_for_selection(plan, selection)
            generated = ensure_generated_gsn_cache(pairs)
        except GsnCacheProductionError as error:
            raise NativeResourceUnavailableError(str(error)) from error
        kernel = VettedNativeDeterminantKernel.from_generated_resource(
            generated.path, generated.sha256
        )
        return cls(
            NativeDeterminantAdapter(identity=kernel.identity, kernel=kernel),
            plan.precision_capabilities,
            generated,
            julia_adapter,
            calibration_receipt=effective_calibration_receipt,
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

    def execute_horizon_stage(self, leaf: CampaignLeafPlan) -> StageOutcome:
        """Run the binary64 horizon survey without the finite-amplitude ladder.

        Horizon response is an analytic fixed-root quantity.  This boundary
        deliberately evaluates only the zero-coupling determinant partials;
        it never calls ``run_component``/``execute_stage``, never constructs a
        ``LadderLevel``, and never launches a worker.
        """

        if leaf.mechanism_id != "horizon-admittance":
            raise ValueError("binary64 horizon stage requires a horizon leaf")
        job = leaf.job
        root = complex(job.root.omega)
        if not math.isfinite(root.real) or not math.isfinite(root.imag):
            raise ValueError("binary64 horizon root is not finite")
        partials = self.adapter.kernel.horizon_partials(
            job=job,
            background_root=job.root,
            policy=job.policy,
        )
        derivative = complex(partials.frequency_derivative)
        if not math.isfinite(derivative.real) or not math.isfinite(derivative.imag):
            raise ValueError("binary64 horizon derivative is not finite")

        # The fixed root and the binary64 stencil are authenticated inputs to
        # this stage.  Retain a conservative representable arithmetic radius;
        # a zero-containing disk becomes a typed promotion rather than an
        # asserted response.
        horizon_radius = 1.0 + math.sqrt(max(0.0, 1.0 - job.spin * job.spin))
        horizon_frequency = root - job.mode.m * (
            job.spin / (2.0 * horizon_radius)
        )
        frequency_radius = math.ulp(max(abs(horizon_frequency), 1.0))
        derivative_radius = math.ulp(max(abs(derivative), 1.0))
        frequency_disk = ComplexDisk(
            horizon_frequency,
            frequency_radius,
            exact_zero_radius=frequency_radius == 0.0,
        )
        derivative_disk = ComplexDisk(
            derivative,
            derivative_radius,
            exact_zero_radius=derivative_radius == 0.0,
        )
        response_disk = None
        status = ComponentStatus.DERIVATIVE_UNRESOLVED
        response = None
        try:
            if partials.simple_root_valid:
                response_disk = horizon_response_disk(
                    horizon_frequency=frequency_disk,
                    determinant_derivative=derivative_disk,
                )
        except ZeroContainingDiskError:
            response_disk = None
        if response_disk is not None:
            status = ComponentStatus.CONVERGED
            response = response_disk.centre

        baseline = RootReadout(
            omega=root,
            determinant_residual_abs=0.0,
            determinant_derivative_abs=max(abs(derivative), math.ulp(1.0)),
            converged=True,
            root_reference_id=job.root.root_reference_id,
            branch_id=job.root.branch_id,
            equation_id=job.equation_id,
            truncation_radius=0.0,
            resolution_radius=0.0,
            seed_path_radius=0.0,
            diagnostic_readouts=None,
        )
        result = ComponentResult(
            job_id=job.job_id,
            leaf_id=job.leaf_id,
            mechanism_id=job.mechanism_id,
            status=status,
            convergence_basis=(
                "PRIMARY_HORIZON_ANALYTIC"
                if response is not None
                else "UNRESOLVED"
            ),
            response=response,
            signed_root_crosscheck=None,
            closed_form_response=response,
            error_channels={
                **{name: 0.0 for name in ERROR_CHANNELS},
                "resolution": (
                    0.0 if response_disk is None else response_disk.radius
                ),
            },
            baseline=baseline,
            levels=(),
            lineage={
                "leaf_id": job.leaf_id,
                "root_reference_id": job.root.root_reference_id,
                "root_identity_sha256": job.root.identity_sha256,
                "policy_sha256": job.policy.identity_sha256,
                "backend_identity_sha256": job.backend_identity.identity_sha256,
                "equation_id": job.equation_id,
                "sampling_coordinate": job.sampling_coordinate.to_mapping(),
                "source_root_mapping": None,
            },
            component_scientific_identity=(
                "binary64-horizon-analytic-component/v1"
            ),
            response_method="binary64-fixed-root-horizon-response/v1",
            finite_amplitude_ladder_required=False,
            finite_amplitude_ladder_executed=False,
            finite_amplitude_readout_count=0,
            response_uncertainty_status=(
                "BOUNDED_ANALYTIC_RESPONSE"
                if response is not None
                else "UNBOUNDED_ANALYTIC_RESPONSE"
            ),
            error_channel_applicability={
                name: response is not None and name == "resolution"
                for name in ERROR_CHANNELS
            },
            analytic_horizon_evidence={
                "identity": "binary64-fixed-root-horizon-response/v1",
                "fixed_root": {
                    "real": root.real,
                    "imaginary": root.imag,
                },
                "horizon_frequency_disk": frequency_disk.to_mapping(),
                "determinant_derivative_disk": derivative_disk.to_mapping(),
                "response_disk": (
                    None
                    if response_disk is None
                    else response_disk.to_mapping()
                ),
                "levels": [],
                "worker_launch_count": 0,
                "nonzero_amplitude_readout_count": 0,
            },
        )
        component_result = {
            "evidence_kind": "package-owned-binary64-horizon-analytic-component",
            "result": result.to_mapping(),
            "scientific_runtime": self._cache_runtime(),
            "operation_contract": {
                "finite_amplitude_ladder": False,
                "nonzero_amplitudes": False,
                "diagnostic_root_phases": (),
                "worker_launch_count": 0,
            },
        }
        local_radius = 0.0 if response_disk is None else response_disk.radius
        return StageOutcome(
            digits=64,
            numerical_state=status.value,
            component_result=component_result,
            local_disk_radius_abs=local_radius,
            signed_error_channels=_component_stage_signed_error_channels(
                component_result,
                result,
                repeat_applicable=False,
                precision_ladder_applicable=False,
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

    def execute_promoted_response_repair(
        self,
        leaf: CampaignLeafPlan,
        digits: int,
        previous_outcomes: Sequence[StageOutcome],
    ) -> StageOutcome:
        """Repair response samples at a persisted root; never read a root."""

        if (
            leaf.mechanism_id not in {
                "horizon-admittance",
                "exterior-light-ring",
            }
            or digits not in self.precision_capabilities.digits
            or digits not in (80, 120)
            or tuple(stage.digits for stage in previous_outcomes) != (64, 80)
        ):
            raise NativeResourceUnavailableError(
                "root-sealed response repair requires a 64/80 promoted predecessor"
            )
        if self.julia_adapter is None:
            raise NativeResourceUnavailableError("M02 Julia precision worker is unavailable")
        raw_previous = previous_outcomes[-1].component_result.get("result")
        if not isinstance(raw_previous, Mapping):
            raise ValueError("root-sealed response repair predecessor is missing")
        previous_result = ComponentResult.from_mapping(raw_previous)
        seal = _sealed_root_for_result(previous_result)
        if seal is None:
            raise ValueError("root-sealed response repair predecessor lacks a seal")
        seal.validate_for(leaf.job)
        response_backend = self._julia_precision_backend_for(leaf.job, digits)
        if leaf.mechanism_id == "horizon-admittance":
            result = run_promoted_horizon_response_from_seal(
                leaf.job,
                response_backend,
                seal,
                derivative_step=leaf.job.policy.epsilons[0],
            )
        else:
            repair_families = _response_precision_limited_families(
                previous_result
            )
            if _root_sealed_response_migration_pending(previous_result):
                repair_families = frozenset({"frequency", "coordinate"})
            if not repair_families:
                raise ValueError(
                    "root-sealed exterior repair lacks a precision-limited "
                    "or migrated derivative family"
                )
            response_backend = _journaled_promoted_exterior_response_backend(
                leaf.job,
                response_backend,
                seal=seal,
                derivative_step=leaf.job.policy.epsilons[0],
                validation_reason=None,
                repair_families=repair_families,
            )
            result = _run_promoted_exterior_response_repair_with_progress(
                leaf.job,
                response_backend,
                seal,
                repair_families=repair_families,
                reusable_result=previous_result,
            )
        if leaf.mechanism_id == "horizon-admittance":
            response_repair_scope = "fixed-root-domega-stencil-only/v1"
        else:
            evidence = result.derivative_evidence
            if not isinstance(evidence, Mapping):
                raise ValueError("root-sealed exterior repair evidence is missing")
            scope = evidence.get("response_repair_scope")
            if not isinstance(scope, Mapping):
                raise ValueError("root-sealed exterior repair scope is missing")
            recomputed = scope.get("recomputed_families")
            reused = scope.get("reused_families")
            if not isinstance(recomputed, list) or not isinstance(reused, list):
                raise ValueError("root-sealed exterior repair scope is invalid")
            actual_families = frozenset(recomputed)
            response_repair_scope = (
                "fixed-root-domega-stencil-only/v1"
                if actual_families == {"frequency"}
                else "fixed-root-dc-stencil-only/v1"
                if actual_families == {"coordinate"}
                else "fixed-root-domega-dc-stencils-only/v1"
                if actual_families == {"frequency", "coordinate"}
                else None
            )
            if response_repair_scope is None:
                raise ValueError("root-sealed exterior repair scope is invalid")
        component_result = {
            "evidence_kind": _ROOT_SEALED_RESPONSE_REPAIR_EVIDENCE_KIND,
            "result": result.to_mapping(),
            "self_refinement_result": None,
            "self_refinement_skipped_reason": (
                _FIXED_ROOT_EXTERIOR_SELF_REFINEMENT_SKIPPED_REASON
            ),
            "scientific_runtime": response_backend.scientific_runtime_for(
                leaf.job
            ),
            "root_seal_sha256": seal.sha256,
            "response_repair_scope": response_repair_scope,
            "precision_ladder_discrepancy_applicable": False,
            "precision_ladder_discrepancy_reason": (
                _PREVIOUS_PROMOTED_RESPONSE_UNAVAILABLE_REASON
                if previous_result.response is None
                else None
            ),
        }
        local_radius = sum(result.error_channels.values())
        unbound = StageOutcome(
            digits=digits,
            numerical_state=result.status.value,
            component_result=component_result,
            local_disk_radius_abs=local_radius,
            signed_error_channels=_component_stage_signed_error_channels(
                component_result,
                result,
                repeat_applicable=False,
                precision_ladder_applicable=False,
            ),
            self_refinement_enclosed=None,
            discrepancy_from_previous_abs=None,
            discrepancy_enclosed=None,
        )
        return _bind_fixed_readout_precision_comparison(
            unbound, previous_outcomes[-1]
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

    def execute_promoted_stage_after_endpoint_arithmetic(
        self,
        leaf: CampaignLeafPlan,
        digits: int,
        predecessor: CampaignExecutionAttempt,
    ) -> StageOutcome:
        return self.execute_promoted_stage_after_endpoint_arithmetic_with_predictor(
            leaf, digits, predecessor, None
        )

    def execute_promoted_stage_after_endpoint_arithmetic_with_predictor(
        self,
        leaf: CampaignLeafPlan,
        digits: int,
        predecessor: CampaignExecutionAttempt,
        response_predictor: complex | None,
    ) -> StageOutcome:
        if (
            digits != 120
            or digits not in self.precision_capabilities.digits
            or not _is_single_promoted_horizon_stage(leaf, digits)
        ):
            raise NativeResourceUnavailableError(
                "endpoint-arithmetic recovery requires a 120-digit "
                "primary horizon capability"
            )
        _validate_endpoint_arithmetic_predecessor(predecessor, leaf)
        if self.julia_adapter is None:
            raise NativeResourceUnavailableError(
                "M02 Julia precision worker is unavailable"
            )
        primary_root_predictor = _failed_preflight_primary_root_predictor(
            predecessor
        )
        primary_backend = self._julia_precision_backend_for(leaf.job, 120)
        result = _run_promoted_horizon_component_with_progress(
            leaf.job,
            primary_backend,
            primary_root_predictor,
        )
        component_result = {
            "evidence_kind": (
                "package-owned-julia-single-promoted-horizon-component"
            ),
            "result": result.to_mapping(),
            "self_refinement_result": None,
            "self_refinement_skipped_reason": (
                "NOT_REQUIRED_BY_V1_4_PROMOTED_ROOT_POLICY"
            ),
            "scientific_runtime": primary_backend.scientific_runtime_for(
                leaf.job
            ),
            "primary_root_predictor_source": (
                "FAILED_80_REQUEST_BINARY64_BASELINE_OMEGA"
            ),
            "precision_ladder_discrepancy_applicable": False,
            "precision_ladder_discrepancy_reason": (
                "BINARY64_COMPONENT_RESPONSE_UNAVAILABLE"
            ),
        }
        local_radius = sum(result.error_channels.values())
        return StageOutcome(
            digits=120,
            numerical_state=result.status.value,
            component_result=component_result,
            local_disk_radius_abs=local_radius,
            signed_error_channels=_component_stage_signed_error_channels(
                component_result,
                result,
                repeat_applicable=False,
                precision_ladder_applicable=False,
            ),
            self_refinement_enclosed=None,
            discrepancy_from_previous_abs=None,
            discrepancy_enclosed=None,
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
        if _is_single_promoted_horizon_stage(leaf, digits):
            primary_root_predictor = _failed_preflight_primary_root_predictor(
                predecessor
            )
            primary_backend = self._julia_precision_backend_for(leaf.job, 120)
            result = _run_promoted_horizon_component_with_progress(
                leaf.job,
                primary_backend,
                primary_root_predictor,
            )
            component_result = {
                "evidence_kind": (
                    "package-owned-julia-single-promoted-horizon-component"
                ),
                "result": result.to_mapping(),
                "self_refinement_result": None,
                "self_refinement_skipped_reason": (
                    "NOT_REQUIRED_BY_V1_4_PROMOTED_ROOT_POLICY"
                ),
                "scientific_runtime": primary_backend.scientific_runtime_for(
                    leaf.job
                ),
                "primary_root_predictor_source": (
                    "FAILED_80_REQUEST_BINARY64_BASELINE_OMEGA"
                ),
                "precision_ladder_discrepancy_applicable": False,
                "precision_ladder_discrepancy_reason": (
                    "BINARY64_COMPONENT_RESPONSE_UNAVAILABLE"
                ),
                "failed_preflight_predecessor": predecessor.to_mapping(),
                "comparison_kind": _FAILED_PREFLIGHT_SINGLE_HORIZON_KIND,
            }
            local_radius = sum(result.error_channels.values())
            return StageOutcome(
                digits=120,
                numerical_state=result.status.value,
                component_result=component_result,
                local_disk_radius_abs=local_radius,
                signed_error_channels=_component_stage_signed_error_channels(
                    component_result,
                    result,
                    repeat_applicable=False,
                    precision_ladder_applicable=False,
                ),
                self_refinement_enclosed=None,
                discrepancy_from_previous_abs=None,
                discrepancy_enclosed=None,
            )
        base_backend = self._julia_precision_backend_for(leaf.job, 120)
        primary_root_predictor = _failed_preflight_exterior_root_predictor(
            predecessor
        )
        base = _run_promoted_exterior_component_with_progress(
            leaf.job,
            base_backend,
            primary_root_predictor,
        )
        base_radius = sum(base.error_channels.values())
        component_result = {
            "evidence_kind": (
                "package-owned-julia-fixed-root-exterior-derivative-component"
            ),
            "result": base.to_mapping(),
            "self_refinement_result": None,
            "self_refinement_skipped_reason": (
                _FIXED_ROOT_EXTERIOR_SELF_REFINEMENT_SKIPPED_REASON
            ),
            "scientific_runtime": base_backend.scientific_runtime_for(
                leaf.job
            ),
            "primary_root_predictor_source": (
                "FAILED_80_REQUEST_BINARY64_BASELINE_OMEGA"
            ),
            "failed_preflight_predecessor": predecessor.to_mapping(),
            "comparison_kind": _FAILED_PREFLIGHT_FIXED_ROOT_EXTERIOR_KIND,
            "precision_ladder_discrepancy_applicable": False,
            "precision_ladder_discrepancy_reason": (
                _BINARY64_RESPONSE_UNAVAILABLE_REASON
            ),
        }
        return StageOutcome(
            digits=120,
            numerical_state=base.status.value,
            component_result=component_result,
            local_disk_radius_abs=base_radius,
            signed_error_channels=_component_stage_signed_error_channels(
                component_result,
                base,
                repeat_applicable=False,
                precision_ladder_applicable=False,
            ),
            self_refinement_enclosed=None,
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
        previous_result = ComponentResult.from_mapping(
            previous_outcomes[-1].component_result["result"]
        )
        # Bounded analytic horizon stages are selected by mechanism, never by
        # a stale binary64 ladder-recovery hint.  Selective readout promotion
        # is admitted only for PRIMARY exterior-light-ring components.
        selective_recovery_allowed = (
            leaf.role == "primary"
            and leaf.mechanism_id == "exterior-light-ring"
            and not _is_single_promoted_horizon_stage(leaf, digits)
        )
        recovery = (
            previous_result.resolved_window
            if selective_recovery_allowed
            else None
        )
        selective_plan = (
            None
            if not isinstance(recovery, Mapping)
            else recovery.get("readout_specific_promotion_plan")
        )
        selective_tier = (
            None
            if not isinstance(recovery, Mapping)
            else recovery.get("next_precision_tier")
        )
        if selective_plan:
            semantic_trace: list[str] = []
            result = previous_result
            selective_backend = None
            while selective_plan:
                semantic_digits = {
                    "bigfloat-40": 40,
                    "bigfloat-80": 80,
                    "bigfloat-120": 120,
                }.get(selective_tier)
                if semantic_digits is None:
                    raise ValueError("selective promotion precision tier is invalid")
                selective_backend = self._julia_precision_backend_for(
                    leaf.job, semantic_digits
                )
                result = run_selective_readout_promotion(
                    leaf.job,
                    result,
                    selective_backend,
                    response_predictor,
                )
                semantic_trace.append(f"bigfloat-{semantic_digits}")
                if result.status is ComponentStatus.CONVERGED:
                    break
                recovery = result.resolved_window
                selective_plan = (
                    None
                    if not isinstance(recovery, Mapping)
                    else recovery.get("readout_specific_promotion_plan")
                )
                selective_tier = (
                    None
                    if not isinstance(recovery, Mapping)
                    else recovery.get("next_precision_tier")
                )
                if semantic_digits == 120:
                    break
            assert selective_backend is not None
            previous_response = previous_result.response
            precision_delta = (
                None
                if result.response is None or previous_response is None
                else result.response - previous_response
            )
            local_radius = sum(result.error_channels.values()) + (
                0.0 if precision_delta is None else abs(precision_delta)
            )
            component_result = {
                "evidence_kind": "package-owned-selective-readout-promotion",
                "result": result.to_mapping(),
                "scientific_runtime": selective_backend.scientific_runtime_for(
                    leaf.job
                ),
                "legacy_campaign_stage_digits": digits,
                "semantic_precision_tier": semantic_trace[-1],
                "semantic_selective_tier_trace": semantic_trace,
                "whole_component_promotion_used": False,
            }
            return StageOutcome(
                digits=digits,
                numerical_state=result.status.value,
                component_result=component_result,
                local_disk_radius_abs=local_radius,
                signed_error_channels=_component_stage_signed_error_channels(
                    component_result,
                    result,
                    precision_delta=0.0j if precision_delta is None else precision_delta,
                    repeat_applicable=False,
                    precision_ladder_applicable=precision_delta is not None,
                ),
                self_refinement_enclosed=None,
                discrepancy_from_previous_abs=(
                    None if precision_delta is None else abs(precision_delta)
                ),
                discrepancy_enclosed=None,
            )
        primary_backend = self._julia_precision_backend_for(leaf.job, digits)
        if _is_single_promoted_horizon_stage(leaf, digits):
            primary_root_predictor = previous_result.baseline.omega
            result = _run_promoted_horizon_component_with_progress(
                leaf.job,
                primary_backend,
                primary_root_predictor,
            )
            previous_response = previous_result.response
            precision_ladder_applicable = (
                result.response is not None and previous_response is not None
            )
            precision_delta = (
                result.response - previous_response
                if precision_ladder_applicable
                else None
            )
            discrepancy = (
                None if precision_delta is None else abs(precision_delta)
            )
            discrepancy_enclosed = (
                None
                if precision_delta is None
                else discrepancy
                <= (
                    sum(result.error_channels.values())
                    + previous_outcomes[-1].local_disk_radius_abs
                )
            )
            component_result = {
                "evidence_kind": (
                    "package-owned-julia-single-promoted-horizon-component"
                ),
                "result": result.to_mapping(),
                "self_refinement_result": None,
                "self_refinement_skipped_reason": (
                    "NOT_REQUIRED_BY_V1_4_PROMOTED_ROOT_POLICY"
                ),
                "scientific_runtime": primary_backend.scientific_runtime_for(
                    leaf.job
                ),
                "primary_root_predictor_source": (
                    "PREVIOUS_STAGE_BASELINE_OMEGA"
                ),
                "precision_ladder_discrepancy_applicable": (
                    precision_ladder_applicable
                ),
                "precision_ladder_discrepancy_reason": (
                    None
                    if precision_ladder_applicable
                    else (
                        "BINARY64_COMPONENT_RESPONSE_UNAVAILABLE"
                        if previous_outcomes[-1].digits == 64
                        else "PREVIOUS_PROMOTED_COMPONENT_RESPONSE_UNAVAILABLE"
                    )
                ),
            }
            local_radius = (
                sum(result.error_channels.values())
                + (0.0 if discrepancy is None else discrepancy)
            )
            return StageOutcome(
                digits=digits,
                numerical_state=result.status.value,
                component_result=component_result,
                local_disk_radius_abs=local_radius,
                signed_error_channels=_component_stage_signed_error_channels(
                    component_result,
                    result,
                    precision_delta=(
                        0.0j if precision_delta is None else precision_delta
                    ),
                    repeat_applicable=False,
                    precision_ladder_applicable=(
                        precision_ladder_applicable
                    ),
                ),
                self_refinement_enclosed=None,
                discrepancy_from_previous_abs=discrepancy,
                discrepancy_enclosed=discrepancy_enclosed,
            )
        result = _run_promoted_exterior_component_with_progress(
            leaf.job,
            primary_backend,
            previous_result.baseline.omega,
        )
        base_radius = sum(result.error_channels.values())
        component_result = {
            "evidence_kind": (
                "package-owned-julia-fixed-root-exterior-derivative-component"
            ),
            "result": result.to_mapping(),
            "self_refinement_result": None,
            "self_refinement_skipped_reason": (
                _FIXED_ROOT_EXTERIOR_SELF_REFINEMENT_SKIPPED_REASON
            ),
            "scientific_runtime": primary_backend.scientific_runtime_for(
                leaf.job
            ),
            "primary_root_predictor_source": (
                "PREVIOUS_STAGE_BASELINE_OMEGA"
            ),
            "precision_ladder_discrepancy_applicable": False,
            "precision_ladder_discrepancy_reason": (
                _BINARY64_RESPONSE_UNAVAILABLE_REASON
                if previous_outcomes[-1].digits == 64
                else _PREVIOUS_PROMOTED_RESPONSE_UNAVAILABLE_REASON
            ),
        }
        unbound = StageOutcome(
            digits=digits,
            numerical_state=result.status.value,
            component_result=component_result,
            local_disk_radius_abs=base_radius,
            signed_error_channels=_component_stage_signed_error_channels(
                component_result,
                result,
                repeat_applicable=False,
                precision_ladder_applicable=False,
            ),
            self_refinement_enclosed=None,
            discrepancy_from_previous_abs=None,
            discrepancy_enclosed=None,
        )
        return _bind_fixed_readout_precision_comparison(
            unbound, previous_outcomes[-1]
        )
