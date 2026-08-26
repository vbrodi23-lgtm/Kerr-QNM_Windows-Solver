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


CAMPAIGN_CHECKPOINT_SCHEMA_VERSION = 11
PROMOTION_QUEUE_SCHEMA = "windows-solver.m02-promotion-queue/1"


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
    if item is not PromotionQueueDisposition.PENDING
)

_EVIDENCE_RANK = {
    EvidenceLevel.SCREENED.value: 1,
    EvidenceLevel.CERTIFIED.value: 2,
    EvidenceLevel.VALIDATED.value: 3,
}
_SCHEMA11_FIELDS = {
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
        "queue_ordinal": len(entries),
        "disposition": PromotionQueueDisposition.PENDING.value,
        "disposition_receipt_sha256": None,
    }
    entry["source_fingerprint_sha256"] = promotion_source_fingerprint_sha256(entry)
    entries.append(entry)
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
    entry["disposition"] = disposition_value
    entry["disposition_receipt_sha256"] = _sha256(receipt)
    entry["provisional_reuse_receipt"] = reuse_receipt
    entry["provisional_reuse_receipt_sha256"] = (
        None if reuse_receipt is None else reuse_receipt["receipt_sha256"]
    )
    _assert_layer1_guard(layer1_guard, result)
    return result


def validate_schema11_checkpoint(
    value: Mapping[str, object],
) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _SCHEMA11_FIELDS:
        raise ValueError("schema-11 checkpoint envelope fields are invalid")
    result = copy.deepcopy(dict(value))
    if result["schema_version"] != CAMPAIGN_CHECKPOINT_SCHEMA_VERSION:
        raise ValueError("campaign checkpoint is not schema 11")
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
        elif entry_fields != _PROMOTION_ENTRY_PROVISIONAL_FIELDS:
            raise ValueError("schema-11 promotion queue entry fields are invalid")
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
        if entry["source_fingerprint_sha256"] != promotion_source_fingerprint_sha256(
            entry
        ):
            raise ValueError("schema-11 promotion source fingerprint is invalid")

    for field in ("attempts", "system_failures", "recovery_receipts"):
        if not isinstance(result[field], list):
            raise ValueError(f"schema-11 {field} must be an array")
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
    "PROMOTED_SURVEY_DISPOSITIONS",
    "PROMOTION_QUEUE_SCHEMA",
    "PromotionQueueDisposition",
    "PromotionQueueKind",
    "SurveyDisposition",
    "SurveyPass",
    "add_numerical_record",
    "append_promotion",
    "empty_schema11_checkpoint",
    "finish_promotion",
    "promotion_source_fingerprint_sha256",
    "record_evidence",
    "record_survey_disposition",
    "validate_schema11_checkpoint",
]
