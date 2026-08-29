"""Typed, context-scoped progress events kept outside scientific payloads."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, fields, replace
from enum import StrEnum
import math
import time
from types import MappingProxyType
from typing import Protocol


PROGRESS_SCHEMA = "windows-solver.progress/3"


class ProgressMode(StrEnum):
    QUIET = "quiet"
    NORMAL = "normal"
    TRACE = "trace"


class ProgressEventKind(StrEnum):
    SOLVED_LEAF_CACHE_SCANNED = "solved_leaf_cache_scanned"
    CAMPAIGN_STARTED = "campaign_started"
    CAMPAIGN_COMPLETED = "campaign_completed"
    CAMPAIGN_FAILED = "campaign_failed"
    CAMPAIGN_INTERRUPTED = "campaign_interrupted"
    CAMPAIGN_PASS_STARTED = "campaign_pass_started"
    CAMPAIGN_PASS_COMPLETED = "campaign_pass_completed"
    CAMPAIGN_PASS_INTERRUPTED = "campaign_pass_interrupted"
    LEAF_STARTED = "leaf_started"
    LEAF_REUSED = "leaf_reused"
    LEAF_CACHE_STALE = "leaf_cache_stale"
    LEAF_CACHE_CORRUPT = "leaf_cache_corrupt"
    LEAF_CACHE_PUBLISHED = "leaf_cache_published"
    LEAF_CACHE_PUBLICATION_FAILED = "leaf_cache_publication_failed"
    LEAF_COMPLETED = "leaf_completed"
    LEAF_FAILED = "leaf_failed"
    LEAF_INTERRUPTED = "leaf_interrupted"
    LEAF_PASS_STARTED = "leaf_pass_started"
    LEAF_PASS_DISPOSITION_RECORDED = "leaf_pass_disposition_recorded"
    PROMOTION_QUEUED = "promotion_queued"
    SURVEY_SAMPLE_STARTED = "survey_sample_started"
    SURVEY_SAMPLE_COMPLETED = "survey_sample_completed"
    SYSTEM_FAILURE_RECORDED = "system_failure_recorded"
    REPORT_STATUS_CHANGED = "report_status_changed"
    CHECKPOINT_WRITING = "checkpoint_writing"
    CHECKPOINT_WRITTEN = "checkpoint_written"
    PRECISION_STAGE_STARTED = "precision_stage_started"
    PRECISION_STAGE_COMPLETED = "precision_stage_completed"
    COMPONENT_PASS_STARTED = "component_pass_started"
    COMPONENT_PASS_COMPLETED = "component_pass_completed"
    AMPLITUDE_READOUT_STARTED = "amplitude_readout_started"
    AMPLITUDE_READOUT_COMPLETED = "amplitude_readout_completed"
    ROOT_PHASE_STARTED = "root_phase_started"
    ROOT_SEED_SELECTED = "root_seed_selected"
    ROOT_PHASE_AUTHENTICATION_ESCALATED = (
        "root_phase_authentication_escalated"
    )
    PRIMARY_STAGED_AUTHENTICATION_STARTED = (
        "primary_staged_authentication_started"
    )
    PRIMARY_STAGED_DERIVATIVE_ACCEPTED = (
        "primary_staged_derivative_accepted"
    )
    PRIMARY_STAGED_DERIVATIVE_REJECTED = (
        "primary_staged_derivative_rejected"
    )
    PRIMARY_STAGED_AUTHENTICATION_COMPLETED = (
        "primary_staged_authentication_completed"
    )
    PRIMARY_FULL_AUTHENTICATION_ESCALATED = (
        "primary_full_authentication_escalated"
    )
    PRIMARY_FULL_AUTHENTICATION_COMPLETED = (
        "primary_full_authentication_completed"
    )
    DIAGNOSTIC_CONSISTENCY_STARTED = "diagnostic_consistency_started"
    DIAGNOSTIC_CONSISTENCY_COMPLETED = "diagnostic_consistency_completed"
    DIAGNOSTIC_FULL_AUTHENTICATION_ESCALATED = (
        "diagnostic_full_authentication_escalated"
    )
    DIAGNOSTIC_FULL_AUTHENTICATION_COMPLETED = (
        "diagnostic_full_authentication_completed"
    )
    ROOT_PHASE_COMPLETED = "root_phase_completed"
    NEWTON_ITERATION_STARTED = "newton_iteration_started"
    NEWTON_ITERATION_COMPLETED = "newton_iteration_completed"
    DETERMINANT_STARTED = "determinant_started"
    DETERMINANT_COMPLETED = "determinant_completed"
    DETERMINANT_EVALUATED = "determinant_evaluated"
    DETERMINANT_EVIDENCE_REUSED = "determinant_evidence_reused"
    HORIZON_CHART_EVALUATED = "horizon_chart_evaluated"
    DERIVATIVE_CONTROL_COMPLETED = "derivative_control_completed"
    ASYMPTOTIC_SERIES_EVALUATED = "asymptotic_series_evaluated"
    CARRIER_CHANGED = "carrier_changed"
    FACTORED_ODE_COMPLETED = "factored_ode_completed"
    SCATTERING_COEFFICIENTS_EXTRACTED = "scattering_coefficients_extracted"
    DETERMINANT_CHART_EVALUATED = "determinant_chart_evaluated"
    # Real-inner horizon geometry gate. Candidates are reported individually so
    # a NO_VERIFIED_HORIZON_ENDPOINT failure can be read back to the exact
    # radial-approach or series condition that rejected each one.
    HORIZON_ENDPOINT_CANDIDATE = "horizon_endpoint_candidate"
    # One round of the endpoint depth and order search. Reported per round so an
    # exhausted search can be read back to the depth it reached and the
    # limitation that stopped it rather than to a bare endpoint failure.
    HORIZON_ENDPOINT_DEPTH_ATTEMPT = "horizon_endpoint_depth_attempt"
    HORIZON_ENDPOINT_SEARCH_COMPLETED = "horizon_endpoint_search_completed"
    HORIZON_ENDPOINTS_VERIFIED = "horizon_endpoints_verified"
    OUTER_ENDPOINT_SELECTED = "outer_endpoint_selected"
    OUTER_ENDPOINT_PAIR_SELECTED = "outer_endpoint_pair_selected"
    EXTERIOR_ENDPOINT_RECOVERY_ATTEMPT = (
        "exterior_endpoint_recovery_attempt"
    )
    EXTERIOR_ENDPOINT_RECOVERY_DECIDED = (
        "exterior_endpoint_recovery_decided"
    )
    COORDINATE_IDENTITY_CHECKED = "coordinate_identity_checked"
    COORDINATE_INVERSION_STALLED = "coordinate_inversion_stalled"
    DETERMINANT_ERROR_ESTIMATED = "determinant_error_estimated"
    # One rung of the finite-difference step search. Reported per attempt so an
    # exhausted range can be read back to which condition each step failed.
    FREQUENCY_STEP_EVALUATED = "frequency_step_evaluated"
    CONDITIONING_EVALUATED = "conditioning_evaluated"
    CANDIDATE_EVALUATED = "candidate_evaluated"
    DAMPING_DECIDED = "damping_decided"
    SUBOPERATION_STARTED = "suboperation_started"
    SUBOPERATION_PROGRESS = "suboperation_progress"
    SUBOPERATION_COMPLETED = "suboperation_completed"
    ODE_SOLVE_STARTED = "ode_solve_started"
    ODE_SOLVE_PROGRESS = "ode_solve_progress"
    ODE_SOLVE_COMPLETED = "ode_solve_completed"
    ODE_SOLVE_FAILED = "ode_solve_failed"
    ODE_RESOURCE_LIMIT = "ode_resource_limit"
    ROOT_READOUT_RESOURCE_INFEASIBLE = "root_readout_resource_infeasible"
    ROOT_READOUT_REUSED = "root_readout_reused"
    ROOT_READOUT_RETAINED = "root_readout_retained"
    ROOT_READOUT_CACHE_STALE = "root_readout_cache_stale"
    ROOT_READOUT_CACHE_CORRUPT = "root_readout_cache_corrupt"
    REQUEST_STARTED = "request_started"
    REQUEST_VALIDATED = "request_validated"
    REQUEST_COMPLETED = "request_completed"
    REQUEST_FAILED = "request_failed"
    REQUEST_INTERRUPTED = "request_interrupted"
    WORKER_HEARTBEAT = "worker_heartbeat"
    ERROR = "error"


def _freeze(value: object) -> object:
    """Take a recursively immutable snapshot of an out-of-band value."""

    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key, item in value.items():
            frozen[key if isinstance(key, str) else _safe_text(key)] = _freeze(item)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(item) for item in value)
    if isinstance(value, bytearray):
        return bytes(value)
    if value is None or isinstance(value, (bool, int, float, str, bytes, complex)):
        return value
    return _safe_text(value)


def _safe_text(value: object) -> str:
    try:
        return repr(value)
    except Exception:
        return f"<unrepresentable {type(value).__name__}>"


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
        "determinant_index_leaf",
        "determinant_index_phase",
        "determinant_index_newton",
        "promotion_queue_count",
        "sample_count_used",
        "sample_count_limit",
        "root_read_count",
        "root_read_limit",
        "worker_launch_count",
        "worker_launch_limit",
        "sample_index",
    }
)
_FLOAT_CONTEXT_KEYS = frozenset({
    "spin",
    "epsilon",
    "binary64_seconds",
    "bf40_seconds",
    "bf80_seconds",
    "bf120_seconds",
    "total_leaf_seconds",
})
_BOOLEAN_CONTEXT_KEYS = frozenset({"fallback_used", "retryable", "terminal"})
_STRING_CONTEXT_KEYS = frozenset(
    {
        "leaf_id",
        "role",
        "mechanism_id",
        "component_pass",
        "readout_role",
        "phase",
        "root_phase",
        "seed_kind",
        "determinant_purpose",
        "suboperation",
        "execution_profile",
        "survey_pass",
        "pass_disposition",
        "evidence_level",
        "promotion_reason",
        "report_state",
        "system_failure_fingerprint",
        "precision_tier",
        "operation",
        "plan",
        "scope",
        "sample_role",
        "execution_identity_sha256",
        "request_sha256",
        "control_receipt_sha256",
        "control_return_sha256",
        "control_decision_sha256",
        "transition_id",
        "outcome_kind",
        "current_action_kind",
        "current_tier",
        "next_tier",
        "limiting_resource",
        "selected_intervention",
        "endpoint_recovery_result",
    }
)
_SEQUENCE_CONTEXT_KEYS = frozenset({
    "endpoint_branches",
    "attempted_endpoint_orders",
    "attempted_endpoint_geometries",
})
_MAPPING_CONTEXT_KEYS = frozenset(
    {
        "mode",
        "sampling_coordinate",
        "bound_omega",
        "seed_omega",
        "current_omega",
        "candidate_omega",
        "amplitude",
    }
)


def _validate_context_values(values: Mapping[str, object]) -> Mapping[str, object]:
    unknown = set(values) - _PROGRESS_CONTEXT_KEYS
    if unknown:
        raise ValueError(
            "unknown progress context fields: "
            + ", ".join(sorted(_safe_text(key) for key in unknown))
        )
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
        if name in _BOOLEAN_CONTEXT_KEYS and not isinstance(value, bool):
            raise ValueError(f"progress context {name} must be a boolean")
        if name in _STRING_CONTEXT_KEYS and not isinstance(value, str):
            raise ValueError(f"progress context {name} must be a string")
        if name in _MAPPING_CONTEXT_KEYS and not isinstance(value, Mapping):
            raise ValueError(f"progress context {name} must be a mapping")
        if name in _SEQUENCE_CONTEXT_KEYS and not isinstance(
            value, (list, tuple)
        ):
            raise ValueError(f"progress context {name} must be a sequence")
        if name in _INTEGER_CONTEXT_KEYS and value < 0:
            raise ValueError(f"progress context {name} must be nonnegative")
        if name in _FLOAT_CONTEXT_KEYS and (
            not math.isfinite(float(value)) or value < 0
        ):
            raise ValueError(
                f"progress context {name} must be finite and nonnegative"
            )
    endpoint_branches = values.get("endpoint_branches")
    if endpoint_branches is not None and any(
        not isinstance(branch, str) or not branch
        for branch in endpoint_branches
    ):
        raise ValueError("progress endpoint branches are invalid")
    attempted_orders = values.get("attempted_endpoint_orders")
    if attempted_orders is not None and any(
        not isinstance(branch_orders, (list, tuple))
        or any(
            isinstance(order, bool) or not isinstance(order, int) or order < 0
            for order in branch_orders
        )
        for branch_orders in attempted_orders
    ):
        raise ValueError("progress attempted endpoint orders are invalid")
    attempted_geometries = values.get("attempted_endpoint_geometries")
    if attempted_geometries is not None and any(
        not isinstance(branch_geometries, (list, tuple))
        or any(
            not isinstance(geometry, str) or not geometry
            for geometry in branch_geometries
        )
        for branch_geometries in attempted_geometries
    ):
        raise ValueError("progress attempted endpoint geometries are invalid")
    enum_values = {
        "execution_profile": {"SURVEY", "CERTIFY", "VALIDATE"},
        "survey_pass": {"binary64", "promoted", "certify", "validate"},
        "evidence_level": {"SCREENED", "CERTIFIED", "VALIDATED"},
        "precision_tier": {"binary64", "BF40", "BF80", "BF120"},
        "scope": {"REQUEST", "SAMPLE"},
        "current_action_kind": {"ROOT", "RESPONSE"},
        "current_tier": {"BF40", "BF80", "BF120"},
        "next_tier": {"BF40", "BF80", "BF120"},
        "outcome_kind": {
            "PROMOTION_PENDING",
            "UNRESOLVED",
            "DEFERRED",
            "REJECTED",
            "SYSTEM_FAILURE",
        },
    }
    for name, allowed in enum_values.items():
        if values.get(name) is not None and values[name] not in allowed:
            raise ValueError(f"progress context {name} is invalid")
    fingerprint = values.get("system_failure_fingerprint")
    if fingerprint is not None:
        try:
            valid_fingerprint = len(fingerprint) == 64 and int(fingerprint, 16) >= 0
        except (TypeError, ValueError):
            valid_fingerprint = False
        if not valid_fingerprint:
            raise ValueError("progress system failure fingerprint is invalid")
    for name in (
        "execution_identity_sha256",
        "request_sha256",
        "control_receipt_sha256",
        "control_return_sha256",
        "control_decision_sha256",
        "transition_id",
    ):
        digest = values.get(name)
        if digest is None:
            continue
        try:
            valid_digest = len(digest) == 64 and int(digest, 16) >= 0
        except (TypeError, ValueError):
            valid_digest = False
        if not valid_digest:
            raise ValueError(f"progress context {name} is invalid")
    if values.get("scope") == "REQUEST" and (
        values.get("sample_index") is not None
        or values.get("sample_role") is not None
    ):
        raise ValueError("REQUEST progress context cannot select a sample")
    if values.get("scope") == "SAMPLE" and (
        values.get("sample_index") is None
        or values.get("sample_role") is None
    ):
        raise ValueError("SAMPLE progress context requires a sample identity")
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
    seed_omega: Mapping[str, object] | None = None
    current_omega: Mapping[str, object] | None = None
    candidate_omega: Mapping[str, object] | None = None
    precision_digits: int | None = None
    component_pass: str | None = None
    readout_index: int | None = None
    readout_role: str | None = None
    epsilon: float | None = None
    amplitude: Mapping[str, object] | None = None
    phase: str | None = None
    root_phase: str | None = None
    seed_kind: str | None = None
    fallback_used: bool | None = None
    newton_index: int | None = None
    newton_limit: int | None = None
    determinant_index: int | None = None
    determinant_index_leaf: int | None = None
    determinant_index_phase: int | None = None
    determinant_index_newton: int | None = None
    determinant_purpose: str | None = None
    suboperation: str | None = None
    execution_profile: str | None = None
    survey_pass: str | None = None
    pass_disposition: str | None = None
    evidence_level: str | None = None
    promotion_reason: str | None = None
    promotion_queue_count: int | None = None
    sample_count_used: int | None = None
    sample_count_limit: int | None = None
    root_read_count: int | None = None
    root_read_limit: int | None = None
    worker_launch_count: int | None = None
    worker_launch_limit: int | None = None
    report_state: str | None = None
    system_failure_fingerprint: str | None = None
    precision_tier: str | None = None
    operation: str | None = None
    plan: str | None = None
    scope: str | None = None
    sample_index: int | None = None
    sample_role: str | None = None
    execution_identity_sha256: str | None = None
    request_sha256: str | None = None
    control_receipt_sha256: str | None = None
    control_return_sha256: str | None = None
    control_decision_sha256: str | None = None
    transition_id: str | None = None
    outcome_kind: str | None = None
    retryable: bool | None = None
    terminal: bool | None = None
    current_action_kind: str | None = None
    current_tier: str | None = None
    next_tier: str | None = None
    endpoint_branches: tuple[str, ...] | None = None
    attempted_endpoint_orders: tuple[tuple[int, ...], ...] | None = None
    attempted_endpoint_geometries: tuple[tuple[str, ...], ...] | None = None
    limiting_resource: str | None = None
    selected_intervention: str | None = None
    endpoint_recovery_result: str | None = None
    binary64_seconds: float | None = None
    bf40_seconds: float | None = None
    bf80_seconds: float | None = None
    bf120_seconds: float | None = None
    total_leaf_seconds: float | None = None

    def __post_init__(self) -> None:
        values = _validate_context_values(
            {field.name: getattr(self, field.name) for field in fields(self)}
        )
        for name in _MAPPING_CONTEXT_KEYS | _SEQUENCE_CONTEXT_KEYS:
            value = values[name]
            object.__setattr__(self, name, value)

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> "ProgressContext":
        snapshot = _validate_context_values(values)
        return cls(**snapshot)

    def to_mapping(self) -> dict[str, object]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


_PROGRESS_CONTEXT_KEYS = frozenset(field.name for field in fields(ProgressContext))


_ODE_PROGRESS_KINDS = frozenset(
    {
        ProgressEventKind.ODE_SOLVE_STARTED,
        ProgressEventKind.ODE_SOLVE_PROGRESS,
        ProgressEventKind.ODE_SOLVE_COMPLETED,
        ProgressEventKind.ODE_SOLVE_FAILED,
        ProgressEventKind.ODE_RESOURCE_LIMIT,
    }
)
_ODE_BASE_PAYLOAD_FIELDS = frozenset(
    {
        "ode_solve_id",
        "ode_leg",
        "ode_stats_scope",
        "ode_t_start",
        "ode_t_end",
        "ode_algorithm_configured",
    }
)
_ODE_COUNTER_PAYLOAD_FIELDS = frozenset(
    {
        "ode_rhs_evaluations",
        "ode_accepted_steps",
        "ode_rejected_steps",
        "ode_jacobian_evaluations",
        "ode_linear_solves",
        "ode_nonlinear_iterations",
        "ode_nonlinear_convergence_failures",
    }
)
_ODE_SNAPSHOT_PAYLOAD_FIELDS = frozenset(
    {
        "ode_t_current",
        *_ODE_COUNTER_PAYLOAD_FIELDS,
        "ode_last_accepted_step_abs",
        "ode_min_accepted_step_abs",
        "ode_proposed_step_abs",
        "elapsed_seconds",
    }
)
_ODE_TERMINAL_PAYLOAD_FIELDS = frozenset(
    {"ode_retcode", "ode_endpoint_reached"}
)
_ODE_FAILURE_PAYLOAD_FIELDS = frozenset(
    {"failure_code", "failure_class", "limit_kind", "limiting_resource"}
)
_ODE_ALLOWED_PAYLOAD_FIELDS = frozenset(
    {
        *_ODE_BASE_PAYLOAD_FIELDS,
        *_ODE_SNAPSHOT_PAYLOAD_FIELDS,
        *_ODE_TERMINAL_PAYLOAD_FIELDS,
        *_ODE_FAILURE_PAYLOAD_FIELDS,
        "request_elapsed_seconds",
        "execution_resource_policy",
    }
)


def _validate_external_payload(
    kind: ProgressEventKind, payload: Mapping[str, object]
) -> Mapping[str, object]:
    """Validate strict worker-owned payloads before publishing them locally."""

    if kind not in _ODE_PROGRESS_KINDS:
        return _mapping_snapshot(payload)
    unknown = set(payload) - _ODE_ALLOWED_PAYLOAD_FIELDS
    if unknown:
        raise ValueError(
            "unknown ODE progress payload fields: "
            + ", ".join(sorted(_safe_text(key) for key in unknown))
        )
    required = set(_ODE_BASE_PAYLOAD_FIELDS)
    if kind is not ProgressEventKind.ODE_SOLVE_STARTED:
        required.update(_ODE_SNAPSHOT_PAYLOAD_FIELDS)
    if kind in {
        ProgressEventKind.ODE_SOLVE_COMPLETED,
        ProgressEventKind.ODE_SOLVE_FAILED,
        ProgressEventKind.ODE_RESOURCE_LIMIT,
    }:
        required.update(_ODE_TERMINAL_PAYLOAD_FIELDS)
    if kind in {
        ProgressEventKind.ODE_SOLVE_FAILED,
        ProgressEventKind.ODE_RESOURCE_LIMIT,
    }:
        required.update({"failure_code", "failure_class"})
    missing = required - set(payload)
    if missing:
        raise ValueError(
            "missing ODE progress payload fields: " + ", ".join(sorted(missing))
        )

    solve_id = payload.get("ode_solve_id")
    if isinstance(solve_id, bool) or not isinstance(solve_id, int) or solve_id < 1:
        raise ValueError("ODE progress ode_solve_id must be a positive integer")
    for name in (
        "ode_leg",
        "ode_stats_scope",
        "ode_t_start",
        "ode_t_end",
        "ode_algorithm_configured",
        "ode_t_current",
        "ode_retcode",
        "failure_code",
        "failure_class",
        "limit_kind",
        "limiting_resource",
    ):
        if name in payload and not isinstance(payload[name], str):
            raise ValueError(f"ODE progress {name} must be a string")
    if payload.get("ode_stats_scope") != "leg":
        raise ValueError("ODE progress ode_stats_scope must be leg")
    for name in _ODE_COUNTER_PAYLOAD_FIELDS:
        if name in payload:
            value = payload[name]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"ODE progress {name} must be a nonnegative integer")
    if "ode_endpoint_reached" in payload and not isinstance(
        payload["ode_endpoint_reached"], bool
    ):
        raise ValueError("ODE progress ode_endpoint_reached must be a boolean")
    for name in (
        "ode_last_accepted_step_abs",
        "ode_min_accepted_step_abs",
        "ode_proposed_step_abs",
    ):
        if name in payload and payload[name] is not None and not isinstance(
            payload[name], str
        ):
            raise ValueError(f"ODE progress {name} must be a string or null")
    for name in ("elapsed_seconds", "request_elapsed_seconds"):
        if name in payload:
            elapsed = payload[name]
            if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)):
                raise ValueError(f"ODE progress {name} must be a number")
            if not math.isfinite(float(elapsed)) or elapsed < 0:
                raise ValueError(
                    f"ODE progress {name} must be finite and nonnegative"
                )
    if "execution_resource_policy" in payload:
        identity = payload["execution_resource_policy"]
        if (
            not isinstance(identity, Mapping)
            or set(identity) != {"schema", "version", "sha256"}
            or not isinstance(identity["schema"], str)
            or isinstance(identity["version"], bool)
            or not isinstance(identity["version"], int)
            or not isinstance(identity["sha256"], str)
            or len(identity["sha256"]) != 64
        ):
            raise ValueError("ODE progress resource-policy identity is invalid")
    return _mapping_snapshot(payload)


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


def current_progress_context() -> dict[str, object]:
    """Return a detached snapshot for an operational failure receipt."""

    return _ACTIVE_CONTEXT.get().to_mapping()


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
    validated_context = _validate_context_values(context)
    validated_payload = _validate_external_payload(kind, payload)
    with progress_scope(**validated_context):
        return emit_progress(kind, **validated_payload)
