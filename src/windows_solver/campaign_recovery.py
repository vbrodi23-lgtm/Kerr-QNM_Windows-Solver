"""Deterministic, count-agnostic, no-numerics campaign recovery."""

from __future__ import annotations

import copy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Callable, Mapping, Sequence

from .campaign_policy import (
    EvidenceLevel,
    add_numerical_record,
    empty_schema11_checkpoint,
    promotion_source_fingerprint_sha256,
    record_evidence,
    validate_schema11_checkpoint,
)
from .contracts import canonical_json_bytes
from .campaign_record_intake import (
    CampaignRecordIntake,
    HORIZON_RESPONSE_V2_SCIENTIFICALLY_STALE,
)
from .response_batches import CampaignLeafRecord
from .response_engine import _validated_worker_response_receipt
from .root_readout_cache import (
    ROOT_READOUT_RESPONSE_CONTRACT_SHA256,
    RootReadoutStore,
)


RECOVERY_RECEIPT_SCHEMA = "windows-solver.campaign-recovery/v1"
ENDPOINT_RECOVERY_MIGRATION_SCHEMA = (
    "windows-solver.m02-endpoint-recovery-migration/1"
)
ENDPOINT_RECOVERY_MIGRATION_IDENTITY = (
    "authenticated-v2-to-v3-order-geometry-endpoint-recovery/v1"
)
M02_ENDPOINT_RECOVERY_KNOWN_AFFECTED_LEAF_ID = (
    "b-prime-leaf-e6c649ba56795de2c7c4d992fc92652914622017bbd0a0443ab75de34057c1f0"
)
M02_ENDPOINT_RECOVERY_KNOWN_AFFECTED_QUEUE_ORDINAL = 146
ROOT_READOUT_RECOVERY_INDEX_SCHEMA = "windows-solver.root-readout-recovery-index/v2"
LEGACY_COMPATIBILITY_SCHEMA = "legacy-compatibility/v1"
SCIENTIFIC_COMPATIBILITY_SCHEMA = "scientific-compatibility/v1"
STALE_HORIZON_REASON = HORIZON_RESPONSE_V2_SCIENTIFICALLY_STALE
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_SOLVED_RECEIPT_FIELDS = {
    "schema_version",
    "scientific_computation_identity_sha256",
    "leaf_id",
    "record",
    "canonical_leaf_record_sha256",
    "terminal_state",
    "stage_count",
    "created_utc",
    "source_type",
    "receipt_sha256",
}
_TERMINAL_STATES = frozenset({"PRODUCED", "UNRESOLVED", "REJECTED"})
_EVIDENCE_RANK = {None: 0, "SCREENED": 1, "CERTIFIED": 2, "VALIDATED": 3}
_SCHEMA9_CHECKPOINT_FIELDS = {
    "schema_version",
    "state",
    "bindings",
    "records",
    "records_sha256",
    "attempts",
    "attempts_sha256",
    "release_admissible",
}
_SCHEMA9_BINDING_FIELDS = {
    "campaign_bindings",
    "campaign_id",
    "precision_contract_sha256",
    "precision_factory_identity",
    "selection",
    "selection_jobs_sha256",
}
_SCHEMA9_SELECTION_FIELDS = {
    "cohort_ids",
    "leaf_ids",
    "role",
    "selection_id",
}
_SCHEMA9_CAMPAIGN_BINDING_FIELDS = {
    "backend_identity_sha256",
    "campaign_source_sha256",
    "cohort_set_sha256",
    "engine_source_sha256",
    "ordered_leaf_set_sha256",
    "policy_sha256",
    "precision_capabilities_sha256",
    "precision_factory_identity",
    "root_set_sha256",
    "schema_version",
}


RecordValidator = Callable[[str, Mapping[str, object]], None]
RecordIntakeAssessor = Callable[
    [str, Mapping[str, object]], CampaignRecordIntake
]
CheckpointFinalizer = Callable[[Mapping[str, object], Path], Mapping[str, object]]


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _HEX_64.fullmatch(value) is not None


def migrate_fixed_root_endpoint_policy_checkpoint(
    checkpoint: Mapping[str, object],
    *,
    endpoint_recovery_migration: bool = False,
) -> dict[str, object]:
    """Validate schema 11 and optionally apply the explicit endpoint migration.

    Ordinary recovery callers retain current v2 evidence.  The explicit
    migration path preserves the authenticated defective stage as
    ``FORENSIC_ONLY`` and returns the pending queue state without invoking
    roots, determinants, ODEs, or samples.
    """

    return validate_schema11_checkpoint(
        checkpoint,
        endpoint_recovery_migration=endpoint_recovery_migration,
    )


def _endpoint_migration_histories(
    checkpoint: Mapping[str, object],
) -> list[Mapping[str, object]]:
    histories = checkpoint.get("forensic_fixed_root_v2_history")
    if not isinstance(histories, Mapping):
        raise ValueError("endpoint migration forensic history is absent")
    selected = [
        value for value in histories.values()
        if isinstance(value, Mapping)
        and value.get("schema")
        == "windows-solver.fixed-root-endpoint-forensic-history/3"
        and value.get("migration_reason")
        == "FIXED_ROOT_TWO_DIMENSIONAL_ENDPOINT_RECOVERY_REQUIRED"
    ]
    return sorted(
        selected,
        key=lambda item: (int(item["queue_ordinal"]), str(item["leaf_id"])),
    )


def _archive_endpoint_recovery_solved_leaf_receipts(
    store_root: Path | None,
    affected_leaf_ids: set[str],
) -> list[dict[str, object]]:
    if store_root is None or not store_root.exists():
        return []
    if not store_root.is_dir():
        raise ValueError("solved-leaf store is not a directory")
    from .solved_leaf_cache import SolvedLeafStore

    actions: list[tuple[Path, Path, Mapping[str, object], str]] = []
    archive_root = store_root / "forensic-endpoint-recovery-v3"
    for source in sorted(store_root.glob("*.json"), key=lambda item: item.name):
        if source.is_symlink():
            raise ValueError("solved-leaf migration refuses a symlink")
        value = _read_json(source)
        receipt = SolvedLeafStore._validate_receipt(value)
        leaf_id = str(receipt["leaf_id"])
        if leaf_id not in affected_leaf_ids:
            continue
        source_sha256 = _file_sha256(source)
        destination = archive_root / (
            f"{source.stem}.{receipt['receipt_sha256']}.json"
        )
        if destination.exists():
            if _file_sha256(destination) != source_sha256:
                raise ValueError("solved-leaf forensic archive conflicts")
            os.replace(source, destination)
        else:
            actions.append((source, destination, receipt, source_sha256))

    for source, destination, _receipt, _source_sha256 in actions:
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, destination)

    archived: list[dict[str, object]] = []
    if not archive_root.exists():
        return archived
    for destination in sorted(
        archive_root.glob("*.json"), key=lambda item: item.name
    ):
        if destination.is_symlink():
            raise ValueError("solved-leaf forensic archive refuses a symlink")
        receipt = SolvedLeafStore._validate_receipt(_read_json(destination))
        if str(receipt["leaf_id"]) not in affected_leaf_ids:
            continue
        archived.append({
            "leaf_id": receipt["leaf_id"],
            "scientific_computation_identity_sha256": receipt[
                "scientific_computation_identity_sha256"
            ],
            "receipt_sha256": receipt["receipt_sha256"],
            "artifact_sha256": _file_sha256(destination),
            "forensic_path": str(destination),
        })
    return archived


