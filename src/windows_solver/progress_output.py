"""Human and JSONL renderers for typed campaign progress events."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time
from typing import TextIO
from uuid import uuid4

from .progress import PROGRESS_SCHEMA, ProgressEvent, ProgressEventKind, ProgressMode


_QUIET_KINDS = frozenset(
    {
        ProgressEventKind.CAMPAIGN_COMPLETED,
        ProgressEventKind.CAMPAIGN_FAILED,
        ProgressEventKind.LEAF_STARTED,
        ProgressEventKind.LEAF_REUSED,
        ProgressEventKind.LEAF_COMPLETED,
        ProgressEventKind.LEAF_FAILED,
        ProgressEventKind.ERROR,
    }
)
_NORMAL_KINDS = _QUIET_KINDS | frozenset(
    {
        ProgressEventKind.CAMPAIGN_STARTED,
        ProgressEventKind.CHECKPOINT_WRITING,
        ProgressEventKind.CHECKPOINT_WRITTEN,
        ProgressEventKind.PRECISION_STAGE_STARTED,
        ProgressEventKind.PRECISION_STAGE_COMPLETED,
        ProgressEventKind.COMPONENT_PASS_STARTED,
        ProgressEventKind.COMPONENT_PASS_COMPLETED,
        ProgressEventKind.AMPLITUDE_READOUT_STARTED,
        ProgressEventKind.AMPLITUDE_READOUT_COMPLETED,
        ProgressEventKind.ROOT_PHASE_STARTED,
        ProgressEventKind.ROOT_PHASE_COMPLETED,
        ProgressEventKind.NEWTON_ITERATION_STARTED,
        ProgressEventKind.NEWTON_ITERATION_COMPLETED,
        ProgressEventKind.REQUEST_STARTED,
        ProgressEventKind.REQUEST_VALIDATED,
        ProgressEventKind.REQUEST_COMPLETED,
        ProgressEventKind.REQUEST_FAILED,
    }
)
_TERMINAL_KINDS = frozenset(
    {
        ProgressEventKind.CAMPAIGN_COMPLETED,
        ProgressEventKind.CAMPAIGN_FAILED,
        ProgressEventKind.LEAF_COMPLETED,
        ProgressEventKind.LEAF_FAILED,
        ProgressEventKind.ERROR,
    }
)
_FORCED_STATUS_KINDS = frozenset(
    {
        ProgressEventKind.REQUEST_STARTED,
        ProgressEventKind.REQUEST_COMPLETED,
        ProgressEventKind.REQUEST_FAILED,
        ProgressEventKind.CAMPAIGN_STARTED,
        ProgressEventKind.CAMPAIGN_COMPLETED,
        ProgressEventKind.CAMPAIGN_FAILED,
        ProgressEventKind.LEAF_STARTED,
        ProgressEventKind.LEAF_COMPLETED,
        ProgressEventKind.LEAF_FAILED,
        ProgressEventKind.PRECISION_STAGE_STARTED,
        ProgressEventKind.ERROR,
    }
)
_STATUS_INTERVAL_SECONDS = 0.25


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_json_value(item) for item in value), key=repr)
    if isinstance(value, complex):
        return {"real": _json_value(value.real), "imaginary": _json_value(value.imag)}
    if isinstance(value, float) and not math.isfinite(value):
        if math.isnan(value):
            return "nan"
        return "+inf" if value > 0 else "-inf"
    if isinstance(value, ProgressMode):
        return value.value
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


class CampaignProgressReporter:
    """Render out-of-band progress without allowing output failures to abort work."""

    def __init__(
        self,
        mode: ProgressMode | str,
        checkpoint: Path | str,
        stream: TextIO | None = None,
    ) -> None:
        self.mode = ProgressMode(mode)
        self.checkpoint = Path(checkpoint)
        self.stream = sys.stderr if stream is None else stream
        self.session = uuid4().hex
        self._started = time.monotonic()
        self._sequence = 0
        self._status_open = False
        self._traced_leaf_paths: set[Path] = set()
        self._phase_counters: dict[tuple[object, object, object], dict[str, int]] = {}
        self._leaf_determinants: dict[object, int] = {}
        self._newton_determinants: dict[
            tuple[object, object, object, object], int
        ] = {}
        self._active_newton: dict[tuple[object, object, object], object] = {}
        self._leaf_started: dict[object, float] = {}
        self._root_started: dict[tuple[object, object, object], float] = {}
        self._newton_started: dict[
            tuple[object, object, object, object], float
        ] = {}
        self._current_determinants: dict[tuple[object, object, object], object] = {}
        self._best_determinants: dict[
            tuple[object, object, object], tuple[float, object]
        ] = {}
        self._last_status_seconds: float | None = None
        self.diagnostics: list[str] = []

    def publish(self, event: ProgressEvent) -> None:
        """Add renderer metadata and safely render one event."""

        try:
            record = self._record(event)
            if self._should_write_status(event):
                self._write_status(record)
            self._render(event, record)
            if self.mode is ProgressMode.TRACE:
                self._append_trace(record)
        except Exception as error:  # Progress must never change solver outcome.
            self._report_failure(error)

    def _record(self, event: ProgressEvent) -> dict[str, object]:
        context = event.context.to_mapping()
        counter_key = (
            context["leaf_id"], context["readout_index"], context["phase"]
        )
        counters = self._phase_counters.setdefault(
            counter_key, {"newton": 0, "determinant": 0}
        )
        determinant_kinds = {
            ProgressEventKind.DETERMINANT_STARTED,
            ProgressEventKind.DETERMINANT_COMPLETED,
            ProgressEventKind.DETERMINANT_EVALUATED,
        }
        if (
            event.kind in determinant_kinds
            and context["newton_index"] is None
        ):
            context["newton_index"] = self._active_newton.get(counter_key)
        if event.kind is ProgressEventKind.NEWTON_ITERATION_STARTED:
            counters["newton"] += 1
            self._active_newton[counter_key] = context["newton_index"]
        elif event.kind is ProgressEventKind.DETERMINANT_STARTED:
            counters["determinant"] += 1
            leaf_key = context["leaf_id"]
            newton_key = (
                leaf_key,
                context["readout_index"],
                context["phase"],
                context["newton_index"],
            )
            self._leaf_determinants[leaf_key] = (
                self._leaf_determinants.get(leaf_key, 0) + 1
            )
            self._newton_determinants[newton_key] = (
                self._newton_determinants.get(newton_key, 0) + 1
            )
        if event.kind in determinant_kinds:
            leaf_key = context["leaf_id"]
            newton_key = (
                leaf_key,
                context["readout_index"],
                context["phase"],
                context["newton_index"],
            )
            context["determinant_index_leaf"] = (
                context["determinant_index_leaf"]
                or self._leaf_determinants.get(leaf_key, 0)
            )
            context["determinant_index_phase"] = (
                context["determinant_index_phase"] or counters["determinant"]
            )
            context["determinant_index_newton"] = (
                context["determinant_index_newton"]
                or self._newton_determinants.get(newton_key, 0)
            )
        self._sequence += 1
        now = event.monotonic_seconds
        leaf_key = context["leaf_id"]
        root_key = (leaf_key, context["readout_index"], context["phase"])
        newton_key = (
            leaf_key,
            context["readout_index"],
            context["phase"],
            context["newton_index"],
        )
        if event.kind is ProgressEventKind.LEAF_STARTED:
            self._leaf_started[leaf_key] = now
        if event.kind is ProgressEventKind.ROOT_PHASE_STARTED:
            self._root_started[root_key] = now
        if event.kind is ProgressEventKind.NEWTON_ITERATION_STARTED:
            self._newton_started[newton_key] = now
        determinant_key = (leaf_key, context["readout_index"], context["phase"])
        payload = event.payload
        current_determinant = payload.get("determinant_abs")
        if current_determinant is None:
            current_determinant = payload.get("resulting_determinant_abs")
        if current_determinant is not None:
            self._current_determinants[determinant_key] = current_determinant
            self._observe_best_determinant(determinant_key, current_determinant)
        declared_best = payload.get("best_determinant_abs")
        if declared_best is not None:
            self._observe_best_determinant(determinant_key, declared_best)
        record = {
            "schema": PROGRESS_SCHEMA,
            "kind": event.kind.value,
            "session": self.session,
            "sequence": self._sequence,
            "timestamp_utc": datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "elapsed_seconds": time.monotonic() - self._started,
            "monotonic_seconds": event.monotonic_seconds,
            "context": context,
            "payload": event.payload,
            "counters": dict(counters),
        }
        if leaf_key in self._leaf_started:
            record["elapsed_leaf_seconds"] = now - self._leaf_started[leaf_key]
        if root_key in self._root_started:
            record["elapsed_root_seconds"] = now - self._root_started[root_key]
        if newton_key in self._newton_started:
            record["elapsed_newton_seconds"] = now - self._newton_started[newton_key]
        if determinant_key in self._current_determinants:
            record["current_determinant_abs"] = self._current_determinants[
                determinant_key
            ]
        if determinant_key in self._best_determinants:
            record["best_determinant_abs"] = self._best_determinants[
                determinant_key
            ][1]
        return record

    def _observe_best_determinant(
        self, key: tuple[object, object, object], value: object
    ) -> None:
        try:
            comparable = float(value)
        except (TypeError, ValueError, OverflowError):
            return
        if not math.isfinite(comparable):
            return
        prior = self._best_determinants.get(key)
        if prior is None or comparable < prior[0]:
            self._best_determinants[key] = comparable, value

    def _should_write_status(self, event: ProgressEvent) -> bool:
        now = event.monotonic_seconds
        if (
            self._last_status_seconds is None
            or event.kind in _FORCED_STATUS_KINDS
            or now - self._last_status_seconds >= _STATUS_INTERVAL_SECONDS
        ):
            self._last_status_seconds = now
            return True
        return False

    def _render(self, event: ProgressEvent, record: Mapping[str, object]) -> None:
        if self.mode is ProgressMode.QUIET:
            if event.kind in _QUIET_KINDS:
                self._ordinary_line(record)
            return
        if self.mode is ProgressMode.NORMAL:
            if event.kind in {
                ProgressEventKind.DETERMINANT_STARTED,
                ProgressEventKind.DETERMINANT_COMPLETED,
                ProgressEventKind.DETERMINANT_EVALUATED,
            }:
                self._determinant_status(record)
            elif event.kind in {
                ProgressEventKind.SUBOPERATION_STARTED,
                ProgressEventKind.SUBOPERATION_COMPLETED,
            }:
                self._suboperation_status(record)
            elif event.kind in _NORMAL_KINDS:
                self._ordinary_line(record)
            return
        self._ordinary_line(record)

    def _ordinary_line(self, record: Mapping[str, object]) -> None:
        self._close_status()
        context = record["context"]
        assert isinstance(context, Mapping)
        parts = [str(record["kind"]) + "".join(self._live_identity_parts(context))]
        for name in (
            "seed_omega",
            "current_omega",
            "candidate_omega",
            "epsilon",
            "amplitude",
            "newton_index",
            "newton_limit",
            "determinant_purpose",
            "suboperation",
        ):
            value = context[name]
            if value is not None:
                label = "leaf" if name == "leaf_id" else name
                parts.append(f"{label}={value}")
        payload = record["payload"]
        assert isinstance(payload, Mapping)
        for name in (
            "current_omega",
            "determinant_abs",
            "best_determinant_abs",
            "omega",
            "residual_abs",
            "best_residual_abs",
            "duration_seconds",
        ):
            if name in payload:
                parts.append(f"{name}={payload[name]}")
        for name in (
            "elapsed_leaf_seconds",
            "elapsed_root_seconds",
            "elapsed_newton_seconds",
        ):
            if name in record:
                parts.append(f"{name}={record[name]:.3f}s")
        self.stream.write(" ".join(parts) + "\n")
        self.stream.flush()

    def _determinant_status(self, record: Mapping[str, object]) -> None:
        context = record["context"]
        counters = record["counters"]
        assert isinstance(context, Mapping)
        assert isinstance(counters, Mapping)
        payload = record["payload"]
        assert isinstance(payload, Mapping)
        details = self._live_identity_parts(context)
        purpose = context["determinant_purpose"] or payload.get("purpose")
        if purpose is not None:
            details.append(f" purpose={purpose}")
        current_omega = context["current_omega"] or payload.get("current_omega")
        candidate_omega = context["candidate_omega"] or payload.get("omega")
        if current_omega is not None:
            details.append(f" current_omega={current_omega}")
        if candidate_omega is not None:
            details.append(f" candidate_omega={candidate_omega}")
        if "current_determinant_abs" in record:
            details.append(f" current_|D|={record['current_determinant_abs']}")
        if "best_determinant_abs" in record:
            details.append(f" best_|D|={record['best_determinant_abs']}")
        newton_index = context["newton_index"] or counters["newton"]
        newton_limit = context["newton_limit"] or "?"
        leaf_index = context["determinant_index_leaf"] or counters["determinant"]
        phase_index = context["determinant_index_phase"] or counters["determinant"]
        newton_det_index = context["determinant_index_newton"] or counters["determinant"]
        self.stream.write(
            "\rdeterminant"
            f" Newton={newton_index}/{newton_limit}"
            f" leaf-total={leaf_index} phase-total={phase_index}"
            f" newton-total={newton_det_index}"
            + "".join(details)
            + self._elapsed_parts(record, payload)
        )
        self.stream.flush()
        self._status_open = True

    def _suboperation_status(self, record: Mapping[str, object]) -> None:
        context = record["context"]
        payload = record["payload"]
        assert isinstance(context, Mapping)
        assert isinstance(payload, Mapping)
        operation = context["suboperation"] or payload.get("suboperation")
        details = self._live_identity_parts(context)
        if "current_determinant_abs" in record:
            details.append(f" current_|D|={record['current_determinant_abs']}")
        if "best_determinant_abs" in record:
            details.append(f" best_|D|={record['best_determinant_abs']}")
        self.stream.write(
            "\rsuboperation"
            f" Newton={context['newton_index'] or '?'}"
            f" purpose={context['determinant_purpose']}"
            f" current={operation}"
            + "".join(details)
            + self._elapsed_parts(record, payload)
        )
        self.stream.flush()
        self._status_open = True

    @staticmethod
    def _live_identity_parts(context: Mapping[str, object]) -> list[str]:
        parts: list[str] = []
        leaf_index = context["leaf_index"]
        leaf_count = context["leaf_count"]
        if leaf_index is not None and leaf_count is not None:
            parts.append(f" leaf={leaf_index}/{leaf_count}")
        if context["leaf_id"] is not None:
            parts.append(f" leaf_id={context['leaf_id']}")
        if context["role"] is not None:
            parts.append(f" role={context['role']}")
        mode = context["mode"]
        if isinstance(mode, Mapping):
            parts.append(
                " s={s} ell={ell} m={m} n={n}".format(
                    s=mode.get("s"),
                    ell=mode.get("ell"),
                    m=mode.get("m"),
                    n=mode.get("n"),
                )
            )
        if context["spin"] is not None:
            parts.append(f" a/M={context['spin']}")
        if context["sampling_coordinate"] is not None:
            parts.append(f" source={context['sampling_coordinate']}")
        if context["mechanism_id"] is not None:
            parts.append(f" mechanism={context['mechanism_id']}")
        if context["precision_digits"] is not None:
            parts.append(f" precision={context['precision_digits']}")
        if context["component_pass"] is not None:
            parts.append(f" component={context['component_pass']}")
        if context["readout_role"] is not None:
            parts.append(
                f" readout={context['readout_index']}:{context['readout_role']}"
            )
        if context["phase"] is not None:
            parts.append(f" root_phase={context['phase']}")
        return parts

    @staticmethod
    def _elapsed_parts(
        record: Mapping[str, object], payload: Mapping[str, object]
    ) -> str:
        parts = [f" campaign={record['elapsed_seconds']:.3f}s"]
        for record_name, label in (
            ("elapsed_leaf_seconds", "leaf"),
            ("elapsed_root_seconds", "root"),
            ("elapsed_newton_seconds", "Newton"),
        ):
            if record_name in record:
                parts.append(f" {label}={record[record_name]:.3f}s")
        if "elapsed_seconds" in payload:
            parts.append(f" evaluation={payload['elapsed_seconds']}s")
        return " elapsed" + "".join(parts)

    def _close_status(self) -> None:
        if self._status_open:
            self.stream.write("\n")
            self.stream.flush()
            self._status_open = False

    def _append_trace(self, record: Mapping[str, object]) -> None:
        context = record["context"]
        assert isinstance(context, Mapping)
        leaf_index = context["leaf_index"]
        if isinstance(leaf_index, bool) or not isinstance(leaf_index, int):
            return
        path = Path(f"{self.checkpoint}.progress") / f"leaf-{leaf_index:06d}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path not in self._traced_leaf_paths:
            marker = dict(record)
            marker["kind"] = "session_started"
            self._write_jsonl(path, marker)
            self._traced_leaf_paths.add(path)
            self._sequence += 1
            assert isinstance(record, dict)
            record["sequence"] = self._sequence
        self._write_jsonl(path, record)

    def _write_status(self, record: Mapping[str, object]) -> None:
        """Atomically replace the diagnostic snapshot inspected by other processes."""

        path = Path(f"{self.checkpoint}.status.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(
            _json_value(record), ensure_ascii=False, allow_nan=False,
            separators=(",", ":"), sort_keys=True,
        ).encode("utf-8")
        descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(descriptor, "wb") as temporary:
                temporary.write(encoded)
                temporary.flush()
            os.replace(temporary_name, path)
        except BaseException:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise

    def close(self) -> None:
        self._close_status()

    @staticmethod
    def _write_jsonl(path: Path, record: Mapping[str, object]) -> None:
        encoded = json.dumps(
            _json_value(record), ensure_ascii=False, allow_nan=False,
            separators=(",", ":"), sort_keys=True,
        )
        with path.open("a", encoding="utf-8") as trace:
            trace.write(encoded + "\n")
            trace.flush()

    def _report_failure(self, error: Exception) -> None:
        message = f"progress diagnostic: {type(error).__name__}: {error}"
        self.diagnostics.append(message)
        try:
            self._close_status()
            self.stream.write(message + "\n")
            self.stream.flush()
        except Exception:
            pass
