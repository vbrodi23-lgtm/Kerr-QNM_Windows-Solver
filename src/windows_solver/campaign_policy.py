"""Schema-11 campaign state contracts.

Numerical records are immutable.  Evidence, pass progress, promotions, attempts,
and system failures live in separate ledgers so an operational update cannot
change a retained numerical centre or its digest.
"""

from __future__ import annotations

import copy
import hashlib
from enum import Enum
from typing import Mapping, Sequence

from .contracts import canonical_json_bytes
from .evidence_authentication import certified_disposition_is_admitted
from .validation_admission import validated_disposition_is_admitted
from .campaign_timing import TimingFragment, fold_timing_fragments
from .promoted_control_authority import (
    authenticate_persisted_control_decision,
    authenticate_persisted_control_return,
    validate_persisted_control_stage_accounting,
)


CAMPAIGN_CHECKPOINT_SCHEMA_VERSION = 11
PROMOTION_QUEUE_SCHEMA = "windows-solver.m02-promotion-queue/1"
PROMOTED_CALCULATION_STAGE_SCHEMA = (
    "windows-solver.promoted-calculation-stage/2"
)
PROMOTED_CONTROL_RETURN_STAGE_SCHEMA = (
    "windows-solver.promoted-control-return-stage/1"
)
PROMOTED_CONTROL_DECISION_STAGE_SCHEMA = (
    "windows-solver.promoted-control-decision-stage/1"
)
PROMOTED_CONTROL_CONTINUATION_STAGE_SCHEMA = (
    "windows-solver.promoted-control-continuation-stage/1"
)
PROMOTED_CONTROL_RETURN_SCHEMA = (
    "windows-solver.promoted-exterior-control-return/4"
)
PROMOTED_CONTROL_DECISION_SCHEMA = (
    "windows-solver.promoted-exterior-control-decision/3"
)
PROMOTED_HORIZON_CONTROL_RETURN_SCHEMA = (
    "windows-solver.promoted-horizon-control-return/2"
)
PROMOTED_HORIZON_CONTROL_DECISION_SCHEMA = (
    "windows-solver.promoted-horizon-control-decision/2"
)
PROMOTED_CONTROL_CONTINUATION_PROOF_SCHEMA = (
    "windows-solver.promoted-control-continuation-proof/2"
)
PROMOTED_CONTROL_TERMINAL_RECEIPT_SCHEMA = (
    "windows-solver.promoted-control-terminal-disposition/3"
)
PROMOTED_POLICY_TERMINAL_STAGE_SCHEMA = (
    "windows-solver.promoted-policy-terminal-stage/1"
)
PROMOTED_POLICY_TERMINAL_DECISION_SCHEMA = (
    "windows-solver.promoted-policy-terminal-decision/1"
)
PROMOTED_POLICY_TERMINAL_RECEIPT_SCHEMA = (
    "windows-solver.promoted-policy-terminal-disposition/1"
)

_PROMOTED_CONTROL_DECISION_RETURN_SCHEMAS = {
    PROMOTED_CONTROL_DECISION_SCHEMA: PROMOTED_CONTROL_RETURN_SCHEMA,
    PROMOTED_HORIZON_CONTROL_DECISION_SCHEMA: (
        PROMOTED_HORIZON_CONTROL_RETURN_SCHEMA
    ),
}
_PROMOTED_CONTROL_RETURN_SCHEMAS = frozenset(
    _PROMOTED_CONTROL_DECISION_RETURN_SCHEMAS.values()
)
_PROMOTED_CONTROL_DECISION_SCHEMAS = frozenset(
    _PROMOTED_CONTROL_DECISION_RETURN_SCHEMAS
)
_PROMOTED_ARTIFACT_DIGEST_FIELDS = {
    "windows-solver.promoted-exterior-calculation/4": "calculation_sha256",
    "windows-solver.promoted-horizon-calculation/3": "calculation_sha256",
    PROMOTED_CONTROL_RETURN_SCHEMA: "control_return_sha256",
    PROMOTED_CONTROL_DECISION_SCHEMA: "control_decision_sha256",
    PROMOTED_HORIZON_CONTROL_RETURN_SCHEMA: "control_return_sha256",
    PROMOTED_HORIZON_CONTROL_DECISION_SCHEMA: "control_decision_sha256",
}


def _control_outcome_kind(value: object) -> str | None:
    """Read the canonical outcome enum without interpreting compatibility flags."""

    transition = value.get("transition") if isinstance(value, Mapping) else None
    outcome = transition.get("outcome") if isinstance(transition, Mapping) else None
    kind = outcome.get("kind") if isinstance(outcome, Mapping) else None
    return kind if isinstance(kind, str) else None


class ExecutionProfile(str, Enum):
    SURVEY = "SURVEY"
    CERTIFY = "CERTIFY"
    VALIDATE = "VALIDATE"


class SurveyPass(str, Enum):
    BINARY64 = "binary64"
    PROMOTED = "promoted"


class SurveyDisposition(str, Enum):
    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    CACHE_REUSED = "CACHE_REUSED"
    COMPLETED = "COMPLETED"
    PROMOTION_PENDING_ROOT = "PROMOTION_PENDING_ROOT"
    PROMOTION_PENDING_RESPONSE = "PROMOTION_PENDING_RESPONSE"
    UNRESOLVED = "UNRESOLVED"
    DEFERRED = "DEFERRED"
    REJECTED = "REJECTED"
    CALCULATED_AWAITING_ADMISSION = "CALCULATED_AWAITING_ADMISSION"
    SUPERSEDED_BY_CACHE = "SUPERSEDED_BY_CACHE"


class EvidenceLevel(str, Enum):
    SCREENED = "SCREENED"
    CERTIFIED = "CERTIFIED"
    VALIDATED = "VALIDATED"


class PromotionQueueKind(str, Enum):
    ROOT = "ROOT"
    RESPONSE = "RESPONSE"


class PromotionQueueDisposition(str, Enum):
    PENDING = "PENDING"
    CALCULATED_PENDING_DERIVATION = "CALCULATED_PENDING_DERIVATION"
    CONTROL_RETURN_RETAINED = "CONTROL_RETURN_RETAINED"
    CONTROL_DECISION_RETAINED = "CONTROL_DECISION_RETAINED"
    NUMERICAL_CONTINUATION = "NUMERICAL_CONTINUATION"
    AWAITING_ADMISSION = "AWAITING_ADMISSION"
    ADMITTED_PENDING_PUBLICATION = "ADMITTED_PENDING_PUBLICATION"
    COMPLETED = "COMPLETED"
    UNRESOLVED = "UNRESOLVED"
    DEFERRED = "DEFERRED"
    REJECTED = "REJECTED"
    SUPERSEDED_BY_CACHE = "SUPERSEDED_BY_CACHE"


NUMERICAL_RECORD_STATES = frozenset(
    {"IN_PROGRESS", "PRODUCED", "UNRESOLVED", "REJECTED"}
)
BINARY64_SURVEY_DISPOSITIONS = frozenset(item.value for item in SurveyDisposition)
PROMOTED_SURVEY_DISPOSITIONS = BINARY64_SURVEY_DISPOSITIONS - {
    SurveyDisposition.PROMOTION_PENDING_ROOT.value,
    SurveyDisposition.PROMOTION_PENDING_RESPONSE.value,
}
TERMINAL_PROMOTION_DISPOSITIONS = frozenset(
    item.value
    for item in PromotionQueueDisposition
    if item
    not in {
        PromotionQueueDisposition.PENDING,
        PromotionQueueDisposition.CALCULATED_PENDING_DERIVATION,
        PromotionQueueDisposition.CONTROL_RETURN_RETAINED,
        PromotionQueueDisposition.CONTROL_DECISION_RETAINED,
        PromotionQueueDisposition.NUMERICAL_CONTINUATION,
        PromotionQueueDisposition.AWAITING_ADMISSION,
        PromotionQueueDisposition.ADMITTED_PENDING_PUBLICATION,
    }
)

_EVIDENCE_RANK = {
    EvidenceLevel.SCREENED.value: 1,
    EvidenceLevel.CERTIFIED.value: 2,
    EvidenceLevel.VALIDATED.value: 3,
}
_SCHEMA11_BASE_FIELDS = {
    "schema_version",
    "campaign_id",
    "selection_id",
    "state",
    "records",
    "evidence_ledger",
    "survey_pass_ledger",
    "promotion_queue",
    "attempts",
    "system_failures",
    "recovery_receipts",
    "report_status_receipt",
}
_SCHEMA11_LAYER2_LEDGER_FIELDS = {
    "promoted_stage_ledger",
    "promoted_background_ledger",
    "promoted_root_ledger",
}
_SCHEMA11_PRE_PR75_FIELDS = _SCHEMA11_BASE_FIELDS | _SCHEMA11_LAYER2_LEDGER_FIELDS
_SCHEMA11_FORENSIC_FIELDS = {"forensic_fixed_root_v2_history"}
_SCHEMA11_FIELDS = _SCHEMA11_PRE_PR75_FIELDS | _SCHEMA11_FORENSIC_FIELDS
_PASS_ENTRY_FIELDS = {
    "leaf_id",
    "pass",
    "source_record_sha256",
    "result_record_sha256",
    "operation_identity",
    "precision_tiers",
    "reason_code",
    "sample_count",
    "sample_limit",
    "root_read_count",
    "root_read_limit",
    "worker_launch_count",
    "worker_launch_limit",
    "tier_timing",
    "session_fragments",
    "disposition",
    "disposition_receipt_sha256",
}
_PROMOTION_ENTRY_FIELDS = {
    "leaf_id",
    "queue_kind",
    "source_pass",
    "reason_code",
    "minimum_requested_tier",
    "source_record_sha256",
    "source_stage_sha256",
    "source_root_seal_sha256",
    "scientific_computation_identity",
    "queue_ordinal",
    "disposition",
    "disposition_receipt_sha256",
}
_PROMOTION_ENTRY_PRE_FINGERPRINT_FIELDS = _PROMOTION_ENTRY_FIELDS | {
    "provisional_stage",
    "provisional_stage_sha256",
    "provisional_operation_identity",
    "source_binary64_disposition_receipt_sha256",
    "provisional_reuse_receipt",
    "provisional_reuse_receipt_sha256",
}
_PROMOTION_SOURCE_FINGERPRINT_FIELDS = (
    "leaf_id",
    "queue_kind",
    "source_pass",
    "reason_code",
    "minimum_requested_tier",
    "source_record_sha256",
    "source_stage_sha256",
    "source_root_seal_sha256",
    "scientific_computation_identity",
    "provisional_stage",
    "provisional_stage_sha256",
    "provisional_operation_identity",
    "source_binary64_disposition_receipt_sha256",
    "queue_ordinal",
)
_PROMOTION_ENTRY_PROVISIONAL_FIELDS = (
    _PROMOTION_ENTRY_PRE_FINGERPRINT_FIELDS | {"source_fingerprint_sha256"}
)
_PROMOTION_ENTRY_LAYER2_FIELDS = _PROMOTION_ENTRY_PROVISIONAL_FIELDS | {
    "retained_promoted_stage_sha256",
}
_PROMOTED_EXECUTION_MODES = frozenset(
    {"CALCULATE_AND_ADMIT", "CALCULATE_ONLY", "BLOCK_ALL"}
)


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


def promoted_artifact_digest(
    artifact: Mapping[str, object],
) -> tuple[str, str]:
    """Authenticate one explicitly registered promoted artifact.

    Schema discrimination is deliberately exhaustive.  A misspelled, future,
    or corrupted CONTROL schema cannot fall through to calculation handling.
    """

    if not isinstance(artifact, Mapping):
        raise ValueError("retained promoted artifact is invalid")
    schema = artifact.get("schema")
    try:
        digest_field = _PROMOTED_ARTIFACT_DIGEST_FIELDS[str(schema)]
    except KeyError as error:
        raise ValueError("retained promoted artifact schema is unsupported") from error
    supplied = artifact.get(digest_field)
    content = {key: item for key, item in artifact.items() if key != digest_field}
    if not _is_sha256(supplied) or supplied != _sha256(content):
        raise ValueError("retained promoted artifact digest is invalid")
    return digest_field, str(supplied)


def promotion_source_fingerprint_sha256(entry: Mapping[str, object]) -> str:
    """Hash the exact immutable Layer-1 source portion of one queue entry."""

    if not isinstance(entry, Mapping):
        raise ValueError("promotion source entry is invalid")
    if set(_PROMOTION_SOURCE_FINGERPRINT_FIELDS) - set(entry):
        raise ValueError("promotion source entry is incomplete")
    return _sha256({field: entry[field] for field in _PROMOTION_SOURCE_FINGERPRINT_FIELDS})


def _assert_layer1_guard(layer1_guard: object | None, checkpoint: Mapping[str, object]) -> None:
    if layer1_guard is None:
        return
    assertion = getattr(layer1_guard, "assert_unchanged", None)
    if not callable(assertion):
        raise ValueError("Layer-1 guard is invalid")
    assertion(checkpoint)


def _expected_promoted_control_action(
    stage: Mapping[str, object],
    control_return: Mapping[str, object],
    queue_entry: Mapping[str, object],
) -> str:
    """Derive the active action from the concrete operation and route.

    A ROOT queue performs its primary readout and then may execute a fixed-root
    RESPONSE batch.  Consequently the original queue kind is not itself the
    current action.  The concrete operation is decisive; the route only
    disambiguates the root-readout operation embedded in a horizon response.
    """

    operation = control_return.get("operation")
    if operation in {
        "fixed-root-survey-batch",
        "fixed-root-determinant-sample",
    }:
        return PromotionQueueKind.RESPONSE.value
    if operation == "root-readout":
        if stage.get("route") == "HORIZON_BF80":
            return PromotionQueueKind.RESPONSE.value
        if queue_entry.get("queue_kind") == PromotionQueueKind.ROOT.value:
            return PromotionQueueKind.ROOT.value
    raise ValueError("promoted CONTROL stage action cannot be derived")


