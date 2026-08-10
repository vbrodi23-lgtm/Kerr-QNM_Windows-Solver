"""Human and JSONL renderers for typed campaign progress events."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
from statistics import fmean, median
import sys
import tempfile
import time
from typing import TYPE_CHECKING, TextIO
from uuid import uuid4

from .campaign_reports import CampaignReportModel, refresh_campaign_reports
from .progress import PROGRESS_SCHEMA, ProgressEvent, ProgressEventKind, ProgressMode

if TYPE_CHECKING:
    from .response_batches import CampaignPlan


_QUIET_KINDS = frozenset(
    {
        ProgressEventKind.CAMPAIGN_COMPLETED,
        ProgressEventKind.CAMPAIGN_FAILED,
        ProgressEventKind.LEAF_STARTED,
        ProgressEventKind.LEAF_REUSED,
        ProgressEventKind.LEAF_CACHE_STALE,
        ProgressEventKind.LEAF_CACHE_CORRUPT,
        ProgressEventKind.LEAF_CACHE_PUBLICATION_FAILED,
        ProgressEventKind.LEAF_COMPLETED,
        ProgressEventKind.LEAF_FAILED,
        ProgressEventKind.ERROR,
    }
)
_NORMAL_KINDS = _QUIET_KINDS | frozenset(
    {
        ProgressEventKind.SOLVED_LEAF_CACHE_SCANNED,
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
        ProgressEventKind.ROOT_SEED_SELECTED,
        ProgressEventKind.ROOT_PHASE_COMPLETED,
        ProgressEventKind.NEWTON_ITERATION_STARTED,
        ProgressEventKind.NEWTON_ITERATION_COMPLETED,
        ProgressEventKind.REQUEST_STARTED,
        ProgressEventKind.REQUEST_VALIDATED,
        ProgressEventKind.REQUEST_COMPLETED,
        ProgressEventKind.REQUEST_FAILED,
        ProgressEventKind.LEAF_CACHE_PUBLISHED,
    }
)
_NORMAL_FALLBACK_KINDS = _NORMAL_KINDS | frozenset(
    {
        ProgressEventKind.DETERMINANT_COMPLETED,
        ProgressEventKind.DETERMINANT_EVALUATED,
        ProgressEventKind.SUBOPERATION_COMPLETED,
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
        ProgressEventKind.LEAF_REUSED,
        ProgressEventKind.LEAF_CACHE_STALE,
        ProgressEventKind.LEAF_CACHE_CORRUPT,
        ProgressEventKind.LEAF_CACHE_PUBLICATION_FAILED,
        ProgressEventKind.SOLVED_LEAF_CACHE_SCANNED,
        ProgressEventKind.LEAF_COMPLETED,
        ProgressEventKind.LEAF_FAILED,
        ProgressEventKind.PRECISION_STAGE_STARTED,
        ProgressEventKind.ERROR,
    }
)
_STATUS_INTERVAL_SECONDS = 0.25
_LEAF_TIMING_WINDOW = 10


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
        if stream is None:
            if self.mode is ProgressMode.NORMAL and self._is_terminal(sys.stdout):
                stream = sys.stdout
            else:
                stream = sys.stderr
        self.stream = stream
        self.session = uuid4().hex
        self._started = time.monotonic()
        self._sequence = 0
        self._status_open = False
        self._traced_leaf_paths: set[Path] = set()
        self._phase_counters: dict[tuple[object, ...], dict[str, int]] = {}
        self._leaf_determinants: dict[object, int] = {}
        self._newton_determinants: dict[
            tuple[object, ...], int
        ] = {}
        self._active_newton: dict[tuple[object, ...], object] = {}
        self._leaf_started: dict[object, float] = {}
        self._completed_leaf_seconds: deque[float] = deque(
            maxlen=_LEAF_TIMING_WINDOW
        )
        self._settled_leaf_ids: set[object] = set()
        self._accepted_leaf_ids: set[object] = set()
        self._rejected_leaf_ids: set[object] = set()
        self._indeterminate_leaf_ids: set[object] = set()
        self._failed_leaf_ids: set[object] = set()
        self._last_accepted_leaf: object | None = None
        self._checkpoint_status = "not yet written"
        self._campaign_status = "PENDING"
        self._cache_compatible = 0
        self._cache_stored = 0
        self._cache_reusing = 0
        self._cache_next_unsolved: object = None
        self._cache_published_leaf_ids: set[object] = set()
        self._cache_publication_failures: dict[object, dict[str, object]] = {}
        self._root_started: dict[tuple[object, ...], float] = {}
        self._newton_started: dict[
            tuple[object, ...], float
        ] = {}
        self._current_determinants: dict[tuple[object, ...], object] = {}
        self._best_determinants: dict[
            tuple[object, ...], tuple[float, object]
        ] = {}
        self._root_seed_state: dict[
            tuple[object, ...], dict[str, object]
        ] = {}
        self._primary_seed_stats: dict[str, dict[str, float | int]] = {}
        self._completed_primary_roots: set[tuple[object, ...]] = set()
        self._last_status_seconds: float | None = None
        self._last_dashboard_seconds: float | None = None
        self._dashboard_rendered_rows = 0
        self._terminal_dashboard = self._stream_is_terminal()
        if self._terminal_dashboard:
            self._terminal_dashboard = self._enable_virtual_terminal()
        self._dashboard_state: dict[str, object] = {}
        self._campaign_report_plan: CampaignPlan | None = None
        self._campaign_report_model: CampaignReportModel | None = None
        self._report_run_provenance: dict[str, str] = {}
        self.diagnostics: list[str] = []

    def bind_campaign_reports(self, plan: CampaignPlan) -> None:
        """Enable derived reports without placing them in campaign execution."""

        self._campaign_report_plan = plan
        if self.checkpoint.is_file():
            self._refresh_campaign_reports()

    def publish(self, event: ProgressEvent) -> None:
        """Add renderer metadata and safely render one event."""

        try:
            if (
                event.kind is ProgressEventKind.LEAF_STARTED
                and event.context.leaf_id is not None
            ):
                self._report_run_provenance[event.context.leaf_id] = "EXECUTED"
            if event.kind in {
                ProgressEventKind.CHECKPOINT_WRITTEN,
                ProgressEventKind.CAMPAIGN_COMPLETED,
            }:
                self._refresh_campaign_reports()
            record = self._record(event)
            self._update_dashboard_state(record)
            if self._should_write_status(event):
                self._write_status(record)
            self._render(event, record)
            if "root_solve" in record:
                self._append_root_solve(record)
            if self.mode is ProgressMode.TRACE:
                self._append_trace(record)
        except Exception as error:  # Progress must never change solver outcome.
            self._report_failure(error)

    def _refresh_campaign_reports(self) -> None:
        plan = self._campaign_report_plan
        if plan is None or not self.checkpoint.is_file():
            return
        try:
            self._campaign_report_model = refresh_campaign_reports(
                plan,
                self.checkpoint,
                run_provenance=self._report_run_provenance,
            )
        except Exception as error:
            self._report_failure(error)

    def _record(self, event: ProgressEvent) -> dict[str, object]:
        context = event.context.to_mapping()
        counter_key = (
            context["leaf_id"],
            context["precision_digits"],
            context["component_pass"],
            context["readout_index"],
            context["phase"],
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
                *counter_key,
                context["newton_index"],
            )
            self._leaf_determinants[leaf_key] = (
                self._leaf_determinants.get(leaf_key, 0) + 1
            )
            self._newton_determinants[newton_key] = (
                self._newton_determinants.get(newton_key, 0) + 1
            )
        if context["leaf_id"] is not None:
            leaf_key = context["leaf_id"]
            newton_key = (
                *counter_key,
                context["newton_index"],
            )
            context["determinant_index_leaf"] = (
                context["determinant_index_leaf"]
                or self._leaf_determinants.get(leaf_key)
            )
            context["determinant_index_phase"] = (
                context["determinant_index_phase"]
                or (counters["determinant"] or None)
            )
            context["determinant_index_newton"] = (
                context["determinant_index_newton"]
                or self._newton_determinants.get(newton_key)
            )
        self._sequence += 1
        now = event.monotonic_seconds
        leaf_key = context["leaf_id"]
        root_key = counter_key
        newton_key = (
            *root_key,
            context["newton_index"],
        )
        if event.kind is ProgressEventKind.LEAF_STARTED:
            self._leaf_started[leaf_key] = now
        if (
            event.kind in {
                ProgressEventKind.LEAF_COMPLETED,
                ProgressEventKind.LEAF_REUSED,
            }
            and leaf_key is not None
            and leaf_key not in self._settled_leaf_ids
        ):
            if (
                event.kind is ProgressEventKind.LEAF_COMPLETED
                and leaf_key in self._leaf_started
            ):
                duration = now - self._leaf_started[leaf_key]
                if math.isfinite(duration) and duration >= 0:
                    self._completed_leaf_seconds.append(duration)
            self._settled_leaf_ids.add(leaf_key)
        if event.kind is ProgressEventKind.ROOT_PHASE_STARTED:
            self._root_started[root_key] = now
        if event.kind is ProgressEventKind.NEWTON_ITERATION_STARTED:
            self._newton_started[newton_key] = now
        determinant_key = root_key
        payload = event.payload
        if event.kind is ProgressEventKind.ROOT_SEED_SELECTED:
            prior_seed = self._root_seed_state.get(root_key, {})
            predictor_initial = prior_seed.get("initial_determinant_abs")
            fallback_used = bool(payload.get("fallback_used", False))
            self._root_seed_state[root_key] = {
                "requested_seed_kind": payload.get("requested_seed_kind"),
                "seed_kind": payload.get("seed_kind"),
                "seed_omega": payload.get("seed_omega"),
                "fallback_used": fallback_used,
                "fallback_reason": payload.get("fallback_reason"),
                "fallback_error_type": payload.get("fallback_error_type"),
                "initial_determinant_abs": None,
                "predictor_initial_determinant_abs": (
                    predictor_initial if fallback_used else None
                ),
            }
        if event.kind is ProgressEventKind.DETERMINANT_COMPLETED:
            seed_state = self._root_seed_state.get(root_key)
            if (
                seed_state is not None
                and seed_state.get("initial_determinant_abs") is None
                and payload.get("determinant_abs") is not None
            ):
                seed_state["initial_determinant_abs"] = payload["determinant_abs"]
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
        if event.kind is ProgressEventKind.ROOT_PHASE_COMPLETED:
            seed_state = dict(self._root_seed_state.get(root_key, {}))
            root_solve = {
                **seed_state,
                "newton_iterations": counters["newton"],
                "determinant_calls": counters["determinant"],
                "resulting_omega": payload.get("resulting_omega"),
                "resulting_determinant_abs": payload.get(
                    "resulting_determinant_abs"
                ),
                "converged": payload.get("converged"),
                "elapsed_seconds": payload.get("elapsed_seconds"),
            }
            record["root_solve"] = root_solve
            if context["phase"] == "PRIMARY" and root_key not in self._completed_primary_roots:
                self._completed_primary_roots.add(root_key)
                self._observe_primary_seed_result(root_solve)
        record["momentum_summary"] = self._momentum_summary()
        self._add_leaf_timing_estimate(record, context)
        return record

    def _observe_primary_seed_result(self, root_solve: Mapping[str, object]) -> None:
        seed_kind = root_solve.get("seed_kind")
        if not isinstance(seed_kind, str) or not seed_kind:
            return
        stats = self._primary_seed_stats.setdefault(
            seed_kind,
            {
                "solve_count": 0,
                "fallback_count": 0,
                "total_newton_iterations": 0,
                "total_determinant_calls": 0,
                "total_elapsed_seconds": 0.0,
            },
        )
        stats["solve_count"] += 1
        stats["fallback_count"] += int(bool(root_solve.get("fallback_used")))
        stats["total_newton_iterations"] += int(
            root_solve.get("newton_iterations", 0)
        )
        stats["total_determinant_calls"] += int(
            root_solve.get("determinant_calls", 0)
        )
        try:
            elapsed = float(root_solve.get("elapsed_seconds", 0.0))
        except (TypeError, ValueError, OverflowError):
            elapsed = 0.0
        if math.isfinite(elapsed) and elapsed >= 0.0:
            stats["total_elapsed_seconds"] += elapsed

    def _momentum_summary(self) -> dict[str, object]:
        by_seed_kind: dict[str, dict[str, object]] = {}
        for seed_kind in sorted(self._primary_seed_stats):
            raw = self._primary_seed_stats[seed_kind]
            count = int(raw["solve_count"])
            by_seed_kind[seed_kind] = {
                "solve_count": count,
                "fallback_count": int(raw["fallback_count"]),
                "total_newton_iterations": int(raw["total_newton_iterations"]),
                "average_newton_iterations": (
                    float(raw["total_newton_iterations"]) / count
                ),
                "total_determinant_calls": int(raw["total_determinant_calls"]),
                "average_determinant_calls": (
                    float(raw["total_determinant_calls"]) / count
                ),
                "total_elapsed_seconds": float(raw["total_elapsed_seconds"]),
                "mean_solve_seconds": float(raw["total_elapsed_seconds"]) / count,
            }
        epsilon_count = sum(
            int(by_seed_kind.get(kind, {}).get("solve_count", 0))
            for kind in ("EPSILON_CONTINUATION", "FALLBACK_BACKGROUND")
        )
        fallback_count = int(
            by_seed_kind.get("FALLBACK_BACKGROUND", {}).get("solve_count", 0)
        )
        background = by_seed_kind.get("AUTHENTICATED_BACKGROUND")
        epsilon = by_seed_kind.get("EPSILON_CONTINUATION")
        observed_delta = None
        if background is not None and epsilon is not None:
            observed_delta = (
                float(background["average_determinant_calls"])
                - float(epsilon["average_determinant_calls"])
            )
        return {
            "primary_solve_count": sum(
                int(item["solve_count"]) for item in by_seed_kind.values()
            ),
            "epsilon_continuation_fallback_rate": (
                None if epsilon_count == 0 else fallback_count / epsilon_count
            ),
            "observed_epsilon_determinant_call_delta_vs_background_mean": observed_delta,
            "by_seed_kind": by_seed_kind,
        }

    def _add_leaf_timing_estimate(
        self, record: dict[str, object], context: Mapping[str, object]
    ) -> None:
        if not self._completed_leaf_seconds:
            return
        leaf_count = context["leaf_count"]
        if isinstance(leaf_count, bool) or not isinstance(leaf_count, int):
            return
        average = fmean(self._completed_leaf_seconds)
        midpoint = median(self._completed_leaf_seconds)
        remaining = max(0, leaf_count - len(self._settled_leaf_ids))
        eta_seconds = average * remaining
        finish = datetime.now().astimezone() + timedelta(seconds=eta_seconds)
        record.update(
            {
                "leaf_timing_sample_size": len(self._completed_leaf_seconds),
                "leaf_timing_window_size": _LEAF_TIMING_WINDOW,
                "average_leaf_seconds": average,
                "median_leaf_seconds": midpoint,
                "eta_seconds": eta_seconds,
                "estimated_finish": finish.isoformat(timespec="minutes"),
            }
        )

    def _observe_best_determinant(
        self, key: tuple[object, ...], value: object
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
            if self._terminal_dashboard:
                if self._should_render_dashboard(event):
                    self._dashboard(record)
            elif event.kind in _NORMAL_FALLBACK_KINDS:
                self._ordinary_line(record)
            return
        self._ordinary_line(record)

    def _stream_is_terminal(self) -> bool:
        return self._is_terminal(self.stream)

    @staticmethod
    def _is_terminal(stream: TextIO) -> bool:
        try:
            return bool(stream.isatty())
        except (AttributeError, OSError):
            return False

    def _enable_virtual_terminal(self) -> bool:
        if os.name != "nt":
            return True
        try:
            import ctypes
            import msvcrt

            handle = msvcrt.get_osfhandle(self.stream.fileno())
            mode = ctypes.c_ulong()
            kernel32 = ctypes.windll.kernel32
            if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                return False
            enable_virtual_terminal_processing = 0x0004
            return bool(
                kernel32.SetConsoleMode(
                    handle, mode.value | enable_virtual_terminal_processing
                )
            )
        except (AttributeError, ImportError, OSError, ValueError):
            return False

    def _should_render_dashboard(self, event: ProgressEvent) -> bool:
        now = event.monotonic_seconds
        if (
            self._last_dashboard_seconds is None
            or event.kind in _FORCED_STATUS_KINDS
            or now - self._last_dashboard_seconds >= _STATUS_INTERVAL_SECONDS
        ):
            self._last_dashboard_seconds = now
            return True
        return False

    def _dashboard(self, record: Mapping[str, object]) -> None:
        lines = self._bounded_dashboard_lines(record)
        if self._dashboard_rendered_rows:
            # Redraw relative to the current cursor.  A saved screen position is
            # not stable once a first render scrolls a short console.
            self.stream.write(f"\x1b[{self._dashboard_rendered_rows}F")
        # Erase only the dashboard region below the current cursor.  Do not use
        # Clear-Host or ESC[2J: bootstrap and command history must remain in
        # scrollback.
        self.stream.write("\x1b[0J")
        self.stream.write("\n".join(lines) + "\n")
        self.stream.flush()
        self._dashboard_rendered_rows = len(lines)

    def _bounded_dashboard_lines(self, record: Mapping[str, object]) -> list[str]:
        columns, terminal_rows = self._terminal_dimensions()
        maximum_rows = max(1, terminal_rows - 1)
        lines = self._dashboard_lines(record)
        if len(lines) > maximum_rows:
            lines = self._compact_dashboard_lines(record)
        return [self._fit_dashboard_line(line, columns) for line in lines[:maximum_rows]]

    def _terminal_dimensions(self) -> tuple[int, int]:
        try:
            size = os.get_terminal_size(self.stream.fileno())
        except (AttributeError, OSError, ValueError):
            # Preserve the full Format-List view for terminal-like streams that
            # do not expose a file descriptor (including test and embedded hosts).
            return 120, 50
        return max(1, size.columns), max(2, size.lines)

    @staticmethod
    def _fit_dashboard_line(line: str, columns: int) -> str:
        if len(line) <= columns:
            return line
        if columns == 1:
            return "…"
        return line[: columns - 1] + "…"

    def _update_dashboard_state(self, record: Mapping[str, object]) -> None:
        context = record["context"]
        assert isinstance(context, Mapping)
        payload = record["payload"]
        assert isinstance(payload, Mapping)
        kind = record["kind"]
        if kind == ProgressEventKind.SOLVED_LEAF_CACHE_SCANNED.value:
            self._cache_compatible = int(payload.get("compatible_count", 0))
            self._cache_stored = int(payload.get("stored_count", 0))
            self._cache_reusing = int(payload.get("reusing_count", 0))
            self._cache_next_unsolved = payload.get("next_unsolved_index")
        elif kind == ProgressEventKind.LEAF_CACHE_PUBLISHED.value:
            leaf_id = context.get("leaf_id")
            if leaf_id is not None:
                self._cache_published_leaf_ids.add(leaf_id)
                self._cache_publication_failures.pop(leaf_id, None)
        elif kind == ProgressEventKind.LEAF_CACHE_PUBLICATION_FAILED.value:
            leaf_id = context.get("leaf_id")
            if leaf_id is not None:
                self._cache_published_leaf_ids.discard(leaf_id)
                self._cache_publication_failures[leaf_id] = {
                    "leaf_id": leaf_id,
                    "leaf_index": context.get("leaf_index"),
                    "store_path": payload.get("store_path"),
                    "error_type": payload.get("error_type"),
                    "message": payload.get("message"),
                    "sequence": record.get("sequence"),
                    "timestamp_utc": record.get("timestamp_utc"),
                }
        prior_leaf = self._dashboard_state.get("leaf_id")
        next_leaf = context["leaf_id"]
        if next_leaf is not None and next_leaf != prior_leaf:
            self._dashboard_state.clear()
            self._dashboard_state.update(
                {
                    "leaf_status": "RUNNING",
                    "root_status": "PENDING",
                    "precision_status": "PENDING",
                }
            )
        else:
            prior_readout = self._dashboard_state.get("readout_index")
            next_readout = context["readout_index"]
            prior_phase = self._dashboard_state.get("phase")
            next_phase = context["phase"]
            if (
                next_readout is not None
                and prior_readout is not None
                and next_readout != prior_readout
            ) or (
                next_phase is not None
                and prior_phase is not None
                and next_phase != prior_phase
            ):
                for name in (
                    "current_omega",
                    "candidate_omega",
                    "newton_index",
                    "newton_limit",
                    "determinant_index_phase",
                    "determinant_index_newton",
                    "determinant_abs",
                    "suboperation",
                ):
                    self._dashboard_state.pop(name, None)
        for name, value in context.items():
            if value is not None:
                self._dashboard_state[name] = value
        determinant_abs = record.get("current_determinant_abs")
        if determinant_abs is not None:
            self._dashboard_state["determinant_abs"] = determinant_abs
        best_determinant_abs = record.get("best_determinant_abs")
        if best_determinant_abs is not None:
            self._dashboard_state["best_determinant_abs"] = best_determinant_abs
        acceptance_threshold = payload.get("acceptance_threshold")
        if acceptance_threshold is not None:
            self._dashboard_state["acceptance_threshold"] = acceptance_threshold
        if kind == ProgressEventKind.LEAF_STARTED.value:
            self._dashboard_state["leaf_status"] = "RUNNING"
        elif kind in {
            ProgressEventKind.LEAF_COMPLETED.value,
            ProgressEventKind.LEAF_REUSED.value,
        }:
            self._record_leaf_outcome(next_leaf, payload.get("state"))
        elif kind == ProgressEventKind.LEAF_FAILED.value:
            self._dashboard_state["leaf_status"] = "FAILED"
            if next_leaf is not None:
                self._discard_leaf_outcomes(next_leaf)
                self._failed_leaf_ids.add(next_leaf)
        elif kind == ProgressEventKind.ROOT_PHASE_STARTED.value:
            self._dashboard_state["root_status"] = "SEARCHING"
        elif kind == ProgressEventKind.ROOT_PHASE_COMPLETED.value:
            converged = payload.get("converged")
            if converged is True:
                self._dashboard_state["root_status"] = "CONVERGED"
            elif converged is False:
                self._dashboard_state["root_status"] = "NOT_CONVERGED"
        elif kind == ProgressEventKind.PRECISION_STAGE_STARTED.value:
            self._dashboard_state["precision_status"] = "ACTIVE"
        elif kind == ProgressEventKind.PRECISION_STAGE_COMPLETED.value:
            numerical_state = payload.get("numerical_state")
            if numerical_state is not None:
                self._dashboard_state["precision_status"] = numerical_state
            if payload.get("leaf_state") == "MISSING_PRECISION":
                self._dashboard_state["leaf_status"] = "MISSING_PRECISION"
        elif kind == ProgressEventKind.CHECKPOINT_WRITING.value:
            self._checkpoint_status = "writing"
        elif kind == ProgressEventKind.CHECKPOINT_WRITTEN.value:
            self._checkpoint_status = "written"
        elif kind == ProgressEventKind.CAMPAIGN_STARTED.value:
            self._campaign_status = "RUNNING"
        elif kind == ProgressEventKind.CAMPAIGN_COMPLETED.value:
            state = payload.get("state")
            self._campaign_status = str(state) if state is not None else "COMPLETED"
            if (
                self._campaign_status == "PARTIAL"
                and self._dashboard_state.get("leaf_status") == "RUNNING"
            ):
                self._dashboard_state["leaf_status"] = "PARTIAL"
        elif kind == ProgressEventKind.CAMPAIGN_FAILED.value:
            self._campaign_status = "FAILED"

    def _record_leaf_outcome(self, leaf_id: object, state: object) -> None:
        if leaf_id is not None:
            self._discard_leaf_outcomes(leaf_id)
        if state == "PRODUCED":
            status = "ACCEPTED"
            target = self._accepted_leaf_ids
            self._last_accepted_leaf = leaf_id
        elif state == "UNRESOLVED":
            status = "INDETERMINATE"
            target = self._indeterminate_leaf_ids
        elif state == "REJECTED":
            status = "REJECTED"
            target = self._rejected_leaf_ids
        else:
            status = "COMPLETED"
            target = None
        self._dashboard_state["leaf_status"] = status
        if leaf_id is not None and target is not None:
            target.add(leaf_id)

    def _discard_leaf_outcomes(self, leaf_id: object) -> None:
        for outcomes in (
            self._accepted_leaf_ids,
            self._rejected_leaf_ids,
            self._indeterminate_leaf_ids,
            self._failed_leaf_ids,
        ):
            outcomes.discard(leaf_id)

    def _current_leaf_persistence(self) -> dict[str, object]:
        leaf_id = self._dashboard_state.get("leaf_id")
        return {
            "leaf_id": leaf_id,
            "terminal_computed": leaf_id in self._settled_leaf_ids,
            "checkpoint_saved": self._checkpoint_status == "written",
            "receipt_published": leaf_id in self._cache_published_leaf_ids,
            "publication_failed": leaf_id in self._cache_publication_failures,
        }

    def _persistence_status(self) -> dict[str, object]:
        failures = sorted(
            self._cache_publication_failures.values(),
            key=lambda item: (
                item.get("sequence") is None,
                item.get("sequence"),
            ),
        )
        return {
            "publication_failure_count": len(failures),
            "publication_failures": failures,
            "current_leaf": self._current_leaf_persistence(),
        }

    def _persistent_receipt_status(self) -> str:
        state = self._current_leaf_persistence()
        if state["receipt_published"]:
            return "PUBLISHED"
        if state["publication_failed"]:
            return "FAILED"
        if state["terminal_computed"] and state["checkpoint_saved"]:
            return "NOT_PUBLISHED"
        return "PENDING"

    def _latest_scientific_leaf_row(self) -> Mapping[str, object] | None:
        model = self._campaign_report_model
        if model is None:
            return None
        if self._last_accepted_leaf is not None:
            for row in model.leaf_rows:
                if row.get("leaf_id") == self._last_accepted_leaf:
                    return row
        for row in reversed(model.leaf_rows):
            if row.get("terminal_state") == "PRODUCED":
                return row
        return None

    @staticmethod
    def _projective_component_ids(value: object) -> tuple[str, ...]:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (TypeError, ValueError):
                return ()
        if not isinstance(value, list):
            return ()
        return tuple(str(item) for item in value)

    def _selected_projective_row(
        self, latest_leaf_id: object
    ) -> tuple[Mapping[str, object] | None, int, int]:
        model = self._campaign_report_model
        if model is None:
            return None, 0, 0
        rows = model.projective_rows
        resolved = tuple(
            row for row in rows if row.get("reducer_state") != "INCOMPLETE"
        )
        relevant = tuple(
            row
            for row in rows
            if latest_leaf_id is not None
            and str(latest_leaf_id)
            in self._projective_component_ids(row.get("present_component_ids"))
        )
        relevant_resolved = tuple(
            row for row in relevant if row.get("reducer_state") != "INCOMPLETE"
        )
        selected = (
            relevant_resolved[-1]
            if relevant_resolved
            else resolved[-1]
            if resolved
            else relevant[0]
            if relevant
            else rows[0]
            if rows
            else None
        )
        return selected, len(resolved), len(rows)

    def _scientific_dashboard_fields(self) -> tuple[tuple[str, object], ...]:
        if self._campaign_report_model is None:
            return ()
        row = self._latest_scientific_leaf_row()
        latest_leaf_id = None if row is None else row.get("leaf_id")
        projective, resolved_count, projective_count = (
            self._selected_projective_row(latest_leaf_id)
        )
        channels = None
        baseline = None
        signed_root = None
        if row is not None:
            channels = {
                "signed-root": row.get("signed_root_error"),
                "truncation": row.get("truncation_error"),
                "resolution": row.get("resolution_error"),
                "seed-path": row.get("seed_path_error"),
                "axis": row.get("axis_error"),
                "amplitude": row.get("amplitude_error"),
            }
            baseline = {
                "real": row.get("baseline_omega_real"),
                "imaginary": row.get("baseline_omega_imaginary"),
            }
            signed_root = {
                "real": row.get("signed_root_crosscheck_real"),
                "imaginary": row.get("signed_root_crosscheck_imaginary"),
            }
        projective_state = None
        bounds = None
        if projective is not None:
            projective_state = {
                "reducer": projective.get("reducer_state"),
                "scientific": projective.get("scientific_state"),
            }
            bounds = {
                "lower": projective.get("angle_lower_bound"),
                "upper": projective.get("angle_upper_bound"),
            }
        return (
            ("LatestResult", latest_leaf_id),
            ("ResultMode", None if row is None else row.get("mode")),
            ("ResultSpin", None if row is None else row.get("spin_or_Mkappa")),
            (
                "ResultMechanism",
                None if row is None else row.get("mechanism"),
            ),
            ("ResponseRe", None if row is None else row.get("response_real")),
            ("ResponseIm", None if row is None else row.get("response_imaginary")),
            ("ResponseAbs", None if row is None else row.get("response_magnitude")),
            ("LocalDisk", None if row is None else row.get("local_disk_radius")),
            (
                "DiskResponse",
                None if row is None else row.get("relative_disk_radius"),
            ),
            ("DiskState", None if row is None else row.get("relative_disk_state")),
            (
                "Convergence",
                None if row is None else row.get("convergence_basis"),
            ),
            ("BaselineOmega", baseline),
            (
                "BaselineResidual",
                None if row is None else row.get("baseline_determinant_residual"),
            ),
            ("SignedRoot", signed_root),
            (
                "SignedRootAbs",
                None
                if row is None
                else row.get("signed_root_crosscheck_magnitude"),
            ),
            ("ErrorChannels", channels),
            ("Projective", f"{resolved_count}/{projective_count} resolved"),
            (
                "ProjectiveRow",
                None if projective is None else projective.get("row_id"),
            ),
            ("ProjectiveState", projective_state),
            (
                "ProjectiveOutcome",
                None if projective is None else projective.get("projective_outcome"),
            ),
            (
                "FSAngle",
                None if projective is None else projective.get("nominal_angle"),
            ),
            ("FSBounds", bounds),
            (
                "SepThreshold",
                None if projective is None else projective.get("separation_threshold"),
            ),
            (
                "EquivThreshold",
                None if projective is None else projective.get("equivalence_threshold"),
            ),
            (
                "ProjectiveReason",
                None if projective is None else projective.get("reason"),
            ),
        )

    def _dashboard_fields(
        self, record: Mapping[str, object]
    ) -> tuple[tuple[str, object], ...]:
        context = self._dashboard_state
        leaf = "-"
        if context.get("leaf_index") is not None and context.get("leaf_count") is not None:
            leaf = f"{context['leaf_index']}/{context['leaf_count']}"
        return (
            ("Sequence", record["sequence"]),
            ("Event", record["kind"]),
            ("Elapsed_s", round(float(record["elapsed_seconds"]), 1)),
            ("CampaignStatus", self._campaign_status),
            (
                "SolvedCache",
                f"{self._cache_compatible} compatible / {self._cache_stored} stored",
            ),
            ("CacheReusing", self._cache_reusing),
            ("NextUnsolved", self._cache_next_unsolved),
            ("Leaf", leaf),
            ("LeafStatus", context.get("leaf_status")),
            ("RootStatus", context.get("root_status")),
            ("PrecisionStatus", context.get("precision_status")),
            ("Completed", self._completed_value(context.get("leaf_count"))),
            ("Accepted", len(self._accepted_leaf_ids)),
            ("Rejected", len(self._rejected_leaf_ids)),
            ("Indeterminate", len(self._indeterminate_leaf_ids)),
            ("Failed", len(self._failed_leaf_ids)),
            ("LastAccepted", self._last_accepted_leaf),
            ("Computed", self._current_leaf_persistence()["terminal_computed"]),
            ("PersistentReceipt", self._persistent_receipt_status()),
            ("CachePublishFailures", len(self._cache_publication_failures)),
            ("LeafId", context.get("leaf_id")),
            ("Role", context.get("role")),
            ("Mode", context.get("mode")),
            ("Spin", context.get("spin")),
            ("Mechanism", context.get("mechanism_id")),
            ("Precision", context.get("precision_digits")),
            ("Phase", context.get("phase")),
            ("Newton", context.get("newton_index")),
            ("CurrentOmega", context.get("current_omega")),
            ("DeterminantAbs", context.get("determinant_abs")),
            ("BestDetAbs", context.get("best_determinant_abs")),
            ("Threshold", context.get("acceptance_threshold")),
            ("DetLeaf", context.get("determinant_index_leaf")),
            ("DetPhase", context.get("determinant_index_phase")),
            ("DetNewton", context.get("determinant_index_newton")),
            ("Suboperation", context.get("suboperation")),
            ("Checkpoint", self._checkpoint_status),
            (
                "TimingSample",
                self._timing_sample(record),
            ),
            ("AvgLeaf", self._duration_value(record.get("average_leaf_seconds"))),
            ("MedianLeaf", self._duration_value(record.get("median_leaf_seconds"))),
            ("ETA", self._duration_value(record.get("eta_seconds"))),
            ("Finish", self._finish_value(record.get("estimated_finish"))),
            *self._scientific_dashboard_fields(),
        )

    def _dashboard_lines(self, record: Mapping[str, object]) -> list[str]:
        return [
            f"{label:<15}: {self._dashboard_value(value)}"
            for label, value in self._dashboard_fields(record)
        ]

    def _compact_dashboard_lines(self, record: Mapping[str, object]) -> list[str]:
        fields = dict(self._dashboard_fields(record))

        def line(*labels: str) -> str:
            return " | ".join(
                f"{label}: {self._dashboard_value(fields.get(label))}"
                for label in labels
            )

        lines = [
            "M02 CAMPAIGN | " + line("Sequence", "Event", "Elapsed_s"),
            line("CampaignStatus", "Leaf", "LeafStatus"),
            line("SolvedCache", "CacheReusing", "NextUnsolved"),
            line("LeafId"),
            line("Role", "Mode", "Spin"),
            line("Mechanism", "Precision", "Phase", "Newton"),
            line("RootStatus", "PrecisionStatus", "Checkpoint"),
            line("Completed", "Accepted", "Rejected"),
            line("Indeterminate", "Failed", "LastAccepted"),
            line("Computed", "Checkpoint", "PersistentReceipt"),
            line("CachePublishFailures"),
            line("CurrentOmega"),
            line("DeterminantAbs", "BestDetAbs", "Threshold"),
            line("DetLeaf", "DetPhase", "DetNewton"),
            line("Suboperation"),
            line("TimingSample", "AvgLeaf", "MedianLeaf"),
            line("ETA", "Finish"),
        ]
        if self._campaign_report_model is not None:
            lines.extend(
                [
                    "LATEST SCIENTIFIC RESULT | "
                    + line("LatestResult", "ResultMode"),
                    line("ResultSpin", "ResultMechanism", "Convergence"),
                    line("ResponseRe", "ResponseIm", "ResponseAbs"),
                    line("LocalDisk", "DiskResponse", "DiskState"),
                    line("BaselineOmega"),
                    line("BaselineResidual", "SignedRootAbs"),
                    line("ErrorChannels"),
                    "PROJECTIVE EVIDENCE | "
                    + line("Projective", "ProjectiveRow"),
                    line("ProjectiveState", "ProjectiveOutcome"),
                    line("FSAngle", "FSBounds"),
                    line("SepThreshold", "EquivThreshold"),
                ]
            )
        return lines

    def _completed_value(self, leaf_count: object) -> str:
        completed = len(self._settled_leaf_ids)
        if isinstance(leaf_count, bool) or not isinstance(leaf_count, int):
            return str(completed)
        return f"{completed}/{leaf_count}"

    @classmethod
    def _dashboard_value(cls, value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, Mapping):
            entries = "; ".join(
                f"{key}={cls._dashboard_value(value[key])}" for key in sorted(value)
            )
            return "@{" + entries + "}"
        if isinstance(value, bool):
            return str(value).lower()
        return str(value)

    @staticmethod
    def _timing_sample(record: Mapping[str, object]) -> str | None:
        sample = record.get("leaf_timing_sample_size")
        window = record.get("leaf_timing_window_size")
        if sample is None or window is None:
            return None
        return f"{sample}/{window}"

    @staticmethod
    def _duration_value(value: object) -> str | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        seconds = max(0, round(value))
        days, seconds = divmod(seconds, 86400)
        hours, seconds = divmod(seconds, 3600)
        minutes, seconds = divmod(seconds, 60)
        if days:
            return f"{days}d {hours}h {minutes}m"
        if hours:
            return f"{hours}h {minutes}m {seconds}s"
        if minutes:
            return f"{minutes}m {seconds}s"
        return f"{seconds}s"

    @staticmethod
    def _finish_value(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        try:
            finish = datetime.fromisoformat(value)
        except ValueError:
            return value
        compact = finish.strftime("%Y-%m-%d %H:%M %z")
        return compact[:-2] + ":" + compact[-2:]

    def _ordinary_line(self, record: Mapping[str, object]) -> None:
        self._close_status()
        context = record["context"]
        assert isinstance(context, Mapping)
        payload = record["payload"]
        assert isinstance(payload, Mapping)
        kind = record["kind"]
        leaf = self._live_leaf_label(context)
        if kind == ProgressEventKind.SOLVED_LEAF_CACHE_SCANNED.value:
            compatible = payload.get("compatible_count", 0)
            stored = payload.get("stored_count", 0)
            reusing = payload.get("reusing_count", 0)
            next_unsolved = payload.get("next_unsolved_index")
            leaf_count = payload.get("leaf_count")
            next_text = "none" if next_unsolved is None else f"{next_unsolved}/{leaf_count}"
            self.stream.write(
                f"Solved-leaf cache: {compatible} compatible / {stored} stored | "
                f"Reusing {reusing} leaves | Next unsolved leaf: {next_text}\n"
            )
            self.stream.flush()
            return
        if kind == ProgressEventKind.LEAF_REUSED.value:
            source = payload.get("source", "authenticated prior result")
            self.stream.write(f"leaf_reused | Leaf {leaf} REUSED | {source}\n")
            self.stream.flush()
            return
        if kind in {
            ProgressEventKind.LEAF_CACHE_STALE.value,
            ProgressEventKind.LEAF_CACHE_CORRUPT.value,
        }:
            label = "CACHE STALE" if kind.endswith("stale") else "CACHE CORRUPT"
            message = payload.get("message", "not reused")
            self.stream.write(f"Leaf {leaf} {label} | {message} | solving normally\n")
            self.stream.flush()
            return
        if kind == ProgressEventKind.LEAF_CACHE_PUBLICATION_FAILED.value:
            self.stream.write(
                "leaf_cache_publication_failed"
                f" | Leaf {leaf} PERSISTENT RECEIPT FAILED"
                f" | store={payload.get('store_path')}"
                f" | {payload.get('error_type')}: {payload.get('message')}\n"
            )
            self.stream.flush()
            return
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

    @staticmethod
    def _live_leaf_label(context: Mapping[str, object]) -> str:
        index = context.get("leaf_index")
        count = context.get("leaf_count")
        if index is None or count is None:
            return str(context.get("leaf_id") or "-")
        return f"{index}/{count}"

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

    def _append_root_solve(self, record: Mapping[str, object]) -> None:
        """Persist one compact solve measurement in every progress mode."""

        path = Path(f"{self.checkpoint}.progress") / "root-solves.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_jsonl(path, record)

    def _write_status(self, record: Mapping[str, object]) -> None:
        """Atomically replace the diagnostic snapshot inspected by other processes."""

        path = Path(f"{self.checkpoint}.status.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        status = dict(record)
        status["persistence"] = self._persistence_status()
        status["scientific"] = dict(self._scientific_dashboard_fields())
        encoded = json.dumps(
            _json_value(status), ensure_ascii=False, allow_nan=False,
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
