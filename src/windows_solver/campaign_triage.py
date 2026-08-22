"""Deterministic whole-atlas risk triage for targeted M02 evidence work."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Mapping, Sequence

from .campaign_policy import EvidenceLevel, ExecutionProfile
from .contracts import canonical_json_bytes
from .response_batches import CampaignPlan, CampaignRunSummary
from .response_engine import ComponentResult, ComponentStatus


TRIAGE_SCHEMA = "windows-solver.m02-atlas-triage/1"
_TRIAGE_ACTION_BY_PROFILE = {
    ExecutionProfile.CERTIFY: "CERTIFY",
    ExecutionProfile.VALIDATE: "VALIDATE",
}


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _json_ids(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return ()
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value)


def triage_leaf_ids_for_profile(
    plan: CampaignPlan,
    value: object,
    profile: ExecutionProfile,
    *,
    limit: int | None = None,
) -> tuple[str, ...]:
    """Authenticate one unified mixed-role queue and select its next action."""

    if profile not in _TRIAGE_ACTION_BY_PROFILE:
        raise ValueError("triage queues require certify or validate profile")
    if limit is not None and (
        type(limit) is not int or limit <= 0
    ):
        raise ValueError("triage queue limit must be a positive integer")
    if not isinstance(value, Mapping) or set(value) != {
        "schema",
        "campaign_id",
        "checkpoint_source_receipt",
        "recommended_certification_queue",
        "triage_sha256",
    }:
        raise ValueError("campaign triage report fields are invalid")
    content = {
        name: value[name]
        for name in value
        if name != "triage_sha256"
    }
    if (
        value.get("schema") != TRIAGE_SCHEMA
        or value.get("campaign_id") != plan.campaign_id
        or value.get("triage_sha256") != _sha256(content)
    ):
        raise ValueError("campaign triage report identity is invalid")
    raw_entries = value.get("recommended_certification_queue")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise ValueError("campaign triage queue is empty or invalid")
    leaf_by_id = {leaf.leaf_id: leaf for leaf in plan.leaves}
    expected_fields = {
        "rank",
        "leaf_id",
        "mode",
        "mechanism",
        "terminal_state",
        "evidence_level",
        "recommended_action",
        "priority_score",
        "reasons",
        "metrics",
    }
    eligible: list[str] = []
    seen: set[str] = set()
    expected_action = _TRIAGE_ACTION_BY_PROFILE[profile]
    for expected_rank, raw in enumerate(raw_entries, start=1):
        if (
            not isinstance(raw, Mapping)
            or set(raw) != expected_fields
            or raw.get("rank") != expected_rank
            or not isinstance(raw.get("reasons"), list)
            or not isinstance(raw.get("metrics"), Mapping)
        ):
            raise ValueError("campaign triage queue entry is invalid")
        leaf_id = raw.get("leaf_id")
        if not isinstance(leaf_id, str) or leaf_id in seen:
            raise ValueError("campaign triage queue leaf identity is invalid")
        leaf = leaf_by_id.get(leaf_id)
        if (
            leaf is None
            or raw.get("mode") != leaf.leaf.mode_label
            or raw.get("mechanism") != leaf.mechanism_id
        ):
            raise ValueError("campaign triage queue is off-plan")
        seen.add(leaf_id)
        if raw.get("recommended_action") == expected_action:
            eligible.append(leaf_id)
    if not eligible:
        raise ValueError(
            f"campaign triage queue has no {expected_action} leaves"
        )
    return tuple(eligible if limit is None else eligible[:limit])


@dataclass(frozen=True, slots=True)
class CampaignTriageEntry:
    rank: int
    leaf_id: str
    mode: str
    mechanism: str
    terminal_state: str
    evidence_level: str | None
    recommended_action: str
    priority_score: float
    reasons: tuple[str, ...]
    metrics: Mapping[str, object]

    def to_mapping(self) -> dict[str, object]:
        return {
            "rank": self.rank,
            "leaf_id": self.leaf_id,
            "mode": self.mode,
            "mechanism": self.mechanism,
            "terminal_state": self.terminal_state,
            "evidence_level": self.evidence_level,
            "recommended_action": self.recommended_action,
            "priority_score": self.priority_score,
            "reasons": list(self.reasons),
            "metrics": dict(self.metrics),
        }


@dataclass(frozen=True, slots=True)
class CampaignTriageReport:
    campaign_id: str
    checkpoint_source_receipt: str
    entries: tuple[CampaignTriageEntry, ...]

    @property
    def content(self) -> dict[str, object]:
        return {
            "schema": TRIAGE_SCHEMA,
            "campaign_id": self.campaign_id,
            "checkpoint_source_receipt": self.checkpoint_source_receipt,
            "recommended_certification_queue": [
                entry.to_mapping() for entry in self.entries
            ],
        }

    @property
    def triage_sha256(self) -> str:
        return _sha256(self.content)

    def to_mapping(self) -> dict[str, object]:
        return {**self.content, "triage_sha256": self.triage_sha256}


def _component_result(record) -> ComponentResult | None:
    if not record.stages:
        return None
    return _stage_component_result(record.stages[-1])


def _stage_component_result(stage) -> ComponentResult | None:
    raw = stage.outcome.component_result.get("result")
    if not isinstance(raw, Mapping):
        return None
    try:
        return ComponentResult.from_mapping(raw)
    except (TypeError, ValueError):
        return None


def build_campaign_triage(
    plan: CampaignPlan,
    summary: CampaignRunSummary,
    leaf_rows: Sequence[Mapping[str, object]],
    projective_rows: Sequence[Mapping[str, object]],
    *,
    checkpoint_source_receipt: str,
) -> CampaignTriageReport:
    """Rank atlas risks without changing any numerical acceptance rule."""

    records = {record.leaf_id: record for record in summary.records}
    rows = {str(row["leaf_id"]): row for row in leaf_rows}
    leaf_plan = {leaf.leaf_id: leaf for leaf in plan.leaves}
    reasons: dict[str, set[str]] = {leaf_id: set() for leaf_id in records}
    scores: dict[str, float] = {leaf_id: 0.0 for leaf_id in records}
    metrics: dict[str, dict[str, object]] = {
        leaf_id: {} for leaf_id in records
    }

    finite_relative: list[tuple[float, str]] = []
    finite_clearance: list[tuple[float, str]] = []
    finite_derivative_disagreement: list[tuple[float, str]] = []
    finite_precision_disagreement: list[tuple[float, str]] = []
    for leaf_id, record in records.items():
        row = rows.get(leaf_id, {})
        if record.state in {"UNRESOLVED", "FAILED"}:
            reasons[leaf_id].add(
                "FAILED_SURVEY_LEAF"
                if record.state == "FAILED"
                else "UNRESOLVED_SURVEY_LEAF"
            )
            scores[leaf_id] += 10000.0
        radius = row.get("local_disk_radius")
        magnitude = row.get("response_magnitude")
        if isinstance(radius, (int, float)) and isinstance(
            magnitude, (int, float)
        ):
            radius_value = float(radius)
            magnitude_value = float(magnitude)
            if math.isfinite(radius_value) and math.isfinite(magnitude_value):
                metrics[leaf_id]["response_magnitude"] = magnitude_value
                metrics[leaf_id]["local_disk_radius"] = radius_value
                if magnitude_value <= radius_value:
                    reasons[leaf_id].add("RESPONSE_DISK_CONTAINS_ZERO")
                    scores[leaf_id] += 9000.0
                if magnitude_value > 0.0:
                    relative = radius_value / magnitude_value
                    finite_relative.append((relative, leaf_id))
                    metrics[leaf_id]["relative_disk_radius"] = relative
                if radius_value > 0.0:
                    clearance = (magnitude_value - radius_value) / radius_value
                    finite_clearance.append((clearance, leaf_id))

        result = _component_result(record)
        if result is not None:
            if (
                result.status is ComponentStatus.BRANCH_LOSS
                or result.baseline.root_reference_id
                != leaf_plan[leaf_id].job.root.root_reference_id
                or result.baseline.branch_id
                != leaf_plan[leaf_id].job.root.branch_id
            ):
                reasons[leaf_id].add("BRANCH_RISK")
                scores[leaf_id] += 8000.0
            conditioning = result.baseline.numerical_conditioning
            if conditioning is not None and conditioning.precision_limited:
                reasons[leaf_id].add("PRECISION_LIMITED")
                scores[leaf_id] += 7000.0
            derivative = result.derivative_evidence
            if isinstance(derivative, Mapping):
                disagreements = tuple(
                    float(value)
                    for name in (
                        "raw_step_disagreement_abs",
                        "frequency_raw_step_disagreement_abs",
                    )
                    for value in (derivative.get(name),)
                    if isinstance(value, (int, float))
                    and math.isfinite(float(value))
                )
                if disagreements and max(disagreements) > 0.0:
                    disagreement = max(disagreements)
                    metrics[leaf_id]["derivative_disagreement_abs"] = (
                        disagreement
                    )
                    finite_derivative_disagreement.append(
                        (disagreement, leaf_id)
                    )
                decision = derivative.get("conditioning_decision")
                if (
                    isinstance(decision, Mapping)
                    and decision.get("accepted") is False
                ):
                    reasons[leaf_id].add("DERIVATIVE_DISAGREEMENT")
                    scores[leaf_id] += 7500.0

        if len(record.stages) > 1:
            left = _stage_component_result(record.stages[0])
            right = _component_result(record)
            if (
                left is not None
                and right is not None
                and left.response is not None
                and right.response is not None
            ):
                disagreement = abs(right.response - left.response)
                bound = (
                    record.stages[0].outcome.local_disk_radius_abs
                    + record.stages[-1].outcome.local_disk_radius_abs
                )
                metrics[leaf_id]["binary64_promoted_disagreement_abs"] = (
                    disagreement
                )
                if disagreement > 0.0:
                    finite_precision_disagreement.append(
                        (disagreement, leaf_id)
                    )
                if disagreement > bound:
                    reasons[leaf_id].add("BINARY64_PROMOTED_DISAGREEMENT")
                    scores[leaf_id] += 8500.0

    relative_count = max(1, math.ceil(len(finite_relative) / 10))
    for relative, leaf_id in sorted(finite_relative, reverse=True)[:relative_count]:
        reasons[leaf_id].add("LARGEST_RELATIVE_RESPONSE_DISK")
        scores[leaf_id] += 1000.0 + min(relative, 1000.0)
    near_zero_count = max(1, math.ceil(len(finite_clearance) / 10))
    for clearance, leaf_id in sorted(finite_clearance)[:near_zero_count]:
        reasons[leaf_id].add("APPROACHING_ZERO")
        scores[leaf_id] += 1200.0 + max(0.0, 100.0 - clearance)
    derivative_count = max(
        1, math.ceil(len(finite_derivative_disagreement) / 10)
    )
    for _, leaf_id in sorted(
        finite_derivative_disagreement, reverse=True
    )[:derivative_count]:
        reasons[leaf_id].add("LARGEST_DERIVATIVE_DISAGREEMENT")
        scores[leaf_id] += 1100.0
    precision_count = max(
        1, math.ceil(len(finite_precision_disagreement) / 10)
    )
    for _, leaf_id in sorted(
        finite_precision_disagreement, reverse=True
    )[:precision_count]:
        reasons[leaf_id].add("LARGEST_BINARY64_PROMOTED_DISAGREEMENT")
        scores[leaf_id] += 1150.0

    complete_angles = tuple(
        row
        for row in projective_rows
        if isinstance(row.get("nominal_angle"), (int, float))
        and math.isfinite(float(row["nominal_angle"]))
    )
    if complete_angles:
        controlling = min(
            complete_angles, key=lambda row: float(row["nominal_angle"])
        )
        controlling_ids = set(_json_ids(controlling.get("left_component_ids")))
        controlling_ids.update(
            _json_ids(controlling.get("right_component_ids"))
        )
        for leaf_id in controlling_ids & set(records):
            reasons[leaf_id].update({
                "SMALLEST_PROJECTIVE_ANGLE_ROW",
                "PROJECTIVE_CLASSIFICATION_CONTROLLER",
            })
            scores[leaf_id] += 6000.0
            metrics[leaf_id]["controlling_projective_row_id"] = controlling.get(
                "row_id"
            )
            metrics[leaf_id]["controlling_nominal_angle"] = controlling.get(
                "nominal_angle"
            )

    def add_sentinels(attribute: str, reason: str) -> None:
        groups: dict[str, list[str]] = {}
        for leaf_id in records:
            leaf = leaf_plan[leaf_id]
            value = (
                leaf.mechanism_id
                if attribute == "mechanism"
                else leaf.leaf.mode_label
            )
            groups.setdefault(value, []).append(leaf_id)
        for members in groups.values():
            selected = max(
                members,
                key=lambda leaf_id: (scores[leaf_id], -plan.leaves.index(leaf_plan[leaf_id])),
            )
            reasons[selected].add(reason)
            scores[selected] += 500.0

    add_sentinels("mechanism", "MECHANISM_SENTINEL")
    add_sentinels("mode", "MODE_FAMILY_SENTINEL")

    ordered_ids = sorted(
        records,
        key=lambda leaf_id: (
            -scores[leaf_id],
            plan.leaves.index(leaf_plan[leaf_id]),
        ),
    )
    entries: list[CampaignTriageEntry] = []
    for rank, leaf_id in enumerate(ordered_ids, start=1):
        record = records[leaf_id]
        level = None if record.evidence is None else record.evidence.evidence_level
        action = (
            "RESOLVE_SURVEY"
            if record.state in {"UNRESOLVED", "FAILED"}
            else "CERTIFY"
            if level is EvidenceLevel.SCREENED
            else "VALIDATE"
            if level is EvidenceLevel.CERTIFIED
            else "REVIEW"
        )
        leaf = leaf_plan[leaf_id]
        entries.append(CampaignTriageEntry(
            rank=rank,
            leaf_id=leaf_id,
            mode=leaf.leaf.mode_label,
            mechanism=leaf.mechanism_id,
            terminal_state=record.state,
            evidence_level=None if level is None else level.value,
            recommended_action=action,
            priority_score=scores[leaf_id],
            reasons=tuple(sorted(reasons[leaf_id])),
            metrics=metrics[leaf_id],
        ))
    return CampaignTriageReport(
        campaign_id=plan.campaign_id,
        checkpoint_source_receipt=checkpoint_source_receipt,
        entries=tuple(entries),
    )


def write_campaign_triage_report(
    path: Path, report: CampaignTriageReport
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json_bytes(report.to_mapping()))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
