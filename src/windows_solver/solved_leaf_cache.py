"""Private, per-user storage for authenticated terminal campaign leaves."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from types import MappingProxyType
from typing import Mapping, Sequence

from .contracts import canonical_json_bytes
from .evidence_discovery import EvidenceDiscovery, EvidenceDiscoveryStatus


SOLVED_LEAF_CACHE_SCHEMA_VERSION = 1
_STORE_DIRECTORY_NAME = "solved-leaves-" + "v" + str(
    SOLVED_LEAF_CACHE_SCHEMA_VERSION
)
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_TERMINAL_STATES = frozenset({"PRODUCED", "UNRESOLVED"})
_SCHEMA11_NUMERICAL_RECORD = "windows-solver.schema11-numerical-record/1"
_SOURCE_TYPES = frozenset({
    "originating-campaign",
    "imported-authenticated-checkpoint",
})
_RECEIPT_FIELDS = frozenset({
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
})


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    output: dict[str, object] = {}
    for key, value in pairs:
        if key in output:
            raise ValueError(f"duplicate solved-leaf cache JSON key: {key}")
        output[key] = value
    return output


def _load_json(path: Path) -> object:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda item: (_ for _ in ()).throw(
                ValueError(f"solved-leaf cache contains non-finite constant {item}")
            ),
        )
    except json.JSONDecodeError as error:
        raise ValueError("solved-leaf cache entry is not valid JSON") from error


def _is_cacheable_terminal_record(
    record: Mapping[str, object], *, state: object, stages: object
) -> bool:
    """Accept both historical leaf records and current schema-11 survey records.

    Schema-11 survey records deliberately do not carry the historical
    ``computed`` field.  They are nevertheless immutable terminal numerical
    evidence once their own record digest and current campaign validation pass.
    """

    if record.get("schema") == _SCHEMA11_NUMERICAL_RECORD:
        return state == "PRODUCED" and isinstance(stages, list) and bool(stages)
    return (
        state in _TERMINAL_STATES
        and record.get("computed") is True
        and isinstance(stages, list)
        and bool(stages)
    )


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


class SolvedLeafLookupStatus(StrEnum):
    MISSING = "missing"
    HIT = "hit"
    STALE = "stale"
    CORRUPT = "corrupt"


@dataclass(frozen=True, slots=True)
class SolvedLeafLookup:
    status: SolvedLeafLookupStatus
    path: Path | None = None
    receipt: Mapping[str, object] | None = None
    reason: str | None = None
    discovery: EvidenceDiscovery = field(
        default_factory=EvidenceDiscovery.not_attempted
    )


@dataclass(frozen=True, slots=True)
class SolvedLeafStoreDiscovery:
    """One authenticated inventory of a configured solved-leaf store.

    A pass consumes this inventory once, then selects exact compatible entries
    from it for each leaf.  That avoids reporting the same physical store as
    newly discovered for every requested leaf.
    """

    lookups: Mapping[str, SolvedLeafLookup]
    discovery: EvidenceDiscovery
    source_error: str | None = None

    def lookup_for(self, scientific_identity_sha256: str) -> SolvedLeafLookup:
        try:
            return self.lookups[scientific_identity_sha256]
        except KeyError as error:
            raise ValueError("solved-leaf discovery request is unknown") from error


class SolvedLeafStore:
    """One independently authenticated receipt per leaf computation identity."""

    def __init__(self, root: str | os.PathLike[str] | Path) -> None:
        self.root = Path(root)

    @classmethod
    def default(cls) -> "SolvedLeafStore":
        """Return the fixed per-user production store for this platform."""

        local = os.environ.get("LOCALAPPDATA")
        if local:
            return cls(
                Path(local)
                / "Kerr-QNM_Windows-Solver"
                / _STORE_DIRECTORY_NAME
            )
        data = os.environ.get("XDG_DATA_HOME")
        base = Path(data) if data else Path.home() / ".local" / "share"
        return cls(base / "Kerr-QNM_Windows-Solver" / _STORE_DIRECTORY_NAME)

    @property
    def stored_count(self) -> int:
        if not self.root.is_dir():
            return 0
        return sum(path.is_file() for path in self.root.glob("*.json"))

    def _entry_path(self, scientific_identity_sha256: str) -> Path:
        if _HEX_64.fullmatch(scientific_identity_sha256) is None:
            raise ValueError("scientific computation identity SHA-256 is invalid")
        return self.root / f"{scientific_identity_sha256}.json"

    @staticmethod
    def _validate_receipt(value: object) -> Mapping[str, object]:
        if not isinstance(value, Mapping) or set(value) != _RECEIPT_FIELDS:
            raise ValueError("solved-leaf cache receipt fields are invalid")
        if value["schema_version"] != SOLVED_LEAF_CACHE_SCHEMA_VERSION:
            raise ValueError("solved-leaf cache schema is invalid")
        identity = value["scientific_computation_identity_sha256"]
        record_sha = value["canonical_leaf_record_sha256"]
        if (
            not isinstance(identity, str)
            or _HEX_64.fullmatch(identity) is None
            or not isinstance(record_sha, str)
            or _HEX_64.fullmatch(record_sha) is None
        ):
            raise ValueError("solved-leaf cache digest field is invalid")
        leaf_id = value["leaf_id"]
        if not isinstance(leaf_id, str) or not leaf_id:
            raise ValueError("solved-leaf cache leaf ID is invalid")
        state = value["terminal_state"]
        if state not in _TERMINAL_STATES:
            raise ValueError("solved-leaf cache state is not terminal")
        stages = value["stage_count"]
        if isinstance(stages, bool) or not isinstance(stages, int) or stages < 1:
            raise ValueError("solved-leaf cache stage count is invalid")
        if value["source_type"] not in _SOURCE_TYPES:
            raise ValueError("solved-leaf cache source type is invalid")
        if not isinstance(value["created_utc"], str) or not value["created_utc"]:
            raise ValueError("solved-leaf cache creation timestamp is invalid")
        record = value["record"]
        if not isinstance(record, Mapping):
            raise ValueError("solved-leaf cache record is invalid")
        if (
            record.get("leaf_id") != leaf_id
            or record.get("state") != state
            or not _is_cacheable_terminal_record(
                record, state=state, stages=record.get("stages")
            )
            or len(record["stages"]) != stages
            or record.get("record_sha256") != record_sha
        ):
            raise ValueError("solved-leaf cache receipt disagrees with its record")
        record_content = {
            key: item for key, item in record.items() if key != "record_sha256"
        }
        if _sha256(record_content) != record_sha:
            raise ValueError("solved-leaf cache canonical record digest is invalid")
        sealed = {
            key: item for key, item in value.items() if key != "receipt_sha256"
        }
        if value["receipt_sha256"] != _sha256(sealed):
            raise ValueError("solved-leaf cache outer receipt digest is invalid")
        return value

    def lookup(
        self, scientific_identity_sha256: str, leaf_id: str
    ) -> SolvedLeafLookup:
        lookup = self.lookup_readonly(scientific_identity_sha256, leaf_id)
        if (
            lookup.status is SolvedLeafLookupStatus.CORRUPT
            and lookup.path is not None
        ):
            self.quarantine(lookup.path, str(lookup.reason))
        return lookup

    def lookup_readonly(
        self, scientific_identity_sha256: str, leaf_id: str
    ) -> SolvedLeafLookup:
        """Inspect one cache identity without moving or rewriting any source file."""

        inventory = self.discover_many(((scientific_identity_sha256, leaf_id),))
        lookup = inventory.lookup_for(scientific_identity_sha256)
        if inventory.source_error is None:
            return lookup
        if lookup.status is SolvedLeafLookupStatus.CORRUPT:
            return lookup
        return SolvedLeafLookup(
            SolvedLeafLookupStatus.CORRUPT,
            reason=inventory.source_error,
            discovery=inventory.discovery,
        )

    def discover_many(
        self, requests: Sequence[tuple[str, str]]
    ) -> SolvedLeafStoreDiscovery:
        """Authenticate a whole store once for an exact set of leaf requests.

        ``discovered_count`` is the number of physical cache objects in this
        configured source, not that count multiplied by the number of leaves
        which consulted it.  A corrupt object makes the trusted source fail
        closed even when another request would otherwise be a normal miss.
        """

        requested: dict[str, str] = {}
        for scientific_identity_sha256, leaf_id in requests:
            self._entry_path(scientific_identity_sha256)
            if not isinstance(leaf_id, str) or not leaf_id:
                raise ValueError("solved-leaf cache request leaf ID is invalid")
            previous = requested.setdefault(scientific_identity_sha256, leaf_id)
            if previous != leaf_id:
                raise ValueError("solved-leaf cache request identity conflicts")

        def empty_inventory(
            status: EvidenceDiscoveryStatus,
            *,
            reason: str | None = None,
            discovered_count: int = 0,
        ) -> SolvedLeafStoreDiscovery:
            discovery = EvidenceDiscovery(
                status=status,
                discovered_count=discovered_count,
                compatible_count=0,
                rejected_count=0,
            )
            lookup_status = (
                SolvedLeafLookupStatus.CORRUPT
                if status is EvidenceDiscoveryStatus.CORRUPT
                else SolvedLeafLookupStatus.MISSING
            )
            return SolvedLeafStoreDiscovery(
                lookups=MappingProxyType({
                    identity: SolvedLeafLookup(
                        lookup_status,
                        reason=reason,
                        discovery=discovery,
                    )
                    for identity in requested
                }),
                discovery=discovery,
                source_error=reason,
            )

        if not self.root.exists():
            return empty_inventory(EvidenceDiscoveryStatus.EMPTY)
        if not self.root.is_dir():
            return empty_inventory(
                EvidenceDiscoveryStatus.CORRUPT,
                reason="solved-leaf cache store is not a directory",
                discovered_count=1,
            )
        candidates = tuple(sorted(self.root.glob("*.json"), key=lambda item: item.name))
        if not candidates:
            return empty_inventory(EvidenceDiscoveryStatus.EMPTY)

        valid: dict[str, tuple[Path, Mapping[str, object]]] = {}
        stale_by_leaf: dict[str, tuple[Path, Mapping[str, object]]] = {}
        corrupt_paths: dict[str, Path] = {}
        errors: list[str] = []
        for candidate in candidates:
            try:
                if candidate.is_symlink():
                    raise ValueError("solved-leaf cache entry may not be a symlink")
                receipt = self._validate_receipt(_load_json(candidate))
                identity = str(receipt["scientific_computation_identity_sha256"])
                if candidate != self._entry_path(identity):
                    raise ValueError("solved-leaf cache filename does not match identity")
                if identity in valid:
                    raise ValueError("solved-leaf cache contains duplicate identities")
            except (OSError, ValueError, UnicodeDecodeError) as error:
                errors.append(f"{candidate}: {error}")
                candidate_identity = candidate.stem
                if candidate_identity in requested:
                    corrupt_paths[candidate_identity] = candidate
                continue
            valid[identity] = (candidate, receipt)
            leaf_id = str(receipt["leaf_id"])
            stale_by_leaf.setdefault(leaf_id, (candidate, receipt))

        exact: dict[str, tuple[Path, Mapping[str, object]]] = {}
        for identity, expected_leaf_id in requested.items():
            candidate = valid.get(identity)
            if candidate is None:
                continue
            path, receipt = candidate
            if receipt["leaf_id"] != expected_leaf_id:
                errors.append(
                    f"{path}: solved-leaf cache object identity is invalid"
                )
                corrupt_paths[identity] = path
                continue
            exact[identity] = candidate

        discovered_count = len(candidates)
        compatible_count = len(exact)
        rejected_count = len(valid) - compatible_count
        if errors:
            discovery = EvidenceDiscovery(
                status=EvidenceDiscoveryStatus.CORRUPT,
                discovered_count=discovered_count,
                compatible_count=compatible_count,
                rejected_count=rejected_count,
            )
            source_error = "trusted solved-leaf cache source is corrupt: " + "; ".join(
                errors
            )
        else:
            status = (
                EvidenceDiscoveryStatus.HIT
                if compatible_count
                else EvidenceDiscoveryStatus.MISS
            )
            discovery = EvidenceDiscovery(
                status=status,
                discovered_count=discovered_count,
                compatible_count=compatible_count,
                rejected_count=rejected_count,
            )
            source_error = None

        lookups: dict[str, SolvedLeafLookup] = {}
        for identity, leaf_id in requested.items():
            if identity in exact:
                path, receipt = exact[identity]
                lookup_status = (
                    SolvedLeafLookupStatus.CORRUPT
                    if source_error is not None
                    else SolvedLeafLookupStatus.HIT
                )
                lookups[identity] = SolvedLeafLookup(
                    lookup_status,
                    path=path,
                    receipt=None if source_error is not None else receipt,
                    reason=source_error,
                    discovery=discovery,
                )
                continue
            if source_error is not None:
                lookups[identity] = SolvedLeafLookup(
                    SolvedLeafLookupStatus.CORRUPT,
                    path=corrupt_paths.get(identity),
                    reason=source_error,
                    discovery=discovery,
                )
                continue
            stale = stale_by_leaf.get(leaf_id)
            if stale is not None:
                path, receipt = stale
                lookups[identity] = SolvedLeafLookup(
                    SolvedLeafLookupStatus.STALE,
                    path=path,
                    receipt=receipt,
                    reason="scientific computation identity changed",
                    discovery=discovery,
                )
            else:
                lookups[identity] = SolvedLeafLookup(
                    SolvedLeafLookupStatus.MISSING,
                    discovery=discovery,
                )
        return SolvedLeafStoreDiscovery(
            lookups=MappingProxyType(lookups),
            discovery=discovery,
            source_error=source_error,
        )

    def quarantine(self, path: Path, reason: str) -> Path | None:
        if not path.exists():
            return None
        quarantine = self.root / "quarantine"
        quarantine.mkdir(parents=True, exist_ok=True)
        reason_sha = hashlib.sha256(reason.encode("utf-8", errors="replace")).hexdigest()[:12]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        target = quarantine / f"{path.stem}.corrupt-{stamp}-{reason_sha}.json"
        os.replace(path, target)
        return target

    def _publication_receipt(
        self,
        *,
        scientific_identity_sha256: str,
        leaf_id: str,
        record: Mapping[str, object],
        source_type: str,
    ) -> dict[str, object]:
        state = record.get("state")
        if not _is_cacheable_terminal_record(
            record, state=state, stages=record.get("stages")
        ):
            raise ValueError("solved-leaf cache accepts terminal records only")
        stages = record.get("stages")
        if not isinstance(stages, list) or not stages:
            raise ValueError("solved-leaf cache record stages are incomplete")
        record_sha = record.get("record_sha256")
        if not isinstance(record_sha, str) or _HEX_64.fullmatch(record_sha) is None:
            raise ValueError("solved-leaf cache record digest is invalid")
        sealed: dict[str, object] = {
            "schema_version": SOLVED_LEAF_CACHE_SCHEMA_VERSION,
            "scientific_computation_identity_sha256": scientific_identity_sha256,
            "leaf_id": leaf_id,
            "record": dict(record),
            "canonical_leaf_record_sha256": record_sha,
            "terminal_state": state,
            "stage_count": len(stages),
            "created_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source_type": source_type,
        }
        receipt = {**sealed, "receipt_sha256": _sha256(sealed)}
        self._validate_receipt(receipt)
        return receipt

    def publish(
        self,
        *,
        scientific_identity_sha256: str,
        leaf_id: str,
        record: Mapping[str, object],
        source_type: str,
    ) -> Path:
        path = self._entry_path(scientific_identity_sha256)
        receipt = self._publication_receipt(
            scientific_identity_sha256=scientific_identity_sha256,
            leaf_id=leaf_id,
            record=record,
            source_type=source_type,
        )

        lock = self.root / "locks" / f"{scientific_identity_sha256}.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as error:
            raise RuntimeError("solved-leaf cache publication is locked") from error
        try:
            os.close(descriptor)
            if path.exists():
                existing = self.lookup(scientific_identity_sha256, leaf_id)
                if existing.status is SolvedLeafLookupStatus.HIT:
                    assert existing.receipt is not None
                    if existing.receipt["record"] == record:
                        return path
                    raise RuntimeError(
                        "solved-leaf cache contains conflicting authenticated evidence"
                    )
            _atomic_json(path, receipt)
            return path
        finally:
            try:
                lock.unlink()
            except FileNotFoundError:
                pass

    def publish_if_missing(
        self,
        *,
        scientific_identity_sha256: str,
        leaf_id: str,
        record: Mapping[str, object],
        source_type: str,
    ) -> SolvedLeafLookup:
        """Publish only when no exact current object exists under the lock."""

        path = self._entry_path(scientific_identity_sha256)
        receipt = self._publication_receipt(
            scientific_identity_sha256=scientific_identity_sha256,
            leaf_id=leaf_id,
            record=record,
            source_type=source_type,
        )
        lock = self.root / "locks" / f"{scientific_identity_sha256}.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as error:
            raise RuntimeError("solved-leaf cache publication is locked") from error
        try:
            os.close(descriptor)
            if path.exists():
                return self.lookup(scientific_identity_sha256, leaf_id)
            _atomic_json(path, receipt)
            return SolvedLeafLookup(
                SolvedLeafLookupStatus.HIT,
                path=path,
                receipt=receipt,
                discovery=EvidenceDiscovery(
                    status=EvidenceDiscoveryStatus.HIT,
                    discovered_count=1,
                    compatible_count=1,
                    rejected_count=0,
                ),
            )
        finally:
            try:
                lock.unlink()
            except FileNotFoundError:
                pass