def migrate_endpoint_recovery_checkpoint_file(
    source_checkpoint_path: str | os.PathLike[str] | Path,
    *,
    output_path: str | os.PathLike[str] | Path,
    receipt_path: str | os.PathLike[str] | Path,
    binary64_lock_receipt_sha256: str,
    solved_leaf_store: str | os.PathLike[str] | Path | None = None,
    replace_source: bool = False,
    checkpoint_finalizer: CheckpointFinalizer | None = None,
) -> dict[str, object]:
    """Migrate only defective v2 endpoint evidence, with zero numerics."""

    source_path = Path(source_checkpoint_path)
    output = Path(output_path)
    receipt = Path(receipt_path)
    if output == receipt or source_path == receipt:
        raise ValueError("endpoint migration paths must be distinct")
    if output == source_path and not replace_source:
        raise ValueError("in-place endpoint migration requires explicit authority")
    if not _is_sha256(binary64_lock_receipt_sha256):
        raise ValueError("binary64 lock receipt SHA-256 is invalid")
    if output.exists() and receipt.exists():
        return validate_endpoint_recovery_migration_receipt(
            output,
            receipt,
            binary64_lock_receipt_sha256=binary64_lock_receipt_sha256,
        )
    if receipt.exists():
        raise ValueError("endpoint migration receipt exists without its output")
    try:
        source_value = _read_json(source_path)
    except (OSError, ValueError) as error:
        raise ValueError(
            f"endpoint migration source checkpoint is corrupt: {source_path}: {error}"
        ) from error
    if not isinstance(source_value, Mapping):
        raise ValueError("endpoint migration source checkpoint must be an object")
    source_bytes = source_path.read_bytes()
    if source_bytes != canonical_json_bytes(source_value):
        raise ValueError("endpoint migration source checkpoint is not canonical")
    source_checkpoint_sha256 = hashlib.sha256(source_bytes).hexdigest()
    authenticated_source = validate_schema11_checkpoint(source_value)
    source_histories = {
        str(item.get("history_sha256"))
        for item in _endpoint_migration_histories(authenticated_source)
    }
    migrated = migrate_fixed_root_endpoint_policy_checkpoint(
        authenticated_source,
        endpoint_recovery_migration=True,
    )
    histories = [
        item for item in _endpoint_migration_histories(migrated)
        if str(item.get("history_sha256")) not in source_histories
    ]
    if not histories:
        histories = _endpoint_migration_histories(migrated)
    affected_leaf_ids = {str(item["leaf_id"]) for item in histories}
    affected_ordinals = [int(item["queue_ordinal"]) for item in histories]
    if not affected_leaf_ids:
        raise ValueError("no defective endpoint-policy evidence was discovered")
    known_entries = [
        entry for entry in migrated["promotion_queue"]["entries"]
        if isinstance(entry, Mapping)
        and entry.get("leaf_id") == M02_ENDPOINT_RECOVERY_KNOWN_AFFECTED_LEAF_ID
    ]
    if known_entries and (
        len(known_entries) != 1
        or known_entries[0].get("queue_ordinal")
        != M02_ENDPOINT_RECOVERY_KNOWN_AFFECTED_QUEUE_ORDINAL
        or M02_ENDPOINT_RECOVERY_KNOWN_AFFECTED_LEAF_ID
        not in affected_leaf_ids
    ):
        raise ValueError("known endpoint-recovery boundary was not migrated")
    checkpoint_entry_content = {
        "schema": "windows-solver.m02-endpoint-recovery-migration-entry/1",
        "migration_identity": ENDPOINT_RECOVERY_MIGRATION_IDENTITY,
        "source_checkpoint_sha256": source_checkpoint_sha256,
        "affected_leaf_ids": sorted(affected_leaf_ids),
        "affected_queue_ordinals": sorted(affected_ordinals),
        "archived_stage_sha256s": sorted(
            str(item["source_stage_sha256"]) for item in histories
        ),
        "numerical_work": {
            "backend_constructions": 0,
            "julia_launches": 0,
            "determinant_evaluations": 0,
            "root_solves": 0,
        },
    }
    checkpoint_entry = {
        **checkpoint_entry_content,
        "receipt_sha256": _sha256(checkpoint_entry_content),
    }
    existing_entries = [
        item for item in migrated["recovery_receipts"]
        if isinstance(item, Mapping)
        and item.get("schema")
        == "windows-solver.m02-endpoint-recovery-migration-entry/1"
        and item.get("migration_identity")
        == ENDPOINT_RECOVERY_MIGRATION_IDENTITY
    ]
    if existing_entries:
        if len(existing_entries) != 1:
            raise ValueError("endpoint migration checkpoint entry is ambiguous")
        checkpoint_entry = copy.deepcopy(dict(existing_entries[0]))
    else:
        migrated["recovery_receipts"].append(checkpoint_entry)
    if checkpoint_finalizer is not None:
        scientific_sha256 = _checkpoint_scientific_sha256(migrated)
        migrated = migrate_fixed_root_endpoint_policy_checkpoint(
            checkpoint_finalizer(migrated, output),
            endpoint_recovery_migration=True,
        )
        if _checkpoint_scientific_sha256(migrated) != scientific_sha256:
            raise ValueError(
                "endpoint migration report finalizer changed scientific state"
            )

    source_entries = authenticated_source.get(
        "promotion_queue", {}
    ).get("entries", [])
    output_entries = migrated.get("promotion_queue", {}).get("entries", [])
    if not isinstance(source_entries, list) or not isinstance(output_entries, list):
        raise ValueError("endpoint migration queue is invalid")
    preserved_fields = {
        "queue_ordinal", "leaf_id", "queue_kind", "source_pass", "route",
        "minimum_requested_tier", "source_record_sha256",
        "source_stage_sha256", "source_root_seal_sha256",
        "source_fingerprint_sha256", "scientific_computation_identity",
    }
    if len(source_entries) != len(output_entries) or any(
        {
            name: source_entry.get(name) for name in preserved_fields
        } != {
            name: output_entry.get(name) for name in preserved_fields
        }
        for source_entry, output_entry in zip(source_entries, output_entries)
        if isinstance(source_entry, Mapping) and isinstance(output_entry, Mapping)
    ):
        raise ValueError("endpoint migration changed a frozen queue binding")
    if (
        authenticated_source.get("survey_pass_ledger", {}).get("binary64")
        != migrated.get("survey_pass_ledger", {}).get("binary64")
        or authenticated_source.get("promoted_root_ledger")
        != migrated.get("promoted_root_ledger")
    ):
        raise ValueError("endpoint migration changed frozen Layer-1/root evidence")

    archived_cache = _archive_endpoint_recovery_solved_leaf_receipts(
        None if solved_leaf_store is None else Path(solved_leaf_store),
        affected_leaf_ids,
    )
    output_checkpoint_sha256 = _sha256(migrated)
    receipt_content = {
        "schema": ENDPOINT_RECOVERY_MIGRATION_SCHEMA,
        "migration_identity": ENDPOINT_RECOVERY_MIGRATION_IDENTITY,
        "source_checkpoint_sha256": source_checkpoint_sha256,
        "output_checkpoint_sha256": output_checkpoint_sha256,
        "source_binary64_lock_receipt_sha256": binary64_lock_receipt_sha256,
        "output_binary64_lock_receipt_sha256": binary64_lock_receipt_sha256,
        "affected_leaf_ids": sorted(affected_leaf_ids),
        "affected_queue_ordinals": sorted(affected_ordinals),
        "affected_entries": [
            {
                "leaf_id": str(item["leaf_id"]),
                "queue_ordinal": int(item["queue_ordinal"]),
                "source_stage_sha256": str(item["source_stage_sha256"]),
            }
            for item in sorted(
                histories, key=lambda value: int(value["queue_ordinal"])
            )
        ],
        "archived_stage_sha256s": sorted(
            str(item["source_stage_sha256"]) for item in histories
        ),
        "archived_solved_leaf_receipts": archived_cache,
        "preserved_binary64_processed_count": len(
            migrated["survey_pass_ledger"]["binary64"]
        ),
        "preserved_sample_count": sum(
            int(item.get("sample_count", 0))
            for item in migrated["survey_pass_ledger"]["binary64"].values()
            if isinstance(item, Mapping)
        ),
        "preserved_root_object_count": sum(
            len(bucket) for bucket in migrated["promoted_root_ledger"].values()
            if isinstance(bucket, Mapping)
        ),
        "preserved_queue_cardinality": len(output_entries),
        "reset_entry_count": len(histories),
        "numerical_work": {
            "backend_constructions": 0,
            "julia_launches": 0,
            "determinant_evaluations": 0,
            "root_solves": 0,
        },
    }
    migration_receipt = {
        **receipt_content,
        "receipt_sha256": _sha256(receipt_content),
    }
    if receipt.exists():
        existing = _read_json(receipt)
        if existing != migration_receipt:
            raise ValueError("endpoint migration receipt destination conflicts")
    if output.exists() and output != source_path:
        existing = _read_json(output)
        if existing != migrated:
            raise ValueError("endpoint migration output destination conflicts")
    else:
        _atomic_json(output, migrated)
    if not receipt.exists():
        _atomic_json(receipt, migration_receipt)
    return migration_receipt


