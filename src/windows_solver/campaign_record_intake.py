"""Single mixed-version intake owner for authenticated campaign records."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import math
from pathlib import Path
from typing import Mapping

from .campaign_policy import validate_schema11_checkpoint
from .contracts import canonical_json_bytes
from .response_batches import (
    forensic_v2_scientific_computation_identity_sha256,
    scientific_computation_identity_sha256,
    validate_campaign_recovery_record,
    validate_schema11_horizon_record_for_scientific_identity,
)
from .response_engine import BINARY64_HORIZON_OPERATION_V3, ComponentResult
from .root_evidence import AuthenticatedRootEvidence
from .structural_diagnostics import StructuralDiagnosticSession


_SCHEMA11_NUMERICAL_RECORD = "windows-solver.schema11-numerical-record/1"
_FORENSIC_ARCHIVE_SCHEMA = "windows-solver.forensic-record-archive/1"
_V2_HORIZON_OPERATION = "binary64-horizon-production/v2"
HORIZON_RESPONSE_V2_SCIENTIFICALLY_STALE = (
    "HORIZON_RESPONSE_V2_SCIENTIFICALLY_STALE"
)


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


class CampaignRecordScientificStatus(StrEnum):
    CURRENT = "CURRENT"
    FORENSIC_V2_STALE = "FORENSIC_V2_STALE"
    MIXED_V2_V3_INVALID = "MIXED_V2_V3_INVALID"
    INCOMPATIBLE = "INCOMPATIBLE"
    CORRUPT = "CORRUPT"


@dataclass(frozen=True, slots=True)
class CampaignRecordIntake:
    record: Mapping[str, object]
    scientific_status: CampaignRecordScientificStatus
    response_admissible: bool
    forensic_only: bool
    reason_code: str | None
    root_seed: AuthenticatedRootEvidence | None


class CampaignRecordIntakeFailure(ValueError):
    """Fatal intake result retaining its exact scientific classification."""

    def __init__(
        self,
        status: CampaignRecordScientificStatus,
        reason_code: str,
        detail: str,
    ) -> None:
        self.intake_status = status
        self.reason_code = reason_code
        super().__init__(f"{status.value}: {reason_code}: {detail}")


def _leaf_for(plan: object, leaf_id: str) -> object:
    leaf = next(
        (item for item in getattr(plan, "leaves", ()) if item.leaf_id == leaf_id),
        None,
    )
    if leaf is None:
        raise CampaignRecordIntakeFailure(
            CampaignRecordScientificStatus.INCOMPATIBLE,
            "LEAF_OUTSIDE_CURRENT_PLAN",
            "record leaf is outside the current campaign plan",
        )
    return leaf


def _stage_operations(record: Mapping[str, object]) -> frozenset[str]:
    stages = record.get("stages")
    if not isinstance(stages, list) or not stages:
        raise ValueError("schema-11 record stages are invalid")
    operations: set[str] = set()
    for stage in stages:
        if not isinstance(stage, Mapping):
            raise ValueError("schema-11 record stage is invalid")
        operation = stage.get("operation_identity")
        if not isinstance(operation, str) or not operation:
            raise ValueError("schema-11 record operation identity is invalid")
        operations.add(operation)
    return frozenset(operations)


def _forensic_v2_root_seed(
    leaf: object, record: Mapping[str, object]
) -> AuthenticatedRootEvidence:
    stages = record["stages"]
    assert isinstance(stages, list)
    source_stage = next(
        stage
        for stage in stages
        if isinstance(stage, Mapping)
        and stage.get("operation_identity") == _V2_HORIZON_OPERATION
    )
    payload = source_stage.get("component_result")
    raw_result = payload.get("result") if isinstance(payload, Mapping) else None
    if not isinstance(raw_result, Mapping):
        raise ValueError("forensic predecessor root component is missing")
    result = ComponentResult.from_mapping(raw_result)
    if result.to_mapping() != raw_result:
        raise ValueError("forensic predecessor root component is not canonical")
    baseline = result.baseline
    job = leaf.job
    expected_source_mapping = (
        None
        if job.source_root_mapping is None
        else dict(job.source_root_mapping)
    )
    if (
        baseline.root_reference_id != job.root.root_reference_id
        or baseline.branch_id != job.root.branch_id
        or baseline.equation_id != job.equation_id
        or baseline.source_root_mapping != expected_source_mapping
        or not math.isfinite(baseline.omega.real)
        or not math.isfinite(baseline.omega.imag)
    ):
        raise ValueError("forensic predecessor root binding is invalid")
    record_sha256 = record.get("record_sha256")
    if not isinstance(record_sha256, str):
        raise ValueError("forensic predecessor record digest is invalid")
    return AuthenticatedRootEvidence.from_seal(
        leaf,
        fixed_root=baseline.omega,
        branch_identity=baseline.branch_id,
        source_receipt_sha256=record_sha256,
    )


def _corrupt(error: BaseException) -> CampaignRecordIntakeFailure:
    return CampaignRecordIntakeFailure(
        CampaignRecordScientificStatus.CORRUPT,
        "RECORD_AUTHENTICATION_FAILED",
        str(error),
    )


def assess_campaign_record_for_current_runtime(
    plan: object,
    leaf_id: str,
    record: Mapping[str, object],
) -> CampaignRecordIntake:
    """Authenticate history first, then decide response and root admissibility."""

    if not isinstance(record, Mapping):
        raise _corrupt(ValueError("campaign record is not an object"))
    leaf = _leaf_for(plan, leaf_id)
    canonical_record = copy.deepcopy(dict(record))
    if canonical_record.get("schema") != _SCHEMA11_NUMERICAL_RECORD:
        try:
            validate_campaign_recovery_record(plan, leaf_id, canonical_record)
        except (TypeError, ValueError) as error:
            raise _corrupt(error) from error
        return CampaignRecordIntake(
            canonical_record,
            CampaignRecordScientificStatus.CURRENT,
            True,
            False,
            None,
            None,
        )

    try:
        operations = _stage_operations(canonical_record)
    except (TypeError, ValueError) as error:
        raise _corrupt(error) from error
    contains_forensic_operation = _V2_HORIZON_OPERATION in operations
    has_v3 = BINARY64_HORIZON_OPERATION_V3 in operations
    legacy_identity = None
    if getattr(leaf, "mechanism_id", None) == "horizon-admittance":
        legacy_identity = forensic_v2_scientific_computation_identity_sha256(
            plan, leaf
        )

    if contains_forensic_operation and has_v3:
        observed_identity = canonical_record.get("scientific_computation_identity")
        allowed_identities = {
            scientific_computation_identity_sha256(plan, leaf),
            legacy_identity,
        }
        if observed_identity not in allowed_identities:
            raise _corrupt(ValueError("mixed horizon identity is unauthenticated"))
        try:
            validate_schema11_horizon_record_for_scientific_identity(
                plan,
                leaf,
                canonical_record,
                expected_scientific_identity=str(observed_identity),
                allow_mixed_binary64_operations=True,
            )
        except (TypeError, ValueError) as error:
            raise _corrupt(error) from error
        raise CampaignRecordIntakeFailure(
            CampaignRecordScientificStatus.MIXED_V2_V3_INVALID,
            "HORIZON_RESPONSE_MIXED_V2_V3_INVALID",
            "record contains mixed predecessor and current horizon response stages",
        )

    if contains_forensic_operation:
        if legacy_identity is None:
            raise _corrupt(
                ValueError(
                    "forensic predecessor operation is bound to a non-horizon leaf"
                )
            )
        try:
            validate_schema11_horizon_record_for_scientific_identity(
                plan,
                leaf,
                canonical_record,
                expected_scientific_identity=legacy_identity,
            )
            root_seed = _forensic_v2_root_seed(leaf, canonical_record)
        except (TypeError, ValueError, StopIteration) as error:
            raise _corrupt(error) from error
        return CampaignRecordIntake(
            canonical_record,
            CampaignRecordScientificStatus.FORENSIC_V2_STALE,
            False,
            True,
            HORIZON_RESPONSE_V2_SCIENTIFICALLY_STALE,
            root_seed,
        )

    try:
        validate_campaign_recovery_record(plan, leaf_id, canonical_record)
    except (TypeError, ValueError) as current_error:
        observed_identity = canonical_record.get("scientific_computation_identity")
        if (
            legacy_identity is not None
            and observed_identity == legacy_identity
            and has_v3
        ):
            try:
                validate_schema11_horizon_record_for_scientific_identity(
                    plan,
                    leaf,
                    canonical_record,
                    expected_scientific_identity=legacy_identity,
                )
            except (TypeError, ValueError) as error:
                raise _corrupt(error) from error
            return CampaignRecordIntake(
                canonical_record,
                CampaignRecordScientificStatus.INCOMPATIBLE,
                False,
                False,
                "SCIENTIFIC_COMPUTATION_IDENTITY_STALE",
                None,
            )
        raise _corrupt(current_error) from current_error
    return CampaignRecordIntake(
        canonical_record,
        CampaignRecordScientificStatus.CURRENT,
        True,
        False,
        None,
        None,
    )


def emit_forensic_record_excluded(
    diagnostic_session: StructuralDiagnosticSession | None,
    intake: CampaignRecordIntake,
    *,
    leaf_id: str,
    source_kind: str,
    source_path: str | Path,
    stale_cache_hit_prevented: bool,
) -> None:
    """Emit the one canonical structural event for a forensic exclusion."""

    if (
        diagnostic_session is None
        or intake.scientific_status
        is not CampaignRecordScientificStatus.FORENSIC_V2_STALE
    ):
        return
    record_sha256 = intake.record.get("record_sha256")
    diagnostic_session.append(
        "FORENSIC_RECORD_EXCLUDED",
        leaf={"leaf_id": leaf_id},
        transition={
            "next_state": "EXCLUDED",
            "reason_code": intake.reason_code,
        },
        connections={
            "source_record_sha256": record_sha256,
            "root_seal_sha256": (
                None
                if intake.root_seed is None
                else intake.root_seed.root_seal_sha256
            ),
        },
        compact_diagnostics={
            "source_kind": source_kind,
            "source_path": str(source_path),
            "scientific_status": intake.scientific_status.value,
            "reason_code": intake.reason_code,
            "current_response_admissible": False,
            "root_seed_salvaged": intake.root_seed is not None,
            "stale_cache_hit_prevented": stale_cache_hit_prevented,
        },
        durable=True,
    )


def archive_excluded_record_in_checkpoint(
    checkpoint: Mapping[str, object],
    intake: CampaignRecordIntake,
    *,
    source_path: str | Path,
) -> dict[str, object]:
    """Move excluded evidence from current ledgers into an authenticated archive."""

    result = validate_schema11_checkpoint(checkpoint)
    leaf_id = intake.record.get("leaf_id")
    record_sha256 = intake.record.get("record_sha256")
    if not isinstance(leaf_id, str) or not isinstance(record_sha256, str):
        raise ValueError("excluded record archive identity is invalid")
    result["records"] = [
        item
        for item in result["records"]
        if not (
            item.get("leaf_id") == leaf_id
            and item.get("record_sha256") == record_sha256
        )
    ]
    result["evidence_ledger"].pop(leaf_id, None)
    for ledger in result["survey_pass_ledger"].values():
        ledger.pop(leaf_id, None)
    entries = [
        item
        for item in result["promotion_queue"]["entries"]
        if item.get("leaf_id") != leaf_id
    ]
    for ordinal, entry in enumerate(entries):
        entry["queue_ordinal"] = ordinal
    result["promotion_queue"]["entries"] = entries
    for field in ("attempts", "system_failures"):
        result[field] = [
            item
            for item in result[field]
            if not isinstance(item, Mapping) or item.get("leaf_id") != leaf_id
        ]
    archive_content = {
        "schema": _FORENSIC_ARCHIVE_SCHEMA,
        "source_path": str(source_path),
        "leaf_id": leaf_id,
        "record_sha256": record_sha256,
        "scientific_status": intake.scientific_status.value,
        "reason_code": intake.reason_code,
        "current_response_admissible": intake.response_admissible,
        "root_seed": (
            None if intake.root_seed is None else intake.root_seed.to_mapping()
        ),
        "record": copy.deepcopy(dict(intake.record)),
    }
    archive = {**archive_content, "receipt_sha256": _sha256(archive_content)}
    if not any(
        isinstance(item, Mapping)
        and item.get("schema") == _FORENSIC_ARCHIVE_SCHEMA
        and item.get("record_sha256") == record_sha256
        for item in result["recovery_receipts"]
    ):
        result["recovery_receipts"].append(archive)
    result["report_status_receipt"] = None
    result["state"] = "PARTIAL"
    return validate_schema11_checkpoint(result)


__all__ = [
    "CampaignRecordIntake",
    "CampaignRecordIntakeFailure",
    "CampaignRecordScientificStatus",
    "HORIZON_RESPONSE_V2_SCIENTIFICALLY_STALE",
    "archive_excluded_record_in_checkpoint",
    "assess_campaign_record_for_current_runtime",
    "emit_forensic_record_excluded",
]
