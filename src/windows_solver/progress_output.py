"""Human and JSONL renderers for typed campaign progress events."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from decimal import Decimal
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

from .campaign_reports import (
    CONDITIONING_REPORT_COLUMNS,
    CampaignReportModel,
    refresh_campaign_reports,
)
from .precision_tiers import precision_tier_presentation
from .progress import (
    PROGRESS_SCHEMA,
    ProgressContext,
    ProgressEvent,
    ProgressEventKind,
    ProgressMode,
)
from .schema11_dashboard import (
    Schema11DashboardRow,
    Schema11DashboardSnapshot,
    Schema11EvidenceRow,
    project_schema11_dashboard,
)

if TYPE_CHECKING:
    from .response_batches import CampaignPlan


_QUIET_KINDS = frozenset(
    {
        ProgressEventKind.CAMPAIGN_COMPLETED,
        ProgressEventKind.CAMPAIGN_FAILED,
        ProgressEventKind.CAMPAIGN_INTERRUPTED,
        ProgressEventKind.LEAF_STARTED,
        ProgressEventKind.LEAF_REUSED,
        ProgressEventKind.LEAF_CACHE_STALE,
        ProgressEventKind.LEAF_CACHE_CORRUPT,
        ProgressEventKind.LEAF_CACHE_PUBLICATION_FAILED,
        ProgressEventKind.LEAF_COMPLETED,
        ProgressEventKind.LEAF_FAILED,
        ProgressEventKind.LEAF_INTERRUPTED,
        ProgressEventKind.ERROR,
    }
)
_AUTHENTICATION_WORKFLOW_KINDS = frozenset(
    {
        ProgressEventKind.PRIMARY_STAGED_AUTHENTICATION_STARTED,
        ProgressEventKind.PRIMARY_STAGED_DERIVATIVE_ACCEPTED,
        ProgressEventKind.PRIMARY_STAGED_DERIVATIVE_REJECTED,
        ProgressEventKind.PRIMARY_STAGED_AUTHENTICATION_COMPLETED,
        ProgressEventKind.PRIMARY_FULL_AUTHENTICATION_ESCALATED,
        ProgressEventKind.PRIMARY_FULL_AUTHENTICATION_COMPLETED,
        ProgressEventKind.DIAGNOSTIC_CONSISTENCY_STARTED,
        ProgressEventKind.DIAGNOSTIC_CONSISTENCY_COMPLETED,
        ProgressEventKind.DIAGNOSTIC_FULL_AUTHENTICATION_ESCALATED,
        ProgressEventKind.DIAGNOSTIC_FULL_AUTHENTICATION_COMPLETED,
    }
)
_NORMAL_KINDS = (
    _QUIET_KINDS
    | _AUTHENTICATION_WORKFLOW_KINDS
    | frozenset(
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
            ProgressEventKind.ROOT_PHASE_AUTHENTICATION_ESCALATED,
            ProgressEventKind.ROOT_PHASE_COMPLETED,
            ProgressEventKind.NEWTON_ITERATION_STARTED,
            ProgressEventKind.NEWTON_ITERATION_COMPLETED,
            ProgressEventKind.REQUEST_STARTED,
            ProgressEventKind.REQUEST_VALIDATED,
            ProgressEventKind.REQUEST_COMPLETED,
            ProgressEventKind.REQUEST_FAILED,
            ProgressEventKind.REQUEST_INTERRUPTED,
            ProgressEventKind.LEAF_CACHE_PUBLISHED,
            ProgressEventKind.ROOT_READOUT_REUSED,
        }
    )
)
_NORMAL_FALLBACK_KINDS = _NORMAL_KINDS | frozenset(
    {
        ProgressEventKind.DETERMINANT_COMPLETED,
        ProgressEventKind.DETERMINANT_EVALUATED,
        ProgressEventKind.SUBOPERATION_COMPLETED,
        ProgressEventKind.SUBOPERATION_PROGRESS,
        ProgressEventKind.ODE_SOLVE_COMPLETED,
        ProgressEventKind.ODE_SOLVE_FAILED,
        ProgressEventKind.ODE_RESOURCE_LIMIT,
        ProgressEventKind.COORDINATE_INVERSION_STALLED,
        ProgressEventKind.ROOT_READOUT_RESOURCE_INFEASIBLE,
    }
)
_TERMINAL_KINDS = frozenset(
    {
        ProgressEventKind.CAMPAIGN_COMPLETED,
        ProgressEventKind.CAMPAIGN_FAILED,
        ProgressEventKind.CAMPAIGN_INTERRUPTED,
        ProgressEventKind.LEAF_COMPLETED,
        ProgressEventKind.LEAF_FAILED,
        ProgressEventKind.LEAF_INTERRUPTED,
        ProgressEventKind.ERROR,
    }
)
_FORCED_STATUS_KINDS = frozenset(
    {
        ProgressEventKind.REQUEST_STARTED,
        ProgressEventKind.REQUEST_COMPLETED,
        ProgressEventKind.REQUEST_FAILED,
        ProgressEventKind.REQUEST_INTERRUPTED,
        ProgressEventKind.CAMPAIGN_STARTED,
        ProgressEventKind.CAMPAIGN_COMPLETED,
        ProgressEventKind.CAMPAIGN_FAILED,
        ProgressEventKind.CAMPAIGN_INTERRUPTED,
        ProgressEventKind.LEAF_STARTED,
        ProgressEventKind.LEAF_REUSED,
        ProgressEventKind.LEAF_CACHE_STALE,
        ProgressEventKind.LEAF_CACHE_CORRUPT,
        ProgressEventKind.LEAF_CACHE_PUBLICATION_FAILED,
        ProgressEventKind.SOLVED_LEAF_CACHE_SCANNED,
        ProgressEventKind.LEAF_COMPLETED,
        ProgressEventKind.LEAF_FAILED,
        ProgressEventKind.LEAF_INTERRUPTED,
        ProgressEventKind.PRECISION_STAGE_STARTED,
        ProgressEventKind.ASYMPTOTIC_SERIES_EVALUATED,
        ProgressEventKind.CONDITIONING_EVALUATED,
        ProgressEventKind.DERIVATIVE_CONTROL_COMPLETED,
        ProgressEventKind.ODE_SOLVE_COMPLETED,
        ProgressEventKind.ODE_SOLVE_FAILED,
        ProgressEventKind.ODE_RESOURCE_LIMIT,
        ProgressEventKind.COORDINATE_INVERSION_STALLED,
        ProgressEventKind.ROOT_READOUT_RESOURCE_INFEASIBLE,
        ProgressEventKind.WORKER_HEARTBEAT,
        ProgressEventKind.ERROR,
    }
) | _AUTHENTICATION_WORKFLOW_KINDS
_STATUS_INTERVAL_SECONDS = 0.25
_DASHBOARD_INTERVAL_SECONDS = 0.25
_DASHBOARD_FORCED_KINDS = frozenset(
    {
        ProgressEventKind.SOLVED_LEAF_CACHE_SCANNED,
        ProgressEventKind.CAMPAIGN_STARTED,
        ProgressEventKind.CAMPAIGN_COMPLETED,
        ProgressEventKind.CAMPAIGN_FAILED,
        ProgressEventKind.CAMPAIGN_INTERRUPTED,
        ProgressEventKind.PRECISION_STAGE_STARTED,
        ProgressEventKind.PRECISION_STAGE_COMPLETED,
        ProgressEventKind.ROOT_PHASE_STARTED,
        ProgressEventKind.ROOT_SEED_SELECTED,
        ProgressEventKind.ROOT_PHASE_AUTHENTICATION_ESCALATED,
        ProgressEventKind.ROOT_PHASE_COMPLETED,
        ProgressEventKind.ASYMPTOTIC_SERIES_EVALUATED,
        ProgressEventKind.CONDITIONING_EVALUATED,
        ProgressEventKind.DERIVATIVE_CONTROL_COMPLETED,
        ProgressEventKind.ODE_SOLVE_FAILED,
        ProgressEventKind.ODE_RESOURCE_LIMIT,
        ProgressEventKind.COORDINATE_INVERSION_STALLED,
        ProgressEventKind.ROOT_READOUT_RESOURCE_INFEASIBLE,
        ProgressEventKind.WORKER_HEARTBEAT,
        ProgressEventKind.LEAF_COMPLETED,
        ProgressEventKind.LEAF_REUSED,
        ProgressEventKind.LEAF_FAILED,
        ProgressEventKind.LEAF_INTERRUPTED,
    }
) | _AUTHENTICATION_WORKFLOW_KINDS
_DASHBOARD_LIVE_KINDS = frozenset(
    {
        ProgressEventKind.NEWTON_ITERATION_STARTED,
        ProgressEventKind.NEWTON_ITERATION_COMPLETED,
        ProgressEventKind.DETERMINANT_STARTED,
        ProgressEventKind.DETERMINANT_COMPLETED,
        ProgressEventKind.SUBOPERATION_STARTED,
        ProgressEventKind.SUBOPERATION_PROGRESS,
        ProgressEventKind.SUBOPERATION_COMPLETED,
        ProgressEventKind.ODE_SOLVE_STARTED,
        ProgressEventKind.ODE_SOLVE_PROGRESS,
        ProgressEventKind.ODE_SOLVE_COMPLETED,
        ProgressEventKind.ASYMPTOTIC_SERIES_EVALUATED,
        ProgressEventKind.CARRIER_CHANGED,
        ProgressEventKind.FACTORED_ODE_COMPLETED,
        ProgressEventKind.SCATTERING_COEFFICIENTS_EXTRACTED,
        ProgressEventKind.DETERMINANT_CHART_EVALUATED,
        ProgressEventKind.CONDITIONING_EVALUATED,
        ProgressEventKind.DETERMINANT_ERROR_ESTIMATED,
        ProgressEventKind.DERIVATIVE_CONTROL_COMPLETED,
    }
)
_LEAF_TIMING_WINDOW = 10
_RADIAL_PROGRESS_STATE_KEYS = (
    "radial_suboperation",
    "radial_rhs_evaluations",
    "radial_rho_span_fraction",
    "radial_elapsed_seconds",
)
_ODE_PROGRESS_STATE_KEYS = (
    "ode_solve_id",
    "ode_leg",
    "ode_stats_scope",
    "ode_t_start",
    "ode_t_end",
    "ode_t_current",
    "ode_retcode",
    "ode_endpoint_reached",
    "ode_rhs_evaluations",
    "ode_accepted_steps",
    "ode_rejected_steps",
    "ode_jacobian_evaluations",
    "ode_linear_solves",
    "ode_nonlinear_iterations",
    "ode_nonlinear_convergence_failures",
    "ode_last_accepted_step_abs",
    "ode_min_accepted_step_abs",
    "ode_proposed_step_abs",
    "ode_algorithm_configured",
    "ode_elapsed_seconds",
    "failure_code",
    "failure_class",
    "limit_kind",
    "limiting_resource",
    "request_elapsed_seconds",
)
_CONDITIONING_LIVE_STATE_KEYS = (
    "homogeneous_representation",
    "determinant_family",
    "determinant_normalisation",
    "scattering_diagnostics_applicable",
    "scattering_column_convention",
    "determinant_convention",
    "current_carrier",
    "maximum_series_digits_lost",
    "maximum_recurrence_digits_lost",
    "maximum_series_evaluation_spread",
    "maximum_basis_condition",
    "maximum_basis_backward_error",
    "maximum_matching_reconstruction_residual",
    "endpoint_remainders_regular",
    "maximum_endpoint_reconstruction_error",
    "maximum_contour_angle_deformation",
    "maximum_fd_digits_lost",
    "predicted_reliable_digits",
    "required_reliable_digits",
    "precision_limited",
    "minimum_cref_chart_margin",
    "maximum_carrier_change_error",
    "normalised_determinant_abs",
    "raw_determinant_abs",
    "raw_determinant_evidence_status",
    "determinant_chart",
    "cref_chart_safe",
    "asymptotic_preflight_adequate",
    "asymptotic_preflight_avoided_ode",
)
_DETERMINANT_ERROR_LIVE_STATE_KEYS = (
    "determinant_error_model",
    "determinant_error_abs",
    "determinant_error_safety_factor",
    "endpoint_disagreement_abs",
    "control_disagreement_abs",
    "equivalence_disagreement_abs",
    "precision_disagreement_abs",
)
_AUTHENTICATION_LIVE_STATE_KEYS = (
    "central_determinant_re",
    "central_determinant_im",
    *_DETERMINANT_ERROR_LIVE_STATE_KEYS,
    "residual_upper_bound_abs",
    "derivative_re",
    "derivative_im",
    "derivative_propagated_error_abs",
    "derivative_step_disagreement_abs",
    "derivative_lower_bound_abs",
    "derivative_selected_step",
    "derivative_axis",
    "correction_upper_bound",
    "root_correction_tolerance",
    "root_authentication_accepted",
)
_PROMOTED_ACCEPTANCE_LIVE_STATE_KEYS = (
    "promoted_root_readout_policy",
    "acceptance_metric",
    "correction_abs",
    "derivative_abs",
    "derivative",
    "post_newton_determinant_count",
    "fixed_root",
    "derivative_source",
    "determinant_error_abs",
    "error_model_id",
)
_PRECISION_LIVE_STATE_KEYS = (
    "phase",
    "seed_kind",
    "seed_authenticated",
    "fallback_used",
    "seed_omega",
    "current_omega",
    "candidate_omega",
    "newton_index",
    "newton_limit",
    "determinant_index_leaf",
    "determinant_index_phase",
    "determinant_index_newton",
    "determinant_abs",
    "best_determinant_abs",
    "acceptance_threshold",
    "suboperation",
    "readout_index",
    "readout_role",
    "epsilon",
    "amplitude",
    *_CONDITIONING_LIVE_STATE_KEYS,
    *_AUTHENTICATION_LIVE_STATE_KEYS,
    *_PROMOTED_ACCEPTANCE_LIVE_STATE_KEYS,
    *_RADIAL_PROGRESS_STATE_KEYS,
    *_ODE_PROGRESS_STATE_KEYS,
)


def _json_value(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
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


class CleanTailDashboard:
    """Append-only completed rows plus one carriage-return live line.

    Rows carry human ordinals, physical coordinates, and evidence, chosen by
    the active survey pass. The SHA-form leaf identity stays in the status
    receipt and logs; the dashboard preserves the numbers an operator needs
    to read without decoding — spins are never truncated, mechanism names
    stay recognizable, and internal mappings never reach the live line.
    """

    _MECHANISM_SHORT = {
        "horizon-admittance": "horizon",
        "exterior-alpha-one": "ext-alpha1",
        "exterior-light-ring": "ext-lightring",
        "exterior-throat-kappa": "ext-throatkappa",
    }

    _BANNER_WIDTH = 108
    _COMPACT_THRESHOLD = 96

    _BINARY64_COLUMNS: tuple[tuple[str, int], ...] = (
        ("LEAF", 8),
        ("MODE", 4),
        ("SPIN", 10),
        ("MECHANISM", 16),
        ("TIME", 8),
        ("|RESPONSE|", 11),
        ("REL.ERROR", 11),
        ("STATE", 10),
    )
    _PROMOTED_COLUMNS: tuple[tuple[str, int], ...] = (
        ("LEAF", 8),
        ("MODE", 4),
        ("SPIN", 10),
        ("MECHANISM", 16),
        ("BF40", 7),
        ("BF80", 7),
        ("TOTAL", 8),
        ("|RESPONSE|", 11),
        ("REL.ERROR", 11),
        ("STATE", 10),
    )
    _BINARY64_COMPACT_COLUMNS: tuple[tuple[str, int], ...] = (
        ("LEAF", 7),
        ("MODE", 4),
        ("SPIN", 10),
        ("MECH", 8),
        ("TIME", 7),
        ("|R|", 9),
        ("ERR", 9),
        ("STATE", 10),
    )
    _PROMOTED_COMPACT_COLUMNS: tuple[tuple[str, int], ...] = (
        ("LEAF", 7),
        ("MODE", 4),
        ("SPIN", 10),
        ("MECH", 8),
        ("BF40", 6),
        ("BF80", 6),
        ("TOT", 7),
        ("|R|", 9),
        ("ERR", 9),
        ("STATE", 10),
    )

    def __init__(
        self,
        stream: TextIO,
        *,
        width: int | None = None,
        ansi: bool = False,
    ) -> None:
        self.stream = stream
        self.width = max(1, width or self._stream_width(stream))
        self.ansi = bool(ansi)
        self._started = False
        self._emitted_leaf_ids: set[str] = set()
        self._live_text = ""
        self._pass_name: str | None = None

    @staticmethod
    def _stream_width(stream: TextIO) -> int:
        try:
            return max(1, os.get_terminal_size(stream.fileno()).columns)
        except (AttributeError, OSError, ValueError):
            return 120

    @property
    def compact(self) -> bool:
        return self.width < self._COMPACT_THRESHOLD

    def _columns(self) -> tuple[tuple[str, int], ...]:
        promoted = self._pass_name == "promoted"
        if self.compact:
            return (
                self._PROMOTED_COMPACT_COLUMNS
                if promoted
                else self._BINARY64_COMPACT_COLUMNS
            )
        return (
            self._PROMOTED_COLUMNS if promoted else self._BINARY64_COLUMNS
        )

    def start(
        self,
        historical_rows: tuple[Mapping[str, object], ...]
        | list[Mapping[str, object]],
        *,
        counts: Mapping[str, object],
        profile: str | None = None,
        pass_name: str | None = None,
        report_status: Mapping[str, object] | None = None,
    ) -> None:
        if self._started:
            return
        self._started = True
        self._pass_name = pass_name
        banner_width = min(self.width, self._BANNER_WIDTH)
        banner = "=" * banner_width
        header_label = "  M02 | DASHBOARD"
        badge_bits = [
            str(part).upper()
            for part in (profile, pass_name)
            if part is not None
        ]
        if badge_bits:
            badge = " / ".join(badge_bits)
            padding = banner_width - len(header_label) - len(badge)
            if padding > 1:
                header_label = header_label + " " * padding + badge
            else:
                header_label = f"{header_label}  {badge}"
        self._line(banner)
        self._line(header_label)
        self._line(banner)
        for line in self._summary_lines(counts):
            self._line(line)
        if report_status:
            status = "   ".join(
                f"{name}={value}" for name, value in report_status.items()
            )
            self._line(f"REPORTS   {status}")
        self._line(self._header())
        for row in historical_rows:
            self.complete(row)

    @classmethod
    def _summary_lines(
        cls, counts: Mapping[str, object]
    ) -> tuple[str, ...]:
        if not counts:
            return ()
        normalized = {str(name).lower(): value for name, value in counts.items()}
        used: set[str] = set()
        top: list[str] = []
        for label, key in (
            ("DONE", "completed"),
            ("QUEUED", "queued"),
            ("DEFERRED", "deferred"),
            ("UNRESOLVED", "unresolved"),
            ("REJECTED", "rejected"),
            ("SYS FAIL", "system_failures"),
        ):
            if key in normalized:
                top.append(f"{label} {normalized[key]}")
                used.add(key)
        evidence: list[str] = []
        for label, key in (
            ("CERTIFIED", "certified"),
            ("SCREENED", "screened"),
            ("VALIDATED", "validated"),
        ):
            if key in normalized:
                evidence.append(f"{label} {normalized[key]}")
                used.add(key)
        leftover: list[str] = []
        for name, value in sorted(counts.items()):
            if str(name).lower() in used:
                continue
            leftover.append(f"{str(name).upper()} {value}")
        lines: list[str] = []
        if top:
            lines.append("   ".join(top))
        if evidence:
            lines.append("EVIDENCE   " + "   ".join(evidence))
        if leftover:
            lines.append("   ".join(leftover))
        return tuple(lines)

    _LIVE_FIELD_ORDER: tuple[tuple[str, str | None], ...] = (
        ("leaf", None),
        ("mode", None),
        ("spin", "a"),
        ("mechanism", None),
        ("tier", None),
        ("role", None),
        ("phase", None),
        ("elapsed", None),
    )

    def live(self, state: Mapping[str, object]) -> None:
        if not self._started:
            self.start((), counts={})
        parts: list[str] = []
        for name, prefix in self._LIVE_FIELD_ORDER:
            value = self._scalar(state.get(name))
            if value is None and name == "tier":
                value = self._scalar(state.get("pass"))
            if value is None:
                continue
            rendered = self._format_live_field(name, value)
            if rendered is None:
                continue
            parts.append(
                rendered if prefix is None else f"{prefix}={rendered}"
            )
        text = "RUNNING  " + " | ".join(parts) if parts else ""
        counts = self._scalar(state.get("counts"))
        if counts:
            suffix = self._plain(counts)
            text = f"{text}   {suffix}" if text else suffix
        self._live_text = self._clip(text)
        self.stream.write("\r" + self._live_text.ljust(self.width))
        self.stream.flush()

    @staticmethod
    def _scalar(value: object) -> object | None:
        if value is None:
            return None
        if isinstance(value, (Mapping, list, tuple, set, frozenset)):
            return None
        if isinstance(value, str) and not value:
            return None
        return value

    @classmethod
    def _format_live_field(cls, name: str, value: object) -> str | None:
        if name == "spin":
            return cls._format_spin(value)
        if name == "mechanism":
            return cls._format_mechanism(value)
        text = cls._plain(value)
        return text if text and text != "-" else None

    def complete(self, row: Mapping[str, object]) -> None:
        leaf_id = row.get("leaf_id")
        if not isinstance(leaf_id, str) or not leaf_id:
            raise ValueError("clean-tail completed row requires leaf_id")
        if leaf_id in self._emitted_leaf_ids:
            return
        if not self._started:
            self.start((), counts={})
        prior_live = self._live_text
        if prior_live:
            self.stream.write("\r" + (" " * self.width) + "\r")
        self.stream.write(self._clip(self._row(row)) + "\n")
        self._emitted_leaf_ids.add(leaf_id)
        if prior_live:
            self.stream.write("\r" + prior_live.ljust(self.width))
        self.stream.flush()

    def finish_live(self) -> None:
        if not self._live_text:
            return
        self.stream.write("\r" + self._live_text.ljust(self.width) + "\n")
        self.stream.flush()
        self._live_text = ""

    def _line(self, value: str) -> None:
        self.stream.write(self._clip(value) + "\n")

    def _clip(self, value: str) -> str:
        if len(value) <= self.width:
            return value
        if self.width == 1:
            return "…"
        return value[: self.width - 1] + "…"

    @staticmethod
    def _plain(value: object) -> str:
        if value is None:
            return "-"
        if isinstance(value, bool):
            return str(value)
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            return format(value, ".4g")
        return str(value).replace("\r", " ").replace("\n", " ")

    @classmethod
    def _cell(cls, value: object, width: int) -> str:
        text = cls._plain(value)
        if len(text) <= width:
            return text.ljust(width)
        # Preserve the datum even when it overflows: extending the row is a
        # better tradeoff than mutilating a physical coordinate or an
        # identifier.  Fixed widths were chosen to fit typical values.
        return text + " "

    def _header(self) -> str:
        return " ".join(
            self._cell(name, width) for name, width in self._columns()
        ).rstrip()

    @classmethod
    def _format_leaf(cls, row: Mapping[str, object]) -> str:
        ordinal = row.get("leaf_ordinal")
        count = row.get("leaf_count")
        if isinstance(ordinal, int):
            if isinstance(count, int) and count > 0:
                return f"{ordinal}/{count}"
            return str(ordinal)
        leaf_id = row.get("leaf_id")
        return str(leaf_id) if leaf_id else "-"

    @classmethod
    def _format_spin(cls, value: object) -> str:
        if value is None or value == "-":
            return "-"
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return str(value)
        if not math.isfinite(number):
            return str(value)
        return format(number, ".8g")

    @classmethod
    def _format_mechanism(cls, value: object) -> str:
        if value is None:
            return "-"
        text = str(value)
        return cls._MECHANISM_SHORT.get(text, text)

    @classmethod
    def _format_time(
        cls, value: object, *, reconstructed: bool = False
    ) -> str:
        if value is None:
            return "-"
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return cls._plain(value)
        prefix = "~" if reconstructed else ""
        if number < 100:
            return f"{prefix}{number:.2f}s"
        if number < 10000:
            return f"{prefix}{number:.1f}s"
        return f"{prefix}{number:.0f}s"

    @classmethod
    def _format_response(cls, value: object) -> str:
        if value is None or value == "-":
            return "-"
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return cls._plain(value)
        if not math.isfinite(number):
            return cls._plain(value)
        return format(number, ".4g")

    @classmethod
    def _format_relative_error(cls, value: object) -> str:
        if value is None or value == "-":
            return "-"
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return cls._plain(value)
        if not math.isfinite(number):
            return cls._plain(value)
        return format(number, ".3e")

    def _cell_value(
        self, name: str, row: Mapping[str, object]
    ) -> str:
        reconstructed = bool(row.get("reconstructed_timing"))
        if name == "LEAF":
            return self._format_leaf(row)
        if name == "MODE":
            return self._plain(row.get("mode", "-"))
        if name == "SPIN":
            return self._format_spin(
                row.get("spin_or_Mkappa", row.get("spin", "-"))
            )
        if name in ("MECHANISM", "MECH"):
            return self._format_mechanism(
                row.get("mechanism", row.get("mechanism_id", "-"))
            )
        if name == "TIME":
            return self._format_time(
                row.get("binary64_seconds", row.get("total_leaf_seconds")),
                reconstructed=reconstructed,
            )
        if name == "BF40":
            return self._format_time(
                row.get("bf40_seconds"), reconstructed=reconstructed
            )
        if name == "BF80":
            return self._format_time(
                row.get("bf80_seconds"), reconstructed=reconstructed
            )
        if name == "BF120":
            return self._format_time(
                row.get("bf120_seconds"), reconstructed=reconstructed
            )
        if name in ("TOTAL", "TOT"):
            return self._format_time(
                row.get("total_leaf_seconds"), reconstructed=reconstructed
            )
        if name in ("|RESPONSE|", "|R|"):
            return self._format_response(row.get("response_magnitude", "-"))
        if name in ("REL.ERROR", "ERR"):
            return self._format_relative_error(
                row.get("relative_disk_radius", row.get("relative_error", "-"))
            )
        if name == "STATE":
            state = row.get("evidence_level", row.get("terminal_state", "-"))
            if state in (None, "", "-"):
                state = row.get("terminal_state", "-")
            return self._plain(state)
        return "-"

    def _row(self, row: Mapping[str, object]) -> str:
        return " ".join(
            self._cell(self._cell_value(name, row), width)
            for name, width in self._columns()
        ).rstrip()


class AppendOnlySchema11Dashboard:
    """Render the approved schema-11 dashboard using newline writes only."""

    WIDTH = 118
    INITIAL_ROWS = 14
    _MECHANISM_SHORT = {
        "horizon-admittance": "horizon",
        "exterior-fixed-r3": "ext-r3",
        "exterior-alpha-zero": "ext-alpha0",
        "exterior-alpha-half": "ext-alpha1/2",
        "exterior-alpha-one": "ext-alpha1",
        "exterior-light-ring": "ext-lightring",
        "exterior-throat-kappa": "ext-throatk",
    }

    def __init__(self, stream: TextIO) -> None:
        self.stream = stream
        self._started = False
        self._terminal_summary_emitted = False
        self._emitted_leaf_ids: set[str] = set()
        self._active_pass = "binary64"

    @property
    def started(self) -> bool:
        return self._started

    def start(
        self,
        snapshot: Schema11DashboardSnapshot,
        rows: tuple[Schema11DashboardRow, ...],
        *,
        profile: str,
        active_pass: str,
        running: Mapping[str, object] | None,
        terminal: bool = False,
    ) -> tuple[str, ...]:
        if self._started:
            return tuple(self._emitted_leaf_ids)
        self._started = True
        self._active_pass = active_pass
        rule = "=" * self.WIDTH
        dash = "-" * self.WIDTH
        self._line(rule)
        self._line("  M02 | OPERATOR DASHBOARD")
        self._line(rule)
        self._line(
            "  PROFILE  {profile:<8}  PASS  {active:<10}    CHECKPOINT  "
            "schema-11    LAYER-1 LOCK  NOT YET CREATED".format(
                profile=str(profile).upper(), active=str(active_pass).upper()
            )
        )
        self._line(dash)
        self._line(
            "  BINARY64 PROCESSED   {processed:3}/{selected:<3}     PRODUCED   "
            "{produced:3}     PENDING   {pending:3}     SYS FAIL   {failures:3}".format(
                processed=snapshot.binary64_processed_count,
                selected=snapshot.selected_leaf_count,
                produced=snapshot.produced_count,
                pending=snapshot.pending_count,
                failures=snapshot.system_failure_count,
            )
        )
        self._line(
            "  PROMOTION ROUTES        BF40 {bf40:3}     BF80 {bf80:3}     "
            "RETAINED BINARY64 SAMPLES {samples:4}".format(
                bf40=snapshot.pending_by_minimum_tier.get("BF40", 0),
                bf80=snapshot.pending_by_minimum_tier.get("BF80", 0),
                samples=snapshot.retained_binary64_sample_count,
            )
        )
        self._line(
            "  PROMOTED PROCESSED    {processed:3}         DEFERRED {deferred:3}     "
            "UNRESOLVED {unresolved:3}     REJECTED {rejected:3}".format(
                processed=snapshot.promoted_processed_count,
                deferred=snapshot.deferred_count,
                unresolved=snapshot.unresolved_count,
                rejected=snapshot.rejected_count,
            )
        )
        self._line(
            "  EVIDENCE             SCREENED {screened:3}     CERTIFIED {certified:3}     "
            "VALIDATED {validated:3}".format(
                screened=snapshot.evidence_counts.get("SCREENED", 0),
                certified=snapshot.evidence_counts.get("CERTIFIED", 0),
                validated=snapshot.evidence_counts.get("VALIDATED", 0),
            )
        )
        self._line(dash)
        if terminal:
            self._line("  PASS COMPLETE — no active leaf")
        elif running:
            self._line("  " + self._running_text(running))
        else:
            self._line("  WAITING FOR ACTIVE LEAF...")
        self._line(dash)
        self._line("  LAST SETTLED LEAVES")
        self._line("")
        self._line(
            "  {0:<9} {1:<5} {2:<10} {3:<16} {4:<8} {5:>8} {6:>7} {7:<6} {8}".format(
                "LEAF", "MODE", "SPIN", "MECHANISM", "ROLE", "TIME", "SAMPLES", "NEXT", "STATE"
            )
        )
        self._line(
            "  {0:<9} {1:<5} {2:<10} {3:<16} {4:<8} {5:>8} {6:>7} {7:<6} {8}".format(
                "-" * 9,
                "-" * 5,
                "-" * 10,
                "-" * 16,
                "-" * 8,
                "-" * 8,
                "-" * 7,
                "-" * 6,
                "-" * 18,
            )
        )
        for row in rows[-self.INITIAL_ROWS :]:
            self.append_row(row)
        return tuple(self._emitted_leaf_ids)

    def append_row(self, row: Schema11DashboardRow) -> None:
        if row.leaf_id in self._emitted_leaf_ids:
            return
        self._line(self._row_text(row))
        self._emitted_leaf_ids.add(row.leaf_id)

    def append_terminal_summary(
        self,
        snapshot: Schema11DashboardSnapshot,
        event: ProgressEvent,
    ) -> None:
        if self._terminal_summary_emitted:
            return
        self._terminal_summary_emitted = True
        dash = "-" * self.WIDTH
        self._line("")
        self._line(dash)
        completed = event.kind in {
            ProgressEventKind.CAMPAIGN_PASS_COMPLETED,
            ProgressEventKind.CAMPAIGN_COMPLETED,
        }
        if completed:
            title = (
                "BINARY64 SURVEY COMPLETE"
                if self._active_pass == "binary64"
                else "PROMOTED PASS COMPLETE"
            )
        else:
            title = "M02 PASS INTERRUPTED"
        self._line("  " + title)
        self._line("")
        self._line(
            "  PROCESSED                  {0:>3}/{1}".format(
                snapshot.binary64_processed_count
                if self._active_pass == "binary64"
                else snapshot.promoted_processed_count,
                snapshot.selected_leaf_count,
            )
        )
        self._line("  PENDING PROMOTIONS         {0:>3}".format(snapshot.pending_count))
        self._line(
            "    EXTERIOR -> BF40         {0:>3}".format(
                snapshot.pending_by_minimum_tier.get("BF40", 0)
            )
        )
        self._line(
            "    HORIZON  -> BF80         {0:>3}".format(
                snapshot.pending_by_minimum_tier.get("BF80", 0)
            )
        )
        self._line(
            "  RETAINED BINARY64 SAMPLES {0:>4}".format(
                snapshot.retained_binary64_sample_count
            )
        )
        self._line("  SYSTEM FAILURES            {0:>3}".format(snapshot.system_failure_count))
        self._line("")
        if completed:
            self._line("  NEXT PASS: SURVEY / PROMOTED")
        else:
            reason = self._terminal_reason(event)
            self._line("  TERMINAL FAILURE: " + reason)
        self._line(dash)
        self._line("  Ctrl+C stops this preview. The solver in the other window is untouched.")
        self._line("=" * self.WIDTH)

    def _row_text(self, row: Schema11DashboardRow | Schema11EvidenceRow) -> str:
        leaf = (
            f"{row.leaf_ordinal}/{row.leaf_count}"
            if row.leaf_ordinal is not None
            else f"?/{row.leaf_count}"
        )
        if isinstance(row, Schema11EvidenceRow):
            return (
                "  {0:<9} {1:<5} {2:<10} {3:<16} {4:<8} {5:>8} {6:>7} {7:<6} {8}"
            ).format(
                leaf,
                self._safe(row.mode),
                self._spin(row.spin),
                self._mechanism(row.mechanism),
                self._safe(row.role),
                "-",
                "-",
                "-",
                row.state,
            )
        return (
            "  {0:<9} {1:<5} {2:<10} {3:<16} {4:<8} {5:>8} {6:>7} {7:<6} {8}"
        ).format(
            leaf,
            self._safe(row.mode),
            self._spin(row.spin),
            self._mechanism(row.mechanism),
            self._safe(row.role),
            self._time(row.time_seconds),
            row.sample_count,
            row.next_tier or "-",
            row.state,
        )

    @classmethod
    def _running_text(cls, running: Mapping[str, object]) -> str:
        parts = ["RUNNING"]
        for name in ("leaf", "mode", "spin", "mechanism", "tier", "role", "phase", "elapsed"):
            value = running.get(name)
            if value is None or isinstance(value, Mapping) or value == "":
                continue
            if name == "spin":
                value = cls._spin(value)
            elif name == "mechanism":
                value = cls._mechanism(value)
            parts.append(str(value))
        return "  |  ".join(parts)

    @classmethod
    def _safe(cls, value: object) -> str:
        return str(value if value not in (None, "") else "-").replace("\r", " ").replace("\n", " ")

    @classmethod
    def _spin(cls, value: object) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return cls._safe(value)
        return format(number, ".8g") if math.isfinite(number) else cls._safe(value)

    @classmethod
    def _mechanism(cls, value: object) -> str:
        text = cls._safe(value)
        return cls._MECHANISM_SHORT.get(text, text)

    @classmethod
    def _time(cls, value: object) -> str:
        if value is None:
            return "-"
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return cls._safe(value)
        if number < 100:
            return f"{number:.2f}s"
        if number < 10000:
            return f"{number:.1f}s"
        return f"{number:.0f}s"

    @classmethod
    def _terminal_reason(cls, event: ProgressEvent) -> str:
        payload = event.payload
        for name in ("reason", "failure_code", "message", "error_type"):
            value = payload.get(name)
            if value:
                return cls._safe(value)
        return event.kind.value

    def _line(self, value: str) -> None:
        self.stream.write(self._safe(value) + "\n")
        self.stream.flush()


def schema11_dashboard_snapshot(
    checkpoint: Mapping[str, object],
    *,
    leaf_metadata: Mapping[str, Mapping[str, object]] | None = None,
) -> tuple[tuple[dict[str, object], ...], dict[str, int], dict[str, object]]:
    """Compatibility adapter backed entirely by the canonical projection."""

    from .campaign_policy import validate_schema11_checkpoint

    value = validate_schema11_checkpoint(checkpoint)
    metadata = leaf_metadata or {}
    selected: list[str] = []
    for leaf_id in sorted(
        metadata,
        key=lambda item: (
            metadata[item].get("leaf_ordinal", 2**31)
            if isinstance(metadata[item], Mapping)
            else 2**31,
            item,
        ),
    ):
        selected.append(leaf_id)
    ledgers = value["survey_pass_ledger"]
    if isinstance(ledgers, Mapping):
        for pass_name in ("binary64", "promoted"):
            ledger = ledgers.get(pass_name)
            if isinstance(ledger, Mapping):
                for leaf_id in ledger:
                    if isinstance(leaf_id, str) and leaf_id not in selected:
                        selected.append(leaf_id)
    for record in value["records"]:
        if isinstance(record, Mapping):
            leaf_id = record.get("leaf_id")
            if isinstance(leaf_id, str) and leaf_id not in selected:
                selected.append(leaf_id)
    snapshot = project_schema11_dashboard(
        checkpoint,
        selected_leaf_ids=selected,
        leaf_metadata=metadata,
    )
    rows = tuple(
        {
            "leaf_id": row.leaf_id,
            "leaf_ordinal": row.leaf_ordinal,
            "leaf_count": row.leaf_count,
            "survey_pass": row.survey_pass,
            "mode": row.mode,
            "spin_or_Mkappa": row.spin,
            "mechanism": row.mechanism,
            "role": row.role,
            "evidence_level": row.evidence_level,
            "sample_count": row.sample_count,
            "binary64_seconds": row.binary64_seconds,
            "bf40_seconds": row.bf40_seconds,
            "bf80_seconds": row.bf80_seconds,
            "bf120_seconds": row.bf120_seconds,
            "total_leaf_seconds": row.total_leaf_seconds,
            "response_magnitude": row.response_magnitude,
            "relative_disk_radius": row.relative_error,
            "terminal_state": row.state,
        }
        for row in (*snapshot.binary64_rows, *snapshot.promoted_rows)
    )
    counts = {
        "completed": snapshot.binary64_processed_count
        + snapshot.promoted_processed_count,
        "queued": snapshot.pending_count,
        "deferred": snapshot.deferred_count,
        "unresolved": snapshot.unresolved_count,
        "rejected": snapshot.rejected_count,
        "system_failures": snapshot.system_failure_count,
        "SCREENED": snapshot.evidence_counts["SCREENED"],
        "CERTIFIED": snapshot.evidence_counts["CERTIFIED"],
        "VALIDATED": snapshot.evidence_counts["VALIDATED"],
    }
    return rows, counts, dict(snapshot.report_status)


def _finite_seconds(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return number if math.isfinite(number) and number >= 0.0 else 0.0


def _optional_seconds(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number >= 0.0 else None


def _latest_precision_tier(record: Mapping[str, object]) -> object:
    stages = record.get("stages")
    if not isinstance(stages, list) or not stages:
        return "-"
    stage = stages[-1]
    if not isinstance(stage, Mapping):
        return "-"
    return stage.get("precision_tier", stage.get("digits", "-"))


def _record_component_result(record: Mapping[str, object]) -> Mapping[str, object]:
    stages = record.get("stages")
    if not isinstance(stages, list):
        return {}
    for stage in reversed(stages):
        if not isinstance(stage, Mapping):
            continue
        candidates = (stage, stage.get("outcome"))
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue
            component = candidate.get("component_result")
            if isinstance(component, Mapping):
                return component
    return {}


def _record_response_magnitude(record: Mapping[str, object]) -> object:
    retained = record.get("retained_centre")
    if isinstance(retained, Mapping):
        try:
            return abs(complex(
                float(retained["real"]),
                float(retained.get("imaginary", retained.get("imag"))),
            ))
        except (KeyError, TypeError, ValueError, OverflowError):
            pass
    stages = record.get("stages")
    if isinstance(stages, list) and stages and isinstance(stages[-1], Mapping):
        disk = stages[-1].get("response_disk")
        if isinstance(disk, Mapping) and isinstance(disk.get("centre"), Mapping):
            centre = disk["centre"]
            try:
                return abs(complex(
                    float(centre["real"]),
                    float(centre.get("imaginary", centre.get("imag"))),
                ))
            except (KeyError, TypeError, ValueError, OverflowError):
                pass
    component = _record_component_result(record)
    direct = component.get("response_magnitude")
    if direct is not None:
        return direct
    response = component.get("response")
    if isinstance(response, Mapping):
        try:
            return abs(complex(float(response["real"]), float(response["imaginary"])))
        except (KeyError, TypeError, ValueError, OverflowError):
            return "-"
    nested = component.get("result")
    if isinstance(nested, Mapping):
        response = nested.get("response")
        if isinstance(response, Mapping):
            try:
                return abs(complex(
                    float(response["real"]),
                    float(response.get("imaginary", response.get("imag"))),
                ))
            except (KeyError, TypeError, ValueError, OverflowError):
                return "-"
    return "-"


def _record_relative_error(record: Mapping[str, object]) -> object:
    stages = record.get("stages")
    if isinstance(stages, list) and stages and isinstance(stages[-1], Mapping):
        disk = stages[-1].get("response_disk")
        if isinstance(disk, Mapping):
            centre = disk.get("centre", record.get("retained_centre"))
            if isinstance(centre, Mapping):
                try:
                    magnitude = abs(complex(
                        float(centre["real"]),
                        float(centre.get("imaginary", centre.get("imag"))),
                    ))
                    radius = float(disk["radius"])
                    if magnitude > 0 and math.isfinite(radius) and radius >= 0:
                        return radius / magnitude
                except (KeyError, TypeError, ValueError, OverflowError):
                    pass
    component = _record_component_result(record)
    for name in ("relative_disk_radius", "relative_error"):
        if component.get(name) is not None:
            return component[name]
    nested = component.get("result")
    if isinstance(nested, Mapping):
        for name in ("relative_disk_radius", "relative_error"):
            if nested.get(name) is not None:
                return nested[name]
    return "-"


class Schema11ProgressReporter:
    """Synchronise one append-only schema-11 view from committed checkpoints."""

    def __init__(
        self,
        checkpoint: Path | str,
        *,
        leaf_metadata: Mapping[str, Mapping[str, object]] | None = None,
        profile: str = "survey",
        pass_name: str | None = None,
        stream: TextIO | None = None,
        width: int | None = None,
        mode: ProgressMode | str = ProgressMode.NORMAL,
        diagnostic_paths: Mapping[str, str | os.PathLike[str] | Path | None] | None = None,
    ) -> None:
        self.checkpoint = Path(checkpoint)
        self.leaf_metadata = dict(leaf_metadata or {})
        self.profile = profile
        self.pass_name = pass_name
        self.mode = ProgressMode(mode)
        self._started_monotonic = time.monotonic()
        self.stream = stream or sys.stdout
        self.dashboard = (
            None
            if self.mode is ProgressMode.QUIET
            else AppendOnlySchema11Dashboard(self.stream)
        )
        self.diagnostics: list[str] = []
        self._live: dict[str, object] = {
            "profile": profile,
            "pass": pass_name,
        }
        paths = dict(diagnostic_paths or {})
        expected_diagnostic_paths = {
            "diagnostic_session_directory",
            "postmortem_path",
            "bundle_path",
        }
        if set(paths) - expected_diagnostic_paths:
            raise ValueError("schema-11 diagnostic status paths are invalid")
        # Diagnostic paths are a status-serialisation field: preserve the
        # caller-supplied representation verbatim so the status receipt
        # round-trips identically on Windows and POSIX. Feeding an
        # already-canonical string through pathlib.Path merely rewrites
        # its separators to the current OS's native form, which corrupts
        # the receipt for downstream readers.
        self._diagnostic_paths = {
            name: (
                None
                if paths.get(name) is None
                else (
                    paths[name]
                    if isinstance(paths[name], str)
                    else os.fspath(paths[name])
                )
            )
            for name in expected_diagnostic_paths
        }
        self._current_live_event: dict[str, object] | None = None
        self._last_nonterminal_event: dict[str, object] | None = None
        self._terminal_event: dict[str, object] | None = None
        self._terminal_event_object: ProgressEvent | None = None
        self._active_leaf_at_terminal_event: dict[str, object] | None = None
        self._last_committed_leaf: dict[str, object] | None = None
        self._next_intended_leaf: dict[str, object] | None = None
        self._terminal_failure: dict[str, object] | None = None
        self._opened = False
        self._closed = False
        self._dashboard_degraded = False
        self._terminal_summary_emitted = False
        self._emitted_leaf_ids: set[str] = set()
        self._snapshot: Schema11DashboardSnapshot | None = None
        ordered_metadata = sorted(
            (
                (value.get("leaf_ordinal"), leaf_id)
                for leaf_id, value in self.leaf_metadata.items()
                if isinstance(value.get("leaf_ordinal"), int)
            ),
            key=lambda item: item[0],
        )
        self._next_leaf_by_id = {
            leaf_id: ordered_metadata[index + 1][1]
            for index, (_ordinal, leaf_id) in enumerate(ordered_metadata[:-1])
        }
        self._counts: dict[str, int] = {}
        self._write_status(None)

    def _load(self) -> Mapping[str, object] | None:
        if not self.checkpoint.is_file():
            return None
        try:
            value = json.loads(self.checkpoint.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
            # An atomic checkpoint replacement can be observed between the
            # existence check and the read.  The next safe event retries it.
            return None
        if not isinstance(value, Mapping):
            raise ValueError("schema-11 progress checkpoint is not an object")
        return value

    def _selected_leaf_ids(self, value: Mapping[str, object]) -> tuple[str, ...]:
        selected: list[str] = []
        ordered_metadata = sorted(
            self.leaf_metadata.items(),
            key=lambda item: (
                item[1].get("leaf_ordinal", 2**31)
                if isinstance(item[1], Mapping)
                else 2**31,
                item[0],
            ),
        )
        for leaf_id, _metadata in ordered_metadata:
            if leaf_id not in selected:
                selected.append(leaf_id)
        ledgers = value.get("survey_pass_ledger")
        if isinstance(ledgers, Mapping):
            for pass_name in ("binary64", "promoted"):
                ledger = ledgers.get(pass_name)
                if isinstance(ledger, Mapping):
                    for leaf_id in ledger:
                        if isinstance(leaf_id, str) and leaf_id not in selected:
                            selected.append(leaf_id)
        records = value.get("records")
        if isinstance(records, list):
            for record in records:
                if isinstance(record, Mapping):
                    leaf_id = record.get("leaf_id")
                    if isinstance(leaf_id, str) and leaf_id not in selected:
                        selected.append(leaf_id)
        return tuple(selected)

    def _project(self, value: Mapping[str, object]) -> Schema11DashboardSnapshot:
        return project_schema11_dashboard(
            value,
            selected_leaf_ids=self._selected_leaf_ids(value),
            leaf_metadata=self.leaf_metadata,
        )

    def _snapshot_from_checkpoint(self) -> Schema11DashboardSnapshot | None:
        value = self._load()
        if value is None:
            return None
        return self._project(value)

    def rows_for_current_view(
        self, snapshot: Schema11DashboardSnapshot
    ) -> tuple[Schema11DashboardRow | Schema11EvidenceRow, ...]:
        if self.profile in {"certify", "validate"}:
            return snapshot.evidence_rows
        if str(self.pass_name).lower() == "promoted":
            return snapshot.promoted_rows
        return snapshot.binary64_rows

    def _active_pass_label(self, snapshot: Schema11DashboardSnapshot) -> str:
        if self.profile in {"certify", "validate"}:
            return self.profile
        if str(self.pass_name).lower() == "promoted":
            return "promoted"
        return "binary64"

    def sync_from_checkpoint(self) -> Schema11DashboardSnapshot:
        """Project once, append only unseen durable rows, then write status."""

        snapshot = self._snapshot_from_checkpoint()
        if snapshot is None:
            if self._snapshot is not None:
                return self._snapshot
            from .campaign_policy import empty_schema11_checkpoint

            snapshot = project_schema11_dashboard(
                empty_schema11_checkpoint("unavailable", "unavailable"),
                selected_leaf_ids=(),
                leaf_metadata={},
            )
        rows = self.rows_for_current_view(snapshot)
        if self._opened and self.dashboard is not None and not self._dashboard_degraded:
            new_rows = sorted(
                (row for row in rows if row.leaf_id not in self._emitted_leaf_ids),
                key=lambda row: (
                    row.leaf_ordinal if row.leaf_ordinal is not None else 2**31,
                    row.leaf_id,
                ),
            )
            for row in new_rows:
                self._render(lambda row=row: self.dashboard.append_row(row))
                if not self._dashboard_degraded:
                    self._emitted_leaf_ids.add(row.leaf_id)
        self._snapshot = snapshot
        self._counts = dict(snapshot.counts)
        self._write_status_from(snapshot, None)
        return snapshot

    def _start_from_checkpoint(self) -> None:
        # Kept as a compatibility hook for callers that used the old private
        # method.  Schema-11 opens only in response to an approved event.
        return None

    def publish(self, event: ProgressEvent) -> None:
        try:
            event_snapshot = self._event_snapshot(event)
            terminal = self._is_terminal_event(event.kind)
            if terminal:
                self._terminal_event = event_snapshot
                self._terminal_event_object = event
                self._active_leaf_at_terminal_event = self._current_live_event
                self._current_live_event = None
                self._terminal_failure = self._terminal_failure_snapshot(event)
            else:
                self._current_live_event = event_snapshot
                self._last_nonterminal_event = event_snapshot
                if event.kind is ProgressEventKind.LEAF_PASS_DISPOSITION_RECORDED:
                    self._last_committed_leaf = event_snapshot
                    leaf_id = event.context.leaf_id
                    if isinstance(leaf_id, str):
                        next_leaf_id = self._next_leaf_by_id.get(leaf_id)
                        if next_leaf_id is not None:
                            self._next_intended_leaf = {
                                "leaf_id": next_leaf_id,
                                **dict(self.leaf_metadata[next_leaf_id]),
                            }
            if not terminal:
                self._update_live(event)

            if not self._opened and event.kind in self._opening_kinds():
                self._open(event, terminal=terminal)

            if event.kind in self._sync_kinds() or terminal:
                snapshot = self.sync_from_checkpoint()
            else:
                snapshot = self._snapshot

            if terminal and self._opened and snapshot is not None:
                if self.dashboard is not None and not self._dashboard_degraded:
                    self._render(
                        lambda: self.dashboard.append_terminal_summary(
                            snapshot, event
                        )
                    )
                if not self._dashboard_degraded:
                    self._terminal_summary_emitted = True
            elif snapshot is not None:
                self._write_status_from(snapshot, event)
        except Exception as error:
            self._degrade(error)
            self._safe_write_status()

    def close(self) -> None:
        try:
            snapshot = self.sync_from_checkpoint()
            if (
                self._terminal_event is not None
                and not self._terminal_summary_emitted
                and self._opened
                and self.dashboard is not None
                and not self._dashboard_degraded
            ):
                event = self._terminal_event_object
                if event is None:
                    raise ValueError("terminal event object is unavailable")
                self._render(
                    lambda: self.dashboard.append_terminal_summary(snapshot, event)
                )
                if not self._dashboard_degraded:
                    self._terminal_summary_emitted = True
            self._closed = True
        except Exception as error:
            self._degrade(error)
            self._safe_write_status()

    @staticmethod
    def _opening_kinds() -> frozenset[ProgressEventKind]:
        return frozenset(
            {
                ProgressEventKind.LEAF_PASS_STARTED,
                ProgressEventKind.CAMPAIGN_PASS_COMPLETED,
                ProgressEventKind.CAMPAIGN_PASS_INTERRUPTED,
                ProgressEventKind.CAMPAIGN_COMPLETED,
                ProgressEventKind.CAMPAIGN_FAILED,
                ProgressEventKind.CAMPAIGN_INTERRUPTED,
                ProgressEventKind.SYSTEM_FAILURE_RECORDED,
            }
        )

    @staticmethod
    def _sync_kinds() -> frozenset[ProgressEventKind]:
        return frozenset(
            {
                ProgressEventKind.CHECKPOINT_WRITTEN,
                ProgressEventKind.LEAF_PASS_DISPOSITION_RECORDED,
                ProgressEventKind.PROMOTION_QUEUED,
                ProgressEventKind.REPORT_STATUS_CHANGED,
                ProgressEventKind.SYSTEM_FAILURE_RECORDED,
            }
        )

    def _open(self, event: ProgressEvent, *, terminal: bool) -> None:
        snapshot = self._snapshot_from_checkpoint()
        if snapshot is None:
            return
        self._snapshot = snapshot
        self._counts = dict(snapshot.counts)
        rows = self.rows_for_current_view(snapshot)
        self._opened = True
        if self.dashboard is not None and not self._dashboard_degraded:
            self._render(
                lambda: self.dashboard.start(
                    snapshot,
                    rows,
                    profile=self.profile,
                    active_pass=self._active_pass_label(snapshot),
                    running=None if terminal else self._live,
                    terminal=terminal,
                )
            )
        # The initial display is intentionally only the latest fourteen rows,
        # but every already-settled ID is known so omitted history never
        # reappears after the first checkpoint refresh.
        self._emitted_leaf_ids.update(row.leaf_id for row in rows)
        self._write_status_from(snapshot, event)

    def _update_live(self, event: ProgressEvent) -> None:
        context = event.context.to_mapping()
        leaf_id = context.get("leaf_id")
        metadata = (
            self.leaf_metadata.get(leaf_id, {})
            if isinstance(leaf_id, str)
            else {}
        )

        def scalar(value: object) -> object | None:
            if value is None or isinstance(value, Mapping):
                return None
            if isinstance(value, str) and not value:
                return None
            return value

        leaf_index = context.get("leaf_index", metadata.get("leaf_ordinal"))
        leaf_count = context.get("leaf_count", metadata.get("leaf_count"))
        self._live.update(
            {
                "leaf": (
                    None
                    if leaf_index is None
                    else f"{leaf_index}/{leaf_count or '?'}"
                ),
                "mode": scalar(context.get("mode")) or scalar(metadata.get("mode")),
                "spin": (
                    scalar(context.get("spin"))
                    or scalar(metadata.get("spin_or_Mkappa"))
                    or scalar(metadata.get("spin"))
                ),
                "mechanism": scalar(context.get("mechanism_id")) or scalar(
                    metadata.get("mechanism")
                ),
                "tier": scalar(context.get("precision_tier")),
                "role": scalar(context.get("role")) or scalar(metadata.get("role")),
                "phase": scalar(context.get("phase", event.kind.value)),
                "elapsed": f"{max(0.0, event.monotonic_seconds - self._started_monotonic):.1f}s",
            }
        )

    def _render(self, action) -> None:
        if self.dashboard is None or self._dashboard_degraded:
            return
        try:
            action()
        except Exception as error:
            self._degrade(error)

    def _degrade(self, error: Exception) -> None:
        diagnostic = f"{type(error).__name__}: {error}"
        self.diagnostics.append(diagnostic)
        if self._dashboard_degraded:
            return
        self._dashboard_degraded = True
        try:
            self.stream.write("DASHBOARD DEGRADED\n")
            self.stream.flush()
        except Exception:
            pass

    def _safe_write_status(self) -> None:
        try:
            snapshot = self._snapshot or self._snapshot_from_checkpoint()
            if snapshot is not None:
                self._write_status_from(snapshot, None)
        except Exception as error:
            self.diagnostics.append(f"status {type(error).__name__}: {error}")

    @staticmethod
    def _is_terminal_event(kind: ProgressEventKind) -> bool:
        return kind in {
            ProgressEventKind.CAMPAIGN_COMPLETED,
            ProgressEventKind.CAMPAIGN_FAILED,
            ProgressEventKind.CAMPAIGN_INTERRUPTED,
            ProgressEventKind.CAMPAIGN_PASS_COMPLETED,
            ProgressEventKind.CAMPAIGN_PASS_INTERRUPTED,
            ProgressEventKind.SYSTEM_FAILURE_RECORDED,
        }

    @staticmethod
    def _event_snapshot(event: ProgressEvent) -> dict[str, object]:
        return {
            "kind": event.kind.value,
            "context": event.context.to_mapping(),
            "payload": dict(event.payload),
            "monotonic_seconds": event.monotonic_seconds,
        }

    def _terminal_failure_snapshot(
        self, event: ProgressEvent
    ) -> dict[str, object] | None:
        payload = dict(event.payload)
        meaningful = {
            name: payload[name]
            for name in (
                "reason",
                "failure_code",
                "error_type",
                "message",
                "system_failure_fingerprint",
            )
            if name in payload
        }
        if not meaningful and event.kind not in {
            ProgressEventKind.CAMPAIGN_FAILED,
            ProgressEventKind.SYSTEM_FAILURE_RECORDED,
        }:
            return None
        return {"event_kind": event.kind.value, **meaningful}

    def _write_status(self, event: ProgressEvent | None) -> None:
        snapshot = self._snapshot or self._snapshot_from_checkpoint()
        if snapshot is None:
            return
        self._write_status_from(snapshot, event)

    def _write_status_from(
        self,
        snapshot: Schema11DashboardSnapshot,
        event: ProgressEvent | None,
    ) -> None:
        path = Path(f"{self.checkpoint}.status.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        current_rows = self.rows_for_current_view(snapshot)
        numerical_records: list[str] = []
        value = self._load()
        if value is not None and isinstance(value.get("records"), list):
            numerical_records = [
                str(record["leaf_id"])
                for record in value["records"]
                if isinstance(record, Mapping)
                and record.get("state") == "PRODUCED"
                and isinstance(record.get("leaf_id"), str)
            ]
        active_leaf = None
        if self._current_live_event is not None:
            active_leaf = dict(self._current_live_event.get("context", {}))
            active_leaf["event_kind"] = self._current_live_event.get("kind")
        status = {
            "schema": "windows-solver.schema11-progress-status/2",
            "checkpoint_path": str(self.checkpoint),
            "profile": self.profile,
            "survey_pass": self.pass_name,
            "selected_leaf_count": snapshot.selected_leaf_count,
            "binary64_processed_count": snapshot.binary64_processed_count,
            "promoted_processed_count": snapshot.promoted_processed_count,
            "produced_count": snapshot.produced_count,
            "pending_count": snapshot.pending_count,
            "pending_by_minimum_tier": dict(snapshot.pending_by_minimum_tier),
            "retained_binary64_sample_count": snapshot.retained_binary64_sample_count,
            "deferred_count": snapshot.deferred_count,
            "unresolved_count": snapshot.unresolved_count,
            "rejected_count": snapshot.rejected_count,
            "system_failure_count": snapshot.system_failure_count,
            "evidence_counts": dict(snapshot.evidence_counts),
            "settled_leaf_ids": list(snapshot.settled_leaf_ids),
            "printed_leaf_ids": [
                row.leaf_id
                for row in current_rows
                if row.leaf_id in self._emitted_leaf_ids
            ],
            "presentation": {
                "opened": self._opened,
                "emitted_leaf_ids": sorted(self._emitted_leaf_ids),
                "terminal_summary_emitted": self._terminal_summary_emitted,
            },
            "counts": snapshot.counts,
            "report_status": dict(snapshot.report_status),
            # The legacy name is retained only for explicit numerical records;
            # it is never used for human dashboard progress.
            "completed_leaf_ids": numerical_records,
            "live_execution": dict(self._live),
            "active_leaf": active_leaf,
            "current_live_event": self._current_live_event,
            "last_nonterminal_event": self._last_nonterminal_event,
            "terminal_event": self._terminal_event,
            "active_leaf_at_terminal_event": self._active_leaf_at_terminal_event,
            "last_committed_leaf": self._last_committed_leaf,
            "next_intended_leaf": self._next_intended_leaf,
            "terminal_failure": self._terminal_failure,
            **self._diagnostic_paths,
            "last_event": self._terminal_event or self._last_nonterminal_event,
            "diagnostics": list(self.diagnostics),
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        encoded = json.dumps(
            _json_value(status),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(descriptor, "wb") as temporary:
                temporary.write(encoded)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, path)
        except BaseException:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise


def _ratio(numerator: object, denominator: object) -> str | None:
    if numerator is None and denominator is None:
        return None
    return f"{numerator if numerator is not None else '-'}/{denominator if denominator is not None else '-'}"


def _count_text(counts: Mapping[str, object]) -> str:
    labels = {
        "completed": "done",
        "queued": "queue",
        "deferred": "defer",
        "unresolved": "unres",
        "rejected": "reject",
        "system_failures": "sysfail",
    }
    return "/".join(
        f"{labels[name]}:{counts[name]}" for name in labels if name in counts
    )


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
        self._terminal_computed_leaf_ids: set[object] = set()
        self._accepted_leaf_ids: set[object] = set()
        self._rejected_leaf_ids: set[object] = set()
        self._indeterminate_leaf_ids: set[object] = set()
        self._failed_leaf_ids: set[object] = set()
        self._resource_limited_leaf_ids: set[object] = set()
        self._worker_timeout_leaf_ids: set[object] = set()
        self._protocol_failure_leaf_ids: set[object] = set()
        self._last_accepted_leaf: object | None = None
        self._last_terminal_leaf: object | None = None
        self._last_terminal_state: object | None = None
        self._checkpoint_status = "not yet written"
        self._checkpoint_leaf_ids: set[object] = set()
        self._campaign_status = "PENDING"
        self._cache_compatible = 0
        self._cache_stored = 0
        self._cache_reusing = 0
        self._cache_next_unsolved: object = None
        self._cache_published_leaf_ids: set[object] = set()
        self._cache_publication_failures: dict[object, dict[str, object]] = {}
        self._root_started: dict[tuple[object, ...], float] = {}
        self._precision_started: dict[tuple[object, object], float] = {}
        self._precision_activity: dict[
            tuple[object, object], tuple[float, str, str]
        ] = {}
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
        self._clean_tail = (
            CleanTailDashboard(self.stream, ansi=False)
            if self._terminal_dashboard
            else None
        )
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
            for row in self._campaign_report_model.leaf_rows:
                leaf_id = row.get("leaf_id")
                state = row.get("terminal_state")
                if leaf_id is None or state == "PENDING":
                    continue
                self._checkpoint_leaf_ids.add(leaf_id)
                if state in {"PRODUCED", "UNRESOLVED"}:
                    self._settled_leaf_ids.add(leaf_id)
                    self._terminal_computed_leaf_ids.add(leaf_id)
            for row in self._campaign_report_model.resource_failure_rows:
                leaf_id = row.get("leaf_id")
                code = row.get("failure_code")
                retry_status = row.get("retry_status")
                if leaf_id is None:
                    continue
                if retry_status == "RETRIED_COMPLETED":
                    self._resource_limited_leaf_ids.discard(leaf_id)
                    self._worker_timeout_leaf_ids.discard(leaf_id)
                    continue
                if retry_status == "RETRIED_FAILED":
                    continue
                self._resource_limited_leaf_ids.discard(leaf_id)
                self._worker_timeout_leaf_ids.discard(leaf_id)
                if code == "WORKER_TIMEOUT":
                    self._worker_timeout_leaf_ids.add(leaf_id)
                else:
                    self._resource_limited_leaf_ids.add(leaf_id)
            if self._checkpoint_leaf_ids:
                self._checkpoint_status = "written"
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
        timestamp_utc = (
            datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        leaf_key = context["leaf_id"]
        precision_key = (leaf_key, context["precision_digits"])
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
            self._terminal_computed_leaf_ids.add(leaf_key)
        if (
            event.kind is ProgressEventKind.LEAF_FAILED
            and leaf_key is not None
            and leaf_key not in self._settled_leaf_ids
            and self._failure_category(event.payload)
            not in {"RESOURCE LIMIT", "WORKER TIMEOUT"}
        ):
            self._settled_leaf_ids.add(leaf_key)
        if event.kind is ProgressEventKind.ROOT_PHASE_STARTED:
            self._root_started[root_key] = now
        if (
            event.kind is ProgressEventKind.PRECISION_STAGE_STARTED
            and leaf_key is not None
            and context["precision_digits"] is not None
        ):
            self._precision_started[precision_key] = now
        if (
            precision_key in self._precision_started
            and event.kind is not ProgressEventKind.WORKER_HEARTBEAT
        ):
            self._precision_activity[precision_key] = (
                now,
                event.kind.value,
                timestamp_utc,
            )
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
            "timestamp_utc": timestamp_utc,
            "elapsed_seconds": time.monotonic() - self._started,
            "monotonic_seconds": event.monotonic_seconds,
            "context": context,
            "payload": event.payload,
            "counters": dict(counters),
        }
        if leaf_key in self._leaf_started:
            record["elapsed_leaf_seconds"] = now - self._leaf_started[leaf_key]
        if precision_key in self._precision_started:
            record["elapsed_precision_seconds"] = (
                now - self._precision_started[precision_key]
            )
        if precision_key in self._precision_activity:
            activity_seconds, activity_kind, activity_timestamp = (
                self._precision_activity[precision_key]
            )
            record["last_activity_age_seconds"] = max(
                0.0, now - activity_seconds
            )
            record["last_activity_kind"] = activity_kind
            record["last_activity_timestamp_utc"] = activity_timestamp
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
            workflow_keys = (
                "solve_role",
                "authentication_mode",
                "authoritative",
                "full_authentication_escalated",
                "escalation_reason",
                "authenticated_evidence_reused",
                "determinant_count",
                "determinant_count_phase",
                "control_identity",
                "branch_authenticated",
                "residual_upper_bound_abs",
                "derivative_lower_bound_abs",
                "required_derivative_lower_bound_abs",
                "correction_upper_bound",
                "root_correction_tolerance",
                "raw_step_disagreement_abs",
                "guarded_step_disagreement_abs",
                "propagated_derivative_error_abs",
                *_PROMOTED_ACCEPTANCE_LIVE_STATE_KEYS,
            )
            if any(key in payload for key in workflow_keys):
                root_solve.update({
                    name: payload.get(name)
                    for name in workflow_keys
                })
                root_solve["determinant_count_phase"] = payload.get(
                    "determinant_count_phase", payload.get("determinant_count")
                )
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
        if event.kind in _DASHBOARD_FORCED_KINDS:
            self._last_dashboard_seconds = event.monotonic_seconds
            return True
        if event.kind not in _DASHBOARD_LIVE_KINDS:
            return False
        now = event.monotonic_seconds
        if (
            self._last_dashboard_seconds is None
            or now - self._last_dashboard_seconds >= _DASHBOARD_INTERVAL_SECONDS
        ):
            self._last_dashboard_seconds = now
            return True
        return False

    def _dashboard(self, record: Mapping[str, object]) -> None:
        dashboard = self._clean_tail
        if dashboard is None:
            return
        context = record["context"]
        payload = record["payload"]
        assert isinstance(context, Mapping)
        assert isinstance(payload, Mapping)
        if not dashboard._started:
            historical = tuple(
                self._clean_tail_row_from_report(row)
                for row in (
                    ()
                    if self._campaign_report_model is None
                    else self._campaign_report_model.leaf_rows
                )
                if row.get("terminal_state") != "PENDING"
            )
            dashboard.start(
                historical,
                counts={
                    "completed": len(self._settled_leaf_ids),
                    "accepted": len(self._accepted_leaf_ids),
                    "unresolved": len(self._indeterminate_leaf_ids),
                    "rejected": len(self._rejected_leaf_ids),
                    "failed": len(self._failed_leaf_ids),
                    "total": context.get("leaf_count", "-"),
                },
                profile="legacy",
                pass_name="campaign",
            )
        kind = record["kind"]
        live = self._live_execution_mapping()
        live_line = {
            "elapsed": f"{float(record['elapsed_seconds']):.1f}s",
            "counts": (
                f"done:{len(self._settled_leaf_ids)}"
                f"/acc:{len(self._accepted_leaf_ids)}"
                f"/unres:{len(self._indeterminate_leaf_ids)}"
                f"/reject:{len(self._rejected_leaf_ids)}"
                f"/fail:{len(self._failed_leaf_ids)}"
                f"/cache:{self._cache_stored}"
            ),
            "leaf": self._index_limit(
                live.get("leaf_index"), live.get("leaf_count")
            ),
            "profile": "legacy",
            "pass": live.get("phase"),
            "root": live.get("root"),
            "mechanism": live.get("mechanism_id"),
            "tier": live.get("precision_label"),
            "phase": live.get("root_phase"),
            "metric": live.get("determinant_abs"),
            "suboperation": live.get("suboperation"),
            "timing": live.get("elapsed_precision_seconds"),
            "last_activity_age": live.get("last_activity_age_seconds"),
        }
        if kind in {
            ProgressEventKind.LEAF_COMPLETED.value,
            ProgressEventKind.LEAF_REUSED.value,
            ProgressEventKind.LEAF_FAILED.value,
        }:
            dashboard.live(live_line)
            dashboard.complete(self._clean_tail_row(record))
        elif kind in {
            ProgressEventKind.CAMPAIGN_COMPLETED.value,
            ProgressEventKind.CAMPAIGN_FAILED.value,
            ProgressEventKind.CAMPAIGN_INTERRUPTED.value,
        }:
            dashboard.finish_live()
        else:
            dashboard.live(live_line)

    def _clean_tail_row_from_report(
        self, row: Mapping[str, object]
    ) -> dict[str, object]:
        return {
            "leaf_id": row.get("leaf_id"),
            "leaf_ordinal": row.get("leaf_ordinal"),
            "mode": row.get("mode"),
            "spin_or_Mkappa": row.get("spin_or_Mkappa"),
            "mechanism": row.get("mechanism"),
            "survey_pass": "campaign",
            "evidence_level": row.get("convergence_basis", "-"),
            "precision_tier": row.get(
                "precision_tier", row.get("precision_digits", "-")
            ),
            "response_magnitude": row.get("response_magnitude", "-"),
            "relative_disk_radius": row.get("relative_disk_radius", "-"),
            "terminal_state": row.get("terminal_state", "-"),
        }

    def _clean_tail_row(
        self, record: Mapping[str, object]
    ) -> dict[str, object]:
        context = record["context"]
        payload = record["payload"]
        assert isinstance(context, Mapping)
        assert isinstance(payload, Mapping)
        leaf_id = context.get("leaf_id")
        model = self._campaign_report_model
        if model is not None:
            for row in model.leaf_rows:
                if row.get("leaf_id") == leaf_id:
                    projected = self._clean_tail_row_from_report(row)
                    projected.setdefault(
                        "leaf_count", context.get("leaf_count")
                    )
                    return projected
        return {
            "leaf_id": leaf_id,
            "leaf_ordinal": context.get("leaf_index"),
            "leaf_count": context.get("leaf_count"),
            "mode": context.get("mode"),
            "spin": context.get("spin"),
            "mechanism_id": context.get("mechanism_id"),
            "survey_pass": "campaign",
            "evidence_level": "-",
            "precision_digits": context.get("precision_digits"),
            "total_leaf_seconds": record.get("leaf_elapsed_seconds"),
            "terminal_state": payload.get("state", "FAILED"),
        }

    def _bounded_dashboard_lines(self, record: Mapping[str, object]) -> list[str]:
        columns, terminal_rows = self._terminal_dimensions()
        maximum_rows = max(1, terminal_rows - 1)
        lines = self._dashboard_lines(record)
        if len(lines) > maximum_rows:
            lines = self._compact_dashboard_lines(record, maximum_rows)
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
        if kind == ProgressEventKind.PRECISION_STAGE_STARTED.value:
            for name in _PRECISION_LIVE_STATE_KEYS:
                self._dashboard_state.pop(name, None)
        if kind == ProgressEventKind.SOLVED_LEAF_CACHE_SCANNED.value:
            self._cache_compatible = int(payload.get("compatible_count", 0))
            self._cache_stored = int(payload.get("stored_count", 0))
            self._cache_reusing = int(payload.get("reusing_count", 0))
            self._cache_next_unsolved = payload.get("next_unsolved_index")
        elif kind == ProgressEventKind.LEAF_CACHE_PUBLISHED.value:
            leaf_id = context.get("leaf_id")
            if leaf_id is not None:
                if leaf_id not in self._cache_published_leaf_ids:
                    self._cache_stored += 1
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
                    *_AUTHENTICATION_LIVE_STATE_KEYS,
                    *_RADIAL_PROGRESS_STATE_KEYS,
                ):
                    self._dashboard_state.pop(name, None)
        for name, value in context.items():
            if value is not None:
                self._dashboard_state[name] = value
        for name in (
            "elapsed_precision_seconds",
            "last_activity_age_seconds",
            "last_activity_kind",
            "last_activity_timestamp_utc",
        ):
            if name in record:
                self._dashboard_state[name] = record[name]
        determinant_abs = record.get("current_determinant_abs")
        if determinant_abs is not None:
            self._dashboard_state["determinant_abs"] = determinant_abs
        best_determinant_abs = record.get("best_determinant_abs")
        if best_determinant_abs is not None:
            self._dashboard_state["best_determinant_abs"] = best_determinant_abs
        acceptance_threshold = payload.get("acceptance_threshold")
        if acceptance_threshold is not None:
            self._dashboard_state["acceptance_threshold"] = acceptance_threshold
        self._update_conditioning_dashboard_state(kind, payload)
        self._update_authentication_dashboard_state(kind, payload)
        if kind == ProgressEventKind.SUBOPERATION_PROGRESS.value:
            self._dashboard_state.update({
                "radial_suboperation": (
                    context.get("suboperation") or payload.get("suboperation")
                ),
                "radial_rhs_evaluations": payload.get("rhs_evaluations"),
                "radial_rho_span_fraction": payload.get("rho_span_fraction"),
                "radial_elapsed_seconds": payload.get("elapsed_seconds"),
            })
        elif kind in {
            ProgressEventKind.SUBOPERATION_STARTED.value,
            ProgressEventKind.SUBOPERATION_COMPLETED.value,
        }:
            # A finished or newly started integration has no interior progress of
            # its own yet; keep the panel from reporting the previous one.
            for name in _RADIAL_PROGRESS_STATE_KEYS:
                self._dashboard_state.pop(name, None)
        if kind in {
            ProgressEventKind.ODE_SOLVE_STARTED.value,
            ProgressEventKind.ODE_SOLVE_PROGRESS.value,
            ProgressEventKind.ODE_SOLVE_COMPLETED.value,
            ProgressEventKind.ODE_SOLVE_FAILED.value,
            ProgressEventKind.ODE_RESOURCE_LIMIT.value,
        }:
            if kind == ProgressEventKind.ODE_SOLVE_STARTED.value:
                for name in _ODE_PROGRESS_STATE_KEYS:
                    self._dashboard_state.pop(name, None)
            for name in _ODE_PROGRESS_STATE_KEYS:
                payload_name = (
                    "elapsed_seconds" if name == "ode_elapsed_seconds" else name
                )
                if payload_name in payload:
                    self._dashboard_state[name] = payload[payload_name]
            if kind in {
                ProgressEventKind.ODE_SOLVE_FAILED.value,
                ProgressEventKind.ODE_RESOURCE_LIMIT.value,
            }:
                self._dashboard_state["execution_state"] = "FAILED"
                self._dashboard_state["root_status"] = "FAILED"
                self._dashboard_state["failure_category"] = (
                    "RESOURCE LIMIT"
                    if kind == ProgressEventKind.ODE_RESOURCE_LIMIT.value
                    else "PROTOCOL/CONTROL FAILURE"
                )
        if kind == ProgressEventKind.ROOT_READOUT_RESOURCE_INFEASIBLE.value:
            self._dashboard_state["execution_state"] = "FAILED"
            self._dashboard_state["root_status"] = "RESOURCE LIMIT"
            self._dashboard_state["failure_category"] = "RESOURCE LIMIT"
            for name in ("failure_code", "limiting_resource"):
                if name in payload:
                    self._dashboard_state[name] = payload[name]
        if kind == ProgressEventKind.LEAF_STARTED.value:
            self._dashboard_state["leaf_status"] = "RUNNING"
        elif kind in {
            ProgressEventKind.LEAF_COMPLETED.value,
            ProgressEventKind.LEAF_REUSED.value,
        }:
            self._record_leaf_outcome(next_leaf, payload.get("state"))
        elif kind == ProgressEventKind.LEAF_FAILED.value:
            category = self._failure_category(payload)
            self._dashboard_state["failure_category"] = category
            structured = None
            worker_failure = payload.get("worker_failure")
            if isinstance(worker_failure, Mapping):
                candidate = worker_failure.get("failure")
                if isinstance(candidate, Mapping):
                    structured = candidate
            if structured is not None:
                for name in ("failure_code", "limiting_resource"):
                    if name in structured:
                        self._dashboard_state[name] = structured[name]
            if category == "RESOURCE LIMIT":
                leaf_status = "RESOURCE LIMITED / DEFERRED"
                root_status = "RESOURCE LIMIT"
                execution_state = "DEFERRED"
            elif category == "WORKER TIMEOUT":
                leaf_status = "WORKER TIMEOUT / DEFERRED"
                root_status = "WORKER TIMEOUT"
                execution_state = "DEFERRED"
            else:
                leaf_status = "FAILED"
                root_status = "FAILED"
                execution_state = "FAILED"
            self._dashboard_state["leaf_status"] = leaf_status
            self._dashboard_state["precision_status"] = root_status
            self._dashboard_state["root_status"] = root_status
            self._dashboard_state["execution_state"] = execution_state
            self._last_terminal_leaf = next_leaf
            self._last_terminal_state = leaf_status
            if next_leaf is not None:
                self._discard_leaf_outcomes(next_leaf)
                if category == "RESOURCE LIMIT":
                    self._resource_limited_leaf_ids.add(next_leaf)
                elif category == "WORKER TIMEOUT":
                    self._worker_timeout_leaf_ids.add(next_leaf)
                else:
                    self._failed_leaf_ids.add(next_leaf)
                    self._protocol_failure_leaf_ids.add(next_leaf)
        elif kind == ProgressEventKind.LEAF_INTERRUPTED.value:
            self._dashboard_state["leaf_status"] = "INTERRUPTED"
            self._dashboard_state["precision_status"] = "INTERRUPTED"
            self._dashboard_state["root_status"] = "INTERRUPTED"
            self._dashboard_state["execution_state"] = "INTERRUPTED"
            if next_leaf is not None:
                self._discard_leaf_outcomes(next_leaf)
        elif kind == ProgressEventKind.ROOT_PHASE_STARTED.value:
            self._dashboard_state["root_status"] = "SEARCHING"
            for name in (
                "root_phase",
                "solve_role",
                "authentication_mode",
                "authoritative",
                "full_authentication_escalated",
                "escalation_reason",
                "authenticated_evidence_reused",
                "control_identity",
                "residual_upper_bound_abs",
                "derivative_lower_bound_abs",
                "required_derivative_lower_bound_abs",
                "correction_upper_bound",
                "root_correction_tolerance",
                "raw_step_disagreement_abs",
                "guarded_step_disagreement_abs",
                "propagated_derivative_error_abs",
                *_PROMOTED_ACCEPTANCE_LIVE_STATE_KEYS,
            ):
                self._dashboard_state[name] = payload.get(name)
            self._dashboard_state["phase_determinant_count"] = 0
        elif kind == (
            ProgressEventKind.ROOT_PHASE_AUTHENTICATION_ESCALATED.value
        ):
            self._dashboard_state["full_authentication_escalated"] = True
            self._dashboard_state["escalation_reason"] = payload.get(
                "escalation_reason"
            )
            for name in (
                "root_phase",
                "solve_role",
                "authentication_mode",
                "authoritative",
                "authenticated_evidence_reused",
            ):
                self._dashboard_state[name] = payload.get(name)
            self._dashboard_state["phase_determinant_count"] = payload.get(
                "determinant_count_phase", payload.get("determinant_count")
            )
        elif kind in {
            event_kind.value
            for event_kind in _AUTHENTICATION_WORKFLOW_KINDS
        }:
            for name in (
                "root_phase",
                "authentication_mode",
                "authoritative",
                "full_authentication_escalated",
                "escalation_reason",
                "residual_upper_bound_abs",
                "derivative_lower_bound_abs",
                "required_derivative_lower_bound_abs",
                "correction_upper_bound",
                "root_correction_tolerance",
                "raw_step_disagreement_abs",
                "guarded_step_disagreement_abs",
                "propagated_derivative_error_abs",
                *_PROMOTED_ACCEPTANCE_LIVE_STATE_KEYS,
            ):
                self._dashboard_state[name] = payload.get(name)
            self._dashboard_state["phase_determinant_count"] = payload.get(
                "determinant_count_phase"
            )
        elif kind == ProgressEventKind.ROOT_PHASE_COMPLETED.value:
            for name in (
                "root_phase",
                "solve_role",
                "authentication_mode",
                "authoritative",
                "full_authentication_escalated",
                "escalation_reason",
                "authenticated_evidence_reused",
                "control_identity",
                "branch_authenticated",
                "residual_upper_bound_abs",
                "derivative_lower_bound_abs",
                "required_derivative_lower_bound_abs",
                "correction_upper_bound",
                "root_correction_tolerance",
                "raw_step_disagreement_abs",
                "guarded_step_disagreement_abs",
                "propagated_derivative_error_abs",
                *_PROMOTED_ACCEPTANCE_LIVE_STATE_KEYS,
            ):
                self._dashboard_state[name] = payload.get(name)
            self._dashboard_state["phase_determinant_count"] = payload.get(
                "determinant_count_phase", payload.get("determinant_count")
            )
            converged = payload.get("converged")
            if converged is True:
                self._dashboard_state["root_status"] = "CONVERGED"
            elif converged is False:
                self._dashboard_state["root_status"] = "NOT_CONVERGED"
                self._dashboard_state["failure_category"] = (
                    "NUMERICAL NONCONVERGENCE"
                )
        elif kind == ProgressEventKind.ROOT_SEED_SELECTED.value:
            seed_kind = context.get("seed_kind") or payload.get("seed_kind")
            self._dashboard_state["seed_kind"] = seed_kind
            self._dashboard_state["seed_authenticated"] = seed_kind in {
                "AUTHENTICATED_BACKGROUND",
                "FALLBACK_BACKGROUND",
                "EPSILON_CONTINUATION",
                "SPIN_CONTINUATION",
            }
        elif kind == ProgressEventKind.PRECISION_STAGE_STARTED.value:
            for name in (
                "failure_category",
                "failure_code",
                "limiting_resource",
            ):
                self._dashboard_state.pop(name, None)
            self._dashboard_state["precision_status"] = "ACTIVE"
            self._dashboard_state["execution_state"] = "RUNNING"
            self._dashboard_state["root_status"] = "PENDING"
            self._dashboard_state["branch_valid"] = "PENDING"
            self._dashboard_state["worker"] = (
                "Julia"
                if context.get("precision_digits") in {80, 120}
                else "Python"
            )
            self._dashboard_state["promotion_reason"] = self._promotion_reason(
                next_leaf, context.get("precision_digits")
            )
        elif kind == ProgressEventKind.PRECISION_STAGE_COMPLETED.value:
            numerical_state = payload.get("numerical_state")
            if numerical_state is not None:
                self._dashboard_state["precision_status"] = numerical_state
            if payload.get("leaf_state") == "MISSING_PRECISION":
                self._dashboard_state["leaf_status"] = "MISSING_PRECISION"
            self._dashboard_state["execution_state"] = "COMPLETED"
        elif kind == ProgressEventKind.WORKER_HEARTBEAT.value:
            worker = payload.get("worker")
            if isinstance(worker, str) and worker:
                self._dashboard_state["worker"] = worker
        elif kind == ProgressEventKind.CHECKPOINT_WRITING.value:
            self._checkpoint_status = "writing"
        elif kind == ProgressEventKind.CHECKPOINT_WRITTEN.value:
            self._checkpoint_status = "written"
            if next_leaf is not None:
                self._checkpoint_leaf_ids.add(next_leaf)
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
            self._dashboard_state["root_status"] = "FAILED"
            self._dashboard_state["execution_state"] = "FAILED"
        elif kind == ProgressEventKind.CAMPAIGN_INTERRUPTED.value:
            self._campaign_status = "INTERRUPTED"
            if self.checkpoint.is_file():
                self._refresh_campaign_reports()
            if self._dashboard_state.get("leaf_status") == "RUNNING":
                self._dashboard_state["leaf_status"] = "INTERRUPTED"
                self._dashboard_state["precision_status"] = "INTERRUPTED"
            self._dashboard_state["root_status"] = "INTERRUPTED"
            self._dashboard_state["execution_state"] = "INTERRUPTED"
        elif kind == ProgressEventKind.REQUEST_FAILED.value:
            self._dashboard_state["root_status"] = "FAILED"
            self._dashboard_state["execution_state"] = "FAILED"
        elif kind == ProgressEventKind.REQUEST_INTERRUPTED.value:
            self._dashboard_state["root_status"] = "INTERRUPTED"
            self._dashboard_state["execution_state"] = "INTERRUPTED"

    def _update_conditioning_dashboard_state(
        self, kind: str, payload: Mapping[str, object]
    ) -> None:
        """Retain bounded factored diagnostics, never full series values."""

        payload_names = {
            "homogeneous_representation": (
                "homogeneous_representation",
                "representation_id",
            ),
            "determinant_family": ("determinant_family",),
            "determinant_normalisation": ("determinant_normalisation",),
            "scattering_diagnostics_applicable": (
                "scattering_diagnostics_applicable",
            ),
            "scattering_column_convention": (
                "scattering_column_convention",
            ),
            "determinant_convention": ("determinant_convention",),
            "current_carrier": (
                "current_carrier",
                "carrier_id",
                "carrier",
                "to_carrier",
            ),
            "maximum_series_digits_lost": (
                "maximum_series_digits_lost",
                "series_digits_lost",
            ),
            "maximum_recurrence_digits_lost": (
                "maximum_recurrence_digits_lost",
                "recurrence_digits_lost",
            ),
            "maximum_series_evaluation_spread": (
                "maximum_series_evaluation_spread",
                "series_evaluation_spread",
            ),
            "maximum_basis_condition": (
                "maximum_basis_condition",
                "basis_condition",
            ),
            "maximum_basis_backward_error": (
                "maximum_basis_backward_error",
                "basis_backward_error",
            ),
            "maximum_matching_reconstruction_residual": (
                "maximum_matching_reconstruction_residual",
                "matching_reconstruction_residual",
            ),
            "endpoint_remainders_regular": ("endpoint_remainders_regular",),
            "maximum_endpoint_reconstruction_error": (
                "maximum_endpoint_reconstruction_error",
                "endpoint_reconstruction_error",
            ),
            "maximum_contour_angle_deformation": (
                "maximum_contour_angle_deformation",
                "contour_angle_deformation",
            ),
            "maximum_fd_digits_lost": (
                "maximum_fd_digits_lost",
                "fd_digits_lost",
                "digits_lost_fd",
            ),
            "predicted_reliable_digits": ("predicted_reliable_digits",),
            "required_reliable_digits": ("required_reliable_digits",),
            "precision_limited": ("precision_limited",),
            "minimum_cref_chart_margin": (
                "minimum_cref_chart_margin",
                "cref_chart_margin",
            ),
            "maximum_carrier_change_error": (
                "maximum_carrier_change_error",
                "carrier_change_error",
            ),
            "normalised_determinant_abs": ("normalised_determinant_abs",),
            "raw_determinant_abs": ("raw_determinant_abs",),
            "cref_chart_safe": ("cref_chart_safe",),
            "asymptotic_preflight_adequate": (
                "asymptotic_preflight_adequate",
                "adequate",
            ),
            "asymptotic_preflight_avoided_ode": (
                "asymptotic_preflight_avoided_ode",
                "ode_avoided",
            ),
        }
        applicability = payload.get("scattering_diagnostics_applicable")
        mechanism_id = self._dashboard_state.get("mechanism_id")
        if mechanism_id == "horizon-admittance":
            exterior = False
        elif isinstance(mechanism_id, str) and mechanism_id.startswith(
            "exterior-"
        ):
            exterior = True
        else:
            exterior = applicability is False or (
                payload.get("determinant_family") == "exterior-wronskian/v1"
            )
        exterior_forbidden_fields = frozenset({
            "maximum_basis_condition",
            "maximum_basis_backward_error",
            "maximum_matching_reconstruction_residual",
            "minimum_cref_chart_margin",
            "maximum_carrier_change_error",
            "scattering_column_convention",
            "cref_chart_safe",
            "raw_determinant_abs",
        })
        if exterior:
            # These values belong only to the horizon scattering solve.  Clear
            # them explicitly because ignoring JSON null would display stale
            # Cref/basis evidence from an earlier event.
            for name in exterior_forbidden_fields:
                self._dashboard_state.pop(name, None)
        for state_name, candidates in payload_names.items():
            if exterior and state_name in exterior_forbidden_fields:
                continue
            for payload_name in candidates:
                if payload_name in payload and payload[payload_name] is not None:
                    self._dashboard_state[state_name] = payload[payload_name]
                    break
        if "raw_determinant_evidence_status" in payload:
            raw_status = payload["raw_determinant_evidence_status"]
            if exterior:
                self._dashboard_state["raw_determinant_evidence_status"] = (
                    "not-applicable/v1"
                )
                self._dashboard_state.pop("raw_determinant_abs", None)
            elif raw_status in {"available/v1", "unavailable-overflow/v1"}:
                self._dashboard_state["raw_determinant_evidence_status"] = (
                    raw_status
                )
                if (
                    raw_status == "unavailable-overflow/v1"
                    or payload.get("raw_determinant_abs") is None
                ):
                    self._dashboard_state.pop("raw_determinant_abs", None)
            else:
                self._dashboard_state.pop(
                    "raw_determinant_evidence_status", None
                )
                self._dashboard_state.pop("raw_determinant_abs", None)
        if exterior:
            self._dashboard_state.update({
                "determinant_family": "exterior-wronskian/v1",
                "determinant_convention": (
                    "wronskian-perturbed-Xin-with-Xup/v1"
                ),
                "determinant_normalisation": (
                    "unit-asymptotic-branch-wronskian/v1"
                ),
                "scattering_diagnostics_applicable": False,
                "determinant_chart": "unit-asymptotic branch Wronskian",
                "raw_determinant_evidence_status": "not-applicable/v1",
            })
        elif kind == ProgressEventKind.DETERMINANT_CHART_EVALUATED.value:
            self._dashboard_state["determinant_chart"] = "Cinc/Cref − R"

    def _update_authentication_dashboard_state(
        self, kind: str, payload: Mapping[str, object]
    ) -> None:
        """Retain the exact terms behind the current root decision."""

        authentication = payload.get("root_authentication")
        if isinstance(authentication, Mapping):
            for name in (
                "central_determinant_re",
                "central_determinant_im",
                "residual_upper_bound_abs",
                "correction_upper_bound",
                "root_correction_tolerance",
            ):
                if authentication.get(name) is not None:
                    self._dashboard_state[name] = authentication[name]
            accepted = authentication.get("accepted")
            if type(accepted) is bool:
                self._dashboard_state["root_authentication_accepted"] = accepted

            derivative = authentication.get("derivative_authentication")
            if isinstance(derivative, Mapping):
                derivative_names = {
                    "derivative_re": "derivative_re",
                    "derivative_im": "derivative_im",
                    "derivative_propagated_error_abs": "propagated_error_abs",
                    "derivative_step_disagreement_abs": "step_disagreement_abs",
                    "derivative_lower_bound_abs": "lower_bound_abs",
                    "derivative_selected_step": "selected_step",
                    "derivative_axis": "axis",
                }
                for state_name, payload_name in derivative_names.items():
                    if derivative.get(payload_name) is not None:
                        self._dashboard_state[state_name] = derivative[payload_name]

            determinant_error = authentication.get("determinant_error")
            if determinant_error is None:
                for name in _DETERMINANT_ERROR_LIVE_STATE_KEYS:
                    self._dashboard_state.pop(name, None)
            elif isinstance(determinant_error, Mapping):
                error_names = {
                    "determinant_error_model": "error_model_id",
                    "determinant_error_abs": "numerical_error_abs",
                    "determinant_error_safety_factor": "safety_factor",
                    "endpoint_disagreement_abs": "endpoint_disagreement_abs",
                    "control_disagreement_abs": "control_disagreement_abs",
                    "equivalence_disagreement_abs": (
                        "equivalence_disagreement_abs"
                    ),
                    "precision_disagreement_abs": "precision_disagreement_abs",
                }
                for state_name, payload_name in error_names.items():
                    value = determinant_error.get(payload_name)
                    if value is None:
                        self._dashboard_state.pop(state_name, None)
                    else:
                        self._dashboard_state[state_name] = value
            return

        if kind == ProgressEventKind.DETERMINANT_ERROR_ESTIMATED.value:
            direct_names = {
                "determinant_error_model": "error_model_id",
                "determinant_error_abs": "numerical_error_abs",
                "determinant_error_safety_factor": "safety_factor",
                "endpoint_disagreement_abs": "endpoint_disagreement_abs",
                "control_disagreement_abs": "control_disagreement_abs",
                "equivalence_disagreement_abs": "equivalence_disagreement_abs",
                "precision_disagreement_abs": "precision_disagreement_abs",
            }
            for state_name, payload_name in direct_names.items():
                value = payload.get(payload_name)
                if value is None:
                    self._dashboard_state.pop(state_name, None)
                else:
                    self._dashboard_state[state_name] = value

    def _promotion_reason(
        self, leaf_id: object, precision_digits: object
    ) -> str | None:
        if (
            leaf_id is None
            or isinstance(precision_digits, bool)
            or not isinstance(precision_digits, int)
            or precision_digits <= 64
            or self._campaign_report_model is None
        ):
            return None
        prior = [
            row
            for row in self._campaign_report_model.precision_stage_rows
            if row.get("leaf_id") == leaf_id
            and isinstance(row.get("precision_digits"), int)
            and row["precision_digits"] < precision_digits
        ]
        if not prior:
            return None
        row = prior[-1]
        prior_digits = row["precision_digits"]
        label = (
            "binary64"
            if prior_digits == 64
            else precision_tier_presentation(prior_digits).presentation_label
        )
        state = row.get("numerical_state")
        return label if state is None else f"{label} {state}"

    @staticmethod
    def _failure_category(payload: Mapping[str, object]) -> str:
        worker_failure = payload.get("worker_failure")
        if isinstance(worker_failure, Mapping):
            structured = worker_failure.get("failure")
            if worker_failure.get("worker_timed_out") is True:
                return "WORKER TIMEOUT"
            if isinstance(structured, Mapping):
                code = structured.get("failure_code")
                if code == "WORKER_TIMEOUT":
                    return "WORKER TIMEOUT"
                if code in {
                    "ODE_RESOURCE_LIMIT",
                    "ROOT_READOUT_RESOURCE_INFEASIBLE",
                } and structured.get("failure_class") == "CONTROL":
                    return "RESOURCE LIMIT"
        if payload.get("numerical_state") == "NOT_CONVERGED":
            return "NUMERICAL NONCONVERGENCE"
        return "PROTOCOL/CONTROL FAILURE"

    def _record_leaf_outcome(self, leaf_id: object, state: object) -> None:
        self._last_terminal_leaf = leaf_id
        self._last_terminal_state = state
        if leaf_id is not None:
            self._discard_leaf_outcomes(leaf_id)
        if state == "PRODUCED":
            status = "ACCEPTED"
            target = self._accepted_leaf_ids
            self._last_accepted_leaf = leaf_id
        elif state == "UNRESOLVED":
            status = "INDETERMINATE"
            target = self._indeterminate_leaf_ids
            self._dashboard_state["failure_category"] = (
                "NUMERICAL NONCONVERGENCE"
            )
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
            self._resource_limited_leaf_ids,
            self._worker_timeout_leaf_ids,
            self._protocol_failure_leaf_ids,
        ):
            outcomes.discard(leaf_id)

    def _current_leaf_persistence(self) -> dict[str, object]:
        leaf_id = self._dashboard_state.get("leaf_id")
        return {
            "leaf_id": leaf_id,
            "terminal_computed": leaf_id in self._terminal_computed_leaf_ids,
            "checkpoint_saved": leaf_id in self._checkpoint_leaf_ids,
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
        if self._last_terminal_leaf is not None:
            for row in model.leaf_rows:
                if row.get("leaf_id") == self._last_terminal_leaf:
                    return row
            return None
        if self._last_accepted_leaf is not None:
            for row in model.leaf_rows:
                if row.get("leaf_id") == self._last_accepted_leaf:
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
        result_precision = None if row is None else row.get("precision_digits")
        precision = (
            None
            if result_precision is None
            else precision_tier_presentation(result_precision)
        )
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
            ("ResultState", None if row is None else row.get("terminal_state")),
            ("ResultPrecision", result_precision),
            (
                "ResultPrecisionTier",
                None if precision is None else precision.precision_tier,
            ),
            (
                "ResultPrecisionDecimalDigitsNominal",
                None
                if precision is None
                else precision.nominal_decimal_digits,
            ),
            (
                "ResultPrecisionLabel",
                None if precision is None else precision.presentation_label,
            ),
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
            (
                "BaselineNewtonCorrection",
                None if row is None else row.get("baseline_newton_correction"),
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
            *tuple(
                (
                    name,
                    None if row is None else row.get(name),
                )
                for name in CONDITIONING_REPORT_COLUMNS
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
            ("ResourceLimited", len(self._resource_limited_leaf_ids)),
            ("WorkerTimeout", len(self._worker_timeout_leaf_ids)),
            ("ProtocolControlFailed", len(self._protocol_failure_leaf_ids)),
            ("FailureCategory", context.get("failure_category")),
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
            ("RootPhase", context.get("root_phase")),
            ("SolveRole", context.get("solve_role")),
            ("AuthenticationMode", context.get("authentication_mode")),
            ("Authoritative", context.get("authoritative")),
            (
                "FullAuthEscalated",
                context.get("full_authentication_escalated"),
            ),
            ("EscalationReason", context.get("escalation_reason")),
            (
                "AuthenticatedReuse",
                context.get("authenticated_evidence_reused"),
            ),
            ("PhaseDeterminants", context.get("phase_determinant_count")),
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
        fields = dict(self._dashboard_fields(record))
        lines = [
            "==============================================================",
            " M02 KERR-QNM SCIENTIFIC DASHBOARD",
            "==============================================================",
            "",
            " CAMPAIGN",
            self._dashboard_field_line("Completed", fields.get("Completed")),
            self._dashboard_field_line("Accepted", fields.get("Accepted")),
            self._dashboard_field_line("Unresolved", fields.get("Indeterminate")),
            self._dashboard_field_line("Rejected", fields.get("Rejected")),
            self._dashboard_field_line("Failed", fields.get("Failed")),
            self._dashboard_field_line(
                "Resource limits", fields.get("ResourceLimited")
            ),
            self._dashboard_field_line(
                "Worker timeouts", fields.get("WorkerTimeout")
            ),
            self._dashboard_field_line(
                "Protocol/control", fields.get("ProtocolControlFailed")
            ),
            "",
            " LATEST COMPLETED LEAF",
            *self._latest_completed_leaf_lines(fields),
            *self._current_execution_lines(),
            *self._precision_stage_table_lines(),
            "",
            " CACHE",
            self._dashboard_field_line("Stored", self._cache_stored),
            self._dashboard_field_line(
                "Publish fails", len(self._cache_publication_failures)
            ),
            "",
            f" Last refresh:  {datetime.now().astimezone().strftime('%H:%M:%S')}",
            " Dashboard refreshes throughout active work and after committed stages.",
        ]
        return lines

    def _compact_dashboard_lines(
        self, record: Mapping[str, object], maximum_rows: int
    ) -> list[str]:
        fields = dict(self._dashboard_fields(record))
        leading = [
            "==============================================================",
            " M02 KERR-QNM SCIENTIFIC DASHBOARD",
            "==============================================================",
            "",
            " CAMPAIGN",
            self._dashboard_field_line("Completed", fields.get("Completed")),
            (
                f" Accepted       {self._dashboard_value(fields.get('Accepted'))}"
                f" | Unresolved {self._dashboard_value(fields.get('Indeterminate'))}"
            ),
            (
                f" Rejected       {self._dashboard_value(fields.get('Rejected'))}"
                f" | Failed {self._dashboard_value(fields.get('Failed'))}"
            ),
            "",
            " LATEST COMPLETED LEAF",
            self._dashboard_field_line(
                "State", fields.get("ResultState") or self._last_terminal_state
            ),
            self._dashboard_field_line(
                "Mechanism",
                fields.get("ResultMechanism")
                or self._dashboard_state.get("mechanism_id"),
            ),
            (
                f" Spin           {self._dashboard_value(fields.get('ResultSpin') or self._dashboard_state.get('spin'))}"
                f" | Precision {self._precision_value(fields)}"
            ),
            "",
            *self._current_execution_lines(compact=True),
        ]
        trailing = [
            " CACHE",
            (
                f" Stored         {self._cache_stored}"
                f" | Publish fails {len(self._cache_publication_failures)}"
            ),
            "",
            f" Last refresh:  {datetime.now().astimezone().strftime('%H:%M:%S')}",
            " Dashboard refreshes throughout active work and after committed stages.",
        ]
        table_overhead = 4
        table_rows = max(1, maximum_rows - len(leading) - len(trailing) - table_overhead)
        return [
            *leading,
            *self._precision_stage_table_lines(maximum_rows=table_rows),
            *trailing,
        ]

    def _precision_stage_table_lines(
        self, *, maximum_rows: int = 8
    ) -> list[str]:
        """Render recent committed precision stages as one fixed-width table."""

        model = self._campaign_report_model
        header = (
            f"{'ROOT':<16} {'PRECISION':<21} {'RESULT':<13} {'CONVERGED':<9} "
            f"{'BRANCH_OK':<9} {'D_ABS':>10} {'CORR_OVER_TOL':>13} "
            f"{'NEWTON_DW':>10} {'DELTA_ROOT':>10}"
        )
        if model is None or not model.precision_stage_rows:
            return [
                "",
                " PRECISION STAGE RESULTS",
                header,
                "-" * len(header),
                "(no completed precision stages in the authenticated checkpoint)",
            ]
        rows = model.precision_stage_rows[-max(1, maximum_rows):]
        return [
            "",
            " PRECISION STAGE RESULTS",
            header,
            "-" * len(header),
            *(self._precision_stage_table_row(row) for row in rows),
        ]

    def _current_execution_lines(self, *, compact: bool = False) -> list[str]:
        state = self._live_execution_mapping()
        if state.get("state") != "RUNNING":
            category = state.get("failure_category")
            if category is None:
                return []
            return [
                " CURRENT EXECUTION CONTROL RESULT",
                self._dashboard_field_line("Category", category),
                self._dashboard_field_line("Failure code", state.get("failure_code")),
                self._dashboard_field_line(
                    "Limiting resource", state.get("limiting_resource")
                ),
            ]
        current_leaf = self._index_limit(
            state.get("leaf_index"), state.get("leaf_count")
        )
        root = state.get("root")
        mechanism = state.get("mechanism_id")
        precision = state.get("precision_label")
        phase = state.get("phase")
        promotion = state.get("promotion_reason")
        seed = state.get("seed_kind")
        seed_authenticated = self._yes_no_pending(
            state.get("seed_authenticated")
        )
        branch_valid = self._yes_no_pending(state.get("branch_valid"))
        worker = state.get("worker")
        tier_elapsed = self._duration_value(state.get("elapsed_precision_seconds"))
        activity = self._activity_text(state)
        newton = self._index_limit(
            state.get("newton_index"), state.get("newton_limit")
        )
        determinant_counts = " | ".join(
            (
                f"leaf {self._dashboard_value(state.get('determinant_index_leaf')) or '-'}",
                f"phase {self._dashboard_value(state.get('determinant_index_phase')) or '-'}",
                f"Newton {self._dashboard_value(state.get('determinant_index_newton')) or '-'}",
            )
        )
        current_omega = self._complex_text(state.get("current_omega"))
        determinant_abs = self._scientific_number(state.get("determinant_abs"))
        best_determinant_abs = self._scientific_number(
            state.get("best_determinant_abs")
        )
        suboperation = state.get("suboperation")
        radial = self._radial_progress_text()
        ode_lines = self._ode_progress_lines(compact=compact)
        conditioning_lines = self._conditioning_progress_lines(compact=compact)
        authentication_lines = self._authentication_progress_lines(
            compact=compact
        )
        if compact:
            suboperation_text = self._dashboard_value(suboperation)
            if radial is not None:
                suboperation_text = f"{suboperation_text} ({radial})"
            compact_determinants = determinant_counts.replace(" | ", " ")
            return [
                " CURRENTLY EXECUTING",
                f" Current leaf   {current_leaf} | Root {self._dashboard_value(root)} | {self._dashboard_value(precision)}",
                f" Mechanism      {self._dashboard_value(mechanism)} | Phase {self._dashboard_value(phase)} | {self._dashboard_value(state.get('failure_category') or 'RUNNING')}",
                f" Promoted by    {self._dashboard_value(promotion)} | Branch {branch_valid}",
                f" Worker         {self._dashboard_value(worker)} | Tier elapsed {self._dashboard_value(tier_elapsed)}",
                f" Activity       {self._dashboard_value(activity)} | Seed authenticated {seed_authenticated}",
                " LIVE ROOT SOLVE",
                f" Newton         {newton} | Dets {compact_determinants} | Suboperation {suboperation_text}",
                self._dashboard_field_line("Current ω", current_omega),
                f" |D|            {determinant_abs} | Best |D| {best_determinant_abs}",
                *ode_lines,
                *conditioning_lines,
                *authentication_lines,
            ]
        return [
            "",
            " CURRENTLY EXECUTING",
            self._dashboard_field_line("Current leaf", current_leaf),
            self._dashboard_field_line("Root", root),
            self._dashboard_field_line("Mechanism", mechanism),
            self._dashboard_field_line("Precision", precision),
            self._dashboard_field_line("Phase", phase),
            self._dashboard_field_line("State", state.get("state")),
            self._dashboard_field_line(
                "Classification", state.get("failure_category")
            ),
            self._dashboard_field_line("Promotion", promotion),
            self._dashboard_field_line("Seed", seed),
            self._dashboard_field_line("Seed authenticated", seed_authenticated),
            self._dashboard_field_line("Branch valid", branch_valid),
            self._dashboard_field_line("Worker", worker),
            self._dashboard_field_line("Tier elapsed", tier_elapsed),
            self._dashboard_field_line("Last activity", activity),
            "",
            " LIVE ROOT SOLVE",
            self._dashboard_field_line("Newton", newton),
            self._dashboard_field_line("Determinants", determinant_counts),
            self._dashboard_field_line("Current ω", current_omega),
            self._dashboard_field_line("|D|", determinant_abs),
            self._dashboard_field_line("Best |D|", best_determinant_abs),
            self._dashboard_field_line("Suboperation", suboperation),
            self._dashboard_field_line("Radial progress", radial),
            *ode_lines,
            *conditioning_lines,
            *authentication_lines,
        ]

    def _radial_progress_text(self) -> str | None:
        """Summarise how far the active radial integration has advanced."""

        state = self._dashboard_state
        evaluations = state.get("radial_rhs_evaluations")
        if isinstance(evaluations, bool) or not isinstance(evaluations, int):
            return None
        parts = [f"{evaluations} evals"]
        fraction = state.get("radial_rho_span_fraction")
        if not isinstance(fraction, bool) and isinstance(fraction, (int, float)):
            if math.isfinite(float(fraction)):
                parts.append(f"{float(fraction) * 100.0:.1f}% of ρ span")
        elapsed = state.get("radial_elapsed_seconds")
        if not isinstance(elapsed, bool) and isinstance(elapsed, (int, float)):
            if math.isfinite(float(elapsed)):
                parts.append(f"{float(elapsed):.0f}s")
        return ", ".join(parts)

    def _ode_progress_lines(self, *, compact: bool) -> list[str]:
        """Render the latest exact SciML segment snapshot without hiding collapse."""

        state = self._dashboard_state
        leg = state.get("ode_leg")
        if not isinstance(leg, str) or not leg:
            return []

        def shown(name: str) -> str:
            value = state.get(name)
            return "-" if value is None else str(value)

        identity = (
            f"#{shown('ode_solve_id')} {leg} | ret={shown('ode_retcode')} "
            f"| endpoint={shown('ode_endpoint_reached')}"
        )
        work = (
            f"nf={shown('ode_rhs_evaluations')} "
            f"accept/reject={shown('ode_accepted_steps')}/{shown('ode_rejected_steps')} "
            f"jac/linear={shown('ode_jacobian_evaluations')}/{shown('ode_linear_solves')} "
            f"nonlinear/fail={shown('ode_nonlinear_iterations')}/"
            f"{shown('ode_nonlinear_convergence_failures')}"
        )
        steps = (
            f"dt last/min/proposed={shown('ode_last_accepted_step_abs')}/"
            f"{shown('ode_min_accepted_step_abs')}/"
            f"{shown('ode_proposed_step_abs')}"
        )
        algorithm = f"algorithm={shown('ode_algorithm_configured')}"
        if compact:
            return [
                f" ODE segment    {identity}",
                f" ODE work       {work}",
                f" ODE steps      {steps}",
            ]
        return [
            "",
            " LIVE ODE SEGMENT",
            self._dashboard_field_line("Identity", identity),
            self._dashboard_field_line("Work", work),
            self._dashboard_field_line("Steps", steps),
            self._dashboard_field_line("Algorithm", algorithm),
        ]

    def _conditioning_progress_lines(self, *, compact: bool) -> list[str]:
        """Render the bounded state, excluding detailed complex series values."""

        state = self._dashboard_state
        if not any(
            state.get(name) is not None
            for name in _CONDITIONING_LIVE_STATE_KEYS
        ):
            return []

        def shown(name: str) -> str:
            value = state.get(name)
            return "-" if value is None else str(value)

        adequate = state.get("asymptotic_preflight_adequate")
        if adequate is True:
            adequacy = "adequate"
        elif adequate is False:
            adequacy = "inadequate"
        else:
            adequacy = "-"
        avoided = state.get("asymptotic_preflight_avoided_ode")
        avoided_text = (
            "yes" if avoided is True else "no" if avoided is False else "-"
        )
        safe = state.get("cref_chart_safe")
        safe_text = "safe" if safe is True else "unsafe" if safe is False else "-"
        representation = shown("homogeneous_representation")
        determinant_family = shown("determinant_family")
        carrier = shown("current_carrier")
        asymptotic = (
            f"{adequacy}; loss={shown('maximum_series_digits_lost')}; "
            f"spread={shown('maximum_series_evaluation_spread')}; "
            f"ODE avoided={avoided_text}"
        )
        losses = (
            f"recurrence={shown('maximum_recurrence_digits_lost')}; "
            f"basis={shown('maximum_basis_condition')}; "
            f"FD={shown('maximum_fd_digits_lost')}"
        )
        reliable = (
            f"{shown('predicted_reliable_digits')} / "
            f"{shown('required_reliable_digits')}"
        )
        if state.get("scattering_diagnostics_applicable") is False:
            chart = (
                f"{shown('determinant_chart')}; scattering n/a; "
                f"|D|={shown('normalised_determinant_abs')}; "
                f"raw={shown('raw_determinant_evidence_status')}"
            )
        else:
            chart = (
                f"{shown('determinant_chart')}; Cref {safe_text}; "
                f"|D|={shown('normalised_determinant_abs')}; "
                f"raw={shown('raw_determinant_evidence_status')}"
            )
        if compact:
            return [
                " FACTORED CONDITIONING",
                f" Representation {representation} | Determinant {determinant_family}",
                f" Carrier        {carrier}",
                f" Asymptotic     {asymptotic}",
                f" Loss/condition {losses}",
                f" Reliable digits {reliable}",
                f" Chart          {chart}",
            ]
        return [
            "",
            " FACTORED CONDITIONING",
            self._dashboard_field_line("Representation", representation),
            self._dashboard_field_line("Determinant", determinant_family),
            self._dashboard_field_line("Carrier", carrier),
            self._dashboard_field_line("Asymptotic", asymptotic),
            self._dashboard_field_line("Loss/condition", losses),
            self._dashboard_field_line("Reliable digits", reliable),
            self._dashboard_field_line("Chart", chart),
        ]

    def _authentication_progress_lines(self, *, compact: bool) -> list[str]:
        """Render the absolute-error certificate for the current root."""

        state = self._dashboard_state
        if not any(
            state.get(name) is not None
            for name in _AUTHENTICATION_LIVE_STATE_KEYS
        ):
            return []

        def shown(name: str) -> str:
            value = state.get(name)
            return "-" if value is None else str(value)

        determinant = (
            f"D={shown('central_determinant_re')} "
            f"{shown('central_determinant_im')}i; "
            f"eta={shown('determinant_error_abs')}; "
            f"residual<={shown('residual_upper_bound_abs')}"
        )
        derivative = (
            f"D'={shown('derivative_re')} {shown('derivative_im')}i; "
            f"lower={shown('derivative_lower_bound_abs')}; "
            f"step={shown('derivative_selected_step')} "
            f"({shown('derivative_axis')})"
        )
        decision = (
            f"{shown('correction_upper_bound')} / "
            f"{shown('root_correction_tolerance')}; "
            f"accepted={shown('root_authentication_accepted')}"
        )
        if compact:
            return [
                " ROOT AUTHENTICATION",
                f" Determinant     {determinant}",
                f" Derivative      {derivative}",
                f" Correction      {decision}",
            ]
        return [
            "",
            " ROOT AUTHENTICATION",
            self._dashboard_field_line("Determinant", determinant),
            self._dashboard_field_line("Derivative", derivative),
            self._dashboard_field_line("Correction", decision),
            self._dashboard_field_line(
                "Error model", shown("determinant_error_model")
            ),
        ]

    def _live_execution_mapping(self) -> dict[str, object]:
        state = self._dashboard_state
        mode = state.get("mode")
        spin = state.get("spin")
        mode_label = self._mode_label(mode)
        root = None
        if mode_label is not None and spin is not None:
            try:
                spin_text = format(float(spin), ".6g")
            except (TypeError, ValueError, OverflowError):
                spin_text = str(spin)
            root = f"{mode_label} a/M={spin_text}"
        precision_digits = state.get("precision_digits")
        precision_label = None
        if (
            isinstance(precision_digits, int)
            and not isinstance(precision_digits, bool)
        ):
            precision_label = precision_tier_presentation(
                precision_digits
            ).presentation_label
        return {
            "state": state.get("execution_state", "IDLE"),
            "leaf_index": state.get("leaf_index"),
            "leaf_count": state.get("leaf_count"),
            "root": root,
            "leaf_id": state.get("leaf_id"),
            "mechanism_id": state.get("mechanism_id"),
            "precision_digits": precision_digits,
            "precision_label": precision_label,
            "phase": state.get("phase"),
            "root_phase": state.get("root_phase"),
            "solve_role": state.get("solve_role"),
            "authentication_mode": state.get("authentication_mode"),
            "authoritative": state.get("authoritative"),
            "full_authentication_escalated": state.get(
                "full_authentication_escalated"
            ),
            "escalation_reason": state.get("escalation_reason"),
            "authenticated_evidence_reused": state.get(
                "authenticated_evidence_reused"
            ),
            "phase_determinant_count": state.get(
                "phase_determinant_count"
            ),
            "phase_control_identity": state.get("control_identity"),
            "phase_branch_authenticated": state.get(
                "branch_authenticated"
            ),
            "phase_residual_upper_bound_abs": state.get(
                "residual_upper_bound_abs"
            ),
            "phase_derivative_lower_bound_abs": state.get(
                "derivative_lower_bound_abs"
            ),
            "phase_required_derivative_lower_bound_abs": state.get(
                "required_derivative_lower_bound_abs"
            ),
            "phase_correction_upper_bound": state.get(
                "correction_upper_bound"
            ),
            "phase_root_correction_tolerance": state.get(
                "root_correction_tolerance"
            ),
            "phase_raw_step_disagreement_abs": state.get(
                "raw_step_disagreement_abs"
            ),
            "phase_guarded_step_disagreement_abs": state.get(
                "guarded_step_disagreement_abs"
            ),
            "phase_propagated_derivative_error_abs": state.get(
                "propagated_derivative_error_abs"
            ),
            "phase_promoted_root_readout_policy": state.get(
                "promoted_root_readout_policy"
            ),
            "phase_acceptance_metric": state.get("acceptance_metric"),
            "phase_correction_abs": state.get("correction_abs"),
            "phase_derivative_abs": state.get("derivative_abs"),
            "phase_derivative": state.get("derivative"),
            "phase_post_newton_determinant_count": state.get(
                "post_newton_determinant_count"
            ),
            "phase_fixed_root": state.get("fixed_root"),
            "phase_derivative_source": state.get("derivative_source"),
            "phase_determinant_error_abs": state.get(
                "determinant_error_abs"
            ),
            "phase_error_model_id": state.get("error_model_id"),
            "promotion_reason": state.get("promotion_reason"),
            "seed_kind": state.get("seed_kind"),
            "seed_authenticated": state.get("seed_authenticated"),
            "branch_valid": state.get("branch_valid"),
            "worker": state.get("worker"),
            "failure_category": state.get("failure_category"),
            "failure_code": state.get("failure_code"),
            "limiting_resource": state.get("limiting_resource"),
            "elapsed_precision_seconds": state.get("elapsed_precision_seconds"),
            "last_activity_age_seconds": state.get("last_activity_age_seconds"),
            "last_activity_kind": state.get("last_activity_kind"),
            "last_activity_timestamp_utc": state.get(
                "last_activity_timestamp_utc"
            ),
            "newton_index": state.get("newton_index"),
            "newton_limit": state.get("newton_limit"),
            "determinant_index_leaf": state.get("determinant_index_leaf"),
            "determinant_index_phase": state.get("determinant_index_phase"),
            "determinant_index_newton": state.get("determinant_index_newton"),
            "current_omega": state.get("current_omega"),
            "determinant_abs": state.get("determinant_abs"),
            "best_determinant_abs": state.get("best_determinant_abs"),
            "suboperation": state.get("suboperation"),
            "radial_suboperation": state.get("radial_suboperation"),
            "radial_rhs_evaluations": state.get("radial_rhs_evaluations"),
            "radial_rho_span_fraction": state.get("radial_rho_span_fraction"),
            "radial_elapsed_seconds": state.get("radial_elapsed_seconds"),
            **{
                name: state.get(name)
                for name in _CONDITIONING_LIVE_STATE_KEYS
            },
            **{
                name: state.get(name)
                for name in _AUTHENTICATION_LIVE_STATE_KEYS
            },
            "series_digits_lost_max": state.get(
                "maximum_series_digits_lost"
            ),
            "recurrence_digits_lost_max": state.get(
                "maximum_recurrence_digits_lost"
            ),
            "basis_condition_max": state.get("maximum_basis_condition"),
            "basis_backward_error_max": state.get(
                "maximum_basis_backward_error"
            ),
            "matching_reconstruction_residual_max": state.get(
                "maximum_matching_reconstruction_residual"
            ),
            "endpoint_reconstruction_error_max": state.get(
                "maximum_endpoint_reconstruction_error"
            ),
            "contour_angle_deformation_max": state.get(
                "maximum_contour_angle_deformation"
            ),
            "fd_digits_lost_max": state.get("maximum_fd_digits_lost"),
            "cref_chart_margin_min": state.get("minimum_cref_chart_margin"),
            **{name: state.get(name) for name in _ODE_PROGRESS_STATE_KEYS},
        }

    @staticmethod
    def _mode_label(value: object) -> str | None:
        if not isinstance(value, Mapping):
            return None
        ell, m, n = value.get("ell"), value.get("m"), value.get("n")
        if any(isinstance(item, bool) or not isinstance(item, int) for item in (ell, m, n)):
            return None
        return f"{ell}{m}{n}"

    @staticmethod
    def _yes_no_pending(value: object) -> str:
        if value is True:
            return "YES"
        if value is False:
            return "NO"
        if isinstance(value, str) and value:
            return value
        return "PENDING"

    @staticmethod
    def _index_limit(index: object, limit: object) -> str:
        left = "-" if index is None else str(index)
        right = "-" if limit is None else str(limit)
        return f"{left}/{right}"

    @classmethod
    def _complex_text(cls, value: object) -> str:
        if not isinstance(value, Mapping):
            return ""
        real = value.get("real")
        imaginary = value.get("imaginary")
        if real is None or imaginary is None:
            return ""
        return f"{real} {imaginary}i"

    @classmethod
    def _activity_text(cls, state: Mapping[str, object]) -> str:
        kind = state.get("last_activity_kind")
        if not isinstance(kind, str) or not kind:
            return "PENDING"
        if kind == ProgressEventKind.SUBOPERATION_STARTED.value:
            label = f"{state.get('suboperation') or 'suboperation'} started"
        elif kind == ProgressEventKind.SUBOPERATION_COMPLETED.value:
            label = f"{state.get('suboperation') or 'suboperation'} completed"
        else:
            label = kind.replace("_", " ")
        age = cls._duration_value(state.get("last_activity_age_seconds"))
        return label if age is None else f"{label} ({age} ago)"

    @classmethod
    def _precision_stage_table_row(cls, row: Mapping[str, object]) -> str:
        root = cls._precision_stage_text(row.get("root"))
        result = cls._precision_stage_text(row.get("numerical_state"))
        converged = cls._precision_stage_boolean(row.get("converged"))
        branch_ok = cls._precision_stage_boolean(row.get("branch_ok"))
        determinant = cls._precision_stage_number(row.get("determinant_abs"))
        correction_over_tolerance = cls._precision_stage_number(
            row.get("newton_correction_over_tolerance")
        )
        newton = cls._precision_stage_number(row.get("newton_correction"))
        displacement = cls._precision_stage_number(
            row.get("root_displacement_abs")
        )
        precision_digits = row.get("precision_digits")
        precision = (
            "-"
            if precision_digits is None
            else precision_tier_presentation(
                precision_digits
            ).presentation_label
        )
        return (
            f"{root:<16.16} {precision:<21.21} {result:<13.13} "
            f"{converged:<9.9} {branch_ok:<9.9} {determinant:>10.10} "
            f"{correction_over_tolerance:>13.13} {newton:>10.10} {displacement:>10.10}"
        )

    @staticmethod
    def _precision_stage_text(value: object) -> str:
        return "-" if value is None else str(value)

    @staticmethod
    def _precision_stage_boolean(value: object) -> str:
        if value is True:
            return "True"
        if value is False:
            return "False"
        return "-"

    @staticmethod
    def _precision_stage_number(value: object) -> str:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return "-"
        number = float(value)
        if not math.isfinite(number):
            return "-"
        if 1.0e-3 <= abs(number) < 1.0e5:
            return format(number, ".6g")
        return format(number, ".3E")

    def _latest_completed_leaf_lines(
        self, fields: Mapping[str, object]
    ) -> list[str]:
        state = fields.get("ResultState") or self._last_terminal_state
        mechanism = (
            fields.get("ResultMechanism")
            or self._dashboard_state.get("mechanism_id")
        )
        spin = fields.get("ResultSpin") or self._dashboard_state.get("spin")
        lines = [
            self._dashboard_field_line("State", state),
            self._dashboard_field_line("Mechanism", mechanism),
            self._dashboard_field_line("Spin", spin),
            self._dashboard_field_line("Precision", self._precision_value(fields)),
            self._dashboard_field_line("Convergence", fields.get("Convergence")),
        ]
        response_real = fields.get("ResponseRe")
        response_imaginary = fields.get("ResponseIm")
        if response_real is None or response_imaginary is None:
            lines.extend(["", " No scientific result payload."])
            return lines
        response = (
            f"{self._general_number(response_real)} "
            f"{self._signed_imaginary(response_imaginary)}i"
        )
        lines.extend(
            [
                "",
                self._dashboard_field_line("Response", response),
                self._dashboard_field_line(
                    "|Response|", self._scientific_number(fields.get("ResponseAbs"))
                ),
                self._dashboard_field_line(
                    "Local disk", self._scientific_number(fields.get("LocalDisk"))
                ),
                self._dashboard_field_line(
                    "Disk / |R|",
                    self._scientific_number(fields.get("DiskResponse")),
                ),
                "",
                self._dashboard_field_line(
                    "Baseline Re",
                    self._general_number(
                        self._mapping_value(fields.get("BaselineOmega"), "real")
                    ),
                ),
                self._dashboard_field_line(
                    "Baseline Im",
                    self._general_number(
                        self._mapping_value(
                            fields.get("BaselineOmega"), "imaginary"
                        )
                    ),
                ),
                self._dashboard_field_line(
                    "Baseline |D|",
                    self._scientific_number(fields.get("BaselineResidual")),
                ),
                self._dashboard_field_line(
                    "Newton corr",
                    self._scientific_number(
                        fields.get("BaselineNewtonCorrection")
                    ),
                ),
            ]
        )
        return lines

    @classmethod
    def _dashboard_field_line(cls, label: str, value: object) -> str:
        return f" {label:<14} {cls._dashboard_value(value)}"

    def _precision_value(self, fields: Mapping[str, object]) -> str:
        value = (
            fields.get("ResultPrecision")
            or self._dashboard_state.get("precision_digits")
        )
        if value is None:
            return ""
        return precision_tier_presentation(value).presentation_label

    @staticmethod
    def _mapping_value(value: object, key: str) -> object:
        if not isinstance(value, Mapping):
            return None
        return value.get(key)

    @staticmethod
    def _general_number(value: object) -> str:
        if value is None:
            return ""
        try:
            return format(float(value), ".13g")
        except (TypeError, ValueError, OverflowError):
            return str(value)

    @staticmethod
    def _signed_imaginary(value: object) -> str:
        try:
            return format(float(value), "+.12f")
        except (TypeError, ValueError, OverflowError):
            return str(value)

    @staticmethod
    def _scientific_number(value: object) -> str:
        if value is None:
            return ""
        try:
            return format(float(value), ".3E")
        except (TypeError, ValueError, OverflowError):
            return str(value)

    @staticmethod
    def _color_dashboard_line(line: str) -> str:
        return line

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
            "ode_solve_id",
            "ode_leg",
            "ode_retcode",
            "ode_rhs_evaluations",
            "ode_accepted_steps",
            "ode_rejected_steps",
            "failure_code",
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
            precision = precision_tier_presentation(
                context["precision_digits"]
            )
            parts.append(f" precision={precision.presentation_label}")
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
        context = record.get("context")
        precision_value = (
            context.get("precision_digits")
            if isinstance(context, Mapping)
            else None
        )
        status["precision"] = (
            None
            if precision_value is None
            else precision_tier_presentation(precision_value).to_mapping()
        )
        status["persistence"] = self._persistence_status()
        status["scientific"] = dict(self._scientific_dashboard_fields())
        status["live_execution"] = self._live_execution_mapping()
        status["resource_failures"] = (
            []
            if self._campaign_report_model is None
            else [
                dict(row)
                for row in self._campaign_report_model.resource_failure_rows
            ]
        )
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
        if self._clean_tail is not None:
            self._clean_tail.finish_live()
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
