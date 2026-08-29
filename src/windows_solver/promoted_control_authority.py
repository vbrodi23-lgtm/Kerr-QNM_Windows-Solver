"""Route-independent authority for persisted promoted CONTROL evidence.

Checkpoint hashes prove that retained bytes have not changed; they do not
prove that a retained decision is the registry result for its worker receipt.
This module closes that distinction below campaign policy.  Raw-return
authentication owns the exact request, producer diagnostics and work account.
Decision authentication separately owns the immutable canonical transition
and its derived fingerprint material.

The persisted-receipt import is deliberately local.  The Julia adapter owns
the code-specific diagnostic validators, while this module owns no adapter or
campaign route.  Keeping that dependency lazy lets campaign policy and failure
classification share this authority without an import cycle.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from decimal import Decimal
import math
from types import MappingProxyType
from typing import Mapping

from .operation_control import (
    PromotedControlTransition,
    FIXED_ROOT_SURVEY_BATCH_OPERATION,
    ROOT_READOUT_OPERATION,
    ValidatedControlReceipt,
    authenticate_promoted_control_transition,
    canonical_sha256,
    execution_identity_from_request,
    promoted_control_transition,
)


_CONTROL_DECISION_FIELDS = frozenset({
    "schema",
    "control_return_sha256",
    "control_receipt_sha256",
    "failure_code",
    "failure_fingerprint_sha256",
    "fingerprint_material",
    "transition_id",
    "transition",
    "disposition",
    "queue_kind",
    "current_tier",
    "current_action_kind",
    "next_tier",
    "next_action_kind",
    "control_decision_sha256",
})
_PROMOTED_PARTIAL_WORK_SCHEMA = "windows-solver.promoted-partial-work/2"
_PROMOTED_ATTEMPT_RECORD_SCHEMA = "windows-solver.promoted-worker-attempt/1"
_PROMOTED_EXPECTED_ACTION_SCHEMA = (
    "windows-solver.promoted-expected-fixed-root-action/1"
)
_PROMOTED_CANONICAL_BACKGROUND_RECEIPT_SCHEMA = (
    "windows-solver.promoted-canonical-background-receipt/3"
)
_EXTERIOR_PROVISIONAL_REUSE_RECEIPT_SCHEMA = (
    "windows-solver.exterior-provisional-reuse-decision/1"
)


@dataclass(frozen=True, slots=True)
class ControlWorkAccounting:
    """Work derived only from authenticated receipts and attempt records."""

    evidence_receipts: tuple[Mapping[str, object], ...]
    attempt_records: tuple[Mapping[str, object], ...]
    sample_count: int
    root_read_count: int
    worker_launch_count: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "evidence_receipts",
            tuple(
                MappingProxyType(copy.deepcopy(dict(item)))
                for item in self.evidence_receipts
            ),
        )
        object.__setattr__(
            self,
            "attempt_records",
            tuple(
                MappingProxyType(copy.deepcopy(dict(item)))
                for item in self.attempt_records
            ),
        )
        for name in ("sample_count", "root_read_count", "worker_launch_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("persisted CONTROL work accounting is invalid")

    def receipts(self) -> list[dict[str, object]]:
        return [copy.deepcopy(dict(item)) for item in self.evidence_receipts]


def _effective_policy_sha256(receipt: ValidatedControlReceipt) -> str:
    effective_policy = receipt.identity.mapping["effective_policy_identity"]
    if isinstance(effective_policy, Mapping):
        return str(effective_policy["sha256"])
    return str(effective_policy)


def _authenticated_artifact_digest(
    artifact: Mapping[str, object],
    digest_field: str,
) -> str:
    supplied = artifact.get(digest_field)
    content = {
        name: item for name, item in artifact.items() if name != digest_field
    }
    expected = canonical_sha256(content)
    if supplied != expected:
        raise ValueError("persisted CONTROL artifact digest is invalid")
    return expected


def _validated_expected_action(
    value: object,
    *,
    queue_ordinal: int,
    leaf_id: str,
    tier: str,
) -> dict[str, object]:
    fields = {
        "schema",
        "queue_ordinal",
        "leaf_id",
        "job_id",
        "backend_identity_sha256",
        "tier",
        "current_action_kind",
        "operation",
        "plan",
        "scientific_operation_identity",
        "sample_roles",
        "root_reference_id",
        "root_seal_sha256",
        "branch_identity",
        "precision_digits",
        "request_sha256",
        "request_execution_identity_sha256",
        "action_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError("persisted CONTROL expected-action fields are invalid")
    content = {name: item for name, item in value.items() if name != "action_sha256"}
    precision_digits = value.get("precision_digits")
    expected_tier = (
        None
        if isinstance(precision_digits, bool)
        or not isinstance(precision_digits, int)
        else f"BF{precision_digits}"
    )
    if (
        value.get("schema") != _PROMOTED_EXPECTED_ACTION_SCHEMA
        or value.get("action_sha256") != canonical_sha256(content)
        or value.get("operation") != FIXED_ROOT_SURVEY_BATCH_OPERATION
        or value.get("current_action_kind") != "RESPONSE"
        or value.get("queue_ordinal") != queue_ordinal
        or value.get("leaf_id") != leaf_id
        or value.get("tier") != tier
        or expected_tier != tier
        or not isinstance(value.get("sample_roles"), list)
        or not value["sample_roles"]
        or any(
            not isinstance(value.get(name), str) or not value.get(name)
            for name in (
                "job_id",
                "backend_identity_sha256",
                "plan",
                "scientific_operation_identity",
                "root_reference_id",
                "root_seal_sha256",
                "branch_identity",
                "request_sha256",
                "request_execution_identity_sha256",
            )
        )
    ):
        raise ValueError("persisted CONTROL expected action is invalid")
    return copy.deepcopy(dict(value))


def _bind_attempt_to_expected_action(
    receipt: ValidatedControlReceipt,
    expected: Mapping[str, object],
) -> None:
    canonical_request = receipt.canonical_request
    if canonical_request is None:
        raise ValueError("persisted CONTROL attempt lost its canonical request")
    request_identity = execution_identity_from_request(
        canonical_request,
        request_sha256=receipt.identity.request_sha256,
    )
    shared = {
        "operation": expected["operation"],
        "leaf_id": expected["leaf_id"],
        "job_id": expected["job_id"],
        "backend_identity_sha256": expected["backend_identity_sha256"],
        "precision_digits": expected["precision_digits"],
        "plan": expected["plan"],
        "scientific_operation_identity": expected[
            "scientific_operation_identity"
        ],
        "root_reference_id": expected["root_reference_id"],
        "root_seal_sha256": expected["root_seal_sha256"],
        "branch_identity": expected["branch_identity"],
    }
    receipt_identity = receipt.identity.mapping
    if (
        receipt.identity.request_sha256 != expected["request_sha256"]
        or request_identity.sha256
        != expected["request_execution_identity_sha256"]
        or any(
            request_identity.mapping.get(name) != item
            for name, item in shared.items()
        )
        or any(receipt_identity.get(name) != item for name, item in shared.items())
        or tuple(request_identity.mapping.get("sample_roles", ()))
        != tuple(expected["sample_roles"])
        or tuple(receipt_identity.get("sample_roles", ()))
        != tuple(expected["sample_roles"])
    ):
        raise ValueError("persisted CONTROL attempt phase identity is invalid")


def _validated_attempt_record(
    value: object,
    *,
    queue_ordinal: int,
    leaf_id: str,
) -> tuple[dict[str, object], ValidatedControlReceipt]:
    fields = {
        "schema",
        "current_tier",
        "current_action_kind",
        "expected_action",
        "canonical_request",
        "control_receipt",
        "control_receipt_sha256",
        "attempt_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError("persisted CONTROL attempt fields are invalid")
    content = {name: item for name, item in value.items() if name != "attempt_sha256"}
    canonical_request = value.get("canonical_request")
    control_receipt = value.get("control_receipt")
    tier = value.get("current_tier")
    action = value.get("current_action_kind")
    if (
        value.get("schema") != _PROMOTED_ATTEMPT_RECORD_SCHEMA
        or value.get("attempt_sha256") != canonical_sha256(content)
        or tier not in {"BF40", "BF80"}
        or action not in {"ROOT", "RESPONSE"}
        or not isinstance(canonical_request, Mapping)
        or not isinstance(control_receipt, Mapping)
    ):
        raise ValueError("persisted CONTROL attempt is invalid")

    from .julia_response_backend import (  # local by dependency design
        validate_persisted_operation_control_receipt,
    )

    receipt = validate_persisted_operation_control_receipt(
        control_receipt,
        canonical_request,
    )
    expected_operation = (
        ROOT_READOUT_OPERATION
        if action == "ROOT"
        else FIXED_ROOT_SURVEY_BATCH_OPERATION
    )
    if (
        receipt.sha256 != value.get("control_receipt_sha256")
        or receipt.identity.operation != expected_operation
        or receipt.identity.mapping.get("leaf_id") != leaf_id
        or receipt.identity.mapping.get("semantic_precision_tier")
        != f"bigfloat-{str(tier)[2:]}"
    ):
        raise ValueError("persisted CONTROL attempt identity is invalid")
    if action == "RESPONSE":
        expected = _validated_expected_action(
            value.get("expected_action"),
            queue_ordinal=queue_ordinal,
            leaf_id=leaf_id,
            tier=str(tier),
        )
        _bind_attempt_to_expected_action(receipt, expected)
    elif value.get("expected_action") is not None:
        raise ValueError("persisted root attempt has an inapplicable action")
    return copy.deepcopy(dict(value)), receipt


def _promoted_sample_from_mapping(value: object) -> object:
    if not isinstance(value, Mapping) or set(value) != {
        "sample_index",
        "sample_role",
        "execution_identity",
        "omega",
        "amplitude",
        "determinant",
        "numerical_conditioning",
        "determinant_error_evidence",
    }:
        raise ValueError("persisted promoted sample is invalid")

    from .julia_response_backend import (
        DecimalComplex,
        ExteriorDeterminantErrorEvidence,
        FixedRootSurveyConditioning,
        JuliaFixedRootSurveySample,
    )

    def complex_value(item: object, label: str) -> complex:
        if not isinstance(item, Mapping) or set(item) != {"real", "imaginary"}:
            raise ValueError(f"persisted promoted {label} is invalid")
        try:
            parsed = complex(float(item["real"]), float(item["imaginary"]))
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError(f"persisted promoted {label} is invalid") from error
        if not math.isfinite(parsed.real) or not math.isfinite(parsed.imag):
            raise ValueError(f"persisted promoted {label} is invalid")
        return parsed

    determinant = value["determinant"]
    if not isinstance(determinant, Mapping) or set(determinant) != {
        "real",
        "imaginary",
    }:
        raise ValueError("persisted promoted determinant is invalid")
    try:
        decimal_determinant = DecimalComplex(
            Decimal(str(determinant["real"])),
            Decimal(str(determinant["imaginary"])),
        )
    except Exception as error:
        raise ValueError("persisted promoted determinant is invalid") from error
    raw_error = value["determinant_error_evidence"]
    return JuliaFixedRootSurveySample(
        sample_index=int(value["sample_index"]),
        sample_role=str(value["sample_role"]),
        omega=complex_value(value["omega"], "sample frequency"),
        amplitude=complex_value(value["amplitude"], "sample amplitude"),
        determinant=decimal_determinant,
        numerical_conditioning=FixedRootSurveyConditioning(
            value["numerical_conditioning"]
        ),
        execution_identity=value["execution_identity"],
        determinant_error_evidence=(
            None
            if raw_error is None
            else ExteriorDeterminantErrorEvidence(raw_error)
        ),
    )


def _promoted_batch_from_mapping(value: object) -> object:
    fields = {
        "schema",
        "operation",
        "identity",
        "plan",
        "execution_identity",
        "scientific_operation_identity",
        "leaf_id",
        "job_id",
        "mechanism_id",
        "root_reference_id",
        "root_seal_sha256",
        "branch_identity",
        "fixed_root",
        "frequency_step",
        "coordinate_step",
        "request_sha256",
        "precision_tier",
        "working_precision_bits",
        "sample_roles",
        "sample_count",
        "maximum_sample_count",
        "julia_launch_count",
        "root_read_count",
        "samples",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError("persisted promoted batch fields are invalid")

    from .julia_response_backend import (
        FIXED_ROOT_SURVEY_BATCH_RESPONSE_SCHEMA,
        FixedRootSurveyPlan,
        JuliaFixedRootSurveyBatch,
    )
    from .precision_tiers import PrecisionTier

    if value.get("schema") != FIXED_ROOT_SURVEY_BATCH_RESPONSE_SCHEMA:
        raise ValueError("persisted promoted batch schema is invalid")

    def complex_value(item: object, label: str) -> complex:
        if not isinstance(item, Mapping) or set(item) != {"real", "imaginary"}:
            raise ValueError(f"persisted promoted batch {label} is invalid")
        try:
            parsed = complex(float(item["real"]), float(item["imaginary"]))
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError(
                f"persisted promoted batch {label} is invalid"
            ) from error
        if not math.isfinite(parsed.real) or not math.isfinite(parsed.imag):
            raise ValueError(f"persisted promoted batch {label} is invalid")
        return parsed

    def integer(name: str, *, minimum: int) -> int:
        candidate = value[name]
        if (
            isinstance(candidate, bool)
            or not isinstance(candidate, int)
            or candidate < minimum
        ):
            raise ValueError(f"persisted promoted batch {name} is invalid")
        return candidate

    try:
        frequency_step = Decimal(str(value["frequency_step"]))
        coordinate_step = Decimal(str(value["coordinate_step"]))
    except Exception as error:
        raise ValueError("persisted promoted batch steps are invalid") from error
    if (
        not frequency_step.is_finite()
        or not coordinate_step.is_finite()
        or frequency_step <= 0
        or coordinate_step < 0
    ):
        raise ValueError("persisted promoted batch steps are invalid")
    raw_samples = value["samples"]
    raw_roles = value["sample_roles"]
    if not isinstance(raw_samples, list) or not isinstance(raw_roles, list):
        raise ValueError("persisted promoted batch samples are invalid")
    samples = tuple(_promoted_sample_from_mapping(item) for item in raw_samples)
    roles = tuple(str(getattr(item, "role")) for item in samples)
    if (
        tuple(raw_roles) != roles
        or integer("sample_count", minimum=0) != len(samples)
        or integer("maximum_sample_count", minimum=len(samples)) < len(samples)
    ):
        raise ValueError("persisted promoted batch sample plan is invalid")
    try:
        precision_tier = PrecisionTier(str(value["precision_tier"]))
    except ValueError as error:
        raise ValueError("persisted promoted batch precision is invalid") from error
    required_strings = (
        "operation",
        "identity",
        "scientific_operation_identity",
        "leaf_id",
        "job_id",
        "mechanism_id",
        "root_reference_id",
        "root_seal_sha256",
        "branch_identity",
        "request_sha256",
    )
    if any(
        not isinstance(value[name], str) or not value[name]
        for name in required_strings
    ):
        raise ValueError("persisted promoted batch identity is invalid")
    root_seal_sha256 = str(value["root_seal_sha256"])
    try:
        if len(root_seal_sha256) != 64:
            raise ValueError
        int(root_seal_sha256, 16)
    except ValueError as error:
        raise ValueError("persisted promoted batch root seal is invalid") from error
    return JuliaFixedRootSurveyBatch(
        leaf_id=str(value["leaf_id"]),
        job_id=str(value["job_id"]),
        mechanism_id=str(value["mechanism_id"]),
        root_reference_id=str(value["root_reference_id"]),
        root_seal_sha256=root_seal_sha256,
        branch_identity=str(value["branch_identity"]),
        fixed_root=complex_value(value["fixed_root"], "fixed root"),
        frequency_step=frequency_step,
        coordinate_step=coordinate_step,
        scientific_operation_identity=str(value["scientific_operation_identity"]),
        plan=FixedRootSurveyPlan(str(value["plan"])),
        execution_identity=value["execution_identity"],
        request_sha256=str(value["request_sha256"]),
        precision_tier=precision_tier,
        working_precision_bits=integer("working_precision_bits", minimum=2),
        samples=samples,
        maximum_sample_count=integer(
            "maximum_sample_count", minimum=len(samples)
        ),
        operation=str(value["operation"]),
        identity=str(value["identity"]),
        julia_launch_count=integer("julia_launch_count", minimum=0),
        root_read_count=integer("root_read_count", minimum=0),
    )


def _validated_background_receipt(value: object) -> tuple[object, dict[str, object]]:
    fields = {
        "schema",
        "cache_key_sha256",
        "reuse_key",
        "source_queue_ordinal",
        "source_leaf_id",
        "background_worker_request_sha256",
        "background_worker_batch",
        "background_sha256",
        "receipt_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError("persisted background receipt fields are invalid")
    content = {name: item for name, item in value.items() if name != "receipt_sha256"}
    if (
        value.get("schema") != _PROMOTED_CANONICAL_BACKGROUND_RECEIPT_SCHEMA
        or value.get("receipt_sha256") != canonical_sha256(content)
    ):
        raise ValueError("persisted background receipt digest is invalid")

    from .promoted_artifacts import PromotedCanonicalBackgroundReceipt

    batch = _promoted_batch_from_mapping(value["background_worker_batch"])
    receipt = PromotedCanonicalBackgroundReceipt(
        batch=batch,
        cache_key_sha256=str(value["cache_key_sha256"]),
        reuse_key=value["reuse_key"],
        source_queue_ordinal=value["source_queue_ordinal"],
        source_leaf_id=str(value["source_leaf_id"]),
    )
    canonical = receipt.to_mapping()
    if canonical != dict(value):
        raise ValueError("persisted background receipt is not canonical")
    return receipt, canonical


def _derive_control_work_accounting(
    control_return: Mapping[str, object],
    receipt: ValidatedControlReceipt,
    *,
    queue_ordinal: int | None,
    leaf_id: str,
) -> ControlWorkAccounting:
    partial = control_return.get("partial_work")
    if partial is None:
        return ControlWorkAccounting(
            evidence_receipts=(),
            attempt_records=(),
            sample_count=0,
            root_read_count=(
                1 if receipt.identity.operation == ROOT_READOUT_OPERATION else 0
            ),
            worker_launch_count=1,
        )
    if queue_ordinal is None:
        raise ValueError("persisted CONTROL partial work lacks queue authority")
    if (
        not isinstance(partial, Mapping)
        or set(partial) != {"schema", "evidence_receipts", "attempt_records"}
        or partial.get("schema") != _PROMOTED_PARTIAL_WORK_SCHEMA
        or not isinstance(partial.get("evidence_receipts"), list)
        or not isinstance(partial.get("attempt_records"), list)
    ):
        raise ValueError("persisted CONTROL partial work is invalid")

    from .promoted_root_authority import (
        PROMOTED_ROOT_RECEIPT_SCHEMA,
        validate_promoted_root_receipt,
    )

    sample_count = root_count = launch_count = 0
    receipts: list[dict[str, object]] = []
    attempts: list[dict[str, object]] = []
    seen_receipts: set[tuple[str, str]] = set()
    for candidate in partial["evidence_receipts"]:
        if not isinstance(candidate, Mapping):
            raise ValueError("persisted CONTROL evidence receipt is invalid")
        schema = candidate.get("schema")
        digest = candidate.get("receipt_sha256")
        if not isinstance(schema, str) or not isinstance(digest, str):
            raise ValueError("persisted CONTROL evidence receipt is invalid")
        key = (schema, digest)
        if key in seen_receipts:
            raise ValueError("persisted CONTROL evidence receipt is duplicated")
        seen_receipts.add(key)
        if schema == _PROMOTED_CANONICAL_BACKGROUND_RECEIPT_SCHEMA:
            parsed, canonical = _validated_background_receipt(candidate)
            if (
                getattr(parsed, "source_queue_ordinal") == queue_ordinal
                and getattr(parsed, "source_leaf_id") == leaf_id
            ):
                batch = getattr(parsed, "batch")
                if (
                    batch.sample_count != 5
                    or batch.julia_launch_count != 1
                    or batch.root_read_count != 0
                ):
                    raise ValueError("persisted CONTROL background budget is invalid")
                sample_count += 5
                launch_count += 1
            receipts.append(canonical)
        elif schema == PROMOTED_ROOT_RECEIPT_SCHEMA:
            canonical, _authority = validate_promoted_root_receipt(
                candidate,
                queue_ordinal=queue_ordinal,
                leaf_id=leaf_id,
            )
            root_count += 1
            launch_count += 1
            receipts.append(canonical)
        elif schema == _EXTERIOR_PROVISIONAL_REUSE_RECEIPT_SCHEMA:
            fields = {
                "schema", "status", "leaf_id", "provisional_stage_sha256",
                "root_seal_sha256", "target_precision_tier", "decision",
                "receipt_sha256",
            }
            content = {
                name: item for name, item in candidate.items()
                if name != "receipt_sha256"
            }
            if (
                set(candidate) != fields
                or digest != canonical_sha256(content)
                or candidate.get("status") != "COMPATIBLE"
                or candidate.get("leaf_id") != leaf_id
                or candidate.get("target_precision_tier") != "BF40"
                or candidate.get("decision")
                != "AUTHENTICATED_BINARY64_PREDECESSOR_CONSUMED"
            ):
                raise ValueError("persisted CONTROL reuse receipt is invalid")
            receipts.append(copy.deepcopy(dict(candidate)))
        else:
            raise ValueError("persisted CONTROL evidence receipt is unsupported")

    seen_attempts: set[str] = set()
    for candidate in partial["attempt_records"]:
        canonical, validated = _validated_attempt_record(
            candidate,
            queue_ordinal=queue_ordinal,
            leaf_id=leaf_id,
        )
        digest = str(canonical["attempt_sha256"])
        if digest in seen_attempts:
            raise ValueError("persisted CONTROL attempt is duplicated")
        seen_attempts.add(digest)
        launch_count += 1
        if validated.identity.operation == ROOT_READOUT_OPERATION:
            root_count += 1
        attempts.append(canonical)
    if not attempts or attempts[-1]["control_receipt_sha256"] != receipt.sha256:
        raise ValueError("persisted CONTROL current attempt is absent")
    return ControlWorkAccounting(
        evidence_receipts=tuple(receipts),
        attempt_records=tuple(attempts),
        sample_count=sample_count,
        root_read_count=root_count,
        worker_launch_count=launch_count,
    )


@dataclass(frozen=True, slots=True)
class ControlClassificationMaterial:
    """Registry-derived material shared by persistence and runtime policy."""

    receipt: ValidatedControlReceipt
    transition: PromotedControlTransition
    effective_policy_identity: str
    fingerprint_material: Mapping[str, object]
    fingerprint_sha256: str

    def __post_init__(self) -> None:
        snapshot = copy.deepcopy(dict(self.fingerprint_material))
        object.__setattr__(
            self,
            "fingerprint_material",
            MappingProxyType(snapshot),
        )

    def decision_content(
        self,
        *,
        schema: str,
        control_return_sha256: str,
        current_tier: str,
        current_action_kind: str,
    ) -> dict[str, object]:
        """Return the canonical decision projection for one retained return."""

        if (
            current_tier != self.transition.current_tier
            or current_action_kind != self.transition.current_action_kind
        ):
            raise ValueError(
                "persisted CONTROL decision action contradicts its transition"
            )

        return {
            "schema": schema,
            "control_return_sha256": control_return_sha256,
            "control_receipt_sha256": self.receipt.sha256,
            "failure_code": self.receipt.failure_code,
            "failure_fingerprint_sha256": self.fingerprint_sha256,
            "fingerprint_material": copy.deepcopy(
                dict(self.fingerprint_material)
            ),
            "transition_id": self.transition.transition_id,
            "transition": self.transition.to_mapping(),
            "disposition": self.transition.disposition,
            "queue_kind": self.transition.queue_kind,
            "current_tier": current_tier,
            "current_action_kind": current_action_kind,
            "next_tier": self.transition.next_tier,
            "next_action_kind": self.transition.next_action_kind,
        }


@dataclass(frozen=True, slots=True)
class PersistedControlReturnAuthority:
    """Authenticated producer return with no campaign disposition."""

    control_return_sha256: str
    receipt: ValidatedControlReceipt
    effective_policy_identity: str
    current_tier: str
    current_action_kind: str
    work_accounting: ControlWorkAccounting


@dataclass(frozen=True, slots=True)
class PersistedControlDecisionAuthority:
    """Authenticated return plus its immutable campaign transition."""

    return_authority: PersistedControlReturnAuthority
    classification: ControlClassificationMaterial

    @property
    def control_return_sha256(self) -> str:
        return self.return_authority.control_return_sha256

    @property
    def receipt(self) -> ValidatedControlReceipt:
        return self.return_authority.receipt

    @property
    def current_tier(self) -> str:
        return self.return_authority.current_tier

    @property
    def current_action_kind(self) -> str:
        return self.return_authority.current_action_kind

    @property
    def work_accounting(self) -> ControlWorkAccounting:
        return self.return_authority.work_accounting

    @property
    def transition(self) -> PromotedControlTransition:
        return self.classification.transition

    def normalized_decision(
        self,
        *,
        schema: str,
        current_tier: str,
        current_action_kind: str,
    ) -> dict[str, object]:
        content = self.classification.decision_content(
            schema=schema,
            control_return_sha256=self.control_return_sha256,
            current_tier=current_tier,
            current_action_kind=current_action_kind,
        )
        return {
            **content,
            "control_decision_sha256": canonical_sha256(content),
        }


def classify_control_receipt_material(
    receipt: ValidatedControlReceipt,
    *,
    current_tier: str,
    current_action_kind: str,
) -> ControlClassificationMaterial:
    """Authenticate and resolve one live producer receipt exactly once."""

    canonical_request = receipt.canonical_request
    if canonical_request is None:
        raise ValueError(
            "promoted CONTROL classification requires its canonical request"
        )
    from .julia_response_backend import (  # local by dependency design
        validate_persisted_operation_control_receipt,
    )

    receipt = validate_persisted_operation_control_receipt(
        receipt.to_mapping(),
        canonical_request,
    )
    transition = promoted_control_transition(
        receipt,
        current_tier=current_tier,
        current_action_kind=current_action_kind,
    )
    if not transition.persist_return or not transition.persist_decision:
        raise ValueError(
            "promoted CONTROL registry does not authorize the mandatory "
            "return-and-decision checkpoint chain"
        )
    return _classification_material_from_transition(receipt, transition)


def _classification_material_from_transition(
    receipt: ValidatedControlReceipt,
    transition: PromotedControlTransition,
) -> ControlClassificationMaterial:
    """Project immutable decision material from authenticated authorities."""

    identity = receipt.identity
    effective_policy_identity = _effective_policy_sha256(receipt)
    fingerprint_material: dict[str, object] = {
        "failure_code": receipt.failure_code,
        "failure_class": "CONTROL",
        "stage": receipt.stage,
        "worker_operation": identity.operation,
        "control_profile": transition.control_profile,
        "request_schema": str(identity.mapping["request_schema"]),
        "backend_identity": str(identity.mapping["backend_identity_sha256"]),
        "policy_identity": effective_policy_identity,
        "precision_tier": transition.current_tier,
        "cause_type": transition.exception_type,
        "request_sha256": identity.request_sha256,
        "control_receipt_sha256": receipt.sha256,
        "execution_identity_sha256": identity.sha256,
        "effective_policy_identity": effective_policy_identity,
        "transition_id": transition.transition_id,
        "outcome_kind": transition.outcome_kind.value,
    }
    return ControlClassificationMaterial(
        receipt=receipt,
        transition=transition,
        effective_policy_identity=effective_policy_identity,
        fingerprint_material=fingerprint_material,
        fingerprint_sha256=canonical_sha256(fingerprint_material),
    )


def resolve_persisted_control_return(
    authority: PersistedControlReturnAuthority,
) -> PersistedControlDecisionAuthority:
    """Perform the first and only campaign classification of a raw return."""

    transition = promoted_control_transition(
        authority.receipt,
        current_tier=authority.current_tier,
        current_action_kind=authority.current_action_kind,
    )
    if not transition.persist_return or not transition.persist_decision:
        raise ValueError(
            "promoted CONTROL registry does not authorize the mandatory "
            "return-and-decision checkpoint chain"
        )
    classification = _classification_material_from_transition(
        authority.receipt,
        transition,
    )
    return PersistedControlDecisionAuthority(
        return_authority=authority,
        classification=classification,
    )


def authenticate_persisted_control_return(
    control_return: Mapping[str, object],
    *,
    expected_schema: str,
    expected_leaf_id: str,
    expected_current_action_kind: str,
    expected_queue_ordinal: int | None = None,
) -> PersistedControlReturnAuthority:
    """Authenticate one checkpointed producer return without classifying it."""

    required_fields = {
        "schema",
        "operation",
        "request_schema",
        "request_sha256",
        "execution_identity_sha256",
        "effective_policy_identity",
        "current_tier",
        "current_action_kind",
        "canonical_request",
        "control_receipt",
        "control_receipt_sha256",
        "control_return_sha256",
    }
    if (
        not isinstance(control_return, Mapping)
        or control_return.get("schema") != expected_schema
        or not required_fields.issubset(control_return)
        or not isinstance(control_return.get("canonical_request"), Mapping)
        or not isinstance(control_return.get("control_receipt"), Mapping)
    ):
        raise ValueError("persisted CONTROL return fields are invalid")
    current_tier = control_return.get("current_tier")
    current_action_kind = control_return.get("current_action_kind")
    if (
        current_tier not in {"BF40", "BF80"}
        or current_action_kind != expected_current_action_kind
    ):
        raise ValueError("persisted CONTROL return action identity is invalid")
    return_sha256 = _authenticated_artifact_digest(
        control_return,
        "control_return_sha256",
    )

    # The adapter validator re-derives the request identity and applies the
    # code-specific numerical/resource/timeout diagnostic contract.
    from .julia_response_backend import (  # local by dependency design
        validate_persisted_operation_control_receipt,
    )

    receipt = validate_persisted_operation_control_receipt(
        control_return["control_receipt"],  # type: ignore[arg-type]
        control_return["canonical_request"],  # type: ignore[arg-type]
    )
    identity = receipt.identity
    effective_policy_identity = _effective_policy_sha256(receipt)
    expected_semantic_tier = f"bigfloat-{str(current_tier)[2:]}"
    if (
        identity.mapping.get("leaf_id") != expected_leaf_id
        or identity.mapping.get("semantic_precision_tier")
        != expected_semantic_tier
        or control_return.get("operation") != identity.operation
        or control_return.get("request_schema")
        != identity.mapping["request_schema"]
        or control_return.get("request_sha256") != identity.request_sha256
        or control_return.get("execution_identity_sha256") != identity.sha256
        or control_return.get("effective_policy_identity")
        != effective_policy_identity
        or control_return.get("control_receipt_sha256") != receipt.sha256
    ):
        raise ValueError("persisted CONTROL return identity is invalid")
    return PersistedControlReturnAuthority(
        control_return_sha256=return_sha256,
        receipt=receipt,
        effective_policy_identity=effective_policy_identity,
        current_tier=str(current_tier),
        current_action_kind=str(current_action_kind),
        work_accounting=_derive_control_work_accounting(
            control_return,
            receipt,
            queue_ordinal=expected_queue_ordinal,
            leaf_id=expected_leaf_id,
        ),
    )


def authenticate_persisted_control_decision(
    control_return: Mapping[str, object],
    control_decision: Mapping[str, object],
    *,
    expected_return_schema: str,
    expected_decision_schema: str,
    expected_leaf_id: str,
    expected_current_action_kind: str,
    expected_queue_ordinal: int | None = None,
) -> PersistedControlDecisionAuthority:
    """Authenticate a retained immutable decision without reclassification."""

    return_authority = authenticate_persisted_control_return(
        control_return,
        expected_schema=expected_return_schema,
        expected_leaf_id=expected_leaf_id,
        expected_current_action_kind=expected_current_action_kind,
        expected_queue_ordinal=expected_queue_ordinal,
    )
    if (
        not isinstance(control_decision, Mapping)
        or set(control_decision) != _CONTROL_DECISION_FIELDS
        or control_decision.get("schema") != expected_decision_schema
    ):
        raise ValueError("persisted CONTROL decision fields are invalid")
    _authenticated_artifact_digest(
        control_decision,
        "control_decision_sha256",
    )
    transition = authenticate_promoted_control_transition(
        control_decision.get("transition"),
        transition_id=control_decision.get("transition_id"),
    )
    receipt = return_authority.receipt
    identity = receipt.identity
    control_profile = (
        str(identity.mapping["control_profile"])
        if "control_profile" in identity.mapping
        else None
    )
    if (
        transition.origin != receipt.origin
        or transition.operation != identity.operation
        or transition.control_profile != control_profile
        or transition.failure_code != receipt.failure_code
        or transition.stage != receipt.stage
        or transition.scope != identity.scope
        or transition.current_tier != return_authority.current_tier
        or transition.current_action_kind
        != return_authority.current_action_kind
    ):
        raise ValueError(
            "persisted CONTROL decision is not bound to its producer return"
        )
    authority = PersistedControlDecisionAuthority(
        return_authority=return_authority,
        classification=_classification_material_from_transition(
            receipt,
            transition,
        ),
    )
    expected = authority.normalized_decision(
        schema=expected_decision_schema,
        current_tier=return_authority.current_tier,
        current_action_kind=return_authority.current_action_kind,
    )
    if dict(control_decision) != expected:
        raise ValueError(
            "persisted CONTROL decision does not match registry authority"
        )
    return authority


def validate_persisted_control_stage_accounting(
    stage: Mapping[str, object],
    authority: (
        PersistedControlReturnAuthority | PersistedControlDecisionAuthority
    ),
) -> None:
    """Require stage/reporting counters to equal authenticated raw evidence."""

    accounting = authority.work_accounting
    receipts = stage.get("receipts")
    counts = {
        "sample_count": accounting.sample_count,
        "root_read_count": accounting.root_read_count,
        "worker_launch_count": accounting.worker_launch_count,
    }
    limits = {
        "sample_limit": (counts["sample_count"], 18),
        "root_read_limit": (counts["root_read_count"], 2),
        "worker_launch_limit": (counts["worker_launch_count"], 5),
    }
    tiers = stage.get("precision_tiers")
    current_tier = authority.current_tier
    if (
        not isinstance(receipts, list)
        or not all(isinstance(item, Mapping) for item in receipts)
        or receipts != accounting.receipts()
        or any(stage.get(name) != expected for name, expected in counts.items())
        or not isinstance(tiers, list)
        or not tiers
        or any(tier not in {"BF40", "BF80"} for tier in tiers)
        or tiers[-1] != current_tier
    ):
        raise ValueError("persisted CONTROL stage accounting is invalid")
    for name, (count, ceiling) in limits.items():
        value = stage.get(name)
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < count
            or value > ceiling
        ):
            raise ValueError("persisted CONTROL stage limit is invalid")


__all__ = [
    "ControlClassificationMaterial",
    "ControlWorkAccounting",
    "PersistedControlDecisionAuthority",
    "PersistedControlReturnAuthority",
    "authenticate_persisted_control_decision",
    "authenticate_persisted_control_return",
    "classify_control_receipt_material",
    "resolve_persisted_control_return",
    "validate_persisted_control_stage_accounting",
]
