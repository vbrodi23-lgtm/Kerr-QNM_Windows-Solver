"""Cache-first entry points for schema-11 campaign survey passes."""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path
import tempfile
from typing import Callable, Mapping

from .campaign_policy import (
    SurveyDisposition,
    SurveyPass,
    add_numerical_record,
    empty_schema11_checkpoint,
    record_survey_disposition,
    validate_schema11_checkpoint,
)
from .campaign_recovery import RecoverySelection
from .contracts import canonical_json_bytes
from .solved_leaf_cache import (
    SolvedLeafLookupStatus,
    SolvedLeafStore,
)
from .response_engine import _EXTERIOR_PROFILE_IDS, _exterior_support


RecordValidator = Callable[[str, Mapping[str, object]], None]


@dataclass(frozen=True, slots=True)
class CacheFirstOutcome:
    cache_complete: bool
    cache_hit_count: int
    missing_leaf_ids: tuple[str, ...]
    checkpoint_path: str | None = None
    execution_result: object | None = None


def preflight_campaign_supports(
    plan: object, selected_leaf_ids: tuple[str, ...]
) -> None:
    """Validate every selected exterior support before any work is dispatched."""

    leaves = tuple(getattr(plan, "leaves"))
    leaf_by_id = {leaf.leaf_id: leaf for leaf in leaves}
    if len(leaf_by_id) != len(leaves):
        raise ValueError("campaign plan contains duplicate leaf identifiers")
    if len(set(selected_leaf_ids)) != len(selected_leaf_ids):
        raise ValueError("campaign selection contains duplicate leaf identifiers")
    unknown = tuple(
        leaf_id for leaf_id in selected_leaf_ids if leaf_id not in leaf_by_id
    )
    if unknown:
        raise ValueError(
            "campaign selection contains leaves outside the plan: "
            + ", ".join(unknown)
        )

    readout_radius = float(getattr(getattr(plan, "policy"), "readout_radius"))
    for leaf_id in selected_leaf_ids:
        leaf = leaf_by_id[leaf_id]
        if leaf.mechanism_id not in _EXTERIOR_PROFILE_IDS:
            continue
        spin = float(leaf.job.spin)
        horizon = 1.0 + math.sqrt(max(0.0, 1.0 - spin * spin))
        support = _exterior_support(spin, leaf.mechanism_id)
        gap = support.centre - horizon
        standoff = min(5.0e-4, gap / 4.0)
        if gap <= 0.0 or standoff <= 0.0 or support.half_width <= 0.0:
            raise ValueError(f"invalid exterior support for {leaf_id}")
        if support.lower != support.centre - support.half_width:
            raise ValueError(f"inconsistent exterior support lower bound for {leaf_id}")
        if support.upper != support.centre + support.half_width:
            raise ValueError(f"inconsistent exterior support upper bound for {leaf_id}")
        if support.lower < horizon + standoff:
            raise ValueError(f"exterior support violates horizon standoff for {leaf_id}")
        if support.upper >= readout_radius:
            raise ValueError(f"exterior support reaches the readout radius for {leaf_id}")


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


def dispatch_cache_first(
    selection: RecoverySelection,
    store: SolvedLeafStore,
    *,
    checkpoint_path: str | os.PathLike[str] | Path,
    backend_factory: Callable[[], object],
    execute_misses: Callable[[object], object],
    record_validator: RecordValidator | None = None,
) -> CacheFirstOutcome:
    """Return exact hits before constructing a backend; execute only on a miss."""

    records: dict[str, dict[str, object]] = {}
    missing: list[str] = []
    for leaf_id in selection.ordered_leaf_ids:
        lookup = store.lookup_readonly(
            selection.scientific_identities[leaf_id], leaf_id
        )
        if lookup.status is SolvedLeafLookupStatus.CORRUPT:
            raise ValueError(
                f"trusted solved-leaf cache receipt is corrupt: {lookup.path}: "
                f"{lookup.reason}"
            )
        if lookup.status is not SolvedLeafLookupStatus.HIT:
            missing.append(leaf_id)
            continue
        if lookup.receipt is None:
            raise ValueError("solved-leaf cache hit has no authenticated receipt")
        record = lookup.receipt["record"]
        if not isinstance(record, Mapping):
            raise ValueError("solved-leaf cache hit record is invalid")
        if record_validator is not None:
            record_validator(leaf_id, record)
        records[leaf_id] = dict(record)

    if missing:
        backend = backend_factory()
        execution_result = execute_misses(backend)
        return CacheFirstOutcome(
            cache_complete=False,
            cache_hit_count=len(records),
            missing_leaf_ids=tuple(missing),
            execution_result=execution_result,
        )

    checkpoint = empty_schema11_checkpoint(
        selection.campaign_id, selection.selection_id
    )
    for leaf_id in selection.ordered_leaf_ids:
        record = records[leaf_id]
        checkpoint = add_numerical_record(checkpoint, record)
        tiers = [str(stage.get("digits")) for stage in record["stages"]]
        checkpoint = record_survey_disposition(
            checkpoint,
            survey_pass=SurveyPass.BINARY64,
            leaf_id=leaf_id,
            disposition=SurveyDisposition.CACHE_REUSED,
            source_record_sha256=record["record_sha256"],
            result_record_sha256=record["record_sha256"],
            operation_identity="solved-leaf-cache/v1",
            precision_tiers=tiers,
            reason_code="EXACT_AUTHENTICATED_CACHE_HIT",
            sample_count=0,
            sample_limit=0,
            root_read_count=0,
            root_read_limit=0,
            worker_launch_count=0,
            worker_launch_limit=0,
            tier_timing=(),
            session_fragments=(),
        )
    checkpoint["state"] = "COMPLETE"
    validate_schema11_checkpoint(checkpoint)
    path = Path(checkpoint_path)
    if path.exists():
        raise ValueError("cache-first survey refuses to overwrite a checkpoint")
    _atomic_json(path, checkpoint)
    return CacheFirstOutcome(
        cache_complete=True,
        cache_hit_count=len(records),
        missing_leaf_ids=(),
        checkpoint_path=str(path),
    )


__all__ = [
    "CacheFirstOutcome",
    "dispatch_cache_first",
    "preflight_campaign_supports",
]
