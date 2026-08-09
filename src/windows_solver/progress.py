"""Typed, context-scoped progress events kept outside scientific payloads."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, fields, replace
from enum import StrEnum
import time
from types import MappingProxyType
from typing import Protocol


PROGRESS_SCHEMA = "windows-solver.progress/v1"


class ProgressMode(StrEnum):
    QUIET = "quiet"
    NORMAL = "normal"
    TRACE = "trace"


class ProgressEventKind(StrEnum):
    CAMPAIGN_STARTED = "campaign_started"
    CAMPAIGN_COMPLETED = "campaign_completed"
    CAMPAIGN_FAILED = "campaign_failed"
    LEAF_STARTED = "leaf_started"
    LEAF_REUSED = "leaf_reused"
    LEAF_COMPLETED = "leaf_completed"
    LEAF_FAILED = "leaf_failed"
    CHECKPOINT_WRITING = "checkpoint_writing"
    CHECKPOINT_WRITTEN = "checkpoint_written"
    PRECISION_STAGE_STARTED = "precision_stage_started"
    PRECISION_STAGE_COMPLETED = "precision_stage_completed"
    COMPONENT_PASS_STARTED = "component_pass_started"
    COMPONENT_PASS_COMPLETED = "component_pass_completed"
    AMPLITUDE_READOUT_STARTED = "amplitude_readout_started"
    AMPLITUDE_READOUT_COMPLETED = "amplitude_readout_completed"
    ROOT_PHASE_STARTED = "root_phase_started"
    ROOT_PHASE_COMPLETED = "root_phase_completed"
    NEWTON_ITERATION_STARTED = "newton_iteration_started"
    NEWTON_ITERATION_COMPLETED = "newton_iteration_completed"
    DETERMINANT_EVALUATED = "determinant_evaluated"
    CANDIDATE_EVALUATED = "candidate_evaluated"
    DAMPING_DECIDED = "damping_decided"
    SUBOPERATION_STARTED = "suboperation_started"
    SUBOPERATION_COMPLETED = "suboperation_completed"
    ERROR = "error"


def _freeze(value: object) -> object:
    """Take a recursively immutable snapshot of an out-of-band value."""

    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("progress mapping keys must be strings")
            frozen[key] = _freeze(item)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(item) for item in value)
    return value


def _mapping_snapshot(values: Mapping[str, object]) -> Mapping[str, object]:
    return _freeze(values)  # type: ignore[return-value]


_INTEGER_CONTEXT_KEYS = frozenset(
    {
        "leaf_index",
        "leaf_count",
        "precision_digits",
        "readout_index",
        "newton_index",
        "newton_limit",
        "determinant_index",
    }
)
_FLOAT_CONTEXT_KEYS = frozenset({"spin", "epsilon"})
_STRING_CONTEXT_KEYS = frozenset(
    {
        "leaf_id",
        "role",
        "mechanism_id",
        "component_pass",
        "readout_role",
        "phase",
        "determinant_purpose",
        "suboperation",
    }
)
_MAPPING_CONTEXT_KEYS = frozenset(
    {"mode", "sampling_coordinate", "bound_omega", "amplitude"}
)


def _validate_context_values(values: Mapping[str, object]) -> Mapping[str, object]:
    unknown = sorted(set(values) - _PROGRESS_CONTEXT_KEYS)
    if unknown:
        raise ValueError("unknown progress context fields: " + ", ".join(unknown))
    for name, value in values.items():
        if value is None:
            continue
        if name in _INTEGER_CONTEXT_KEYS and (
            isinstance(value, bool) or not isinstance(value, int)
        ):
            raise ValueError(f"progress context {name} must be an integer")
        if name in _FLOAT_CONTEXT_KEYS and (
            isinstance(value, bool) or not isinstance(value, (int, float))
        ):
            raise ValueError(f"progress context {name} must be a number")
        if name in _STRING_CONTEXT_KEYS and not isinstance(value, str):
            raise ValueError(f"progress context {name} must be a string")
        if name in _MAPPING_CONTEXT_KEYS and not isinstance(value, Mapping):
            raise ValueError(f"progress context {name} must be a mapping")
    return _mapping_snapshot(values)


@dataclass(frozen=True, slots=True)
class ProgressContext:
    leaf_index: int | None = None
    leaf_count: int | None = None
    leaf_id: str | None = None
    role: str | None = None
    mode: Mapping[str, object] | None = None
    spin: float | None = None
    sampling_coordinate: Mapping[str, object] | None = None
    mechanism_id: str | None = None
    bound_omega: Mapping[str, object] | None = None
    precision_digits: int | None = None
    component_pass: str | None = None
    readout_index: int | None = None
    readout_role: str | None = None
    epsilon: float | None = None
    amplitude: Mapping[str, object] | None = None
    phase: str | None = None
    newton_index: int | None = None
    newton_limit: int | None = None
    determinant_index: int | None = None
    determinant_purpose: str | None = None
    suboperation: str | None = None

    def __post_init__(self) -> None:
        values = _validate_context_values(
            {field.name: getattr(self, field.name) for field in fields(self)}
        )
        for name in _MAPPING_CONTEXT_KEYS:
            value = values[name]
            object.__setattr__(self, name, value)

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> "ProgressContext":
        snapshot = _validate_context_values(values)
        return cls(**snapshot)

    def to_mapping(self) -> dict[str, object]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


_PROGRESS_CONTEXT_KEYS = frozenset(field.name for field in fields(ProgressContext))


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    kind: ProgressEventKind
    context: ProgressContext
    payload: Mapping[str, object]
    monotonic_seconds: float

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ProgressEventKind):
            raise ValueError("progress kind must be a ProgressEventKind")
        if not isinstance(self.context, ProgressContext):
            raise ValueError("progress context must be a ProgressContext")
        if not isinstance(self.payload, Mapping):
            raise ValueError("progress payload must be a mapping")
        object.__setattr__(self, "payload", _mapping_snapshot(self.payload))


class ProgressObserver(Protocol):
    def publish(self, event: ProgressEvent) -> None: ...


_ACTIVE_OBSERVER: ContextVar[ProgressObserver | None] = ContextVar(
    "windows_solver_progress_observer", default=None
)
_ACTIVE_CONTEXT: ContextVar[ProgressContext] = ContextVar(
    "windows_solver_progress_context", default=ProgressContext()
)


@contextmanager
def activate_progress(observer: ProgressObserver) -> Iterator[None]:
    """Route events to an observer only for the current context scope."""

    token = _ACTIVE_OBSERVER.set(observer)
    try:
        yield
    finally:
        _ACTIVE_OBSERVER.reset(token)


@contextmanager
def progress_scope(**values: object) -> Iterator[None]:
    """Apply a validated hierarchy fragment for the current context scope."""

    update = ProgressContext.from_mapping(values).to_mapping()
    supplied = {key: update[key] for key in values}
    token = _ACTIVE_CONTEXT.set(replace(_ACTIVE_CONTEXT.get(), **supplied))
    try:
        yield
    finally:
        _ACTIVE_CONTEXT.reset(token)


def emit_progress(kind: ProgressEventKind, **payload: object) -> ProgressEvent | None:
    """Publish an immutable event, or no-op when no progress observer is active."""

    observer = _ACTIVE_OBSERVER.get()
    if observer is None:
        return None
    if not isinstance(kind, ProgressEventKind):
        raise ValueError("progress kind must be a ProgressEventKind")
    event = ProgressEvent(
        kind=kind,
        context=_ACTIVE_CONTEXT.get(),
        payload=_mapping_snapshot(payload),
        monotonic_seconds=time.monotonic(),
    )
    observer.publish(event)
    return event


def ingest_external_progress(value: object) -> ProgressEvent | None:
    """Validate a transport event before forwarding it to the current observer."""

    if not isinstance(value, Mapping):
        raise ValueError("external progress event must be a mapping")
    expected = frozenset({"schema", "kind", "context", "payload"})
    if set(value) != expected:
        raise ValueError("external progress event must have exactly schema, kind, context, payload")
    if value["schema"] != PROGRESS_SCHEMA:
        raise ValueError("unsupported external progress schema")
    try:
        kind = ProgressEventKind(value["kind"])
    except (TypeError, ValueError) as error:
        raise ValueError("unknown external progress kind") from error
    context = value["context"]
    payload = value["payload"]
    if not isinstance(context, Mapping) or not isinstance(payload, Mapping):
        raise ValueError("external progress context and payload must be mappings")
    validated_context = ProgressContext.from_mapping(context)
    with progress_scope(**validated_context.to_mapping()):
        return emit_progress(kind, **_mapping_snapshot(payload))
