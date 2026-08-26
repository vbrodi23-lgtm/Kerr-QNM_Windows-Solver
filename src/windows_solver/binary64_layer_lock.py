"""Immutable Layer-1 binary64 handoff receipts for schema-11 campaigns."""

from __future__ import annotations

import copy
from dataclasses import dataclass
import hashlib
import json
import os
import re
from pathlib import Path
import tempfile
from typing import Mapping, Sequence
from types import MappingProxyType

from .campaign_policy import (
    PromotionQueueKind,
    SurveyDisposition,
    promotion_source_fingerprint_sha256,
    validate_schema11_checkpoint,
)
from .campaign_recovery import RecoverySelection
from .campaign_survey import binary64_pass_exhaustion
from .contracts import canonical_json_bytes


BINARY64_LAYER_LOCK_SCHEMA = "windows-solver.binary64-layer-lock/1"
BINARY64_LAYER_PROJECTION_SCHEMA = "windows-solver.binary64-layer-projection/1"
ROOT_EVIDENCE_STORE_IDENTITY = "windows-solver.root-evidence-store/v2"
CANONICAL_BACKGROUND_STORE_IDENTITY = (
    "windows-solver.canonical-background-evidence-store/v1"
)
ROOT_READOUT_STORE_IDENTITY = "windows-solver.root-readout-store/v2"

_HEX_64 = re.compile(r"[0-9a-f]{64}")
_LOCK_FIELDS = frozenset({
    "schema",
    "campaign_id",
    "selection_id",
    "checkpoint_schema_version",
    "ordered_leaf_ids",
    "source_checkpoint_sha256",
    "binary64_layer_projection_sha256",
    "binary64_pass_ledger_sha256",
    "promotion_source_projection_sha256",
    "source_record_projection_sha256",
    "auxiliary_evidence_manifest_sha256",
    "selected_leaf_count",
    "binary64_processed_count",
    "pending_promotion_count",
    "route_counts",
    "retained_sample_counts",
    "per_leaf_route_bindings",
    "receipt_sha256",
})
_EXTERIOR_REASON_CODES = frozenset({
    "BLOCKED_BY_REVIEWED_ERROR_EVIDENCE",
    "DETERMINANT_ERROR_EVIDENCE_UNAVAILABLE",
})


class Binary64LayerLockViolation(ValueError):
    """A Layer-2 entry attempted to consume changed Layer-1 source evidence."""


@dataclass(frozen=True, slots=True)
class LockedPromotionRoute:
    """One typed Layer-2 route authorized by the frozen binary64 source."""

    queue_ordinal: int
    leaf_id: str
    route: str
    minimum_requested_tier: str
    source_stage_sha256: str
    source_root_seal_sha256: str
    source_fingerprint_sha256: str
    provisional_stage: Mapping[str, object] | None