def validate_endpoint_recovery_migration_receipt(
    checkpoint_path: str | os.PathLike[str] | Path,
    receipt_path: str | os.PathLike[str] | Path,
    *,
    binary64_lock_receipt_sha256: str,
) -> dict[str, object]:
    checkpoint = Path(checkpoint_path)
    receipt = Path(receipt_path)
    value = _read_json(receipt)
    if not isinstance(value, Mapping):
        raise ValueError("endpoint migration receipt must be an object")
    fields = {
        "schema", "migration_identity", "source_checkpoint_sha256",
        "output_checkpoint_sha256", "source_binary64_lock_receipt_sha256",
        "output_binary64_lock_receipt_sha256", "affected_leaf_ids",
        "affected_queue_ordinals", "affected_entries",
        "archived_stage_sha256s",
        "archived_solved_leaf_receipts", "preserved_binary64_processed_count",
        "preserved_sample_count", "preserved_root_object_count",
        "preserved_queue_cardinality", "reset_entry_count", "numerical_work",
        "receipt_sha256",
    }
    content = {
        name: item for name, item in value.items() if name != "receipt_sha256"
    }
    if (
        set(value) != fields
        or value.get("schema") != ENDPOINT_RECOVERY_MIGRATION_SCHEMA
        or value.get("migration_identity")
        != ENDPOINT_RECOVERY_MIGRATION_IDENTITY
        or value.get("receipt_sha256") != _sha256(content)
        or value.get("source_binary64_lock_receipt_sha256")
        != binary64_lock_receipt_sha256
        or value.get("output_binary64_lock_receipt_sha256")
        != binary64_lock_receipt_sha256
        or value.get("numerical_work") != {
            "backend_constructions": 0,
            "julia_launches": 0,
            "determinant_evaluations": 0,
            "root_solves": 0,
        }
        or value.get("output_checkpoint_sha256") != _file_sha256(checkpoint)
    ):
        raise ValueError("endpoint migration receipt authentication failed")
    affected_leaf_ids = value.get("affected_leaf_ids")
    affected_ordinals = value.get("affected_queue_ordinals")
    affected_entries = value.get("affected_entries")
    archived_stage_sha256s = value.get("archived_stage_sha256s")
    archived_cache = value.get("archived_solved_leaf_receipts")
    if (
        not isinstance(affected_leaf_ids, list)
        or not affected_leaf_ids
        or affected_leaf_ids != sorted(set(affected_leaf_ids))
        or not all(isinstance(item, str) and item for item in affected_leaf_ids)
        or not isinstance(affected_ordinals, list)
        or affected_ordinals != sorted(set(affected_ordinals))
        or not all(type(item) is int and item >= 0 for item in affected_ordinals)
        or len(affected_leaf_ids) != len(affected_ordinals)
        or not isinstance(affected_entries, list)
        or len(affected_entries) != len(affected_leaf_ids)
        or not isinstance(archived_stage_sha256s, list)
        or archived_stage_sha256s != sorted(set(archived_stage_sha256s))
        or len(archived_stage_sha256s) != len(affected_leaf_ids)
        or not all(_is_sha256(item) for item in archived_stage_sha256s)
        or value.get("reset_entry_count") != len(affected_leaf_ids)
        or not isinstance(archived_cache, list)
    ):
        raise ValueError("endpoint migration receipt inventory is invalid")
    affected_entry_fields = {
        "leaf_id", "queue_ordinal", "source_stage_sha256",
    }
    if (
        any(
            not isinstance(item, Mapping)
            or set(item) != affected_entry_fields
            or not isinstance(item.get("leaf_id"), str)
            or type(item.get("queue_ordinal")) is not int
            or not _is_sha256(item.get("source_stage_sha256"))
            for item in affected_entries
        )
        or affected_entries != sorted(
            affected_entries, key=lambda item: int(item["queue_ordinal"])
        )
        or sorted(item["leaf_id"] for item in affected_entries)
        != affected_leaf_ids
        or [item["queue_ordinal"] for item in affected_entries]
        != affected_ordinals
        or sorted(item["source_stage_sha256"] for item in affected_entries)
        != archived_stage_sha256s
    ):
        raise ValueError("endpoint migration affected-entry binding is invalid")
    from .solved_leaf_cache import SolvedLeafStore

    cache_fields = {
        "leaf_id", "scientific_computation_identity_sha256",
        "receipt_sha256", "artifact_sha256", "forensic_path",
    }
    for item in archived_cache:
        if (
            not isinstance(item, Mapping)
            or set(item) != cache_fields
            or item.get("leaf_id") not in affected_leaf_ids
            or not _is_sha256(item.get("scientific_computation_identity_sha256"))
            or not _is_sha256(item.get("receipt_sha256"))
            or not _is_sha256(item.get("artifact_sha256"))
            or not isinstance(item.get("forensic_path"), str)
        ):
            raise ValueError("endpoint migration cache archive is invalid")
        forensic_path = Path(item["forensic_path"])
        if (
            forensic_path.is_symlink()
            or not forensic_path.is_file()
            or _file_sha256(forensic_path) != item["artifact_sha256"]
        ):
            raise ValueError("endpoint migration cache artifact is invalid")
        cached_receipt = SolvedLeafStore._validate_receipt(
            _read_json(forensic_path)
        )
        if (
            cached_receipt["leaf_id"] != item["leaf_id"]
            or cached_receipt["receipt_sha256"] != item["receipt_sha256"]
            or cached_receipt["scientific_computation_identity_sha256"]
            != item["scientific_computation_identity_sha256"]
        ):
            raise ValueError("endpoint migration cache binding is invalid")

    migrated = validate_schema11_checkpoint(_read_json(checkpoint))
    histories = [
        item for item in _endpoint_migration_histories(migrated)
        if item.get("source_stage_sha256") in archived_stage_sha256s
    ]
    history_by_leaf = {str(item["leaf_id"]): item for item in histories}
    if (
        set(history_by_leaf) != set(affected_leaf_ids)
        or sorted(int(item["queue_ordinal"]) for item in histories)
        != affected_ordinals
        or sorted(str(item["source_stage_sha256"]) for item in histories)
        != archived_stage_sha256s
    ):
        raise ValueError("endpoint migration forensic binding is invalid")
    entries = migrated["promotion_queue"]["entries"]
    for affected in affected_entries:
        leaf_id = str(affected["leaf_id"])
        ordinal = int(affected["queue_ordinal"])
        entry = entries[ordinal]
        if (
            entry.get("leaf_id") != leaf_id
            or entry.get("disposition") != "PENDING"
            or entry.get("retained_promoted_stage_sha256") is not None
        ):
            raise ValueError("endpoint migration queue reset is invalid")
    if (
        value.get("preserved_binary64_processed_count")
        != len(migrated["survey_pass_ledger"]["binary64"])
        or value.get("preserved_sample_count")
        != sum(
            int(item.get("sample_count", 0))
            for item in migrated["survey_pass_ledger"]["binary64"].values()
            if isinstance(item, Mapping)
        )
        or value.get("preserved_root_object_count")
        != sum(
            len(bucket) for bucket in migrated["promoted_root_ledger"].values()
            if isinstance(bucket, Mapping)
        )
        or value.get("preserved_queue_cardinality") != len(entries)
    ):
        raise ValueError("endpoint migration preservation counts are invalid")
    return copy.deepcopy(dict(value))


def _checkpoint_scientific_sha256(checkpoint: Mapping[str, object]) -> str:
    scientific = copy.deepcopy(dict(checkpoint))
    scientific["report_status_receipt"] = None
    return _sha256(scientific)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate recovery JSON key: {key}")
        result[key] = value
    return result


def _read_json(path: Path) -> object:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda item: (_ for _ in ()).throw(
                ValueError(f"recovery input contains non-finite constant {item}")
            ),
        )
    except json.JSONDecodeError as error:
        raise ValueError("recovery input is not valid JSON") from error


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


@dataclass(frozen=True, slots=True)
class RecoverySelection:
    campaign_id: str
    selection_id: str
    ordered_leaf_ids: tuple[str, ...]
    roles: Mapping[str, str]
    scientific_identities: Mapping[str, str]

    def __post_init__(self) -> None:
        leaf_ids = self.ordered_leaf_ids
        if (
            not self.campaign_id
            or not self.selection_id
            or len(leaf_ids) != len(set(leaf_ids))
            or any(not isinstance(item, str) or not item for item in leaf_ids)
        ):
            raise ValueError("recovery selection identity is invalid")
        if set(self.roles) != set(leaf_ids):
            raise ValueError("recovery selection roles are incomplete")
        if set(self.scientific_identities) != set(leaf_ids):
            raise ValueError("recovery scientific identities are incomplete")
        if any(not isinstance(role, str) or not role for role in self.roles.values()):
            raise ValueError("recovery selection role is invalid")
        if any(not _is_sha256(item) for item in self.scientific_identities.values()):
            raise ValueError("recovery scientific computation identity is invalid")
        object.__setattr__(self, "roles", dict(self.roles))
        object.__setattr__(
            self, "scientific_identities", dict(self.scientific_identities)
        )


def checkpoint_bound_promoted_recovery_selection(
    plan: object,
    selection: object,
    checkpoint: Mapping[str, object],
) -> RecoverySelection:
    """Bind one fully queued historical checkpoint without rewriting evidence.

    Campaign source hashes legitimately change across a control-plane repair.
    A stale identifier is therefore accepted only when the authenticated
    promotion queue covers the current full 212-leaf selection exactly and
    every queue source still binds to its retained Binary64 disposition.
    """

    plan_leaf_ids = tuple(leaf.leaf_id for leaf in plan.leaves)
    selected_leaf_ids = tuple(selection.leaf_ids)
    if (
        getattr(selection, "role", None) != "all"
        or len(plan_leaf_ids) != 212
        or selected_leaf_ids != plan_leaf_ids
    ):
        raise ValueError(
            "historical promoted handover requires the exact full 212-leaf selection"
        )
    value, roles, scientific_identities = (
        _checkpoint_bound_promoted_recovery_material(
            plan, selected_leaf_ids, checkpoint
        )
    )
    return RecoverySelection(
        campaign_id=str(value["campaign_id"]),
        selection_id=str(value["selection_id"]),
        ordered_leaf_ids=selected_leaf_ids,
        roles=roles,
        scientific_identities=scientific_identities,
    )


