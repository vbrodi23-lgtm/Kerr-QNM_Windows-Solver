"""Closed failure classification and immediate-abort pass boundary."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from enum import Enum
import hashlib
from types import MappingProxyType
from typing import Callable, Mapping, Sequence

from .campaign_policy import validate_schema11_checkpoint
from .contracts import canonical_json_bytes
from .progress import ProgressEventKind, emit_progress, progress_scope


class FailureDisposition(str, Enum):
    PROMOTION_PENDING = "PROMOTION_PENDING"
    UNRESOLVED = "UNRESOLVED"
    DEFERRED = "DEFERRED"
    REJECTED = "REJECTED"
    SYSTEM_FAILURE = "SYSTEM_FAILURE"


PROMOTION_ALLOWLIST = MappingProxyType(
    {
        "INSUFFICIENT_ASYMPTOTIC_PRECISION": "RESPONSE",
        "HORIZON_ARITHMETIC_INADEQUATE": "RESPONSE",
        "FINITE_DIFFERENCE_NOISE_LIMIT": "RESPONSE",
        "DETERMINANT_UNCERTAINTY_TOO_LARGE": "ROOT",
    }
)

_LEAF_LOCAL_DISPOSITIONS = {
    "ODE_RESOURCE_LIMIT": FailureDisposition.DEFERRED,
    "ROOT_READOUT_RESOURCE_INFEASIBLE": FailureDisposition.DEFERRED,
    "COORDINATE_INVERSION_STALLED": FailureDisposition.UNRESOLVED,
    "HORIZON_GEOMETRY_EXHAUSTED": FailureDisposition.UNRESOLVED,
    "HORIZON_MAXIMUM_ORDER_INADEQUATE": FailureDisposition.UNRESOLVED,
    "HORIZON_ONLY_ONE_ENDPOINT": FailureDisposition.UNRESOLVED,
    "PHYSICAL_SINGULAR_LIMIT": FailureDisposition.REJECTED,
    "SCATTERING_BASIS_ILL_CONDITIONED": FailureDisposition.UNRESOLVED,
    "SCATTERING_CHART_ILL_CONDITIONED": FailureDisposition.UNRESOLVED,
    "ALGEBRAIC_REPRESENTATION_SINGULAR": FailureDisposition.REJECTED,
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


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


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
        object.__setattr__(self, "diagnostics", copy.deepcopy(dict(self.diagnostics)))

    @property
    def fingerprint_material(self) -> dict[str, object]:
        return {
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

    @property
    def fingerprint_sha256(self) -> str:
        return _sha256(self.fingerprint_material)


@dataclass(frozen=True, slots=True)
class FailureDecision:
    disposition: FailureDisposition
    failure_code: str
    fingerprint_sha256: str
    queue_kind: str | None = None


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
    """Classify from reviewed static tables; unknowns fail closed."""

    diagnostics_complete = report.diagnostics.get("complete") is True
    if report.cause_type in _SYSTEM_CAUSE_TYPES or not diagnostics_complete:
        disposition = FailureDisposition.SYSTEM_FAILURE
        queue_kind = None
    elif report.failure_code in PROMOTION_ALLOWLIST:
        disposition = FailureDisposition.PROMOTION_PENDING
        queue_kind = PROMOTION_ALLOWLIST[report.failure_code]
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


def _system_failure_receipt(
    *,
    leaf_id: str,
    failure_code: str,
    cause_type: str,
    message: str,
    fingerprint_sha256: str,
) -> dict[str, object]:
    content: dict[str, object] = {
        "schema": "windows-solver.system-failure/v1",
        "leaf_id": leaf_id,
        "failure_code": failure_code,
        "cause_type": cause_type,
        "message": message,
        "fingerprint_sha256": fingerprint_sha256,
    }
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
) -> None:
    durable = validate_schema11_checkpoint(checkpoint)
    receipt = _system_failure_receipt(
        leaf_id=leaf_id,
        failure_code=failure_code,
        cause_type=cause_type,
        message=message,
        fingerprint_sha256=fingerprint_sha256,
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
    fingerprints: dict[str, set[str]] = {}
    armed_fingerprint: str | None = None
    for leaf_id in leaf_ids:
        if armed_fingerprint is not None:
            _abort_with_receipt(
                durable,
                leaf_id=leaf_id,
                failure_code="REPEATED_LEAF_FAILURE_FINGERPRINT",
                cause_type="RepetitionBreaker",
                message="failure repetition breaker stopped the pass before the third leaf",
                fingerprint_sha256=armed_fingerprint,
                persist_checkpoint=persist_checkpoint,
            )
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
            decision = classify_failure(outcome)
            if decision.disposition is FailureDisposition.SYSTEM_FAILURE:
                _abort_with_receipt(
                    durable,
                    leaf_id=leaf_id,
                    failure_code=outcome.failure_code,
                    cause_type=outcome.cause_type,
                    message="classified system failure aborted the active pass",
                    fingerprint_sha256=decision.fingerprint_sha256,
                    persist_checkpoint=persist_checkpoint,
                )
            commit_leaf_outcome(leaf_id, decision)
            seen = fingerprints.setdefault(decision.fingerprint_sha256, set())
            seen.add(leaf_id)
            if len(seen) >= 2:
                armed_fingerprint = decision.fingerprint_sha256
        else:
            commit_leaf_outcome(leaf_id, outcome)
        persist_checkpoint(copy.deepcopy(durable))
    return durable


__all__ = [
    "CampaignSystemFailure",
    "FailureDecision",
    "FailureDisposition",
    "FailureReport",
    "PROMOTION_ALLOWLIST",
    "abort_unexpected_system_failure",
    "classify_failure",
    "run_guarded_pass",
]