@dataclass(frozen=True, slots=True)
class Layer1Guard:
    """The sole authenticated gate for Layer-2 persistence and execution."""

    _lock: Mapping[str, object]
    _selection: RecoverySelection
    _leaf_mechanism_ids: Mapping[str, str]
    _auxiliary_evidence_manifest: tuple[Mapping[str, object], ...]
    locked_routes_by_ordinal: Mapping[int, LockedPromotionRoute]

    @classmethod
    def from_authenticated_lock(
        cls,
        lock: Mapping[str, object],
        checkpoint: Mapping[str, object],
        *,
        selection: RecoverySelection,
        leaf_mechanism_ids: Mapping[str, str],
        auxiliary_evidence_manifest: Sequence[Mapping[str, object]],
    ) -> "Layer1Guard":
        """Authenticate a lock once and expose only typed route bindings."""

        validated_lock = validate_binary64_layer_lock(
            lock,
            checkpoint,
            selection=selection,
            leaf_mechanism_ids=leaf_mechanism_ids,
            auxiliary_evidence_manifest=auxiliary_evidence_manifest,
        )
        value = validate_schema11_checkpoint(checkpoint)
        entries = {
            entry["queue_ordinal"]: entry
            for entry in value["promotion_queue"]["entries"]
        }
        routes: dict[int, LockedPromotionRoute] = {}
        for binding in validated_lock["per_leaf_route_bindings"]:
            if not isinstance(binding, Mapping):
                raise Binary64LayerLockViolation(
                    "BINARY64_LAYER_LOCK_VIOLATION: route binding is invalid"
                )
            ordinal = binding.get("queue_ordinal")
            entry = entries.get(ordinal)
            if (
                isinstance(ordinal, bool)
                or not isinstance(ordinal, int)
                or not isinstance(entry, Mapping)
                or entry.get("leaf_id") != binding.get("leaf_id")
                or entry.get("source_stage_sha256")
                != binding.get("source_stage_sha256")
                or entry.get("source_root_seal_sha256")
                != binding.get("source_root_seal_sha256")
            ):
                raise Binary64LayerLockViolation(
                    "BINARY64_LAYER_LOCK_VIOLATION: route binding diverges from queue"
                )
            source_fingerprint_sha256 = promotion_source_fingerprint_sha256(entry)
            if entry.get("source_fingerprint_sha256") != source_fingerprint_sha256:
                raise Binary64LayerLockViolation(
                    "BINARY64_LAYER_LOCK_VIOLATION: queue source fingerprint is invalid"
                )
            routes[ordinal] = LockedPromotionRoute(
                queue_ordinal=ordinal,
                leaf_id=str(binding["leaf_id"]),
                route=str(binding["route"]),
                minimum_requested_tier=str(binding["minimum_requested_tier"]),
                source_stage_sha256=str(binding["source_stage_sha256"]),
                source_root_seal_sha256=str(binding["source_root_seal_sha256"]),
                source_fingerprint_sha256=source_fingerprint_sha256,
                provisional_stage=(
                    None
                    if entry.get("provisional_stage") is None
                    else MappingProxyType(_copy(dict(entry["provisional_stage"])))
                ),
            )
        return cls(
            _lock=_copy(validated_lock),
            _selection=selection,
            _leaf_mechanism_ids=MappingProxyType(dict(leaf_mechanism_ids)),
            _auxiliary_evidence_manifest=tuple(
                _copy(dict(entry)) for entry in auxiliary_evidence_manifest
            ),
            locked_routes_by_ordinal=MappingProxyType(routes),
        )

    def assert_unchanged(
        self,
        checkpoint: Mapping[str, object],
        *,
        phase: str = "UNSPECIFIED",
    ) -> dict[str, object]:
        """Reject every persisted mutation of Layer-1 source state."""

        try:
            if phase not in {
                "UNSPECIFIED",
                "PRE_WRITE",
                "POST_WRITE",
                "POST_CALLBACK",
            }:
                raise ValueError("Layer-1 guard phase is invalid")
            validated = validate_binary64_layer_lock(
                self._lock,
                checkpoint,
                selection=self._selection,
                leaf_mechanism_ids=self._leaf_mechanism_ids,
                auxiliary_evidence_manifest=self._auxiliary_evidence_manifest,
            )
            value = validate_schema11_checkpoint(checkpoint)
            entries = {
                entry["queue_ordinal"]: entry
                for entry in value["promotion_queue"]["entries"]
            }
            if set(entries) != set(self.locked_routes_by_ordinal):
                raise ValueError("queue ordinals do not match the locked routes")
            for ordinal, route in self.locked_routes_by_ordinal.items():
                entry = entries[ordinal]
                if (
                    entry["leaf_id"] != route.leaf_id
                    or entry["source_stage_sha256"] != route.source_stage_sha256
                    or entry["source_root_seal_sha256"]
                    != route.source_root_seal_sha256
                    or promotion_source_fingerprint_sha256(entry)
                    != route.source_fingerprint_sha256
                ):
                    raise ValueError("queue source diverges from locked route")
            return validated
        except (KeyError, TypeError, ValueError) as error:
            raise Binary64LayerLockViolation(
                f"BINARY64_LAYER_LOCK_VIOLATION: {error}"
            ) from error

    def pre_write(self, checkpoint: Mapping[str, object]) -> dict[str, object]:
        """Validate Layer 1 before a scheduler makes a checkpoint durable."""

        return self.assert_unchanged(checkpoint, phase="PRE_WRITE")

    def post_write(self, checkpoint: Mapping[str, object]) -> dict[str, object]:
        """Revalidate Layer 1 immediately after the durable checkpoint write."""

        return self.assert_unchanged(checkpoint, phase="POST_WRITE")

    def post_callback(self, checkpoint: Mapping[str, object]) -> dict[str, object]:
        """Revalidate Layer 1 after a durable-write callback returns."""

        return self.assert_unchanged(checkpoint, phase="POST_CALLBACK")

    # Compatibility aliases for callers that adopted the initial guard draft.
    pre_persist = pre_write
    post_persist = post_callback


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _HEX_64.fullmatch(value) is not None


def _copy(value: object) -> object:
    return copy.deepcopy(value)