def promoted_control_terminal_disposition_receipt(
    queue_entry: Mapping[str, object],
    decision_stage: Mapping[str, object],
) -> dict[str, object]:
    """Project the only terminal receipt authorised by a CONTROL decision.

    The queue stores the receipt digest while the decision stage retains all
    receipt inputs.  Keeping this projection exact makes the terminal receipt
    independently recomputable at every checkpoint load instead of trusting
    caller-authored descriptive fields.
    """

    if not isinstance(queue_entry, Mapping) or not isinstance(
        decision_stage, Mapping
    ):
        raise ValueError("CONTROL terminal proof is invalid")
    decision = decision_stage.get("control_decision")
    chain = decision_stage.get("calculation_chain")
    return_stage = chain[-1] if isinstance(chain, list) and chain else None
    control_return = (
        return_stage.get("control_return")
        if isinstance(return_stage, Mapping)
        else None
    )
    decision_schema = (
        decision.get("schema") if isinstance(decision, Mapping) else None
    )
    expected_return_schema = _PROMOTED_CONTROL_DECISION_RETURN_SCHEMAS.get(
        decision_schema
    )
    transition_payload = (
        decision.get("transition") if isinstance(decision, Mapping) else None
    )
    transition_event = (
        transition_payload.get("event")
        if isinstance(transition_payload, Mapping)
        else None
    )
    transition_outcome = (
        transition_payload.get("outcome")
        if isinstance(transition_payload, Mapping)
        else None
    )
    terminal = (
        transition_outcome.get("kind")
        if isinstance(transition_outcome, Mapping)
        else None
    )
    if (
        decision_stage.get("schema")
        != PROMOTED_CONTROL_DECISION_STAGE_SCHEMA
        or decision_stage.get("admission_state")
        != PromotionQueueDisposition.CONTROL_DECISION_RETAINED.value
        or not isinstance(decision, Mapping)
        or decision_schema not in _PROMOTED_CONTROL_DECISION_SCHEMAS
        or terminal
        not in {
            PromotionQueueDisposition.UNRESOLVED.value,
            PromotionQueueDisposition.DEFERRED.value,
            PromotionQueueDisposition.REJECTED.value,
        }
        or decision_stage.get("numerical_disposition") != terminal
        or decision_stage.get("reason_code") != decision.get("failure_code")
        or not isinstance(transition_event, Mapping)
        or not isinstance(return_stage, Mapping)
        or return_stage.get("schema") != PROMOTED_CONTROL_RETURN_STAGE_SCHEMA
        or return_stage.get("route") != decision_stage.get("route")
        or not isinstance(control_return, Mapping)
        or control_return.get("schema") != expected_return_schema
        or decision.get("control_return_sha256")
        != control_return.get("control_return_sha256")
        or queue_entry.get("queue_ordinal")
        != decision_stage.get("queue_ordinal")
        or queue_entry.get("leaf_id") != decision_stage.get("leaf_id")
        or queue_entry.get("retained_promoted_stage_sha256")
        != decision_stage.get("stage_sha256")
    ):
        raise ValueError("CONTROL terminal proof chain is invalid")
    return {
        "schema": PROMOTED_CONTROL_TERMINAL_RECEIPT_SCHEMA,
        "queue_ordinal": queue_entry["queue_ordinal"],
        "leaf_id": queue_entry["leaf_id"],
        "route": decision_stage["route"],
        "disposition": terminal,
        "reason_code": decision["failure_code"],
        "source_fingerprint_sha256": queue_entry["source_fingerprint_sha256"],
        "retained_promoted_stage_sha256": decision_stage["stage_sha256"],
        "control_decision_schema": decision_schema,
        "control_decision_sha256": decision["control_decision_sha256"],
        "transition_id": decision["transition_id"],
        "control_return_stage_sha256": return_stage["stage_sha256"],
        "control_return_schema": expected_return_schema,
        "control_return_sha256": control_return["control_return_sha256"],
        "control_receipt_sha256": control_return["control_receipt_sha256"],
        "current_tier": transition_event["current_tier"],
        "current_action_kind": transition_event["current_action_kind"],
    }


def promoted_policy_terminal_disposition_receipt(
    queue_entry: Mapping[str, object],
    policy_stage: Mapping[str, object],
) -> dict[str, object]:
    """Project a deterministic receipt for a no-work policy terminal."""

    if not isinstance(queue_entry, Mapping) or not isinstance(
        policy_stage, Mapping
    ):
        raise ValueError("promoted policy terminal proof is invalid")
    policy_terminal = policy_stage.get("policy_terminal")
    terminal = policy_stage.get("admission_state")
    if (
        policy_stage.get("schema") != PROMOTED_POLICY_TERMINAL_STAGE_SCHEMA
        or policy_stage.get("execution_mode") != "BLOCK_ALL"
        or terminal
        not in {
            PromotionQueueDisposition.UNRESOLVED.value,
            PromotionQueueDisposition.DEFERRED.value,
            PromotionQueueDisposition.REJECTED.value,
        }
        or not isinstance(policy_terminal, Mapping)
        or queue_entry.get("queue_ordinal") != policy_stage.get("queue_ordinal")
        or queue_entry.get("leaf_id") != policy_stage.get("leaf_id")
    ):
        raise ValueError("promoted policy terminal proof is invalid")
    return {
        "schema": PROMOTED_POLICY_TERMINAL_RECEIPT_SCHEMA,
        "queue_ordinal": queue_entry["queue_ordinal"],
        "leaf_id": queue_entry["leaf_id"],
        "route": policy_stage["route"],
        "disposition": terminal,
        "reason_code": policy_stage["reason_code"],
        "source_fingerprint_sha256": queue_entry["source_fingerprint_sha256"],
        "retained_promoted_stage_sha256": policy_stage["stage_sha256"],
        "policy_terminal_sha256": policy_terminal["policy_terminal_sha256"],
    }


def _validate_promoted_stage_payload(
    stage: Mapping[str, object],
    *,
    queue_entry: Mapping[str, object],
) -> None:
    """Validate the schema-owned payload of one current or predecessor stage."""

    schema = stage.get("schema")
    if schema == PROMOTED_POLICY_TERMINAL_STAGE_SCHEMA:
        policy_terminal = stage.get("policy_terminal")
        policy_fields = {
            "schema",
            "disposition",
            "reason_code",
            "operation_identity",
            "route",
            "execution_mode",
            "policy_terminal_sha256",
        }
        expected_content = {
            "schema": PROMOTED_POLICY_TERMINAL_DECISION_SCHEMA,
            "disposition": stage.get("admission_state"),
            "reason_code": stage.get("reason_code"),
            "operation_identity": stage.get("operation_identity"),
            "route": stage.get("route"),
            "execution_mode": stage.get("execution_mode"),
        }
        if (
            stage.get("execution_mode") != "BLOCK_ALL"
            or stage.get("admission_state")
            not in {
                PromotionQueueDisposition.UNRESOLVED.value,
                PromotionQueueDisposition.DEFERRED.value,
                PromotionQueueDisposition.REJECTED.value,
            }
            or stage.get("numerical_disposition")
            != stage.get("admission_state")
            or stage.get("precision_tiers") != []
            or stage.get("receipts") != []
            or any(
                stage.get(field) != 0
                for field in (
                    "sample_count",
                    "sample_limit",
                    "root_read_count",
                    "root_read_limit",
                    "worker_launch_count",
                    "worker_launch_limit",
                )
            )
            or not isinstance(policy_terminal, Mapping)
            or set(policy_terminal) != policy_fields
            or {
                key: item
                for key, item in policy_terminal.items()
                if key != "policy_terminal_sha256"
            }
            != expected_content
            or policy_terminal.get("policy_terminal_sha256")
            != _sha256(expected_content)
            or any(
                field in stage
                for field in (
                    "calculation_artifact",
                    "control_return",
                    "control_decision",
                    "control_proof",
                )
            )
        ):
            raise ValueError("promoted policy terminal stage is invalid")
        return
    if schema == "windows-solver.promoted-calculation-stage/1":
        # Schema 1 is retained only as a standalone, historical terminal
        # presentation.  It predates typed raw artifacts and therefore cannot
        # be used as an escape hatch for an unknown or mistyped CONTROL
        # payload.  Current typed artifacts belong exclusively to the
        # authenticated schema-2 stage family below.
        if any(
            field in stage
            for field in (
                "calculation_artifact",
                "control_return",
                "control_decision",
                "control_proof",
            )
        ):
            raise ValueError("legacy promoted stage cannot carry a typed artifact")
        return
    if schema == PROMOTED_CALCULATION_STAGE_SCHEMA:
        artifact = stage.get("calculation_artifact")
        if (
            not isinstance(artifact, Mapping)
            or artifact.get("schema")
            in (
                _PROMOTED_CONTROL_RETURN_SCHEMAS
                | _PROMOTED_CONTROL_DECISION_SCHEMAS
                | {"windows-solver.promoted-horizon-control-return/1"}
            )
        ):
            raise ValueError("promoted calculation stage artifact is invalid")
        promoted_artifact_digest(artifact)
        return
    if schema == PROMOTED_CONTROL_RETURN_STAGE_SCHEMA:
        artifact = stage.get("control_return")
        if (
            stage.get("admission_state")
            != PromotionQueueDisposition.CONTROL_RETURN_RETAINED.value
            or not isinstance(artifact, Mapping)
            or artifact.get("schema") not in _PROMOTED_CONTROL_RETURN_SCHEMAS
            or "calculation_artifact" in stage
            or "control_decision" in stage
            or "control_proof" in stage
        ):
            raise ValueError("promoted control-return stage is invalid")
        promoted_artifact_digest(artifact)
        authority = authenticate_persisted_control_return(
            artifact,
            expected_schema=str(artifact["schema"]),
            expected_leaf_id=str(queue_entry["leaf_id"]),
            expected_current_action_kind=_expected_promoted_control_action(
                stage,
                artifact,
                queue_entry,
            ),
            expected_queue_ordinal=int(stage["queue_ordinal"]),
        )
        validate_persisted_control_stage_accounting(stage, authority)
        return
    if schema == PROMOTED_CONTROL_DECISION_STAGE_SCHEMA:
        artifact = stage.get("control_decision")
        chain = stage.get("calculation_chain")
        predecessor = chain[-1] if isinstance(chain, list) and chain else None
        predecessor_return = (
            predecessor.get("control_return")
            if isinstance(predecessor, Mapping)
            else None
        )
        expected_return_schema = _PROMOTED_CONTROL_DECISION_RETURN_SCHEMAS.get(
            artifact.get("schema") if isinstance(artifact, Mapping) else None
        )
        if (
            stage.get("admission_state")
            != PromotionQueueDisposition.CONTROL_DECISION_RETAINED.value
            or not isinstance(artifact, Mapping)
            or artifact.get("schema") not in _PROMOTED_CONTROL_DECISION_SCHEMAS
            or expected_return_schema is None
            or not isinstance(predecessor, Mapping)
            or predecessor.get("schema") != PROMOTED_CONTROL_RETURN_STAGE_SCHEMA
            or not isinstance(predecessor_return, Mapping)
            or predecessor_return.get("schema") != expected_return_schema
            or artifact.get("control_return_sha256")
            != predecessor_return.get("control_return_sha256")
            or "calculation_artifact" in stage
            or "control_return" in stage
            or "control_proof" in stage
        ):
            raise ValueError("promoted control-decision stage is invalid")
        promoted_artifact_digest(artifact)
        promoted_artifact_digest(predecessor_return)
        authority = authenticate_persisted_control_decision(
            predecessor_return,
            artifact,
            expected_return_schema=str(expected_return_schema),
            expected_decision_schema=str(artifact["schema"]),
            expected_leaf_id=str(queue_entry["leaf_id"]),
            expected_current_action_kind=_expected_promoted_control_action(
                predecessor,
                predecessor_return,
                queue_entry,
            ),
            expected_queue_ordinal=int(stage["queue_ordinal"]),
        )
        transition = authority.classification.transition
        if (
            stage.get("numerical_disposition") != transition.disposition
            or stage.get("reason_code") != transition.failure_code
        ):
            raise ValueError(
                "promoted control-decision stage contradicts its transition"
            )
        validate_persisted_control_stage_accounting(stage, authority)
        return
    if schema == PROMOTED_CONTROL_CONTINUATION_STAGE_SCHEMA:
        proof = stage.get("control_proof")
        chain = stage.get("calculation_chain")
        decision_stage = chain[-1] if isinstance(chain, list) and chain else None
        decision = (
            decision_stage.get("control_decision")
            if isinstance(decision_stage, Mapping)
            else None
        )
        decision_chain = (
            decision_stage.get("calculation_chain")
            if isinstance(decision_stage, Mapping)
            else None
        )
        return_stage = (
            decision_chain[-1]
            if isinstance(decision_chain, list) and decision_chain
            else None
        )
        control_return = (
            return_stage.get("control_return")
            if isinstance(return_stage, Mapping)
            else None
        )
        proof_fields = {
            "schema",
            "control_return_stage_sha256",
            "control_return_sha256",
            "control_decision_stage_sha256",
            "control_decision_sha256",
            "transition_id",
            "current_tier",
            "current_action_kind",
            "next_tier",
            "next_action_kind",
            "proof_sha256",
        }
        proof_content = (
            {key: item for key, item in proof.items() if key != "proof_sha256"}
            if isinstance(proof, Mapping)
            else None
        )
        transition_payload = (
            decision.get("transition")
            if isinstance(decision, Mapping)
            else None
        )
        transition_event = (
            transition_payload.get("event")
            if isinstance(transition_payload, Mapping)
            else None
        )
        transition_outcome = (
            transition_payload.get("outcome")
            if isinstance(transition_payload, Mapping)
            else None
        )
        if (
            stage.get("admission_state")
            != PromotionQueueDisposition.NUMERICAL_CONTINUATION.value
            or not isinstance(proof, Mapping)
            or set(proof) != proof_fields
            or proof.get("schema") != PROMOTED_CONTROL_CONTINUATION_PROOF_SCHEMA
            or proof.get("proof_sha256") != _sha256(proof_content)
            or not isinstance(decision_stage, Mapping)
            or decision_stage.get("schema")
            != PROMOTED_CONTROL_DECISION_STAGE_SCHEMA
            or not isinstance(decision, Mapping)
            or decision.get("schema") != PROMOTED_CONTROL_DECISION_SCHEMA
            or not isinstance(return_stage, Mapping)
            or return_stage.get("schema") != PROMOTED_CONTROL_RETURN_STAGE_SCHEMA
            or not isinstance(control_return, Mapping)
            or control_return.get("schema") != PROMOTED_CONTROL_RETURN_SCHEMA
            or proof.get("control_return_stage_sha256")
            != return_stage.get("stage_sha256")
            or proof.get("control_return_sha256")
            != control_return.get("control_return_sha256")
            or proof.get("control_decision_stage_sha256")
            != decision_stage.get("stage_sha256")
            or proof.get("control_decision_sha256")
            != decision.get("control_decision_sha256")
            or proof.get("transition_id") != decision.get("transition_id")
            or proof.get("current_tier") != "BF40"
            or proof.get("next_tier") != "BF80"
            or proof.get("current_action_kind") not in {"ROOT", "RESPONSE"}
            or proof.get("next_action_kind")
            != proof.get("current_action_kind")
            or not isinstance(transition_event, Mapping)
            or not isinstance(transition_outcome, Mapping)
            or transition_outcome.get("kind") != "PROMOTION_PENDING"
            or transition_outcome.get("queue_kind")
            != proof.get("current_action_kind")
            or transition_event.get("current_tier")
            != proof.get("current_tier")
            or transition_event.get("current_action_kind")
            != proof.get("current_action_kind")
            or transition_outcome.get("next_tier") != proof.get("next_tier")
            or transition_outcome.get("next_action_kind")
            != proof.get("next_action_kind")
            or "calculation_artifact" in stage
            or "control_return" in stage
            or "control_decision" in stage
        ):
            raise ValueError("promoted control continuation proof is invalid")
        promoted_artifact_digest(control_return)
        promoted_artifact_digest(decision)
        authority = authenticate_persisted_control_decision(
            control_return,
            decision,
            expected_return_schema=PROMOTED_CONTROL_RETURN_SCHEMA,
            expected_decision_schema=PROMOTED_CONTROL_DECISION_SCHEMA,
            expected_leaf_id=str(queue_entry["leaf_id"]),
            expected_current_action_kind=_expected_promoted_control_action(
                return_stage,
                control_return,
                queue_entry,
            ),
            expected_queue_ordinal=int(stage["queue_ordinal"]),
        )
        validate_persisted_control_stage_accounting(stage, authority)
        return
    raise ValueError("promoted stage schema is unsupported")


