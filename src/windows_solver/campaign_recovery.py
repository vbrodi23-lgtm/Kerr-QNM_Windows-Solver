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
    record_evidence,
    validate_schema11_checkpoint,
)
from .contracts import canonical_json_bytes
from .response_batches import CampaignLeafRecord
from .response_engine import _validated_worker_response_receipt
from .root_readout_cache import RootReadoutStore


RECOVERY_RECEIPT_SCHEMA = "windows-solver.campaign-recovery/v1"
ROOT_READOUT_RECOVERY_INDEX_SCHEMA = "windows-solver.root-readout-recovery-index/v1"
LEGACY_COMPATIBILITY_SCHEMA = "legacy-compatibility/v1"
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


def _schema9_current_binding_reason(
    checkpoint: Mapping[str, object], selection: RecoverySelection
) -> str | None:
    """Return why the old campaign cannot be claimed as the current one."""

    bindings = checkpoint["bindings"]
    assert isinstance(bindings, Mapping)
    source_selection = bindings["selection"]
    assert isinstance(source_selection, Mapping)
    if bindings["campaign_id"] != selection.campaign_id:
        return "CURRENT_CAMPAIGN_IDENTITY_MISMATCH"
    if source_selection["selection_id"] != selection.selection_id:
        return "CURRENT_SELECTION_IDENTITY_MISMATCH"
    source_leaf_ids = set(source_selection["leaf_ids"])
    if not set(selection.ordered_leaf_ids).issubset(source_leaf_ids):
        return "CURRENT_SELECTION_MEMBERSHIP_MISMATCH"
    return None


def _legacy_compatibility_receipt(
    *,
    path: Path,
    source_sha256: str,
    checkpoint: Mapping[str, object],
    record: Mapping[str, object],
    selection: RecoverySelection,
    imported: bool,
    reason: str | None,
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
        "leaf_id": leaf_id,
        "source_record_sha256": record["record_sha256"],
        "source_terminal_state": record["state"],
        "current_scientific_identity_sha256": selection.scientific_identities.get(
            leaf_id
        ),
        "original_record_status": "AUTHENTICATED",
        "imported_as_current_numerical_record": imported,
        "schema11_evidence_level": None,
        "reason": reason,
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
) -> tuple[int, int, int]:
    """Recover only schema-9 records whose current identity is proven.

    A terminal schema-9 record is authentic historical work, not automatically
    current scientific evidence.  When the current campaign identity cannot be
    reconstructed, retain a deterministic compatibility receipt and leave the
    numerical record out of the schema-11 checkpoint.
    """

    source_binding_reason = _schema9_current_binding_reason(checkpoint, selection)
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
            unreconstructable_count += 1
            continue

        reason = source_binding_reason
        if reason is None and record_validator is None:
            reason = "CURRENT_SCIENTIFIC_IDENTITY_VALIDATOR_NOT_SUPPLIED"
        if reason is None:
            try:
                validated = _validated_record(
                    record,
                    expected_role=selection.roles[leaf_id],
                    record_validator=record_validator,
                )
            except ValueError:
                reason = "CURRENT_SCIENTIFIC_IDENTITY_UNRECONSTRUCTABLE"
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
            )
        )
        ignored.append({"path": str(path), "leaf_id": leaf_id, "reason": reason})
        unreconstructable_count += 1
    return authenticated_terminal_count, imported_count, unreconstructable_count


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
    response = getattr(entry, "response", None)
    if (
        not _is_sha256(request_sha256)
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
    legacy_authenticated_terminal_count = 0
    legacy_imported_count = 0
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
            discovered, imported, unreconstructable = _schema9_source_candidates(
                path=path,
                source_sha256=source_sha,
                checkpoint=schema9_checkpoint,
                selection=selection,
                record_validator=record_validator,
                candidates=candidates,
                ignored=ignored,
                compatibility_receipts=legacy_compatibility_receipts,
            )
            legacy_authenticated_terminal_count += discovered
            legacy_imported_count += imported
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
            checkpoint = validate_schema11_checkpoint(value)
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
                    record_validator=record_validator,
                )
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
                    record_validator=(
                        record_validator if raw_leaf_id in selected else None
                    ),
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
            "legacy_rejected_records": legacy_unreconstructable_count,
        },
    }
    candidate_checkpoint["recovery_receipts"].append(recovery_entry)
    validate_schema11_checkpoint(candidate_checkpoint)
    if checkpoint_finalizer is not None:
        scientific_sha256 = _checkpoint_scientific_sha256(candidate_checkpoint)
        candidate_checkpoint = validate_schema11_checkpoint(
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
    checkpoint = validate_schema11_checkpoint(value)
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
    "RECOVERY_RECEIPT_SCHEMA",
    "RecoverySelection",
    "RecoverySummary",
    "recover_campaign",
    "validate_recovery_checkpoint",
    "validate_recovery_receipt",
]