def binary64_layer_lock_path(checkpoint_path: Path) -> Path:
    """Return the sole deterministic sidecar address for a checkpoint lock."""

    return Path(f"{checkpoint_path}.binary64-lock.json")


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate binary64 lock JSON key: {key}")
        result[key] = value
    return result


def load_binary64_layer_lock(path: Path) -> dict[str, object]:
    """Load only canonical JSON bytes from a deterministic lock sidecar."""

    try:
        raw = Path(path).read_bytes()
        parsed = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"binary64 lock contains non-finite constant {value}")
            ),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"binary64 lock is unreadable: {path}: {error}") from error
    if not isinstance(parsed, Mapping):
        raise ValueError("binary64 lock must be a JSON object")
    value = dict(parsed)
    if canonical_json_bytes(value) != raw:
        raise ValueError("binary64 lock JSON is not canonical")
    return value


def write_binary64_layer_lock(path: Path, lock: Mapping[str, object]) -> None:
    """Atomically write a canonical lock sidecar after receipt construction."""

    if not isinstance(lock, Mapping):
        raise ValueError("binary64 lock is invalid")
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json_bytes(dict(lock)))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} is invalid")
    return value


def _require_nonempty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} is invalid")
    return value


def _manifest_key(value: object) -> bytes:
    return canonical_json_bytes(value)


