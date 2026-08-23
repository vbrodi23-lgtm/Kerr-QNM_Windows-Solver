"""Cache-first entry points for schema-11 campaign survey passes."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import os
from pathlib import Path
import tempfile
from typing import Callable, Mapping

from .campaign_policy import (
    EvidenceLevel,
    PromotionQueueKind,
    SurveyDisposition,
    SurveyPass,
    add_numerical_record,
    append_promotion,
    empty_schema11_checkpoint,
    record_evidence,
    record_survey_disposition,
    validate_schema11_checkpoint,
)
from .campaign_recovery import RecoverySelection
from .campaign_failures import PROMOTION_ALLOWLIST, abort_unexpected_system_failure
from .contracts import canonical_json_bytes
from .solved_leaf_cache import (
    SolvedLeafLookupStatus,
    SolvedLeafStore,
)
from .response_engine import _EXTERIOR_PROFILE_IDS, _exterior_support
from .response_engine import (
    BINARY64_FIXED_ROOT_SURVEY_IDENTITY,
    BackgroundEquivalenceReceipt,
    Binary64FixedRootBatch,
    Binary64ReusedBackgroundBatch,
    Binary64SurveyDisposition,
    CanonicalExteriorBackground,
    build_exterior_background_reuse_key,
    canonical_background_from_binary64_batch,
    screen_binary64_fixed_root_batch,
    screen_binary64_reused_background_batch,
)


RecordValidator = Callable[[str, Mapping[str, object]], None]


@dataclass(frozen=True, slots=True)
class CacheFirstOutcome:
    cache_complete: bool
    cache_hit_count: int
    missing_leaf_ids: tuple[str, ...]
    checkpoint_path: str | None = None
    execution_result: object | None = None


@dataclass(frozen=True, slots=True)
class AuthenticatedRootSeal:
    fixed_root: complex
    branch_identity: str
    root_seal_sha256: str

    def __post_init__(self) -> None:
        root = complex(self.fixed_root)
        if not math.isfinite(root.real) or not math.isfinite(root.imag):
            raise ValueError("authenticated root seal root is invalid")
        object.__setattr__(self, "fixed_root", root)
        if not isinstance(self.branch_identity, str) or not self.branch_identity:
            raise ValueError("authenticated root seal branch is invalid")
        if (
            not isinstance(self.root_seal_sha256, str)
            or len(self.root_seal_sha256) != 64
        ):
            raise ValueError("authenticated root seal digest is invalid")
        try:
            int(self.root_seal_sha256, 16)
        except ValueError as error:
            raise ValueError("authenticated root seal digest is invalid") from error


@dataclass(frozen=True, slots=True)
class Binary64PassOutcome:
    disposition: SurveyDisposition
    operation_identity: str
    reason_code: str
    record: Mapping[str, object] | None = None
    stage_sha256: str | None = None
    queue_kind: PromotionQueueKind | None = None
    sample_count: int = 0
    sample_limit: int = 0
    root_read_count: int = 0
    root_read_limit: int = 0
    worker_launch_count: int = 0
    worker_launch_limit: int = 0
    evidence_receipts: tuple[Mapping[str, object], ...] = ()

    @classmethod
    def produced(
        cls,
        *,
        record: Mapping[str, object],
        stage_sha256: str,
        operation_identity: str,
        reason_code: str,
        sample_count: int = 0,
        sample_limit: int = 0,
        root_read_count: int = 0,
        root_read_limit: int = 0,
        worker_launch_count: int = 0,
        worker_launch_limit: int = 0,
        evidence_receipts: tuple[Mapping[str, object], ...] = (),
    ) -> "Binary64PassOutcome":
        return cls(
            disposition=SurveyDisposition.COMPLETED,
            operation_identity=operation_identity,
            reason_code=reason_code,
            record=record,
            stage_sha256=stage_sha256,
            sample_count=sample_count,
            sample_limit=sample_limit,
            root_read_count=root_read_count,
            root_read_limit=root_read_limit,
            worker_launch_count=worker_launch_count,
            worker_launch_limit=worker_launch_limit,
            evidence_receipts=evidence_receipts,
        )


@dataclass(frozen=True, slots=True)
class Binary64SurveyRun:
    checkpoint: dict[str, object]
    completed_count: int
    queued_count: int
    cache_reused_count: int
    skipped_count: int


def _record_pass_outcome(
    checkpoint: Mapping[str, object],
    *,
    selection: RecoverySelection,
    leaf_id: str,
    outcome: Binary64PassOutcome,
    root_seal_sha256: str | None,
) -> dict[str, object]:
    result = validate_schema11_checkpoint(checkpoint)
    record_sha256 = None
    if outcome.disposition is SurveyDisposition.COMPLETED:
        if outcome.record is None or outcome.stage_sha256 is None:
            raise ValueError("completed binary64 outcome lacks a numerical record")
        result = add_numerical_record(result, outcome.record)
        record_sha256 = str(outcome.record["record_sha256"])
        result = record_evidence(
            result,
            leaf_id=leaf_id,
            central_record_sha256=record_sha256,
            central_stage_sha256=outcome.stage_sha256,
            evidence_level=EvidenceLevel.SCREENED,
            receipts=outcome.evidence_receipts,
        )
    elif outcome.queue_kind is not None:
        result = append_promotion(
            result,
            leaf_id=leaf_id,
            queue_kind=outcome.queue_kind,
            reason_code=outcome.reason_code,
            minimum_requested_tier="BF40",
            scientific_computation_identity=(
                selection.scientific_identities[leaf_id]
            ),
            source_root_seal_sha256=root_seal_sha256,
        )
    result = record_survey_disposition(
        result,
        survey_pass=SurveyPass.BINARY64,
        leaf_id=leaf_id,
        disposition=outcome.disposition,
        source_record_sha256=None,
        result_record_sha256=record_sha256,
        operation_identity=outcome.operation_identity,
        precision_tiers=("binary64",),
        reason_code=outcome.reason_code,
        sample_count=outcome.sample_count,
        sample_limit=outcome.sample_limit,
        root_read_count=outcome.root_read_count,
        root_read_limit=outcome.root_read_limit,
        worker_launch_count=outcome.worker_launch_count,
        worker_launch_limit=outcome.worker_launch_limit,
        tier_timing=(),
        session_fragments=(),
    )
    return result


def run_binary64_survey(
    plan: object,
    selection: RecoverySelection,
    checkpoint: Mapping[str, object],
    *,
    checkpoint_path: str | os.PathLike[str] | Path,
    root_seal_lookup: Callable[[object], AuthenticatedRootSeal | None],
    native_backend_factory: Callable[[], object],
    horizon_runner: Callable[[object], Binary64PassOutcome],
    produced_record_builder: Callable[
        [object, object, object], tuple[Mapping[str, object], str]
    ],
    equivalence_receipt_lookup: Callable[
        [object, CanonicalExteriorBackground],
        BackgroundEquivalenceReceipt | None,
    ] | None = None,
    solved_leaf_store: SolvedLeafStore | None = None,
    record_validator: RecordValidator | None = None,
) -> Binary64SurveyRun:
    """Run only the binary64 pass; promotion is recorded and never executed."""

    result = validate_schema11_checkpoint(checkpoint)
    if (
        result["campaign_id"] != selection.campaign_id
        or result["selection_id"] != selection.selection_id
    ):
        raise ValueError("binary64 survey checkpoint identity mismatch")
    preflight_campaign_supports(plan, selection.ordered_leaf_ids)
    leaves = {leaf.leaf_id: leaf for leaf in getattr(plan, "leaves")}
    existing_records = {
        record["leaf_id"]: record for record in result["records"]
    }
    binary64_ledger = result["survey_pass_ledger"]["binary64"]
    backend = None
    backgrounds: dict[str, CanonicalExteriorBackground] = {}
    completed = queued = reused = skipped = 0
    path = Path(checkpoint_path)

    for leaf_id in selection.ordered_leaf_ids:
        leaf = leaves[leaf_id]
        if leaf_id in binary64_ledger:
            skipped += 1
            continue
        committed_before_leaf = result

        def guarded(action: Callable[[], object]) -> object:
            try:
                return action()
            except KeyboardInterrupt:
                raise
            except Exception as error:
                abort_unexpected_system_failure(
                    committed_before_leaf,
                    leaf_id=leaf_id,
                    error=error,
                    persist_checkpoint=lambda value: _atomic_json(path, value),
                )
                raise AssertionError("system failure abort returned unexpectedly")

        retained = existing_records.get(leaf_id)
        if retained is None and solved_leaf_store is not None:
            lookup = guarded(
                lambda: solved_leaf_store.lookup_readonly(
                    selection.scientific_identities[leaf_id], leaf_id
                )
            )
            assert hasattr(lookup, "status")
            if lookup.status is SolvedLeafLookupStatus.CORRUPT:
                guarded(
                    lambda: (_ for _ in ()).throw(ValueError(
                        "trusted solved-leaf cache receipt is corrupt: "
                        f"{lookup.path}: {lookup.reason}"
                    ))
                )
            if lookup.status is SolvedLeafLookupStatus.HIT:
                if lookup.receipt is None:
                    guarded(
                        lambda: (_ for _ in ()).throw(
                            ValueError("solved-leaf cache hit lacks a receipt")
                        )
                    )
                assert lookup.receipt is not None
                retained = lookup.receipt["record"]
                if not isinstance(retained, Mapping):
                    guarded(
                        lambda: (_ for _ in ()).throw(
                            ValueError("solved-leaf cache record is invalid")
                        )
                    )
                if record_validator is not None:
                    guarded(lambda: record_validator(leaf_id, retained))
                result = guarded(lambda: add_numerical_record(result, retained))
                assert isinstance(result, dict)
                existing_records[leaf_id] = retained
        if retained is not None:
            result = guarded(
                lambda: record_survey_disposition(
                    result,
                    survey_pass=SurveyPass.BINARY64,
                    leaf_id=leaf_id,
                    disposition=SurveyDisposition.CACHE_REUSED,
                    source_record_sha256=retained["record_sha256"],
                    result_record_sha256=retained["record_sha256"],
                    operation_identity="solved-leaf-cache/v1",
                    precision_tiers=tuple(
                        str(stage.get("digits", "retained"))
                        for stage in retained["stages"]
                    ),
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
            )
            assert isinstance(result, dict)
            reused += 1
            _atomic_json(path, result)
            binary64_ledger = result["survey_pass_ledger"]["binary64"]
            continue

        if leaf.mechanism_id == "horizon-admittance":
            outcome = guarded(lambda: horizon_runner(leaf))
            if not isinstance(outcome, Binary64PassOutcome):
                guarded(
                    lambda: (_ for _ in ()).throw(
                        ValueError("binary64 horizon runner returned an invalid outcome")
                    )
                )
            assert isinstance(outcome, Binary64PassOutcome)
            root_seal_sha256 = None
        else:
            seal = guarded(lambda: root_seal_lookup(leaf))
            if seal is None:
                outcome = Binary64PassOutcome(
                    disposition=SurveyDisposition.PROMOTION_PENDING_ROOT,
                    operation_identity=BINARY64_FIXED_ROOT_SURVEY_IDENTITY,
                    reason_code="ROOT_SEAL_UNAVAILABLE",
                    queue_kind=PromotionQueueKind.ROOT,
                )
                root_seal_sha256 = None
            else:
                if not isinstance(seal, AuthenticatedRootSeal):
                    guarded(
                        lambda: (_ for _ in ()).throw(
                            ValueError("root seal lookup returned an invalid value")
                        )
                    )
                assert isinstance(seal, AuthenticatedRootSeal)
                if seal.branch_identity != leaf.job.root.branch_id:
                    guarded(
                        lambda: (_ for _ in ()).throw(
                            ValueError("authenticated root seal branch mismatch")
                        )
                    )
                root_seal_sha256 = seal.root_seal_sha256
                reuse_key = guarded(
                    lambda: build_exterior_background_reuse_key(
                        leaf.job,
                        root_seal_sha256=seal.root_seal_sha256,
                        fixed_root=seal.fixed_root,
                    )
                )
                assert hasattr(reuse_key, "to_mapping")
                key_sha256 = hashlib.sha256(
                    canonical_json_bytes(reuse_key.to_mapping())
                ).hexdigest()
                background = backgrounds.get(key_sha256)
                receipt = guarded(lambda: (
                    None
                    if background is None or equivalence_receipt_lookup is None
                    else equivalence_receipt_lookup(leaf, background)
                ))
                if backend is None:
                    backend = guarded(native_backend_factory)
                batch = guarded(
                    lambda: backend.fixed_root_survey_with_optional_background(
                        job=leaf.job,
                        fixed_root=seal.fixed_root,
                        branch_identity=seal.branch_identity,
                        background=background,
                        equivalence_receipt=receipt,
                    )
                )
                if isinstance(batch, Binary64FixedRootBatch):
                    screening = guarded(
                        lambda: screen_binary64_fixed_root_batch(batch)
                    )
                    canonical = guarded(
                        lambda: canonical_background_from_binary64_batch(
                            batch, reuse_key
                        )
                    )
                    assert isinstance(canonical, CanonicalExteriorBackground)
                    backgrounds[key_sha256] = canonical
                elif isinstance(batch, Binary64ReusedBackgroundBatch):
                    if background is None:
                        guarded(
                            lambda: (_ for _ in ()).throw(
                                ValueError("reused batch lacks canonical background")
                            )
                        )
                    assert background is not None
                    screening = guarded(
                        lambda: screen_binary64_reused_background_batch(
                            background, batch
                        )
                    )
                else:
                    guarded(
                        lambda: (_ for _ in ()).throw(
                            ValueError(
                                "native binary64 backend returned an invalid batch"
                            )
                        )
                    )
                    raise AssertionError("invalid batch guard returned")
                evidence_receipts = ({
                    "schema": "windows-solver.binary64-screening/1",
                    "batch": batch.to_mapping(),
                },)
                if isinstance(batch, Binary64ReusedBackgroundBatch):
                    assert receipt is not None
                    evidence_receipts += (receipt.to_mapping(),)
                if screening.disposition is Binary64SurveyDisposition.PRODUCED:
                    built = guarded(
                        lambda: produced_record_builder(leaf, batch, screening)
                    )
                    if not isinstance(built, tuple) or len(built) != 2:
                        guarded(
                            lambda: (_ for _ in ()).throw(
                                ValueError("produced record builder returned invalid data")
                            )
                        )
                    record, stage_sha256 = built
                    outcome = Binary64PassOutcome.produced(
                        record=record,
                        stage_sha256=stage_sha256,
                        operation_identity=BINARY64_FIXED_ROOT_SURVEY_IDENTITY,
                        reason_code="BOUNDED_FIXED_ROOT_RESPONSE",
                        sample_count=batch.sample_count,
                        sample_limit=batch.sample_limit,
                        evidence_receipts=evidence_receipts,
                    )
                else:
                    reason_code = str(screening.reason_code)
                    queue_name = PROMOTION_ALLOWLIST.get(reason_code)
                    if queue_name is None:
                        guarded(
                            lambda: (_ for _ in ()).throw(
                                ValueError(
                                    "binary64 screening returned an unapproved "
                                    f"promotion reason: {reason_code}"
                                )
                            )
                        )
                        raise AssertionError("promotion guard returned")
                    queue_kind = PromotionQueueKind(queue_name)
                    outcome = Binary64PassOutcome(
                        disposition=(
                            SurveyDisposition.PROMOTION_PENDING_ROOT
                            if queue_kind is PromotionQueueKind.ROOT
                            else SurveyDisposition.PROMOTION_PENDING_RESPONSE
                        ),
                        operation_identity=BINARY64_FIXED_ROOT_SURVEY_IDENTITY,
                        reason_code=reason_code,
                        queue_kind=queue_kind,
                        sample_count=batch.sample_count,
                        sample_limit=batch.sample_limit,
                    )
        result = guarded(
            lambda: _record_pass_outcome(
                result,
                selection=selection,
                leaf_id=leaf_id,
                outcome=outcome,
                root_seal_sha256=root_seal_sha256,
            )
        )
        assert isinstance(result, dict)
        if outcome.disposition is SurveyDisposition.COMPLETED:
            completed += 1
            existing_records[leaf_id] = outcome.record
        elif outcome.queue_kind is not None:
            queued += 1
        _atomic_json(path, result)
        binary64_ledger = result["survey_pass_ledger"]["binary64"]

    return Binary64SurveyRun(
        checkpoint=validate_schema11_checkpoint(result),
        completed_count=completed,
        queued_count=queued,
        cache_reused_count=reused,
        skipped_count=skipped,
    )


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
    "AuthenticatedRootSeal",
    "Binary64PassOutcome",
    "Binary64SurveyRun",
    "CacheFirstOutcome",
    "dispatch_cache_first",
    "preflight_campaign_supports",
    "run_binary64_survey",
]
