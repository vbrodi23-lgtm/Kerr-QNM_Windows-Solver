"""Pure, ledger-driven projection for the schema-11 human dashboard.

This module is deliberately presentation-only.  It validates the latest
committed checkpoint and derives operator counts and settled rows from the
durable pass, queue, evidence, and failure ledgers.  Numerical records are
consulted only for optional response details and the distinct ``PRODUCED``
count; they are never the source of pass progress.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import math
from types import MappingProxyType

from .campaign_policy import PromotionQueueDisposition, validate_schema11_checkpoint
from .campaign_failures import system_failure_resolution_index


_EVIDENCE_LEVELS = ("SCREENED", "CERTIFIED", "VALIDATED")
_ROUTE_TIERS = ("BF40", "BF80")
_ACTIVE_CALCULATION_DISPOSITIONS = frozenset(
    {
        PromotionQueueDisposition.PENDING.value,
        PromotionQueueDisposition.CALCULATED_PENDING_DERIVATION.value,
        PromotionQueueDisposition.CONTROL_RETURN_RETAINED.value,
        PromotionQueueDisposition.CONTROL_DECISION_RETAINED.value,
        PromotionQueueDisposition.NUMERICAL_CONTINUATION.value,
    }
)


@dataclass(frozen=True, slots=True)
class Schema11DashboardRow:
    """One immutable human-facing settled pass row."""

    leaf_id: str
    leaf_ordinal: int | None
    leaf_count: int
    mode: object
    spin: object
    mechanism: object
    role: object
    time_seconds: float | None
    sample_count: int
    next_tier: str | None
    state: str
    survey_pass: str
    evidence_level: str
    binary64_seconds: float | None = None
    bf40_seconds: float | None = None
    bf80_seconds: float | None = None
    bf120_seconds: float | None = None
    total_leaf_seconds: float | None = None
    response_magnitude: object = "-"
    relative_error: object = "-"

    @property
    def spin_or_Mkappa(self) -> object:  # noqa: N802 - checkpoint vocabulary
        return self.spin


@dataclass(frozen=True, slots=True)
class Schema11EvidenceRow:
    """One immutable evidence-ledger row for certify/validate views."""

    leaf_id: str
    leaf_ordinal: int | None
    leaf_count: int
    mode: object
    spin: object
    mechanism: object
    role: object
    evidence_level: str
    state: str


@dataclass(frozen=True, slots=True)
class Schema11EndpointRecoveryRow:
    """One branch/order/geometry decision retained from endpoint recovery."""

    leaf_id: str
    endpoint_branch: str
    attempted_order: int
    attempted_geometry: str
    limiting_resource: str
    selected_intervention: str
    result: str
    aggregate_limitation: str


@dataclass(frozen=True, slots=True)
class Schema11DashboardSnapshot:
    """Canonical operator projection of one committed schema-11 checkpoint."""

    selected_leaf_ids: tuple[str, ...]
    binary64_rows: tuple[Schema11DashboardRow, ...]
    promoted_rows: tuple[Schema11DashboardRow, ...]
    evidence_rows: tuple[Schema11EvidenceRow, ...]
    endpoint_recovery_rows: tuple[Schema11EndpointRecoveryRow, ...]
    selected_leaf_count: int
    binary64_processed_count: int
    promoted_processed_count: int
    produced_count: int
    pending_count: int
    pending_by_minimum_tier: Mapping[str, int]
    retained_binary64_sample_count: int
    deferred_count: int
    unresolved_count: int
    rejected_count: int
    system_failure_count: int
    active_system_failure_count: int
    historical_system_failure_count: int
    evidence_counts: Mapping[str, int]
    settled_leaf_ids: tuple[str, ...]
    report_status: Mapping[str, object]

    @property
    def rows(self) -> tuple[Schema11DashboardRow, ...]:
        """Compatibility view containing both numerical pass row sets."""

        return self.binary64_rows + self.promoted_rows

    @property
    def selected_count(self) -> int:
        return self.selected_leaf_count

    @property
    def pending_bf40_count(self) -> int:
        return int(self.pending_by_minimum_tier.get("BF40", 0))

    @property
    def pending_bf80_count(self) -> int:
        return int(self.pending_by_minimum_tier.get("BF80", 0))

    @property
    def screened_count(self) -> int:
        return int(self.evidence_counts.get("SCREENED", 0))

    @property
    def certified_count(self) -> int:
        return int(self.evidence_counts.get("CERTIFIED", 0))

    @property
    def validated_count(self) -> int:
        return int(self.evidence_counts.get("VALIDATED", 0))

    @property
    def counts(self) -> dict[str, object]:
        """Return the status vocabulary shared by human and machine output."""

        return {
            "selected_leaf_count": self.selected_leaf_count,
            "binary64_processed_count": self.binary64_processed_count,
            "promoted_processed_count": self.promoted_processed_count,
            "produced_count": self.produced_count,
            "pending_count": self.pending_count,
            "pending_by_minimum_tier": dict(self.pending_by_minimum_tier),
            "retained_binary64_sample_count": self.retained_binary64_sample_count,
            "deferred_count": self.deferred_count,
            "unresolved_count": self.unresolved_count,
            "rejected_count": self.rejected_count,
            "system_failure_count": self.system_failure_count,
            "active_system_failure_count": self.active_system_failure_count,
            "historical_system_failure_count": self.historical_system_failure_count,
            "evidence_counts": dict(self.evidence_counts),
        }


def project_schema11_dashboard(
    checkpoint: Mapping[str, object],
    *,
    selected_leaf_ids: Iterable[str],
    leaf_metadata: Mapping[str, Mapping[str, object]] | None,
) -> Schema11DashboardSnapshot:
    """Project authenticated schema-11 state into one immutable snapshot.

    ``selected_leaf_ids`` is the authoritative selected set.  Every count is
    restricted to it except the system-failure total, which is the durable
    checkpoint failure ledger length.  Its active and historical partitions
    are derived only from append-only resolution receipts.  The function never
    infers progress from report CSVs or from the presence of numerical records.
    """

    value = validate_schema11_checkpoint(checkpoint)
    selected = _stable_selected_ids(selected_leaf_ids)
    metadata = leaf_metadata or {}
    selected_set = set(selected)
    selected_count = len(selected)

    ledgers = value["survey_pass_ledger"]
    assert isinstance(ledgers, Mapping)
    binary = _mapping(ledgers.get("binary64"))
    promoted = _mapping(ledgers.get("promoted"))

    queue = value["promotion_queue"]
    assert isinstance(queue, Mapping)
    queue_entries = queue.get("entries")
    if not isinstance(queue_entries, list):
        queue_entries = []
    pending_by_leaf: dict[str, Mapping[str, object]] = {}
    pending_by_tier = {tier: 0 for tier in _ROUTE_TIERS}
    pending_count = 0
    for item in queue_entries:
        if not isinstance(item, Mapping):
            continue
        leaf_id = item.get("leaf_id")
        if (
            item.get("disposition") not in _ACTIVE_CALCULATION_DISPOSITIONS
            or leaf_id not in selected_set
        ):
            continue
        pending_count += 1
        tier = str(item.get("minimum_requested_tier", "-"))
        pending_by_tier[tier] = pending_by_tier.get(tier, 0) + 1
        if isinstance(leaf_id, str):
            pending_by_leaf[leaf_id] = item

    records = {
        str(item["leaf_id"]): item
        for item in value["records"]
        if isinstance(item, Mapping) and isinstance(item.get("leaf_id"), str)
    }
    evidence_ledger = _mapping(value["evidence_ledger"])

    binary_selected = [leaf_id for leaf_id in selected if leaf_id in binary]
    promoted_selected = [leaf_id for leaf_id in selected if leaf_id in promoted]
    produced_count = sum(
        1
        for leaf_id in selected
        if isinstance(records.get(leaf_id), Mapping)
        and records[leaf_id].get("state") == "PRODUCED"
    )
    retained_samples = sum(
        _nonnegative_int(binary[leaf_id].get("sample_count"))
        for leaf_id in binary_selected
        if isinstance(binary[leaf_id], Mapping)
    )

    active_entries = [
        ledger[leaf_id]
        for ledger in (binary, promoted)
        for leaf_id in selected
        if isinstance(ledger.get(leaf_id), Mapping)
    ]
    deferred_count = sum(
        1 for item in active_entries if item.get("disposition") == "DEFERRED"
    )
    unresolved_count = sum(
        1 for item in active_entries if item.get("disposition") == "UNRESOLVED"
    )
    rejected_count = sum(
        1 for item in active_entries if item.get("disposition") == "REJECTED"
    )

    evidence_counts = {level: 0 for level in _EVIDENCE_LEVELS}
    for leaf_id in selected:
        entry = evidence_ledger.get(leaf_id)
        if isinstance(entry, Mapping):
            level = entry.get("evidence_level")
            if level in evidence_counts:
                evidence_counts[str(level)] += 1

    resolutions = system_failure_resolution_index(value)
    system_failure_count = len(value["system_failures"])
    historical_system_failure_count = len(resolutions)
    active_system_failure_count = (
        system_failure_count - historical_system_failure_count
    )

    binary_rows = _rows_for_ledger(
        binary,
        selected,
        metadata,
        selected_count=selected_count,
        pending_by_leaf=pending_by_leaf,
        records=records,
        evidence_ledger=evidence_ledger,
        survey_pass="binary64",
    )
    promoted_rows = _rows_for_ledger(
        promoted,
        selected,
        metadata,
        selected_count=selected_count,
        pending_by_leaf={},
        records=records,
        evidence_ledger=evidence_ledger,
        survey_pass="promoted",
    )
    evidence_rows = tuple(
        _evidence_row_for(
            leaf_id,
            evidence_ledger[leaf_id],
            metadata.get(leaf_id, {}),
            selected_count=selected_count,
        )
        for leaf_id in _ordered_ids(selected, evidence_ledger, metadata)
        if isinstance(evidence_ledger.get(leaf_id), Mapping)
    )
    report_status = _report_status(value.get("report_status_receipt"))

    return Schema11DashboardSnapshot(
        selected_leaf_ids=selected,
        binary64_rows=binary_rows,
        promoted_rows=promoted_rows,
        evidence_rows=evidence_rows,
        endpoint_recovery_rows=_endpoint_recovery_rows(value, selected_set),
        selected_leaf_count=selected_count,
        binary64_processed_count=len(binary_selected),
        promoted_processed_count=len(promoted_selected),
        produced_count=produced_count,
        pending_count=pending_count,
        pending_by_minimum_tier=MappingProxyType(dict(pending_by_tier)),
        retained_binary64_sample_count=retained_samples,
        deferred_count=deferred_count,
        unresolved_count=unresolved_count,
        rejected_count=rejected_count,
        system_failure_count=system_failure_count,
        active_system_failure_count=active_system_failure_count,
        historical_system_failure_count=historical_system_failure_count,
        evidence_counts=MappingProxyType(dict(evidence_counts)),
        settled_leaf_ids=_unique_leaf_ids(
            row.leaf_id for row in (*binary_rows, *promoted_rows, *evidence_rows)
        ),
        report_status=MappingProxyType(dict(report_status)),
    )


def _endpoint_recovery_rows(
    checkpoint: Mapping[str, object], selected: set[str]
) -> tuple[Schema11EndpointRecoveryRow, ...]:
    rows: list[Schema11EndpointRecoveryRow] = []
    stage_ledger = checkpoint.get("promoted_stage_ledger")
    if not isinstance(stage_ledger, Mapping):
        return ()
    for bucket in stage_ledger.values():
        if not isinstance(bucket, Mapping):
            continue
        for leaf_id, stage in bucket.items():
            if leaf_id not in selected or not isinstance(stage, Mapping):
                continue
            stack: list[object] = [stage]
            while stack:
                item = stack.pop()
                if isinstance(item, Mapping):
                    receipts = item.get("endpoint_receipts")
                    aggregate = item.get("aggregate_limitation")
                    if isinstance(receipts, list) and isinstance(aggregate, str):
                        for receipt in receipts:
                            if not isinstance(receipt, Mapping):
                                continue
                            branch = receipt.get("endpoint_branch")
                            attempts = receipt.get("attempts")
                            if not isinstance(branch, str) or not isinstance(attempts, list):
                                continue
                            for attempt in attempts:
                                if not isinstance(attempt, Mapping):
                                    continue
                                order = attempt.get("attempted_endpoint_order")
                                geometry = attempt.get("attempted_geometry")
                                limitation = attempt.get("candidate_limitation")
                                intervention = attempt.get("selected_intervention")
                                result = attempt.get("result")
                                if (
                                    type(order) is int
                                    and all(isinstance(value, str) for value in (
                                        branch, geometry, limitation,
                                        intervention, result, aggregate,
                                    ))
                                ):
                                    rows.append(Schema11EndpointRecoveryRow(
                                        str(leaf_id), branch, order, geometry,
                                        limitation, intervention, result,
                                        aggregate,
                                    ))
                    stack.extend(item.values())
                elif isinstance(item, list):
                    stack.extend(item)
    # The same receipt may occur in a stage chain more than once. Preserve
    # causal order while projecting each exact row once.
    return tuple(dict.fromkeys(rows))


def _rows_for_ledger(
    ledger: Mapping[str, object],
    selected: Sequence[str],
    metadata: Mapping[str, Mapping[str, object]],
    *,
    selected_count: int,
    pending_by_leaf: Mapping[str, Mapping[str, object]],
    records: Mapping[str, Mapping[str, object]],
    evidence_ledger: Mapping[str, object],
    survey_pass: str,
) -> tuple[Schema11DashboardRow, ...]:
    return tuple(
        _row_for(
            leaf_id,
            ledger[leaf_id],
            metadata.get(leaf_id, {}),
            selected_count=selected_count,
            queue_entry=pending_by_leaf.get(leaf_id),
            record=records.get(leaf_id),
            evidence_entry=evidence_ledger.get(leaf_id),
            survey_pass=survey_pass,
        )
        for leaf_id in _ordered_ids(selected, ledger, metadata)
        if isinstance(ledger.get(leaf_id), Mapping)
    )


def _evidence_row_for(
    leaf_id: str,
    entry: Mapping[str, object],
    metadata: Mapping[str, object],
    *,
    selected_count: int,
) -> Schema11EvidenceRow:
    ordinal = metadata.get("leaf_ordinal")
    if not isinstance(ordinal, int):
        ordinal = None
    level = str(entry.get("evidence_level", "-"))
    return Schema11EvidenceRow(
        leaf_id=leaf_id,
        leaf_ordinal=ordinal,
        leaf_count=_nonnegative_int(metadata.get("leaf_count")) or selected_count,
        mode=metadata.get("mode", "-"),
        spin=metadata.get("spin_or_Mkappa", metadata.get("spin", "-")),
        mechanism=metadata.get("mechanism", metadata.get("mechanism_id", "-")),
        role=metadata.get("role", "-"),
        evidence_level=level,
        state=level,
    )


def _stable_selected_ids(values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError("selected_leaf_ids must be an iterable of leaf IDs")
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value:
            raise ValueError("selected_leaf_ids contains an invalid leaf ID")
        if value in seen:
            raise ValueError("selected_leaf_ids must not contain duplicates")
        seen.add(value)
        result.append(value)
    return tuple(result)


def _unique_leaf_ids(values: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for leaf_id in values:
        if leaf_id not in seen:
            seen.add(leaf_id)
            result.append(leaf_id)
    return tuple(result)


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _ordered_ids(
    selected: Sequence[str],
    ledger: Mapping[str, object],
    metadata: Mapping[str, Mapping[str, object]],
) -> tuple[str, ...]:
    position = {leaf_id: ordinal for ordinal, leaf_id in enumerate(selected)}

    def key(leaf_id: str) -> tuple[int, int, str]:
        item = metadata.get(leaf_id, {})
        ordinal = item.get("leaf_ordinal")
        if isinstance(ordinal, int) and ordinal >= 0:
            return (0, ordinal, leaf_id)
        return (1, position[leaf_id], leaf_id)

    return tuple(sorted((leaf_id for leaf_id in selected if leaf_id in ledger), key=key))


def _row_for(
    leaf_id: str,
    entry: Mapping[str, object],
    metadata: Mapping[str, object],
    *,
    selected_count: int,
    queue_entry: Mapping[str, object] | None,
    record: Mapping[str, object] | None,
    evidence_entry: Mapping[str, object] | None,
    survey_pass: str,
) -> Schema11DashboardRow:
    timing = _tier_seconds(entry)
    next_tier: str | None = None
    state = str(entry.get("disposition", "-"))
    if queue_entry is not None:
        next_tier = str(queue_entry.get("minimum_requested_tier", "-"))
        state = f"QUEUED->{next_tier}"
    ordinal = metadata.get("leaf_ordinal")
    if not isinstance(ordinal, int):
        ordinal = None
    evidence_level = "-"
    if isinstance(evidence_entry, Mapping):
        evidence_level = str(evidence_entry.get("evidence_level", "-"))
    return Schema11DashboardRow(
        leaf_id=leaf_id,
        leaf_ordinal=ordinal,
        leaf_count=_nonnegative_int(metadata.get("leaf_count")) or selected_count,
        mode=metadata.get("mode", "-"),
        spin=metadata.get("spin_or_Mkappa", metadata.get("spin", "-")),
        mechanism=metadata.get("mechanism", metadata.get("mechanism_id", "-")),
        role=metadata.get("role", "-"),
        time_seconds=(sum(timing.values()) if timing else None),
        sample_count=_nonnegative_int(entry.get("sample_count")),
        next_tier=next_tier,
        state=state,
        survey_pass=survey_pass,
        evidence_level=evidence_level,
        binary64_seconds=timing.get("binary64"),
        bf40_seconds=timing.get("BF40"),
        bf80_seconds=timing.get("BF80"),
        bf120_seconds=timing.get("BF120"),
        total_leaf_seconds=(sum(timing.values()) if timing else None),
        response_magnitude=(
            "-" if record is None else _record_response_magnitude(record)
        ),
        relative_error=("-" if record is None else _record_relative_error(record)),
    )


def _tier_seconds(entry: Mapping[str, object]) -> dict[str, float]:
    result: dict[str, float] = {}
    timing = entry.get("tier_timing")
    if not isinstance(timing, list):
        return result
    for item in timing:
        if not isinstance(item, Mapping):
            continue
        seconds = _optional_seconds(item.get("elapsed_seconds"))
        tier = item.get("tier")
        if seconds is None or not isinstance(tier, str):
            continue
        result[tier] = result.get(tier, 0.0) + seconds
    return result


def _nonnegative_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _optional_seconds(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if math.isfinite(number) and number >= 0:
        return number
    return None


def _record_response_magnitude(record: Mapping[str, object]) -> object:
    retained = record.get("retained_centre")
    if isinstance(retained, Mapping):
        try:
            return abs(
                complex(
                    float(retained["real"]),
                    float(retained.get("imaginary", retained.get("imag"))),
                )
            )
        except (KeyError, TypeError, ValueError, OverflowError):
            pass
    for container in (record.get("stages"),):
        if not isinstance(container, list):
            continue
        for stage in reversed(container):
            if not isinstance(stage, Mapping):
                continue
            disk = stage.get("response_disk")
            if isinstance(disk, Mapping) and isinstance(disk.get("centre"), Mapping):
                centre = disk["centre"]
                try:
                    return abs(
                        complex(
                            float(centre["real"]),
                            float(centre.get("imaginary", centre.get("imag"))),
                        )
                    )
                except (KeyError, TypeError, ValueError, OverflowError):
                    pass
    return "-"


def _record_relative_error(record: Mapping[str, object]) -> object:
    stages = record.get("stages")
    if isinstance(stages, list):
        for stage in reversed(stages):
            if not isinstance(stage, Mapping):
                continue
            disk = stage.get("response_disk")
            if isinstance(disk, Mapping):
                centre = disk.get("centre", record.get("retained_centre"))
                try:
                    if isinstance(centre, Mapping):
                        magnitude = abs(
                            complex(
                                float(centre["real"]),
                                float(
                                    centre.get("imaginary", centre.get("imag"))
                                ),
                            )
                        )
                        radius = float(disk["radius"])
                        if magnitude > 0 and math.isfinite(radius) and radius >= 0:
                            return radius / magnitude
                except (KeyError, TypeError, ValueError, OverflowError):
                    pass
    return "-"


def _report_status(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, object] = {}
    for name in ("basic", "projective", "triage"):
        item = value.get(name)
        result[name] = item.get("status", "UNKNOWN") if isinstance(item, Mapping) else "UNKNOWN"
    return result


__all__ = [
    "Schema11DashboardRow",
    "Schema11DashboardSnapshot",
    "Schema11EndpointRecoveryRow",
    "Schema11EvidenceRow",
    "project_schema11_dashboard",
]