def _authenticate_promoted_stage_chain(
    stage: Mapping[str, object],
    *,
    queue_entry: Mapping[str, object],
    queue_ordinal: int,
) -> None:
    """Authenticate every reconstructable predecessor of one promoted stage."""

    chain = stage.get("calculation_chain")
    # Schema-1 promoted stages predate the immutable predecessor chain.  They
    # are accepted only as standalone legacy terminal material (there is no
    # successor digest to authenticate); every stage emitted by the current
    # pipeline is schema-2 and must carry an explicit list, including the
    # empty list for the first raw stage.
    if stage.get("schema") == "windows-solver.promoted-calculation-stage/1":
        if chain is None and stage.get("source_calculation_stage_sha256") is None:
            _validate_promoted_stage_payload(stage, queue_entry=queue_entry)
            return
    if not isinstance(chain, list) or not all(
        isinstance(item, Mapping) for item in chain
    ):
        raise ValueError("promoted calculation chain is invalid")
    expected_source: str | None = None
    for predecessor in chain:
        content = {
            key: item for key, item in predecessor.items() if key != "stage_sha256"
        }
        digest = predecessor.get("stage_sha256")
        if (
            predecessor.get("schema")
            not in {
                PROMOTED_CALCULATION_STAGE_SCHEMA,
                PROMOTED_CONTROL_RETURN_STAGE_SCHEMA,
                PROMOTED_CONTROL_DECISION_STAGE_SCHEMA,
                PROMOTED_CONTROL_CONTINUATION_STAGE_SCHEMA,
                PROMOTED_POLICY_TERMINAL_STAGE_SCHEMA,
            }
            or not _is_sha256(digest)
            or digest != _sha256(content)
            or predecessor.get("queue_ordinal") != queue_ordinal
            or predecessor.get("leaf_id") != queue_entry["leaf_id"]
            or predecessor.get("scientific_computation_identity")
            != queue_entry["scientific_computation_identity"]
            or predecessor.get("source_fingerprint_sha256")
            != queue_entry["source_fingerprint_sha256"]
            or predecessor.get("predecessor_stage_sha256")
            != queue_entry["source_stage_sha256"]
            or predecessor.get("source_root_seal_sha256")
            != queue_entry["source_root_seal_sha256"]
            or predecessor.get("source_calculation_stage_sha256")
            != expected_source
        ):
            raise ValueError("promoted calculation predecessor is invalid")
        _validate_promoted_stage_payload(
            predecessor,
            queue_entry=queue_entry,
        )
        expected_source = str(digest)
    if stage.get("source_calculation_stage_sha256") != expected_source:
        raise ValueError("promoted calculation chain head is invalid")
    _validate_promoted_stage_payload(stage, queue_entry=queue_entry)


def _require_replaced_promoted_stage(
    existing: object,
    successor: Mapping[str, object],
) -> None:
    """Require a successor to retain the exact stage it replaces."""

    if existing is None:
        if successor.get("source_calculation_stage_sha256") is not None:
            raise ValueError("initial promoted stage has a calculation predecessor")
        return
    if existing == successor:
        return
    if not isinstance(existing, Mapping) or (
        successor.get("source_calculation_stage_sha256")
        != existing.get("stage_sha256")
    ):
        raise ValueError("promoted successor does not retain its predecessor")
    chain = successor.get("calculation_chain")
    if not isinstance(chain, list) or not chain or chain[-1] != existing:
        raise ValueError("promoted successor predecessor bytes are not recoverable")


def _enum_value(value: object, enum_type: type[Enum], label: str) -> str:
    try:
        return enum_type(value).value  # type: ignore[call-arg, return-value]
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid {label}: {value!r}") from error