def _checkpoint_bound_promoted_recovery_material(
    plan: object,
    selected_leaf_ids: tuple[str, ...],
    checkpoint: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, str], dict[str, str]]:
    """Authenticate the historical queue as routing evidence, not calculations."""

    value = migrate_fixed_root_endpoint_policy_checkpoint(checkpoint)
    plan_leaf_ids = tuple(leaf.leaf_id for leaf in plan.leaves)
    if len(plan_leaf_ids) != 212 or selected_leaf_ids != plan_leaf_ids:
        raise ValueError(
            "historical promoted handover requires the exact full 212-leaf order"
        )
    entries = value["promotion_queue"]["entries"]
    if (
        len(entries) != len(selected_leaf_ids)
        or tuple(entry.get("queue_ordinal") for entry in entries)
        != tuple(range(len(selected_leaf_ids)))
        or tuple(entry.get("leaf_id") for entry in entries) != selected_leaf_ids
    ):
        raise ValueError(
            "historical promoted handover queue does not match the selected leaf order"
        )

    binary64 = value["survey_pass_ledger"]["binary64"]
    scientific_identities: dict[str, str] = {}
    roles = {leaf.leaf_id: leaf.role for leaf in plan.leaves}
    for leaf_id, entry in zip(selected_leaf_ids, entries, strict=True):
        binary64_entry = binary64.get(leaf_id)
        scientific_identity = entry.get("scientific_computation_identity")
        source_fingerprint = entry.get("source_fingerprint_sha256")
        if (
            not isinstance(binary64_entry, Mapping)
            or binary64_entry.get("leaf_id") != leaf_id
            or entry.get("source_binary64_disposition_receipt_sha256")
            != binary64_entry.get("disposition_receipt_sha256")
            or not _is_sha256(scientific_identity)
            or not _is_sha256(entry.get("source_stage_sha256"))
            or not _is_sha256(entry.get("source_root_seal_sha256"))
            or not _is_sha256(source_fingerprint)
            or source_fingerprint != promotion_source_fingerprint_sha256(entry)
        ):
            raise ValueError(
                "historical promoted handover queue source binding is invalid"
            )
        provisional = entry.get("provisional_stage")
        if provisional is not None and (
            not isinstance(provisional, Mapping)
            or entry.get("provisional_stage_sha256")
            != provisional.get("stage_sha256")
            or entry.get("source_stage_sha256") != provisional.get("stage_sha256")
        ):
            raise ValueError(
                "historical promoted handover provisional source is invalid"
            )
        scientific_identities[leaf_id] = scientific_identity

    return value, roles, scientific_identities


def validate_checkpoint_bound_promoted_recovery_selection(
    plan: object,
    selection: RecoverySelection,
    checkpoint: Mapping[str, object],
) -> RecoverySelection:
    """Reauthenticate a historical handover at the scheduler boundary."""

    if not isinstance(selection, RecoverySelection):
        raise ValueError("historical promoted recovery selection is invalid")
    if getattr(plan, "campaign_id", None) == selection.campaign_id:
        raise ValueError("historical promoted handover requires a stale campaign ID")
    value, roles, scientific_identities = (
        _checkpoint_bound_promoted_recovery_material(
            plan, selection.ordered_leaf_ids, checkpoint
        )
    )
    if (
        value["campaign_id"] != selection.campaign_id
        or value["selection_id"] != selection.selection_id
        or roles != selection.roles
        or scientific_identities != selection.scientific_identities
    ):
        raise ValueError("historical promoted recovery binding is invalid")
    return selection


@dataclass(frozen=True, slots=True)
class RecoverySummary:
    campaign_id: str
    selection_id: str
    discovered_valid_unique_count: int
    recovered_count: int
    lost_valid_count: int
    fabricated_count: int
    ignored_count: int
    output_path: str
    receipt_path: str
    backend_constructions: int = 0
    julia_launches: int = 0
    determinant_evaluations: int = 0
    root_solves: int = 0
    legacy_authenticated_terminal_count: int = 0
    legacy_imported_count: int = 0
    legacy_rejected_count: int = 0
    legacy_unreconstructable_count: int = 0

    def to_mapping(self) -> dict[str, object]:
        return {
            "campaign_id": self.campaign_id,
            "selection_id": self.selection_id,
            "discovered_valid_unique_count": self.discovered_valid_unique_count,
            "recovered_count": self.recovered_count,
            "lost_valid_count": self.lost_valid_count,
            "fabricated_count": self.fabricated_count,
            "ignored_count": self.ignored_count,
            "output_path": self.output_path,
            "receipt_path": self.receipt_path,
            "backend_constructions": self.backend_constructions,
            "julia_launches": self.julia_launches,
            "determinant_evaluations": self.determinant_evaluations,
            "root_solves": self.root_solves,
            "legacy_authenticated_terminal_count": (
                self.legacy_authenticated_terminal_count
            ),
            "legacy_imported_count": self.legacy_imported_count,
            "legacy_rejected_count": self.legacy_rejected_count,
            "legacy_unreconstructable_count": (
                self.legacy_unreconstructable_count
            ),
        }


@dataclass(frozen=True, slots=True)
class _Candidate:
    leaf_id: str
    record: Mapping[str, object]
    source: str
    source_sha256: str
    receipt_sha256: str
    evidence: Mapping[str, object] | None = None


