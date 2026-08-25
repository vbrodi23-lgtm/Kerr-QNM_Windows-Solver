"""Cache-first entry points for schema-11 campaign survey passes."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import math
import os
from pathlib import Path
import tempfile
import time
from typing import Callable, Mapping
from uuid import uuid4

from .campaign_policy import (
    EvidenceLevel,
    PromotionQueueDisposition,
    PromotionQueueKind,
    SurveyDisposition,
    SurveyPass,
    add_numerical_record,
    append_promotion,
    empty_schema11_checkpoint,
    finish_promotion,
    record_evidence,
    record_survey_disposition,
    validate_schema11_checkpoint,
)
from .campaign_recovery import RecoverySelection
from .campaign_failures import (
    FailureDisposition,
    FailureReport,
    PROMOTION_ALLOWLIST,
    ProductionFailureMonitor,
    abort_unexpected_system_failure,
    classify_failure,
)
from .contracts import canonical_json_bytes
from .evidence_discovery import (
    EvidenceDiscovery,
    EvidenceDiscoveryStatus,
    EvidenceDiscoveryTotals,
)
from .campaign_timing import (
    CampaignTimingLog,
    TimingSessionRecorder,
    fold_timing_fragments,
)
from .solved_leaf_cache import (
    SolvedLeafLookupStatus,
    SolvedLeafStore,
)
from .response_engine import _EXTERIOR_PROFILE_IDS, _exterior_support
from .response_engine import (
    BINARY64_FIXED_ROOT_SAMPLE_ROLES,
    BINARY64_FIXED_ROOT_SURVEY_IDENTITY,
    BackgroundEquivalenceReceipt,
    Binary64FixedRootBatch,
    Binary64ReusedBackgroundBatch,
    Binary64SurveyDisposition,
    CanonicalExteriorBackground,
    EXTERIOR_PROVISIONAL_REUSE_RECEIPT_SCHEMA,
    build_exterior_background_reuse_key,
    build_exterior_provisional_stage,
    canonical_background_from_binary64_batch,
    combine_binary64_reused_background_batch,
    reviewed_determinant_error_claims_for_fixed_root_batch,
    screen_binary64_fixed_root_batch,
    screen_binary64_reused_background_batch,
    screen_promoted_fixed_root_samples,
)
from .reviewed_determinant_error import ReviewedDeterminantErrorStore
from .reviewed_determinant_error_issuance import (
    retain_uncalibrated_determinant_error_evidence,
)
from .background_evidence_store import CanonicalBackgroundEvidenceStore
from .julia_response_backend import (
    JuliaFixedRootSurveyBatch,
    JuliaNumericalControlError,
    JuliaODEResourceLimitError,
    JuliaResponseBackendError,
    JuliaRootReadoutResourceLimitError,
    consume_authenticated_binary64_provisional_predecessor,
)
from .progress import ProgressEventKind, emit_progress, progress_scope
from .root_evidence import RootDependencyKey
from .structural_diagnostics import StructuralDiagnosticSession


RecordValidator = Callable[[str, Mapping[str, object]], None]
_ROOT_PROMOTION_ARITHMETIC_TIER = "root-promotion"


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
    provisional_stage: Mapping[str, object] | None = None
    provisional_stage_sha256: str | None = None
    provisional_operation_identity: str | None = None
    queue_kind: PromotionQueueKind | None = None
    minimum_requested_tier: str = "BF40"
    sample_count: int = 0
    sample_limit: int = 0
    root_read_count: int = 0
    root_read_limit: int = 0
    worker_launch_count: int = 0
    worker_launch_limit: int = 0
    evidence_receipts: tuple[Mapping[str, object], ...] = ()
    tier_timing: tuple[Mapping[str, object], ...] = ()
    session_fragments: tuple[Mapping[str, object], ...] = ()

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
        tier_timing: tuple[Mapping[str, object], ...] = (),
        session_fragments: tuple[Mapping[str, object], ...] = (),
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
            tier_timing=tier_timing,
            session_fragments=session_fragments,
        )


@dataclass(frozen=True, slots=True)
class Binary64SurveyRun:
    checkpoint: dict[str, object]
    completed_count: int
    queued_count: int
    cache_reused_count: int
    skipped_count: int
    terminal_cache_discovery: EvidenceDiscoveryTotals = field(
        default_factory=EvidenceDiscoveryTotals
    )
    pass_exhausted: bool = True
    incomplete_leaf_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PromotedRootSolveResult:
    seal: AuthenticatedRootSeal
    precision_tier: str
    root_read_count: int = 1
    worker_launch_count: int = 1
    diagnostic_root_read_count: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.seal, AuthenticatedRootSeal):
            raise ValueError("promoted root result lacks an authenticated seal")
        if self.precision_tier not in {"BF40", "BF80"}:
            raise ValueError("promoted root result precision tier is invalid")
        if (
            self.root_read_count != 1
            or self.worker_launch_count != 1
            or self.diagnostic_root_read_count != 0
        ):
            raise ValueError("promoted root result violates the PRIMARY-only budget")


@dataclass(frozen=True, slots=True)
class PromotedPassOutcome:
    disposition: SurveyDisposition
    reason_code: str
    precision_tiers: tuple[str, ...]
    operation_identity: str = "promoted-survey-production/v1"
    record: Mapping[str, object] | None = None
    stage_sha256: str | None = None
    source_record_sha256: str | None = None
    source_stage_sha256: str | None = None
    sample_count: int = 0
    sample_limit: int = 18
    root_read_count: int = 0
    root_read_limit: int = 2
    worker_launch_count: int = 0
    worker_launch_limit: int = 3
    evidence_receipts: tuple[Mapping[str, object], ...] = ()
    tier_timing: tuple[Mapping[str, object], ...] = ()
    session_fragments: tuple[Mapping[str, object], ...] = ()


@dataclass(slots=True)
class _RootPromotionGroup:
    """One exact root dependency shared by pending ROOT queue entries."""

    dependency_key: RootDependencyKey
    canonical_primary_leaf_id: str
    member_leaf_ids: tuple[str, ...]
    root_solve_count: int = 0
    publication_count: int = 0
    attempted_tiers: set[str] = field(default_factory=set)
    seal: AuthenticatedRootSeal | None = None
    resolved_precision_tier: str | None = None
    terminal_outcome: PromotedPassOutcome | None = None
    status: str = "PENDING"

    def reuse(self, seal: AuthenticatedRootSeal) -> None:
        if self.seal is not None and self.seal != seal:
            raise ValueError("SYSTEM_FAILURE ROOT_SEAL_CONFLICT")
        self.seal = seal
        if self.status == "PENDING":
            self.status = "REUSED"

    def publish(self, seal: AuthenticatedRootSeal, tier: str) -> None:
        self.reuse(seal)
        self.publication_count += 1
        self.resolved_precision_tier = tier
        self.status = "RESOLVED"

    def fail(self, outcome: PromotedPassOutcome) -> None:
        if self.terminal_outcome is not None and self.terminal_outcome != outcome:
            raise ValueError("SYSTEM_FAILURE ROOT_PROMOTION_GROUP_CONFLICT")
        self.terminal_outcome = outcome
        self.status = outcome.disposition.value


@dataclass(frozen=True, slots=True)
class PromotedSurveyRun:
    checkpoint: dict[str, object]
    completed_count: int
    unresolved_count: int
    deferred_count: int
    rejected_count: int
    skipped_count: int
    cache_reused_count: int = 0
    terminal_cache_discovery: EvidenceDiscoveryTotals = field(
        default_factory=EvidenceDiscoveryTotals
    )
    pass_exhausted: bool = True
    incomplete_leaf_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PassExhaustion:
    exhausted: bool
    incomplete_leaf_ids: tuple[str, ...]
    reasons: tuple[str, ...]


def binary64_pass_exhaustion(
    checkpoint: Mapping[str, object], selection: RecoverySelection
) -> PassExhaustion:
    """Prove every selected leaf has one authenticated binary64 disposition."""

    value = validate_schema11_checkpoint(checkpoint)
    selected = tuple(selection.ordered_leaf_ids)
    selected_set = set(selected)
    ledger = value["survey_pass_ledger"]["binary64"]
    missing = tuple(leaf_id for leaf_id in selected if leaf_id not in ledger)
    unexpected = tuple(sorted(set(ledger) - selected_set))
    queue_by_leaf: dict[str, list[Mapping[str, object]]] = {}
    for entry in value["promotion_queue"]["entries"]:
        queue_by_leaf.setdefault(str(entry["leaf_id"]), []).append(entry)
    reasons: list[str] = []
    if missing:
        reasons.append("MISSING_SELECTED_BINARY64_DISPOSITION")
    if unexpected:
        reasons.append("OFF_SELECTION_BINARY64_DISPOSITION")
    for leaf_id in selected:
        entry = ledger.get(leaf_id)
        if not isinstance(entry, Mapping):
            continue
        disposition = entry["disposition"]
        expected_kind = {
            SurveyDisposition.PROMOTION_PENDING_ROOT.value: PromotionQueueKind.ROOT.value,
            SurveyDisposition.PROMOTION_PENDING_RESPONSE.value: PromotionQueueKind.RESPONSE.value,
        }.get(disposition)
        queues = queue_by_leaf.get(leaf_id, [])
        if expected_kind is None:
            if queues:
                reasons.append(f"CONTRADICTORY_PROMOTION_QUEUE:{leaf_id}")
        elif len(queues) != 1 or queues[0]["queue_kind"] != expected_kind:
            reasons.append(f"MISSING_OR_DUPLICATE_PROMOTION_QUEUE:{leaf_id}")
    incomplete = tuple(dict.fromkeys((*missing, *unexpected)))
    return PassExhaustion(not reasons, incomplete, tuple(reasons))


def _survey_failure_report(
    leaf: object,
    *,
    survey_pass: str,
    reason_code: str,
    operation_identity: str,
    precision_tier: str,
    disposition: SurveyDisposition,
) -> FailureReport:
    return FailureReport(
        failure_code=reason_code,
        failure_class=f"{survey_pass.upper()}_SURVEY_DISPOSITION",
        stage=survey_pass,
        worker_operation=operation_identity,
        request_schema="windows-solver.schema11-survey-pass/1",
        backend_identity=leaf.job.backend_identity.identity_sha256,
        policy_identity=leaf.job.policy.identity_sha256,
        precision_tier=precision_tier,
        cause_type=f"Reviewed{disposition.value.title().replace('_', '')}",
        diagnostics={"complete": True, "disposition": disposition.value},
    )


def promoted_pass_exhaustion(
    checkpoint: Mapping[str, object],
    selection: RecoverySelection,
    applicable_queue_ordinals: tuple[int, ...] | None = None,
) -> PassExhaustion:
    """Prove each applicable promotion is terminal or cache-superseded."""

    value = validate_schema11_checkpoint(checkpoint)
    selected = set(selection.ordered_leaf_ids)
    queue = value["promotion_queue"]["entries"]
    ordinals = (
        tuple(range(len(queue)))
        if applicable_queue_ordinals is None
        else applicable_queue_ordinals
    )
    ledger = value["survey_pass_ledger"]["promoted"]
    reasons: list[str] = []
    incomplete: list[str] = []
    expected_disposition = {
        PromotionQueueDisposition.COMPLETED.value: SurveyDisposition.COMPLETED.value,
        PromotionQueueDisposition.UNRESOLVED.value: SurveyDisposition.UNRESOLVED.value,
        PromotionQueueDisposition.DEFERRED.value: SurveyDisposition.DEFERRED.value,
        PromotionQueueDisposition.REJECTED.value: SurveyDisposition.REJECTED.value,
        PromotionQueueDisposition.SUPERSEDED_BY_CACHE.value: (
            SurveyDisposition.SUPERSEDED_BY_CACHE.value
        ),
    }
    for ordinal in ordinals:
        if ordinal < 0 or ordinal >= len(queue):
            reasons.append(f"MISSING_PROMOTION_ORDINAL:{ordinal}")
            continue
        item = queue[ordinal]
        leaf_id = str(item["leaf_id"])
        if leaf_id not in selected:
            reasons.append(f"OFF_SELECTION_PROMOTION:{leaf_id}")
            incomplete.append(leaf_id)
            continue
        disposition = str(item["disposition"])
        if disposition == PromotionQueueDisposition.PENDING.value:
            reasons.append(f"PENDING_PROMOTION:{leaf_id}")
            incomplete.append(leaf_id)
            continue
        pass_entry = ledger.get(leaf_id)
        if (
            not isinstance(pass_entry, Mapping)
            or pass_entry["disposition"] != expected_disposition.get(disposition)
        ):
            reasons.append(f"QUEUE_LEDGER_MISMATCH:{leaf_id}")
            incomplete.append(leaf_id)
    for item in queue:
        if (
            item["leaf_id"] in selected
            and item["disposition"] == PromotionQueueDisposition.PENDING.value
        ):
            leaf_id = str(item["leaf_id"])
            marker = f"PENDING_PROMOTION:{leaf_id}"
            if marker not in reasons:
                reasons.append(marker)
                incomplete.append(leaf_id)
    return PassExhaustion(
        not reasons, tuple(dict.fromkeys(incomplete)), tuple(reasons)
    )


def _record_pass_outcome(
    checkpoint: Mapping[str, object],
    *,
    selection: RecoverySelection,
    leaf_id: str,
    outcome: Binary64PassOutcome,
    root_seal_sha256: str | None,
    record_validator: RecordValidator | None = None,
) -> dict[str, object]:
    result = validate_schema11_checkpoint(checkpoint)
    if outcome.record is not None and outcome.stage_sha256 is None:
        raise ValueError("binary64 outcome record lacks its stage digest")
    if outcome.provisional_stage is not None:
        if (
            outcome.record is not None
            or outcome.queue_kind is not PromotionQueueKind.RESPONSE
            or outcome.provisional_stage_sha256 is None
            or outcome.provisional_operation_identity is None
        ):
            raise ValueError("binary64 provisional stage has an invalid owner")
        if not isinstance(outcome.provisional_stage, Mapping):
            raise ValueError("binary64 provisional stage is invalid")
        provisional_content = {
            key: item
            for key, item in outcome.provisional_stage.items()
            if key != "stage_sha256"
        }
        if (
            outcome.provisional_stage.get("stage_sha256")
            != outcome.provisional_stage_sha256
            or outcome.provisional_stage_sha256
            != hashlib.sha256(canonical_json_bytes(provisional_content)).hexdigest()
            or outcome.provisional_stage.get("operation_identity")
            != outcome.provisional_operation_identity
        ):
            raise ValueError("binary64 provisional stage authentication is invalid")
    elif (
        outcome.provisional_stage_sha256 is not None
        or outcome.provisional_operation_identity is not None
    ):
        raise ValueError("binary64 provisional stage metadata is incomplete")
    if outcome.disposition is SurveyDisposition.COMPLETED:
        if outcome.queue_kind is not None:
            raise ValueError("completed binary64 outcome cannot queue promotion")
        if outcome.record is None or outcome.stage_sha256 is None:
            raise ValueError("completed binary64 outcome lacks a numerical record")
    elif outcome.queue_kind is None and outcome.record is not None:
        raise ValueError("binary64 retained record lacks a promotion queue")
    if outcome.queue_kind is PromotionQueueKind.ROOT and outcome.record is not None:
        raise ValueError("root promotion cannot retain a binary64 response record")
    if (
        outcome.queue_kind is PromotionQueueKind.ROOT
        and outcome.provisional_stage is not None
    ):
        raise ValueError("root promotion cannot retain a provisional response stage")
    record_sha256 = None
    if outcome.record is not None:
        if record_validator is not None:
            record_validator(leaf_id, outcome.record)
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
        tier_timing=outcome.tier_timing,
        session_fragments=outcome.session_fragments,
    )
    if outcome.queue_kind is not None:
        binary64_entry = result["survey_pass_ledger"]["binary64"][leaf_id]
        source_stage_sha256 = (
            outcome.stage_sha256
            if outcome.stage_sha256 is not None
            else outcome.provisional_stage_sha256
        )
        result = append_promotion(
            result,
            leaf_id=leaf_id,
            queue_kind=outcome.queue_kind,
            reason_code=outcome.reason_code,
            minimum_requested_tier=outcome.minimum_requested_tier,
            scientific_computation_identity=(
                selection.scientific_identities[leaf_id]
            ),
            source_record_sha256=record_sha256,
            source_stage_sha256=source_stage_sha256,
            source_root_seal_sha256=root_seal_sha256,
            provisional_stage=outcome.provisional_stage,
            provisional_stage_sha256=outcome.provisional_stage_sha256,
            provisional_operation_identity=outcome.provisional_operation_identity,
            source_binary64_disposition_receipt_sha256=(
                binary64_entry["disposition_receipt_sha256"]
            ),
        )
    return result


def _checkpoint_terminal_discovery() -> EvidenceDiscovery:
    """Account for one authenticated terminal record already in schema-11 state."""

    return EvidenceDiscovery(
        status=EvidenceDiscoveryStatus.HIT,
        discovered_count=1,
        compatible_count=1,
        rejected_count=0,
    )


class TerminalCacheConflictError(ValueError):
    """Two authenticated exact terminal sources disagree for one request."""

    def __init__(self) -> None:
        self.discovery = EvidenceDiscovery(
            status=EvidenceDiscoveryStatus.CONFLICT,
            discovered_count=2,
            compatible_count=2,
            rejected_count=0,
        )
        super().__init__(
            "TERMINAL_CACHE_CONFLICT "
            + canonical_json_bytes(self.discovery.to_mapping()).decode("utf-8")
        )


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
    provisional_stage_committed: Callable[
        [object, Mapping[str, object]], None
    ],
    equivalence_receipt_lookup: Callable[
        [object, CanonicalExteriorBackground],
        BackgroundEquivalenceReceipt | None,
    ] | None = None,
    determinant_error_store: ReviewedDeterminantErrorStore | None = None,
    background_evidence_store: CanonicalBackgroundEvidenceStore | None = None,
    solved_leaf_store: SolvedLeafStore | None = None,
    record_validator: RecordValidator | None = None,
    timing_log: CampaignTimingLog | None = None,
    clock: Callable[[], float] = time.monotonic,
    session_id_factory: Callable[[], str] | None = None,
    checkpoint_committed: Callable[
        [Mapping[str, object]], Mapping[str, object]
    ] | None = None,
    terminal_record_committed: Callable[
        [object, Mapping[str, object]], None
    ] | None = None,
    diagnostic_session: StructuralDiagnosticSession | None = None,
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
    terminal_cache_discovery = EvidenceDiscoveryTotals()
    path = Path(checkpoint_path)
    operational_timing = timing_log or CampaignTimingLog(
        path.with_name(f"{path.name}.timing.jsonl")
    )
    make_session_id = session_id_factory or (lambda: uuid4().hex)
    failure_monitor = ProductionFailureMonitor(diagnostic_session=diagnostic_session)

    def persist(value: Mapping[str, object]) -> dict[str, object]:
        durable = validate_schema11_checkpoint(value)
        _atomic_json(path, durable)
        if checkpoint_committed is not None:
            durable = validate_schema11_checkpoint(checkpoint_committed(durable))
        return durable
    result = persist(result)
    cache_inventory = (
        None
        if solved_leaf_store is None
        else solved_leaf_store.discover_many(
            tuple(
                (selection.scientific_identities[leaf_id], leaf_id)
                for leaf_id in selection.ordered_leaf_ids
            )
        )
    )
    cache_reused_from_store = 0

    with progress_scope(execution_profile="SURVEY", survey_pass="binary64"):
        emit_progress(ProgressEventKind.CAMPAIGN_PASS_STARTED)

    for leaf_id in selection.ordered_leaf_ids:
        leaf = leaves[leaf_id]
        leaf_context = {
            "leaf_index": selection.ordered_leaf_ids.index(leaf_id) + 1,
            "leaf_count": len(selection.ordered_leaf_ids),
            "leaf_id": leaf_id,
            "role": leaf.role,
            "mode": {
                "ell": leaf.leaf.mode[0],
                "m": leaf.leaf.mode[1],
                "n": leaf.leaf.mode[2],
            },
            "spin": leaf.job.spin,
            "sampling_coordinate": leaf.job.sampling_coordinate.to_mapping(),
            "mechanism_id": leaf.mechanism_id,
            "execution_profile": "SURVEY",
            "survey_pass": "binary64",
            "precision_tier": "binary64",
        }
        if leaf_id in binary64_ledger:
            skipped += 1
            continue
        committed_before_leaf = result
        timing_recorder: TimingSessionRecorder | None = None
        with progress_scope(**leaf_context):
            emit_progress(ProgressEventKind.LEAF_PASS_STARTED)

        def guarded(action: Callable[[], object]) -> object:
            try:
                return action()
            except KeyboardInterrupt:
                raise
            except Exception as error:
                if (
                    timing_recorder is not None
                    and timing_recorder.active_tier is not None
                ):
                    timing_recorder.interrupt_tier()
                abort_unexpected_system_failure(
                    committed_before_leaf,
                    leaf_id=leaf_id,
                    error=error,
                    persist_checkpoint=lambda value: persist(value),
                )
                raise AssertionError("system failure abort returned unexpectedly")

        retained = existing_records.get(leaf_id)
        checkpoint_discovery = (
            None if retained is None else _checkpoint_terminal_discovery()
        )
        if retained is not None and record_validator is not None:
            guarded(lambda: record_validator(leaf_id, retained))
        cache_lookup = (
            None
            if cache_inventory is None
            else cache_inventory.lookup_for(selection.scientific_identities[leaf_id])
        )
        cache_record: Mapping[str, object] | None = None
        if cache_inventory is not None:
            if cache_inventory.source_error is not None:
                guarded(
                    lambda: (_ for _ in ()).throw(ValueError(
                        cache_inventory.source_error
                    ))
                )
            assert cache_lookup is not None
            if cache_lookup.status is SolvedLeafLookupStatus.CORRUPT:
                guarded(
                    lambda: (_ for _ in ()).throw(ValueError(
                        "trusted solved-leaf cache receipt is corrupt: "
                        f"{cache_lookup.path}: {cache_lookup.reason}"
                    ))
                )
            if cache_lookup.status is SolvedLeafLookupStatus.HIT:
                if cache_lookup.receipt is None:
                    guarded(
                        lambda: (_ for _ in ()).throw(
                            ValueError("solved-leaf cache hit lacks a receipt")
                        )
                    )
                assert cache_lookup.receipt is not None
                cache_record = cache_lookup.receipt.get("record")
                if not isinstance(cache_record, Mapping):
                    guarded(
                        lambda: (_ for _ in ()).throw(
                            ValueError("solved-leaf cache record is invalid")
                        )
                    )
                assert isinstance(cache_record, Mapping)
                if record_validator is not None:
                    guarded(lambda: record_validator(leaf_id, cache_record))
                if retained is not None and dict(retained) != dict(cache_record):
                    guarded(
                        lambda: (_ for _ in ()).throw(TerminalCacheConflictError())
                    )
                if retained is None:
                    retained = cache_record
                    result = guarded(lambda: add_numerical_record(result, retained))
                    assert isinstance(result, dict)
                    existing_records[leaf_id] = retained
                    cache_reused_from_store += 1
        if checkpoint_discovery is not None:
            terminal_cache_discovery = terminal_cache_discovery.add(
                checkpoint_discovery.with_reused(1)
            )
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
                    precision_tiers=_record_precision_tiers(retained),
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
            result = persist(result)
            with progress_scope(
                leaf_id=leaf_id,
                execution_profile="SURVEY",
                survey_pass="binary64",
                pass_disposition=SurveyDisposition.CACHE_REUSED.value,
                sample_count_used=0,
                sample_count_limit=0,
                root_read_count=0,
                root_read_limit=0,
                worker_launch_count=0,
                worker_launch_limit=0,
            ):
                emit_progress(ProgressEventKind.LEAF_PASS_DISPOSITION_RECORDED)
            binary64_ledger = result["survey_pass_ledger"]["binary64"]
            continue

        if leaf.mechanism_id == "horizon-admittance":
            seal = guarded(lambda: root_seal_lookup(leaf))
            if seal is None:
                outcome = Binary64PassOutcome(
                    disposition=SurveyDisposition.PROMOTION_PENDING_ROOT,
                    operation_identity="binary64-horizon-production/v2",
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
                timing_recorder = TimingSessionRecorder(
                    log=operational_timing,
                    session_id=make_session_id(),
                    leaf_id=leaf_id,
                    execution_profile="SURVEY",
                    survey_pass="binary64",
                    clock=clock,
                )
                timing_recorder.start_tier("binary64")
                with progress_scope(**leaf_context):
                    outcome = guarded(lambda: horizon_runner(leaf))
                if not isinstance(outcome, Binary64PassOutcome):
                    guarded(
                        lambda: (_ for _ in ()).throw(
                            ValueError("binary64 horizon runner returned an invalid outcome")
                        )
                    )
                assert isinstance(outcome, Binary64PassOutcome)
                timing_recorder.complete_tier()
                timing_summary = fold_timing_fragments(timing_recorder.fragments)
                outcome = replace(
                    outcome,
                    tier_timing=timing_summary.tier_timing_mappings(),
                    session_fragments=tuple(
                        fragment.to_mapping()
                        for fragment in timing_recorder.fragments
                    ),
                )
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
                issued_equivalence_receipts: tuple[
                    BackgroundEquivalenceReceipt, ...
                ] = ()
                if background_evidence_store is not None:
                    durable_background = guarded(
                        lambda: background_evidence_store.lookup(
                            leaf.job, reuse_key
                        )
                    )
                    background = durable_background.background
                    receipt = durable_background.receipt
                else:
                    background = backgrounds.get(key_sha256)
                    receipt = guarded(lambda: (
                        None
                        if background is None or equivalence_receipt_lookup is None
                        else equivalence_receipt_lookup(leaf, background)
                    ))
                if backend is None:
                    timing_recorder = TimingSessionRecorder(
                        log=operational_timing,
                        session_id=make_session_id(),
                        leaf_id=leaf_id,
                        execution_profile="SURVEY",
                        survey_pass="binary64",
                        clock=clock,
                    )
                    timing_recorder.start_tier("binary64")
                    backend = guarded(native_backend_factory)
                elif timing_recorder is None:
                    timing_recorder = TimingSessionRecorder(
                        log=operational_timing,
                        session_id=make_session_id(),
                        leaf_id=leaf_id,
                        execution_profile="SURVEY",
                        survey_pass="binary64",
                        clock=clock,
                    )
                    timing_recorder.start_tier("binary64")
                with progress_scope(**leaf_context):
                    batch = guarded(
                        lambda: backend.fixed_root_survey_with_optional_background(
                            job=leaf.job,
                            fixed_root=seal.fixed_root,
                            branch_identity=seal.branch_identity,
                            background=background,
                            equivalence_receipt=receipt,
                        )
                    )
                canonical_background: CanonicalExteriorBackground | None = None
                combined_batch: Binary64FixedRootBatch | None = None
                if isinstance(batch, Binary64FixedRootBatch):
                    canonical = guarded(
                        lambda: canonical_background_from_binary64_batch(
                            batch, reuse_key
                        )
                    )
                    assert isinstance(canonical, CanonicalExteriorBackground)
                    canonical_background = canonical
                    combined_batch = batch
                    if background_evidence_store is not None:
                        compatible_receipts: dict[
                            str, BackgroundEquivalenceReceipt
                        ] = {}
                        for candidate in leaves.values():
                            if candidate.mechanism_id not in _EXTERIOR_PROFILE_IDS:
                                continue
                            candidate_key = guarded(
                                lambda candidate=candidate: (
                                    build_exterior_background_reuse_key(
                                        candidate.job,
                                        root_seal_sha256=seal.root_seal_sha256,
                                        fixed_root=seal.fixed_root,
                                    )
                                )
                            )
                            if candidate_key != reuse_key:
                                continue
                            candidate_receipt = guarded(
                                lambda candidate=candidate: (
                                    BackgroundEquivalenceReceipt.issue(
                                        reuse_key=reuse_key,
                                        job=candidate.job,
                                        canonical_background_sha256=canonical.sha256,
                                        fixed_root=seal.fixed_root,
                                    )
                                )
                            )
                            prior = compatible_receipts.get(
                                candidate.mechanism_id
                            )
                            if prior is not None and prior != candidate_receipt:
                                guarded(lambda: (_ for _ in ()).throw(
                                    ValueError(
                                        "conflicting structural background proofs"
                                    )
                                ))
                            compatible_receipts[
                                candidate.mechanism_id
                            ] = candidate_receipt
                        issued_equivalence_receipts = tuple(
                            compatible_receipts.values()
                        )
                        guarded(
                            lambda: background_evidence_store.publish(
                                canonical, issued_equivalence_receipts
                            )
                        )
                    else:
                        backgrounds[key_sha256] = canonical
                    determinant_error_evidence = guarded(lambda: (
                        None
                        if determinant_error_store is None
                        else determinant_error_store.resolve_required(
                            reviewed_determinant_error_claims_for_fixed_root_batch(
                                leaf.job,
                                batch,
                                root_seal_sha256=seal.root_seal_sha256,
                                arithmetic_tier="binary64",
                                working_precision=53,
                            )
                        )
                    ))
                    screening = guarded(
                        lambda: screen_binary64_fixed_root_batch(
                            batch,
                            determinant_error_evidence=determinant_error_evidence,
                        )
                    )
                elif isinstance(batch, Binary64ReusedBackgroundBatch):
                    if background is None:
                        guarded(
                            lambda: (_ for _ in ()).throw(
                                ValueError("reused batch lacks canonical background")
                            )
                        )
                    assert background is not None
                    combined = guarded(
                        lambda: combine_binary64_reused_background_batch(
                            background, batch
                        )
                    )
                    assert isinstance(combined, Binary64FixedRootBatch)
                    canonical_background = background
                    combined_batch = combined
                    determinant_error_evidence = guarded(lambda: (
                        None
                        if determinant_error_store is None
                        else determinant_error_store.resolve_required(
                            reviewed_determinant_error_claims_for_fixed_root_batch(
                                leaf.job,
                                combined,
                                root_seal_sha256=seal.root_seal_sha256,
                                arithmetic_tier="binary64",
                                working_precision=53,
                            )
                        )
                    ))
                    screening = guarded(
                        lambda: screen_binary64_reused_background_batch(
                            background,
                            batch,
                            determinant_error_evidence=determinant_error_evidence,
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
                if canonical_background is None or combined_batch is None:
                    guarded(
                        lambda: (_ for _ in ()).throw(
                            ValueError("binary64 provisional background is missing")
                        )
                    )
                    raise AssertionError("missing provisional background guard returned")
                provisional_background_receipt = guarded(
                    lambda: BackgroundEquivalenceReceipt.issue(
                        reuse_key=reuse_key,
                        job=leaf.job,
                        canonical_background_sha256=canonical_background.sha256,
                        fixed_root=seal.fixed_root,
                    )
                )
                assert isinstance(
                    provisional_background_receipt, BackgroundEquivalenceReceipt
                )
                if (
                    isinstance(batch, Binary64ReusedBackgroundBatch)
                    and receipt is not None
                    and receipt != provisional_background_receipt
                ):
                    guarded(
                        lambda: (_ for _ in ()).throw(
                            ValueError(
                                "reused binary64 background receipt is incompatible"
                            )
                        )
                    )
                    raise AssertionError("incompatible background receipt guard returned")
                evidence_receipts = ({
                    "schema": "windows-solver.binary64-screening/1",
                    "batch": batch.to_mapping(),
                },)
                if isinstance(batch, Binary64ReusedBackgroundBatch):
                    assert receipt is not None
                    evidence_receipts += (receipt.to_mapping(),)
                if issued_equivalence_receipts:
                    evidence_receipts += tuple(
                        item.to_mapping()
                        for item in issued_equivalence_receipts
                    )
                if determinant_error_evidence is not None:
                    evidence_receipts += (
                        determinant_error_evidence.to_mappings()
                    )
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
                    provisional_stage = None
                    provisional_stage_sha256 = None
                    provisional_operation_identity = None
                    if queue_kind is PromotionQueueKind.RESPONSE:
                        provisional_stage, provisional_stage_sha256 = guarded(
                            lambda: build_exterior_provisional_stage(
                                job=leaf.job,
                                scientific_computation_identity=(
                                    selection.scientific_identities[leaf_id]
                                ),
                                root_seal_sha256=seal.root_seal_sha256,
                                raw_batch=batch,
                                combined_batch=combined_batch,
                                background=canonical_background,
                                background_receipt=provisional_background_receipt,
                                reason_code=reason_code,
                            )
                        )
                        provisional_operation_identity = (
                            "binary64-fixed-root-provisional/v1"
                        )
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
                        provisional_stage=provisional_stage,
                        provisional_stage_sha256=provisional_stage_sha256,
                        provisional_operation_identity=provisional_operation_identity,
                    )
                assert timing_recorder is not None
                timing_recorder.complete_tier()
                timing_summary = fold_timing_fragments(timing_recorder.fragments)
                outcome = replace(
                    outcome,
                    tier_timing=timing_summary.tier_timing_mappings(),
                    session_fragments=tuple(
                        fragment.to_mapping()
                        for fragment in timing_recorder.fragments
                    ),
                )
        result = guarded(
            lambda: _record_pass_outcome(
                result,
                selection=selection,
                leaf_id=leaf_id,
                outcome=outcome,
                root_seal_sha256=root_seal_sha256,
                record_validator=record_validator,
            )
        )
        assert isinstance(result, dict)
        result = persist(result)
        if outcome.provisional_stage is not None:
            try:
                provisional_stage_committed(leaf, outcome.provisional_stage)
            except KeyboardInterrupt:
                raise
            except Exception as error:
                # The provisional source stage is already durable in the
                # checkpoint.  A failed publication must preserve it and
                # fail closed against the current checkpoint.
                abort_unexpected_system_failure(
                    result,
                    leaf_id=leaf_id,
                    error=error,
                    persist_checkpoint=lambda value: persist(value),
                )
        if (
            outcome.record is not None
            and outcome.disposition is SurveyDisposition.COMPLETED
            and terminal_record_committed is not None
        ):
            try:
                terminal_record_committed(leaf, outcome.record)
            except KeyboardInterrupt:
                raise
            except Exception as error:
                # The numerical record is already durable.  Record the
                # publication/root-reuse failure against that current
                # checkpoint so recovery never rolls back the committed leaf.
                abort_unexpected_system_failure(
                    result,
                    leaf_id=leaf_id,
                    error=error,
                    persist_checkpoint=lambda value: persist(value),
                )
        if outcome.disposition is SurveyDisposition.COMPLETED:
            completed += 1
            existing_records[leaf_id] = outcome.record
        elif outcome.queue_kind is not None:
            queued += 1
            with progress_scope(
                leaf_id=leaf_id,
                execution_profile="SURVEY",
                survey_pass="binary64",
                pass_disposition=outcome.disposition.value,
                promotion_reason=outcome.reason_code,
                promotion_queue_count=queued,
            ):
                emit_progress(ProgressEventKind.PROMOTION_QUEUED)
        with progress_scope(
            leaf_id=leaf_id,
            execution_profile="SURVEY",
            survey_pass="binary64",
            pass_disposition=outcome.disposition.value,
            sample_count_used=outcome.sample_count,
            sample_count_limit=outcome.sample_limit,
            root_read_count=outcome.root_read_count,
            root_read_limit=outcome.root_read_limit,
            worker_launch_count=outcome.worker_launch_count,
            worker_launch_limit=outcome.worker_launch_limit,
            binary64_seconds=sum(
                item["elapsed_seconds"] for item in outcome.tier_timing
                if item["tier"] == "binary64"
            ),
            total_leaf_seconds=sum(
                item["elapsed_seconds"] for item in outcome.tier_timing
            ),
        ):
            emit_progress(ProgressEventKind.LEAF_PASS_DISPOSITION_RECORDED)
        binary64_ledger = result["survey_pass_ledger"]["binary64"]
        if outcome.disposition not in {
            SurveyDisposition.COMPLETED,
            SurveyDisposition.CACHE_REUSED,
        }:
            report = _survey_failure_report(
                leaf,
                survey_pass="binary64",
                reason_code=outcome.reason_code,
                operation_identity=outcome.operation_identity,
                precision_tier="binary64",
                disposition=outcome.disposition,
            )
            if (
                failure_monitor.observe_leaf_outcome(leaf_id, report).disposition
                is FailureDisposition.SYSTEM_FAILURE
            ):
                failure_monitor.observe_system_failure(
                    result,
                    leaf_id=leaf_id,
                    report=report,
                    persist_checkpoint=lambda value: persist(value),
                )

    exhaustion = binary64_pass_exhaustion(result, selection)
    with progress_scope(execution_profile="SURVEY", survey_pass="binary64"):
        emit_progress(
            (
                ProgressEventKind.CAMPAIGN_PASS_COMPLETED
                if exhaustion.exhausted
                else ProgressEventKind.CAMPAIGN_PASS_INTERRUPTED
            ),
            completed_count=completed,
            queued_count=queued,
            cache_reused_count=reused,
            skipped_count=skipped,
            incomplete_leaf_ids=list(exhaustion.incomplete_leaf_ids),
            incomplete_reasons=list(exhaustion.reasons),
        )
    if cache_inventory is not None:
        terminal_cache_discovery = terminal_cache_discovery.add(
            cache_inventory.discovery.with_reused(cache_reused_from_store)
        )
    return Binary64SurveyRun(
        checkpoint=validate_schema11_checkpoint(result),
        completed_count=completed,
        queued_count=queued,
        cache_reused_count=reused,
        skipped_count=skipped,
        terminal_cache_discovery=terminal_cache_discovery,
        pass_exhausted=exhaustion.exhausted,
        incomplete_leaf_ids=exhaustion.incomplete_leaf_ids,
    )


def _screening_receipt(screening: object) -> dict[str, object]:
    def disk(value: object) -> object:
        if value is None:
            return None
        return {
            "centre": {
                "real": value.centre.real,
                "imaginary": value.centre.imag,
            },
            "radius": value.radius,
        }

    return {
        "schema": "windows-solver.promoted-fixed-root-screening/1",
        "disposition": screening.disposition.value,
        "reason_code": screening.reason_code,
        "response_disk": disk(screening.response_disk),
        "frequency_derivative_disk": disk(
            screening.frequency_derivative_disk
        ),
        "coordinate_derivative_disk": disk(
            screening.coordinate_derivative_disk
        ),
        "root_correction_upper_bound": screening.root_correction_upper_bound,
        "determinant_certificate_status": screening.determinant_certificate_status,
    }


def _promoted_control_decision(
    error: Exception,
    *,
    leaf: object,
    digits: int,
) -> object | None:
    if isinstance(error, JuliaNumericalControlError):
        code = error.failure_code
    elif isinstance(error, JuliaODEResourceLimitError):
        code = "ODE_RESOURCE_LIMIT"
    elif isinstance(error, JuliaRootReadoutResourceLimitError):
        code = "ROOT_READOUT_RESOURCE_INFEASIBLE"
    else:
        return None
    worker = getattr(error, "worker_failure", {})
    structured = worker.get("failure", {}) if isinstance(worker, Mapping) else {}
    stage = (
        structured.get("stage", "fixed-root-response")
        if isinstance(structured, Mapping)
        else "fixed-root-response"
    )
    report = FailureReport(
        failure_code=code,
        failure_class="NUMERICAL_CONTROL",
        stage=str(stage),
        worker_operation="fixed-root-survey-batch",
        request_schema="windows-solver.fixed-root-survey-batch/1",
        backend_identity=str(leaf.job.backend_identity.identity_sha256),
        policy_identity=str(leaf.job.policy.identity_sha256),
        precision_tier=f"BF{digits}",
        cause_type=type(error).__name__,
        diagnostics={
            "schema": "windows-solver.promoted-control-failure/1",
            "complete": True,
            "worker_failure": dict(worker) if isinstance(worker, Mapping) else {},
        },
    )
    return classify_failure(report)


def _terminal_promoted_outcome(
    decision: object,
    *,
    tiers: tuple[str, ...],
    sample_count: int,
    root_read_count: int,
    worker_launch_count: int,
) -> PromotedPassOutcome:
    dispositions = {
        FailureDisposition.UNRESOLVED: SurveyDisposition.UNRESOLVED,
        FailureDisposition.DEFERRED: SurveyDisposition.DEFERRED,
        FailureDisposition.REJECTED: SurveyDisposition.REJECTED,
    }
    disposition = dispositions.get(decision.disposition)
    if disposition is None:
        raise JuliaResponseBackendError(
            f"promoted survey cannot contain {decision.failure_code}"
        )
    return PromotedPassOutcome(
        disposition=disposition,
        reason_code=decision.failure_code,
        precision_tiers=tiers,
        sample_count=sample_count,
        root_read_count=root_read_count,
        worker_launch_count=worker_launch_count,
    )


def _run_promoted_exterior_queue_entry(
    leaf: object,
    entry: Mapping[str, object],
    *,
    root_seal_lookup: Callable[
        [object, Mapping[str, object]], AuthenticatedRootSeal | None
    ],
    root_seal_publish: Callable[[object, AuthenticatedRootSeal], None],
    backend_factory: Callable[[object, int], object],
    primary_root_runner: Callable[
        [object, object, int], PromotedRootSolveResult
    ],
    produced_record_builder: Callable[
        [object, JuliaFixedRootSurveyBatch, object, int],
        tuple[Mapping[str, object], str],
    ],
    timing_recorder: TimingSessionRecorder,
    determinant_error_store: ReviewedDeterminantErrorStore | None,
    root_promotion_group: _RootPromotionGroup | None,
    provisional_predecessor_receipt: Mapping[str, object] | None,
) -> PromotedPassOutcome:
    queue_kind = PromotionQueueKind(entry["queue_kind"])
    seal = root_seal_lookup(leaf, entry)
    if queue_kind is PromotionQueueKind.RESPONSE:
        if not isinstance(seal, AuthenticatedRootSeal):
            raise ValueError("promoted response queue lacks its authenticated root seal")
        if seal.root_seal_sha256 != entry["source_root_seal_sha256"]:
            raise ValueError("promoted response root seal digest mismatch")
        if seal.branch_identity != leaf.job.root.branch_id:
            raise ValueError("promoted response root seal branch mismatch")
    elif root_promotion_group is not None:
        if seal is not None:
            root_promotion_group.reuse(seal)
        elif root_promotion_group.terminal_outcome is not None:
            return replace(
                root_promotion_group.terminal_outcome,
                root_read_count=0,
                worker_launch_count=0,
                tier_timing=(),
                session_fragments=(),
            )
        elif root_promotion_group.seal is not None:
            seal = root_promotion_group.seal

    tiers: list[str] = []
    receipts: list[Mapping[str, object]] = []
    if provisional_predecessor_receipt is not None:
        receipts.append(dict(provisional_predecessor_receipt))
    sample_count = root_reads = worker_launches = 0
    for digits in (40, 80):
        tier = f"BF{digits}"
        tiers.append(tier)
        timing_recorder.start_tier(tier)
        backend = backend_factory(leaf, digits)
        if seal is None:
            if (
                root_promotion_group is not None
                and tier in root_promotion_group.attempted_tiers
            ):
                timing_recorder.complete_tier()
                continue
            if root_promotion_group is not None:
                root_promotion_group.attempted_tiers.add(tier)
                root_promotion_group.root_solve_count += 1
            root_reads += 1
            worker_launches += 1
            try:
                root_result = primary_root_runner(leaf, backend, digits)
            except KeyboardInterrupt:
                raise
            except Exception as error:
                decision = _promoted_control_decision(
                    error, leaf=leaf, digits=digits
                )
                if decision is None or decision.disposition is FailureDisposition.SYSTEM_FAILURE:
                    raise
                if (
                    digits == 40
                    and decision.disposition is FailureDisposition.PROMOTION_PENDING
                    and decision.failure_code in PROMOTION_ALLOWLIST
                ):
                    timing_recorder.complete_tier()
                    continue
                if decision.disposition is FailureDisposition.PROMOTION_PENDING:
                    outcome = PromotedPassOutcome(
                        disposition=SurveyDisposition.UNRESOLVED,
                        reason_code=decision.failure_code,
                        precision_tiers=tuple(tiers),
                        sample_count=sample_count,
                        root_read_count=root_reads,
                        worker_launch_count=worker_launches,
                    )
                    if root_promotion_group is not None:
                        root_promotion_group.fail(outcome)
                    timing_recorder.complete_tier()
                    return outcome
                outcome = _terminal_promoted_outcome(
                    decision,
                    tiers=tuple(tiers),
                    sample_count=sample_count,
                    root_read_count=root_reads,
                    worker_launch_count=worker_launches,
                )
                if root_promotion_group is not None:
                    root_promotion_group.fail(outcome)
                timing_recorder.complete_tier()
                return outcome
            if not isinstance(root_result, PromotedRootSolveResult):
                raise ValueError("promoted PRIMARY runner returned an invalid result")
            if root_result.precision_tier != tier:
                raise ValueError("promoted PRIMARY result tier mismatch")
            seal = root_result.seal
            if seal.branch_identity != leaf.job.root.branch_id:
                raise ValueError("promoted PRIMARY root seal branch mismatch")
            root_seal_publish(leaf, seal)
            if root_promotion_group is not None:
                root_promotion_group.publish(seal, tier)

        worker_launches += 1
        try:
            batch = backend.fixed_root_survey_batch(
                leaf.job,
                fixed_root=seal.fixed_root,
                root_seal_sha256=seal.root_seal_sha256,
                branch_identity=seal.branch_identity,
                sample_roles=tuple(BINARY64_FIXED_ROOT_SAMPLE_ROLES),
            )
        except KeyboardInterrupt:
            raise
        except Exception as error:
            decision = _promoted_control_decision(
                error, leaf=leaf, digits=digits
            )
            if decision is None or decision.disposition is FailureDisposition.SYSTEM_FAILURE:
                raise
            if (
                digits == 40
                and decision.disposition is FailureDisposition.PROMOTION_PENDING
                and decision.failure_code in PROMOTION_ALLOWLIST
            ):
                timing_recorder.complete_tier()
                continue
            if decision.disposition is FailureDisposition.PROMOTION_PENDING:
                outcome = PromotedPassOutcome(
                    disposition=SurveyDisposition.UNRESOLVED,
                    reason_code=decision.failure_code,
                    precision_tiers=tuple(tiers),
                    sample_count=sample_count,
                    root_read_count=root_reads,
                    worker_launch_count=worker_launches,
                )
                timing_recorder.complete_tier()
                return outcome
            outcome = _terminal_promoted_outcome(
                decision,
                tiers=tuple(tiers),
                sample_count=sample_count,
                root_read_count=root_reads,
                worker_launch_count=worker_launches,
            )
            timing_recorder.complete_tier()
            return outcome
        if not isinstance(batch, JuliaFixedRootSurveyBatch):
            raise ValueError("promoted backend returned an invalid survey batch")
        if (
            batch.precision_tier.value != f"bigfloat-{digits}"
            or batch.root_seal_sha256 != seal.root_seal_sha256
            or batch.root_read_count != 0
            or batch.julia_launch_count != 1
        ):
            raise ValueError("promoted fixed-root survey batch budget mismatch")
        sample_count += batch.sample_count
        if determinant_error_store is not None:
            retain_uncalibrated_determinant_error_evidence(
                determinant_error_store,
                leaf.job,
                batch,
                root_seal_sha256=seal.root_seal_sha256,
            )
        determinant_error_evidence = (
            None
            if determinant_error_store is None
            else determinant_error_store.resolve_required(
                reviewed_determinant_error_claims_for_fixed_root_batch(
                    leaf.job,
                    batch,
                    root_seal_sha256=seal.root_seal_sha256,
                    arithmetic_tier=batch.precision_tier.value,
                    working_precision=batch.working_precision_bits,
                )
            )
        )
        screening = screen_promoted_fixed_root_samples(
            batch.samples,
            frequency_step=batch.frequency_step,
            coordinate_step=batch.coordinate_step,
            determinant_error_evidence=determinant_error_evidence,
        )
        receipts.append({
            "schema": "windows-solver.promoted-fixed-root-batch-receipt/1",
            "batch": batch.to_mapping(),
            "screening": _screening_receipt(screening),
        })
        if determinant_error_evidence is not None:
            receipts.extend(determinant_error_evidence.to_mappings())
        if screening.disposition is Binary64SurveyDisposition.PRODUCED:
            built = produced_record_builder(leaf, batch, screening, digits)
            if not isinstance(built, tuple) or len(built) != 2:
                raise ValueError("promoted record builder returned invalid data")
            record, stage_sha256 = built
            outcome = PromotedPassOutcome(
                disposition=SurveyDisposition.COMPLETED,
                reason_code="BOUNDED_PROMOTED_FIXED_ROOT_RESPONSE",
                precision_tiers=tuple(tiers),
                record=record,
                stage_sha256=stage_sha256,
                sample_count=sample_count,
                root_read_count=root_reads,
                worker_launch_count=worker_launches,
                evidence_receipts=tuple(receipts),
            )
            timing_recorder.complete_tier()
            return outcome
        reason = str(screening.reason_code)
        if reason not in PROMOTION_ALLOWLIST:
            raise ValueError(
                f"promoted screening returned an unknown reason: {reason}"
            )
        if digits == 40:
            timing_recorder.complete_tier()
            continue
        outcome = PromotedPassOutcome(
            disposition=SurveyDisposition.UNRESOLVED,
            reason_code=reason,
            precision_tiers=tuple(tiers),
            sample_count=sample_count,
            root_read_count=root_reads,
            worker_launch_count=worker_launches,
            evidence_receipts=tuple(receipts),
        )
        timing_recorder.complete_tier()
        return outcome
    raise AssertionError("promoted survey precision ladder did not terminate")


def _commit_promoted_outcome(
    checkpoint: Mapping[str, object],
    *,
    leaf_id: str,
    queue_ordinal: int,
    queue_kind: PromotionQueueKind,
    outcome: PromotedPassOutcome,
    record_validator: RecordValidator | None = None,
) -> dict[str, object]:
    result = validate_schema11_checkpoint(checkpoint)
    record_sha256 = None
    if outcome.record is not None:
        if outcome.stage_sha256 is None:
            raise ValueError("promoted outcome record lacks its stage digest")
        if outcome.source_record_sha256 is not None:
            raise ValueError("promoted outcome has both a new and source record")
        if record_validator is not None:
            record_validator(leaf_id, outcome.record)
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
    elif outcome.source_record_sha256 is not None:
        if outcome.source_stage_sha256 is None:
            raise ValueError("promoted comparison lacks its source stage digest")
        retained = next(
            (
                item for item in result["records"]
                if item.get("leaf_id") == leaf_id
            ),
            None,
        )
        if (
            not isinstance(retained, Mapping)
            or retained.get("record_sha256") != outcome.source_record_sha256
        ):
            raise ValueError("promoted comparison source record is not retained")
        record_sha256 = outcome.source_record_sha256
        if outcome.evidence_receipts:
            result = record_evidence(
                result,
                leaf_id=leaf_id,
                central_record_sha256=record_sha256,
                central_stage_sha256=outcome.source_stage_sha256,
                evidence_level=EvidenceLevel.SCREENED,
                receipts=outcome.evidence_receipts,
                discrepancy_codes=(
                    ()
                    if outcome.disposition is SurveyDisposition.COMPLETED
                    else (outcome.reason_code,)
                ),
            )
    elif outcome.disposition is SurveyDisposition.COMPLETED:
        raise ValueError("completed promoted outcome lacks a record or source record")
    queue_dispositions = {
        SurveyDisposition.COMPLETED: PromotionQueueDisposition.COMPLETED,
        SurveyDisposition.UNRESOLVED: PromotionQueueDisposition.UNRESOLVED,
        SurveyDisposition.DEFERRED: PromotionQueueDisposition.DEFERRED,
        SurveyDisposition.REJECTED: PromotionQueueDisposition.REJECTED,
    }
    queue_disposition = queue_dispositions.get(outcome.disposition)
    if queue_disposition is None:
        raise ValueError("promoted outcome is not terminal")
    provisional_reuse_receipt = next(
        (
            receipt
            for receipt in outcome.evidence_receipts
            if isinstance(receipt, Mapping)
            and receipt.get("schema") == EXTERIOR_PROVISIONAL_REUSE_RECEIPT_SCHEMA
        ),
        None,
    )
    result = finish_promotion(
        result,
        queue_ordinal=queue_ordinal,
        disposition=queue_disposition,
        disposition_receipt={
            "schema": "windows-solver.promoted-queue-disposition/1",
            "leaf_id": leaf_id,
            "queue_ordinal": queue_ordinal,
            "disposition": outcome.disposition.value,
            "reason_code": outcome.reason_code,
            "precision_tiers": list(outcome.precision_tiers),
            "result_record_sha256": record_sha256,
            "source_record_sha256": outcome.source_record_sha256,
            "evidence_receipt_sha256s": [
                receipt["receipt_sha256"]
                for receipt in outcome.evidence_receipts
                if isinstance(receipt, Mapping)
                and isinstance(receipt.get("receipt_sha256"), str)
            ],
        },
        provisional_reuse_receipt=provisional_reuse_receipt,
    )
    result = record_survey_disposition(
        result,
        survey_pass=SurveyPass.PROMOTED,
        leaf_id=leaf_id,
        disposition=outcome.disposition,
        source_record_sha256=outcome.source_record_sha256,
        result_record_sha256=record_sha256,
        operation_identity=outcome.operation_identity,
        precision_tiers=outcome.precision_tiers,
        reason_code=outcome.reason_code,
        sample_count=outcome.sample_count,
        sample_limit=outcome.sample_limit,
        root_read_count=outcome.root_read_count,
        root_read_limit=(
            outcome.root_read_limit
            if (
                queue_kind is not PromotionQueueKind.RESPONSE
                or outcome.operation_identity.startswith("promoted-horizon-")
            )
            else 0
        ),
        worker_launch_count=outcome.worker_launch_count,
        worker_launch_limit=(
            2
            if queue_kind is PromotionQueueKind.RESPONSE
            else outcome.worker_launch_limit
        ),
        tier_timing=outcome.tier_timing,
        session_fragments=outcome.session_fragments,
    )
    return result


def _record_precision_tiers(record: Mapping[str, object]) -> tuple[str, ...]:
    """Preserve the terminal record's actual precision labels in a cache receipt."""

    stages = record.get("stages")
    if not isinstance(stages, list) or not stages:
        raise ValueError("terminal cache record stages are invalid")
    tiers: list[str] = []
    for stage in stages:
        if not isinstance(stage, Mapping):
            raise ValueError("terminal cache record stage is invalid")
        value = stage.get("precision_tier", stage.get("digits"))
        if value is None:
            raise ValueError("terminal cache record precision is invalid")
        tiers.append(str(value))
    return tuple(tiers)