def _validated_record(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("schema-11 numerical record must be an object")
    record = copy.deepcopy(dict(value))
    leaf_id = record.get("leaf_id")
    if not isinstance(leaf_id, str) or not leaf_id:
        raise ValueError("schema-11 numerical record leaf_id is invalid")
    state = record.get("state")
    if state == "FAILED":
        raise ValueError("FAILED is not a schema-11 numerical record state")
    if state not in NUMERICAL_RECORD_STATES:
        raise ValueError(f"invalid schema-11 numerical record state: {state!r}")
    supplied = record.get("record_sha256")
    content = {key: item for key, item in record.items() if key != "record_sha256"}
    if not _is_sha256(supplied) or supplied != _sha256(content):
        raise ValueError("schema-11 numerical record digest is invalid")
    return record


def _validated_pass_timing(
    *,
    leaf_id: str,
    pass_value: str,
    tier_timing: Sequence[Mapping[str, object]],
    session_fragments: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    fragments = [TimingFragment.from_mapping(item) for item in session_fragments]
    if any(
        fragment.leaf_id != leaf_id
        or fragment.execution_profile != ExecutionProfile.SURVEY.value
        or fragment.survey_pass != pass_value
        for fragment in fragments
    ):
        raise ValueError("survey timing fragment binding is invalid")
    expected = list(fold_timing_fragments(fragments).tier_timing_mappings())
    supplied = [copy.deepcopy(dict(item)) for item in tier_timing]
    if fragments and supplied != expected:
        raise ValueError("survey tier timing disagrees with session fragments")
    if not fragments and supplied:
        raise ValueError("survey tier timing requires session fragments")
    return supplied, [fragment.to_mapping() for fragment in fragments]


def empty_schema11_checkpoint(
    campaign_id: str, selection_id: str
) -> dict[str, object]:
    if not campaign_id or not selection_id:
        raise ValueError("campaign_id and selection_id are required")
    return {
        "schema_version": CAMPAIGN_CHECKPOINT_SCHEMA_VERSION,
        "campaign_id": campaign_id,
        "selection_id": selection_id,
        "state": "PARTIAL",
        "records": [],
        "evidence_ledger": {},
        "survey_pass_ledger": {"binary64": {}, "promoted": {}},
        "promotion_queue": {"schema": PROMOTION_QUEUE_SCHEMA, "entries": []},
        "promoted_stage_ledger": {},
        "promoted_background_ledger": {},
        "promoted_root_ledger": {},
        "forensic_fixed_root_v2_history": {},
        "attempts": [],
        "system_failures": [],
        "recovery_receipts": [],
        "report_status_receipt": None,
    }


def add_numerical_record(
    checkpoint: Mapping[str, object], record: Mapping[str, object]
) -> dict[str, object]:
    result = validate_schema11_checkpoint(checkpoint)
    candidate = _validated_record(record)
    records = result["records"]
    assert isinstance(records, list)
    existing = [item for item in records if item["leaf_id"] == candidate["leaf_id"]]
    if existing:
        if existing[0] == candidate:
            return result
        raise ValueError(f"conflicting numerical record for {candidate['leaf_id']}")
    records.append(candidate)
    return result


def record_evidence(
    checkpoint: Mapping[str, object],
    *,
    leaf_id: str,
    central_record_sha256: str,
    central_stage_sha256: str,
    evidence_level: EvidenceLevel | str,
    receipts: Sequence[Mapping[str, object]] = (),
    discrepancy_codes: Sequence[str] = (),
) -> dict[str, object]:
    result = validate_schema11_checkpoint(checkpoint)
    level = _enum_value(evidence_level, EvidenceLevel, "evidence level")
    records = result["records"]
    assert isinstance(records, list)
    matching = [item for item in records if item["leaf_id"] == leaf_id]
    if not matching or matching[0]["record_sha256"] != central_record_sha256:
        raise ValueError("evidence does not bind the retained numerical record")
    if not _is_sha256(central_stage_sha256):
        raise ValueError("evidence central stage digest is invalid")
    ledger = result["evidence_ledger"]
    assert isinstance(ledger, dict)
    previous = ledger.get(leaf_id)
    if previous is not None:
        previous_level = previous["evidence_level"]
        if _EVIDENCE_RANK[level] < _EVIDENCE_RANK[previous_level]:
            raise ValueError("evidence level cannot decrease")
        if (
            previous["central_record_sha256"] != central_record_sha256
            or previous["central_stage_sha256"] != central_stage_sha256
        ):
            raise ValueError("evidence upgrade cannot replace the retained centre")
        merged_receipts = list(previous["receipts"])
        merged_codes = list(previous["discrepancy_codes"])
    else:
        merged_receipts = []
        merged_codes = []
    if level == EvidenceLevel.VALIDATED.value and not any(
        validated_disposition_is_admitted(
            receipt,
            leaf_id=leaf_id,
            central_record_sha256=central_record_sha256,
            central_stage_sha256=central_stage_sha256,
        )
        for receipt in (*merged_receipts, *receipts)
        if isinstance(receipt, Mapping)
    ):
        raise ValueError(
            "VALIDATED requires an authenticated approved independent route"
        )
    if level == EvidenceLevel.CERTIFIED.value and not any(
        certified_disposition_is_admitted(
            receipt,
            leaf_id=leaf_id,
            central_record_sha256=central_record_sha256,
            central_stage_sha256=central_stage_sha256,
        )
        for receipt in (*merged_receipts, *receipts)
        if isinstance(receipt, Mapping)
    ):
        raise ValueError(
            "CERTIFIED requires an authenticated certification disposition"
        )
    for receipt in receipts:
        candidate = copy.deepcopy(dict(receipt))
        if candidate not in merged_receipts:
            merged_receipts.append(candidate)
    for code in discrepancy_codes:
        if not isinstance(code, str) or not code:
            raise ValueError("evidence discrepancy code is invalid")
        if code not in merged_codes:
            merged_codes.append(code)
    ledger[leaf_id] = {
        "leaf_id": leaf_id,
        "central_record_sha256": central_record_sha256,
        "central_stage_sha256": central_stage_sha256,
        "evidence_level": level,
        "receipts": merged_receipts,
        "discrepancy_codes": merged_codes,
    }
    return result


def record_survey_disposition(
    checkpoint: Mapping[str, object],
    *,
    survey_pass: SurveyPass | str,
    leaf_id: str,
    disposition: SurveyDisposition | str,
    operation_identity: str,
    precision_tiers: Sequence[str],
    reason_code: str,
    sample_count: int,
    sample_limit: int,
    root_read_count: int,
    root_read_limit: int,
    worker_launch_count: int,
    worker_launch_limit: int,
    tier_timing: Sequence[Mapping[str, object]],
    session_fragments: Sequence[Mapping[str, object]],
    source_record_sha256: str | None = None,
    result_record_sha256: str | None = None,
    layer1_guard: object | None = None,
) -> dict[str, object]:
    result = validate_schema11_checkpoint(checkpoint)
    pass_value = _enum_value(survey_pass, SurveyPass, "survey pass")
    disposition_value = _enum_value(
        disposition, SurveyDisposition, "survey disposition"
    )
    allowed = (
        BINARY64_SURVEY_DISPOSITIONS
        if pass_value == SurveyPass.BINARY64.value
        else PROMOTED_SURVEY_DISPOSITIONS
    )
    if disposition_value not in allowed:
        raise ValueError(f"{disposition_value} is invalid for the promoted pass")
    if not leaf_id or not operation_identity or not reason_code:
        raise ValueError("survey disposition identity fields are required")
    for digest in (source_record_sha256, result_record_sha256):
        if digest is not None and not _is_sha256(digest):
            raise ValueError("survey disposition record digest is invalid")
    counters = {
        "sample_count": sample_count,
        "sample_limit": sample_limit,
        "root_read_count": root_read_count,
        "root_read_limit": root_read_limit,
        "worker_launch_count": worker_launch_count,
        "worker_launch_limit": worker_launch_limit,
    }
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in counters.values()
    ):
        raise ValueError("survey disposition counters must be nonnegative integers")
    count_names = ("sample_count", "root_read_count", "worker_launch_count")
    if any(
        counters[name] > counters[name.replace("_count", "_limit")]
        for name in count_names
    ):
        raise ValueError("survey disposition count exceeds its limit")
    validated_timing, validated_fragments = _validated_pass_timing(
        leaf_id=leaf_id,
        pass_value=pass_value,
        tier_timing=tier_timing,
        session_fragments=session_fragments,
    )
    content: dict[str, object] = {
        "leaf_id": leaf_id,
        "pass": pass_value,
        "source_record_sha256": source_record_sha256,
        "result_record_sha256": result_record_sha256,
        "operation_identity": operation_identity,
        "precision_tiers": list(precision_tiers),
        "reason_code": reason_code,
        **counters,
        "tier_timing": validated_timing,
        "session_fragments": validated_fragments,
        "disposition": disposition_value,
    }
    entry = {**content, "disposition_receipt_sha256": _sha256(content)}
    ledger = result["survey_pass_ledger"]
    assert isinstance(ledger, dict)
    pass_ledger = ledger[pass_value]
    assert isinstance(pass_ledger, dict)
    pass_ledger[leaf_id] = entry
    _assert_layer1_guard(layer1_guard, result)
    return result


def append_promotion(
    checkpoint: Mapping[str, object],
    *,
    leaf_id: str,
    queue_kind: PromotionQueueKind | str,
    reason_code: str,
    minimum_requested_tier: str,
    scientific_computation_identity: str,
    source_record_sha256: str | None = None,
    source_stage_sha256: str | None = None,
    source_root_seal_sha256: str | None = None,
    provisional_stage: Mapping[str, object] | None = None,
    provisional_stage_sha256: str | None = None,
    provisional_operation_identity: str | None = None,
    source_binary64_disposition_receipt_sha256: str | None = None,
    layer1_guard: object | None = None,
) -> dict[str, object]:
    result = validate_schema11_checkpoint(checkpoint)
    kind = _enum_value(queue_kind, PromotionQueueKind, "promotion queue kind")
    if not leaf_id or not reason_code or not minimum_requested_tier:
        raise ValueError("promotion queue identity fields are required")
    if not _is_sha256(scientific_computation_identity):
        raise ValueError("scientific computation identity is invalid")
    for digest in (
        source_record_sha256,
        source_stage_sha256,
        source_root_seal_sha256,
        provisional_stage_sha256,
        source_binary64_disposition_receipt_sha256,
    ):
        if digest is not None and not _is_sha256(digest):
            raise ValueError("promotion queue source digest is invalid")
    if provisional_stage is None:
        if (
            provisional_stage_sha256 is not None
            or provisional_operation_identity is not None
        ):
            raise ValueError("promotion queue provisional stage is incomplete")
    else:
        if not isinstance(provisional_stage, Mapping):
            raise ValueError("promotion queue provisional stage is invalid")
        stage = copy.deepcopy(dict(provisional_stage))
        supplied = stage.get("stage_sha256")
        content = {
            key: item for key, item in stage.items() if key != "stage_sha256"
        }
        if (
            not _is_sha256(supplied)
            or supplied != _sha256(content)
            or provisional_stage_sha256 != supplied
            or not isinstance(provisional_operation_identity, str)
            or not provisional_operation_identity
            or stage.get("operation_identity") != provisional_operation_identity
        ):
            raise ValueError("promotion queue provisional stage authentication is invalid")
        if source_stage_sha256 != provisional_stage_sha256:
            raise ValueError("promotion queue provisional stage source mismatch")
        if source_record_sha256 is not None:
            raise ValueError("promotion queue cannot bind a record and provisional stage")
    if source_record_sha256 is not None and provisional_stage is not None:
        raise ValueError("promotion queue source representations are ambiguous")
    queue = result["promotion_queue"]
    assert isinstance(queue, dict)
    entries = queue["entries"]
    assert isinstance(entries, list)
    entry = {
        "leaf_id": leaf_id,
        "queue_kind": kind,
        "source_pass": SurveyPass.BINARY64.value,
        "reason_code": reason_code,
        "minimum_requested_tier": minimum_requested_tier,
        "source_record_sha256": source_record_sha256,
        "source_stage_sha256": source_stage_sha256,
        "source_root_seal_sha256": source_root_seal_sha256,
        "scientific_computation_identity": scientific_computation_identity,
        "provisional_stage": (
            None if provisional_stage is None else copy.deepcopy(dict(provisional_stage))
        ),
        "provisional_stage_sha256": provisional_stage_sha256,
        "provisional_operation_identity": provisional_operation_identity,
        "source_binary64_disposition_receipt_sha256": (
            source_binary64_disposition_receipt_sha256
        ),
        "provisional_reuse_receipt": None,
        "provisional_reuse_receipt_sha256": None,
        "retained_promoted_stage_sha256": None,
        "queue_ordinal": len(entries),
        "disposition": PromotionQueueDisposition.PENDING.value,
        "disposition_receipt_sha256": None,
    }
    entry["source_fingerprint_sha256"] = promotion_source_fingerprint_sha256(entry)
    entries.append(entry)
    _assert_layer1_guard(layer1_guard, result)
    return result


def retain_promoted_control_return(
    checkpoint: Mapping[str, object],
    *,
    queue_ordinal: int,
    promoted_stage: Mapping[str, object],
    execution_mode: str,
    disposition_receipt: Mapping[str, object],
    layer1_guard: object | None = None,
) -> dict[str, object]:
    """Durably retain a CONTROL return without calling it a calculation."""

    result = validate_schema11_checkpoint(checkpoint)
    if execution_mode != "CALCULATE_ONLY":
        raise ValueError("control-return retention requires CALCULATE_ONLY mode")
    entries = result["promotion_queue"]["entries"]
    if (
        isinstance(queue_ordinal, bool)
        or not isinstance(queue_ordinal, int)
        or queue_ordinal < 0
        or queue_ordinal >= len(entries)
    ):
        raise ValueError("promotion queue ordinal is invalid")
    entry = entries[queue_ordinal]
    prior_disposition = entry["disposition"]
    if prior_disposition not in {
        PromotionQueueDisposition.PENDING.value,
        PromotionQueueDisposition.NUMERICAL_CONTINUATION.value,
    }:
        raise ValueError("promotion queue cannot retain a control return")
    stage = copy.deepcopy(dict(promoted_stage))
    content = {key: item for key, item in stage.items() if key != "stage_sha256"}
    if (
        stage.get("stage_sha256") != _sha256(content)
        or stage.get("schema") != PROMOTED_CONTROL_RETURN_STAGE_SCHEMA
        or stage.get("leaf_id") != entry["leaf_id"]
        or stage.get("queue_ordinal") != queue_ordinal
        or stage.get("execution_mode") != execution_mode
        or stage.get("admission_state")
        != PromotionQueueDisposition.CONTROL_RETURN_RETAINED.value
    ):
        raise ValueError("promoted control-return stage authentication is invalid")
    _authenticate_promoted_stage_chain(
        stage, queue_entry=entry, queue_ordinal=queue_ordinal
    )
    bucket = result["promoted_stage_ledger"].setdefault(str(queue_ordinal), {})
    if not isinstance(bucket, dict):
        raise ValueError("promoted stage ledger ordinal is invalid")
    leaf_id = str(entry["leaf_id"])
    existing = bucket.get(leaf_id)
    if prior_disposition == PromotionQueueDisposition.PENDING.value:
        if existing is not None:
            raise ValueError("initial control return conflicts with retained state")
    elif (
        not isinstance(existing, Mapping)
        or existing.get("schema") != PROMOTED_CONTROL_CONTINUATION_STAGE_SCHEMA
    ):
        raise ValueError("BF80 control return lacks its continuation predecessor")
    _require_replaced_promoted_stage(existing, stage)
    receipt = copy.deepcopy(dict(disposition_receipt))
    receipt.update({
        "source_fingerprint_sha256": entry["source_fingerprint_sha256"],
        "retained_promoted_stage_sha256": stage["stage_sha256"],
        "execution_mode": execution_mode,
        "admission_state": PromotionQueueDisposition.CONTROL_RETURN_RETAINED.value,
    })
    bucket[leaf_id] = stage
    entry["retained_promoted_stage_sha256"] = stage["stage_sha256"]
    entry["disposition"] = PromotionQueueDisposition.CONTROL_RETURN_RETAINED.value
    entry["disposition_receipt_sha256"] = _sha256(receipt)
    _assert_layer1_guard(layer1_guard, result)
    return result


def retain_promoted_control_decision(
    checkpoint: Mapping[str, object],
    *,
    queue_ordinal: int,
    promoted_stage: Mapping[str, object],
    execution_mode: str,
    disposition_receipt: Mapping[str, object],
    layer1_guard: object | None = None,
) -> dict[str, object]:
    """Durably retain the pure classification of a retained CONTROL return."""

    result = validate_schema11_checkpoint(checkpoint)
    if execution_mode != "CALCULATE_ONLY":
        raise ValueError("control-decision retention requires CALCULATE_ONLY mode")
    entries = result["promotion_queue"]["entries"]
    if (
        isinstance(queue_ordinal, bool)
        or not isinstance(queue_ordinal, int)
        or queue_ordinal < 0
        or queue_ordinal >= len(entries)
    ):
        raise ValueError("promotion queue ordinal is invalid")
    entry = entries[queue_ordinal]
    if entry["disposition"] != PromotionQueueDisposition.CONTROL_RETURN_RETAINED.value:
        raise ValueError("control decision lacks a durable control return")
    stage = copy.deepcopy(dict(promoted_stage))
    content = {key: item for key, item in stage.items() if key != "stage_sha256"}
    if (
        stage.get("stage_sha256") != _sha256(content)
        or stage.get("schema") != PROMOTED_CONTROL_DECISION_STAGE_SCHEMA
        or stage.get("leaf_id") != entry["leaf_id"]
        or stage.get("queue_ordinal") != queue_ordinal
        or stage.get("execution_mode") != execution_mode
        or stage.get("admission_state")
        != PromotionQueueDisposition.CONTROL_DECISION_RETAINED.value
    ):
        raise ValueError("promoted control-decision stage authentication is invalid")
    _authenticate_promoted_stage_chain(
        stage, queue_entry=entry, queue_ordinal=queue_ordinal
    )
    bucket = result["promoted_stage_ledger"].get(str(queue_ordinal))
    existing = (
        bucket.get(str(entry["leaf_id"])) if isinstance(bucket, dict) else None
    )
    if (
        not isinstance(existing, Mapping)
        or existing.get("schema") != PROMOTED_CONTROL_RETURN_STAGE_SCHEMA
    ):
        raise ValueError("durable control-return stage is missing")
    _require_replaced_promoted_stage(existing, stage)
    receipt = copy.deepcopy(dict(disposition_receipt))
    receipt.update({
        "source_fingerprint_sha256": entry["source_fingerprint_sha256"],
        "retained_promoted_stage_sha256": stage["stage_sha256"],
        "execution_mode": execution_mode,
        "admission_state": PromotionQueueDisposition.CONTROL_DECISION_RETAINED.value,
    })
    assert isinstance(bucket, dict)
    leaf_id = str(entry["leaf_id"])
    bucket[leaf_id] = stage
    entry["retained_promoted_stage_sha256"] = stage["stage_sha256"]
    entry["disposition"] = PromotionQueueDisposition.CONTROL_DECISION_RETAINED.value
    entry["disposition_receipt_sha256"] = _sha256(receipt)
    _assert_layer1_guard(layer1_guard, result)
    return result


def retain_promoted_control_terminal(
    checkpoint: Mapping[str, object],
    *,
    queue_ordinal: int,
    disposition: PromotionQueueDisposition | str,
    disposition_receipt: Mapping[str, object],
    layer1_guard: object | None = None,
) -> dict[str, object]:
    """Finish a non-promoting CONTROL decision without fabricating numerics."""

    result = validate_schema11_checkpoint(checkpoint)
    terminal = _enum_value(
        disposition, PromotionQueueDisposition, "control terminal disposition"
    )
    if terminal not in {
        PromotionQueueDisposition.UNRESOLVED.value,
        PromotionQueueDisposition.DEFERRED.value,
        PromotionQueueDisposition.REJECTED.value,
    }:
        raise ValueError("control terminal disposition is invalid")
    entries = result["promotion_queue"]["entries"]
    if (
        isinstance(queue_ordinal, bool)
        or not isinstance(queue_ordinal, int)
        or queue_ordinal < 0
        or queue_ordinal >= len(entries)
    ):
        raise ValueError("promotion queue ordinal is invalid")
    entry = entries[queue_ordinal]
    bucket = result["promoted_stage_ledger"].get(str(queue_ordinal))
    stage = bucket.get(str(entry["leaf_id"])) if isinstance(bucket, dict) else None
    decision = stage.get("control_decision") if isinstance(stage, Mapping) else None
    if (
        entry["disposition"]
        != PromotionQueueDisposition.CONTROL_DECISION_RETAINED.value
        or not isinstance(stage, Mapping)
        or stage.get("schema") != PROMOTED_CONTROL_DECISION_STAGE_SCHEMA
        or stage.get("stage_sha256") != entry["retained_promoted_stage_sha256"]
        or not isinstance(decision, Mapping)
        or _control_outcome_kind(decision) != terminal
    ):
        raise ValueError("control terminal decision is invalid")
    receipt = promoted_control_terminal_disposition_receipt(entry, stage)
    if copy.deepcopy(dict(disposition_receipt)) != receipt:
        raise ValueError("control terminal disposition receipt is invalid")
    entry["disposition"] = terminal
    entry["disposition_receipt_sha256"] = _sha256(receipt)
    _assert_layer1_guard(layer1_guard, result)
    return result


def retain_promoted_policy_terminal(
    checkpoint: Mapping[str, object],
    *,
    queue_ordinal: int,
    promoted_stage: Mapping[str, object],
    disposition: PromotionQueueDisposition | str,
    disposition_receipt: Mapping[str, object],
    layer1_guard: object | None = None,
) -> dict[str, object]:
    """Retain an explicit no-work policy decision as a typed terminal stage."""

    result = validate_schema11_checkpoint(checkpoint)
    terminal = _enum_value(
        disposition, PromotionQueueDisposition, "policy terminal disposition"
    )
    if terminal not in {
        PromotionQueueDisposition.UNRESOLVED.value,
        PromotionQueueDisposition.DEFERRED.value,
        PromotionQueueDisposition.REJECTED.value,
    }:
        raise ValueError("policy terminal disposition is invalid")
    entries = result["promotion_queue"]["entries"]
    if (
        isinstance(queue_ordinal, bool)
        or not isinstance(queue_ordinal, int)
        or queue_ordinal < 0
        or queue_ordinal >= len(entries)
    ):
        raise ValueError("promotion queue ordinal is invalid")
    entry = entries[queue_ordinal]
    stage = copy.deepcopy(dict(promoted_stage))
    content = {key: item for key, item in stage.items() if key != "stage_sha256"}
    if (
        entry["disposition"] != PromotionQueueDisposition.PENDING.value
        or stage.get("stage_sha256") != _sha256(content)
        or stage.get("schema") != PROMOTED_POLICY_TERMINAL_STAGE_SCHEMA
        or stage.get("leaf_id") != entry["leaf_id"]
        or stage.get("queue_ordinal") != queue_ordinal
        or stage.get("execution_mode") != "BLOCK_ALL"
        or stage.get("admission_state") != terminal
    ):
        raise ValueError("promoted policy terminal stage is invalid")
    _authenticate_promoted_stage_chain(
        stage, queue_entry=entry, queue_ordinal=queue_ordinal
    )
    receipt = promoted_policy_terminal_disposition_receipt(entry, stage)
    if copy.deepcopy(dict(disposition_receipt)) != receipt:
        raise ValueError("policy terminal disposition receipt is invalid")
    bucket = result["promoted_stage_ledger"].setdefault(str(queue_ordinal), {})
    if not isinstance(bucket, dict) or bucket.get(str(entry["leaf_id"])) is not None:
        raise ValueError("conflicting promoted policy terminal stage")
    bucket[str(entry["leaf_id"])] = stage
    entry["retained_promoted_stage_sha256"] = stage["stage_sha256"]
    entry["disposition"] = terminal
    entry["disposition_receipt_sha256"] = _sha256(receipt)
    _assert_layer1_guard(layer1_guard, result)
    return result


def retain_promoted_continuation(
    checkpoint: Mapping[str, object],
    *,
    queue_ordinal: int,
    promoted_stage: Mapping[str, object],
    execution_mode: str,
    layer1_guard: object | None = None,
) -> dict[str, object]:
    """Retain BF80 authority only from a durable classified CONTROL decision."""

    result = validate_schema11_checkpoint(checkpoint)
    if execution_mode not in _PROMOTED_EXECUTION_MODES - {"BLOCK_ALL"}:
        raise ValueError("promoted continuation execution mode is invalid")
    queue = result["promotion_queue"]
    assert isinstance(queue, dict)
    entries = queue["entries"]
    assert isinstance(entries, list)
    if (
        isinstance(queue_ordinal, bool)
        or not isinstance(queue_ordinal, int)
        or queue_ordinal < 0
        or queue_ordinal >= len(entries)
    ):
        raise ValueError("promotion queue ordinal is invalid")
    entry = entries[queue_ordinal]
    if (
        entry["queue_ordinal"] != queue_ordinal
        or entry["disposition"]
        != PromotionQueueDisposition.CONTROL_DECISION_RETAINED.value
    ):
        raise ValueError("promotion continuation lacks a durable control decision")
    if not isinstance(promoted_stage, Mapping):
        raise ValueError("promoted continuation stage is invalid")
    stage = copy.deepcopy(dict(promoted_stage))
    stage_content = {
        key: item for key, item in stage.items() if key != "stage_sha256"
    }
    supplied_stage_sha256 = stage.get("stage_sha256")
    if (
        not _is_sha256(supplied_stage_sha256)
        or supplied_stage_sha256 != _sha256(stage_content)
        or stage.get("leaf_id") != entry["leaf_id"]
        or stage.get("queue_ordinal") != queue_ordinal
        or stage.get("schema") != PROMOTED_CONTROL_CONTINUATION_STAGE_SCHEMA
        or stage.get("execution_mode") != execution_mode
        or stage.get("admission_state") != "NUMERICAL_CONTINUATION"
        or stage.get("next_precision_tier") != "BF80"
        or stage.get("precision_tiers") != ["BF40"]
    ):
        raise ValueError("promoted continuation stage authentication is invalid")
    _authenticate_promoted_stage_chain(
        stage, queue_entry=entry, queue_ordinal=queue_ordinal
    )
    stage_ledger = result["promoted_stage_ledger"]
    assert isinstance(stage_ledger, dict)
    ordinal_key = str(queue_ordinal)
    bucket = stage_ledger.setdefault(ordinal_key, {})
    if not isinstance(bucket, dict):
        raise ValueError("promoted stage ledger ordinal is invalid")
    leaf_id = str(entry["leaf_id"])
    existing_stage = bucket.get(leaf_id)
    if (
        not isinstance(existing_stage, Mapping)
        or existing_stage.get("schema")
        != PROMOTED_CONTROL_DECISION_STAGE_SCHEMA
        or existing_stage.get("admission_state")
        != PromotionQueueDisposition.CONTROL_DECISION_RETAINED.value
    ):
        raise ValueError("promoted continuation decision stage is missing")
    if existing_stage != stage and stage.get("source_calculation_stage_sha256") != (
        existing_stage.get("stage_sha256")
    ):
        raise ValueError("conflicting promoted continuation stage")
    _require_replaced_promoted_stage(existing_stage, stage)
    bucket[leaf_id] = stage
    entry["retained_promoted_stage_sha256"] = supplied_stage_sha256
    entry["disposition"] = PromotionQueueDisposition.NUMERICAL_CONTINUATION.value
    entry["disposition_receipt_sha256"] = _sha256({
        "schema": "windows-solver.promoted-numerical-continuation/2",
        "queue_ordinal": queue_ordinal,
        "leaf_id": leaf_id,
        "retained_promoted_stage_sha256": supplied_stage_sha256,
        "source_fingerprint_sha256": entry["source_fingerprint_sha256"],
    })
    _assert_layer1_guard(layer1_guard, result)
    return result


def _retain_promoted_auxiliary_entry(
    result: dict[str, object],
    *,
    ledger_field: str,
    queue_ordinal: int,
    leaf_id: str,
    payload: Mapping[str, object],
    schema: str,
) -> None:
    """Store one checkpoint-owned promoted dependency without a sidecar."""

    content: dict[str, object] = {
        "schema": schema,
        "queue_ordinal": queue_ordinal,
        "leaf_id": leaf_id,
        "payload": copy.deepcopy(dict(payload)),
    }
    ledger_entry = {**content, "ledger_entry_sha256": _sha256(content)}
    auxiliary_ledger = result[ledger_field]
    assert isinstance(auxiliary_ledger, dict)
    ordinal_key = str(queue_ordinal)
    auxiliary_bucket = auxiliary_ledger.setdefault(ordinal_key, {})
    if not isinstance(auxiliary_bucket, dict):
        raise ValueError(f"{ledger_field} ordinal is invalid")
    existing = auxiliary_bucket.get(leaf_id)
    if existing is None or existing == ledger_entry:
        auxiliary_bucket[leaf_id] = ledger_entry
        return
    if ledger_field != "promoted_background_ledger":
        raise ValueError(f"conflicting {ledger_field} entry")
    if not isinstance(existing, Mapping):
        raise ValueError("conflicting promoted background entry")
    existing_payload = existing.get("payload")
    existing_receipts = (
        existing_payload.get("background_receipts")
        if isinstance(existing_payload, Mapping)
        else None
    )
    incoming_receipts = payload.get("background_receipts")
    if (
        not isinstance(existing_receipts, list)
        or not isinstance(incoming_receipts, list)
        or existing_payload.get("schema") != payload.get("schema")
        or existing_payload.get("route") != payload.get("route")
    ):
        raise ValueError("conflicting promoted background entry")
    merged: list[dict[str, object]] = []
    by_digest: dict[str, dict[str, object]] = {}
    for receipt in [*existing_receipts, *incoming_receipts]:
        if not isinstance(receipt, Mapping):
            raise ValueError("promoted background receipt is invalid")
        canonical = copy.deepcopy(dict(receipt))
        digest = canonical.get("receipt_sha256")
        if not _is_sha256(digest):
            raise ValueError("promoted background receipt digest is invalid")
        prior = by_digest.get(str(digest))
        if prior is not None:
            if prior != canonical:
                raise ValueError("conflicting promoted background receipt")
            continue
        by_digest[str(digest)] = canonical
        merged.append(canonical)
    merged_payload = copy.deepcopy(dict(payload))
    merged_payload["background_receipts"] = merged
    merged_content = {
        "schema": schema,
        "queue_ordinal": queue_ordinal,
        "leaf_id": leaf_id,
        "payload": merged_payload,
    }
    auxiliary_bucket[leaf_id] = {
        **merged_content,
        "ledger_entry_sha256": _sha256(merged_content),
    }


def retain_promoted_background(
    checkpoint: Mapping[str, object],
    *,
    queue_ordinal: int,
    route: str,
    background_receipt: Mapping[str, object],
    layer1_guard: object | None = None,
) -> dict[str, object]:
    """Commit a shared promoted background before its mechanism samples run."""

    result = validate_schema11_checkpoint(checkpoint)
    queue = result["promotion_queue"]
    assert isinstance(queue, dict)
    entries = queue["entries"]
    assert isinstance(entries, list)
    if (
        isinstance(queue_ordinal, bool)
        or not isinstance(queue_ordinal, int)
        or queue_ordinal < 0
        or queue_ordinal >= len(entries)
    ):
        raise ValueError("promotion queue ordinal is invalid")
    entry = entries[queue_ordinal]
    if (
        entry["queue_ordinal"] != queue_ordinal
        or entry["disposition"]
        not in {
            PromotionQueueDisposition.PENDING.value,
            PromotionQueueDisposition.CALCULATED_PENDING_DERIVATION.value,
            PromotionQueueDisposition.NUMERICAL_CONTINUATION.value,
        }
        or route not in {"EXTERIOR_BF40", "HORIZON_BF80"}
        or not isinstance(background_receipt, Mapping)
        or not _is_sha256(background_receipt.get("receipt_sha256"))
    ):
        raise ValueError("promoted background retention is invalid")
    _retain_promoted_auxiliary_entry(
        result,
        ledger_field="promoted_background_ledger",
        queue_ordinal=queue_ordinal,
        leaf_id=str(entry["leaf_id"]),
        payload={
            "schema": "windows-solver.promoted-background-retention/1",
            "route": route,
            "background_receipts": [copy.deepcopy(dict(background_receipt))],
        },
        schema="windows-solver.promoted-background-ledger-entry/1",
    )
    _assert_layer1_guard(layer1_guard, result)
    return result


def retain_promoted_raw_calculation(
    checkpoint: Mapping[str, object],
    *,
    queue_ordinal: int,
    promoted_stage: Mapping[str, object],
    execution_mode: str,
    disposition_receipt: Mapping[str, object],
    layer1_guard: object | None = None,
) -> dict[str, object]:
    """Durably retain one worker return before any reducer may consume it.

    This is intentionally a distinct state from ``AWAITING_ADMISSION``.  A
    raw result can survive an interrupt and later be reduced without a second
    worker launch; it is not yet a screened claim or a terminal record.
    """

    result = validate_schema11_checkpoint(checkpoint)
    if execution_mode != "CALCULATE_ONLY":
        raise ValueError("raw promoted retention requires CALCULATE_ONLY mode")
    queue = result["promotion_queue"]
    assert isinstance(queue, dict)
    entries = queue["entries"]
    assert isinstance(entries, list)
    if (
        isinstance(queue_ordinal, bool)
        or not isinstance(queue_ordinal, int)
        or queue_ordinal < 0
        or queue_ordinal >= len(entries)
    ):
        raise ValueError("promotion queue ordinal is invalid")
    entry = entries[queue_ordinal]
    if (
        entry["queue_ordinal"] != queue_ordinal
        or entry["disposition"]
        not in {
            PromotionQueueDisposition.PENDING.value,
            PromotionQueueDisposition.NUMERICAL_CONTINUATION.value,
        }
        or not isinstance(promoted_stage, Mapping)
    ):
        raise ValueError("promotion queue cannot retain a raw calculation")
    stage = copy.deepcopy(dict(promoted_stage))
    stage_content = {key: item for key, item in stage.items() if key != "stage_sha256"}
    stage_sha256 = stage.get("stage_sha256")
    artifact = stage.get("calculation_artifact")
    if (
        not _is_sha256(stage_sha256)
        or stage_sha256 != _sha256(stage_content)
        or stage.get("leaf_id") != entry["leaf_id"]
        or stage.get("queue_ordinal") != queue_ordinal
        or stage.get("execution_mode") != execution_mode
        or stage.get("admission_state") != "CALCULATED_PENDING_DERIVATION"
        or not isinstance(artifact, Mapping)
    ):
        raise ValueError("raw promoted calculation authentication is invalid")
    _authenticate_promoted_stage_chain(
        stage, queue_entry=entry, queue_ordinal=queue_ordinal
    )
    artifact_digest_field, artifact_sha256 = promoted_artifact_digest(artifact)
    if artifact.get("schema") in (
        _PROMOTED_CONTROL_RETURN_SCHEMAS
        | _PROMOTED_CONTROL_DECISION_SCHEMAS
        | {"windows-solver.promoted-horizon-control-return/1"}
    ):
        raise ValueError("CONTROL artifact cannot be retained as a calculation")
    receipt = copy.deepcopy(dict(disposition_receipt))
    source_fingerprint_sha256 = entry["source_fingerprint_sha256"]
    supplied_fingerprint = receipt.get("source_fingerprint_sha256")
    if supplied_fingerprint is not None and supplied_fingerprint != source_fingerprint_sha256:
        raise ValueError("raw promoted calculation source fingerprint is invalid")
    if receipt.get("schema") == "windows-solver.promoted-raw-return-retention/3":
        if (
            receipt.get("artifact_digest_field") != artifact_digest_field
            or receipt.get("artifact_sha256") != artifact_sha256
        ):
            raise ValueError("raw promoted return receipt is invalid")
    receipt.update({
        "source_fingerprint_sha256": source_fingerprint_sha256,
        "retained_promoted_stage_sha256": stage_sha256,
        "execution_mode": execution_mode,
        "admission_state": "CALCULATED_PENDING_DERIVATION",
    })
    stage_ledger = result["promoted_stage_ledger"]
    assert isinstance(stage_ledger, dict)
    bucket = stage_ledger.setdefault(str(queue_ordinal), {})
    if not isinstance(bucket, dict):
        raise ValueError("promoted stage ledger ordinal is invalid")
    leaf_id = str(entry["leaf_id"])
    existing = bucket.get(leaf_id)
    if existing is not None and existing != stage and not (
        isinstance(existing, Mapping)
        and existing.get("admission_state") == "NUMERICAL_CONTINUATION"
    ):
        raise ValueError("conflicting raw promoted calculation")
    _require_replaced_promoted_stage(existing, stage)
    bucket[leaf_id] = stage
    entry["retained_promoted_stage_sha256"] = stage_sha256
    entry["disposition"] = PromotionQueueDisposition.CALCULATED_PENDING_DERIVATION.value
    entry["disposition_receipt_sha256"] = _sha256(receipt)
    _assert_layer1_guard(layer1_guard, result)
    return result


def retain_promoted_calculation(
    checkpoint: Mapping[str, object],
    *,
    queue_ordinal: int,
    promoted_stage: Mapping[str, object],
    execution_mode: str,
    disposition_receipt: Mapping[str, object],
    provisional_reuse_receipt: Mapping[str, object] | None = None,
    promoted_background: Mapping[str, object] | None = None,
    promoted_root: Mapping[str, object] | None = None,
    layer1_guard: object | None = None,
) -> dict[str, object]:
    """Durably retain promoted numerics without admitting them as evidence."""

    result = validate_schema11_checkpoint(checkpoint)
    if execution_mode != "CALCULATE_ONLY":
        raise ValueError(
            "retained unadmitted calculation requires CALCULATE_ONLY mode"
        )
    queue = result["promotion_queue"]
    assert isinstance(queue, dict)
    entries = queue["entries"]
    assert isinstance(entries, list)
    if (
        isinstance(queue_ordinal, bool)
        or not isinstance(queue_ordinal, int)
        or queue_ordinal < 0
        or queue_ordinal >= len(entries)
    ):
        raise ValueError("promotion queue ordinal is invalid")
    entry = entries[queue_ordinal]
    if (
        entry["queue_ordinal"] != queue_ordinal
        or entry["disposition"]
        not in {
            PromotionQueueDisposition.PENDING.value,
            PromotionQueueDisposition.CALCULATED_PENDING_DERIVATION.value,
            PromotionQueueDisposition.NUMERICAL_CONTINUATION.value,
        }
    ):
        raise ValueError("promotion queue entry cannot retain a reduced calculation")
    if not isinstance(promoted_stage, Mapping):
        raise ValueError("retained promoted stage is invalid")
    stage = copy.deepcopy(dict(promoted_stage))
    supplied_stage_sha256 = stage.get("stage_sha256")
    stage_content = {
        key: item for key, item in stage.items() if key != "stage_sha256"
    }
    if (
        not _is_sha256(supplied_stage_sha256)
        or supplied_stage_sha256 != _sha256(stage_content)
        or stage.get("leaf_id") != entry["leaf_id"]
        or stage.get("queue_ordinal") != queue_ordinal
        or stage.get("execution_mode") != execution_mode
        or stage.get("admission_state") != "AWAITING_ADMISSION"
    ):
        raise ValueError("retained promoted stage authentication is invalid")
    _authenticate_promoted_stage_chain(
        stage, queue_entry=entry, queue_ordinal=queue_ordinal
    )
    reuse_receipt = (
        None
        if provisional_reuse_receipt is None
        else copy.deepcopy(dict(provisional_reuse_receipt))
    )
    if reuse_receipt is not None:
        reuse_content = {
            key: item
            for key, item in reuse_receipt.items()
            if key != "receipt_sha256"
        }
        if (
            not _is_sha256(reuse_receipt.get("receipt_sha256"))
            or reuse_receipt["receipt_sha256"] != _sha256(reuse_content)
        ):
            raise ValueError("provisional reuse receipt is invalid")
    receipt = copy.deepcopy(dict(disposition_receipt))
    source_fingerprint_sha256 = entry["source_fingerprint_sha256"]
    supplied_fingerprint = receipt.get("source_fingerprint_sha256")
    if (
        supplied_fingerprint is not None
        and supplied_fingerprint != source_fingerprint_sha256
    ):
        raise ValueError("promotion disposition source fingerprint is invalid")
    receipt.update(
        {
            "source_fingerprint_sha256": source_fingerprint_sha256,
            "retained_promoted_stage_sha256": supplied_stage_sha256,
            "execution_mode": execution_mode,
            "admission_state": "AWAITING_ADMISSION",
        }
    )
    stage_ledger = result["promoted_stage_ledger"]
    assert isinstance(stage_ledger, dict)
    ordinal_key = str(queue_ordinal)
    bucket = stage_ledger.setdefault(ordinal_key, {})
    if not isinstance(bucket, dict):
        raise ValueError("promoted stage ledger ordinal is invalid")
    leaf_id = str(entry["leaf_id"])
    existing_stage = bucket.get(leaf_id)
    if existing_stage is not None and existing_stage != stage:
        if not (
            isinstance(existing_stage, Mapping)
            and existing_stage.get("admission_state")
            in {"NUMERICAL_CONTINUATION", "CALCULATED_PENDING_DERIVATION"}
        ):
            raise ValueError("conflicting retained promoted stage")
    _require_replaced_promoted_stage(existing_stage, stage)
    bucket[leaf_id] = stage
    for ledger_field, payload, schema in (
        (
            "promoted_background_ledger",
            promoted_background,
            "windows-solver.promoted-background-ledger-entry/1",
        ),
        (
            "promoted_root_ledger",
            promoted_root,
            "windows-solver.promoted-root-ledger-entry/1",
        ),
    ):
        if payload is None:
            continue
        if not isinstance(payload, Mapping):
            raise ValueError(f"{ledger_field} payload is invalid")
        _retain_promoted_auxiliary_entry(
            result,
            ledger_field=ledger_field,
            queue_ordinal=queue_ordinal,
            leaf_id=leaf_id,
            payload=payload,
            schema=schema,
        )
    entry["retained_promoted_stage_sha256"] = supplied_stage_sha256
    entry["disposition"] = PromotionQueueDisposition.AWAITING_ADMISSION.value
    entry["disposition_receipt_sha256"] = _sha256(receipt)
    entry["provisional_reuse_receipt"] = reuse_receipt
    entry["provisional_reuse_receipt_sha256"] = (
        None if reuse_receipt is None else reuse_receipt["receipt_sha256"]
    )
    _assert_layer1_guard(layer1_guard, result)
    return result


def retain_promoted_terminal_reduction(
    checkpoint: Mapping[str, object],
    *,
    queue_ordinal: int,
    promoted_stage: Mapping[str, object],
    disposition: PromotionQueueDisposition | str,
    disposition_receipt: Mapping[str, object],
    layer1_guard: object | None = None,
) -> dict[str, object]:
    """Retain a checkpoint-reduced numerical terminal without admitting it."""

    result = validate_schema11_checkpoint(checkpoint)
    terminal = _enum_value(
        disposition, PromotionQueueDisposition, "promotion reduction disposition"
    )
    if terminal not in {
        PromotionQueueDisposition.UNRESOLVED.value,
        PromotionQueueDisposition.DEFERRED.value,
        PromotionQueueDisposition.REJECTED.value,
    }:
        raise ValueError("promoted numerical reduction disposition is invalid")
    entries = result["promotion_queue"]["entries"]
    if (
        isinstance(queue_ordinal, bool)
        or not isinstance(queue_ordinal, int)
        or queue_ordinal < 0
        or queue_ordinal >= len(entries)
    ):
        raise ValueError("promotion queue ordinal is invalid")
    entry = entries[queue_ordinal]
    stage = copy.deepcopy(dict(promoted_stage))
    content = {key: item for key, item in stage.items() if key != "stage_sha256"}
    if (
        entry["disposition"]
        != PromotionQueueDisposition.CALCULATED_PENDING_DERIVATION.value
        or stage.get("stage_sha256") != _sha256(content)
        or stage.get("leaf_id") != entry["leaf_id"]
        or stage.get("queue_ordinal") != queue_ordinal
        or stage.get("admission_state") != terminal
    ):
        raise ValueError("promoted terminal reduction stage is invalid")
    _authenticate_promoted_stage_chain(
        stage, queue_entry=entry, queue_ordinal=queue_ordinal
    )
    receipt = copy.deepcopy(dict(disposition_receipt))
    receipt.update({
        "source_fingerprint_sha256": entry["source_fingerprint_sha256"],
        "retained_promoted_stage_sha256": stage["stage_sha256"],
        "admission_state": terminal,
    })
    bucket = result["promoted_stage_ledger"].setdefault(str(queue_ordinal), {})
    if not isinstance(bucket, dict):
        raise ValueError("promoted stage ledger ordinal is invalid")
    _require_replaced_promoted_stage(bucket.get(str(entry["leaf_id"])), stage)
    bucket[str(entry["leaf_id"])] = stage
    entry["retained_promoted_stage_sha256"] = stage["stage_sha256"]
    entry["disposition"] = terminal
    entry["disposition_receipt_sha256"] = _sha256(receipt)
    _assert_layer1_guard(layer1_guard, result)
    return result


def finish_promotion(
    checkpoint: Mapping[str, object],
    *,
    queue_ordinal: int,
    disposition: PromotionQueueDisposition | str,
    disposition_receipt: Mapping[str, object],
    provisional_reuse_receipt: Mapping[str, object] | None = None,
    layer1_guard: object | None = None,
) -> dict[str, object]:
    result = validate_schema11_checkpoint(checkpoint)
    disposition_value = _enum_value(
        disposition, PromotionQueueDisposition, "promotion queue disposition"
    )
    if disposition_value == PromotionQueueDisposition.AWAITING_ADMISSION.value:
        raise ValueError(
            "AWAITING_ADMISSION requires retained promoted calculation"
        )
    if disposition_value in {
        PromotionQueueDisposition.UNRESOLVED.value,
        PromotionQueueDisposition.DEFERRED.value,
        PromotionQueueDisposition.REJECTED.value,
    }:
        raise ValueError(
            "UNRESOLVED/DEFERRED/REJECTED require a typed retained authority stage"
        )
    if disposition_value not in TERMINAL_PROMOTION_DISPOSITIONS:
        raise ValueError("promotion completion requires a terminal disposition")
    queue = result["promotion_queue"]
    assert isinstance(queue, dict)
    entries = queue["entries"]
    assert isinstance(entries, list)
    if (
        isinstance(queue_ordinal, bool)
        or not isinstance(queue_ordinal, int)
        or queue_ordinal < 0
        or queue_ordinal >= len(entries)
    ):
        raise ValueError("promotion queue ordinal is invalid")
    entry = entries[queue_ordinal]
    if entry["queue_ordinal"] != queue_ordinal:
        raise ValueError("promotion queue order is invalid")
    if entry["disposition"] != PromotionQueueDisposition.PENDING.value:
        raise ValueError("promotion queue entry is already terminal")
    receipt = copy.deepcopy(dict(disposition_receipt))
    source_fingerprint_sha256 = entry["source_fingerprint_sha256"]
    supplied_fingerprint = receipt.get("source_fingerprint_sha256")
    if (
        supplied_fingerprint is not None
        and supplied_fingerprint != source_fingerprint_sha256
    ):
        raise ValueError("promotion disposition source fingerprint is invalid")
    receipt["source_fingerprint_sha256"] = source_fingerprint_sha256
    reuse_receipt = (
        None
        if provisional_reuse_receipt is None
        else copy.deepcopy(dict(provisional_reuse_receipt))
    )
    if reuse_receipt is not None:
        supplied = reuse_receipt.get("receipt_sha256")
        content = {
            key: item for key, item in reuse_receipt.items()
            if key != "receipt_sha256"
        }
        if not _is_sha256(supplied) or supplied != _sha256(content):
            raise ValueError("provisional reuse receipt is invalid")
    continuation_sha256 = entry["retained_promoted_stage_sha256"]
    if continuation_sha256 is not None:
        stage_ledger = result["promoted_stage_ledger"]
        assert isinstance(stage_ledger, dict)
        bucket = stage_ledger.get(str(queue_ordinal))
        stage = (
            bucket.get(str(entry["leaf_id"]))
            if isinstance(bucket, dict)
            else None
        )
        if (
            not isinstance(stage, Mapping)
            or stage.get("stage_sha256") != continuation_sha256
            or stage.get("admission_state") != "NUMERICAL_CONTINUATION"
        ):
            raise ValueError("promotion continuation stage is invalid")
        del bucket[str(entry["leaf_id"])]
        if not bucket:
            del stage_ledger[str(queue_ordinal)]
        entry["retained_promoted_stage_sha256"] = None
    entry["disposition"] = disposition_value
    entry["disposition_receipt_sha256"] = _sha256(receipt)
    entry["provisional_reuse_receipt"] = reuse_receipt
    entry["provisional_reuse_receipt_sha256"] = (
        None if reuse_receipt is None else reuse_receipt["receipt_sha256"]
    )
    _assert_layer1_guard(layer1_guard, result)
    return result


def complete_promoted_admission(
    checkpoint: Mapping[str, object],
    *,
    queue_ordinal: int,
    admission_receipt: Mapping[str, object],
    layer1_guard: object | None = None,
) -> dict[str, object]:
    """Durably stage an admitted record before any external publication."""

    result = validate_schema11_checkpoint(checkpoint)
    queue = result["promotion_queue"]
    assert isinstance(queue, dict)
    entries = queue["entries"]
    assert isinstance(entries, list)
    if (
        isinstance(queue_ordinal, bool)
        or not isinstance(queue_ordinal, int)
        or queue_ordinal < 0
        or queue_ordinal >= len(entries)
    ):
        raise ValueError("promotion queue ordinal is invalid")
    entry = entries[queue_ordinal]
    if (
        entry["queue_ordinal"] != queue_ordinal
        or entry["disposition"]
        != PromotionQueueDisposition.AWAITING_ADMISSION.value
        or not _is_sha256(entry["retained_promoted_stage_sha256"])
    ):
        raise ValueError("promotion queue entry is not awaiting admission")
    receipt = copy.deepcopy(dict(admission_receipt))
    if (
        receipt.get("queue_ordinal") != queue_ordinal
        or receipt.get("leaf_id") != entry["leaf_id"]
        or receipt.get("retained_promoted_stage_sha256")
        != entry["retained_promoted_stage_sha256"]
        or receipt.get("source_fingerprint_sha256")
        != entry["source_fingerprint_sha256"]
    ):
        raise ValueError("promotion admission receipt binding is invalid")
    receipt["source_fingerprint_sha256"] = entry["source_fingerprint_sha256"]
    entry["disposition"] = (
        PromotionQueueDisposition.ADMITTED_PENDING_PUBLICATION.value
    )
    entry["disposition_receipt_sha256"] = _sha256(receipt)
    _assert_layer1_guard(layer1_guard, result)
    return result


def complete_promoted_publication(
    checkpoint: Mapping[str, object],
    *,
    queue_ordinal: int,
    admission_receipt: Mapping[str, object],
    publication_receipt: Mapping[str, object],
    layer1_guard: object | None = None,
) -> dict[str, object]:
    """Commit authenticated publication after the admitted record is durable."""

    result = validate_schema11_checkpoint(checkpoint)
    entries = result["promotion_queue"]["entries"]
    if (
        isinstance(queue_ordinal, bool)
        or not isinstance(queue_ordinal, int)
        or queue_ordinal < 0
        or queue_ordinal >= len(entries)
    ):
        raise ValueError("promotion queue ordinal is invalid")
    entry = entries[queue_ordinal]
    review = copy.deepcopy(dict(admission_receipt))
    publication = copy.deepcopy(dict(publication_receipt))
    if (
        entry["disposition"]
        != PromotionQueueDisposition.ADMITTED_PENDING_PUBLICATION.value
        or entry["disposition_receipt_sha256"] != _sha256(review)
        or review.get("queue_ordinal") != queue_ordinal
        or review.get("leaf_id") != entry["leaf_id"]
        or review.get("retained_promoted_stage_sha256")
        != entry["retained_promoted_stage_sha256"]
        or review.get("source_fingerprint_sha256")
        != entry["source_fingerprint_sha256"]
    ):
        raise ValueError("promoted publication admission binding is invalid")
    matching_records = [
        item for item in result["records"] if item.get("leaf_id") == entry["leaf_id"]
    ]
    if len(matching_records) != 1:
        raise ValueError("promoted publication admitted record is missing")
    record = matching_records[0]
    record_sha256 = record.get("record_sha256")
    if not _is_sha256(record_sha256):
        raise ValueError("promoted publication admitted record is invalid")
    publication_content = {
        "schema": "windows-solver.promoted-publication-completion/1",
        "queue_ordinal": queue_ordinal,
        "leaf_id": entry["leaf_id"],
        "retained_promoted_stage_sha256": entry[
            "retained_promoted_stage_sha256"
        ],
        "source_fingerprint_sha256": entry["source_fingerprint_sha256"],
        "admitted_record_sha256": record_sha256,
        "review_receipt_sha256": review.get("receipt_sha256"),
        "publication_receipt": publication,
        "publication_receipt_sha256": _sha256(publication),
    }
    completion_receipt = {
        **publication_content,
        "receipt_sha256": _sha256(publication_content),
    }
    evidence = result["evidence_ledger"].get(str(entry["leaf_id"]))
    if not isinstance(evidence, Mapping):
        raise ValueError("promoted publication evidence is missing")
    result = record_evidence(
        result,
        leaf_id=str(entry["leaf_id"]),
        central_record_sha256=str(record_sha256),
        central_stage_sha256=str(evidence["central_stage_sha256"]),
        evidence_level=EvidenceLevel.SCREENED,
        receipts=(completion_receipt,),
    )
    retained_stage = result["promoted_stage_ledger"][str(queue_ordinal)][
        str(entry["leaf_id"])
    ]
    previous_pass = result["survey_pass_ledger"][SurveyPass.PROMOTED.value].get(
        str(entry["leaf_id"])
    )
    if not isinstance(previous_pass, Mapping):
        raise ValueError("promoted publication calculation disposition is missing")
    result = record_survey_disposition(
        result,
        survey_pass=SurveyPass.PROMOTED,
        leaf_id=str(entry["leaf_id"]),
        disposition=SurveyDisposition.COMPLETED,
        source_record_sha256=entry["source_record_sha256"],
        result_record_sha256=str(record_sha256),
        operation_identity="promoted-independent-review-admission/v1",
        precision_tiers=tuple(retained_stage.get("precision_tiers", ())),
        reason_code="PUBLISHED_AFTER_DURABLE_ADMISSION",
        sample_count=int(previous_pass["sample_count"]),
        sample_limit=int(previous_pass["sample_limit"]),
        root_read_count=int(previous_pass["root_read_count"]),
        root_read_limit=int(previous_pass["root_read_limit"]),
        worker_launch_count=int(previous_pass["worker_launch_count"]),
        worker_launch_limit=int(previous_pass["worker_launch_limit"]),
        tier_timing=tuple(previous_pass["tier_timing"]),
        session_fragments=tuple(previous_pass["session_fragments"]),
        layer1_guard=layer1_guard,
    )
    completed_entry = result["promotion_queue"]["entries"][queue_ordinal]
    completed_entry["disposition"] = PromotionQueueDisposition.COMPLETED.value
    completed_entry["disposition_receipt_sha256"] = completion_receipt[
        "receipt_sha256"
    ]
    _assert_layer1_guard(layer1_guard, result)
    return result


def _contains_fixed_root_v2_artifact(value: object) -> bool:
    if isinstance(value, Mapping):
        if value.get("schema") in {
            "windows-solver.fixed-root-survey-batch/2",
            "windows-solver.fixed-root-survey-batch-response/2",
            "windows-solver.fixed-root-survey-conditioning/2",
        }:
            return True
        return any(_contains_fixed_root_v2_artifact(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_fixed_root_v2_artifact(item) for item in value)
    return False


def _migrate_fixed_root_v2_forensic_history(
    result: dict[str, object],
) -> None:
    """Retire `/2` exterior authority without replaying upstream work."""

    queue = result.get("promotion_queue")
    stages = result.get("promoted_stage_ledger")
    forensic = result.get("forensic_fixed_root_v2_history")
    pass_ledgers = result.get("survey_pass_ledger")
    backgrounds = result.get("promoted_background_ledger")
    if (
        not isinstance(queue, Mapping)
        or not isinstance(queue.get("entries"), list)
        or not isinstance(stages, dict)
        or not isinstance(forensic, dict)
        or not isinstance(pass_ledgers, Mapping)
        or not isinstance(pass_ledgers.get("promoted"), dict)
        or not isinstance(backgrounds, dict)
    ):
        return
    entries = queue["entries"]
    for ordinal_key in list(stages):
        bucket = stages.get(ordinal_key)
        if not isinstance(ordinal_key, str) or not ordinal_key.isdigit() or not isinstance(bucket, dict):
            continue
        ordinal = int(ordinal_key)
        if ordinal >= len(entries) or not isinstance(entries[ordinal], dict):
            continue
        entry = entries[ordinal]
        for leaf_id in list(bucket):
            stage = bucket.get(leaf_id)
            if not isinstance(stage, Mapping) or not _contains_fixed_root_v2_artifact(stage):
                continue
            stage_content = {
                name: item for name, item in stage.items() if name != "stage_sha256"
            }
            stage_sha256 = stage.get("stage_sha256")
            if (
                stage_sha256 != _sha256(stage_content)
                or entry.get("leaf_id") != leaf_id
                or entry.get("retained_promoted_stage_sha256") != stage_sha256
            ):
                raise ValueError("fixed-root /2 forensic source is unauthenticated")
            promoted_pass = pass_ledgers["promoted"].pop(leaf_id, None)
            background_bucket = backgrounds.get(ordinal_key)
            promoted_background = None
            if isinstance(background_bucket, dict):
                promoted_background = background_bucket.pop(leaf_id, None)
                if not background_bucket:
                    backgrounds.pop(ordinal_key, None)
            history_content = {
                "schema": "windows-solver.fixed-root-v2-forensic-history/1",
                "authority": "FORENSIC_ONLY",
                "migration_reason": "FIXED_ROOT_ENDPOINT_RECOVERY_V3_REQUIRED",
                "queue_ordinal": ordinal,
                "leaf_id": leaf_id,
                "source_stage_sha256": stage_sha256,
                "source_stage": copy.deepcopy(dict(stage)),
                "source_promoted_pass": copy.deepcopy(promoted_pass),
                "source_promoted_background": copy.deepcopy(promoted_background),
            }
            history_content["history_sha256"] = _sha256(history_content)
            forensic[f"{ordinal}:{leaf_id}"] = history_content
            bucket.pop(leaf_id)
            entry["minimum_requested_tier"] = "BF40"
            entry["disposition"] = PromotionQueueDisposition.PENDING.value
            entry["disposition_receipt_sha256"] = None
            entry["retained_promoted_stage_sha256"] = None
            result["state"] = "PARTIAL"
        if not bucket:
            stages.pop(ordinal_key, None)

    # Checkpoint mutators validate their input before appending their own
    # ledger entry.  A `/2` stage can therefore be retired on one validation
    # boundary and have its associated promoted pass/background supplied by
    # the immediately following mutator.  Reconcile those late-arriving
    # records into the already-created forensic entry so they can never regain
    # current `/3` authority.
    for history in forensic.values():
        if not isinstance(history, dict):
            continue
        ordinal = history.get("queue_ordinal")
        leaf_id = history.get("leaf_id")
        if (
            isinstance(ordinal, bool)
            or not isinstance(ordinal, int)
            or not isinstance(leaf_id, str)
        ):
            continue
        promoted_pass = pass_ledgers["promoted"].pop(leaf_id, None)
        background_bucket = backgrounds.get(str(ordinal))
        promoted_background = None
        if isinstance(background_bucket, dict):
            promoted_background = background_bucket.pop(leaf_id, None)
            if not background_bucket:
                backgrounds.pop(str(ordinal), None)
        changed = False
        if promoted_pass is not None:
            history["source_promoted_pass"] = copy.deepcopy(promoted_pass)
            changed = True
        if promoted_background is not None:
            history["source_promoted_background"] = copy.deepcopy(
                promoted_background
            )
            changed = True
        if changed:
            history["history_sha256"] = _sha256({
                name: item for name, item in history.items()
                if name != "history_sha256"
            })


def validate_schema11_checkpoint(
    value: Mapping[str, object],
) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) not in {
        frozenset(_SCHEMA11_BASE_FIELDS),
        frozenset(_SCHEMA11_PRE_PR75_FIELDS),
        frozenset(_SCHEMA11_FIELDS),
    }:
        raise ValueError("schema-11 checkpoint envelope fields are invalid")
    result = copy.deepcopy(dict(value))
    if set(result) == _SCHEMA11_BASE_FIELDS:
        result.update({field: {} for field in _SCHEMA11_LAYER2_LEDGER_FIELDS})
        result["forensic_fixed_root_v2_history"] = {}
    elif set(result) == _SCHEMA11_PRE_PR75_FIELDS:
        result["forensic_fixed_root_v2_history"] = {}
    if result["schema_version"] != CAMPAIGN_CHECKPOINT_SCHEMA_VERSION:
        raise ValueError("campaign checkpoint is not schema 11")
    _migrate_fixed_root_v2_forensic_history(result)
    if not isinstance(result["campaign_id"], str) or not result["campaign_id"]:
        raise ValueError("schema-11 campaign_id is invalid")
    if not isinstance(result["selection_id"], str) or not result["selection_id"]:
        raise ValueError("schema-11 selection_id is invalid")
    if result["state"] not in {"PARTIAL", "COMPLETE"}:
        raise ValueError("schema-11 campaign state is invalid")
    records = result["records"]
    if not isinstance(records, list):
        raise ValueError("schema-11 records must be an array")
    validated_records = [_validated_record(item) for item in records]
    leaf_ids = [item["leaf_id"] for item in validated_records]
    if len(leaf_ids) != len(set(leaf_ids)):
        raise ValueError("schema-11 numerical record leaf IDs are not unique")
    result["records"] = validated_records

    evidence = result["evidence_ledger"]
    if not isinstance(evidence, dict):
        raise ValueError("schema-11 evidence ledger is invalid")
    record_hashes = {item["leaf_id"]: item["record_sha256"] for item in validated_records}
    for leaf_id, entry in evidence.items():
        if not isinstance(leaf_id, str) or not isinstance(entry, Mapping):
            raise ValueError("schema-11 evidence entry is invalid")
        if set(entry) != {
            "leaf_id",
            "central_record_sha256",
            "central_stage_sha256",
            "evidence_level",
            "receipts",
            "discrepancy_codes",
        }:
            raise ValueError("schema-11 evidence entry fields are invalid")
        if (
            entry["leaf_id"] != leaf_id
            or record_hashes.get(leaf_id) != entry["central_record_sha256"]
        ):
            raise ValueError("schema-11 evidence entry does not bind a record")
        _enum_value(entry["evidence_level"], EvidenceLevel, "evidence level")
        if not _is_sha256(entry["central_stage_sha256"]):
            raise ValueError("schema-11 evidence stage digest is invalid")
        if not isinstance(entry["receipts"], list) or not isinstance(
            entry["discrepancy_codes"], list
        ):
            raise ValueError("schema-11 evidence collections are invalid")

    pass_ledgers = result["survey_pass_ledger"]
    if not isinstance(pass_ledgers, dict) or set(pass_ledgers) != {"binary64", "promoted"}:
        raise ValueError("schema-11 survey pass ledger is invalid")
    for pass_name, pass_ledger in pass_ledgers.items():
        if not isinstance(pass_ledger, dict):
            raise ValueError("schema-11 survey pass entries are invalid")
        allowed = (
            BINARY64_SURVEY_DISPOSITIONS
            if pass_name == "binary64"
            else PROMOTED_SURVEY_DISPOSITIONS
        )
        for leaf_id, entry in pass_ledger.items():
            if not isinstance(entry, Mapping) or set(entry) != _PASS_ENTRY_FIELDS:
                raise ValueError("schema-11 survey pass entry fields are invalid")
            if (
                entry["leaf_id"] != leaf_id
                or entry["pass"] != pass_name
                or entry["disposition"] not in allowed
            ):
                raise ValueError("schema-11 survey pass entry identity is invalid")
            receipt_hash = entry["disposition_receipt_sha256"]
            content = {
                key: item
                for key, item in entry.items()
                if key != "disposition_receipt_sha256"
            }
            if receipt_hash != _sha256(content):
                raise ValueError("schema-11 survey disposition receipt is invalid")
            validated_timing, validated_fragments = _validated_pass_timing(
                leaf_id=leaf_id,
                pass_value=pass_name,
                tier_timing=entry["tier_timing"],
                session_fragments=entry["session_fragments"],
            )
            if (
                entry["tier_timing"] != validated_timing
                or entry["session_fragments"] != validated_fragments
            ):
                raise ValueError("schema-11 survey timing is not canonical")

    queue = result["promotion_queue"]
    if (
        not isinstance(queue, dict)
        or set(queue) != {"schema", "entries"}
        or queue["schema"] != PROMOTION_QUEUE_SCHEMA
        or not isinstance(queue["entries"], list)
    ):
        raise ValueError("schema-11 promotion queue is invalid")
    for ordinal, entry in enumerate(queue["entries"]):
        if not isinstance(entry, Mapping) or entry.get("queue_ordinal") != ordinal:
            raise ValueError("schema-11 promotion queue order is invalid")
        entry_fields = set(entry)
        if entry_fields == _PROMOTION_ENTRY_FIELDS:
            # Accept pre-PR68 queue entries at the checkpoint boundary and
            # normalize the new durable provenance fields to explicit nulls.
            normalized = copy.deepcopy(dict(entry))
            normalized.update({
                "provisional_stage": None,
                "provisional_stage_sha256": None,
                "provisional_operation_identity": None,
                "source_binary64_disposition_receipt_sha256": None,
                "provisional_reuse_receipt": None,
                "provisional_reuse_receipt_sha256": None,
            })
            normalized["source_fingerprint_sha256"] = (
                promotion_source_fingerprint_sha256(normalized)
            )
            queue["entries"][ordinal] = normalized
            entry = normalized
        elif entry_fields == (
            _PROMOTION_ENTRY_PRE_FINGERPRINT_FIELDS
            - {"provisional_reuse_receipt", "provisional_reuse_receipt_sha256"}
        ):
            normalized = copy.deepcopy(dict(entry))
            normalized.update({
                "provisional_reuse_receipt": None,
                "provisional_reuse_receipt_sha256": None,
            })
            normalized["source_fingerprint_sha256"] = (
                promotion_source_fingerprint_sha256(normalized)
            )
            queue["entries"][ordinal] = normalized
            entry = normalized
        elif entry_fields == _PROMOTION_ENTRY_PRE_FINGERPRINT_FIELDS:
            normalized = copy.deepcopy(dict(entry))
            normalized["source_fingerprint_sha256"] = (
                promotion_source_fingerprint_sha256(normalized)
            )
            queue["entries"][ordinal] = normalized
            entry = normalized
        elif entry_fields != _PROMOTION_ENTRY_PROVISIONAL_FIELDS and (
            entry_fields != _PROMOTION_ENTRY_LAYER2_FIELDS
        ):
            raise ValueError("schema-11 promotion queue entry fields are invalid")
        if set(entry) == _PROMOTION_ENTRY_PROVISIONAL_FIELDS:
            normalized = copy.deepcopy(dict(entry))
            normalized.update({
                "retained_promoted_stage_sha256": None,
            })
            queue["entries"][ordinal] = normalized
            entry = normalized
        if (
            not isinstance(entry["leaf_id"], str)
            or not entry["leaf_id"]
            or entry["source_pass"] != SurveyPass.BINARY64.value
            or not isinstance(entry["reason_code"], str)
            or not entry["reason_code"]
            or not isinstance(entry["minimum_requested_tier"], str)
            or not entry["minimum_requested_tier"]
            or not _is_sha256(entry["scientific_computation_identity"])
        ):
            raise ValueError("schema-11 promotion queue entry identity is invalid")
        for digest in (
            entry["source_record_sha256"],
            entry["source_stage_sha256"],
            entry["source_root_seal_sha256"],
            entry["provisional_stage_sha256"],
            entry["source_binary64_disposition_receipt_sha256"],
            entry["provisional_reuse_receipt_sha256"],
            entry["retained_promoted_stage_sha256"],
        ):
            if digest is not None and not _is_sha256(digest):
                raise ValueError("schema-11 promotion queue source digest is invalid")
        provisional = entry["provisional_stage"]
        if provisional is None:
            if (
                entry["provisional_stage_sha256"] is not None
                or entry["provisional_operation_identity"] is not None
            ):
                raise ValueError("schema-11 promotion provisional stage is incomplete")
        else:
            if not isinstance(provisional, Mapping):
                raise ValueError("schema-11 promotion provisional stage is invalid")
            provisional_content = {
                key: item
                for key, item in provisional.items()
                if key != "stage_sha256"
            }
            if (
                provisional.get("stage_sha256")
                != entry["provisional_stage_sha256"]
                or entry["provisional_stage_sha256"] != _sha256(provisional_content)
                or provisional.get("operation_identity")
                != entry["provisional_operation_identity"]
                or entry["source_stage_sha256"]
                != entry["provisional_stage_sha256"]
                or entry["source_record_sha256"] is not None
            ):
                raise ValueError("schema-11 promotion provisional stage binding is invalid")
        reuse_receipt = entry["provisional_reuse_receipt"]
        reuse_digest = entry["provisional_reuse_receipt_sha256"]
        if reuse_receipt is None:
            if reuse_digest is not None:
                raise ValueError("schema-11 provisional reuse receipt is incomplete")
        elif not isinstance(reuse_receipt, Mapping):
            raise ValueError("schema-11 provisional reuse receipt is invalid")
        else:
            reuse_content = {
                key: item for key, item in reuse_receipt.items()
                if key != "receipt_sha256"
            }
            if (
                reuse_receipt.get("receipt_sha256") != reuse_digest
                or reuse_digest != _sha256(reuse_content)
            ):
                raise ValueError("schema-11 provisional reuse receipt is invalid")
        retained_promoted_stage_sha256 = entry["retained_promoted_stage_sha256"]
        _enum_value(entry.get("queue_kind"), PromotionQueueKind, "promotion queue kind")
        disposition = _enum_value(
            entry.get("disposition"),
            PromotionQueueDisposition,
            "promotion queue disposition",
        )
        receipt_hash = entry.get("disposition_receipt_sha256")
        if disposition == PromotionQueueDisposition.PENDING.value:
            if receipt_hash is not None:
                raise ValueError("pending promotion cannot have a terminal receipt")
        elif not _is_sha256(receipt_hash):
            raise ValueError("terminal promotion requires a receipt digest")
        if disposition in {
            PromotionQueueDisposition.CALCULATED_PENDING_DERIVATION.value,
            PromotionQueueDisposition.CONTROL_RETURN_RETAINED.value,
            PromotionQueueDisposition.CONTROL_DECISION_RETAINED.value,
            PromotionQueueDisposition.NUMERICAL_CONTINUATION.value,
            PromotionQueueDisposition.AWAITING_ADMISSION.value,
            PromotionQueueDisposition.ADMITTED_PENDING_PUBLICATION.value,
        } and retained_promoted_stage_sha256 is None:
            raise ValueError(
                "retained promotion state requires a retained calculation"
            )
        # This digest is derived provenance, not an independently trusted
        # input.  Recompute it at the checkpoint boundary so a malformed
        # legacy checkpoint reaches the scheduler's durable failure path;
        # the authenticated Layer-1 lock still rejects any source mutation.
        entry["source_fingerprint_sha256"] = promotion_source_fingerprint_sha256(
            entry
        )

    queue_entries = queue["entries"]
    assert isinstance(queue_entries, list)
    stage_ledger = result["promoted_stage_ledger"]
    if not isinstance(stage_ledger, dict):
        raise ValueError("schema-11 promoted stage ledger is invalid")
    seen_stages: set[tuple[int, str]] = set()
    for ordinal_key, bucket in stage_ledger.items():
        if (
            not isinstance(ordinal_key, str)
            or not ordinal_key.isdigit()
            or str(int(ordinal_key)) != ordinal_key
            or not isinstance(bucket, Mapping)
        ):
            raise ValueError("schema-11 promoted stage ledger key is invalid")
        ordinal = int(ordinal_key)
        if ordinal >= len(queue_entries):
            raise ValueError("schema-11 promoted stage ledger ordinal is invalid")
        queue_entry = queue_entries[ordinal]
        for leaf_id, stage in bucket.items():
            if (
                not isinstance(leaf_id, str)
                or not isinstance(stage, Mapping)
                or queue_entry["leaf_id"] != leaf_id
                or stage.get("leaf_id") != leaf_id
                or stage.get("queue_ordinal") != ordinal
            ):
                raise ValueError("schema-11 promoted stage ledger binding is invalid")
            content = {
                key: item for key, item in stage.items() if key != "stage_sha256"
            }
            stage_sha256 = stage.get("stage_sha256")
            admission_state = stage.get("admission_state")
            valid_terminal_stage = (
                admission_state == "AWAITING_ADMISSION"
                and queue_entry["disposition"]
                in {
                    PromotionQueueDisposition.AWAITING_ADMISSION.value,
                    PromotionQueueDisposition.ADMITTED_PENDING_PUBLICATION.value,
                    PromotionQueueDisposition.COMPLETED.value,
                }
            )
            valid_continuation_stage = (
                admission_state == "NUMERICAL_CONTINUATION"
                and queue_entry["disposition"]
                == PromotionQueueDisposition.NUMERICAL_CONTINUATION.value
                and stage.get("schema")
                == PROMOTED_CONTROL_CONTINUATION_STAGE_SCHEMA
                and stage.get("next_precision_tier") == "BF80"
                and stage.get("precision_tiers") == ["BF40"]
            )
            raw_artifact = stage.get("calculation_artifact")
            valid_raw_stage = (
                admission_state == "CALCULATED_PENDING_DERIVATION"
                and queue_entry["disposition"]
                == PromotionQueueDisposition.CALCULATED_PENDING_DERIVATION.value
                and stage.get("schema") == PROMOTED_CALCULATION_STAGE_SCHEMA
                and isinstance(raw_artifact, Mapping)
            )
            valid_control_return_stage = (
                admission_state
                == PromotionQueueDisposition.CONTROL_RETURN_RETAINED.value
                and queue_entry["disposition"]
                == PromotionQueueDisposition.CONTROL_RETURN_RETAINED.value
                and stage.get("schema") == PROMOTED_CONTROL_RETURN_STAGE_SCHEMA
            )
            valid_control_decision_stage = (
                admission_state
                == PromotionQueueDisposition.CONTROL_DECISION_RETAINED.value
                and stage.get("schema") == PROMOTED_CONTROL_DECISION_STAGE_SCHEMA
                and queue_entry["disposition"]
                in {
                    PromotionQueueDisposition.CONTROL_DECISION_RETAINED.value,
                    PromotionQueueDisposition.UNRESOLVED.value,
                    PromotionQueueDisposition.DEFERRED.value,
                    PromotionQueueDisposition.REJECTED.value,
                }
            )
            valid_policy_terminal_stage = (
                admission_state
                in {
                    PromotionQueueDisposition.UNRESOLVED.value,
                    PromotionQueueDisposition.DEFERRED.value,
                    PromotionQueueDisposition.REJECTED.value,
                }
                and queue_entry["disposition"] == admission_state
                and stage.get("schema") == PROMOTED_POLICY_TERMINAL_STAGE_SCHEMA
                and stage.get("execution_mode") == "BLOCK_ALL"
            )
            valid_reduced_numerical_terminal = (
                admission_state
                in {
                    PromotionQueueDisposition.UNRESOLVED.value,
                    PromotionQueueDisposition.DEFERRED.value,
                    PromotionQueueDisposition.REJECTED.value,
                }
                and queue_entry["disposition"] == admission_state
                and stage.get("schema") == PROMOTED_CALCULATION_STAGE_SCHEMA
            )
            if (
                not _is_sha256(stage_sha256)
                or stage_sha256 != _sha256(content)
                or queue_entry["retained_promoted_stage_sha256"] != stage_sha256
                or stage.get("execution_mode") not in _PROMOTED_EXECUTION_MODES
                or not (
                    valid_terminal_stage
                    or valid_continuation_stage
                    or valid_raw_stage
                    or valid_control_return_stage
                    or valid_control_decision_stage
                    or valid_policy_terminal_stage
                    or valid_reduced_numerical_terminal
                )
            ):
                raise ValueError("schema-11 retained promoted stage is invalid")
            _authenticate_promoted_stage_chain(
                stage, queue_entry=queue_entry, queue_ordinal=ordinal
            )
            if valid_control_decision_stage and queue_entry["disposition"] in {
                PromotionQueueDisposition.UNRESOLVED.value,
                PromotionQueueDisposition.DEFERRED.value,
                PromotionQueueDisposition.REJECTED.value,
            }:
                expected_terminal_receipt = (
                    promoted_control_terminal_disposition_receipt(
                        queue_entry,
                        stage,
                    )
                )
                if (
                    _control_outcome_kind(stage.get("control_decision"))
                    != queue_entry["disposition"]
                    or queue_entry["disposition_receipt_sha256"]
                    != _sha256(expected_terminal_receipt)
                ):
                    raise ValueError(
                        "CONTROL terminal disposition proof is invalid"
                    )
                promoted_pass = pass_ledgers[SurveyPass.PROMOTED.value].get(
                    leaf_id
                )
                if (
                    promoted_pass is not None
                    and promoted_pass.get("disposition")
                    != queue_entry["disposition"]
                ):
                    raise ValueError(
                        "CONTROL terminal survey disposition is invalid"
                    )
            if valid_policy_terminal_stage:
                expected_policy_receipt = (
                    promoted_policy_terminal_disposition_receipt(
                        queue_entry,
                        stage,
                    )
                )
                if queue_entry["disposition_receipt_sha256"] != _sha256(
                    expected_policy_receipt
                ):
                    raise ValueError(
                        "policy terminal disposition proof is invalid"
                    )
                promoted_pass = pass_ledgers[SurveyPass.PROMOTED.value].get(
                    leaf_id
                )
                if (
                    promoted_pass is not None
                    and promoted_pass.get("disposition")
                    != queue_entry["disposition"]
                ):
                    raise ValueError(
                        "policy terminal survey disposition is invalid"
                    )
            seen_stages.add((ordinal, leaf_id))
    for ordinal, queue_entry in enumerate(queue_entries):
        pointer = queue_entry["retained_promoted_stage_sha256"]
        if (
            queue_entry["disposition"]
            in {
                PromotionQueueDisposition.UNRESOLVED.value,
                PromotionQueueDisposition.DEFERRED.value,
                PromotionQueueDisposition.REJECTED.value,
            }
            and pointer is None
        ):
            raise ValueError(
                "current terminal disposition lacks its retained authority stage"
            )
        if pointer is not None and (ordinal, str(queue_entry["leaf_id"])) not in seen_stages:
            raise ValueError("schema-11 retained promoted stage pointer is dangling")

    for field in ("promoted_background_ledger", "promoted_root_ledger"):
        ledger = result[field]
        if not isinstance(ledger, dict):
            raise ValueError(f"schema-11 {field} is invalid")
        for ordinal_key, bucket in ledger.items():
            if (
                not isinstance(ordinal_key, str)
                or not ordinal_key.isdigit()
                or str(int(ordinal_key)) != ordinal_key
                or not isinstance(bucket, Mapping)
            ):
                raise ValueError(f"schema-11 {field} key is invalid")
            ordinal = int(ordinal_key)
            if ordinal >= len(queue_entries):
                raise ValueError(f"schema-11 {field} ordinal is invalid")
            queue_entry = queue_entries[ordinal]
            for leaf_id, ledger_entry in bucket.items():
                if (
                    not isinstance(leaf_id, str)
                    or not isinstance(ledger_entry, Mapping)
                    or ledger_entry.get("leaf_id") != leaf_id
                    or ledger_entry.get("queue_ordinal") != ordinal
                    or queue_entry["leaf_id"] != leaf_id
                ):
                    raise ValueError(f"schema-11 {field} binding is invalid")
                content = {
                    key: item
                    for key, item in ledger_entry.items()
                    if key != "ledger_entry_sha256"
                }
                if (
                    not _is_sha256(ledger_entry.get("ledger_entry_sha256"))
                    or ledger_entry["ledger_entry_sha256"] != _sha256(content)
                ):
                    raise ValueError(f"schema-11 {field} digest is invalid")

    for field in ("attempts", "system_failures", "recovery_receipts"):
        if not isinstance(result[field], list):
            raise ValueError(f"schema-11 {field} must be an array")
    forensic = result["forensic_fixed_root_v2_history"]
    if not isinstance(forensic, dict):
        raise ValueError("schema-11 fixed-root forensic history is invalid")
    for key, history in forensic.items():
        if (
            not isinstance(key, str)
            or not isinstance(history, Mapping)
            or set(history) != {
                "schema", "authority", "migration_reason", "queue_ordinal",
                "leaf_id", "source_stage_sha256", "source_stage",
                "source_promoted_pass", "source_promoted_background",
                "history_sha256",
            }
            or history.get("schema")
            != "windows-solver.fixed-root-v2-forensic-history/1"
            or history.get("authority") != "FORENSIC_ONLY"
            or history.get("migration_reason")
            != "FIXED_ROOT_ENDPOINT_RECOVERY_V3_REQUIRED"
            or history.get("history_sha256") != _sha256({
                name: item for name, item in history.items()
                if name != "history_sha256"
            })
            or not _is_sha256(history.get("source_stage_sha256"))
            or not _contains_fixed_root_v2_artifact(history.get("source_stage"))
        ):
            raise ValueError("schema-11 fixed-root forensic history is invalid")
    report = result["report_status_receipt"]
    if report is not None and not isinstance(report, Mapping):
        raise ValueError("schema-11 report status receipt is invalid")
    return result


__all__ = [
    "BINARY64_SURVEY_DISPOSITIONS",
    "CAMPAIGN_CHECKPOINT_SCHEMA_VERSION",
    "EvidenceLevel",
    "ExecutionProfile",
    "NUMERICAL_RECORD_STATES",
    "PROMOTED_CALCULATION_STAGE_SCHEMA",
    "PROMOTED_CONTROL_CONTINUATION_PROOF_SCHEMA",
    "PROMOTED_CONTROL_CONTINUATION_STAGE_SCHEMA",
    "PROMOTED_CONTROL_DECISION_SCHEMA",
    "PROMOTED_CONTROL_DECISION_STAGE_SCHEMA",
    "PROMOTED_CONTROL_RETURN_SCHEMA",
    "PROMOTED_CONTROL_RETURN_STAGE_SCHEMA",
    "PROMOTED_CONTROL_TERMINAL_RECEIPT_SCHEMA",
    "PROMOTED_HORIZON_CONTROL_DECISION_SCHEMA",
    "PROMOTED_HORIZON_CONTROL_RETURN_SCHEMA",
    "PROMOTED_POLICY_TERMINAL_DECISION_SCHEMA",
    "PROMOTED_POLICY_TERMINAL_RECEIPT_SCHEMA",
    "PROMOTED_POLICY_TERMINAL_STAGE_SCHEMA",
    "PROMOTED_SURVEY_DISPOSITIONS",
    "PROMOTION_QUEUE_SCHEMA",
    "PromotionQueueDisposition",
    "PromotionQueueKind",
    "SurveyDisposition",
    "SurveyPass",
    "add_numerical_record",
    "append_promotion",
    "complete_promoted_admission",
    "complete_promoted_publication",
    "empty_schema11_checkpoint",
    "finish_promotion",
    "promoted_artifact_digest",
    "promoted_control_terminal_disposition_receipt",
    "promoted_policy_terminal_disposition_receipt",
    "promotion_source_fingerprint_sha256",
    "record_evidence",
    "record_survey_disposition",
    "retain_promoted_background",
    "retain_promoted_calculation",
    "retain_promoted_continuation",
    "retain_promoted_control_decision",
    "retain_promoted_control_return",
    "retain_promoted_control_terminal",
    "retain_promoted_policy_terminal",
    "retain_promoted_raw_calculation",
    "retain_promoted_terminal_reduction",
    "validate_schema11_checkpoint",
]