def _validated_record(
    value: object,
    *,
    expected_role: str | None,
    record_validator: RecordValidator | None,
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("recovery numerical record must be an object")
    record = copy.deepcopy(dict(value))
    leaf_id = record.get("leaf_id")
    if not isinstance(leaf_id, str) or not leaf_id:
        raise ValueError("recovery numerical record leaf ID is invalid")
    if record.get("state") not in _TERMINAL_STATES:
        raise ValueError("recovery numerical record is not terminal")
    if expected_role is not None and record.get("role") != expected_role:
        raise ValueError("recovery numerical record role is incompatible")
    stages = record.get("stages")
    if not isinstance(stages, list) or not stages:
        raise ValueError("recovery numerical record stages are incomplete")
    for stage in stages:
        if not isinstance(stage, Mapping):
            raise ValueError("recovery numerical stage must be an object")
        stage_sha = stage.get("stage_sha256")
        stage_content = {
            key: item for key, item in stage.items() if key != "stage_sha256"
        }
        if not _is_sha256(stage_sha) or stage_sha != _sha256(stage_content):
            raise ValueError("recovery numerical stage digest is invalid")
    record_sha = record.get("record_sha256")
    record_content = {
        key: item for key, item in record.items() if key != "record_sha256"
    }
    if not _is_sha256(record_sha) or record_sha != _sha256(record_content):
        raise ValueError("recovery numerical record digest is invalid")
    if record_validator is not None:
        record_validator(leaf_id, record)
    return record


def _validated_schema9_checkpoint(value: object) -> dict[str, object]:
    """Authenticate the historical schema-9 envelope without upgrading it.

    Schema 9 predates the schema-11 evidence ledger.  Its immutable numerical
    records remain useful provenance, but this adapter must never manufacture
    SCREENED, CERTIFIED, or VALIDATED evidence for them.
    """

    if not isinstance(value, Mapping):
        raise ValueError("schema-9 checkpoint must be an object")
    checkpoint = copy.deepcopy(dict(value))
    if set(checkpoint) != _SCHEMA9_CHECKPOINT_FIELDS:
        raise ValueError("schema-9 checkpoint envelope fields are invalid")
    if checkpoint["schema_version"] != 9:
        raise ValueError("schema-9 checkpoint version is invalid")
    if checkpoint["state"] not in {"PARTIAL", "COMPLETE"}:
        raise ValueError("schema-9 checkpoint state is invalid")
    if not isinstance(checkpoint["release_admissible"], bool):
        raise ValueError("schema-9 checkpoint release flag is invalid")

    bindings = checkpoint["bindings"]
    if not isinstance(bindings, Mapping) or set(bindings) != _SCHEMA9_BINDING_FIELDS:
        raise ValueError("schema-9 checkpoint bindings are invalid")
    if not isinstance(bindings["campaign_id"], str) or not bindings["campaign_id"]:
        raise ValueError("schema-9 checkpoint campaign ID is invalid")
    if not _is_sha256(bindings["precision_contract_sha256"]) or not _is_sha256(
        bindings["selection_jobs_sha256"]
    ):
        raise ValueError("schema-9 checkpoint binding digest is invalid")

    source_selection = bindings["selection"]
    if (
        not isinstance(source_selection, Mapping)
        or set(source_selection) != _SCHEMA9_SELECTION_FIELDS
        or not isinstance(source_selection["selection_id"], str)
        or not source_selection["selection_id"]
        or not isinstance(source_selection["role"], str)
        or not source_selection["role"]
        or not isinstance(source_selection["cohort_ids"], list)
        or not isinstance(source_selection["leaf_ids"], list)
    ):
        raise ValueError("schema-9 checkpoint selection binding is invalid")
    source_leaf_ids = source_selection["leaf_ids"]
    if (
        not source_leaf_ids
        or len(source_leaf_ids) != len(set(source_leaf_ids))
        or any(not isinstance(item, str) or not item for item in source_leaf_ids)
    ):
        raise ValueError("schema-9 checkpoint selection leaves are invalid")
    if (
        len(source_selection["cohort_ids"])
        != len(set(source_selection["cohort_ids"]))
        or any(
            not isinstance(item, str) or not item
            for item in source_selection["cohort_ids"]
        )
    ):
        raise ValueError("schema-9 checkpoint selection cohorts are invalid")

    campaign_bindings = bindings["campaign_bindings"]
    if (
        not isinstance(campaign_bindings, Mapping)
        or set(campaign_bindings) != _SCHEMA9_CAMPAIGN_BINDING_FIELDS
        or campaign_bindings["schema_version"] != 3
    ):
        raise ValueError("schema-9 checkpoint campaign provenance is invalid")
    for name, item in campaign_bindings.items():
        if name == "schema_version":
            continue
        if name == "precision_factory_identity":
            if not isinstance(item, Mapping) or set(item) != {"factory", "module_sha256"}:
                raise ValueError("schema-9 precision factory provenance is invalid")
            if not isinstance(item["factory"], str) or not _is_sha256(item["module_sha256"]):
                raise ValueError("schema-9 precision factory provenance is invalid")
        elif not _is_sha256(item):
            raise ValueError("schema-9 campaign provenance digest is invalid")
    factory_identity = bindings["precision_factory_identity"]
    if (
        not isinstance(factory_identity, Mapping)
        or dict(factory_identity) != dict(campaign_bindings["precision_factory_identity"])
    ):
        raise ValueError("schema-9 precision factory binding is invalid")

    raw_records = checkpoint["records"]
    if (
        not isinstance(raw_records, list)
        or checkpoint["records_sha256"] != _sha256(raw_records)
    ):
        raise ValueError("schema-9 checkpoint records digest is invalid")
    raw_attempts = checkpoint["attempts"]
    if (
        not isinstance(raw_attempts, list)
        or checkpoint["attempts_sha256"] != _sha256(raw_attempts)
    ):
        raise ValueError("schema-9 checkpoint attempts digest is invalid")

    for raw_record in raw_records:
        record = CampaignLeafRecord.from_mapping(raw_record)
        if record.to_mapping() != raw_record:
            raise ValueError("schema-9 checkpoint record is not canonical")
        if record.leaf_id not in source_leaf_ids:
            raise ValueError("schema-9 record is outside its source selection")
    return checkpoint


def _legacy_compatibility_receipt(
    *,
    path: Path,
    source_sha256: str,
    checkpoint: Mapping[str, object],
    record: Mapping[str, object],
    selection: RecoverySelection,
    imported: bool,
    reason: str | None,
    reason_detail: str | None = None,
) -> dict[str, object]:
    """Record a schema-9 decision without claiming absent evidence.

    This is compatibility provenance, not an evidence-ledger receipt.  In
    particular, a schema-9 record gets no inferred evidence level merely
    because it was once numerically terminal.
    """

    bindings = checkpoint["bindings"]
    assert isinstance(bindings, Mapping)
    source_selection = bindings["selection"]
    assert isinstance(source_selection, Mapping)
    leaf_id = record["leaf_id"]
    assert isinstance(leaf_id, str)
    content: dict[str, object] = {
        "schema": LEGACY_COMPATIBILITY_SCHEMA,
        "source_checkpoint_schema_version": 9,
        "source_path": str(path),
        "source_sha256": source_sha256,
        "source_campaign_id": bindings["campaign_id"],
        "source_selection_id": source_selection["selection_id"],
        "source_records_sha256": checkpoint["records_sha256"],
        "source_campaign_bindings_sha256": _sha256(
            bindings["campaign_bindings"]
        ),
        "source_selection_binding_sha256": _sha256(source_selection),
        "leaf_id": leaf_id,
        "source_record_sha256": record["record_sha256"],
        "source_terminal_state": record["state"],
        "source_campaign_matches_current": (
            bindings["campaign_id"] == selection.campaign_id
        ),
        "source_selection_matches_current": (
            source_selection["selection_id"] == selection.selection_id
        ),
        "source_leaf_was_selected": leaf_id in source_selection["leaf_ids"],
        "current_leaf_is_selected": leaf_id in selection.ordered_leaf_ids,
        "source_stage_sha256s": [
            stage["stage_sha256"] for stage in record["stages"]
        ],
        "current_scientific_identity_sha256": selection.scientific_identities.get(
            leaf_id
        ),
        "original_record_status": "AUTHENTICATED",
        "identity_reconstruction_status": (
            "PROVEN_CURRENT"
            if imported
            else (
                "NOT_APPLICABLE_OFF_SELECTION"
                if reason == "OFF_SELECTION"
                else "NOT_PROVEN"
            )
        ),
        "imported_as_current_numerical_record": imported,
        "schema11_evidence_level": None,
        "reason": reason,
        "reason_detail": reason_detail,
    }
    return {**content, "receipt_sha256": _sha256(content)}


def _stale_horizon_v2_receipt(
    *,
    path: Path,
    source_sha256: str,
    checkpoint: Mapping[str, object] | None,
    record: Mapping[str, object],
    selection: RecoverySelection,
    source_evidence: Mapping[str, object] | None,
    source_kind: str = "checkpoint",
) -> dict[str, object]:
    """Bind an authenticated legacy horizon record as forensic-only input.

    The source checkpoint remains untouched. Its terminal record and attached
    evidence are deliberately excluded from current schema-11 numerical and
    evidence ledgers because their response identity is stale under PR69 v3.
    """

    leaf_id = record["leaf_id"]
    assert isinstance(leaf_id, str)
    stages = record["stages"]
    assert isinstance(stages, list)
    operations = sorted(
        {
            str(stage["operation_identity"])
            for stage in stages
            if isinstance(stage, Mapping)
            and isinstance(stage.get("operation_identity"), str)
        }
    )
    content: dict[str, object] = {
        "schema": SCIENTIFIC_COMPATIBILITY_SCHEMA,
        "source_checkpoint_schema_version": 11 if checkpoint is not None else None,
        "source_kind": source_kind,
        "source_path": str(path),
        "source_sha256": source_sha256,
        "source_campaign_id": (
            selection.campaign_id
            if checkpoint is None
            else checkpoint["campaign_id"]
        ),
        "source_selection_id": (
            selection.selection_id
            if checkpoint is None
            else checkpoint["selection_id"]
        ),
        "leaf_id": leaf_id,
        "source_record_sha256": record["record_sha256"],
        "source_stage_sha256s": [stage["stage_sha256"] for stage in stages],
        "source_operation_identities": operations,
        "current_scientific_identity_sha256": selection.scientific_identities[
            leaf_id
        ],
        "original_record_status": "AUTHENTICATED",
        "source_evidence_was_present": source_evidence is not None,
        "imported_as_current_numerical_record": False,
        "imported_as_current_evidence": False,
        "forensic_record_status": "RETAINED_IN_SOURCE_ONLY",
        "operational_queue_disposition": "REBUILT_FROM_CURRENT_SELECTION",
        "reason": STALE_HORIZON_REASON,
    }
    return {**content, "receipt_sha256": _sha256(content)}


def _schema9_source_candidates(
    *,
    path: Path,
    source_sha256: str,
    checkpoint: Mapping[str, object],
    selection: RecoverySelection,
    record_validator: RecordValidator | None,
    candidates: dict[str, list[_Candidate]],
    ignored: list[dict[str, object]],
    compatibility_receipts: list[dict[str, object]],
) -> tuple[int, int, int, int]:
    """Recover only schema-9 records whose current identity is proven.

    A terminal schema-9 record is authentic historical work, not automatically
    current scientific evidence.  When the current campaign identity cannot be
    reconstructed, retain a deterministic compatibility receipt and leave the
    numerical record out of the schema-11 checkpoint.
    """

    selected = set(selection.ordered_leaf_ids)
    raw_records = checkpoint["records"]
    assert isinstance(raw_records, list)
    by_leaf: dict[str, list[dict[str, object]]] = {}
    for raw_record in raw_records:
        assert isinstance(raw_record, Mapping)
        record = copy.deepcopy(dict(raw_record))
        leaf_id = record["leaf_id"]
        assert isinstance(leaf_id, str)
        by_leaf.setdefault(leaf_id, []).append(record)

    authenticated_terminal_count = 0
    imported_count = 0
    rejected_count = 0
    unreconstructable_count = 0
    for leaf_id, records in by_leaf.items():
        terminal_records = [
            record for record in records if record["state"] in _TERMINAL_STATES
        ]
        authenticated_terminal_count += len(terminal_records)
        if len(records) != 1:
            for record in terminal_records:
                compatibility_receipts.append(
                    _legacy_compatibility_receipt(
                        path=path,
                        source_sha256=source_sha256,
                        checkpoint=checkpoint,
                        record=record,
                        selection=selection,
                        imported=False,
                        reason="AMBIGUOUS_LEGACY_RECONSTRUCTION",
                    )
                )
                unreconstructable_count += 1
                rejected_count += 1
            ignored.append(
                {
                    "path": str(path),
                    "leaf_id": leaf_id,
                    "reason": "AMBIGUOUS_LEGACY_RECONSTRUCTION",
                }
            )
            continue
        record = records[0]
        if record["state"] not in _TERMINAL_STATES:
            ignored.append(
                {
                    "path": str(path),
                    "leaf_id": leaf_id,
                    "reason": f"NONTERMINAL_{record['state']}",
                }
            )
            continue
        if leaf_id not in selected:
            compatibility_receipts.append(
                _legacy_compatibility_receipt(
                    path=path,
                    source_sha256=source_sha256,
                    checkpoint=checkpoint,
                    record=record,
                    selection=selection,
                    imported=False,
                    reason="OFF_SELECTION",
                )
            )
            ignored.append(
                {"path": str(path), "leaf_id": leaf_id, "reason": "OFF_SELECTION"}
            )
            rejected_count += 1
            continue

        reason = None
        reason_detail = None
        if record_validator is None:
            reason = "CURRENT_SCIENTIFIC_IDENTITY_VALIDATOR_NOT_SUPPLIED"
        if reason is None:
            try:
                validated = _validated_record(
                    record,
                    expected_role=selection.roles[leaf_id],
                    record_validator=record_validator,
                )
            except ValueError as error:
                reason_detail = str(error)
                insufficient_markers = (
                    "absent",
                    "incomplete",
                    "lacks",
                    "missing",
                    "unavailable",
                )
                reason = (
                    "CURRENT_SCIENTIFIC_IDENTITY_UNRECONSTRUCTABLE"
                    if any(
                        marker in reason_detail.lower()
                        for marker in insufficient_markers
                    )
                    else "CURRENT_SCIENTIFIC_IDENTITY_INCOMPATIBLE"
                )
            else:
                receipt = _legacy_compatibility_receipt(
                    path=path,
                    source_sha256=source_sha256,
                    checkpoint=checkpoint,
                    record=validated,
                    selection=selection,
                    imported=True,
                    reason=None,
                )
                candidates.setdefault(leaf_id, []).append(
                    _Candidate(
                        leaf_id,
                        validated,
                        str(path),
                        source_sha256,
                        receipt["receipt_sha256"],
                    )
                )
                compatibility_receipts.append(receipt)
                imported_count += 1
                continue

        compatibility_receipts.append(
            _legacy_compatibility_receipt(
                path=path,
                source_sha256=source_sha256,
                checkpoint=checkpoint,
                record=record,
                selection=selection,
                imported=False,
                reason=reason,
                reason_detail=reason_detail,
            )
        )
        ignored.append({
            "path": str(path),
            "leaf_id": leaf_id,
            "reason": reason,
            "reason_detail": reason_detail,
        })
        rejected_count += 1
        if reason in {
            "CURRENT_SCIENTIFIC_IDENTITY_UNRECONSTRUCTABLE",
            "CURRENT_SCIENTIFIC_IDENTITY_VALIDATOR_NOT_SUPPLIED",
        }:
            unreconstructable_count += 1
    return (
        authenticated_terminal_count,
        imported_count,
        rejected_count,
        unreconstructable_count,
    )


def _incident_oracle_status(
    oracle_path: str | os.PathLike[str] | Path | None,
) -> str:
    """Classify the optional historical incident oracle without inventing a schema."""

    if oracle_path is None:
        return "NOT_SUPPLIED"
    path = Path(oracle_path)
    if not path.is_file():
        return "INCOMPLETE_FIXTURE"
    try:
        _read_json(path)
    except (OSError, ValueError):
        return "INCOMPLETE_FIXTURE"
    # No complete historical incident-oracle schema is present in the active
    # contract. A parseable arbitrary JSON file is therefore still not an
    # admissible oracle.
    return "INCOMPLETE_FIXTURE"


def _validated_solved_receipt(
    value: object,
    *,
    expected_role: str | None,
    record_validator: RecordValidator | None,
) -> tuple[dict[str, object], str]:
    if not isinstance(value, Mapping) or set(value) != _SOLVED_RECEIPT_FIELDS:
        raise ValueError("solved-leaf recovery receipt fields are invalid")
    if value["schema_version"] != 1:
        raise ValueError("solved-leaf recovery receipt schema is invalid")
    sealed = {key: item for key, item in value.items() if key != "receipt_sha256"}
    if not _is_sha256(value["receipt_sha256"]) or value["receipt_sha256"] != _sha256(
        sealed
    ):
        raise ValueError("solved-leaf outer receipt digest is invalid")
    identity = value["scientific_computation_identity_sha256"]
    if not _is_sha256(identity):
        raise ValueError("solved-leaf scientific identity is invalid")
    record = _validated_record(
        value["record"],
        expected_role=expected_role,
        record_validator=record_validator,
    )
    if (
        value["leaf_id"] != record["leaf_id"]
        or value["terminal_state"] != record["state"]
        or value["canonical_leaf_record_sha256"] != record["record_sha256"]
        or value["stage_count"] != len(record["stages"])
    ):
        raise ValueError("solved-leaf receipt disagrees with its numerical record")
    return record, identity


def _root_readout_recovery_entry(
    *, entry: object, source_sha256: str
) -> dict[str, object]:
    """Seal a cache address for later root authentication without numerics."""

    receipt = getattr(entry, "worker_response_receipt", None)
    if receipt is None:
        raise ValueError("root-readout cache entry lacks a worker response receipt")
    validated_receipt = _validated_worker_response_receipt(receipt)
    if validated_receipt is None:
        raise ValueError("root-readout cache entry lacks a worker response receipt")
    request_sha256 = getattr(entry, "request_sha256", None)
    response_contract_sha256 = getattr(
        entry, "response_contract_sha256", None
    )
    response = getattr(entry, "response", None)
    if (
        not _is_sha256(request_sha256)
        or response_contract_sha256
        != ROOT_READOUT_RESPONSE_CONTRACT_SHA256
        or not isinstance(response, Mapping)
        or validated_receipt["request_sha256"] != request_sha256
        or response.get("request_sha256") != request_sha256
        or validated_receipt["worker_response_schema_version"]
        != response.get("schema_version")
    ):
        raise ValueError("root-readout cache entry receipt binding is invalid")
    return {
        "path": str(entry.path),
        "source_sha256": source_sha256,
        "readout_identity_sha256": entry.readout_identity_sha256,
        "request_sha256": request_sha256,
        "runtime_identity_sha256": entry.runtime_identity_sha256,
        "response_contract_sha256": response_contract_sha256,
        "worker_response_receipt_sha256": validated_receipt["receipt_sha256"],
    }


def _candidate_like_solved_receipt(path: Path, value: object) -> bool:
    if _HEX_64.fullmatch(path.stem) is not None:
        return True
    if not isinstance(value, Mapping):
        return False
    return {
        "scientific_computation_identity_sha256",
        "record",
        "receipt_sha256",
    }.issubset(value)


def _merge_evidence(
    current: Mapping[str, object] | None,
    candidate: Mapping[str, object] | None,
) -> Mapping[str, object] | None:
    if candidate is None:
        return current
    if current is None:
        return copy.deepcopy(dict(candidate))
    if (
        current["central_record_sha256"]
        != candidate["central_record_sha256"]
        or current["central_stage_sha256"]
        != candidate["central_stage_sha256"]
    ):
        raise ValueError("conflicting evidence centres during recovery")
    level = max(
        (current["evidence_level"], candidate["evidence_level"]),
        key=lambda item: _EVIDENCE_RANK[item],
    )
    receipts = {
        canonical_json_bytes(item): copy.deepcopy(dict(item))
        for item in [*current["receipts"], *candidate["receipts"]]
    }
    codes = sorted(
        set(current["discrepancy_codes"]) | set(candidate["discrepancy_codes"])
    )
    return {
        "leaf_id": current["leaf_id"],
        "central_record_sha256": current["central_record_sha256"],
        "central_stage_sha256": current["central_stage_sha256"],
        "evidence_level": level,
        "receipts": [receipts[key] for key in sorted(receipts)],
        "discrepancy_codes": codes,
    }


def recover_campaign(
    selection: RecoverySelection,
    *,
    output_path: str | os.PathLike[str] | Path,
    receipt_path: str | os.PathLike[str] | Path,
    source_checkpoints: Sequence[str | os.PathLike[str] | Path] = (),
    solved_leaf_stores: Sequence[str | os.PathLike[str] | Path] = (),
    root_readout_stores: Sequence[str | os.PathLike[str] | Path] = (),
    oracle_path: str | os.PathLike[str] | Path | None = None,
    record_validator: RecordValidator | None = None,
    record_intake_assessor: RecordIntakeAssessor | None = None,
    checkpoint_finalizer: CheckpointFinalizer | None = None,
) -> RecoverySummary:
    """Recover all compatible terminal records without numerical work."""

    output = Path(output_path)
    receipt = Path(receipt_path)
    if output == receipt:
        raise ValueError("recovery output and receipt paths must differ")
    if output.exists() or receipt.exists():
        raise ValueError("recovery refuses to overwrite an existing destination")

    selected = set(selection.ordered_leaf_ids)
    candidates: dict[str, list[_Candidate]] = {}
    ignored: list[dict[str, object]] = []
    source_artifacts: list[dict[str, object]] = []
    root_readout_indices: list[dict[str, object]] = []
    legacy_compatibility_receipts: list[dict[str, object]] = []
    scientific_compatibility_receipts: list[dict[str, object]] = []
    legacy_authenticated_terminal_count = 0
    legacy_imported_count = 0
    legacy_rejected_count = 0
    legacy_unreconstructable_count = 0

    for raw_path in source_checkpoints:
        path = Path(raw_path)
        try:
            value = _read_json(path)
        except (OSError, ValueError) as error:
            raise ValueError(
                f"explicit source checkpoint is corrupt: {path}: {error}"
            ) from error
        source_sha = _file_sha256(path)
        source_artifacts.append(
            {"kind": "source-checkpoint", "path": str(path), "sha256": source_sha}
        )
        if not isinstance(value, Mapping):
            raise ValueError(f"explicit source checkpoint is corrupt: {path}")
        if value.get("schema_version") == 10:
            raise ValueError("schema-10 checkpoint is poisoned recovery input")
        if value.get("schema_version") == 9:
            try:
                schema9_checkpoint = _validated_schema9_checkpoint(value)
            except ValueError as error:
                raise ValueError(
                    f"explicit source checkpoint is corrupt: {path}: {error}"
                ) from error
            discovered, imported, rejected, unreconstructable = (
                _schema9_source_candidates(
                    path=path,
                    source_sha256=source_sha,
                    checkpoint=schema9_checkpoint,
                    selection=selection,
                    record_validator=record_validator,
                    candidates=candidates,
                    ignored=ignored,
                    compatibility_receipts=legacy_compatibility_receipts,
                )
            )
            legacy_authenticated_terminal_count += discovered
            legacy_imported_count += imported
            legacy_rejected_count += rejected
            legacy_unreconstructable_count += unreconstructable
            continue
        if value.get("schema_version") != 11:
            ignored.append(
                {
                    "path": str(path),
                    "reason": "INCOMPATIBLE_LEGACY_CHECKPOINT",
                }
            )
            continue
        try:
            checkpoint = migrate_fixed_root_endpoint_policy_checkpoint(value)
        except ValueError as error:
            raise ValueError(
                f"explicit source checkpoint is corrupt: {path}: {error}"
            ) from error
        if (
            checkpoint["campaign_id"] != selection.campaign_id
            or checkpoint["selection_id"] != selection.selection_id
        ):
            ignored.append(
                {"path": str(path), "reason": "INCOMPATIBLE_CHECKPOINT_IDENTITY"}
            )
            continue
        evidence_ledger = checkpoint["evidence_ledger"]
        assert isinstance(evidence_ledger, dict)
        for raw_record in checkpoint["records"]:
            leaf_id = raw_record["leaf_id"]
            if leaf_id not in selected:
                ignored.append(
                    {"path": str(path), "leaf_id": leaf_id, "reason": "OFF_SELECTION"}
                )
                continue
            try:
                record = _validated_record(
                    raw_record,
                    expected_role=selection.roles[leaf_id],
                    record_validator=None,
                )
                if (
                    record.get("schema")
                    == "windows-solver.schema11-numerical-record/1"
                    and record_intake_assessor is None
                ):
                    raise ValueError(
                        "schema-11 recovery requires central record intake"
                    )
                intake = (
                    None
                    if record_intake_assessor is None
                    else record_intake_assessor(leaf_id, record)
                )
                if intake is not None and not intake.response_admissible:
                    reason = str(
                        intake.reason_code
                        or "INCOMPATIBLE_SCIENTIFIC_IDENTITY"
                    )
                    if intake.forensic_only:
                        scientific_compatibility_receipts.append(
                            _stale_horizon_v2_receipt(
                                path=path,
                                source_sha256=source_sha,
                                checkpoint=checkpoint,
                                record=record,
                                selection=selection,
                                source_evidence=evidence_ledger.get(leaf_id),
                            )
                        )
                    ignored.append({
                        "path": str(path),
                        "leaf_id": leaf_id,
                        "reason": reason,
                    })
                    continue
                if record_intake_assessor is None and record_validator is not None:
                    record_validator(leaf_id, record)
            except ValueError as error:
                raise ValueError(
                    f"explicit source checkpoint is corrupt: {path}: {error}"
                ) from error
            candidates.setdefault(leaf_id, []).append(
                _Candidate(
                    leaf_id,
                    record,
                    str(path),
                    source_sha,
                    source_sha,
                    evidence_ledger.get(leaf_id),
                )
            )

    for raw_root in solved_leaf_stores:
        root = Path(raw_root)
        if not root.exists():
            ignored.append({"path": str(root), "reason": "MISSING_STORE"})
            continue
        if not root.is_dir():
            raise ValueError(f"solved-leaf store is not a directory: {root}")
        for path in sorted(root.glob("*.json"), key=lambda item: item.name):
            source_sha = _file_sha256(path)
            try:
                value = _read_json(path)
            except (OSError, ValueError) as error:
                if _HEX_64.fullmatch(path.stem) is not None:
                    raise ValueError(
                        f"trusted solved-leaf receipt is corrupt: {path}: {error}"
                    ) from error
                ignored.append({"path": str(path), "reason": "NON_CANDIDATE"})
                continue
            if not _candidate_like_solved_receipt(path, value):
                ignored.append({"path": str(path), "reason": "NON_CANDIDATE"})
                continue
            raw_leaf_id = value.get("leaf_id") if isinstance(value, Mapping) else None
            expected_role = selection.roles.get(raw_leaf_id)
            try:
                record, identity = _validated_solved_receipt(
                    value,
                    expected_role=expected_role,
                    record_validator=None,
                )
            except ValueError as error:
                raise ValueError(
                    f"trusted solved-leaf receipt is corrupt: {path}: {error}"
                ) from error
            leaf_id = record["leaf_id"]
            source_artifacts.append(
                {"kind": "solved-leaf-receipt", "path": str(path), "sha256": source_sha}
            )
            if leaf_id not in selected:
                ignored.append(
                    {"path": str(path), "leaf_id": leaf_id, "reason": "OFF_SELECTION"}
                )
                continue
            try:
                if (
                    record.get("schema")
                    == "windows-solver.schema11-numerical-record/1"
                    and record_intake_assessor is None
                ):
                    raise ValueError(
                        "schema-11 recovery requires central record intake"
                    )
                intake = (
                    None
                    if record_intake_assessor is None
                    else record_intake_assessor(leaf_id, record)
                )
                if intake is not None and not intake.response_admissible:
                    reason = str(
                        intake.reason_code
                        or "INCOMPATIBLE_SCIENTIFIC_IDENTITY"
                    )
                    if intake.forensic_only:
                        scientific_compatibility_receipts.append(
                            _stale_horizon_v2_receipt(
                                path=path,
                                source_sha256=source_sha,
                                checkpoint=None,
                                record=record,
                                selection=selection,
                                source_evidence=None,
                                source_kind="solved-leaf-store",
                            )
                        )
                    ignored.append({
                        "path": str(path),
                        "leaf_id": leaf_id,
                        "reason": reason,
                    })
                    continue
                if record_intake_assessor is None and record_validator is not None:
                    record_validator(leaf_id, record)
            except ValueError as error:
                raise ValueError(
                    f"trusted solved-leaf receipt is corrupt: {path}: {error}"
                ) from error
            if identity != selection.scientific_identities[leaf_id]:
                ignored.append(
                    {
                        "path": str(path),
                        "leaf_id": leaf_id,
                        "reason": "INCOMPATIBLE_SCIENTIFIC_IDENTITY",
                    }
                )
                continue
            candidates.setdefault(leaf_id, []).append(
                _Candidate(
                    leaf_id,
                    record,
                    str(path),
                    source_sha,
                    value["receipt_sha256"],
                )
            )

    for raw_root in root_readout_stores:
        root = Path(raw_root)
        if root.exists() and not root.is_dir():
            raise ValueError(f"root-readout store is not a directory: {root}")
        try:
            entries = RootReadoutStore(root).entries()
        except ValueError as error:
            raise ValueError(
                f"trusted root-readout store is corrupt: {root}: {error}"
            ) from error
        source_artifacts.append(
            {
                "kind": "root-readout-store",
                "path": str(root),
                "status": "AVAILABLE" if root.is_dir() else "MISSING",
            }
        )
        recovered_entries: list[dict[str, object]] = []
        for entry in entries:
            source_sha = _file_sha256(entry.path)
            try:
                recovered_entries.append(
                    _root_readout_recovery_entry(
                        entry=entry, source_sha256=source_sha
                    )
                )
            except ValueError as error:
                if "lacks a worker response receipt" in str(error):
                    ignored.append(
                        {
                            "path": str(entry.path),
                            "reason": "MISSING_WORKER_RESPONSE_RECEIPT",
                        }
                    )
                    continue
                raise ValueError(
                    "trusted root-readout entry is corrupt: "
                    f"{entry.path}: {error}"
                ) from error
            source_artifacts.append(
                {
                    "kind": "root-readout-entry",
                    "path": str(entry.path),
                    "sha256": source_sha,
                }
            )
        if recovered_entries:
            root_readout_indices.append(
                {
                    "schema": ROOT_READOUT_RECOVERY_INDEX_SCHEMA,
                    "store_path": str(root),
                    "entries": recovered_entries,
                }
            )

    candidate_checkpoint = empty_schema11_checkpoint(
        selection.campaign_id, selection.selection_id
    )
    candidate_checkpoint["recovery_receipts"].extend(root_readout_indices)
    candidate_checkpoint["recovery_receipts"].extend(legacy_compatibility_receipts)
    candidate_checkpoint["recovery_receipts"].extend(scientific_compatibility_receipts)
    accepted_receipts: list[dict[str, object]] = []
    for leaf_id in selection.ordered_leaf_ids:
        leaf_candidates = candidates.get(leaf_id, [])
        if not leaf_candidates:
            continue
        canonical_records = {
            canonical_json_bytes(item.record): item for item in leaf_candidates
        }
        if len(canonical_records) != 1:
            states = sorted({str(item.record["state"]) for item in leaf_candidates})
            raise ValueError(
                f"conflicting terminal records for {leaf_id}: states={states}"
            )
        record_bytes = next(iter(canonical_records))
        record = copy.deepcopy(dict(canonical_records[record_bytes].record))
        candidate_checkpoint = add_numerical_record(candidate_checkpoint, record)
        merged_evidence: Mapping[str, object] | None = None
        for item in sorted(leaf_candidates, key=lambda value: value.receipt_sha256):
            merged_evidence = _merge_evidence(merged_evidence, item.evidence)
        if merged_evidence is not None:
            candidate_checkpoint = record_evidence(
                candidate_checkpoint,
                leaf_id=leaf_id,
                central_record_sha256=merged_evidence["central_record_sha256"],
                central_stage_sha256=merged_evidence["central_stage_sha256"],
                evidence_level=EvidenceLevel(merged_evidence["evidence_level"]),
                receipts=merged_evidence["receipts"],
                discrepancy_codes=merged_evidence["discrepancy_codes"],
            )
        accepted_receipts.append(
            {
                "leaf_id": leaf_id,
                "record_sha256": record["record_sha256"],
                "candidate_receipt_sha256s": sorted(
                    {item.receipt_sha256 for item in leaf_candidates}
                ),
            }
        )

    recovered_count = len(candidate_checkpoint["records"])
    if (
        recovered_count == len(selection.ordered_leaf_ids)
        and all(
            record["state"] in {"PRODUCED", "UNRESOLVED"}
            for record in candidate_checkpoint["records"]
        )
    ):
        candidate_checkpoint["state"] = "COMPLETE"
    recovery_entry = {
        "schema": "windows-solver.recovery-summary/v1",
        "discovered_valid_unique_records": len(candidates),
        "recovered_records": recovered_count,
        "lost_valid_records": len(candidates) - recovered_count,
        "fabricated_records": 0,
        "record_hash_changes": 0,
        "discovery_counts": {
            "source_checkpoints_configured": len(source_checkpoints),
            "solved_leaf_stores_configured": len(solved_leaf_stores),
            "root_readout_stores_configured": len(root_readout_stores),
            "legacy_authenticated_terminal_records": (
                legacy_authenticated_terminal_count
            ),
            "legacy_current_compatible_records": legacy_imported_count,
            "legacy_reused_records": legacy_imported_count,
            "legacy_rejected_records": legacy_rejected_count,
        },
    }
    candidate_checkpoint["recovery_receipts"].append(recovery_entry)
    migrate_fixed_root_endpoint_policy_checkpoint(candidate_checkpoint)
    if checkpoint_finalizer is not None:
        scientific_sha256 = _checkpoint_scientific_sha256(candidate_checkpoint)
        candidate_checkpoint = migrate_fixed_root_endpoint_policy_checkpoint(
            checkpoint_finalizer(candidate_checkpoint, output)
        )
        if _checkpoint_scientific_sha256(candidate_checkpoint) != scientific_sha256:
            raise ValueError(
                "recovery checkpoint finalizer changed scientific checkpoint state"
            )

    oracle_status = _incident_oracle_status(oracle_path)
    receipt_content: dict[str, object] = {
        **recovery_entry,
        "schema": RECOVERY_RECEIPT_SCHEMA,
        "campaign_id": selection.campaign_id,
        "selection_id": selection.selection_id,
        "sources": sorted(
            source_artifacts,
            key=lambda item: (str(item.get("kind")), str(item.get("path"))),
        ),
        "accepted_records": accepted_receipts,
        "ignored_inputs": sorted(
            ignored,
            key=lambda item: (str(item.get("path")), str(item.get("leaf_id", ""))),
        ),
        "backend_constructions": 0,
        "julia_launches": 0,
        "determinant_evaluations": 0,
        "root_solves": 0,
        "source_mutations": 0,
        "oracle_status": oracle_status,
        "canary_x9_status": oracle_status,
        "output_sha256": _sha256(candidate_checkpoint),
    }
    recovery_receipt = {
        **receipt_content,
        "receipt_sha256": _sha256(receipt_content),
    }
    _atomic_json(output, candidate_checkpoint)
    try:
        _atomic_json(receipt, recovery_receipt)
    except BaseException:
        try:
            output.unlink()
        except FileNotFoundError:
            pass
        raise

    return RecoverySummary(
        campaign_id=selection.campaign_id,
        selection_id=selection.selection_id,
        discovered_valid_unique_count=len(candidates),
        recovered_count=recovered_count,
        lost_valid_count=len(candidates) - recovered_count,
        fabricated_count=0,
        ignored_count=len(ignored),
        output_path=str(output),
        receipt_path=str(receipt),
        legacy_authenticated_terminal_count=legacy_authenticated_terminal_count,
        legacy_imported_count=legacy_imported_count,
        legacy_rejected_count=legacy_rejected_count,
        legacy_unreconstructable_count=legacy_unreconstructable_count,
    )


def validate_recovery_checkpoint(
    selection: RecoverySelection,
    checkpoint_path: str | os.PathLike[str] | Path,
    *,
    record_validator: RecordValidator | None = None,
) -> dict[str, object]:
    """Validate a schema-11 recovery candidate from disk without numerics."""

    path = Path(checkpoint_path)
    try:
        value = _read_json(path)
    except (OSError, ValueError) as error:
        raise ValueError(f"recovery checkpoint is corrupt: {path}: {error}") from error
    if not isinstance(value, Mapping):
        raise ValueError("recovery checkpoint must be an object")
    checkpoint = migrate_fixed_root_endpoint_policy_checkpoint(value)
    if (
        checkpoint["campaign_id"] != selection.campaign_id
        or checkpoint["selection_id"] != selection.selection_id
    ):
        raise ValueError("recovery checkpoint selection identity is incompatible")
    selected = set(selection.ordered_leaf_ids)
    record_ids = [record["leaf_id"] for record in checkpoint["records"]]
    if any(leaf_id not in selected for leaf_id in record_ids):
        raise ValueError("recovery checkpoint contains an off-selection record")
    expected_order = [
        leaf_id for leaf_id in selection.ordered_leaf_ids if leaf_id in set(record_ids)
    ]
    if record_ids != expected_order:
        raise ValueError("recovery checkpoint records are not in selection order")
    for record in checkpoint["records"]:
        _validated_record(
            record,
            expected_role=selection.roles[record["leaf_id"]],
            record_validator=record_validator,
        )
    return checkpoint


def validate_recovery_receipt(
    selection: RecoverySelection,
    checkpoint_path: str | os.PathLike[str] | Path,
    receipt_path: str | os.PathLike[str] | Path,
) -> dict[str, object]:
    """Authenticate a recovery receipt and its exact candidate checkpoint."""

    checkpoint = Path(checkpoint_path)
    receipt = Path(receipt_path)
    try:
        value = _read_json(receipt)
    except (OSError, ValueError) as error:
        raise ValueError(f"recovery receipt is corrupt: {receipt}: {error}") from error
    if not isinstance(value, Mapping):
        raise ValueError("recovery receipt must be an object")
    receipt_value = dict(value)
    if receipt_value.get("schema") != RECOVERY_RECEIPT_SCHEMA:
        raise ValueError("recovery receipt schema is invalid")
    if (
        receipt_value.get("campaign_id") != selection.campaign_id
        or receipt_value.get("selection_id") != selection.selection_id
    ):
        raise ValueError("recovery receipt selection identity is incompatible")
    supplied_sha = receipt_value.pop("receipt_sha256", None)
    if not _is_sha256(supplied_sha) or supplied_sha != _sha256(receipt_value):
        raise ValueError("recovery receipt digest is invalid")
    if receipt_value.get("output_sha256") != _file_sha256(checkpoint):
        raise ValueError("recovery receipt does not bind the candidate checkpoint")
    return dict(value)


__all__ = [
    "ENDPOINT_RECOVERY_MIGRATION_IDENTITY",
    "ENDPOINT_RECOVERY_MIGRATION_SCHEMA",
    "M02_ENDPOINT_RECOVERY_KNOWN_AFFECTED_LEAF_ID",
    "M02_ENDPOINT_RECOVERY_KNOWN_AFFECTED_QUEUE_ORDINAL",
    "RECOVERY_RECEIPT_SCHEMA",
    "RecoverySelection",
    "RecoverySummary",
    "checkpoint_bound_promoted_recovery_selection",
    "migrate_fixed_root_endpoint_policy_checkpoint",
    "migrate_endpoint_recovery_checkpoint_file",
    "recover_campaign",
    "validate_checkpoint_bound_promoted_recovery_selection",
    "validate_recovery_checkpoint",
    "validate_recovery_receipt",
    "validate_endpoint_recovery_migration_receipt",
]