def _normalise_auxiliary_evidence_manifest(
    manifest: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    seen: set[bytes] = set()
    for entry in manifest:
        if not isinstance(entry, Mapping) or set(entry) != {
            "logical_key",
            "object_schema",
            "object_sha256",
            "store_identity",
        }:
            raise ValueError("auxiliary evidence manifest entry is invalid")
        logical_key = _require_mapping(entry["logical_key"], "manifest logical key")
        key = _manifest_key(logical_key)
        if key in seen:
            raise ValueError("auxiliary evidence manifest key is duplicated")
        seen.add(key)
        object_schema = _require_nonempty_string(
            entry["object_schema"], "manifest object schema"
        )
        object_sha256 = entry["object_sha256"]
        if not _is_sha256(object_sha256):
            raise ValueError("manifest object digest is invalid")
        store_identity = _require_nonempty_string(
            entry["store_identity"], "manifest store identity"
        )
        normalized.append({
            "logical_key": _copy(dict(logical_key)),
            "object_schema": object_schema,
            "object_sha256": object_sha256,
            "store_identity": store_identity,
        })
    return sorted(normalized, key=canonical_json_bytes)


def build_binary64_layer_auxiliary_evidence_manifest(
    plan: object,
    checkpoint: Mapping[str, object],
    *,
    root_evidence_store: object,
    background_evidence_store: object,
) -> list[dict[str, object]]:
    """Read and bind the durable auxiliary objects named by Layer 1.

    This intentionally only reads evidence stores.  It neither constructs a
    numerical backend nor publishes any object, so the same manifest builder
    is safe for the zero-work lock command and promoted preflight.
    """

    from .response_engine import (
        BackgroundEquivalenceReceipt,
        CanonicalExteriorBackground,
    )
    from .root_evidence import RootDependencyKey
    from .root_readout_cache import RootReadoutStore

    value = validate_schema11_checkpoint(checkpoint)
    leaves = {leaf.leaf_id: leaf for leaf in getattr(plan, "leaves")}
    entries: dict[bytes, dict[str, object]] = {}

    def add(entry: dict[str, object]) -> None:
        key = _manifest_key(entry["logical_key"])
        prior = entries.get(key)
        if prior is not None and prior != entry:
            raise ValueError("auxiliary evidence manifest has a conflicting key")
        entries[key] = entry

    for queue_entry in value["promotion_queue"]["entries"]:
        leaf_id = _require_nonempty_string(queue_entry.get("leaf_id"), "promotion leaf ID")
        leaf = leaves.get(leaf_id)
        if leaf is None:
            raise ValueError("promotion leaf is absent from the campaign plan")
        root_seal_sha256 = queue_entry.get("source_root_seal_sha256")
        if not _is_sha256(root_seal_sha256):
            raise ValueError("promotion source root seal is invalid")
        root_evidence = root_evidence_store.lookup(RootDependencyKey.from_leaf(leaf))
        if root_evidence is None:
            raise ValueError("required root evidence is unavailable")
        root_evidence.validate_for(leaf)
        if root_evidence.root_seal_sha256 != root_seal_sha256:
            raise ValueError("root evidence does not match the promotion source")
        root_mapping = root_evidence.to_mapping()
        add({
            "logical_key": {
                "kind": "root-evidence",
                "root_seal_sha256": root_seal_sha256,
            },
            "object_schema": str(root_mapping["schema"]),
            "object_sha256": root_evidence.root_seal_sha256,
            "store_identity": ROOT_EVIDENCE_STORE_IDENTITY,
        })

        stage = queue_entry.get("provisional_stage")
        if stage is None:
            continue
        stage_mapping = _require_mapping(stage, "promotion provisional stage")
        if stage_mapping.get("operation_identity") != "binary64-fixed-root-provisional/v1":
            continue
        background = CanonicalExteriorBackground.from_mapping(
            stage_mapping.get("canonical_background")
        )
        expected_receipt = BackgroundEquivalenceReceipt.from_mapping(
            stage_mapping.get("background_reuse_receipt")
        )
        lookup = background_evidence_store.lookup(leaf.job, background.reuse_key)
        if (
            getattr(lookup, "background", None) != background
            or getattr(lookup, "receipt", None) != expected_receipt
        ):
            raise ValueError("required canonical background evidence is unavailable")
        background_mapping = background.to_mapping()
        add({
            "logical_key": {
                "kind": "canonical-background",
                "background_sha256": background.sha256,
            },
            "object_schema": str(background_mapping["schema"]),
            "object_sha256": background.sha256,
            "store_identity": CANONICAL_BACKGROUND_STORE_IDENTITY,
        })

    # Recovery indexes name durable root-readout entries by a self-addressed
    # request/runtime identity.  The cache file has a creation timestamp, so
    # that file digest is deliberately not lock material.
    for receipt in value["recovery_receipts"]:
        if not isinstance(receipt, Mapping) or receipt.get("schema") != (
            "windows-solver.root-readout-recovery-index/v1"
        ):
            continue
        if set(receipt) != {"schema", "store_path", "entries"}:
            raise ValueError("root-readout recovery index fields are invalid")
        store_path = _require_nonempty_string(
            receipt.get("store_path"), "root-readout store path"
        )
        references = receipt.get("entries")
        if not isinstance(references, list):
            raise ValueError("root-readout recovery index entries are invalid")
        observed = {
            item.readout_identity_sha256: item
            for item in RootReadoutStore(store_path).entries()
        }
        for reference in references:
            if not isinstance(reference, Mapping) or set(reference) != {
                "path",
                "source_sha256",
                "readout_identity_sha256",
                "request_sha256",
                "runtime_identity_sha256",
                "worker_response_receipt_sha256",
            }:
                raise ValueError("root-readout recovery reference is invalid")
            identity = reference.get("readout_identity_sha256")
            if (
                not isinstance(reference.get("path"), str)
                or not reference["path"]
                or any(
                    not _is_sha256(reference.get(field))
                    for field in (
                        "source_sha256",
                        "readout_identity_sha256",
                        "request_sha256",
                        "runtime_identity_sha256",
                        "worker_response_receipt_sha256",
                    )
                )
            ):
                raise ValueError("root-readout recovery identity is invalid")
            entry = observed.get(identity)
            if (
                entry is None
                or entry.request_sha256 != reference.get("request_sha256")
                or entry.runtime_identity_sha256
                != reference.get("runtime_identity_sha256")
                or not isinstance(entry.worker_response_receipt, Mapping)
                or entry.worker_response_receipt.get("receipt_sha256")
                != reference.get("worker_response_receipt_sha256")
            ):
                raise ValueError("root-readout recovery reference is unavailable")
            add({
                "logical_key": {
                    "kind": "root-readout",
                    "readout_identity_sha256": identity,
                },
                "object_schema": "windows-solver.root-readout-cache/2",
                "object_sha256": identity,
                "store_identity": ROOT_READOUT_STORE_IDENTITY,
            })
    return _normalise_auxiliary_evidence_manifest(list(entries.values()))


def _manifest_index(
    manifest: Sequence[Mapping[str, object]],
) -> dict[bytes, Mapping[str, object]]:
    return {_manifest_key(item["logical_key"]): item for item in manifest}


def _require_manifest_entry(
    manifest: Mapping[bytes, Mapping[str, object]],
    logical_key: Mapping[str, object],
    *,
    object_sha256: str,
    subject: str,
) -> Mapping[str, object]:
    entry = manifest.get(_manifest_key(logical_key))
    if entry is None:
        raise ValueError("required auxiliary evidence is absent from the lock")
    if entry["object_sha256"] != object_sha256:
        raise ValueError(f"{subject} manifest digest is incompatible")
    return entry


def _sample_counts(stage: Mapping[str, object]) -> tuple[int, int]:
    raw = stage.get("raw_sample_count")
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise ValueError("provisional raw sample count is invalid")
    combined = stage.get("combined_sample_count")
    if combined is None:
        roles = stage.get("combined_sample_roles")
        if not isinstance(roles, list):
            raise ValueError("provisional combined sample count is invalid")
        combined = len(roles)
    if isinstance(combined, bool) or not isinstance(combined, int) or combined < raw:
        raise ValueError("provisional combined sample count is invalid")
    return raw, combined


def _route_binding(
    entry: Mapping[str, object],
    *,
    leaf_mechanism_ids: Mapping[str, str],
    manifest: Mapping[bytes, Mapping[str, object]],
    records_by_sha: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    leaf_id = _require_nonempty_string(entry.get("leaf_id"), "promotion leaf ID")
    mechanism = _require_nonempty_string(
        leaf_mechanism_ids.get(leaf_id), "promotion mechanism"
    )
    if entry.get("queue_kind") != PromotionQueueKind.RESPONSE.value:
        raise ValueError("binary64 lock cannot include a ROOT promotion")
    root_seal_sha256 = entry.get("source_root_seal_sha256")
    if not _is_sha256(root_seal_sha256):
        raise ValueError("promotion source root seal is invalid")
    _require_manifest_entry(
        manifest,
        {"kind": "root-evidence", "root_seal_sha256": root_seal_sha256},
        object_sha256=root_seal_sha256,
        subject="root evidence",
    )
    stage_sha256 = entry.get("source_stage_sha256")
    if not _is_sha256(stage_sha256):
        raise ValueError("promotion source stage digest is invalid")
    reason_code = _require_nonempty_string(entry.get("reason_code"), "promotion reason")
    minimum_tier = _require_nonempty_string(
        entry.get("minimum_requested_tier"), "promotion minimum tier"
    )
    scientific_identity = entry.get("scientific_computation_identity")
    receipt_sha256 = entry.get("source_binary64_disposition_receipt_sha256")
    queue_ordinal = entry.get("queue_ordinal")
    if (
        not _is_sha256(scientific_identity)
        or not _is_sha256(receipt_sha256)
        or isinstance(queue_ordinal, bool)
        or not isinstance(queue_ordinal, int)
        or queue_ordinal < 0
    ):
        raise ValueError("promotion source binding is invalid")

    provisional = entry.get("provisional_stage")
    if provisional is not None:
        stage = _require_mapping(provisional, "provisional stage")
        if (
            stage.get("stage_sha256") != stage_sha256
            or entry.get("provisional_stage_sha256") != stage_sha256
        ):
            raise ValueError("promotion source stage digest is invalid")
        stage_content = {
            key: value for key, value in stage.items() if key != "stage_sha256"
        }
        if _sha256(stage_content) != stage_sha256:
            raise ValueError("promotion provisional stage authentication failed")
        operation = _require_nonempty_string(
            entry.get("provisional_operation_identity"),
            "provisional operation identity",
        )
        if stage.get("operation_identity") != operation:
            raise ValueError("promotion provisional operation identity is invalid")
        source_kind = "provisional-stage"
    else:
        source_record_sha256 = entry.get("source_record_sha256")
        if not _is_sha256(source_record_sha256):
            raise ValueError("horizon promotion source record is invalid")
        source_record = records_by_sha.get(source_record_sha256)
        if source_record is None:
            raise ValueError("horizon promotion source record is absent")
        stages = source_record.get("stages")
        if not isinstance(stages, list):
            raise ValueError("horizon promotion source stages are invalid")
        candidates = [
            value
            for value in stages
            if isinstance(value, Mapping) and value.get("stage_sha256") == stage_sha256
        ]
        if len(candidates) != 1:
            raise ValueError("horizon promotion source stage is absent")
        stage = candidates[0]
        operation = _require_nonempty_string(
            stage.get("operation_identity"), "horizon source operation identity"
        )
        source_kind = "source-record"

    if operation == "binary64-fixed-root-provisional/v1":
        if source_kind != "provisional-stage":
            raise ValueError("exterior route requires a provisional source stage")
        if (
            stage.get("scientific_computation_identity") != scientific_identity
            or stage.get("root_seal_sha256") != root_seal_sha256
        ):
            raise ValueError("promotion provisional stage source binding is invalid")
        raw_sample_count, combined_sample_count = _sample_counts(stage)
        if reason_code not in _EXTERIOR_REASON_CODES or minimum_tier != "BF40":
            raise ValueError("promotion route is not a reviewed Layer-1 route")
        if stage.get("mechanism_id") != mechanism:
            raise ValueError("exterior provisional mechanism is incompatible")
        if (raw_sample_count, combined_sample_count) not in {(9, 9), (4, 9)}:
            raise ValueError("exterior provisional sample topology is invalid")
        background = _require_mapping(
            stage.get("canonical_background"), "canonical background"
        )
        background_sha256 = _sha256(background)
        _require_manifest_entry(
            manifest,
            {
                "kind": "canonical-background",
                "background_sha256": background_sha256,
            },
            object_sha256=background_sha256,
            subject="canonical background",
        )
        reuse_key = background.get("reuse_key")
        if reuse_key is not None and not isinstance(reuse_key, Mapping):
            raise ValueError("canonical background reuse key is invalid")
        route = "EXTERIOR_BF40"
    elif operation == "binary64-horizon-production/v3":
        if (
            mechanism != "horizon-admittance"
            or reason_code != "ROOT_UNCERTAINTY_EVIDENCE_UNAVAILABLE"
            or minimum_tier != "BF80"
        ):
            raise ValueError("promotion route is not a reviewed Layer-1 route")
        route = "HORIZON_BF80"
        reuse_key = None
        raw_sample_count = 0
        combined_sample_count = 0
    else:
        raise ValueError("promotion route is not a reviewed Layer-1 route")
    return {
        "leaf_id": leaf_id,
        "leaf_ordinal": None,
        "mechanism": mechanism,
        "queue_ordinal": queue_ordinal,
        "queue_kind": PromotionQueueKind.RESPONSE.value,
        "reason_code": reason_code,
        "minimum_requested_tier": minimum_tier,
        "route": route,
        "scientific_computation_identity": scientific_identity,
        "source_stage_sha256": stage_sha256,
        "source_root_seal_sha256": root_seal_sha256,
        "binary64_disposition_receipt_sha256": receipt_sha256,
        "provisional_operation_identity": operation,
        "raw_sample_count": raw_sample_count,
        "combined_sample_count": combined_sample_count,
        "background_reuse_key": None if reuse_key is None else _copy(dict(reuse_key)),
    }


def project_binary64_layer(
    checkpoint: Mapping[str, object],
    *,
    selection: RecoverySelection,
    leaf_mechanism_ids: Mapping[str, str],
    auxiliary_evidence_manifest: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Return the deterministic Layer-1 projection, excluding Layer-2 state."""

    value = validate_schema11_checkpoint(checkpoint)
    if (
        value["campaign_id"] != selection.campaign_id
        or value["selection_id"] != selection.selection_id
    ):
        raise ValueError("checkpoint and selection identities are incompatible")
    ordered_leaf_ids = tuple(selection.ordered_leaf_ids)
    if set(leaf_mechanism_ids) != set(ordered_leaf_ids):
        raise ValueError("Layer-1 mechanisms do not cover the exact selection")
    binary64_ledger = value["survey_pass_ledger"]["binary64"]
    if set(binary64_ledger) != set(ordered_leaf_ids):
        raise ValueError("binary64 pass does not exactly cover the selection")
    manifest = _normalise_auxiliary_evidence_manifest(auxiliary_evidence_manifest)
    manifest_by_key = _manifest_index(manifest)
    entries = value["promotion_queue"]["entries"]
    records_by_sha = {
        record["record_sha256"]: record for record in value["records"]
    }
    queue_by_leaf: dict[str, Mapping[str, object]] = {}
    source_entries: list[dict[str, object]] = []
    bindings: list[dict[str, object]] = []
    for entry in entries:
        leaf_id = _require_nonempty_string(entry.get("leaf_id"), "promotion leaf ID")
        if leaf_id not in set(ordered_leaf_ids):
            raise ValueError("promotion queue contains an off-selection leaf")
        if leaf_id in queue_by_leaf:
            raise ValueError("promotion queue duplicates a selected leaf")
        queue_by_leaf[leaf_id] = entry
        binding = _route_binding(
            entry,
            leaf_mechanism_ids=leaf_mechanism_ids,
            manifest=manifest_by_key,
            records_by_sha=records_by_sha,
        )
        binding["leaf_ordinal"] = ordered_leaf_ids.index(leaf_id)
        pass_entry = binary64_ledger[leaf_id]
        if (
            pass_entry["disposition"]
            != SurveyDisposition.PROMOTION_PENDING_RESPONSE.value
            or pass_entry["disposition_receipt_sha256"]
            != binding["binary64_disposition_receipt_sha256"]
            or pass_entry["reason_code"] != binding["reason_code"]
        ):
            raise ValueError("promotion source does not match its binary64 disposition")
        if binding["scientific_computation_identity"] != selection.scientific_identities[
            leaf_id
        ]:
            raise ValueError("promotion scientific identity is incompatible")
        bindings.append(binding)
        source_entries.append({
            "leaf_id": leaf_id,
            "queue_kind": entry["queue_kind"],
            "source_pass": "binary64",
            "reason_code": entry["reason_code"],
            "minimum_requested_tier": entry["minimum_requested_tier"],
            "source_record_sha256": entry["source_record_sha256"],
            "source_stage_sha256": entry["source_stage_sha256"],
            "source_root_seal_sha256": entry["source_root_seal_sha256"],
            "scientific_computation_identity": entry["scientific_computation_identity"],
            "provisional_stage": _copy(entry["provisional_stage"]),
            "provisional_stage_sha256": entry["provisional_stage_sha256"],
            "provisional_operation_identity": entry[
                "provisional_operation_identity"
            ],
            "source_binary64_disposition_receipt_sha256": entry[
                "source_binary64_disposition_receipt_sha256"
            ],
            "queue_ordinal": entry["queue_ordinal"],
        })
    source_entries.sort(key=lambda item: int(item["queue_ordinal"]))
    bindings.sort(key=lambda item: int(item["queue_ordinal"]))
    source_record_shas = {
        digest
        for pass_entry in binary64_ledger.values()
        for digest in (pass_entry["result_record_sha256"],)
        if isinstance(digest, str)
    } | {
        digest
        for entry in source_entries
        for digest in (entry["source_record_sha256"],)
        if isinstance(digest, str)
    }
    if not source_record_shas <= set(records_by_sha):
        raise ValueError("Layer-1 source record is absent from the checkpoint")
    source_records = [
        _copy(records_by_sha[digest]) for digest in sorted(source_record_shas)
    ]
    return {
        "schema": BINARY64_LAYER_PROJECTION_SCHEMA,
        "checkpoint_schema_version": value["schema_version"],
        "campaign_id": value["campaign_id"],
        "selection_id": value["selection_id"],
        "ordered_leaf_ids": list(ordered_leaf_ids),
        "binary64_pass_ledger": [
            _copy(binary64_ledger[leaf_id]) for leaf_id in ordered_leaf_ids
        ],
        "promotion_source_entries": source_entries,
        "source_records": source_records,
        "auxiliary_evidence_manifest": manifest,
        "per_leaf_route_bindings": bindings,
    }


def _build_lock_receipt(
    checkpoint: Mapping[str, object], projection: Mapping[str, object]
) -> dict[str, object]:
    bindings = projection["per_leaf_route_bindings"]
    assert isinstance(bindings, list)
    route_counts = {
        "EXTERIOR_BF40": sum(
            binding["route"] == "EXTERIOR_BF40" for binding in bindings
        ),
        "HORIZON_BF80": sum(
            binding["route"] == "HORIZON_BF80" for binding in bindings
        ),
    }
    full_exterior = sum(
        binding["route"] == "EXTERIOR_BF40"
        and binding["raw_sample_count"] == binding["combined_sample_count"]
        for binding in bindings
    )
    reused_exterior = sum(
        binding["route"] == "EXTERIOR_BF40"
        and binding["raw_sample_count"] < binding["combined_sample_count"]
        for binding in bindings
    )
    content = {
        "schema": BINARY64_LAYER_LOCK_SCHEMA,
        "campaign_id": projection["campaign_id"],
        "selection_id": projection["selection_id"],
        "checkpoint_schema_version": projection["checkpoint_schema_version"],
        "ordered_leaf_ids": _copy(projection["ordered_leaf_ids"]),
        "source_checkpoint_sha256": _sha256(checkpoint),
        "binary64_layer_projection_sha256": _sha256(projection),
        "binary64_pass_ledger_sha256": _sha256(projection["binary64_pass_ledger"]),
        "promotion_source_projection_sha256": _sha256(
            projection["promotion_source_entries"]
        ),
        "source_record_projection_sha256": _sha256(projection["source_records"]),
        "auxiliary_evidence_manifest_sha256": _sha256(
            projection["auxiliary_evidence_manifest"]
        ),
        "selected_leaf_count": len(projection["ordered_leaf_ids"]),
        "binary64_processed_count": len(projection["binary64_pass_ledger"]),
        "pending_promotion_count": len(bindings),
        "route_counts": route_counts,
        "retained_sample_counts": {
            "full_exterior_nine_sample_acquisitions": full_exterior,
            "reused_exterior_four_sample_acquisitions": reused_exterior,
            "retained_binary64_determinant_evaluations": sum(
                binding["raw_sample_count"]
                for binding in bindings
                if binding["route"] == "EXTERIOR_BF40"
            ),
        },
        "per_leaf_route_bindings": _copy(bindings),
    }
    return {**content, "receipt_sha256": _sha256(content)}


def build_binary64_layer_lock(
    checkpoint: Mapping[str, object],
    *,
    selection: RecoverySelection,
    leaf_mechanism_ids: Mapping[str, str],
    auxiliary_evidence_manifest: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Authenticate an exhausted, clean Layer-1 handoff and freeze its receipt."""

    value = validate_schema11_checkpoint(checkpoint)
    if value["survey_pass_ledger"]["promoted"]:
        raise ValueError("cannot create a binary64 lock after promoted work exists")
    if value["system_failures"]:
        raise ValueError("cannot create a binary64 lock with system failures")
    exhaustion = binary64_pass_exhaustion(value, selection)
    if not exhaustion.exhausted:
        raise ValueError(
            "cannot create a binary64 lock before the binary64 pass is exhausted"
        )
    projection = project_binary64_layer(
        value,
        selection=selection,
        leaf_mechanism_ids=leaf_mechanism_ids,
        auxiliary_evidence_manifest=auxiliary_evidence_manifest,
    )
    return _build_lock_receipt(value, projection)


def validate_binary64_layer_lock(
    lock: Mapping[str, object],
    checkpoint: Mapping[str, object],
    *,
    selection: RecoverySelection,
    leaf_mechanism_ids: Mapping[str, str],
    auxiliary_evidence_manifest: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Validate a receipt and prove the supplied checkpoint retains Layer 1."""

    try:
        if not isinstance(lock, Mapping) or set(lock) != _LOCK_FIELDS:
            raise ValueError("binary64 lock fields are invalid")
        content = {key: value for key, value in lock.items() if key != "receipt_sha256"}
        if (
            lock.get("schema") != BINARY64_LAYER_LOCK_SCHEMA
            or not _is_sha256(lock.get("receipt_sha256"))
            or lock["receipt_sha256"] != _sha256(content)
        ):
            raise ValueError("binary64 lock receipt authentication failed")
        projection = project_binary64_layer(
            checkpoint,
            selection=selection,
            leaf_mechanism_ids=leaf_mechanism_ids,
            auxiliary_evidence_manifest=auxiliary_evidence_manifest,
        )
        expected = _build_lock_receipt(checkpoint, projection)
        for field in (
            "campaign_id",
            "selection_id",
            "checkpoint_schema_version",
            "ordered_leaf_ids",
            "binary64_layer_projection_sha256",
            "binary64_pass_ledger_sha256",
            "promotion_source_projection_sha256",
            "source_record_projection_sha256",
            "auxiliary_evidence_manifest_sha256",
            "selected_leaf_count",
            "binary64_processed_count",
            "pending_promotion_count",
            "route_counts",
            "retained_sample_counts",
            "per_leaf_route_bindings",
        ):
            if lock[field] != expected[field]:
                raise ValueError(f"binary64 lock mismatch: {field}")
        return _copy(dict(lock))
    except Binary64LayerLockViolation:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise Binary64LayerLockViolation(
            f"BINARY64_LAYER_LOCK_VIOLATION: {error}"
        ) from error


def assert_binary64_layer_unchanged(
    lock: Mapping[str, object],
    checkpoint: Mapping[str, object],
    *,
    selection: RecoverySelection,
    leaf_mechanism_ids: Mapping[str, str],
    auxiliary_evidence_manifest: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Raise a typed failure unless the current checkpoint preserves Layer 1."""

    return validate_binary64_layer_lock(
        lock,
        checkpoint,
        selection=selection,
        leaf_mechanism_ids=leaf_mechanism_ids,
        auxiliary_evidence_manifest=auxiliary_evidence_manifest,
    )


__all__ = [
    "BINARY64_LAYER_LOCK_SCHEMA",
    "BINARY64_LAYER_PROJECTION_SCHEMA",
    "CANONICAL_BACKGROUND_STORE_IDENTITY",
    "Layer1Guard",
    "LockedPromotionRoute",
    "ROOT_EVIDENCE_STORE_IDENTITY",
    "ROOT_READOUT_STORE_IDENTITY",
    "Binary64LayerLockViolation",
    "assert_binary64_layer_unchanged",
    "binary64_layer_lock_path",
    "build_binary64_layer_auxiliary_evidence_manifest",
    "build_binary64_layer_lock",
    "load_binary64_layer_lock",
    "project_binary64_layer",
    "validate_binary64_layer_lock",
    "write_binary64_layer_lock",
]
