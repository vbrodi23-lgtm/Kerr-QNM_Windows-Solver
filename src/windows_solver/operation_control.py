"""Authenticated operation identity and promoted CONTROL transitions.

This module is the single control-plane boundary shared by the Julia adapter
and the promoted campaign.  It deliberately contains no solver code: it
validates identities and receipts, then performs an exact transition lookup.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from enum import Enum
import hashlib
from types import MappingProxyType
from typing import Callable, ClassVar, Mapping

from .contracts import canonical_json_bytes


OPERATION_EXECUTION_IDENTITY_SCHEMA = (
    "windows-solver.operation-execution-identity/1"
)
OPERATION_CONTROL_RECEIPT_SCHEMA = "windows-solver.operation-control-receipt/1"
OPERATION_CONTROL_FACT_RECEIPT_SCHEMA = (
    "windows-solver.operation-control-fact-receipt/2"
)
CANONICAL_REQUEST_BINDING_SCHEMA = "windows-solver.canonical-request-binding/1"

ROOT_READOUT_OPERATION = "root-readout"
FIXED_ROOT_SURVEY_BATCH_OPERATION = "fixed-root-survey-batch"
FIXED_ROOT_DETERMINANT_SAMPLE_OPERATION = "fixed-root-determinant-sample"
FIXED_ROOT_DEEP_CONTROL_PROFILE = "fixed-root-deep-v1"
PROMOTED_CONTROL_TRANSITION_SCHEMA = (
    "windows-solver.promoted-control-transition/2"
)

REQUEST_SCOPE = "REQUEST"
SAMPLE_SCOPE = "SAMPLE"

JULIA_WORKER_ORIGIN = "JULIA_WORKER"
PYTHON_SUPERVISOR_ORIGIN = "PYTHON_SUPERVISOR"

_COMMON_IDENTITY_FIELDS = frozenset({
    "schema",
    "scope",
    "operation",
    "request_schema",
    "request_sha256",
    "leaf_id",
    "job_id",
    "backend_identity_sha256",
    "precision_digits",
    "working_precision_bits",
    "semantic_precision_tier",
    "effective_policy_identity",
    "execution_resource_policy_identity",
})
_ROOT_REQUIRED_FIELDS = frozenset({
    "role",
    "job_policy_sha256",
    "refinement_level",
})
_ROOT_OPTIONAL_FIELDS = frozenset({
    "root_phase",
    "newton_index",
})
_FIXED_ROOT_DETERMINANT_REQUIRED_FIELDS = frozenset({
    "fixed_omega",
    "branch_identity",
    "readout_role",
})
_FIXED_ROOT_REQUIRED_FIELDS = frozenset({
    "control_profile",
    "plan",
    "scientific_operation_identity",
    "root_reference_id",
    "root_seal_sha256",
    "branch_identity",
    "sample_roles",
})
_SAMPLE_FIELDS = frozenset({"sample_index", "sample_role"})
_CONTROL_RECEIPT_FACT_FIELDS = frozenset({
    "schema",
    "origin",
    "failure_class",
    "failure_code",
    "stage",
    "scope",
    "execution_identity",
    "diagnostics",
    "canonical_request_binding",
    "receipt_sha256",
})
_CONTROL_RECEIPT_COMPATIBILITY_FIELDS = (
    _CONTROL_RECEIPT_FACT_FIELDS | {"retryable_evidence"}
)
_REQUEST_BINDING_FIELDS = frozenset({
    "schema",
    "operation",
    "request_schema",
    "request_sha256",
    "execution_identity_sha256",
})


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _is_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _is_nonempty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _identity_policy_hash(value: object, label: str) -> str:
    if _is_sha256(value):
        return str(value)
    if isinstance(value, Mapping) and _is_sha256(value.get("sha256")):
        return str(value["sha256"])
    raise ValueError(f"operation execution {label} identity is invalid")


def _immutable_identity_snapshot(value: object) -> object:
    """Recursively freeze one already-validated identity value."""

    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                key: _immutable_identity_snapshot(item)
                for key, item in value.items()
            }
        )
    if isinstance(value, (list, tuple)):
        return tuple(_immutable_identity_snapshot(item) for item in value)
    return copy.deepcopy(value)


def _mutable_identity_snapshot(value: object) -> object:
    """Return a detached JSON-shaped copy of a frozen identity value."""

    if isinstance(value, Mapping):
        return {
            key: _mutable_identity_snapshot(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_mutable_identity_snapshot(item) for item in value]
    return copy.deepcopy(value)


@dataclass(frozen=True, slots=True)
class OperationExecutionIdentity:
    """One validated REQUEST- or SAMPLE-scope execution identity."""

    mapping: Mapping[str, object]

    def __post_init__(self) -> None:
        validated = _validate_execution_identity_mapping(self.mapping)
        frozen = _immutable_identity_snapshot(validated)
        if not isinstance(frozen, Mapping):  # pragma: no cover - structural guard
            raise TypeError("operation execution identity snapshot is invalid")
        object.__setattr__(self, "mapping", frozen)

    @property
    def sha256(self) -> str:
        return canonical_sha256(self.to_mapping())

    @property
    def operation(self) -> str:
        return str(self.mapping["operation"])

    @property
    def scope(self) -> str:
        return str(self.mapping["scope"])

    @property
    def request_sha256(self) -> str:
        return str(self.mapping["request_sha256"])

    def to_mapping(self) -> dict[str, object]:
        mutable = _mutable_identity_snapshot(self.mapping)
        if not isinstance(mutable, dict):  # pragma: no cover - structural guard
            raise TypeError("operation execution identity snapshot is invalid")
        return mutable

    def select_sample(
        self,
        sample_index: int,
        sample_role: str,
    ) -> "OperationExecutionIdentity":
        if (
            self.operation != FIXED_ROOT_SURVEY_BATCH_OPERATION
            or self.scope != REQUEST_SCOPE
        ):
            raise ValueError("only a fixed-root REQUEST identity can select a sample")
        roles = tuple(self.mapping["sample_roles"])
        if (
            isinstance(sample_index, bool)
            or not isinstance(sample_index, int)
            or sample_index < 0
            or sample_index >= len(roles)
            or roles[sample_index] != sample_role
        ):
            raise ValueError("fixed-root sample identity does not match its descriptor")
        selected = self.to_mapping()
        selected["scope"] = SAMPLE_SCOPE
        selected["sample_index"] = sample_index
        selected["sample_role"] = sample_role
        return OperationExecutionIdentity(selected)


def _validate_execution_identity_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("operation execution identity must be an object")
    snapshot = _mutable_identity_snapshot(value)
    if not isinstance(snapshot, dict):  # pragma: no cover - narrowed above
        raise ValueError("operation execution identity must be an object")
    result = snapshot
    operation = result.get("operation")
    scope = result.get("scope")
    required = set(_COMMON_IDENTITY_FIELDS)
    allowed = set(_COMMON_IDENTITY_FIELDS)
    if operation in {ROOT_READOUT_OPERATION, FIXED_ROOT_DETERMINANT_SAMPLE_OPERATION}:
        required.update(_ROOT_REQUIRED_FIELDS)
        allowed.update(_ROOT_REQUIRED_FIELDS | _ROOT_OPTIONAL_FIELDS)
        if operation == FIXED_ROOT_DETERMINANT_SAMPLE_OPERATION:
            required.update(_FIXED_ROOT_DETERMINANT_REQUIRED_FIELDS)
            allowed.update(_FIXED_ROOT_DETERMINANT_REQUIRED_FIELDS)
    elif operation == FIXED_ROOT_SURVEY_BATCH_OPERATION:
        required.update(_FIXED_ROOT_REQUIRED_FIELDS)
        allowed.update(_FIXED_ROOT_REQUIRED_FIELDS)
    else:
        raise ValueError("operation execution identity operation is invalid")
    if scope == SAMPLE_SCOPE:
        if operation != FIXED_ROOT_SURVEY_BATCH_OPERATION:
            raise ValueError("SAMPLE scope is reserved for fixed-root batch samples")
        required.update(_SAMPLE_FIELDS)
        allowed.update(_SAMPLE_FIELDS)
    elif scope != REQUEST_SCOPE:
        raise ValueError("operation execution identity scope is invalid")
    if set(result) != required and not (
        operation in {ROOT_READOUT_OPERATION, FIXED_ROOT_DETERMINANT_SAMPLE_OPERATION}
        and required.issubset(result)
        and set(result).issubset(allowed)
    ):
        raise ValueError("operation execution identity fields are invalid")
    if result.get("schema") != OPERATION_EXECUTION_IDENTITY_SCHEMA:
        raise ValueError("operation execution identity schema is invalid")
    for field in (
        "request_schema",
        "leaf_id",
        "job_id",
        "semantic_precision_tier",
    ):
        if not _is_nonempty_text(result.get(field)):
            raise ValueError(f"operation execution identity {field} is invalid")
    for field in ("request_sha256", "backend_identity_sha256"):
        if not _is_sha256(result.get(field)):
            raise ValueError(f"operation execution identity {field} is invalid")
    for field in ("precision_digits", "working_precision_bits"):
        item = result.get(field)
        if isinstance(item, bool) or not isinstance(item, int) or item < 1:
            raise ValueError(f"operation execution identity {field} is invalid")
    _identity_policy_hash(result.get("effective_policy_identity"), "policy")
    _identity_policy_hash(
        result.get("execution_resource_policy_identity"), "resource-policy"
    )
    if operation in {ROOT_READOUT_OPERATION, FIXED_ROOT_DETERMINANT_SAMPLE_OPERATION}:
        for field in ("role", "job_policy_sha256"):
            item = result.get(field)
            if field.endswith("sha256"):
                valid = _is_sha256(item)
            else:
                valid = _is_nonempty_text(item)
            if not valid:
                raise ValueError(f"root-readout execution identity {field} is invalid")
        refinement = result.get("refinement_level")
        if isinstance(refinement, bool) or not isinstance(refinement, int) or refinement < 0:
            raise ValueError("root-readout refinement identity is invalid")
        if operation == FIXED_ROOT_DETERMINANT_SAMPLE_OPERATION:
            fixed_omega = result.get("fixed_omega")
            if (
                not isinstance(fixed_omega, Mapping)
                or set(fixed_omega) != {"real", "imaginary"}
                or any(
                    not _is_nonempty_text(fixed_omega.get(component))
                    for component in ("real", "imaginary")
                )
            ):
                raise ValueError(
                    "fixed-root determinant frequency identity is invalid"
                )
            for field in ("branch_identity", "readout_role"):
                if not _is_nonempty_text(result.get(field)):
                    raise ValueError(
                        f"fixed-root determinant {field} identity is invalid"
                    )
    else:
        for field in (
            "control_profile",
            "plan",
            "scientific_operation_identity",
            "root_reference_id",
            "branch_identity",
        ):
            if not _is_nonempty_text(result.get(field)):
                raise ValueError(f"fixed-root execution identity {field} is invalid")
        if result["control_profile"] != FIXED_ROOT_DEEP_CONTROL_PROFILE:
            raise ValueError("fixed-root control profile is not registered")
        if not _is_sha256(result.get("root_seal_sha256")):
            raise ValueError("fixed-root root seal identity is invalid")
        roles = result.get("sample_roles")
        if (
            not isinstance(roles, list)
            or not roles
            or any(not _is_nonempty_text(role) for role in roles)
            or len(set(roles)) != len(roles)
        ):
            raise ValueError("fixed-root sample-role identity is invalid")
        if scope == SAMPLE_SCOPE:
            index = result.get("sample_index")
            role = result.get("sample_role")
            if (
                isinstance(index, bool)
                or not isinstance(index, int)
                or index < 0
                or index >= len(roles)
                or roles[index] != role
            ):
                raise ValueError("fixed-root selected sample identity is invalid")
        elif _SAMPLE_FIELDS & set(result):
            raise ValueError("REQUEST identity cannot select a sample")
    return result


def operation_execution_identity(value: object) -> OperationExecutionIdentity:
    return OperationExecutionIdentity(value)  # type: ignore[arg-type]


def execution_identity_from_request(
    request: Mapping[str, object],
    *,
    request_sha256: str,
    sample_index: int | None = None,
    sample_role: str | None = None,
) -> OperationExecutionIdentity:
    """Project an authenticated wire request into its operation identity."""

    operation = request.get("operation")
    policy = request.get("policy")
    resource = request.get("execution_resource")
    if not isinstance(policy, Mapping) or not isinstance(resource, Mapping):
        raise ValueError("operation request policy identities are absent")
    common: dict[str, object] = {
        "schema": OPERATION_EXECUTION_IDENTITY_SCHEMA,
        "scope": REQUEST_SCOPE,
        "operation": operation,
        "request_schema": request.get(
            "schema",
            (
                "windows-solver.root-readout/1"
                if operation == ROOT_READOUT_OPERATION
                else "windows-solver.fixed-root-determinant-sample/1"
                if operation == FIXED_ROOT_DETERMINANT_SAMPLE_OPERATION
                else ""
            ),
        ),
        "request_sha256": request_sha256,
        "leaf_id": request.get("leaf_id"),
        "job_id": request.get("job_id"),
        "backend_identity_sha256": request.get("backend_identity_sha256"),
        "precision_digits": request.get("precision_digits"),
        "working_precision_bits": request.get("working_precision_bits"),
        "semantic_precision_tier": request.get("semantic_precision_tier"),
        "effective_policy_identity": canonical_sha256(dict(policy)),
        "execution_resource_policy_identity": {
            "schema": resource.get("schema"),
            "version": resource.get("version"),
            "sha256": resource.get("sha256"),
        },
    }
    if operation in {ROOT_READOUT_OPERATION, FIXED_ROOT_DETERMINANT_SAMPLE_OPERATION}:
        common.update({
            "role": request.get("role"),
            "job_policy_sha256": request.get("job_policy_sha256"),
            "refinement_level": request.get("refinement_level"),
        })
        for field in _ROOT_OPTIONAL_FIELDS:
            if field in request:
                common[field] = request[field]
        if operation == FIXED_ROOT_DETERMINANT_SAMPLE_OPERATION:
            common.update({
                "fixed_omega": copy.deepcopy(request.get("fixed_omega")),
                "branch_identity": policy.get("branch_convention"),
                "readout_role": request.get("readout_role"),
            })
    elif operation == FIXED_ROOT_SURVEY_BATCH_OPERATION:
        common.update({
            "control_profile": request.get("control_profile"),
            "plan": request.get("plan"),
            "scientific_operation_identity": request.get(
                "scientific_operation_identity"
            ),
            "root_reference_id": request.get("root_reference_id"),
            "root_seal_sha256": request.get("root_seal_sha256"),
            "branch_identity": request.get("branch_identity"),
            "sample_roles": copy.deepcopy(request.get("sample_roles")),
        })
    identity = OperationExecutionIdentity(common)
    if sample_index is None and sample_role is None:
        return identity
    if sample_index is None or sample_role is None:
        raise ValueError("sample identity requires both index and role")
    return identity.select_sample(sample_index, sample_role)


def canonical_request_binding(identity: OperationExecutionIdentity) -> dict[str, object]:
    return {
        "schema": CANONICAL_REQUEST_BINDING_SCHEMA,
        "operation": identity.operation,
        "request_schema": identity.mapping["request_schema"],
        "request_sha256": identity.request_sha256,
        "execution_identity_sha256": identity.sha256,
    }


class ValidatedControlReceipt:
    """Opaque proof that receipt digest, identity, binding, and evidence passed."""

    __slots__ = ("_mapping", "_identity", "_request")
    _TOKEN = object()

    def __init__(
        self,
        mapping: Mapping[str, object],
        identity: OperationExecutionIdentity,
        *,
        _token: object,
        request: Mapping[str, object] | None = None,
    ) -> None:
        if _token is not self._TOKEN:
            raise TypeError("ValidatedControlReceipt is minted only by its validator")
        frozen_mapping = _immutable_identity_snapshot(mapping)
        if not isinstance(frozen_mapping, Mapping):  # pragma: no cover
            raise TypeError("validated operation-control receipt is invalid")
        self._mapping = frozen_mapping
        self._identity = identity
        if request is None:
            self._request = None
        else:
            frozen_request = _immutable_identity_snapshot(request)
            if not isinstance(frozen_request, Mapping):  # pragma: no cover
                raise TypeError("validated canonical request is invalid")
            self._request = frozen_request

    @property
    def mapping(self) -> Mapping[str, object]:
        mutable = _mutable_identity_snapshot(self._mapping)
        if not isinstance(mutable, dict):  # pragma: no cover
            raise TypeError("validated operation-control receipt is invalid")
        return mutable

    @property
    def identity(self) -> OperationExecutionIdentity:
        return self._identity

    @property
    def sha256(self) -> str:
        return str(self._mapping["receipt_sha256"])

    @property
    def failure_code(self) -> str:
        return str(self._mapping["failure_code"])

    @property
    def stage(self) -> str:
        return str(self._mapping["stage"])

    @property
    def origin(self) -> str:
        return str(self._mapping["origin"])

    def to_mapping(self) -> dict[str, object]:
        mutable = _mutable_identity_snapshot(self._mapping)
        if not isinstance(mutable, dict):  # pragma: no cover
            raise TypeError("validated operation-control receipt is invalid")
        return mutable

    @property
    def canonical_request(self) -> Mapping[str, object] | None:
        if self._request is None:
            return None
        mutable = _mutable_identity_snapshot(self._request)
        if not isinstance(mutable, dict):  # pragma: no cover
            raise TypeError("validated canonical request is invalid")
        # The retained authority stays recursively frozen.  Callers receive a
        # detached JSON-shaped export so mutation cannot alter that authority.
        return mutable


def validate_operation_control_receipt(
    value: object,
    *,
    request: Mapping[str, object] | None = None,
    request_sha256: str | None = None,
    diagnostics_validator: Callable[[Mapping[str, object]], bool] | None = None,
) -> ValidatedControlReceipt:
    if not isinstance(value, Mapping):
        raise ValueError("operation control receipt fields are invalid")
    receipt = copy.deepcopy(dict(value))
    receipt_schema = receipt.get("schema")
    if receipt_schema == OPERATION_CONTROL_RECEIPT_SCHEMA:
        expected_fields = _CONTROL_RECEIPT_COMPATIBILITY_FIELDS
    elif receipt_schema == OPERATION_CONTROL_FACT_RECEIPT_SCHEMA:
        expected_fields = _CONTROL_RECEIPT_FACT_FIELDS
    else:
        raise ValueError("operation control receipt schema is invalid")
    if set(receipt) != expected_fields:
        raise ValueError("operation control receipt fields are invalid")
    content = {key: item for key, item in receipt.items() if key != "receipt_sha256"}
    if not _is_sha256(receipt.get("receipt_sha256")) or receipt["receipt_sha256"] != canonical_sha256(content):
        raise ValueError("operation control receipt digest is invalid")
    if receipt.get("origin") not in {JULIA_WORKER_ORIGIN, PYTHON_SUPERVISOR_ORIGIN}:
        raise ValueError("operation control receipt origin is invalid")
    if receipt.get("failure_class") != "CONTROL":
        raise ValueError("operation control receipt class is invalid")
    for field in ("failure_code", "stage"):
        if not _is_nonempty_text(receipt.get(field)):
            raise ValueError(f"operation control receipt {field} is invalid")
    identity = OperationExecutionIdentity(receipt["execution_identity"])
    if receipt.get("scope") != identity.scope:
        raise ValueError("operation control receipt scope is inconsistent")
    if receipt_schema == OPERATION_CONTROL_RECEIPT_SCHEMA:
        retryable = receipt.get("retryable_evidence")
        if (
            not isinstance(retryable, Mapping)
            or set(retryable) != {"retryable", "basis"}
            or not isinstance(retryable.get("retryable"), bool)
            or not _is_nonempty_text(retryable.get("basis"))
        ):
            raise ValueError("operation control retryability evidence is invalid")
    elif (
        identity.operation != FIXED_ROOT_SURVEY_BATCH_OPERATION
        or identity.mapping.get("request_schema")
        != "windows-solver.fixed-root-survey-batch/3"
        or identity.mapping.get("control_profile")
        != FIXED_ROOT_DEEP_CONTROL_PROFILE
    ):
        raise ValueError("operation control fact receipt is not fixed-root `/3`")
    diagnostics = receipt.get("diagnostics")
    if not isinstance(diagnostics, Mapping) or not diagnostics:
        raise ValueError("operation control diagnostics are incomplete")
    if diagnostics_validator is not None and not diagnostics_validator(receipt):
        raise ValueError("operation control diagnostics are invalid")
    binding = receipt.get("canonical_request_binding")
    if not isinstance(binding, Mapping) or set(binding) != _REQUEST_BINDING_FIELDS:
        raise ValueError("operation control request binding is invalid")
    expected_binding = canonical_request_binding(identity)
    if dict(binding) != expected_binding:
        raise ValueError("operation control identity binding is inconsistent")
    if request_sha256 is not None and identity.request_sha256 != request_sha256:
        raise ValueError("operation control request digest mismatch")
    if request is not None:
        if request_sha256 is None:
            request_sha256 = canonical_sha256(dict(request))
        expected_identity = execution_identity_from_request(
            request,
            request_sha256=request_sha256,
            sample_index=(
                int(identity.mapping["sample_index"])
                if identity.scope == SAMPLE_SCOPE
                else None
            ),
            sample_role=(
                str(identity.mapping["sample_role"])
                if identity.scope == SAMPLE_SCOPE
                else None
            ),
        )
        if identity.to_mapping() != expected_identity.to_mapping():
            raise ValueError("operation control identity does not match request")
    _validate_registered_control_emission(receipt, identity)
    return ValidatedControlReceipt(
        receipt,
        identity,
        _token=ValidatedControlReceipt._TOKEN,
        request=request,
    )


def build_operation_control_receipt(
    *,
    origin: str,
    failure_code: str,
    stage: str,
    identity: OperationExecutionIdentity,
    retryable: bool | None = None,
    retryable_basis: str | None = None,
    diagnostics: Mapping[str, object],
) -> dict[str, object]:
    content: dict[str, object] = {
        "schema": (
            OPERATION_CONTROL_FACT_RECEIPT_SCHEMA
            if identity.operation == FIXED_ROOT_SURVEY_BATCH_OPERATION
            and identity.mapping.get("request_schema")
            == "windows-solver.fixed-root-survey-batch/3"
            else OPERATION_CONTROL_RECEIPT_SCHEMA
        ),
        "origin": origin,
        "failure_class": "CONTROL",
        "failure_code": failure_code,
        "stage": stage,
        "scope": identity.scope,
        "execution_identity": identity.to_mapping(),
        "diagnostics": copy.deepcopy(dict(diagnostics)),
        "canonical_request_binding": canonical_request_binding(identity),
    }
    if content["schema"] == OPERATION_CONTROL_RECEIPT_SCHEMA:
        if not isinstance(retryable, bool) or not _is_nonempty_text(
            retryable_basis
        ):
            raise ValueError("compatibility retryability projection is absent")
        content["retryable_evidence"] = {
            "retryable": retryable,
            "basis": retryable_basis,
        }
    return {**content, "receipt_sha256": canonical_sha256(content)}


class ControlOutcomeKind(str, Enum):
    """Closed promoted-campaign outcomes owned by this module."""

    PROMOTION_PENDING = "PROMOTION_PENDING"
    UNRESOLVED = "UNRESOLVED"
    DEFERRED = "DEFERRED"
    REJECTED = "REJECTED"
    SYSTEM_FAILURE = "SYSTEM_FAILURE"


@dataclass(frozen=True, slots=True, init=False)
class ControlOutcome:
    """One internally minted outcome with no independently writable flags."""

    kind: ControlOutcomeKind
    reason_code: str
    queue_kind: str | None
    next_tier: str | None
    next_action_kind: str | None

    _TOKEN: ClassVar[object] = object()

    def __init__(
        self,
        *,
        kind: ControlOutcomeKind,
        reason_code: str,
        queue_kind: str | None,
        next_tier: str | None,
        next_action_kind: str | None,
        _token: object,
    ) -> None:
        if _token is not self._TOKEN:
            raise TypeError("ControlOutcome is minted only by operation_control")
        promotion = kind is ControlOutcomeKind.PROMOTION_PENDING
        continuation = (queue_kind, next_tier, next_action_kind)
        if (promotion and not all(item is not None for item in continuation)) or (
            not promotion and any(item is not None for item in continuation)
        ):
            raise ValueError("control outcome continuation fields are inconsistent")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "reason_code", reason_code)
        object.__setattr__(self, "queue_kind", queue_kind)
        object.__setattr__(self, "next_tier", next_tier)
        object.__setattr__(self, "next_action_kind", next_action_kind)

    @classmethod
    def _mint(
        cls,
        *,
        kind: ControlOutcomeKind,
        reason_code: str,
        queue_kind: str | None = None,
        next_tier: str | None = None,
        next_action_kind: str | None = None,
    ) -> "ControlOutcome":
        return cls(
            kind=kind,
            reason_code=reason_code,
            queue_kind=queue_kind,
            next_tier=next_tier,
            next_action_kind=next_action_kind,
            _token=cls._TOKEN,
        )

    @property
    def retryable(self) -> bool:
        return self.kind in {
            ControlOutcomeKind.PROMOTION_PENDING,
            ControlOutcomeKind.DEFERRED,
        }

    @property
    def terminal(self) -> bool:
        return not self.retryable

    @property
    def requires_promotion(self) -> bool:
        return self.kind is ControlOutcomeKind.PROMOTION_PENDING

    @property
    def containable(self) -> bool:
        return self.kind is not ControlOutcomeKind.SYSTEM_FAILURE

    @property
    def persist_return(self) -> bool:
        return True

    @property
    def persist_decision(self) -> bool:
        return True

    @property
    def explicitly_fatal(self) -> bool:
        return self.kind is ControlOutcomeKind.SYSTEM_FAILURE

    def to_mapping(self) -> dict[str, object]:
        """Serialize compatibility flags strictly as projections of ``kind``."""

        return {
            "kind": self.kind.value,
            "reason_code": self.reason_code,
            "retryable": self.retryable,
            "terminal": self.terminal,
            "requires_promotion": self.requires_promotion,
            "containable": self.containable,
            "queue_kind": self.queue_kind,
            "next_tier": self.next_tier,
            "next_action_kind": self.next_action_kind,
            "persist_return": self.persist_return,
            "persist_decision": self.persist_decision,
        }


@dataclass(frozen=True, slots=True, init=False)
class PromotedControlTransition:
    """Authenticated event identity and its sole canonical campaign outcome."""

    origin: str
    operation: str
    control_profile: str | None
    failure_code: str
    stage: str
    scope: str
    current_tier: str
    current_action_kind: str
    validator: str
    exception_type: str
    outcome: ControlOutcome

    _TOKEN: ClassVar[object] = object()

    def __init__(
        self,
        *,
        origin: str,
        operation: str,
        control_profile: str | None,
        failure_code: str,
        stage: str,
        scope: str,
        current_tier: str,
        current_action_kind: str,
        validator: str,
        exception_type: str,
        outcome: ControlOutcome,
        _token: object,
    ) -> None:
        if _token is not self._TOKEN:
            raise TypeError(
                "PromotedControlTransition is minted only by its registry"
            )
        for name, value in (
            ("origin", origin),
            ("operation", operation),
            ("failure_code", failure_code),
            ("stage", stage),
            ("scope", scope),
            ("current_tier", current_tier),
            ("current_action_kind", current_action_kind),
            ("validator", validator),
            ("exception_type", exception_type),
        ):
            if not _is_nonempty_text(value):
                raise ValueError(f"promoted CONTROL transition {name} is invalid")
            object.__setattr__(self, name, value)
        if control_profile is not None and not _is_nonempty_text(control_profile):
            raise ValueError("promoted CONTROL transition profile is invalid")
        object.__setattr__(self, "control_profile", control_profile)
        object.__setattr__(self, "outcome", outcome)

    @classmethod
    def from_authenticated_facts(
        cls,
        *,
        origin: str,
        operation: str,
        control_profile: str | None,
        failure_code: str,
        stage: str,
        scope: str,
        current_tier: str,
        current_action_kind: str,
        authorized_target_tier: str | None,
        validator: str,
        exception_type: str,
    ) -> "PromotedControlTransition":
        registered_promotion_queue = _NON_FIXED_CONTROL_PROMOTION_CODES.get(
            failure_code
        )
        registered_stages = _CONTROL_STAGE_BY_OPERATION.get(
            operation, {}
        ).get(failure_code, ())
        fixed_root_promotion = (
            operation == FIXED_ROOT_SURVEY_BATCH_OPERATION
            and control_profile == FIXED_ROOT_DEEP_CONTROL_PROFILE
            and failure_code == "EXTERIOR_ENDPOINT_ARITHMETIC_INADEQUATE"
            and stage == "asymptotic-preflight"
            and current_tier == "BF40"
            and authorized_target_tier == "BF80"
            and current_action_kind == "RESPONSE"
            and scope == SAMPLE_SCOPE
            and origin == JULIA_WORKER_ORIGIN
        )
        non_fixed_promotion = (
            operation != FIXED_ROOT_SURVEY_BATCH_OPERATION
            and registered_promotion_queue == current_action_kind
            and current_tier == "BF40"
            and authorized_target_tier == "BF80"
            and origin == JULIA_WORKER_ORIGIN
            and scope == REQUEST_SCOPE
            and stage in registered_stages
        )
        if fixed_root_promotion or non_fixed_promotion:
            outcome = ControlOutcome._mint(
                kind=ControlOutcomeKind.PROMOTION_PENDING,
                reason_code=failure_code,
                queue_kind=current_action_kind,
                next_tier="BF80",
                next_action_kind=current_action_kind,
            )
        elif failure_code in _EXPLICIT_FATAL_CODES:
            outcome = ControlOutcome._mint(
                kind=ControlOutcomeKind.SYSTEM_FAILURE,
                reason_code=failure_code,
            )
        elif failure_code in _DEFERRED_CODES:
            outcome = ControlOutcome._mint(
                kind=ControlOutcomeKind.DEFERRED,
                reason_code=failure_code,
            )
        elif failure_code in _REJECTED_CODES:
            outcome = ControlOutcome._mint(
                kind=ControlOutcomeKind.REJECTED,
                reason_code=failure_code,
            )
        else:
            outcome = ControlOutcome._mint(
                kind=ControlOutcomeKind.UNRESOLVED,
                reason_code=failure_code,
            )
        return cls(
            origin=origin,
            operation=operation,
            control_profile=control_profile,
            failure_code=failure_code,
            stage=stage,
            scope=scope,
            current_tier=current_tier,
            current_action_kind=current_action_kind,
            validator=validator,
            exception_type=exception_type,
            outcome=outcome,
            _token=cls._TOKEN,
        )

    @property
    def key(self) -> tuple[str, str, str | None, str, str, str, str, str]:
        return (
            self.origin,
            self.operation,
            self.control_profile,
            self.failure_code,
            self.stage,
            self.scope,
            self.current_tier,
            self.current_action_kind,
        )

    @property
    def outcome_kind(self) -> ControlOutcomeKind:
        return self.outcome.kind

    @property
    def disposition(self) -> str:
        return self.outcome.kind.value

    @property
    def retryable(self) -> bool:
        return self.outcome.retryable

    @property
    def terminal(self) -> bool:
        return self.outcome.terminal

    @property
    def requires_promotion(self) -> bool:
        return self.outcome.requires_promotion

    @property
    def containable(self) -> bool:
        return self.outcome.containable

    @property
    def queue_kind(self) -> str | None:
        return self.outcome.queue_kind

    @property
    def next_tier(self) -> str | None:
        return self.outcome.next_tier

    @property
    def next_action_kind(self) -> str | None:
        return self.outcome.next_action_kind

    @property
    def persist_return(self) -> bool:
        return self.outcome.persist_return

    @property
    def persist_decision(self) -> bool:
        return self.outcome.persist_decision

    @property
    def explicitly_fatal(self) -> bool:
        return self.outcome.explicitly_fatal

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema": PROMOTED_CONTROL_TRANSITION_SCHEMA,
            "event": {
                "origin": self.origin,
                "operation": self.operation,
                "control_profile": self.control_profile,
                "failure_code": self.failure_code,
                "stage": self.stage,
                "scope": self.scope,
                "current_tier": self.current_tier,
                "current_action_kind": self.current_action_kind,
                "validator": self.validator,
                "exception_type": self.exception_type,
            },
            "outcome": self.outcome.to_mapping(),
        }

    @property
    def transition_id(self) -> str:
        return canonical_sha256(self.to_mapping())


_JULIA_NUMERICAL_CONTROL_STAGE: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "SCATTERING_BASIS_ILL_CONDITIONED": ("scattering-extraction",),
    "SCATTERING_CHART_ILL_CONDITIONED": ("determinant-chart",),
    "ASYMPTOTIC_SERIES_INVALID": ("asymptotic-preflight",),
    "INSUFFICIENT_ASYMPTOTIC_PRECISION": ("asymptotic-preflight",),
    "PHYSICAL_SINGULAR_LIMIT": ("homogeneous-propagation",),
    "ALGEBRAIC_REPRESENTATION_SINGULAR": (
        "request-policy",
        "finite-difference",
        "determinant-chart",
        "homogeneous-propagation",
    ),
    "CARRIER_CHANGE_INCONSISTENT": ("homogeneous-propagation",),
    "INVALID_FACTORED_PROPAGATION_INPUT": ("homogeneous-propagation",),
    "FACTORED_PROPAGATION_PRECISION_MISMATCH": ("homogeneous-propagation",),
    "NONFINITE_FACTORED_PROPAGATION_DATA": ("homogeneous-propagation",),
    "FACTORED_ODE_FAILURE": ("homogeneous-propagation",),
    "NO_VERIFIED_HORIZON_ENDPOINT": ("horizon-endpoint-geometry",),
    "COORDINATE_INVERSION_STALLED": ("coordinate-inversion",),
    "DETERMINANT_UNCERTAINTY_TOO_LARGE": ("root-authentication",),
    "EXTERIOR_DETERMINANT_CERTIFICATE_UNAVAILABLE": (
        "asymptotic-preflight",
        "determinant-chart",
    ),
    "FINITE_DIFFERENCE_NOISE_LIMIT": ("finite-difference",),
    "HORIZON_GEOMETRY_EXHAUSTED": ("horizon-endpoint-geometry",),
    "HORIZON_MAXIMUM_ORDER_INADEQUATE": ("horizon-endpoint-geometry",),
    "HORIZON_ARITHMETIC_INADEQUATE": ("horizon-endpoint-geometry",),
    "HORIZON_COORDINATE_INVERSION_FAILED": ("coordinate-inversion",),
    "HORIZON_ONLY_ONE_ENDPOINT": ("horizon-endpoint-geometry",),
    "COORDINATE_IDENTITY_MISMATCH": ("coordinate-inversion",),
    "ODE_SOLVER_FAILURE": ("homogeneous-propagation",),
})
NUMERICAL_CONTROL_FAILURE_CODES = frozenset(
    _JULIA_NUMERICAL_CONTROL_STAGE
)

_ROOT_READOUT_CONTROL_STAGE: Mapping[str, tuple[str, ...]] = MappingProxyType({
    **dict(_JULIA_NUMERICAL_CONTROL_STAGE),
    "ODE_RESOURCE_LIMIT": ("homogeneous-propagation",),
    "ROOT_READOUT_RESOURCE_INFEASIBLE": ("request-policy",),
    "WORKER_TIMEOUT": ("worker-supervision",),
})
_FIXED_ROOT_SURVEY_CONTROL_STAGE: Mapping[str, tuple[str, ...]] = (
    MappingProxyType({
        **{
            code: stages
            for code, stages in _JULIA_NUMERICAL_CONTROL_STAGE.items()
            if code not in {
                "FINITE_DIFFERENCE_NOISE_LIMIT",
                "DETERMINANT_UNCERTAINTY_TOO_LARGE",
            }
        },
        # A fixed-root survey evaluates already-selected determinant samples;
        # it does not run the root request-policy or derivative ladder.
        "ALGEBRAIC_REPRESENTATION_SINGULAR": (
            "determinant-chart",
            "homogeneous-propagation",
        ),
        "EXTERIOR_ENDPOINT_MAXIMUM_ORDER_INADEQUATE": (
            "asymptotic-preflight",
        ),
        "EXTERIOR_ENDPOINT_GEOMETRY_EXHAUSTED": (
            "asymptotic-preflight",
        ),
        "EXTERIOR_ENDPOINT_ARITHMETIC_INADEQUATE": (
            "asymptotic-preflight",
        ),
        "ODE_RESOURCE_LIMIT": ("homogeneous-propagation",),
        "WORKER_TIMEOUT": ("worker-supervision",),
    })
)
_FIXED_ROOT_DETERMINANT_CONTROL_STAGE: Mapping[str, tuple[str, ...]] = (
    MappingProxyType({
        **{
            code: stages
            for code, stages in _FIXED_ROOT_SURVEY_CONTROL_STAGE.items()
            if not code.startswith("EXTERIOR_ENDPOINT_")
        },
        "WORKER_TIMEOUT": ("worker-supervision",),
    })
)
_CONTROL_STAGE_BY_OPERATION: Mapping[
    str, Mapping[str, tuple[str, ...]]
] = MappingProxyType({
    ROOT_READOUT_OPERATION: _ROOT_READOUT_CONTROL_STAGE,
    FIXED_ROOT_SURVEY_BATCH_OPERATION: _FIXED_ROOT_SURVEY_CONTROL_STAGE,
    FIXED_ROOT_DETERMINANT_SAMPLE_OPERATION: (
        _FIXED_ROOT_DETERMINANT_CONTROL_STAGE
    ),
})

def _validate_registered_control_emission(
    receipt: Mapping[str, object],
    identity: OperationExecutionIdentity,
) -> None:
    """Reject an operation/code/stage/scope combination no producer owns."""

    operation_stages = _CONTROL_STAGE_BY_OPERATION[identity.operation]
    code = str(receipt["failure_code"])
    stage = str(receipt["stage"])
    if stage not in operation_stages.get(code, ()):
        raise ValueError("operation control emission is not registered")
    timeout = code == "WORKER_TIMEOUT"
    expected_origin = PYTHON_SUPERVISOR_ORIGIN if timeout else JULIA_WORKER_ORIGIN
    expected_scope = (
        SAMPLE_SCOPE
        if identity.operation == FIXED_ROOT_SURVEY_BATCH_OPERATION
        and not timeout
        else REQUEST_SCOPE
    )
    if receipt.get("origin") != expected_origin or identity.scope != expected_scope:
        raise ValueError("operation control emission identity is incompatible")
    # Compatibility retryability is intentionally not interpreted here.  It
    # is checked against the exact transition only after tier and scheduler
    # action are authenticated by ``promoted_control_transition``.


_NON_FIXED_CONTROL_PROMOTION_CODES: Mapping[str, str] = MappingProxyType({
    "HORIZON_ARITHMETIC_INADEQUATE": "RESPONSE",
    "FINITE_DIFFERENCE_NOISE_LIMIT": "RESPONSE",
    "DETERMINANT_UNCERTAINTY_TOO_LARGE": "ROOT",
})
_DEFERRED_CODES = frozenset({
    "ODE_RESOURCE_LIMIT",
    "ROOT_READOUT_RESOURCE_INFEASIBLE",
    "WORKER_TIMEOUT",
})
_REJECTED_CODES = frozenset({
    "PHYSICAL_SINGULAR_LIMIT",
    "ALGEBRAIC_REPRESENTATION_SINGULAR",
})
_EXPLICIT_FATAL_CODES = frozenset({
    "ASYMPTOTIC_SERIES_INVALID",
    "CARRIER_CHANGE_INCONSISTENT",
    "EXTERIOR_DETERMINANT_CERTIFICATE_UNAVAILABLE",
    "FACTORED_ODE_FAILURE",
    "FACTORED_PROPAGATION_PRECISION_MISMATCH",
    "HORIZON_COORDINATE_INVERSION_FAILED",
    "INVALID_FACTORED_PROPAGATION_INPUT",
    "NONFINITE_FACTORED_PROPAGATION_DATA",
    "NO_VERIFIED_HORIZON_ENDPOINT",
    "COORDINATE_IDENTITY_MISMATCH",
    "ODE_SOLVER_FAILURE",
})


def _build_transition_registry() -> Mapping[
    tuple[str, str, str | None, str, str, str, str, str],
    PromotedControlTransition,
]:
    result: dict[
        tuple[str, str, str | None, str, str, str, str, str],
        PromotedControlTransition,
    ] = {}
    operation_actions = (
        (
            ROOT_READOUT_OPERATION,
            "ROOT",
            REQUEST_SCOPE,
            _CONTROL_STAGE_BY_OPERATION[ROOT_READOUT_OPERATION],
        ),
        # Promoted horizon response work owns a root-readout baseline.  Its
        # worker receipt still identifies the concrete root-readout operation,
        # while the scheduler action remains RESPONSE.  Keeping both values in
        # the transition key prevents that embedded readout from silently using
        # the standalone ROOT-queue authority.
        (
            ROOT_READOUT_OPERATION,
            "RESPONSE",
            REQUEST_SCOPE,
            _CONTROL_STAGE_BY_OPERATION[ROOT_READOUT_OPERATION],
        ),
        (
            FIXED_ROOT_SURVEY_BATCH_OPERATION,
            "RESPONSE",
            SAMPLE_SCOPE,
            _CONTROL_STAGE_BY_OPERATION[FIXED_ROOT_SURVEY_BATCH_OPERATION],
        ),
        # The promoted horizon derivative stencil uses the older one-sample
        # fixed-root operation rather than the batched exterior operation.
        # It therefore needs its own exact REQUEST-scope registry entries.
        (
            FIXED_ROOT_DETERMINANT_SAMPLE_OPERATION,
            "RESPONSE",
            REQUEST_SCOPE,
            _CONTROL_STAGE_BY_OPERATION[
                FIXED_ROOT_DETERMINANT_SAMPLE_OPERATION
            ],
        ),
    )
    for operation, action, scope, code_stages in operation_actions:
        for code, stages in code_stages.items():
            if (
                code == "WORKER_TIMEOUT"
                and operation == FIXED_ROOT_SURVEY_BATCH_OPERATION
            ):
                # The Python supervisor owns outer-process timeout and cannot
                # authenticate a Julia-selected descriptor after terminating
                # the process.  Its fixed-root receipt is REQUEST-scoped below.
                continue
            origin = PYTHON_SUPERVISOR_ORIGIN if code == "WORKER_TIMEOUT" else JULIA_WORKER_ORIGIN
            for stage in stages:
                for tier in ("BF40", "BF80"):
                    control_profile = (
                        FIXED_ROOT_DEEP_CONTROL_PROFILE
                        if operation == FIXED_ROOT_SURVEY_BATCH_OPERATION
                        else None
                    )
                    transition = PromotedControlTransition.from_authenticated_facts(
                        origin=origin,
                        operation=operation,
                        control_profile=control_profile,
                        failure_code=code,
                        stage=stage,
                        scope=scope,
                        current_tier=tier,
                        current_action_kind=action,
                        authorized_target_tier=(
                            "BF80" if tier == "BF40" else None
                        ),
                        validator=(
                            "supervisor-timeout/v1"
                            if origin == PYTHON_SUPERVISOR_ORIGIN
                            else "julia-control-diagnostics/v1"
                        ),
                        exception_type={
                            "WORKER_TIMEOUT": "JuliaWorkerTimeoutError",
                            "ODE_RESOURCE_LIMIT": "JuliaODEResourceLimitError",
                            "ROOT_READOUT_RESOURCE_INFEASIBLE": (
                                "JuliaRootReadoutResourceLimitError"
                            ),
                        }.get(code, "JuliaNumericalControlError"),
                    )
                    if transition.key in result:
                        raise RuntimeError("duplicate promoted control transition")
                    result[transition.key] = transition
    # A supervisor timeout may occur before Julia selects the first descriptor,
    # so fixed-root timeout has a separate, exact REQUEST-scope transition.
    for tier in ("BF40", "BF80"):
        transition = PromotedControlTransition.from_authenticated_facts(
            origin=PYTHON_SUPERVISOR_ORIGIN,
            operation=FIXED_ROOT_SURVEY_BATCH_OPERATION,
            control_profile=FIXED_ROOT_DEEP_CONTROL_PROFILE,
            failure_code="WORKER_TIMEOUT",
            stage="worker-supervision",
            scope=REQUEST_SCOPE,
            current_tier=tier,
            current_action_kind="RESPONSE",
            authorized_target_tier=("BF80" if tier == "BF40" else None),
            validator="supervisor-timeout/v1",
            exception_type="JuliaWorkerTimeoutError",
        )
        result[transition.key] = transition
    return MappingProxyType(result)


PROMOTED_CONTROL_TRANSITIONS = _build_transition_registry()


def promoted_control_transition(
    receipt: ValidatedControlReceipt,
    *,
    current_tier: str,
    current_action_kind: str,
) -> PromotedControlTransition:
    key = (
        receipt.origin,
        receipt.identity.operation,
        (
            str(receipt.identity.mapping["control_profile"])
            if "control_profile" in receipt.identity.mapping
            else None
        ),
        receipt.failure_code,
        receipt.stage,
        receipt.identity.scope,
        current_tier,
        current_action_kind,
    )
    try:
        transition = PROMOTED_CONTROL_TRANSITIONS[key]
    except KeyError as error:
        raise ValueError("promoted CONTROL outcome has no exact transition") from error
    retryable = receipt.mapping.get("retryable_evidence")
    if (
        isinstance(retryable, Mapping)
        and retryable.get("retryable") is not transition.retryable
    ):
        raise ValueError(
            "operation control retryability contradicts its canonical transition"
        )
    return transition


def expected_operation_control_retryability(
    failure_code: str,
    *,
    operation: str,
    current_tier: str | None = None,
    current_action_kind: str | None = None,
) -> bool:
    """Compatibility projection derived from canonical transitions only."""

    candidates = {
        transition.retryable
        for transition in PROMOTED_CONTROL_TRANSITIONS.values()
        if transition.failure_code == failure_code
        and transition.operation == operation
        and (
            current_tier is None or transition.current_tier == current_tier
        )
        and (
            current_action_kind is None
            or transition.current_action_kind == current_action_kind
        )
    }
    if len(candidates) != 1:
        raise ValueError(
            "operation control retryability requires one exact transition"
        )
    return candidates.pop()
