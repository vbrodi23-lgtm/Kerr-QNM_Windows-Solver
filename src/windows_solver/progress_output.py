"""Human and JSONL renderers for typed campaign progress events."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
import time
from typing import TextIO
from uuid import uuid4

from .progress import PROGRESS_SCHEMA, ProgressEvent, ProgressEventKind, ProgressMode


_QUIET_KINDS = frozenset(
    {
        ProgressEventKind.CAMPAIGN_STARTED,
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
        self._phase_counters: dict[tuple[object, object], dict[str, int]] = {}
        self.diagnostics: list[str] = []

    def publish(self, event: ProgressEvent) -> None:
        """Add renderer metadata and safely render one event."""

        try:
            record = self._record(event)
            self._render(event, record)
            if self.mode is ProgressMode.TRACE:
                self._append_trace(record)
        except Exception as error:  # Progress must never change solver outcome.
            self._report_failure(error)

    def _record(self, event: ProgressEvent) -> dict[str, object]:
        context = event.context.to_mapping()
        counter_key = (context["leaf_id"], context["phase"])
        counters = self._phase_counters.setdefault(
            counter_key, {"newton": 0, "determinant": 0}
        )
        if event.kind is ProgressEventKind.NEWTON_ITERATION_STARTED:
            counters["newton"] += 1
        elif event.kind is ProgressEventKind.DETERMINANT_EVALUATED:
            counters["determinant"] += 1
        self._sequence += 1
        return {
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

    def _render(self, event: ProgressEvent, record: Mapping[str, object]) -> None:
        if self.mode is ProgressMode.QUIET:
            if event.kind in _QUIET_KINDS:
                self._ordinary_line(record)
            return
        if self.mode is ProgressMode.NORMAL:
            if event.kind is ProgressEventKind.DETERMINANT_EVALUATED:
                self._determinant_status(record)
            elif event.kind in _NORMAL_KINDS:
                self._ordinary_line(record)
            return
        self._ordinary_line(record)

    def _ordinary_line(self, record: Mapping[str, object]) -> None:
        self._close_status()
        context = record["context"]
        assert isinstance(context, Mapping)
        parts = [str(record["kind"])]
        for name in (
            "leaf_id",
            "leaf_index",
            "leaf_count",
            "role",
            "mode",
            "spin",
            "mechanism_id",
            "precision_digits",
            "component_pass",
            "readout_index",
            "readout_role",
            "phase",
        ):
            value = context[name]
            if value is not None:
                label = "leaf" if name == "leaf_id" else name
                parts.append(f"{label}={value}")
        payload = record["payload"]
        assert isinstance(payload, Mapping)
        for name in ("omega", "residual_abs", "best_residual_abs", "duration_seconds"):
            if name in payload:
                parts.append(f"{name}={payload[name]}")
        self.stream.write(" ".join(parts) + "\n")
        self.stream.flush()

    def _determinant_status(self, record: Mapping[str, object]) -> None:
        context = record["context"]
        counters = record["counters"]
        assert isinstance(context, Mapping)
        assert isinstance(counters, Mapping)
        payload = record["payload"]
        assert isinstance(payload, Mapping)
        details = []
        for name in ("omega", "residual_abs", "best_residual_abs"):
            if name in payload:
                details.append(f" {name}={payload[name]}")
        purpose = context["determinant_purpose"] or payload.get("purpose")
        if purpose is not None:
            details.append(f" purpose={purpose}")
        self.stream.write(
            "\rdeterminant"
            f" leaf={context['leaf_id']} phase={context['phase']}"
            f" newton={counters['newton']} count={counters['determinant']}"
            f" elapsed={record['elapsed_seconds']:.3f}s"
            + "".join(details)
        )
        self.stream.flush()
        self._status_open = True

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
            raise ValueError("trace event requires an integer leaf_index")
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
