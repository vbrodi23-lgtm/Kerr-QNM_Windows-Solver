"""Durable, non-scientific structural diagnostics for campaign execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Mapping

from .contracts import canonical_json_bytes


_LEGACY_DIAGNOSTIC_EVENT_SCHEMA = "windows-solver.structural-event/1"
DIAGNOSTIC_EVENT_SCHEMA = "windows-solver.structural-event/2"
DIAGNOSTIC_LATEST_SCHEMA = "windows-solver.diagnostic-session-latest/1"

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_LEAF_FIELDS = (
    "index",
    "count",
    "leaf_id",
    "role",
    "mode",
    "exact_coordinate",
    "spin_display",
    "mechanism",
)
_PR74_EXECUTION_FIELDS = ("profile", "pass", "tier", "operation_identity")
_EXECUTION_FIELDS = (
    *_PR74_EXECUTION_FIELDS,
    "operation",
    "execution_identity_sha256",
    "request_sha256",
    "plan",
    "scope",
    "sample_index",
    "sample_role",
    "control_receipt_sha256",
    "control_return_sha256",
    "control_decision_sha256",
    "transition_id",
    "outcome_kind",
    "retryable",
    "terminal",
    "current_action_kind",
    "current_tier",
    "next_tier",
)
_TRANSITION_FIELDS = ("prior_state", "next_state", "reason_code")
_CONNECTION_FIELDS = (
    "scientific_computation_identity",
    "root_dependency_key_sha256",
    "root_seal_sha256",
    "source_record_sha256",
    "source_stage_sha256",
    "provisional_stage_sha256",
    "cache_receipt_sha256",
    "background_receipt_sha256",
    "queue_ordinal",
    "disposition_receipt_sha256",
)
_CHECKPOINT_FIELDS = ("pre_commit_sha256", "post_commit_sha256")
_OPERATION_FLOW_FIELDS = (
    "who",
    "did_what",
    "to_what",
    "using_what",
    "produced_what",
    "handed_to_whom",
    "caller",
    "callee",
    "process_id",
)
_EVENT_FIELDS = frozenset(
    {
        "schema",
        "sequence",
        "previous_event_sha256",
        "event_sha256",
        "timestamp_utc",
        "monotonic_seconds",
        "elapsed_session_seconds",
        "session_id",
        "campaign_id",
        "selection_id",
        "checkpoint_path",
        "event_kind",
        "leaf",
        "execution",
        "transition",
        "connections",
        "checkpoint",
        "operation_flow",
        "compact_diagnostics",
    }
)
_LEGACY_EVENT_FIELDS = _EVENT_FIELDS - {"operation_flow"}


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _json_copy(value: object) -> object:
    """Copy only values that the canonical diagnostic format can preserve."""

    return json.loads(canonical_json_bytes(value).decode("utf-8"))


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


def _section(
    fields: tuple[str, ...],
    value: Mapping[str, object] | None,
    name: str,
    *,
    require_complete: bool = False,
) -> dict[str, object]:
    if value is None:
        value = {}
    if not isinstance(value, Mapping):
        raise ValueError(f"structural event {name} must be an object")
    unknown = set(value) - set(fields)
    if unknown:
        raise ValueError(
            f"unknown structural event {name} fields: {', '.join(sorted(unknown))}"
        )
    if require_complete and set(value) != set(fields):
        raise ValueError(f"structural event {name} schema is invalid")
    result = {field: None for field in fields}
    result.update(_json_copy(dict(value)))
    return result


def _nonempty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _digest_or_none(value: object, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{name} is invalid")
    try:
        int(value, 16)
    except ValueError as error:
        raise ValueError(f"{name} is invalid") from error
    return value


def _validate_material_execution(value: Mapping[str, object]) -> None:
    for name in (
        "execution_identity_sha256",
        "request_sha256",
        "control_receipt_sha256",
        "control_return_sha256",
        "control_decision_sha256",
        "transition_id",
    ):
        if name in value:
            _digest_or_none(value.get(name), f"structural execution {name}")
    scope = value.get("scope")
    if scope is not None and scope not in {"REQUEST", "SAMPLE"}:
        raise ValueError("structural execution scope is invalid")
    sample_index = value.get("sample_index")
    sample_role = value.get("sample_role")
    if scope == "REQUEST" and (sample_index is not None or sample_role is not None):
        raise ValueError("REQUEST structural execution selects a sample")
    if scope == "SAMPLE" and (
        isinstance(sample_index, bool)
        or not isinstance(sample_index, int)
        or sample_index < 0
        or not isinstance(sample_role, str)
        or not sample_role
    ):
        raise ValueError("SAMPLE structural execution identity is invalid")
    for name in ("current_action_kind",):
        if value.get(name) is not None and value[name] not in {"ROOT", "RESPONSE"}:
            raise ValueError(f"structural execution {name} is invalid")
    if value.get("outcome_kind") is not None and value["outcome_kind"] not in {
        "PROMOTION_PENDING",
        "UNRESOLVED",
        "DEFERRED",
        "REJECTED",
        "SYSTEM_FAILURE",
    }:
        raise ValueError("structural execution outcome_kind is invalid")
    for name in ("retryable", "terminal"):
        if value.get(name) is not None and not isinstance(value[name], bool):
            raise ValueError(f"structural execution {name} is invalid")
    for name in ("current_tier", "next_tier"):
        if value.get(name) is not None and value[name] not in {
            "BF40",
            "BF80",
            "BF120",
        }:
            raise ValueError(f"structural execution {name} is invalid")


@dataclass(frozen=True, slots=True)
class StructuralEvent:
    """One authenticated, append-only observation of scheduler movement."""

    value: Mapping[str, object]

    @property
    def event_sha256(self) -> str:
        return str(self.value["event_sha256"])

    @property
    def previous_event_sha256(self) -> str | None:
        value = self.value["previous_event_sha256"]
        return None if value is None else str(value)

    def to_mapping(self) -> dict[str, object]:
        return _json_copy(dict(self.value))  # type: ignore[return-value]

    @classmethod
    def create(
        cls,
        *,
        sequence: int,
        previous_event_sha256: str | None,
        timestamp_utc: str,
        monotonic_seconds: float,
        elapsed_session_seconds: float,
        session_id: str,
        campaign_id: str,
        selection_id: str,
        checkpoint_path: str,
        event_kind: str,
        leaf: Mapping[str, object] | None = None,
        execution: Mapping[str, object] | None = None,
        transition: Mapping[str, object] | None = None,
        connections: Mapping[str, object] | None = None,
        checkpoint: Mapping[str, object] | None = None,
        operation_flow: Mapping[str, object] | None = None,
        compact_diagnostics: Mapping[str, object] | None = None,
    ) -> "StructuralEvent":
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            raise ValueError("structural event sequence is invalid")
        _digest_or_none(previous_event_sha256, "previous event digest")
        for name, value in (
            ("timestamp", timestamp_utc),
            ("session id", session_id),
            ("campaign id", campaign_id),
            ("selection id", selection_id),
            ("checkpoint path", checkpoint_path),
            ("event kind", event_kind),
        ):
            _nonempty_string(value, name)
        for name, value in (
            ("monotonic seconds", monotonic_seconds),
            ("elapsed session seconds", elapsed_session_seconds),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise ValueError(f"structural event {name} is invalid")
        if compact_diagnostics is None:
            compact_diagnostics = {}
        if not isinstance(compact_diagnostics, Mapping):
            raise ValueError("structural event compact diagnostics must be an object")
        execution_section = _section(_EXECUTION_FIELDS, execution, "execution")
        _validate_material_execution(execution_section)
        transition_section = _section(_TRANSITION_FIELDS, transition, "transition")
        leaf_section = _section(_LEAF_FIELDS, leaf, "leaf")
        if operation_flow is None:
            operation_identity = execution_section["operation_identity"]
            profile = execution_section["profile"]
            pass_name = execution_section["pass"]
            target = leaf_section["leaf_id"] or checkpoint_path
            next_owner = transition_section["next_state"] or "diagnostic-ledger"
            actor = operation_identity or profile or "windows-solver"
            operation_flow = {
                "who": str(actor),
                "did_what": event_kind,
                "to_what": str(target),
                "using_what": str(operation_identity or pass_name or event_kind),
                "produced_what": str(transition_section["next_state"] or event_kind),
                "handed_to_whom": str(next_owner),
                "caller": str(profile or "windows-solver"),
                "callee": str(next_owner),
                "process_id": os.getpid(),
            }
        operation_flow_section = _section(
            _OPERATION_FLOW_FIELDS,
            operation_flow,
            "operation flow",
            require_complete=True,
        )
        for name in _OPERATION_FLOW_FIELDS[:-1]:
            _nonempty_string(operation_flow_section[name], f"operation flow {name}")
        process_id = operation_flow_section["process_id"]
        if isinstance(process_id, bool) or not isinstance(process_id, int) or process_id < 1:
            raise ValueError("structural event operation flow process id is invalid")
        content: dict[str, object] = {
            "schema": DIAGNOSTIC_EVENT_SCHEMA,
            "sequence": sequence,
            "previous_event_sha256": previous_event_sha256,
            "timestamp_utc": timestamp_utc,
            "monotonic_seconds": float(monotonic_seconds),
            "elapsed_session_seconds": float(elapsed_session_seconds),
            "session_id": session_id,
            "campaign_id": campaign_id,
            "selection_id": selection_id,
            "checkpoint_path": checkpoint_path,
            "event_kind": event_kind,
            "leaf": leaf_section,
            "execution": execution_section,
            "transition": transition_section,
            "connections": _section(_CONNECTION_FIELDS, connections, "connections"),
            "checkpoint": _section(_CHECKPOINT_FIELDS, checkpoint, "checkpoint"),
            "operation_flow": operation_flow_section,
            "compact_diagnostics": _json_copy(dict(compact_diagnostics)),
        }
        event = {**content, "event_sha256": _sha256(content)}
        return cls(_json_copy(event))  # type: ignore[arg-type]

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "StructuralEvent":
        if not isinstance(value, Mapping) or value.get("schema") not in {
            _LEGACY_DIAGNOSTIC_EVENT_SCHEMA,
            DIAGNOSTIC_EVENT_SCHEMA,
        }:
            raise ValueError("structural event schema is invalid")
        expected_fields = (
            _EVENT_FIELDS
            if value.get("schema") == DIAGNOSTIC_EVENT_SCHEMA
            else _LEGACY_EVENT_FIELDS
        )
        if set(value) != expected_fields:
            raise ValueError("structural event schema is invalid")
        sequence = value.get("sequence")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            raise ValueError("structural event sequence is invalid")
        previous = _digest_or_none(
            value.get("previous_event_sha256"), "previous event digest"
        )
        expected = _sha256({key: item for key, item in value.items() if key != "event_sha256"})
        actual = _digest_or_none(value.get("event_sha256"), "event digest")
        if expected != actual:
            raise ValueError("structural event authentication failed")
        for name in (
            "timestamp_utc",
            "session_id",
            "campaign_id",
            "selection_id",
            "checkpoint_path",
            "event_kind",
        ):
            _nonempty_string(value.get(name), name)
        for name in ("monotonic_seconds", "elapsed_session_seconds"):
            item = value.get(name)
            if isinstance(item, bool) or not isinstance(item, (int, float)) or item < 0:
                raise ValueError(f"structural event {name} is invalid")
        _section(_LEAF_FIELDS, value.get("leaf"), "leaf", require_complete=True)
        execution_value = value.get("execution")
        execution_fields = (
            _PR74_EXECUTION_FIELDS
            if isinstance(execution_value, Mapping)
            and set(execution_value) == set(_PR74_EXECUTION_FIELDS)
            else _EXECUTION_FIELDS
        )
        _section(
            execution_fields,
            execution_value,
            "execution",
            require_complete=True,
        )
        if execution_fields == _EXECUTION_FIELDS:
            _validate_material_execution(execution_value)
        _section(
            _TRANSITION_FIELDS,
            value.get("transition"),
            "transition",
            require_complete=True,
        )
        _section(
            _CONNECTION_FIELDS,
            value.get("connections"),
            "connections",
            require_complete=True,
        )
        _section(
            _CHECKPOINT_FIELDS,
            value.get("checkpoint"),
            "checkpoint",
            require_complete=True,
        )
        if value.get("schema") == DIAGNOSTIC_EVENT_SCHEMA:
            flow = _section(
                _OPERATION_FLOW_FIELDS,
                value.get("operation_flow"),
                "operation flow",
                require_complete=True,
            )
            for name in _OPERATION_FLOW_FIELDS[:-1]:
                _nonempty_string(flow[name], f"operation flow {name}")
            process_id = flow["process_id"]
            if (
                isinstance(process_id, bool)
                or not isinstance(process_id, int)
                or process_id < 1
            ):
                raise ValueError("structural event operation flow process id is invalid")
        if not isinstance(value.get("compact_diagnostics"), Mapping):
            raise ValueError("structural event compact diagnostics must be an object")
        if sequence == 1 and previous is not None:
            raise ValueError("first structural event has a previous digest")
        return cls(_json_copy(dict(value)))  # type: ignore[arg-type]


def read_structural_events(path: str | os.PathLike[str] | Path) -> tuple[dict[str, object], ...]:
    """Read and authenticate a complete structural JSONL event chain."""

    source = Path(path)
    if not source.exists():
        raise ValueError("structural event log is missing")
    events: list[dict[str, object]] = []
    prior: str | None = None
    with source.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                raise ValueError(f"structural event line {line_number} is empty")
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"structural event line {line_number} is malformed") from error
            event = StructuralEvent.from_mapping(raw)
            if event.to_mapping()["sequence"] != line_number:
                raise ValueError("structural event sequence is discontinuous")
            if event.previous_event_sha256 != prior:
                raise ValueError("structural event chain authentication failed")
            prior = event.event_sha256
            events.append(event.to_mapping())
    return tuple(events)


@dataclass(frozen=True, slots=True)
class DiagnosticSessionPaths:
    root: Path
    directory: Path
    latest: Path
    structural_events: Path
    postmortem: Path
    artifact_manifest: Path
    console_transcript: Path
    bundle: Path


class StructuralDiagnosticSession:
    """Own one immutable diagnostic directory and its structural event chain."""

    def __init__(
        self,
        *,
        paths: DiagnosticSessionPaths,
        session_id: str,
        campaign_id: str,
        selection_id: str,
        checkpoint_path: Path,
        started_at_utc: str,
    ) -> None:
        self.paths = paths
        self.session_id = session_id
        self.campaign_id = campaign_id
        self.selection_id = selection_id
        self.checkpoint_path = checkpoint_path
        self.started_at_utc = started_at_utc
        self._started_monotonic = time.monotonic()
        self._sequence = 0
        self._previous_event_sha256: str | None = None
        self._terminal_state: str | None = None
        self._handle = self.paths.structural_events.open("ab")

    @classmethod
    def open(
        cls,
        *,
        checkpoint_path: str | os.PathLike[str] | Path,
        session_id: str,
        campaign_id: str,
        selection_id: str,
        started_at_utc: str | None = None,
    ) -> "StructuralDiagnosticSession":
        if not _SESSION_ID_RE.fullmatch(session_id):
            raise ValueError("diagnostic session id is invalid")
        for name, value in (("campaign id", campaign_id), ("selection id", selection_id)):
            _nonempty_string(value, name)
        checkpoint = Path(checkpoint_path)
        started = started_at_utc or datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )
        _nonempty_string(started, "diagnostic session start timestamp")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        root = Path(f"{checkpoint}.diagnostics")
        directory = root / f"session-{stamp}-{session_id}"
        if directory.exists():
            raise ValueError("diagnostic session directory already exists")
        root.mkdir(parents=True, exist_ok=True)
        directory.mkdir()
        paths = DiagnosticSessionPaths(
            root=root,
            directory=directory,
            latest=root / "latest.json",
            structural_events=directory / "structural-events.jsonl",
            postmortem=directory / "postmortem.json",
            artifact_manifest=directory / "artifact-manifest.json",
            console_transcript=directory / "console-transcript.txt",
            bundle=directory / "diagnostic-bundle.zip",
        )
        return cls(
            paths=paths,
            session_id=session_id,
            campaign_id=campaign_id,
            selection_id=selection_id,
            checkpoint_path=checkpoint,
            started_at_utc=started,
        )

    def append(
        self,
        event_kind: str,
        *,
        leaf: Mapping[str, object] | None = None,
        execution: Mapping[str, object] | None = None,
        transition: Mapping[str, object] | None = None,
        connections: Mapping[str, object] | None = None,
        checkpoint: Mapping[str, object] | None = None,
        operation_flow: Mapping[str, object] | None = None,
        compact_diagnostics: Mapping[str, object] | None = None,
        durable: bool = False,
    ) -> StructuralEvent:
        if self._terminal_state is not None:
            raise ValueError("cannot append after the diagnostic session is terminal")
        self._sequence += 1
        event = StructuralEvent.create(
            sequence=self._sequence,
            previous_event_sha256=self._previous_event_sha256,
            timestamp_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            monotonic_seconds=time.monotonic(),
            elapsed_session_seconds=time.monotonic() - self._started_monotonic,
            session_id=self.session_id,
            campaign_id=self.campaign_id,
            selection_id=self.selection_id,
            checkpoint_path=str(self.checkpoint_path),
            event_kind=event_kind,
            leaf=leaf,
            execution=execution,
            transition=transition,
            connections=connections,
            checkpoint=checkpoint,
            operation_flow=operation_flow,
            compact_diagnostics=compact_diagnostics,
        )
        self._handle.write(canonical_json_bytes(event.to_mapping()) + b"\n")
        self._previous_event_sha256 = event.event_sha256
        self.flush()
        if durable:
            self.fsync()
        return event

    def flush(self) -> None:
        self._handle.flush()

    def fsync(self) -> None:
        self.flush()
        os.fsync(self._handle.fileno())

    def final_events(self, limit: int = 100) -> tuple[dict[str, object], ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise ValueError("structural event limit is invalid")
        self.flush()
        events = read_structural_events(self.paths.structural_events)
        return events[-limit:] if limit else ()

    def forensic_record_counters(self) -> dict[str, int]:
        """Summarize distinct forensic records across all intake consumers."""

        self.flush()
        records: dict[tuple[object, object], dict[str, bool]] = {}
        for event in read_structural_events(self.paths.structural_events):
            if event.get("event_kind") != "FORENSIC_RECORD_EXCLUDED":
                continue
            leaf = event.get("leaf")
            connections = event.get("connections")
            diagnostics = event.get("compact_diagnostics")
            if not isinstance(leaf, Mapping) or not isinstance(
                connections, Mapping
            ) or not isinstance(diagnostics, Mapping):
                raise ValueError("forensic exclusion event is malformed")
            key = (
                leaf.get("leaf_id"),
                connections.get("source_record_sha256"),
            )
            summary = records.setdefault(
                key,
                {"root_seed_salvaged": False, "stale_cache_hit_prevented": False},
            )
            summary["root_seed_salvaged"] = (
                summary["root_seed_salvaged"]
                or diagnostics.get("root_seed_salvaged") is True
            )
            summary["stale_cache_hit_prevented"] = (
                summary["stale_cache_hit_prevented"]
                or diagnostics.get("stale_cache_hit_prevented") is True
            )
        return {
            "forensic_records_discovered": len(records),
            "forensic_records_excluded": len(records),
            "forensic_root_seeds_salvaged": sum(
                item["root_seed_salvaged"] for item in records.values()
            ),
            "stale_cache_hits_prevented": sum(
                item["stale_cache_hit_prevented"] for item in records.values()
            ),
        }

    def set_artifact_paths(
        self,
        *,
        postmortem_path: str | os.PathLike[str] | Path | None = None,
        bundle_path: str | os.PathLike[str] | Path | None = None,
    ) -> None:
        latest = self._latest_mapping()
        if postmortem_path is not None:
            latest["postmortem_path"] = str(Path(postmortem_path))
        if bundle_path is not None:
            latest["bundle_path"] = str(Path(bundle_path))
        _atomic_json(self.paths.latest, latest)

    def _latest_mapping(self) -> dict[str, object]:
        existing: Mapping[str, object] = {}
        if self.paths.latest.exists():
            try:
                loaded = json.loads(self.paths.latest.read_text(encoding="utf-8"))
            except json.JSONDecodeError as error:
                raise ValueError("diagnostic latest pointer is malformed") from error
            if not isinstance(loaded, Mapping):
                raise ValueError("diagnostic latest pointer is malformed")
            existing = loaded
        return {
            "schema": DIAGNOSTIC_LATEST_SCHEMA,
            "session_id": self.session_id,
            "session_directory": str(self.paths.directory),
            "start_timestamp_utc": self.started_at_utc,
            "terminal_state": self._terminal_state,
            "postmortem_path": existing.get("postmortem_path"),
            "bundle_path": existing.get("bundle_path"),
        }

    def _close(self, terminal_state: str) -> None:
        if self._terminal_state is not None:
            raise ValueError("diagnostic session is already terminal")
        self._terminal_state = terminal_state
        self.fsync()
        self._handle.close()
        _atomic_json(self.paths.latest, self._latest_mapping())

    def close_completed(self) -> None:
        self._close("COMPLETED")

    def close_interrupted(self) -> None:
        self._close("INTERRUPTED")

    def close_failed(self) -> None:
        self._close("SYSTEM_FAILURE")


__all__ = [
    "DIAGNOSTIC_EVENT_SCHEMA",
    "DIAGNOSTIC_LATEST_SCHEMA",
    "DiagnosticSessionPaths",
    "StructuralDiagnosticSession",
    "StructuralEvent",
    "read_structural_events",
]
