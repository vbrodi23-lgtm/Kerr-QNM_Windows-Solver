"""Zero-numerics admission of independently reviewed promoted calculations."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Callable, Mapping

from .campaign_policy import (
    EvidenceLevel,
    SurveyDisposition,
    SurveyPass,
    add_numerical_record,
    complete_promoted_admission,
    record_evidence,
    record_survey_disposition,
    validate_schema11_checkpoint,
)
from .contracts import canonical_json_bytes
from .promoted_control_calibration import load_default_calibration_receipt


INDEPENDENT_PROMOTED_REVIEW_RECEIPT_SCHEMA = (
    "windows-solver.independent-promoted-review-receipt/1"
)
_REVIEW_FIELDS = {
    "schema",
    "decision",
    "authority_sha256",
    "reviewed_at_utc",
    "binary64_lock_receipt_sha256",
    "calibration_receipt_sha256",
    "queue_ordinal",
    "leaf_id",
    "route",
    "scientific_computation_identity",
    "retained_promoted_stage_sha256",
    "source_fingerprint_sha256",
    "disagreement_term_sha256s",
    "receipt_sha256",
}


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


@dataclass(frozen=True, slots=True)
class PromotedAdmissionResult:
    checkpoint: dict[str, object]
    queue_ordinal: int
    leaf_id: str
    admitted_record_sha256: str
    review_receipt_sha256: str
    backend_call_count: int = 0
    julia_launch_count: int = 0
    root_read_count: int = 0
    determinant_evaluation_count: int = 0
    binary64_evaluation_count: int = 0


@dataclass(frozen=True, slots=True)
class PromotedAdmissionReduction:
    """Solver-owned reduction of retained work after review authorisation."""

    record: Mapping[str, object]
    evidence_receipts: tuple[Mapping[str, object], ...] = ()


def _validated_review_receipt(
    value: Mapping[str, object],
    *,
    expected_authority_sha256: str,
) -> dict[str, object]:
    if not _is_sha256(expected_authority_sha256):
        raise ValueError("expected independent-review authority is invalid")
    if not isinstance(value, Mapping) or set(value) != _REVIEW_FIELDS:
        raise ValueError("independent review receipt fields are invalid")
    receipt = json.loads(canonical_json_bytes(dict(value)))
    content = {
        key: item for key, item in receipt.items() if key != "receipt_sha256"
    }
    if (
        receipt["schema"] != INDEPENDENT_PROMOTED_REVIEW_RECEIPT_SCHEMA
        or receipt["decision"] != "ADMIT_SCREENED"
        or receipt["authority_sha256"] != expected_authority_sha256
        or not isinstance(receipt["reviewed_at_utc"], str)
        or not receipt["reviewed_at_utc"]
        or not _is_sha256(receipt["receipt_sha256"])
        or receipt["receipt_sha256"] != _sha256(content)
    ):
        raise ValueError("independent review receipt authentication is invalid")
    if any(
        not _is_sha256(receipt[name])
        for name in (
            "binary64_lock_receipt_sha256",
            "calibration_receipt_sha256",
            "retained_promoted_stage_sha256",
            "source_fingerprint_sha256",
        )
    ) or not isinstance(receipt["disagreement_term_sha256s"], list) or any(
        not _is_sha256(item) for item in receipt["disagreement_term_sha256s"]
    ):
        raise ValueError("independent review receipt bindings are invalid")
    return receipt


def _solver_owned_retained_record(
    retained_stage: Mapping[str, object],
) -> dict[str, object]:
    """Recover only the record already reduced by solver-owned code."""

    record = retained_stage.get("retained_record")
    if not isinstance(record, Mapping):
        raise ValueError("retained promoted stage has no solver-owned record")
    return json.loads(canonical_json_bytes(dict(record)))


def _terminal_stage_sha256(
    record: Mapping[str, object],
    retained_stage: Mapping[str, object],
) -> str:
    stages = record.get("stages")
    if not isinstance(stages, list) or not stages or not isinstance(stages[-1], Mapping):
        raise ValueError("solver-owned admitted record stages are invalid")
    stage_sha256 = stages[-1].get("stage_sha256")
    if not _is_sha256(stage_sha256):
        raise ValueError("solver-owned admitted record stage is invalid")
    retained_stage_sha256 = retained_stage.get("retained_record_stage_sha256")
    if retained_stage_sha256 is not None and retained_stage_sha256 != stage_sha256:
        raise ValueError("solver-owned admitted record diverges from retained stage")
    return str(stage_sha256)


def _normalise_reduction(
    value: Mapping[str, object] | PromotedAdmissionReduction,
) -> PromotedAdmissionReduction:
    if isinstance(value, PromotedAdmissionReduction):
        record = value.record
        receipts = value.evidence_receipts
    else:
        record = value
        receipts = ()
    if not isinstance(record, Mapping) or not all(
        isinstance(receipt, Mapping) for receipt in receipts
    ):
        raise ValueError("solver-owned promoted reduction returned invalid data")
    return PromotedAdmissionReduction(
        record=json.loads(canonical_json_bytes(dict(record))),
        evidence_receipts=tuple(
            json.loads(canonical_json_bytes(dict(receipt)))
            for receipt in receipts
        ),
    )


def admit_retained_promoted_work(
    checkpoint: Mapping[str, object],
    *,
    queue_ordinal: int,
    independent_review_receipt: Mapping[str, object],
    layer1_guard: object | None = None,
    record_reducer: Callable[
        [Mapping[str, object], Mapping[str, object]],
        Mapping[str, object] | PromotedAdmissionReduction,
    ] | None = None,
) -> PromotedAdmissionResult:
    """Admit one retained stage using hashes and policy only; run no numerics."""

    result = validate_schema11_checkpoint(checkpoint)
    queue = result["promotion_queue"]
    if (
        isinstance(queue_ordinal, bool)
        or not isinstance(queue_ordinal, int)
        or queue_ordinal < 0
        or queue_ordinal >= len(queue["entries"])
    ):
        raise ValueError("independent review receipt queue ordinal is invalid")
    entry = queue["entries"][queue_ordinal]
    leaf_id = str(entry["leaf_id"])
    stage_bucket = result["promoted_stage_ledger"].get(str(queue_ordinal))
    retained_stage = (
        stage_bucket.get(leaf_id) if isinstance(stage_bucket, Mapping) else None
    )
    if not isinstance(retained_stage, Mapping):
        raise ValueError("independent review receipt retained stage is missing")
    calibration_receipt = load_default_calibration_receipt()
    if retained_stage.get("calibration_receipt_sha256") != calibration_receipt.sha256:
        raise ValueError("retained promoted stage calibration receipt mismatch")
    receipt = _validated_review_receipt(
        independent_review_receipt,
        expected_authority_sha256=(
            calibration_receipt.independent_review_authority_sha256
        ),
    )
    disagreement_terms = retained_stage.get("current_run_disagreement_terms")
    if not isinstance(disagreement_terms, list):
        raise ValueError("independent review receipt disagreement terms are missing")
    expected_disagreement_sha256s = [_sha256(item) for item in disagreement_terms]
    if (
        entry["disposition"] != "AWAITING_ADMISSION"
        or receipt["queue_ordinal"] != queue_ordinal
        or receipt["leaf_id"] != leaf_id
        or receipt["route"] != retained_stage.get("route")
        or receipt["scientific_computation_identity"]
        != entry["scientific_computation_identity"]
        or receipt["scientific_computation_identity"]
        != retained_stage.get("scientific_computation_identity")
        or receipt["retained_promoted_stage_sha256"]
        != retained_stage.get("stage_sha256")
        or receipt["retained_promoted_stage_sha256"]
        != entry["retained_promoted_stage_sha256"]
        or receipt["calibration_receipt_sha256"]
        != retained_stage.get("calibration_receipt_sha256")
        or receipt["binary64_lock_receipt_sha256"]
        != retained_stage.get("layer1_lock_receipt_sha256")
        or receipt["source_fingerprint_sha256"]
        != entry["source_fingerprint_sha256"]
        or receipt["source_fingerprint_sha256"]
        != retained_stage.get("source_fingerprint_sha256")
        or receipt["disagreement_term_sha256s"]
        != expected_disagreement_sha256s
    ):
        raise ValueError("independent review receipt binding is invalid")
    reduction = _normalise_reduction(
        _solver_owned_retained_record(retained_stage)
        if record_reducer is None
        else record_reducer(retained_stage, receipt)
    )
    record = reduction.record
    central_stage_sha256 = _terminal_stage_sha256(record, retained_stage)

    result = add_numerical_record(result, record)
    record_sha256 = str(record["record_sha256"])
    result = record_evidence(
        result,
        leaf_id=leaf_id,
        central_record_sha256=record_sha256,
        central_stage_sha256=central_stage_sha256,
        evidence_level=EvidenceLevel.SCREENED,
        receipts=(receipt, *reduction.evidence_receipts),
    )
    result = complete_promoted_admission(
        result,
        queue_ordinal=queue_ordinal,
        admission_receipt=receipt,
        layer1_guard=layer1_guard,
    )
    result = record_survey_disposition(
        result,
        survey_pass=SurveyPass.PROMOTED,
        leaf_id=leaf_id,
        disposition=SurveyDisposition.COMPLETED,
        source_record_sha256=entry["source_record_sha256"],
        result_record_sha256=record_sha256,
        operation_identity="promoted-independent-review-admission/v1",
        precision_tiers=tuple(retained_stage.get("precision_tiers", ())),
        reason_code="ADMITTED_AFTER_INDEPENDENT_REVIEW",
        sample_count=0,
        sample_limit=0,
        root_read_count=0,
        root_read_limit=0,
        worker_launch_count=0,
        worker_launch_limit=0,
        tier_timing=(),
        session_fragments=(),
        layer1_guard=layer1_guard,
    )
    return PromotedAdmissionResult(
        checkpoint=validate_schema11_checkpoint(result),
        queue_ordinal=queue_ordinal,
        leaf_id=leaf_id,
        admitted_record_sha256=record_sha256,
        review_receipt_sha256=str(receipt["receipt_sha256"]),
    )


def _load_canonical_checkpoint(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("promoted admission checkpoint is unreadable") from error
    if not isinstance(value, Mapping) or canonical_json_bytes(value) != raw:
        raise ValueError("promoted admission checkpoint is not canonical")
    return validate_schema11_checkpoint(value)


def _write_atomic(path: Path, checkpoint: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json_bytes(dict(checkpoint)))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def admit_retained_promoted_checkpoint(
    checkpoint_path: Path | str,
    *,
    queue_ordinal: int,
    independent_review_receipt: Mapping[str, object],
    layer1_guard: object | None = None,
    terminal_record_committed: Callable[[Mapping[str, object]], None] | None = None,
    record_reducer: Callable[
        [Mapping[str, object], Mapping[str, object]],
        Mapping[str, object] | PromotedAdmissionReduction,
    ] | None = None,
) -> PromotedAdmissionResult:
    """Publish one reviewed result, then atomically persist its admission."""

    path = Path(checkpoint_path)
    checkpoint = _load_canonical_checkpoint(path)
    admitted = admit_retained_promoted_work(
        checkpoint,
        queue_ordinal=queue_ordinal,
        independent_review_receipt=independent_review_receipt,
        layer1_guard=layer1_guard,
        record_reducer=record_reducer,
    )
    if layer1_guard is not None:
        layer1_guard.pre_write(admitted.checkpoint)
    if terminal_record_committed is not None:
        record = next(
            item
            for item in admitted.checkpoint["records"]
            if item["leaf_id"] == admitted.leaf_id
        )
        terminal_record_committed(record)
    _write_atomic(path, admitted.checkpoint)
    durable = _load_canonical_checkpoint(path)
    if layer1_guard is not None:
        layer1_guard.post_write(durable)
    durable_result = PromotedAdmissionResult(
        checkpoint=durable,
        queue_ordinal=admitted.queue_ordinal,
        leaf_id=admitted.leaf_id,
        admitted_record_sha256=admitted.admitted_record_sha256,
        review_receipt_sha256=admitted.review_receipt_sha256,
        binary64_evaluation_count=admitted.binary64_evaluation_count,
    )
    if layer1_guard is not None:
        layer1_guard.post_callback(durable)
    return durable_result


__all__ = [
    "INDEPENDENT_PROMOTED_REVIEW_RECEIPT_SCHEMA",
    "PromotedAdmissionReduction",
    "PromotedAdmissionResult",
    "admit_retained_promoted_checkpoint",
    "admit_retained_promoted_work",
]
