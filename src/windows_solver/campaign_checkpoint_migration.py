"""Authenticated schema-7 to schema-8 campaign checkpoint migration."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Mapping

from .contracts import canonical_json_bytes
from .response_batches import (
    CAMPAIGN_CHECKPOINT_SCHEMA_VERSION,
    CampaignLeafRecord,
    CampaignPlan,
    CampaignStageRecord,
    _checkpoint_mapping,
    _load_checkpoint_with_attempts,
)

CAMPAIGN_MIGRATION_SCHEMA = "windows-solver.campaign-checkpoint-migration/1"
_SOURCE_SCHEMA_VERSION = 7
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_ENDPOINT_POLICY_KEYS = frozenset({
    "endpoint_policy_identity",
    "horizon_endpoint_recovery_policy_identity",
    "policy_identity",
})


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate source checkpoint JSON key: {key}")
        result[key] = value
    return result


def _authenticated_source(path: Path, expected_sha256: str) -> bytes:
    if not _HEX_64.fullmatch(expected_sha256):
        raise ValueError("expected source checkpoint SHA-256 is invalid")
    source_bytes = path.read_bytes()
    if hashlib.sha256(source_bytes).hexdigest() != expected_sha256:
        raise ValueError("source checkpoint SHA-256 mismatch")
    try:
        value = json.loads(
            source_bytes,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda item: (_ for _ in ()).throw(
                ValueError(
                    f"source checkpoint contains non-finite constant {item}"
                )
            ),
        )
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError("source checkpoint is not canonical JSON") from error
    if not isinstance(value, Mapping) or source_bytes != canonical_json_bytes(value):
        raise ValueError("source checkpoint bytes are not canonical")
    if value.get("schema_version") != _SOURCE_SCHEMA_VERSION:
        raise ValueError("source checkpoint must use historical schema 7")
    return source_bytes


def _stage_new_file(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".migration-stage.tmp",
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise
    return Path(temporary_name)


def _install_staged_file(staged: Path, target: Path) -> None:
    """Atomically publish one staged file without replacing operator data."""

    try:
        os.link(staged, target)
    except FileExistsError as error:
        raise ValueError(
            "campaign checkpoint migration destination already exists"
        ) from error
    staged.unlink()


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _install_staged_pair(
    staged_checkpoint: Path,
    checkpoint: Path,
    staged_receipt: Path,
    receipt: Path,
) -> None:
    """Publish receipt then checkpoint, rolling back either partial install."""

    installed_receipt = False
    installed_checkpoint = False
    try:
        _install_staged_file(staged_receipt, receipt)
        installed_receipt = True
        _install_staged_file(staged_checkpoint, checkpoint)
        installed_checkpoint = True
        _fsync_directory(receipt.parent)
        if checkpoint.parent != receipt.parent:
            _fsync_directory(checkpoint.parent)
    except BaseException:
        if installed_checkpoint:
            checkpoint.unlink(missing_ok=True)
        if installed_receipt:
            receipt.unlink(missing_ok=True)
        raise


def _recheck_source(path: Path, authenticated_bytes: bytes) -> None:
    if path.read_bytes() != authenticated_bytes:
        raise RuntimeError("source checkpoint changed during migration")


def _endpoint_policy_matches(
    value: object, changes: Mapping[str, str]
) -> frozenset[str]:
    matches: set[str] = set()

    def visit(item: object) -> None:
        if isinstance(item, Mapping):
            for key, nested in item.items():
                if (
                    key in _ENDPOINT_POLICY_KEYS
                    and isinstance(nested, str)
                    and nested in changes
                ):
                    matches.add(nested)
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)

    visit(value)
    return frozenset(matches)


def _record_prefix(
    record: CampaignLeafRecord, stages: tuple[CampaignStageRecord, ...]
) -> CampaignLeafRecord | None:
    if not stages:
        return None
    return CampaignLeafRecord(
        leaf_id=record.leaf_id,
        role=record.role,
        state="IN_PROGRESS",
        stages=stages,
        trigger_ids=record.trigger_ids,
        sentinel=record.sentinel,
        missing_precision_digits=None,
        sentinel_comparison=None,
    )


@dataclass(frozen=True, slots=True)
class CampaignCheckpointMigrationResult:
    source_checkpoint_sha256: str
    destination_checkpoint_sha256: str
    migration_receipt_sha256: str
    retained_record_count: int
    invalidated_evidence_count: int


def migrate_campaign_checkpoint(
    source_path: str | os.PathLike[str],
    destination_path: str | os.PathLike[str],
    *,
    plan: CampaignPlan,
    expected_source_sha256: str,
    changed_endpoint_policy_identities: Mapping[str, str],
    migration_receipt_path: str | os.PathLike[str] | None = None,
) -> CampaignCheckpointMigrationResult:
    """Create a normal resumable schema-8 checkpoint and a sidecar receipt."""

    source = Path(source_path)
    destination = Path(destination_path)
    receipt_path = (
        Path(migration_receipt_path)
        if migration_receipt_path is not None
        else destination.with_name(f"{destination.name}.migration-receipt.json")
    )
    if source.resolve() == destination.resolve():
        raise ValueError("campaign checkpoint migration requires a new destination")
    if destination.exists() or receipt_path.exists():
        raise ValueError("campaign checkpoint migration destination already exists")
    source_bytes = _authenticated_source(source, expected_source_sha256)
    selection, records, attempts, _, _ = _load_checkpoint_with_attempts(
        plan, source
    )

    changes = dict(changed_endpoint_policy_identities)
    if any(
        not isinstance(old, str)
        or not isinstance(new, str)
        or not old
        or not new
        or old == new
        for old, new in changes.items()
    ):
        raise ValueError("changed endpoint policy identities are invalid")

    retained_records: list[CampaignLeafRecord] = []
    invalidated: list[dict[str, object]] = []
    affected_leaf_ids: set[str] = set()
    for record in records:
        retained_stages = list(record.stages)
        for index, stage in enumerate(record.stages):
            matches = _endpoint_policy_matches(stage.to_mapping(), changes)
            promoted_component_identity_changed = stage.outcome.digits > 64
            if not matches and not promoted_component_identity_changed:
                continue
            affected_leaf_ids.add(record.leaf_id)
            retained_stages = list(record.stages[:index])
            invalidated.append({
                "evidence_kind": "campaign-stage-suffix",
                "leaf_id": record.leaf_id,
                "first_invalidated_stage_index": index,
                "old_endpoint_policy_identities": sorted(matches),
                "reason": (
                    "ENDPOINT_POLICY_IDENTITY_CHANGED"
                    if matches
                    else "SCHEMA7_PROMOTED_COMPONENT_IDENTITY_CHANGED"
                ),
            })
            break
        migrated = (
            record
            if len(retained_stages) == len(record.stages)
            else _record_prefix(record, tuple(retained_stages))
        )
        if migrated is not None:
            retained_records.append(migrated)

    retained_attempts = []
    for attempt in attempts:
        matches = _endpoint_policy_matches(attempt.to_mapping(), changes)
        historical_request_identity_changed = attempt.precision_digits > 64
        if (
            matches
            or attempt.leaf_id in affected_leaf_ids
            or historical_request_identity_changed
        ):
            invalidated.append({
                "evidence_kind": "campaign-execution-attempt",
                "leaf_id": attempt.leaf_id,
                "attempt_ordinal": attempt.attempt_ordinal,
                "old_endpoint_policy_identities": sorted(matches),
                "reason": (
                    "ENDPOINT_POLICY_IDENTITY_CHANGED"
                    if matches or attempt.leaf_id in affected_leaf_ids
                    else "SCHEMA7_PROMOTED_REQUEST_IDENTITY_CHANGED"
                ),
            })
        else:
            retained_attempts.append(attempt)

    destination_value = _checkpoint_mapping(
        plan, selection, retained_records, retained_attempts
    )
    if destination_value["schema_version"] != CAMPAIGN_CHECKPOINT_SCHEMA_VERSION:
        raise RuntimeError("migration did not produce the current checkpoint schema")

    receipt_material = {
        "schema": CAMPAIGN_MIGRATION_SCHEMA,
        "source_checkpoint_sha256": expected_source_sha256,
        "source_schema_version": _SOURCE_SCHEMA_VERSION,
        "destination_checkpoint_sha256": _digest(destination_value),
        "destination_schema_version": CAMPAIGN_CHECKPOINT_SCHEMA_VERSION,
        "changed_endpoint_policy_identities": changes,
        "invalidated_evidence": invalidated,
        "retained_record_count": len(retained_records),
        "retained_attempt_count": len(retained_attempts),
    }
    receipt = {
        **receipt_material,
        "migration_receipt_sha256": _digest(receipt_material),
    }
    staged_destination = _stage_new_file(destination, destination_value)
    staged_receipt = _stage_new_file(receipt_path, receipt)
    try:
        _load_checkpoint_with_attempts(plan, staged_destination)
        _recheck_source(source, source_bytes)
        _install_staged_pair(
            staged_destination,
            destination,
            staged_receipt,
            receipt_path,
        )
        try:
            _recheck_source(source, source_bytes)
            _load_checkpoint_with_attempts(plan, destination)
        except BaseException:
            destination.unlink(missing_ok=True)
            receipt_path.unlink(missing_ok=True)
            raise
    finally:
        staged_destination.unlink(missing_ok=True)
        staged_receipt.unlink(missing_ok=True)
    return CampaignCheckpointMigrationResult(
        expected_source_sha256,
        hashlib.sha256(destination.read_bytes()).hexdigest(),
        receipt["migration_receipt_sha256"],
        len(retained_records),
        len(invalidated),
    )
