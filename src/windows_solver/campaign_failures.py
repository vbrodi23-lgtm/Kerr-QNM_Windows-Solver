"""Closed failure classification and immediate-abort pass boundary."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import re
from types import MappingProxyType
from typing import Callable, Mapping, Sequence

from .campaign_policy import validate_schema11_checkpoint
from .contracts import canonical_json_bytes
from .operation_control import (
    PROMOTED_CONTROL_TRANSITIONS,
    PromotedControlTransition,
)
from .progress import ProgressEventKind, emit_progress, progress_scope
from .structural_diagnostics import StructuralDiagnosticSession


class FailureDisposition(str, Enum):
    PROMOTION_PENDING = "PROMOTION_PENDING"
    UNRESOLVED = "UNRESOLVED"
    DEFERRED = "DEFERRED"
    REJECTED = "REJECTED"
    SYSTEM_FAILURE = "SYSTEM_FAILURE"


_REVIEWED_SCREENING_PROMOTION_REASONS = MappingProxyType({
    # These are non-receipt Binary64 screening outcomes.  A Julia CONTROL
    # receipt carrying the same diagnostic code is rejected above and must be
    # resolved by operation_control instead.
    "EXTERIOR_ENDPOINT_ARITHMETIC_INADEQUATE": "RESPONSE",
    "HORIZON_ARITHMETIC_INADEQUATE": "RESPONSE",
    "FINITE_DIFFERENCE_NOISE_LIMIT": "RESPONSE",
    "DETERMINANT_UNCERTAINTY_TOO_LARGE": "ROOT",
    "ROOT_UNCERTAINTY_EVIDENCE_UNAVAILABLE": "ROOT",
    "DETERMINANT_ERROR_EVIDENCE_UNAVAILABLE": "RESPONSE",
    "BLOCKED_BY_REVIEWED_ERROR_EVIDENCE": "RESPONSE",
    "ROOT_SEAL_UNAVAILABLE": "ROOT",
})

_LEAF_LOCAL_DISPOSITIONS = {
    # The generic package condition remains readable for legacy/internal
    # producers, but it has no promotion authority in schema 11.
    "INSUFFICIENT_ASYMPTOTIC_PRECISION": FailureDisposition.UNRESOLVED,
    "ODE_RESOURCE_LIMIT": FailureDisposition.DEFERRED,
    "ROOT_READOUT_RESOURCE_INFEASIBLE": FailureDisposition.DEFERRED,
    "COORDINATE_INVERSION_STALLED": FailureDisposition.UNRESOLVED,
    "HORIZON_GEOMETRY_EXHAUSTED": FailureDisposition.UNRESOLVED,
    "HORIZON_MAXIMUM_ORDER_INADEQUATE": FailureDisposition.UNRESOLVED,
    "HORIZON_ADMITTANCE_CHART_SINGULAR": FailureDisposition.UNRESOLVED,
    "HORIZON_ONLY_ONE_ENDPOINT": FailureDisposition.UNRESOLVED,
    "EXTERIOR_ENDPOINT_MAXIMUM_ORDER_INADEQUATE": (
        FailureDisposition.UNRESOLVED
    ),
    "EXTERIOR_ENDPOINT_GEOMETRY_EXHAUSTED": FailureDisposition.UNRESOLVED,
    "PHYSICAL_SINGULAR_LIMIT": FailureDisposition.REJECTED,
    "SCATTERING_BASIS_ILL_CONDITIONED": FailureDisposition.UNRESOLVED,
    "SCATTERING_CHART_ILL_CONDITIONED": FailureDisposition.UNRESOLVED,
    "ALGEBRAIC_REPRESENTATION_SINGULAR": FailureDisposition.REJECTED,
    "HORIZON_AXIS_MISMATCH": FailureDisposition.REJECTED,
    "HORIZON_BRANCH_LOSS": FailureDisposition.UNRESOLVED,
    "HORIZON_DERIVATIVE_UNRESOLVED": FailureDisposition.UNRESOLVED,
    "HORIZON_LADDER_EXHAUSTED": FailureDisposition.UNRESOLVED,
    "DETERMINANT_ERROR_MODEL_UNAVAILABLE": FailureDisposition.UNRESOLVED,
}
_SYSTEM_CAUSE_TYPES = frozenset(
    {
        "MethodError",
        "TypeError",
        "ValueError",
        "JSONDecodeError",
        "SchemaError",
        "ProtocolError",
        "DigestMismatchError",
        "BudgetBreachError",
    }
)
_PROMOTED_CONTROL_CODES = frozenset(
    transition.failure_code
    for transition in PROMOTED_CONTROL_TRANSITIONS.values()
)
_LEGACY_SYSTEM_FAILURE_RESOLUTION_RECEIPT_SCHEMA = (
    "windows-solver.system-failure-resolution/1"
)
SYSTEM_FAILURE_RESOLUTION_RECEIPT_SCHEMA = (
    "windows-solver.system-failure-resolution/2"
)
LAYER1_SYSTEM_FAILURE_RESOLUTION_RECEIPT_SCHEMA = (
    "windows-solver.layer1-system-failure-resolution/1"
)
_LAYER1_SYSTEM_FAILURE_RESOLUTION_SCOPE = (
    "RESUME_UNRETAINED_LAYER1_WORK_ONLY"
)
_SYSTEM_FAILURE_RESOLUTION_BASE_FIELDS = frozenset({
    "schema",
    "decision",
    "resolution_scope",
    "authority_sha256",
    "resolved_at_utc",
    "binary64_lock_receipt_sha256",
    "calibration_receipt_sha256",
    "system_failure_receipt_sha256",
    "failure_fingerprint_sha256",
    "repair_commit_sha",
    "reason",
    "receipt_sha256",
})
_SYSTEM_FAILURE_RESOLUTION_FIELDS = _SYSTEM_FAILURE_RESOLUTION_BASE_FIELDS | {
    "repair_runtime_sha256",
    "supersedes_resolution_receipt_sha256",
}
_LAYER1_SYSTEM_FAILURE_RESOLUTION_FIELDS = frozenset({
    "schema",
    "decision",
    "resolution_scope",
    "source_layer_state",
    "campaign_id",
    "selection_id",
    "source_checkpoint_sha256",
    "source_binary64_processed_count",
    "authority_sha256",
    "resolved_at_utc",
    "system_failure_receipt_sha256",
    "failure_fingerprint_sha256",
    "repair_commit_sha",
    "repair_runtime_sha256",
    "supersedes_resolution_receipt_sha256",
    "reason",
    "receipt_sha256",
})
_GIT_COMMIT_SHA_RE = re.compile(r"[0-9a-f]{40,64}")


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _is_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _validated_system_failure_resolution(
    value: Mapping[str, object],
) -> dict[str, object]:
    """Authenticate one append-only operator resolution receipt."""

    if not isinstance(value, Mapping) or value.get("schema") not in {
        _LEGACY_SYSTEM_FAILURE_RESOLUTION_RECEIPT_SCHEMA,
        SYSTEM_FAILURE_RESOLUTION_RECEIPT_SCHEMA,
    }:
        raise ValueError("system failure resolution receipt fields are invalid")
    expected_fields = (
        _SYSTEM_FAILURE_RESOLUTION_FIELDS
        if value.get("schema") == SYSTEM_FAILURE_RESOLUTION_RECEIPT_SCHEMA
        else _SYSTEM_FAILURE_RESOLUTION_BASE_FIELDS
    )
    if set(value) != expected_fields:
        raise ValueError("system failure resolution receipt fields are invalid")
    receipt = copy.deepcopy(dict(value))
    content = {key: item for key, item in receipt.items() if key != "receipt_sha256"}
    if (
        receipt.get("decision") != "RESOLVE_FOR_RESUME"
        or receipt.get("resolution_scope")
        != "RESUME_UNRETAINED_LAYER2_WORK_ONLY"
        or receipt.get("receipt_sha256") != _sha256(content)
    ):
        raise ValueError("system failure resolution receipt is invalid")
    for field in (
        "authority_sha256",
        "binary64_lock_receipt_sha256",
        "calibration_receipt_sha256",
        "system_failure_receipt_sha256",
        "failure_fingerprint_sha256",
        "receipt_sha256",
    ):
        if not _is_sha256(receipt.get(field)):
            raise ValueError("system failure resolution receipt digest is invalid")
    if (
        not isinstance(receipt.get("resolved_at_utc"), str)
        or not receipt["resolved_at_utc"]
        or not isinstance(receipt.get("reason"), str)
        or not receipt["reason"].strip()
        or not isinstance(receipt.get("repair_commit_sha"), str)
        or _GIT_COMMIT_SHA_RE.fullmatch(receipt["repair_commit_sha"]) is None
    ):
        raise ValueError("system failure resolution receipt identity is invalid")
    if receipt["schema"] == SYSTEM_FAILURE_RESOLUTION_RECEIPT_SCHEMA:
        if not _is_sha256(receipt.get("repair_runtime_sha256")):
            raise ValueError("system failure repair runtime identity is invalid")
        supersedes = receipt.get("supersedes_resolution_receipt_sha256")
        if supersedes is not None and not _is_sha256(supersedes):
            raise ValueError("system failure resolution supersession is invalid")
    return receipt


def _layer1_resolution_authority_sha256(
    *,
    campaign_id: str,
    selection_id: str,
    source_checkpoint_sha256: str,
    source_binary64_processed_count: int,
    system_failure_receipt_sha256: str,
    failure_fingerprint_sha256: str,
    repair_runtime_sha256: str,
) -> str:
    return _sha256({
        "schema": "windows-solver.layer1-system-failure-repair-authority/1",
        "campaign_id": campaign_id,
        "selection_id": selection_id,
        "source_checkpoint_sha256": source_checkpoint_sha256,
        "source_binary64_processed_count": source_binary64_processed_count,
        "system_failure_receipt_sha256": system_failure_receipt_sha256,
        "failure_fingerprint_sha256": failure_fingerprint_sha256,
        "repair_runtime_sha256": repair_runtime_sha256,
    })


def _validated_layer1_system_failure_resolution(
    value: Mapping[str, object],
) -> dict[str, object]:
    """Authenticate one pre-lock Layer-1 repair authority receipt."""

    if (
        not isinstance(value, Mapping)
        or value.get("schema")
        != LAYER1_SYSTEM_FAILURE_RESOLUTION_RECEIPT_SCHEMA
        or set(value) != _LAYER1_SYSTEM_FAILURE_RESOLUTION_FIELDS
    ):
        raise ValueError("Layer-1 system failure resolution fields are invalid")
    receipt = copy.deepcopy(dict(value))
    content = {key: item for key, item in receipt.items() if key != "receipt_sha256"}
    if (
        receipt.get("decision") != "RESOLVE_FOR_RESUME"
        or receipt.get("resolution_scope")
        != _LAYER1_SYSTEM_FAILURE_RESOLUTION_SCOPE
        or receipt.get("source_layer_state") != "BINARY64_UNLOCKED"
        or receipt.get("receipt_sha256") != _sha256(content)
    ):
        raise ValueError("Layer-1 system failure resolution is invalid")
    for field in (
        "source_checkpoint_sha256",
        "authority_sha256",
        "system_failure_receipt_sha256",
        "failure_fingerprint_sha256",
        "repair_runtime_sha256",
        "receipt_sha256",
    ):
        if not _is_sha256(receipt.get(field)):
            raise ValueError("Layer-1 system failure resolution digest is invalid")
    if (
        not isinstance(receipt.get("campaign_id"), str)
        or not receipt["campaign_id"]
        or not isinstance(receipt.get("selection_id"), str)
        or not receipt["selection_id"]
        or isinstance(receipt.get("source_binary64_processed_count"), bool)
        or not isinstance(receipt.get("source_binary64_processed_count"), int)
        or receipt["source_binary64_processed_count"] < 0
        or not isinstance(receipt.get("resolved_at_utc"), str)
        or not receipt["resolved_at_utc"]
        or not isinstance(receipt.get("reason"), str)
        or not receipt["reason"].strip()
        or not isinstance(receipt.get("repair_commit_sha"), str)
        or _GIT_COMMIT_SHA_RE.fullmatch(receipt["repair_commit_sha"]) is None
    ):
        raise ValueError("Layer-1 system failure resolution identity is invalid")
    supersedes = receipt.get("supersedes_resolution_receipt_sha256")
    if supersedes is not None and not _is_sha256(supersedes):
        raise ValueError("Layer-1 system failure resolution supersession is invalid")
    expected_authority = _layer1_resolution_authority_sha256(
        campaign_id=str(receipt["campaign_id"]),
        selection_id=str(receipt["selection_id"]),
        source_checkpoint_sha256=str(receipt["source_checkpoint_sha256"]),
        source_binary64_processed_count=int(
            receipt["source_binary64_processed_count"]
        ),
        system_failure_receipt_sha256=str(
            receipt["system_failure_receipt_sha256"]
        ),
        failure_fingerprint_sha256=str(receipt["failure_fingerprint_sha256"]),
        repair_runtime_sha256=str(receipt["repair_runtime_sha256"]),
    )
    if receipt["authority_sha256"] != expected_authority:
        raise ValueError("Layer-1 system failure repair authority is invalid")
    return receipt


def _validated_resolution_receipt(
    value: Mapping[str, object],
) -> dict[str, object]:
    if value.get("schema") == LAYER1_SYSTEM_FAILURE_RESOLUTION_RECEIPT_SCHEMA:
        return _validated_layer1_system_failure_resolution(value)
    return _validated_system_failure_resolution(value)


def system_failure_resolution_index(
    checkpoint: Mapping[str, object],
) -> dict[str, dict[str, object]]:
    """Return the latest authenticated receipt in each resolution chain."""

    validated = validate_schema11_checkpoint(checkpoint)
    failures: dict[str, Mapping[str, object]] = {}
    for candidate in validated["system_failures"]:
        if not isinstance(candidate, Mapping):
            raise ValueError("system failure receipt is invalid")
        content = {
            key: item for key, item in candidate.items() if key != "receipt_sha256"
        }
        receipt_sha256 = candidate.get("receipt_sha256")
        fingerprint = candidate.get("fingerprint_sha256")
        if (
            not _is_sha256(receipt_sha256)
            or receipt_sha256 != _sha256(content)
            or not _is_sha256(fingerprint)
        ):
            raise ValueError("system failure receipt is invalid")
        if receipt_sha256 in failures:
            raise ValueError("system failure receipt is duplicated")
        failures[receipt_sha256] = candidate
    result: dict[str, dict[str, object]] = {}
    for candidate in validated["recovery_receipts"]:
        if not isinstance(candidate, Mapping) or candidate.get("schema") not in {
            _LEGACY_SYSTEM_FAILURE_RESOLUTION_RECEIPT_SCHEMA,
            SYSTEM_FAILURE_RESOLUTION_RECEIPT_SCHEMA,
            LAYER1_SYSTEM_FAILURE_RESOLUTION_RECEIPT_SCHEMA,
        }:
            continue
        receipt = _validated_resolution_receipt(candidate)
        target = str(receipt["system_failure_receipt_sha256"])
        failure = failures.get(target)
        if failure is None or receipt["failure_fingerprint_sha256"] != (
            failure.get("fingerprint_sha256")
        ):
            raise ValueError("system failure resolution target is invalid")
        prior = result.get(target)
        supersedes = receipt.get("supersedes_resolution_receipt_sha256")
        if prior is not None:
            if supersedes != prior["receipt_sha256"]:
                raise ValueError("system failure has an invalid resolution chain")
        elif supersedes is not None:
            raise ValueError("system failure resolution supersedes a missing receipt")
        result[target] = receipt
    return result


def _retained_system_failure(
    checkpoint: Mapping[str, object], system_failure_receipt_sha256: str
) -> Mapping[str, object]:
    for candidate in checkpoint["system_failures"]:
        if not isinstance(candidate, Mapping):
            continue
        content = {
            key: item for key, item in candidate.items() if key != "receipt_sha256"
        }
        if (
            candidate.get("receipt_sha256") == system_failure_receipt_sha256
            and _is_sha256(candidate.get("receipt_sha256"))
            and candidate.get("receipt_sha256") == _sha256(content)
        ):
            return candidate
    raise ValueError("system failure receipt is not retained by this checkpoint")


def require_system_failures_resolved_for_binary64_resume(
    checkpoint: Mapping[str, object],
) -> tuple[dict[str, object], ...]:
    """Require current repair authority before continuing an unlocked Layer 1."""

    validated = validate_schema11_checkpoint(checkpoint)
    resolutions = system_failure_resolution_index(validated)
    from .production_wiring import promoted_runtime_identity_sha256

    runtime_sha256 = promoted_runtime_identity_sha256()
    active: list[str] = []
    authorised: list[dict[str, object]] = []
    for failure in validated["system_failures"]:
        target = str(failure["receipt_sha256"])
        receipt = resolutions.get(target)
        if (
            receipt is None
            or receipt.get("schema")
            != LAYER1_SYSTEM_FAILURE_RESOLUTION_RECEIPT_SCHEMA
            or receipt.get("campaign_id") != validated["campaign_id"]
            or receipt.get("selection_id") != validated["selection_id"]
            or receipt.get("repair_runtime_sha256") != runtime_sha256
        ):
            active.append(target)
        else:
            authorised.append(receipt)
    if active:
        raise ValueError(
            "binary64 resume is blocked by active SYSTEM_FAILURE receipts: "
            + ",".join(active)
        )
    return tuple(authorised)


def require_system_failures_resolved_for_promoted_resume(
    checkpoint: Mapping[str, object],
    *,
    expected_authority_sha256: str,
    calibration_receipt_sha256: str,
    binary64_lock_receipt_sha256: str,
) -> tuple[dict[str, object], ...]:
    """Fail closed until every software incident authorises this runtime."""

    if not all(
        _is_sha256(value)
        for value in (
            expected_authority_sha256,
            calibration_receipt_sha256,
            binary64_lock_receipt_sha256,
        )
    ):
        raise ValueError("promoted resume authority binding is invalid")
    validated = validate_schema11_checkpoint(checkpoint)
    resolutions = system_failure_resolution_index(validated)
    from .production_wiring import promoted_runtime_identity_sha256

    runtime_sha256 = promoted_runtime_identity_sha256()
    active: list[str] = []
    authorised: list[dict[str, object]] = []
    for failure in validated["system_failures"]:
        target = str(failure["receipt_sha256"])
        receipt = resolutions.get(target)
        layer1_authorised = (
            receipt is not None
            and receipt.get("schema")
            == LAYER1_SYSTEM_FAILURE_RESOLUTION_RECEIPT_SCHEMA
            and receipt.get("campaign_id") == validated["campaign_id"]
            and receipt.get("selection_id") == validated["selection_id"]
            and receipt.get("repair_runtime_sha256") == runtime_sha256
        )
        layer2_authorised = (
            receipt is not None
            and receipt.get("schema") == SYSTEM_FAILURE_RESOLUTION_RECEIPT_SCHEMA
            and receipt.get("authority_sha256") == expected_authority_sha256
            and receipt.get("calibration_receipt_sha256")
            == calibration_receipt_sha256
            and receipt.get("binary64_lock_receipt_sha256")
            == binary64_lock_receipt_sha256
            and receipt.get("repair_runtime_sha256") == runtime_sha256
        )
        if not (layer1_authorised or layer2_authorised):
            active.append(target)
        else:
            assert receipt is not None
            authorised.append(receipt)
    if active:
        raise ValueError(
            "promoted resume is blocked by active SYSTEM_FAILURE receipts: "
            + ",".join(active)
        )
    return tuple(authorised)


def resolve_system_failure_for_resume(
    checkpoint: Mapping[str, object],
    *,
    system_failure_receipt_sha256: str,
    expected_authority_sha256: str,
    calibration_receipt_sha256: str,
    binary64_lock_receipt_sha256: str,
    repair_commit_sha: str,
    reason: str,
    resolved_at_utc: str | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    """Append—not rewrite—operator authority to resume one failed Layer-2 pass.

    The historical failure remains in ``system_failures`` and no numerical
    state is modified.  The next promoted pass accepts the resume only when
    this authority, Layer-1 lock, calibration, and executing runtime all match.
    """

    result = validate_schema11_checkpoint(checkpoint)
    if not all(
        _is_sha256(value)
        for value in (
            system_failure_receipt_sha256,
            expected_authority_sha256,
            calibration_receipt_sha256,
            binary64_lock_receipt_sha256,
        )
    ):
        raise ValueError("system failure resolution binding digest is invalid")
    if (
        not isinstance(repair_commit_sha, str)
        or _GIT_COMMIT_SHA_RE.fullmatch(repair_commit_sha) is None
        or not isinstance(reason, str)
        or not reason.strip()
    ):
        raise ValueError("system failure resolution identity is invalid")

    failure = _retained_system_failure(result, system_failure_receipt_sha256)
    fingerprint = failure.get("fingerprint_sha256")
    if not _is_sha256(fingerprint):
        raise ValueError("system failure fingerprint is invalid")

    existing = system_failure_resolution_index(result).get(
        system_failure_receipt_sha256
    )
    from .production_wiring import promoted_runtime_identity_sha256

    repair_runtime_sha256 = promoted_runtime_identity_sha256()
    if existing is not None and (
        existing.get("schema") == SYSTEM_FAILURE_RESOLUTION_RECEIPT_SCHEMA
        and existing["authority_sha256"] == expected_authority_sha256
        and existing["calibration_receipt_sha256"] == calibration_receipt_sha256
        and existing["binary64_lock_receipt_sha256"]
        == binary64_lock_receipt_sha256
        and existing["failure_fingerprint_sha256"] == fingerprint
        and existing["repair_commit_sha"] == repair_commit_sha
        and existing["repair_runtime_sha256"] == repair_runtime_sha256
    ):
        return result, existing

    content = {
        "schema": SYSTEM_FAILURE_RESOLUTION_RECEIPT_SCHEMA,
        "decision": "RESOLVE_FOR_RESUME",
        "resolution_scope": "RESUME_UNRETAINED_LAYER2_WORK_ONLY",
        "authority_sha256": expected_authority_sha256,
        "resolved_at_utc": (
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            if resolved_at_utc is None
            else resolved_at_utc
        ),
        "binary64_lock_receipt_sha256": binary64_lock_receipt_sha256,
        "calibration_receipt_sha256": calibration_receipt_sha256,
        "system_failure_receipt_sha256": system_failure_receipt_sha256,
        "failure_fingerprint_sha256": fingerprint,
        "repair_commit_sha": repair_commit_sha,
        "repair_runtime_sha256": repair_runtime_sha256,
        "supersedes_resolution_receipt_sha256": (
            None if existing is None else existing["receipt_sha256"]
        ),
        "reason": reason.strip(),
    }
    receipt = {**content, "receipt_sha256": _sha256(content)}
    result["recovery_receipts"].append(receipt)
    return validate_schema11_checkpoint(result), receipt


def resolve_layer1_system_failure_for_resume(
    checkpoint: Mapping[str, object],
    *,
    system_failure_receipt_sha256: str,
    repair_commit_sha: str,
    reason: str,
    resolved_at_utc: str | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    """Authorise resumption of preserved Binary64 work before a lock exists."""

    result = validate_schema11_checkpoint(checkpoint)
    if (
        not _is_sha256(system_failure_receipt_sha256)
        or not isinstance(repair_commit_sha, str)
        or _GIT_COMMIT_SHA_RE.fullmatch(repair_commit_sha) is None
        or not isinstance(reason, str)
        or not reason.strip()
    ):
        raise ValueError("Layer-1 system failure resolution identity is invalid")
    from .binary64_layer_lock import promoted_layer2_state_exists

    if promoted_layer2_state_exists(result):
        raise ValueError("Layer-1 resolution cannot authorise promoted work")
    failure = _retained_system_failure(result, system_failure_receipt_sha256)
    fingerprint = failure.get("fingerprint_sha256")
    if not _is_sha256(fingerprint):
        raise ValueError("system failure fingerprint is invalid")
    existing = system_failure_resolution_index(result).get(
        system_failure_receipt_sha256
    )
    from .production_wiring import promoted_runtime_identity_sha256

    repair_runtime_sha256 = promoted_runtime_identity_sha256()
    if existing is not None:
        if existing.get("schema") != (
            LAYER1_SYSTEM_FAILURE_RESOLUTION_RECEIPT_SCHEMA
        ):
            raise ValueError(
                "system failure was resolved under a different lifecycle scope"
            )
        if (
            existing.get("repair_commit_sha") == repair_commit_sha
            and existing.get("repair_runtime_sha256") == repair_runtime_sha256
            and existing.get("failure_fingerprint_sha256") == fingerprint
            and existing.get("reason") == reason.strip()
        ):
            return result, existing

    source_checkpoint_sha256 = _sha256(result)
    source_binary64_processed_count = len(
        result["survey_pass_ledger"]["binary64"]
    )
    authority_sha256 = _layer1_resolution_authority_sha256(
        campaign_id=str(result["campaign_id"]),
        selection_id=str(result["selection_id"]),
        source_checkpoint_sha256=source_checkpoint_sha256,
        source_binary64_processed_count=source_binary64_processed_count,
        system_failure_receipt_sha256=system_failure_receipt_sha256,
        failure_fingerprint_sha256=str(fingerprint),
        repair_runtime_sha256=repair_runtime_sha256,
    )
    content = {
        "schema": LAYER1_SYSTEM_FAILURE_RESOLUTION_RECEIPT_SCHEMA,
        "decision": "RESOLVE_FOR_RESUME",
        "resolution_scope": _LAYER1_SYSTEM_FAILURE_RESOLUTION_SCOPE,
        "source_layer_state": "BINARY64_UNLOCKED",
        "campaign_id": result["campaign_id"],
        "selection_id": result["selection_id"],
        "source_checkpoint_sha256": source_checkpoint_sha256,
        "source_binary64_processed_count": source_binary64_processed_count,
        "authority_sha256": authority_sha256,
        "resolved_at_utc": (
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            if resolved_at_utc is None
            else resolved_at_utc
        ),
        "system_failure_receipt_sha256": system_failure_receipt_sha256,
        "failure_fingerprint_sha256": fingerprint,
        "repair_commit_sha": repair_commit_sha,
        "repair_runtime_sha256": repair_runtime_sha256,
        "supersedes_resolution_receipt_sha256": (
            None if existing is None else existing["receipt_sha256"]
        ),
        "reason": reason.strip(),
    }
    receipt = {**content, "receipt_sha256": _sha256(content)}
    _validated_layer1_system_failure_resolution(receipt)
    result["recovery_receipts"].append(receipt)
    return validate_schema11_checkpoint(result), receipt


@dataclass(frozen=True, slots=True)
class FailureReport:
    failure_code: str
    failure_class: str
    stage: str
    worker_operation: str
    request_schema: str
    backend_identity: str
    policy_identity: str
    precision_tier: str
    cause_type: str
    diagnostics: Mapping[str, object]
    request_sha256: str | None = None
    control_receipt_sha256: str | None = None
    execution_identity_sha256: str | None = None
    effective_policy_identity: str | None = None

    def __post_init__(self) -> None:
        identity_fields = (
            self.failure_code,
            self.failure_class,
            self.stage,
            self.worker_operation,
            self.request_schema,
            self.backend_identity,
            self.policy_identity,
            self.precision_tier,
            self.cause_type,
        )
        if any(not isinstance(item, str) or not item for item in identity_fields):
            raise ValueError("failure report identity fields are invalid")
        if not isinstance(self.diagnostics, Mapping):
            raise ValueError("failure diagnostics must be an object")
        for name in (
            "request_sha256",
            "control_receipt_sha256",
            "execution_identity_sha256",
            "effective_policy_identity",
        ):
            value = getattr(self, name)
            if value is not None and not _is_sha256(value):
                raise ValueError(f"failure report {name} is invalid")
        object.__setattr__(self, "diagnostics", copy.deepcopy(dict(self.diagnostics)))

    @property
    def fingerprint_material(self) -> dict[str, object]:
        material: dict[str, object] = {
            "failure_code": self.failure_code,
            "failure_class": self.failure_class,
            "stage": self.stage,
            "worker_operation": self.worker_operation,
            "request_schema": self.request_schema,
            "backend_identity": self.backend_identity,
            "policy_identity": self.policy_identity,
            "precision_tier": self.precision_tier,
            "cause_type": self.cause_type,
        }
        for name in (
            "request_sha256",
            "control_receipt_sha256",
            "execution_identity_sha256",
            "effective_policy_identity",
        ):
            value = getattr(self, name)
            if value is not None:
                material[name] = value
        return material

    @property
    def fingerprint_sha256(self) -> str:
        return _sha256(self.fingerprint_material)


@dataclass(frozen=True, slots=True)
class FailureDecision:
    disposition: FailureDisposition
    failure_code: str
    fingerprint_sha256: str
    queue_kind: str | None = None
    next_precision_tier: str | None = None
    next_action_kind: str | None = None
    control_receipt_sha256: str | None = None


class CampaignSystemFailure(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        receipt: Mapping[str, object],
        checkpoint: Mapping[str, object],
    ) -> None:
        super().__init__(message)
        self.receipt = dict(receipt)
        self.checkpoint = dict(checkpoint)


def classify_failure(report: FailureReport) -> FailureDecision:
    """Classify reviewed non-receipt outcomes; unknowns fail closed.

    Authenticated worker ``CONTROL`` outcomes are deliberately excluded from
    this screening boundary.  They must be resolved by ``operation_control``;
    downstream campaign code consumes that immutable canonical transition.
    """

    diagnostics_complete = report.diagnostics.get("complete") is True
    if (
        report.failure_class == "CONTROL"
        or (
            report.failure_class == "PROMOTED_SURVEY_DISPOSITION"
            and report.failure_code in _PROMOTED_CONTROL_CODES
        )
        or report.cause_type in _SYSTEM_CAUSE_TYPES
        or not diagnostics_complete
    ):
        disposition = FailureDisposition.SYSTEM_FAILURE
        queue_kind = None
    elif report.failure_code in _REVIEWED_SCREENING_PROMOTION_REASONS:
        disposition = FailureDisposition.PROMOTION_PENDING
        queue_kind = _REVIEWED_SCREENING_PROMOTION_REASONS[report.failure_code]
    elif report.failure_code in _LEAF_LOCAL_DISPOSITIONS:
        disposition = _LEAF_LOCAL_DISPOSITIONS[report.failure_code]
        queue_kind = None
    else:
        disposition = FailureDisposition.SYSTEM_FAILURE
        queue_kind = None
    return FailureDecision(
        disposition=disposition,
        failure_code=report.failure_code,
        fingerprint_sha256=report.fingerprint_sha256,
        queue_kind=queue_kind,
    )


def decision_from_control_transition(
    report: FailureReport,
    transition: PromotedControlTransition,
) -> FailureDecision:
    """Project one authenticated transition into failure-reporting form."""

    if (
        not isinstance(transition, PromotedControlTransition)
        or report.failure_code != transition.failure_code
        or report.diagnostics.get("complete") is not True
    ):
        raise ValueError("CONTROL failure report contradicts transition authority")
    return FailureDecision(
        disposition=FailureDisposition(transition.disposition),
        failure_code=transition.failure_code,
        fingerprint_sha256=report.fingerprint_sha256,
        queue_kind=transition.queue_kind,
        next_precision_tier=transition.next_tier,
        next_action_kind=transition.next_action_kind,
    )


def reviewed_screening_promotion_queue(reason_code: str) -> str | None:
    """Return a queue only for a reviewed, non-worker screening reason."""

    return _REVIEWED_SCREENING_PROMOTION_REASONS.get(reason_code)


def _system_failure_receipt(
    *,
    leaf_id: str,
    failure_code: str,
    cause_type: str,
    message: str,
    fingerprint_sha256: str,
    fingerprint_material: Mapping[str, object] | None = None,
) -> dict[str, object]:
    content: dict[str, object] = {
        "schema": "windows-solver.system-failure/v1",
        "leaf_id": leaf_id,
        "failure_code": failure_code,
        "cause_type": cause_type,
        "message": message,
        "fingerprint_sha256": fingerprint_sha256,
    }
    if fingerprint_material is not None:
        content["fingerprint_material"] = copy.deepcopy(dict(fingerprint_material))
    return {**content, "receipt_sha256": _sha256(content)}


def _abort_with_receipt(
    checkpoint: Mapping[str, object],
    *,
    leaf_id: str,
    failure_code: str,
    cause_type: str,
    message: str,
    fingerprint_sha256: str,
    persist_checkpoint: Callable[[dict[str, object]], None],
    fingerprint_material: Mapping[str, object] | None = None,
) -> None:
    durable = validate_schema11_checkpoint(checkpoint)
    receipt = _system_failure_receipt(
        leaf_id=leaf_id,
        failure_code=failure_code,
        cause_type=cause_type,
        message=message,
        fingerprint_sha256=fingerprint_sha256,
        fingerprint_material=fingerprint_material,
    )
    durable["system_failures"].append(receipt)
    durable["state"] = "PARTIAL"
    durable = validate_schema11_checkpoint(durable)
    persist_checkpoint(copy.deepcopy(durable))
    with progress_scope(
        leaf_id=leaf_id,
        system_failure_fingerprint=fingerprint_sha256,
    ):
        emit_progress(
            ProgressEventKind.SYSTEM_FAILURE_RECORDED,
            failure_code=failure_code,
            cause_type=cause_type,
        )
    raise CampaignSystemFailure(message, receipt=receipt, checkpoint=durable)


class ProductionFailureMonitor:
    """Retain repeated ordinary outcomes as diagnostic evidence only."""

    def __init__(
        self, *, diagnostic_session: StructuralDiagnosticSession | None = None
    ) -> None:
        self._leaves_by_fingerprint: dict[str, list[str]] = {}
        self._material_by_fingerprint: dict[str, dict[str, object]] = {}
        self._diagnostic_session = diagnostic_session

    def observe_leaf_outcome(
        self, leaf_id: str, report: FailureReport
    ) -> FailureDecision:
        """Classify one outcome without converting recurrence into an abort.

        A repeated numerical disposition is useful postmortem evidence, but
        it is not a system failure and cannot affect admission of later
        leaves.  Only a closed-table system classification may be escalated
        through :meth:`observe_system_failure`.
        """

        decision = classify_failure(report)
        return self._retain_leaf_decision(leaf_id, report, decision)

    def observe_control_transition(
        self,
        leaf_id: str,
        report: FailureReport,
        transition: PromotedControlTransition,
    ) -> FailureDecision:
        """Render a canonical CONTROL transition without reclassifying its code."""

        decision = decision_from_control_transition(report, transition)
        return self._retain_leaf_decision(leaf_id, report, decision)

    def _retain_leaf_decision(
        self,
        leaf_id: str,
        report: FailureReport,
        decision: FailureDecision,
    ) -> FailureDecision:
        if decision.disposition is FailureDisposition.SYSTEM_FAILURE:
            return decision
        seen = self._leaves_by_fingerprint.setdefault(
            decision.fingerprint_sha256, []
        )
        if leaf_id not in seen:
            seen.append(leaf_id)
        self._material_by_fingerprint[decision.fingerprint_sha256] = (
            dict(report.fingerprint_material)
        )
        observation = {
            "fingerprint_sha256": decision.fingerprint_sha256,
            "fingerprint_material": report.fingerprint_material,
            "failure_code": report.failure_code,
            "disposition": decision.disposition.value,
            "observation_count": len(seen),
            "first_leaf_id": seen[0],
            "latest_leaf_id": leaf_id,
            "all_observed_leaf_ids": list(seen),
            "campaign_aborted": False,
        }
        if self._diagnostic_session is not None:
            self._diagnostic_session.append(
                "LEAF_OUTCOME_OBSERVED",
                leaf={"leaf_id": leaf_id},
                compact_diagnostics=observation,
            )
            if len(seen) >= 2:
                self._diagnostic_session.append(
                    "REPEATED_LEAF_OUTCOME_OBSERVED",
                    leaf={"leaf_id": leaf_id},
                    compact_diagnostics=observation,
                )
        return decision

    def observe_system_failure(
        self,
        checkpoint: Mapping[str, object],
        *,
        leaf_id: str,
        report: FailureReport,
        persist_checkpoint: Callable[[dict[str, object]], None],
        transition: PromotedControlTransition | None = None,
    ) -> None:
        """Fail closed immediately for one actual system classification."""

        decision = (
            classify_failure(report)
            if transition is None
            else decision_from_control_transition(report, transition)
        )
        if decision.disposition is not FailureDisposition.SYSTEM_FAILURE:
            raise ValueError("only a classified system failure may abort a pass")
        if self._diagnostic_session is not None:
            self._diagnostic_session.append(
                "SYSTEM_FAILURE_CLASSIFIED",
                leaf={"leaf_id": leaf_id},
                compact_diagnostics={
                    "fingerprint_sha256": decision.fingerprint_sha256,
                    "failure_code": report.failure_code,
                    "cause_type": report.cause_type,
                    "campaign_aborted": True,
                },
                durable=True,
            )
        _abort_with_receipt(
            checkpoint,
            leaf_id=leaf_id,
            failure_code=report.failure_code,
            cause_type=report.cause_type,
            message="classified system failure aborted the active pass",
            fingerprint_sha256=decision.fingerprint_sha256,
            fingerprint_material=report.fingerprint_material,
            persist_checkpoint=persist_checkpoint,
        )

    def repeated_outcome_summary(self) -> dict[str, object]:
        """Return compact, deterministic advisory evidence for diagnostics."""

        observations = []
        for fingerprint in sorted(self._leaves_by_fingerprint):
            leaves = self._leaves_by_fingerprint[fingerprint]
            if len(leaves) < 2:
                continue
            observations.append(
                {
                    "fingerprint_sha256": fingerprint,
                    "leaf_ids": list(leaves),
                    "count": len(leaves),
                    "fingerprint_material": copy.deepcopy(
                        self._material_by_fingerprint[fingerprint]
                    ),
                }
            )
        return {
            "schema": "windows-solver.repeated-outcome-diagnostics/v1",
            "policy": "ADVISORY_REPEATED_ORDINARY_NUMERICAL_OUTCOMES",
            "armed": False,
            "fired": False,
            "observations": observations,
        }


def abort_unexpected_system_failure(
    checkpoint: Mapping[str, object],
    *,
    leaf_id: str,
    error: Exception,
    persist_checkpoint: Callable[[dict[str, object]], None],
) -> None:
    """Persist the last committed state and abort for an unexpected exception."""

    material = {
        "failure_code": "UNEXPECTED_SOFTWARE_ERROR",
        "cause_type": type(error).__name__,
        "message": str(error),
    }
    _abort_with_receipt(
        checkpoint,
        leaf_id=leaf_id,
        failure_code="UNEXPECTED_SOFTWARE_ERROR",
        cause_type=type(error).__name__,
        message=str(error),
        fingerprint_sha256=_sha256(material),
        persist_checkpoint=persist_checkpoint,
    )


def run_guarded_pass(
    leaf_ids: Sequence[str],
    *,
    checkpoint: Mapping[str, object],
    execute_leaf: Callable[[str], object],
    commit_leaf_outcome: Callable[[str, object], None],
    persist_checkpoint: Callable[[dict[str, object]], None],
) -> dict[str, object]:
    """Run leaves in order and stop before any work after a system failure."""

    durable = validate_schema11_checkpoint(checkpoint)
    failure_monitor = ProductionFailureMonitor()
    for leaf_id in leaf_ids:
        try:
            outcome = execute_leaf(leaf_id)
        except Exception as error:
            material = {
                "failure_code": "UNEXPECTED_SOFTWARE_ERROR",
                "cause_type": type(error).__name__,
                "message": str(error),
            }
            _abort_with_receipt(
                durable,
                leaf_id=leaf_id,
                failure_code="UNEXPECTED_SOFTWARE_ERROR",
                cause_type=type(error).__name__,
                message=str(error),
                fingerprint_sha256=_sha256(material),
                persist_checkpoint=persist_checkpoint,
            )
        if isinstance(outcome, FailureReport):
            decision = failure_monitor.observe_leaf_outcome(leaf_id, outcome)
            if decision.disposition is FailureDisposition.SYSTEM_FAILURE:
                failure_monitor.observe_system_failure(
                    durable,
                    leaf_id=leaf_id,
                    report=outcome,
                    persist_checkpoint=persist_checkpoint,
                )
            commit_leaf_outcome(leaf_id, decision)
        else:
            commit_leaf_outcome(leaf_id, outcome)
        persist_checkpoint(copy.deepcopy(durable))
    return durable


__all__ = [
    "CampaignSystemFailure",
    "FailureDecision",
    "FailureDisposition",
    "FailureReport",
    "LAYER1_SYSTEM_FAILURE_RESOLUTION_RECEIPT_SCHEMA",
    "SYSTEM_FAILURE_RESOLUTION_RECEIPT_SCHEMA",
    "ProductionFailureMonitor",
    "abort_unexpected_system_failure",
    "classify_failure",
    "decision_from_control_transition",
    "reviewed_screening_promotion_queue",
    "require_system_failures_resolved_for_binary64_resume",
    "require_system_failures_resolved_for_promoted_resume",
    "run_guarded_pass",
    "resolve_system_failure_for_resume",
    "resolve_layer1_system_failure_for_resume",
    "system_failure_resolution_index",
]