def _commit_promoted_cache_reuse(
    checkpoint: Mapping[str, object],
    *,
    leaf_id: str,
    queue_ordinal: int,
    record: Mapping[str, object],
) -> dict[str, object]:
    """Supersede a stale promotion with exact authenticated terminal evidence."""

    record_sha256 = record.get("record_sha256")
    if not isinstance(record_sha256, str):
        raise ValueError("terminal cache record digest is invalid")
    result = finish_promotion(
        checkpoint,
        queue_ordinal=queue_ordinal,
        disposition=PromotionQueueDisposition.SUPERSEDED_BY_CACHE,
        disposition_receipt={
            "schema": "windows-solver.promoted-cache-supersession/v1",
            "leaf_id": leaf_id,
            "queue_ordinal": queue_ordinal,
            "source_record_sha256": record_sha256,
            "result_record_sha256": record_sha256,
            "reason_code": "EXACT_AUTHENTICATED_CACHE_HIT",
        },
    )
    return record_survey_disposition(
        result,
        survey_pass=SurveyPass.PROMOTED,
        leaf_id=leaf_id,
        disposition=SurveyDisposition.SUPERSEDED_BY_CACHE,
        source_record_sha256=record_sha256,
        result_record_sha256=record_sha256,
        operation_identity="solved-leaf-cache/v1",
        precision_tiers=_record_precision_tiers(record),
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


def run_promoted_survey(
    plan: object,
    selection: RecoverySelection,
    checkpoint: Mapping[str, object],
    *,
    checkpoint_path: str | os.PathLike[str] | Path,
    root_seal_lookup: Callable[
        [object, Mapping[str, object]], AuthenticatedRootSeal | None
    ],
    provisional_stage_lookup: Callable[
        [object, Mapping[str, object]], Mapping[str, object] | None
    ],
    backend_factory: Callable[[object, int], object],
    primary_root_runner: Callable[
        [object, object, int], PromotedRootSolveResult
    ],
    horizon_runner: Callable[[object], PromotedPassOutcome],
    promoted_horizon_runner: Callable[
        [object, Mapping[str, object], Mapping[str, object] | None,
         tuple[Mapping[str, object], ...]],
        PromotedPassOutcome,
    ] | None = None,
    produced_record_builder: Callable[
        [object, JuliaFixedRootSurveyBatch, object, int],
        tuple[Mapping[str, object], str],
    ],
    root_seal_publish: Callable[
        [object, AuthenticatedRootSeal], None
    ],
    determinant_error_store: ReviewedDeterminantErrorStore | None = None,
    solved_leaf_store: SolvedLeafStore | None = None,
    record_validator: RecordValidator | None = None,
    timing_log: CampaignTimingLog | None = None,
    clock: Callable[[], float] = time.monotonic,
    session_id_factory: Callable[[], str] | None = None,
    checkpoint_committed: Callable[
        [Mapping[str, object]], Mapping[str, object]
    ] | None = None,
    terminal_record_committed: Callable[
        [object, Mapping[str, object]], None
    ] | None = None,
    diagnostic_session: StructuralDiagnosticSession | None = None,
) -> PromotedSurveyRun:
    """Consume only pending promotion entries through BF40/BF80 survey work."""

    result = validate_schema11_checkpoint(checkpoint)
    if (
        result["campaign_id"] != selection.campaign_id
        or result["selection_id"] != selection.selection_id
    ):
        raise ValueError("promoted survey checkpoint identity mismatch")
    preflight_campaign_supports(plan, selection.ordered_leaf_ids)
    leaves = {leaf.leaf_id: leaf for leaf in getattr(plan, "leaves")}
    path = Path(checkpoint_path)
    operational_timing = timing_log or CampaignTimingLog(
        path.with_name(f"{path.name}.timing.jsonl")
    )
    make_session_id = session_id_factory or (lambda: uuid4().hex)
    failure_monitor = ProductionFailureMonitor(diagnostic_session=diagnostic_session)

    def persist(value: Mapping[str, object]) -> dict[str, object]:
        durable = validate_schema11_checkpoint(value)
        _atomic_json(path, durable)
        if checkpoint_committed is not None:
            durable = validate_schema11_checkpoint(checkpoint_committed(durable))
        return durable


    result = persist(result)
    existing_records = {
        record["leaf_id"]: record for record in result["records"]
    }
    completed = unresolved = deferred = rejected = skipped = cache_reused = 0
    terminal_cache_discovery = EvidenceDiscoveryTotals()
    cache_inventory = (
        None
        if solved_leaf_store is None
        else solved_leaf_store.discover_many(
            tuple(
                (selection.scientific_identities[leaf_id], leaf_id)
                for leaf_id in selection.ordered_leaf_ids
            )
        )
    )
    cache_reused_from_store = 0
    with progress_scope(execution_profile="SURVEY", survey_pass="promoted"):
        emit_progress(ProgressEventKind.CAMPAIGN_PASS_STARTED)
    entries = tuple(result["promotion_queue"]["entries"])
    applicable_queue_ordinals = tuple(
        int(item["queue_ordinal"])
        for item in entries
        if item["disposition"] == PromotionQueueDisposition.PENDING.value
    )
    root_group_members: dict[str, tuple[RootDependencyKey, set[str]]] = {}
    for snapshot in entries:
        if (
            snapshot["disposition"] != PromotionQueueDisposition.PENDING.value
            or snapshot["queue_kind"] != PromotionQueueKind.ROOT.value
        ):
            continue
        leaf_id = str(snapshot["leaf_id"])
        if leaf_id not in selection.scientific_identities or leaf_id not in leaves:
            continue
        key = RootDependencyKey.from_leaf(
            leaves[leaf_id], arithmetic_tier=_ROOT_PROMOTION_ARITHMETIC_TIER
        )
        existing = root_group_members.get(key.sha256)
        if existing is None:
            root_group_members[key.sha256] = (key, {leaf_id})
        else:
            existing[1].add(leaf_id)
    root_promotion_groups = {
        digest: _RootPromotionGroup(
            dependency_key=key,
            canonical_primary_leaf_id=next(
                leaf_id
                for leaf_id in selection.ordered_leaf_ids
                if leaf_id in members
            ),
            member_leaf_ids=tuple(
                leaf_id
                for leaf_id in selection.ordered_leaf_ids
                if leaf_id in members
            ),
        )
        for digest, (key, members) in root_group_members.items()
    }
    for snapshot in entries:
        ordinal = int(snapshot["queue_ordinal"])
        if snapshot["disposition"] != PromotionQueueDisposition.PENDING.value:
            skipped += 1
            continue
        leaf_id = str(snapshot["leaf_id"])
        if leaf_id not in selection.scientific_identities or leaf_id not in leaves:
            raise ValueError("promoted queue leaf is outside the selection")
        if (
            snapshot["scientific_computation_identity"]
            != selection.scientific_identities[leaf_id]
        ):
            raise ValueError("promoted queue scientific identity mismatch")
        if leaf_id in result["survey_pass_ledger"]["promoted"]:
            raise ValueError("pending promotion already has a pass disposition")
        leaf = leaves[leaf_id]
        root_promotion_group = None
        if snapshot["queue_kind"] == PromotionQueueKind.ROOT.value:
            key = RootDependencyKey.from_leaf(
                leaf, arithmetic_tier=_ROOT_PROMOTION_ARITHMETIC_TIER
            )
            root_promotion_group = root_promotion_groups.get(key.sha256)
            if root_promotion_group is None:
                raise ValueError("root promotion group is missing")
        leaf_context = {
            "leaf_index": selection.ordered_leaf_ids.index(leaf_id) + 1,
            "leaf_count": len(selection.ordered_leaf_ids),
            "leaf_id": leaf_id,
            "role": leaf.role,
            "mode": {
                "ell": leaf.leaf.mode[0],
                "m": leaf.leaf.mode[1],
                "n": leaf.leaf.mode[2],
            },
            "spin": leaf.job.spin,
            "sampling_coordinate": leaf.job.sampling_coordinate.to_mapping(),
            "mechanism_id": leaf.mechanism_id,
            "execution_profile": "SURVEY",
            "survey_pass": "promoted",
        }
        committed_before_leaf = result
        with progress_scope(**leaf_context):
            emit_progress(ProgressEventKind.LEAF_PASS_STARTED)

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
                    persist_checkpoint=lambda value: persist(value),
                )
                raise AssertionError("system failure abort returned unexpectedly")

        def validate_binary64_disposition_binding() -> None:
            supplied_receipt = snapshot.get(
                "source_binary64_disposition_receipt_sha256"
            )
            provisional_stage = snapshot.get("provisional_stage")
            if supplied_receipt is None:
                if provisional_stage is not None:
                    raise ValueError(
                        "provisional horizon promotion lacks binary64 disposition receipt"
                    )
                return
            binary64_ledger = result["survey_pass_ledger"]["binary64"]
            binary64_entry = (
                binary64_ledger.get(leaf_id)
                if isinstance(binary64_ledger, Mapping)
                else None
            )
            expected_receipt = (
                binary64_entry.get("disposition_receipt_sha256")
                if isinstance(binary64_entry, Mapping)
                else None
            )
            if (
                not isinstance(expected_receipt, str)
                or supplied_receipt != expected_receipt
            ):
                raise ValueError(
                    "horizon promotion binary64 disposition receipt mismatch"
                )

        guarded(validate_binary64_disposition_binding)

        provisional_predecessor_receipt: Mapping[str, object] | None = None
        if (
            leaf.mechanism_id != "horizon-admittance"
            and snapshot["queue_kind"] == PromotionQueueKind.RESPONSE.value
            and snapshot.get("source_record_sha256") is None
        ):
            provisional_stage = guarded(
                lambda: provisional_stage_lookup(leaf, snapshot)
            )
            if not isinstance(provisional_stage, Mapping):
                guarded(
                    lambda: (_ for _ in ()).throw(
                        ValueError(
                            "exterior RESPONSE promotion lacks a provisional stage"
                        )
                    )
                )
                raise AssertionError("missing provisional stage guard returned")
            source_root_seal_sha256 = snapshot.get("source_root_seal_sha256")
            if not isinstance(source_root_seal_sha256, str):
                guarded(
                    lambda: (_ for _ in ()).throw(
                        ValueError(
                            "exterior provisional promotion lacks a root seal"
                        )
                    )
                )
                raise AssertionError("missing provisional root guard returned")
            provisional_predecessor_receipt = guarded(
                lambda: consume_authenticated_binary64_provisional_predecessor(
                    provisional_stage,
                    job=leaf.job,
                    scientific_computation_identity=(
                        selection.scientific_identities[leaf_id]
                    ),
                    root_seal_sha256=source_root_seal_sha256,
                )
            )
            assert isinstance(provisional_predecessor_receipt, Mapping)

        retained = existing_records.get(leaf_id)
        horizon_source_record = (
            leaf.mechanism_id == "horizon-admittance"
            and snapshot.get("source_record_sha256") is not None
        )
        if (
            leaf.mechanism_id == "horizon-admittance"
            and retained is not None
            and snapshot.get("source_record_sha256") is None
        ):
            guarded(lambda: (_ for _ in ()).throw(
                ValueError("horizon promotion source record digest is missing")
            ))
        if horizon_source_record:
            if retained is None:
                guarded(lambda: (_ for _ in ()).throw(
                    ValueError("horizon promotion source record is not retained")
                ))
            if retained is not None and (
                retained.get("record_sha256")
                != snapshot.get("source_record_sha256")
            ):
                guarded(lambda: (_ for _ in ()).throw(
                    ValueError("horizon promotion source record digest mismatch")
                ))
            stages = retained.get("stages") if retained is not None else None
            source_stage = (
                stages[0]
                if isinstance(stages, list) and stages
                else None
            )
            if (
                not isinstance(source_stage, Mapping)
                or source_stage.get("stage_sha256")
                != snapshot.get("source_stage_sha256")
            ):
                guarded(lambda: (_ for _ in ()).throw(
                    ValueError("horizon promotion source stage digest mismatch")
                ))
        checkpoint_discovery = (
            None if retained is None else _checkpoint_terminal_discovery()
        )
        if retained is not None and record_validator is not None:
            guarded(lambda: record_validator(leaf_id, retained))
        cache_lookup = (
            None
            if cache_inventory is None
            else cache_inventory.lookup_for(selection.scientific_identities[leaf_id])
        )
        cache_record: Mapping[str, object] | None = None
        if cache_inventory is not None and not horizon_source_record:
            if cache_inventory.source_error is not None:
                guarded(
                    lambda: (_ for _ in ()).throw(ValueError(
                        cache_inventory.source_error
                    ))
                )
            assert cache_lookup is not None
            if cache_lookup.status is SolvedLeafLookupStatus.CORRUPT:
                guarded(
                    lambda: (_ for _ in ()).throw(ValueError(
                        "trusted solved-leaf cache receipt is corrupt: "
                        f"{cache_lookup.path}: {cache_lookup.reason}"
                    ))
                )
            if cache_lookup.status is SolvedLeafLookupStatus.HIT:
                if cache_lookup.receipt is None:
                    guarded(
                        lambda: (_ for _ in ()).throw(
                            ValueError("solved-leaf cache hit lacks a receipt")
                        )
                    )
                assert cache_lookup.receipt is not None
                cache_record = cache_lookup.receipt.get("record")
                if not isinstance(cache_record, Mapping):
                    guarded(
                        lambda: (_ for _ in ()).throw(
                            ValueError("solved-leaf cache record is invalid")
                        )
                    )
                assert isinstance(cache_record, Mapping)
                if record_validator is not None:
                    guarded(lambda: record_validator(leaf_id, cache_record))
                if retained is not None and dict(retained) != dict(cache_record):
                    guarded(
                        lambda: (_ for _ in ()).throw(TerminalCacheConflictError())
                    )
                if retained is None:
                    retained = cache_record
                    result = guarded(lambda: add_numerical_record(result, retained))
                    assert isinstance(result, dict)
                    existing_records[leaf_id] = retained
                    cache_reused_from_store += 1
        if checkpoint_discovery is not None:
            terminal_cache_discovery = terminal_cache_discovery.add(
                checkpoint_discovery.with_reused(1)
            )
        if retained is not None and not horizon_source_record:
            if root_promotion_group is not None:
                root_promotion_group.status = "SUPERSEDED_BY_CACHE"
            result = guarded(lambda: _commit_promoted_cache_reuse(
                result,
                leaf_id=leaf_id,
                queue_ordinal=ordinal,
                record=retained,
            ))
            assert isinstance(result, dict)
            cache_reused += 1
            result = persist(result)
            with progress_scope(
                leaf_id=leaf_id,
                execution_profile="SURVEY",
                survey_pass="promoted",
                pass_disposition=SurveyDisposition.SUPERSEDED_BY_CACHE.value,
                sample_count_used=0,
                sample_count_limit=0,
                root_read_count=0,
                root_read_limit=0,
                worker_launch_count=0,
                worker_launch_limit=0,
            ):
                emit_progress(ProgressEventKind.LEAF_PASS_DISPOSITION_RECORDED)
            continue

        if leaf.mechanism_id == "horizon-admittance":
            evidence_entry = result["evidence_ledger"].get(leaf_id)
            source_receipts = (
                tuple(evidence_entry["receipts"])
                if isinstance(evidence_entry, Mapping)
                and isinstance(evidence_entry.get("receipts"), list)
                else ()
            )
            recorder = TimingSessionRecorder(
                log=operational_timing,
                session_id=make_session_id(),
                leaf_id=leaf_id,
                execution_profile="SURVEY",
                survey_pass="promoted",
                clock=clock,
            )
            recorder.start_tier("BF80")
            with progress_scope(**leaf_context):
                outcome = guarded(
                    lambda: (
                        promoted_horizon_runner(
                            leaf, snapshot, retained, source_receipts
                        )
                        if promoted_horizon_runner is not None
                        else horizon_runner(leaf)
                    )
                )
            if not isinstance(outcome, PromotedPassOutcome):
                guarded(lambda: (_ for _ in ()).throw(
                    ValueError("promoted horizon runner returned invalid data")
                ))
            assert isinstance(outcome, PromotedPassOutcome)
            if outcome.precision_tiers != ("BF80",):
                guarded(lambda: (_ for _ in ()).throw(
                    ValueError("promoted horizon survey must use BF80 only")
                ))
            recorder.complete_tier()
            timing_summary = fold_timing_fragments(recorder.fragments)
            outcome = replace(
                outcome,
                tier_timing=timing_summary.tier_timing_mappings(),
                session_fragments=tuple(
                    fragment.to_mapping() for fragment in recorder.fragments
                ),
            )
        else:
            def execute_exterior() -> PromotedPassOutcome:
                recorder = TimingSessionRecorder(
                    log=operational_timing,
                    session_id=make_session_id(),
                    leaf_id=leaf_id,
                    execution_profile="SURVEY",
                    survey_pass="promoted",
                    clock=clock,
                )
                try:
                    with progress_scope(**leaf_context):
                        timed_outcome = _run_promoted_exterior_queue_entry(
                            leaf,
                            snapshot,
                            root_seal_lookup=root_seal_lookup,
                            root_seal_publish=root_seal_publish,
                            backend_factory=backend_factory,
                            primary_root_runner=primary_root_runner,
                            produced_record_builder=produced_record_builder,
                            timing_recorder=recorder,
                            determinant_error_store=determinant_error_store,
                            root_promotion_group=root_promotion_group,
                            provisional_predecessor_receipt=(
                                provisional_predecessor_receipt
                            ),
                        )
                except BaseException:
                    if recorder.active_tier is not None:
                        recorder.interrupt_tier()
                    raise
                if recorder.active_tier is not None:
                    raise ValueError("promoted survey left an active timing tier")
                summary = fold_timing_fragments(recorder.fragments)
                return replace(
                    timed_outcome,
                    tier_timing=summary.tier_timing_mappings(),
                    session_fragments=tuple(
                        fragment.to_mapping() for fragment in recorder.fragments
                    ),
                )

            outcome = guarded(execute_exterior)
        assert isinstance(outcome, PromotedPassOutcome)
        result = guarded(lambda: _commit_promoted_outcome(
            result,
            leaf_id=leaf_id,
            queue_ordinal=ordinal,
            queue_kind=PromotionQueueKind(snapshot["queue_kind"]),
            outcome=outcome,
            record_validator=record_validator,
        ))
        assert isinstance(result, dict)
        if outcome.disposition is SurveyDisposition.COMPLETED:
            completed += 1
        elif outcome.disposition is SurveyDisposition.UNRESOLVED:
            unresolved += 1
        elif outcome.disposition is SurveyDisposition.DEFERRED:
            deferred += 1
        elif outcome.disposition is SurveyDisposition.REJECTED:
            rejected += 1
        result = persist(result)
        if (
            outcome.record is not None
            and outcome.disposition is SurveyDisposition.COMPLETED
            and outcome.record.get("state") == "PRODUCED"
            and terminal_record_committed is not None
        ):
            try:
                terminal_record_committed(leaf, outcome.record)
            except KeyboardInterrupt:
                raise
            except Exception as error:
                abort_unexpected_system_failure(
                    result,
                    leaf_id=leaf_id,
                    error=error,
                    persist_checkpoint=lambda value: persist(value),
                )
        if outcome.disposition not in {
            SurveyDisposition.COMPLETED,
            SurveyDisposition.CACHE_REUSED,
            SurveyDisposition.SUPERSEDED_BY_CACHE,
        }:
            report = _survey_failure_report(
                leaf,
                survey_pass="promoted",
                reason_code=outcome.reason_code,
                operation_identity="promoted-survey-production/v1",
                precision_tier="+".join(outcome.precision_tiers),
                disposition=outcome.disposition,
            )
            if (
                failure_monitor.observe_leaf_outcome(leaf_id, report).disposition
                is FailureDisposition.SYSTEM_FAILURE
            ):
                failure_monitor.observe_system_failure(
                    result,
                    leaf_id=leaf_id,
                    report=report,
                    persist_checkpoint=lambda value: persist(value),
                )
        timing_by_tier = {
            item["tier"]: item["elapsed_seconds"] for item in outcome.tier_timing
        }
        with progress_scope(
            leaf_id=leaf_id,
            execution_profile="SURVEY",
            survey_pass="promoted",
            pass_disposition=outcome.disposition.value,
            evidence_level=(
                "SCREENED"
                if outcome.disposition is SurveyDisposition.COMPLETED
                else None
            ),
            sample_count_used=outcome.sample_count,
            sample_count_limit=outcome.sample_limit,
            root_read_count=outcome.root_read_count,
            root_read_limit=(
                outcome.root_read_limit
                if (
                    PromotionQueueKind(snapshot["queue_kind"])
                    is not PromotionQueueKind.RESPONSE
                    or outcome.operation_identity.startswith(
                        "promoted-horizon-"
                    )
                )
                else 0
            ),
            worker_launch_count=outcome.worker_launch_count,
            worker_launch_limit=(
                2
                if PromotionQueueKind(snapshot["queue_kind"])
                is PromotionQueueKind.RESPONSE
                else outcome.worker_launch_limit
            ),
            bf40_seconds=timing_by_tier.get("BF40", 0.0),
            bf80_seconds=timing_by_tier.get("BF80", 0.0),
            bf120_seconds=0.0,
            total_leaf_seconds=sum(timing_by_tier.values()),
        ):
            emit_progress(ProgressEventKind.LEAF_PASS_DISPOSITION_RECORDED)
    if diagnostic_session is not None:
        for group in sorted(
            root_promotion_groups.values(),
            key=lambda item: item.dependency_key.sha256,
        ):
            diagnostic_session.append(
                "ROOT_PROMOTION_GROUP_FINISHED",
                leaf={"leaf_id": group.canonical_primary_leaf_id},
                execution={"profile": "SURVEY", "pass": "promoted"},
                connections={
                    "root_dependency_key_sha256": group.dependency_key.sha256,
                    "root_seal_sha256": (
                        None if group.seal is None else group.seal.root_seal_sha256
                    ),
                },
                compact_diagnostics={
                    "root_dependency_key": group.dependency_key.to_mapping(),
                    "canonical_primary_leaf_id": group.canonical_primary_leaf_id,
                    "member_leaf_ids": list(group.member_leaf_ids),
                    "member_leaf_count": len(group.member_leaf_ids),
                    "root_solve_count": group.root_solve_count,
                    "publication_count": group.publication_count,
                    "resolved_precision_tier": group.resolved_precision_tier,
                    "status": group.status,
                },
                durable=True,
            )
    exhaustion = promoted_pass_exhaustion(
        result, selection, applicable_queue_ordinals
    )
    with progress_scope(execution_profile="SURVEY", survey_pass="promoted"):
        emit_progress(
            (
                ProgressEventKind.CAMPAIGN_PASS_COMPLETED
                if exhaustion.exhausted
                else ProgressEventKind.CAMPAIGN_PASS_INTERRUPTED
            ),
            completed_count=completed,
            unresolved_count=unresolved,
            deferred_count=deferred,
            rejected_count=rejected,
            skipped_count=skipped,
            incomplete_leaf_ids=list(exhaustion.incomplete_leaf_ids),
            incomplete_reasons=list(exhaustion.reasons),
        )
    if cache_inventory is not None:
        terminal_cache_discovery = terminal_cache_discovery.add(
            cache_inventory.discovery.with_reused(cache_reused_from_store)
        )
    return PromotedSurveyRun(
        checkpoint=validate_schema11_checkpoint(result),
        completed_count=completed,
        unresolved_count=unresolved,
        deferred_count=deferred,
        rejected_count=rejected,
        skipped_count=skipped,
        cache_reused_count=cache_reused,
        terminal_cache_discovery=terminal_cache_discovery,
        pass_exhausted=exhaustion.exhausted,
        incomplete_leaf_ids=exhaustion.incomplete_leaf_ids,
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
    "PromotedPassOutcome",
    "PromotedRootSolveResult",
    "PromotedSurveyRun",
    "dispatch_cache_first",
    "preflight_campaign_supports",
    "run_binary64_survey",
    "run_promoted_survey",
]
