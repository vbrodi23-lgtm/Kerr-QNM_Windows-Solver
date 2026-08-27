"""Cache-first entry points for schema-11 campaign survey passes."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field, replace
from decimal import Decimal
import hashlib
import json
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
    retain_promoted_background,
    retain_promoted_calculation,
    retain_promoted_continuation,
    retain_promoted_raw_calculation,
    validate_schema11_checkpoint,
)
from .campaign_recovery import RecoverySelection
from .campaign_record_intake import (
    CampaignRecordIntake,
    archive_excluded_record_in_checkpoint,
    assess_campaign_record_for_current_runtime,
    emit_forensic_record_excluded,
)
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
    BINARY64_HORIZON_OPERATION_V3,
    BackgroundEquivalenceReceipt,
    Binary64FixedRootBatch,
    Binary64ReusedBackgroundBatch,
    Binary64SurveyDisposition,
    CanonicalExteriorBackground,
    DecimalComplex,
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
    PromotedExecutionPreflight,
    retain_uncalibrated_determinant_error_evidence,
)
from .promoted_control_calibration import PromotedExecutionMode
from .background_evidence_store import CanonicalBackgroundEvidenceStore
from .julia_response_backend import (
    ExteriorDeterminantErrorEvidence,
    FIXED_ROOT_SURVEY_BATCH_SCHEMA,
    FixedRootSurveyPlan,
    FixedRootSurveyConditioning,
    JuliaFixedRootSurveyBatch,
    JuliaFixedRootSurveySample,
    JuliaNumericalControlError,
    JuliaODEResourceLimitError,
    JuliaResponseBackendError,
    JuliaRootReadoutResourceLimitError,
    consume_authenticated_binary64_provisional_predecessor,
)
from .promoted_artifacts import (
    PROMOTED_CANONICAL_BACKGROUND_RECEIPT_SCHEMA,
    PROMOTED_EXTERIOR_CALCULATION_SCHEMA,
    PromotedBackgroundBinding,
    PromotedCanonicalBackgroundReceipt,
    PromotedExteriorCalculationResult,
    PromotedFixedRootComposite,
    PromotedHorizonCalculationResult,
)
from .precision_tiers import PrecisionTier
from .progress import ProgressEventKind, emit_progress, progress_scope
from .root_evidence import RootDependencyKey
from .structural_diagnostics import StructuralDiagnosticSession


RecordValidator = Callable[[str, Mapping[str, object]], None]
RecordIntakeAssessor = Callable[
    [str, Mapping[str, object]], CampaignRecordIntake
]
_ROOT_PROMOTION_ARITHMETIC_TIER = "root-promotion"
_ACTIVE_PROMOTED_QUEUE_DISPOSITIONS = frozenset({
    PromotionQueueDisposition.PENDING.value,
    PromotionQueueDisposition.CALCULATED_PENDING_DERIVATION.value,
    PromotionQueueDisposition.NUMERICAL_CONTINUATION.value,
})


def _intake_checkpoint_records(
    plan: object,
    checkpoint: Mapping[str, object],
    *,
    source_path: str | os.PathLike[str] | Path,
    diagnostic_session: StructuralDiagnosticSession | None,
) -> dict[str, object]:
    """Authenticate mixed-version checkpoint records before current use."""

    result = validate_schema11_checkpoint(checkpoint)
    for record in tuple(result["records"]):
        leaf_id = record.get("leaf_id")
        if not isinstance(leaf_id, str):
            raise ValueError("checkpoint record leaf identity is invalid")
        intake = assess_campaign_record_for_current_runtime(plan, leaf_id, record)
        if intake.response_admissible:
            continue
        if intake.forensic_only:
            emit_forensic_record_excluded(
                diagnostic_session,
                intake,
                leaf_id=leaf_id,
                source_kind="checkpoint-forensic-response",
                source_path=source_path,
                stale_cache_hit_prevented=False,
            )
        result = archive_excluded_record_in_checkpoint(
            result,
            intake,
            source_path=source_path,
        )
    return validate_schema11_checkpoint(result)


def _current_terminal_cache_record(
    plan: object,
    leaf_id: str,
    lookup: object,
    *,
    record_validator: RecordValidator | None,
    diagnostic_session: StructuralDiagnosticSession | None,
) -> Mapping[str, object] | None:
    """Return current response evidence after the central intake decision."""

    status = getattr(lookup, "status", None)
    if status not in {
        SolvedLeafLookupStatus.HIT,
        SolvedLeafLookupStatus.STALE,
    }:
        return None
    receipt = getattr(lookup, "receipt", None)
    if not isinstance(receipt, Mapping):
        raise ValueError("solved-leaf cache result lacks an authenticated receipt")
    record = receipt.get("record")
    if not isinstance(record, Mapping):
        raise ValueError("solved-leaf cache record is invalid")
    intake = assess_campaign_record_for_current_runtime(plan, leaf_id, record)
    if not intake.response_admissible:
        if intake.forensic_only:
            emit_forensic_record_excluded(
                diagnostic_session,
                intake,
                leaf_id=leaf_id,
                source_kind="solved-leaf-forensic-response",
                source_path=(
                    "solved-leaf-store"
                    if getattr(lookup, "path", None) is None
                    else getattr(lookup, "path")
                ),
                stale_cache_hit_prevented=True,
            )
        return None
    if status is not SolvedLeafLookupStatus.HIT:
        return None
    if record_validator is not None:
        record_validator(leaf_id, record)
    return intake.record


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
    calculation_artifact: Mapping[str, object] | None = None
    source_calculation_stage_sha256: str | None = None
    calculation_chain: tuple[Mapping[str, object], ...] = ()
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
class PromotedRouteExecutionResult:
    """Typed per-route result, including known non-software policy boundaries."""

    queue_ordinal: int
    leaf_id: str
    route: str
    execution_mode: str
    result_code: str
    numerical_work_performed: bool
    admission_state: str


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
    review_pending_count: int = 0
    policy_blocked_count: int = 0
    route_results: tuple[PromotedRouteExecutionResult, ...] = ()
    locked_route_count: int = 0
    exterior_bf40_route_count: int = 0
    horizon_bf80_route_count: int = 0
    exterior_bf40_executed_count: int = 0
    horizon_bf80_executed_count: int = 0
    binary64_predecessor_evaluation_count: int = 0
    binary64_recomputed_evaluation_count: int = 0
    promoted_background_acquired_count: int = 0
    promoted_background_reused_count: int = 0
    calculated_awaiting_admission_count: int = 0
    admitted_count: int = 0
    screened_count: int = 0
    terminal_publication_count: int = 0


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
    incomplete: list[str] = [*missing, *unexpected]
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
        elif expected_kind == PromotionQueueKind.RESPONSE.value:
            queue_entry = queues[0]
            if any(
                queue_entry.get(field) is None
                for field in (
                    "source_stage_sha256",
                    "source_root_seal_sha256",
                    "source_binary64_disposition_receipt_sha256",
                )
            ):
                reasons.append("UNLOCKABLE_PROMOTION_SOURCE")
                incomplete.append(leaf_id)
    return PassExhaustion(
        not reasons,
        tuple(dict.fromkeys(incomplete)),
        tuple(reasons),
    )


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
        PromotionQueueDisposition.AWAITING_ADMISSION.value: (
            SurveyDisposition.CALCULATED_AWAITING_ADMISSION.value
        ),
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
        if disposition in _ACTIVE_PROMOTED_QUEUE_DISPOSITIONS:
            reasons.append(f"{disposition}_PROMOTION:{leaf_id}")
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
            and item["disposition"] in _ACTIVE_PROMOTED_QUEUE_DISPOSITIONS
        ):
            leaf_id = str(item["leaf_id"])
            marker = f"{item['disposition']}_PROMOTION:{leaf_id}"
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

    result = _intake_checkpoint_records(
        plan,
        checkpoint,
        source_path=checkpoint_path,
        diagnostic_session=diagnostic_session,
    )
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
        leaf_index = selection.ordered_leaf_ids.index(leaf_id) + 1
        leaf_context = {
            "leaf_index": leaf_index,
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

        def append_binary64_structural_event(
            event_kind: str,
            *,
            operation_identity: str | None,
            disposition: str | None,
            reason_code: str | None,
            root_seal_sha256: str | None,
            source_record_sha256: str | None,
            source_stage_sha256: str | None,
            provisional_stage_sha256: str | None,
            post_commit: Mapping[str, object] | None,
        ) -> None:
            if diagnostic_session is None:
                return
            diagnostic_session.append(
                event_kind,
                leaf={
                    "index": leaf_index,
                    "count": len(selection.ordered_leaf_ids),
                    "leaf_id": leaf_id,
                    "role": leaf.role,
                    "mode": "-".join(str(item) for item in leaf.leaf.mode),
                    "exact_coordinate": leaf.job.sampling_coordinate.to_mapping(),
                    "spin_display": str(leaf.job.spin),
                    "mechanism": leaf.mechanism_id,
                },
                execution={
                    "profile": "SURVEY",
                    "pass": "binary64",
                    "tier": "binary64",
                    "operation_identity": operation_identity,
                },
                transition={
                    "prior_state": "NOT_ATTEMPTED",
                    "next_state": disposition,
                    "reason_code": reason_code,
                },
                connections={
                    "scientific_computation_identity": selection.scientific_identities[
                        leaf_id
                    ],
                    "root_seal_sha256": root_seal_sha256,
                    "source_record_sha256": source_record_sha256,
                    "source_stage_sha256": source_stage_sha256,
                    "provisional_stage_sha256": provisional_stage_sha256,
                },
                checkpoint={
                    "pre_commit_sha256": hashlib.sha256(
                        canonical_json_bytes(committed_before_leaf)
                    ).hexdigest(),
                    "post_commit_sha256": (
                        None
                        if post_commit is None
                        else hashlib.sha256(
                            canonical_json_bytes(post_commit)
                        ).hexdigest()
                    ),
                },
                compact_diagnostics={
                    "julia_worker_launched": False,
                },
                durable=False,
            )

        with progress_scope(**leaf_context):
            emit_progress(ProgressEventKind.LEAF_PASS_STARTED)
        append_binary64_structural_event(
            "BINARY64_LEAF_STARTED",
            operation_identity=None,
            disposition=None,
            reason_code=None,
            root_seal_sha256=None,
            source_record_sha256=None,
            source_stage_sha256=None,
            provisional_stage_sha256=None,
            post_commit=None,
        )

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
            if cache_lookup.status in {
                SolvedLeafLookupStatus.HIT,
                SolvedLeafLookupStatus.STALE,
            }:
                cache_record = guarded(
                    lambda: _current_terminal_cache_record(
                        plan,
                        leaf_id,
                        cache_lookup,
                        record_validator=record_validator,
                        diagnostic_session=diagnostic_session,
                    )
                )
                if cache_record is not None:
                    assert isinstance(cache_record, Mapping)
                    if (
                        retained is not None
                        and canonical_json_bytes(retained)
                        != canonical_json_bytes(cache_record)
                    ):
                        guarded(
                            lambda: (_ for _ in ()).throw(
                                TerminalCacheConflictError()
                            )
                        )
                    if retained is None:
                        retained = cache_record
                        result = guarded(
                            lambda: add_numerical_record(result, retained)
                        )
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
            append_binary64_structural_event(
                "BINARY64_LEAF_DISPOSITION_RECORDED",
                operation_identity="solved-leaf-cache/v1",
                disposition=SurveyDisposition.CACHE_REUSED.value,
                reason_code="EXACT_AUTHENTICATED_CACHE_HIT",
                root_seal_sha256=None,
                source_record_sha256=retained["record_sha256"],
                source_stage_sha256=None,
                provisional_stage_sha256=None,
                post_commit=result,
            )
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
                    operation_identity=BINARY64_HORIZON_OPERATION_V3,
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
        append_binary64_structural_event(
            "BINARY64_LEAF_DISPOSITION_RECORDED",
            operation_identity=outcome.operation_identity,
            disposition=outcome.disposition.value,
            reason_code=outcome.reason_code,
            root_seal_sha256=root_seal_sha256,
            source_record_sha256=(
                None if outcome.record is None else outcome.record["record_sha256"]
            ),
            source_stage_sha256=outcome.stage_sha256,
            provisional_stage_sha256=outcome.provisional_stage_sha256,
            post_commit=result,
        )
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


_PROMOTED_BACKGROUND_RECEIPT_SCHEMA = (
    "windows-solver.promoted-background-reuse-receipt/1"
)
_PROMOTED_ROOT_RECEIPT_SCHEMA = "windows-solver.promoted-root-evidence-receipt/1"
_PROMOTED_BACKGROUND_SAMPLE_ROLES = BINARY64_FIXED_ROOT_SAMPLE_ROLES[:5]
_PROMOTED_COMPONENT_SAMPLE_ROLES = BINARY64_FIXED_ROOT_SAMPLE_ROLES[5:]


def _promoted_sample_from_mapping(value: object) -> JuliaFixedRootSurveySample:
    if not isinstance(value, Mapping) or set(value) != {
        "role",
        "omega",
        "amplitude",
        "determinant",
        "numerical_conditioning",
        "determinant_error_evidence",
    }:
        raise ValueError("retained promoted background sample is invalid")

    def parse_complex(item: object, label: str) -> complex:
        if not isinstance(item, Mapping) or set(item) != {"real", "imaginary"}:
            raise ValueError(f"retained promoted {label} is invalid")
        try:
            result = complex(float(item["real"]), float(item["imaginary"]))
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError(f"retained promoted {label} is invalid") from error
        if not math.isfinite(result.real) or not math.isfinite(result.imag):
            raise ValueError(f"retained promoted {label} is invalid")
        return result

    determinant = value["determinant"]
    if not isinstance(determinant, Mapping) or set(determinant) != {
        "real",
        "imaginary",
    }:
        raise ValueError("retained promoted determinant is invalid")
    try:
        decimal_determinant = DecimalComplex(
            Decimal(str(determinant["real"])),
            Decimal(str(determinant["imaginary"])),
        )
    except Exception as error:
        raise ValueError("retained promoted determinant is invalid") from error
    raw_error = value["determinant_error_evidence"]
    return JuliaFixedRootSurveySample(
        role=str(value["role"]),
        omega=parse_complex(value["omega"], "sample frequency"),
        amplitude=parse_complex(value["amplitude"], "sample amplitude"),
        determinant=decimal_determinant,
        numerical_conditioning=FixedRootSurveyConditioning(
            value["numerical_conditioning"]
        ),
        determinant_error_evidence=(
            None
            if raw_error is None
            else ExteriorDeterminantErrorEvidence(raw_error)
        ),
    )


def promoted_fixed_root_batch_from_mapping(
    value: object,
) -> JuliaFixedRootSurveyBatch:
    """Reconstruct one authenticated retained promoted batch without a worker."""

    fields = {
        "schema",
        "operation",
        "identity",
        "scientific_operation_identity",
        "leaf_id",
        "job_id",
        "mechanism_id",
        "root_reference_id",
        "root_seal_sha256",
        "branch_identity",
        "fixed_root",
        "frequency_step",
        "coordinate_step",
        "request_sha256",
        "precision_tier",
        "working_precision_bits",
        "sample_roles",
        "sample_count",
        "maximum_sample_count",
        "julia_launch_count",
        "root_read_count",
        "samples",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError("retained promoted batch fields are invalid")
    if value.get("schema") != FIXED_ROOT_SURVEY_BATCH_SCHEMA:
        raise ValueError("retained promoted batch schema is invalid")

    def parse_complex(item: object, label: str) -> complex:
        if not isinstance(item, Mapping) or set(item) != {"real", "imaginary"}:
            raise ValueError(f"retained promoted batch {label} is invalid")
        try:
            result = complex(float(item["real"]), float(item["imaginary"]))
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            raise ValueError(
                f"retained promoted batch {label} is invalid"
            ) from error
        if not math.isfinite(result.real) or not math.isfinite(result.imag):
            raise ValueError(f"retained promoted batch {label} is invalid")
        return result

    def integer(name: str, *, minimum: int) -> int:
        candidate = value[name]
        if isinstance(candidate, bool) or not isinstance(candidate, int):
            raise ValueError(f"retained promoted batch {name} is invalid")
        if candidate < minimum:
            raise ValueError(f"retained promoted batch {name} is invalid")
        return candidate

    try:
        frequency_step = Decimal(str(value["frequency_step"]))
        coordinate_step = Decimal(str(value["coordinate_step"]))
    except Exception as error:
        raise ValueError("retained promoted batch steps are invalid") from error
    if (
        not frequency_step.is_finite()
        or not coordinate_step.is_finite()
        or frequency_step <= 0
        or coordinate_step < 0
    ):
        raise ValueError("retained promoted batch steps are invalid")
    samples_value = value["samples"]
    roles_value = value["sample_roles"]
    if not isinstance(samples_value, list) or not isinstance(roles_value, list):
        raise ValueError("retained promoted batch samples are invalid")
    samples = tuple(_promoted_sample_from_mapping(sample) for sample in samples_value)
    roles = tuple(sample.role for sample in samples)
    if (
        tuple(roles_value) != roles
        or integer("sample_count", minimum=0) != len(samples)
        or integer("maximum_sample_count", minimum=len(samples)) < len(samples)
    ):
        raise ValueError("retained promoted batch sample plan is invalid")
    try:
        precision_tier = PrecisionTier(str(value["precision_tier"]))
    except ValueError as error:
        raise ValueError("retained promoted batch precision tier is invalid") from error
    required_strings = (
        "operation",
        "identity",
        "scientific_operation_identity",
        "leaf_id",
        "job_id",
        "mechanism_id",
        "root_reference_id",
        "root_seal_sha256",
        "branch_identity",
        "request_sha256",
    )
    if any(not isinstance(value[name], str) or not value[name] for name in required_strings):
        raise ValueError("retained promoted batch identity is invalid")
    root_seal_sha256 = str(value["root_seal_sha256"])
    if len(root_seal_sha256) != 64:
        raise ValueError("retained promoted batch root seal is invalid")
    try:
        int(root_seal_sha256, 16)
    except ValueError as error:
        raise ValueError("retained promoted batch root seal is invalid") from error
    return JuliaFixedRootSurveyBatch(
        leaf_id=str(value["leaf_id"]),
        job_id=str(value["job_id"]),
        mechanism_id=str(value["mechanism_id"]),
        root_reference_id=str(value["root_reference_id"]),
        root_seal_sha256=root_seal_sha256,
        branch_identity=str(value["branch_identity"]),
        fixed_root=parse_complex(value["fixed_root"], "fixed root"),
        frequency_step=frequency_step,
        coordinate_step=coordinate_step,
        scientific_operation_identity=str(value["scientific_operation_identity"]),
        request_sha256=str(value["request_sha256"]),
        precision_tier=precision_tier,
        working_precision_bits=integer("working_precision_bits", minimum=2),
        samples=samples,
        maximum_sample_count=integer("maximum_sample_count", minimum=len(samples)),
        operation=str(value["operation"]),
        identity=str(value["identity"]),
        julia_launch_count=integer("julia_launch_count", minimum=0),
        root_read_count=integer("root_read_count", minimum=0),
    )


def _promoted_background_key(
    leaf: object,
    seal: AuthenticatedRootSeal,
    digits: int,
) -> tuple[str, Mapping[str, object]]:
    reuse_key = build_exterior_background_reuse_key(
        leaf.job,
        root_seal_sha256=seal.root_seal_sha256,
        fixed_root=seal.fixed_root,
    )
    mapping = reuse_key.to_mapping()
    digest = hashlib.sha256(canonical_json_bytes({
        "precision_tier": f"bigfloat-{digits}",
        "reuse_key": mapping,
    })).hexdigest()
    return digest, mapping


def _promoted_canonical_background_receipt_from_mapping(
    value: object,
) -> tuple[PromotedCanonicalBackgroundReceipt, dict[str, object]]:
    """Rehydrate one v2 background receipt from checkpoint data only."""

    fields = {
        "schema",
        "cache_key_sha256",
        "reuse_key",
        "source_queue_ordinal",
        "source_leaf_id",
        "background_worker_request_sha256",
        "background_worker_batch",
        "background_sha256",
        "receipt_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError("promoted canonical background receipt fields are invalid")
    content = {key: item for key, item in value.items() if key != "receipt_sha256"}
    if (
        value.get("schema") != PROMOTED_CANONICAL_BACKGROUND_RECEIPT_SCHEMA
        or value.get("receipt_sha256") != hashlib.sha256(
            canonical_json_bytes(content)
        ).hexdigest()
    ):
        raise ValueError("promoted canonical background receipt digest is invalid")
    batch = promoted_fixed_root_batch_from_mapping(value["background_worker_batch"])
    receipt = PromotedCanonicalBackgroundReceipt(
        batch=batch,
        cache_key_sha256=str(value["cache_key_sha256"]),
        reuse_key=value["reuse_key"],
        source_queue_ordinal=value["source_queue_ordinal"],
        source_leaf_id=str(value["source_leaf_id"]),
    )
    canonical = receipt.to_mapping()
    if canonical != dict(value):
        raise ValueError("promoted canonical background receipt is not canonical")
    return receipt, canonical


def _promoted_exterior_calculation_from_mapping(
    value: object,
) -> tuple[PromotedExteriorCalculationResult, dict[str, object]]:
    """Rehydrate one raw four-sample calculation without a worker call."""

    fields = {
        "schema",
        "component_worker_request_sha256",
        "component_worker_batch",
        "background",
        "calculation_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError("promoted exterior calculation artifact fields are invalid")
    content = {key: item for key, item in value.items() if key != "calculation_sha256"}
    if (
        value.get("schema") != PROMOTED_EXTERIOR_CALCULATION_SCHEMA
        or value.get("calculation_sha256") != hashlib.sha256(
            canonical_json_bytes(content)
        ).hexdigest()
    ):
        raise ValueError("promoted exterior calculation artifact digest is invalid")
    binding_value = value["background"]
    binding_fields = {
        "schema",
        "background_receipt_sha256",
        "background_worker_request_sha256",
        "background_sha256",
        "binding_sha256",
    }
    if not isinstance(binding_value, Mapping) or set(binding_value) != binding_fields:
        raise ValueError("promoted exterior background binding is invalid")
    binding_content = {
        key: item for key, item in binding_value.items() if key != "binding_sha256"
    }
    if binding_value.get("binding_sha256") != hashlib.sha256(
        canonical_json_bytes(binding_content)
    ).hexdigest():
        raise ValueError("promoted exterior background binding digest is invalid")
    component = promoted_fixed_root_batch_from_mapping(
        value["component_worker_batch"]
    )
    if value.get("component_worker_request_sha256") != component.request_sha256:
        raise ValueError("promoted exterior component request binding is invalid")
    binding = PromotedBackgroundBinding(
        background_receipt_sha256=str(binding_value["background_receipt_sha256"]),
        background_worker_request_sha256=str(
            binding_value["background_worker_request_sha256"]
        ),
        background_sha256=str(binding_value["background_sha256"]),
    )
    calculation = PromotedExteriorCalculationResult(
        component_batch=component,
        background=binding,
    )
    canonical = calculation.to_mapping()
    if canonical != dict(value):
        raise ValueError("promoted exterior calculation artifact is not canonical")
    return calculation, canonical


def _resumed_promoted_exterior_outcome(
    retained_stage: Mapping[str, object],
    *,
    promoted_background_cache: Mapping[str, Mapping[str, object]],
) -> PromotedPassOutcome:
    """Reduce an already checkpointed exterior worker result with no numerics."""

    artifact = retained_stage.get("calculation_artifact")
    calculation, canonical_artifact = _promoted_exterior_calculation_from_mapping(
        artifact
    )
    background_entry = next(
        (
            item
            for item in promoted_background_cache.values()
            if isinstance(item, Mapping)
            and isinstance(item.get("background_receipt"), Mapping)
            and item["background_receipt"].get("receipt_sha256")
            == calculation.background.background_receipt_sha256
        ),
        None,
    )
    if not isinstance(background_entry, Mapping):
        raise ValueError("retained exterior calculation background is missing")
    background = background_entry.get("background_batch")
    if not isinstance(background, JuliaFixedRootSurveyBatch):
        raise ValueError("retained exterior calculation uses a legacy background")
    # This is a reducer-owned composition of two retained worker artifacts;
    # it is not a replacement worker batch and invokes no numerical backend.
    PromotedFixedRootComposite(
        background_batch=background,
        component_batch=calculation.component_batch,
        background_receipt_sha256=calculation.background.background_receipt_sha256,
    )
    receipts = retained_stage.get("receipts")
    tiers = retained_stage.get("precision_tiers")
    chain = retained_stage.get("calculation_chain")
    counters = (
        retained_stage.get("sample_count"),
        retained_stage.get("root_read_count"),
        retained_stage.get("worker_launch_count"),
    )
    if (
        not isinstance(receipts, list)
        or not isinstance(tiers, list)
        or not all(isinstance(item, Mapping) for item in receipts)
        or not all(isinstance(item, Mapping) for item in (chain or []))
        or not all(isinstance(item, int) and item >= 0 for item in counters)
    ):
        raise ValueError("retained exterior calculation state is invalid")
    stage_sha256 = retained_stage.get("stage_sha256")
    if not isinstance(stage_sha256, str) or len(stage_sha256) != 64:
        raise ValueError("retained exterior calculation stage digest is invalid")
    return PromotedPassOutcome(
        disposition=SurveyDisposition.CALCULATED_AWAITING_ADMISSION,
        reason_code="AWAITING_INDEPENDENT_REVIEW_ADMISSION",
        precision_tiers=tuple(str(item) for item in tiers),
        operation_identity="promoted-exterior-calculation/v2",
        sample_count=int(counters[0]),
        root_read_count=int(counters[1]),
        worker_launch_count=int(counters[2]),
        evidence_receipts=tuple(copy.deepcopy(dict(item)) for item in receipts),
        calculation_artifact=canonical_artifact,
        source_calculation_stage_sha256=stage_sha256,
        calculation_chain=tuple(copy.deepcopy(dict(item)) for item in (chain or [])),
        tier_timing=tuple(
            copy.deepcopy(dict(item))
            for item in retained_stage.get("tier_timing", [])
            if isinstance(item, Mapping)
        ),
        session_fragments=tuple(
            copy.deepcopy(dict(item))
            for item in retained_stage.get("session_fragments", [])
            if isinstance(item, Mapping)
        ),
    )


def _resumed_promoted_horizon_outcome(
    retained_stage: Mapping[str, object],
) -> PromotedPassOutcome:
    """Advance one checkpointed BF80 return without reopening a worker."""

    artifact = PromotedHorizonCalculationResult.from_mapping(
        retained_stage.get("calculation_artifact")
    ).to_mapping()
    if (
        retained_stage.get("route") != "HORIZON_BF80"
        or retained_stage.get("predecessor_stage_sha256")
        != artifact["predecessor_stage_sha256"]
        or retained_stage.get("source_fingerprint_sha256")
        != artifact["source_fingerprint_sha256"]
        or retained_stage.get("layer1_lock_receipt_sha256")
        != artifact["layer1_lock_receipt_sha256"]
    ):
        raise ValueError("retained horizon calculation lineage is invalid")
    counters = (
        retained_stage.get("sample_count"),
        retained_stage.get("root_read_count"),
        retained_stage.get("worker_launch_count"),
    )
    if not all(isinstance(item, int) and item >= 0 for item in counters):
        raise ValueError("retained horizon calculation counters are invalid")
    stage_sha256 = retained_stage.get("stage_sha256")
    if not isinstance(stage_sha256, str) or len(stage_sha256) != 64:
        raise ValueError("retained horizon calculation stage digest is invalid")
    return PromotedPassOutcome(
        disposition=SurveyDisposition.CALCULATED_AWAITING_ADMISSION,
        reason_code="AWAITING_INDEPENDENT_REVIEW_ADMISSION",
        precision_tiers=("BF80",),
        operation_identity="promoted-horizon-calculation/v2",
        source_record_sha256=(
            None
            if retained_stage.get("source_record_sha256") is None
            else str(retained_stage["source_record_sha256"])
        ),
        source_stage_sha256=(
            None
            if retained_stage.get("source_record_stage_sha256") is None
            else str(retained_stage["source_record_stage_sha256"])
        ),
        sample_count=int(counters[0]),
        root_read_count=int(counters[1]),
        root_read_limit=1,
        worker_launch_count=int(counters[2]),
        worker_launch_limit=1,
        calculation_artifact=artifact,
        source_calculation_stage_sha256=stage_sha256,
        calculation_chain=tuple(
            copy.deepcopy(dict(item))
            for item in retained_stage.get("calculation_chain", [])
            if isinstance(item, Mapping)
        ),
        tier_timing=tuple(
            copy.deepcopy(dict(item))
            for item in retained_stage.get("tier_timing", [])
            if isinstance(item, Mapping)
        ),
        session_fragments=tuple(
            copy.deepcopy(dict(item))
            for item in retained_stage.get("session_fragments", [])
            if isinstance(item, Mapping)
        ),
    )


def _promoted_background_receipt(
    *,
    batch: JuliaFixedRootSurveyBatch,
    cache_key_sha256: str,
    reuse_key: Mapping[str, object],
    source_queue_ordinal: int,
    source_leaf_id: str,
) -> dict[str, object]:
    """Return the real five-sample worker receipt, not a sliced surrogate."""

    return PromotedCanonicalBackgroundReceipt(
        batch=batch,
        cache_key_sha256=cache_key_sha256,
        reuse_key=reuse_key,
        source_queue_ordinal=source_queue_ordinal,
        source_leaf_id=source_leaf_id,
    ).to_mapping()


def _load_promoted_background_cache(
    checkpoint: Mapping[str, object],
) -> dict[str, dict[str, object]]:
    cache: dict[str, dict[str, object]] = {}
    ledger = checkpoint.get("promoted_background_ledger")
    if not isinstance(ledger, Mapping):
        raise ValueError("promoted background ledger is invalid")
    for bucket in ledger.values():
        if not isinstance(bucket, Mapping):
            raise ValueError("promoted background ledger bucket is invalid")
        for ledger_entry in bucket.values():
            payload = (
                ledger_entry.get("payload")
                if isinstance(ledger_entry, Mapping)
                else None
            )
            receipts = (
                payload.get("background_receipts")
                if isinstance(payload, Mapping)
                else None
            )
            if receipts is None:
                continue
            if not isinstance(receipts, list):
                raise ValueError("promoted background receipts are invalid")
            for receipt in receipts:
                if (
                    isinstance(receipt, Mapping)
                    and receipt.get("schema")
                    == PROMOTED_CANONICAL_BACKGROUND_RECEIPT_SCHEMA
                ):
                    parsed_receipt, canonical_receipt = (
                        _promoted_canonical_background_receipt_from_mapping(receipt)
                    )
                    candidate = {
                        "background_sha256": parsed_receipt.background_sha256,
                        "background_batch": parsed_receipt.batch,
                        "background_samples": parsed_receipt.batch.samples,
                        "background_receipt": canonical_receipt,
                        "queue_ordinal": parsed_receipt.source_queue_ordinal,
                        "leaf_id": parsed_receipt.source_leaf_id,
                        "reuse_key": copy.deepcopy(dict(parsed_receipt.reuse_key)),
                    }
                    existing = cache.get(parsed_receipt.cache_key_sha256)
                    if existing is not None and existing != candidate:
                        raise ValueError("conflicting promoted background")
                    cache[parsed_receipt.cache_key_sha256] = candidate
                    continue
                if (
                    not isinstance(receipt, Mapping)
                    or receipt.get("schema") != _PROMOTED_BACKGROUND_RECEIPT_SCHEMA
                ):
                    raise ValueError("promoted background receipt is invalid")
                content = {
                    key: item
                    for key, item in receipt.items()
                    if key != "receipt_sha256"
                }
                if receipt.get("receipt_sha256") != hashlib.sha256(
                    canonical_json_bytes(content)
                ).hexdigest():
                    raise ValueError("promoted background receipt digest is invalid")
                background = receipt.get("background")
                samples = (
                    background.get("samples")
                    if isinstance(background, Mapping)
                    else None
                )
                if not isinstance(samples, list):
                    raise ValueError("promoted background samples are invalid")
                parsed_samples = tuple(
                    _promoted_sample_from_mapping(sample) for sample in samples
                )
                if tuple(sample.role for sample in parsed_samples) != tuple(
                    _PROMOTED_BACKGROUND_SAMPLE_ROLES
                ):
                    raise ValueError("promoted background sample roles are invalid")
                BackgroundEquivalenceReceipt.from_mapping(
                    receipt.get("equivalence_receipt")
                )
                cache_key = receipt.get("cache_key_sha256")
                candidate = {
                    "background_sha256": receipt.get("background_sha256"),
                    "background_batch": None,
                    "background_samples": parsed_samples,
                    "background_receipt": copy.deepcopy(dict(receipt)),
                    "queue_ordinal": receipt.get("source_queue_ordinal"),
                    "leaf_id": receipt.get("source_leaf_id"),
                    "reuse_key": copy.deepcopy(dict(receipt["reuse_key"])),
                }
                existing = cache.get(str(cache_key))
                if existing is not None and existing != candidate:
                    raise ValueError("conflicting promoted background")
                cache[str(cache_key)] = candidate
    return cache


def _continuation_root_seal(
    continuation_stage: Mapping[str, object] | None,
    *,
    leaf: object,
) -> AuthenticatedRootSeal | None:
    """Recover the exact BF40 root seal retained before a BF80 continuation."""

    if continuation_stage is None:
        return None
    receipts = continuation_stage.get("receipts")
    if not isinstance(receipts, list):
        raise ValueError("promoted continuation receipts are invalid")
    restored: AuthenticatedRootSeal | None = None
    for receipt in receipts:
        if (
            not isinstance(receipt, Mapping)
            or receipt.get("schema") != _PROMOTED_ROOT_RECEIPT_SCHEMA
        ):
            continue
        fixed_root = receipt.get("fixed_root")
        if (
            receipt.get("precision_tier") != "BF40"
            or not isinstance(fixed_root, Mapping)
        ):
            raise ValueError("promoted continuation root receipt is invalid")
        try:
            candidate = AuthenticatedRootSeal(
                complex(
                    float(fixed_root["real"]),
                    float(fixed_root["imaginary"]),
                ),
                str(receipt["branch_identity"]),
                str(receipt["root_seal_sha256"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("promoted continuation root receipt is invalid") from error
        if candidate.branch_identity != leaf.job.root.branch_id:
            raise ValueError("promoted continuation root branch mismatch")
        if restored is not None and restored != candidate:
            raise ValueError("conflicting promoted continuation root")
        restored = candidate
    return restored


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
    execution_mode: PromotedExecutionMode,
    promoted_background_cache: dict[str, dict[str, object]],
    continuation_stage: Mapping[str, object] | None = None,
    tier_checkpoint: Callable[[PromotedPassOutcome], None] | None = None,
    background_checkpoint: Callable[[Mapping[str, object]], None] | None = None,
    raw_checkpoint: Callable[[PromotedPassOutcome], str] | None = None,
) -> PromotedPassOutcome:
    queue_kind = PromotionQueueKind(entry["queue_kind"])
    seal = root_seal_lookup(leaf, entry)
    retained_root_seal = _continuation_root_seal(
        continuation_stage,
        leaf=leaf,
    )
    if retained_root_seal is not None:
        if seal is not None and seal != retained_root_seal:
            raise ValueError("promoted continuation root seal conflict")
        seal = retained_root_seal
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
    calculation_chain: list[Mapping[str, object]] = []
    source_calculation_stage_sha256: str | None = None
    sample_count = root_reads = worker_launches = 0
    digits_to_run = (40, 80)
    if continuation_stage is not None:
        if (
            continuation_stage.get("admission_state")
            != "NUMERICAL_CONTINUATION"
            or continuation_stage.get("next_precision_tier") != "BF80"
            or continuation_stage.get("queue_ordinal") != entry["queue_ordinal"]
            or continuation_stage.get("leaf_id") != entry["leaf_id"]
            or continuation_stage.get("precision_tiers") != ["BF40"]
        ):
            raise ValueError("promoted continuation stage is invalid")
        retained_receipts = continuation_stage.get("receipts")
        if not isinstance(retained_receipts, list) or not all(
            isinstance(receipt, Mapping) for receipt in retained_receipts
        ):
            raise ValueError("promoted continuation receipts are invalid")
        counters: list[int] = []
        for field in ("sample_count", "root_read_count", "worker_launch_count"):
            value = continuation_stage.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("promoted continuation counters are invalid")
            counters.append(value)
        tiers = ["BF40"]
        receipts = [copy.deepcopy(dict(receipt)) for receipt in retained_receipts]
        sample_count, root_reads, worker_launches = counters
        digits_to_run = (80,)
    elif provisional_predecessor_receipt is not None:
        receipts.append(dict(provisional_predecessor_receipt))

    def checkpoint_bf40_before_bf80(reason_code: str) -> None:
        if tier_checkpoint is None:
            return
        tier_checkpoint(PromotedPassOutcome(
            disposition=SurveyDisposition.UNRESOLVED,
            reason_code=reason_code,
            precision_tiers=tuple(tiers),
            sample_count=sample_count,
            root_read_count=root_reads,
            worker_launch_count=worker_launches,
            evidence_receipts=tuple(receipts),
            calculation_artifact=(
                None if not calculation_chain else calculation_chain[-1]
            ),
            source_calculation_stage_sha256=source_calculation_stage_sha256,
            calculation_chain=tuple(calculation_chain),
        ))

    for digits in digits_to_run:
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
                    checkpoint_bf40_before_bf80(decision.failure_code)
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
            root_content: dict[str, object] = {
                "schema": _PROMOTED_ROOT_RECEIPT_SCHEMA,
                "queue_ordinal": entry["queue_ordinal"],
                "leaf_id": entry["leaf_id"],
                "precision_tier": tier,
                "root_seal_sha256": seal.root_seal_sha256,
                "branch_identity": seal.branch_identity,
                "fixed_root": {
                    "real": format(seal.fixed_root.real, ".17g"),
                    "imaginary": format(seal.fixed_root.imag, ".17g"),
                },
                "root_dependency_key": (
                    None
                    if root_promotion_group is None
                    else root_promotion_group.dependency_key.to_mapping()
                ),
            }
            receipts.append({
                **root_content,
                "receipt_sha256": hashlib.sha256(
                    canonical_json_bytes(root_content)
                ).hexdigest(),
            })

        background_cache_key, background_reuse_key = _promoted_background_key(
            leaf, seal, digits
        )
        cached_background = promoted_background_cache.get(background_cache_key)
        acquired_background = False
        immediate_background_receipt: Mapping[str, object] | None = None
        resumed_own_background = False
        if cached_background is not None:
            retained_samples = cached_background.get("background_samples")
            if (
                not isinstance(retained_samples, tuple)
                or tuple(sample.role for sample in retained_samples)
                != tuple(_PROMOTED_BACKGROUND_SAMPLE_ROLES)
                or cached_background.get("reuse_key") != background_reuse_key
            ):
                raise ValueError("conflicting promoted background")
            resumed_own_background = (
                cached_background.get("queue_ordinal") == entry["queue_ordinal"]
                and cached_background.get("leaf_id") == entry["leaf_id"]
            )
            if resumed_own_background:
                # The first five samples were durably acquired by an
                # interrupted attempt of this exact route. They remain part
                # of this route's retained accounting without being rerun.
                sample_count += len(retained_samples)
                worker_launches += 1
        requested_sample_roles = tuple(_PROMOTED_COMPONENT_SAMPLE_ROLES)
        try:
            if cached_background is None:
                if background_checkpoint is None:
                    raise ValueError(
                        "promoted work requires background checkpointing before "
                        "mechanism samples"
                    )
                worker_launches += 1
                background_batch = backend.fixed_root_survey_batch(
                    leaf.job,
                    fixed_root=seal.fixed_root,
                    root_seal_sha256=seal.root_seal_sha256,
                    branch_identity=seal.branch_identity,
                    plan=FixedRootSurveyPlan.CANONICAL_BACKGROUND_FIVE,
                )
                if not isinstance(background_batch, JuliaFixedRootSurveyBatch):
                    raise ValueError("promoted backend returned an invalid survey batch")
                if (
                    background_batch.precision_tier.value != f"bigfloat-{digits}"
                    or background_batch.root_seal_sha256 != seal.root_seal_sha256
                    or background_batch.root_read_count != 0
                    or background_batch.julia_launch_count != 1
                    or background_batch.sample_roles
                    != tuple(_PROMOTED_BACKGROUND_SAMPLE_ROLES)
                ):
                    raise ValueError("promoted background acquisition batch is invalid")
                background_samples = tuple(background_batch.samples)
                cache_entry = {
                    "background_sha256": None,
                    "background_batch": background_batch,
                    "background_samples": background_samples,
                    "background_receipt": None,
                    "queue_ordinal": int(entry["queue_ordinal"]),
                    "leaf_id": str(entry["leaf_id"]),
                    "reuse_key": copy.deepcopy(dict(background_reuse_key)),
                }
                promoted_background_cache[background_cache_key] = cache_entry
                immediate_background_receipt = _promoted_background_receipt(
                    batch=background_batch,
                    cache_key_sha256=background_cache_key,
                    reuse_key=background_reuse_key,
                    source_queue_ordinal=int(entry["queue_ordinal"]),
                    source_leaf_id=str(entry["leaf_id"]),
                )
                cache_entry["background_sha256"] = immediate_background_receipt[
                    "background_sha256"
                ]
                cache_entry["background_receipt"] = immediate_background_receipt
                background_checkpoint(immediate_background_receipt)
                acquired_background = True
                cached_background = cache_entry

            worker_launches += 1
            executed_batch = backend.fixed_root_survey_batch(
                leaf.job,
                fixed_root=seal.fixed_root,
                root_seal_sha256=seal.root_seal_sha256,
                branch_identity=seal.branch_identity,
                plan=FixedRootSurveyPlan.MECHANISM_COMPONENT_FOUR,
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
                checkpoint_bf40_before_bf80(decision.failure_code)
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
        if not isinstance(executed_batch, JuliaFixedRootSurveyBatch):
            raise ValueError("promoted backend returned an invalid survey batch")
        if (
            executed_batch.precision_tier.value != f"bigfloat-{digits}"
            or executed_batch.root_seal_sha256 != seal.root_seal_sha256
            or executed_batch.root_read_count != 0
            or executed_batch.julia_launch_count != 1
        ):
            raise ValueError("promoted fixed-root survey batch budget mismatch")
        if executed_batch.sample_roles != tuple(_PROMOTED_COMPONENT_SAMPLE_ROLES):
            raise ValueError("promoted mechanism sample plan is invalid")
        if cached_background is None:
            raise ValueError("promoted background was not retained before component")
        background_batch = cached_background.get("background_batch")
        background_receipt = cached_background.get("background_receipt")
        if not isinstance(background_batch, JuliaFixedRootSurveyBatch) or not isinstance(
            background_receipt, Mapping
        ):
            raise ValueError(
                "legacy promoted background cannot be mixed into a v2 component"
            )
        cached_sha256 = cached_background.get("background_sha256")
        if cached_sha256 != background_receipt.get("background_sha256"):
            raise ValueError("conflicting promoted background")
        binding = PromotedBackgroundBinding(
            background_receipt_sha256=str(background_receipt["receipt_sha256"]),
            background_worker_request_sha256=background_batch.request_sha256,
            background_sha256=str(cached_sha256),
        )
        calculation = PromotedExteriorCalculationResult(
            component_batch=executed_batch,
            background=binding,
        )
        composite = PromotedFixedRootComposite(
            background_batch=background_batch,
            component_batch=executed_batch,
            background_receipt_sha256=binding.background_receipt_sha256,
        )
        sample_count += len(requested_sample_roles)
        if acquired_background:
            sample_count += len(_PROMOTED_BACKGROUND_SAMPLE_ROLES)
        receipts.append(copy.deepcopy(dict(background_receipt)))
        calculation_mapping = calculation.to_mapping()
        receipts.append({
            "schema": "windows-solver.promoted-exterior-calculation-receipt/2",
            "calculation": calculation_mapping,
        })
        if determinant_error_store is not None:
            # This call deliberately preserves raw channels only.  It cannot
            # issue a SCREENED determinant disk before independent admission.
            retain_uncalibrated_determinant_error_evidence(
                determinant_error_store,
                leaf.job,
                executed_batch,
                root_seal_sha256=seal.root_seal_sha256,
            )
        determinant_error_evidence = None
        calculation_chain.append(copy.deepcopy(dict(calculation_mapping)))
        if execution_mode is PromotedExecutionMode.CALCULATE_ONLY:
            if raw_checkpoint is None:
                raise ValueError(
                    "CALCULATE_ONLY promoted work requires raw calculation checkpointing"
                )
            raw_outcome = PromotedPassOutcome(
                disposition=SurveyDisposition.CALCULATED_AWAITING_ADMISSION,
                reason_code="RAW_PROMOTED_EXTERIOR_CALCULATION_RETAINED",
                precision_tiers=tuple(tiers),
                operation_identity="promoted-exterior-calculation/v2",
                sample_count=sample_count,
                root_read_count=root_reads,
                worker_launch_count=worker_launches,
                evidence_receipts=tuple(receipts),
                calculation_artifact=calculation_mapping,
                calculation_chain=tuple(calculation_chain),
            )
            # The checkpoint must include the completed numerical timing too;
            # an interrupt after this point must not erase the duration of a
            # worker return that is already durable.
            timing_recorder.complete_tier()
            source_calculation_stage_sha256 = raw_checkpoint(raw_outcome)
            if not isinstance(source_calculation_stage_sha256, str) or len(
                source_calculation_stage_sha256
            ) != 64:
                raise ValueError("raw promoted calculation checkpoint is invalid")
            # CALCULATE_ONLY deliberately ends after durable retention.  The
            # exact review/admission path will derive screened uncertainty and
            # the terminal record from this artifact; no transient screening
            # decision is allowed to choose publication here.
            outcome = PromotedPassOutcome(
                disposition=SurveyDisposition.CALCULATED_AWAITING_ADMISSION,
                reason_code="AWAITING_INDEPENDENT_REVIEW_ADMISSION",
                precision_tiers=tuple(tiers),
                operation_identity="promoted-exterior-calculation/v2",
                sample_count=sample_count,
                root_read_count=root_reads,
                worker_launch_count=worker_launches,
                evidence_receipts=tuple(receipts),
                calculation_artifact=calculation_mapping,
                source_calculation_stage_sha256=source_calculation_stage_sha256,
                calculation_chain=tuple(calculation_chain),
            )
            return outcome
        screening = screen_promoted_fixed_root_samples(
            composite.samples,
            frequency_step=composite.frequency_step,
            coordinate_step=composite.coordinate_step,
            determinant_error_evidence=determinant_error_evidence,
        )
        receipts.append({
            "schema": "windows-solver.promoted-fixed-root-composite-receipt/2",
            "composite": composite.to_mapping(),
            "screening": _screening_receipt(screening),
        })
        if determinant_error_evidence is not None:
            receipts.extend(determinant_error_evidence.to_mappings())
        if (
            screening.disposition is Binary64SurveyDisposition.PRODUCED
            and execution_mode is not PromotedExecutionMode.CALCULATE_ONLY
        ):
            built = produced_record_builder(leaf, composite, screening, digits)
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
                calculation_artifact=calculation_mapping,
                source_calculation_stage_sha256=source_calculation_stage_sha256,
                calculation_chain=tuple(calculation_chain),
            )
            timing_recorder.complete_tier()
            return outcome
        reason = str(screening.reason_code)
        if execution_mode is PromotedExecutionMode.CALCULATE_ONLY:
            outcome = PromotedPassOutcome(
                disposition=SurveyDisposition.CALCULATED_AWAITING_ADMISSION,
                reason_code="AWAITING_INDEPENDENT_REVIEW_ADMISSION",
                precision_tiers=tuple(tiers),
                sample_count=sample_count,
                root_read_count=root_reads,
                worker_launch_count=worker_launches,
                evidence_receipts=tuple(receipts),
                calculation_artifact=calculation_mapping,
                source_calculation_stage_sha256=source_calculation_stage_sha256,
                calculation_chain=tuple(calculation_chain),
            )
            timing_recorder.complete_tier()
            return outcome
        if reason not in PROMOTION_ALLOWLIST:
            raise ValueError(
                f"promoted screening returned an unknown reason: {reason}"
            )
        if digits == 40:
            timing_recorder.complete_tier()
            checkpoint_bf40_before_bf80(reason)
            continue
        outcome = PromotedPassOutcome(
            disposition=SurveyDisposition.UNRESOLVED,
            reason_code=reason,
            precision_tiers=tuple(tiers),
            sample_count=sample_count,
            root_read_count=root_reads,
            worker_launch_count=worker_launches,
            evidence_receipts=tuple(receipts),
            calculation_artifact=calculation_mapping,
            source_calculation_stage_sha256=source_calculation_stage_sha256,
            calculation_chain=tuple(calculation_chain),
        )
        timing_recorder.complete_tier()
        return outcome
    raise AssertionError("promoted survey precision ladder did not terminate")


def _retained_promoted_stage(
    *,
    leaf: object,
    queue_entry: Mapping[str, object],
    queue_ordinal: int,
    route: str,
    outcome: PromotedPassOutcome,
    preflight: PromotedExecutionPreflight,
    layer1_lock_receipt_sha256: str,
    scientific_computation_identity: str,
    admission_state: str = "AWAITING_ADMISSION",
    next_precision_tier: str | None = None,
    numerical_disposition: str | None = None,
) -> dict[str, object]:
    """Authenticate all current-run numerics without admitting their claims."""

    raw_batches: list[dict[str, object]] = []
    disagreement_terms: list[dict[str, object]] = []

    def retain_batch(raw_batch: object) -> None:
        if not isinstance(raw_batch, Mapping):
            raise ValueError("promoted calculation batch is invalid")
        batch = copy.deepcopy(dict(raw_batch))
        raw_batches.append(batch)
        samples = batch.get("samples")
        if not isinstance(samples, list):
            raise ValueError("promoted calculation batch samples are invalid")
        for sample in samples:
            evidence = (
                sample.get("determinant_error_evidence")
                if isinstance(sample, Mapping)
                else None
            )
            if isinstance(evidence, Mapping):
                disagreement_terms.append(copy.deepcopy(dict(evidence)))

    for receipt in outcome.evidence_receipts:
        if not isinstance(receipt, Mapping):
            raise ValueError("promoted calculation receipt is invalid")
        batch = receipt.get("batch")
        if isinstance(batch, Mapping):
            retain_batch(batch)
        background_batch = receipt.get("background_worker_batch")
        if isinstance(background_batch, Mapping):
            retain_batch(background_batch)
        calculation = receipt.get("calculation")
        if isinstance(calculation, Mapping):
            component_batch = calculation.get("component_worker_batch")
            if isinstance(component_batch, Mapping):
                retain_batch(component_batch)
    retained_record = (
        None if outcome.record is None else copy.deepcopy(dict(outcome.record))
    )
    if retained_record is not None:
        stages = retained_record.get("stages")
        if isinstance(stages, list):
            for stage in stages:
                component = (
                    stage.get("component_result")
                    if isinstance(stage, Mapping)
                    else None
                )
                raw_result = (
                    component.get("result")
                    if isinstance(component, Mapping)
                    else None
                )
                if isinstance(raw_result, Mapping):
                    raw_batches.append(copy.deepcopy(dict(raw_result)))
    calculation_artifact = (
        None
        if outcome.calculation_artifact is None
        else copy.deepcopy(dict(outcome.calculation_artifact))
    )
    if not all(isinstance(item, Mapping) for item in outcome.calculation_chain):
        raise ValueError("retained promoted calculation chain is invalid")
    calculation_chain = [
        copy.deepcopy(dict(item)) for item in outcome.calculation_chain
    ]
    if calculation_artifact is not None:
        artifact_digest = calculation_artifact.get("calculation_sha256")
        artifact_content = {
            key: item
            for key, item in calculation_artifact.items()
            if key != "calculation_sha256"
        }
        if (
            not isinstance(artifact_digest, str)
            or artifact_digest != hashlib.sha256(
                canonical_json_bytes(artifact_content)
            ).hexdigest()
        ):
            raise ValueError("retained promoted calculation artifact is invalid")
    material: dict[str, object] = {
        "schema": "windows-solver.promoted-calculation-stage/2",
        "queue_ordinal": queue_ordinal,
        "leaf_id": str(queue_entry["leaf_id"]),
        "scientific_computation_identity": scientific_computation_identity,
        "route": route,
        "execution_mode": preflight.mode.value,
        "admission_state": admission_state,
        "next_precision_tier": next_precision_tier,
        "layer1_lock_receipt_sha256": layer1_lock_receipt_sha256,
        "source_fingerprint_sha256": queue_entry["source_fingerprint_sha256"],
        "predecessor_stage_sha256": queue_entry["source_stage_sha256"],
        "source_root_seal_sha256": queue_entry["source_root_seal_sha256"],
        "calibration_receipt_sha256": preflight.calibration_receipt_sha256,
        "backend_identity_sha256": leaf.job.backend_identity.identity_sha256,
        "numerical_control_identity_sha256": leaf.job.policy.identity_sha256,
        "operation_identity": outcome.operation_identity,
        "precision_tiers": list(outcome.precision_tiers),
        "numerical_disposition": (
            outcome.disposition.value
            if numerical_disposition is None
            else numerical_disposition
        ),
        "reason_code": outcome.reason_code,
        "calculation_artifact": calculation_artifact,
        "source_calculation_stage_sha256": (
            outcome.source_calculation_stage_sha256
        ),
        "calculation_chain": calculation_chain,
        "raw_promoted_batches": raw_batches,
        "current_run_disagreement_terms": disagreement_terms,
        "retained_record": retained_record,
        "retained_record_stage_sha256": outcome.stage_sha256,
        "source_record_sha256": outcome.source_record_sha256,
        "source_record_stage_sha256": outcome.source_stage_sha256,
        "receipts": [copy.deepcopy(dict(item)) for item in outcome.evidence_receipts],
        "sample_count": outcome.sample_count,
        "sample_limit": outcome.sample_limit,
        "root_read_count": outcome.root_read_count,
        "root_read_limit": outcome.root_read_limit,
        "worker_launch_count": outcome.worker_launch_count,
        "worker_launch_limit": outcome.worker_launch_limit,
        "tier_timing": [copy.deepcopy(dict(item)) for item in outcome.tier_timing],
        "session_fragments": [
            copy.deepcopy(dict(item)) for item in outcome.session_fragments
        ],
    }
    return {
        **material,
        "stage_sha256": hashlib.sha256(canonical_json_bytes(material)).hexdigest(),
    }


def _commit_promoted_continuation(
    checkpoint: Mapping[str, object],
    *,
    leaf: object,
    queue_ordinal: int,
    route: str,
    outcome: PromotedPassOutcome,
    execution_preflight: PromotedExecutionPreflight | None,
    layer1_lock_receipt_sha256: str | None,
    scientific_computation_identity: str,
    layer1_guard: object | None = None,
) -> dict[str, object]:
    """Persist an allowlisted BF40 outcome before starting BF80."""

    if (
        execution_preflight is None
        or execution_preflight.mode is PromotedExecutionMode.BLOCK_ALL
        or layer1_lock_receipt_sha256 is None
    ):
        raise ValueError("promoted continuation lacks authenticated route policy")
    result = validate_schema11_checkpoint(checkpoint)
    queue_entry = result["promotion_queue"]["entries"][queue_ordinal]
    stage = _retained_promoted_stage(
        leaf=leaf,
        queue_entry=queue_entry,
        queue_ordinal=queue_ordinal,
        route=route,
        outcome=outcome,
        preflight=execution_preflight,
        layer1_lock_receipt_sha256=layer1_lock_receipt_sha256,
        scientific_computation_identity=scientific_computation_identity,
        admission_state="NUMERICAL_CONTINUATION",
        next_precision_tier="BF80",
        numerical_disposition="AWAITING_BF80",
    )
    return retain_promoted_continuation(
        result,
        queue_ordinal=queue_ordinal,
        promoted_stage=stage,
        execution_mode=execution_preflight.mode.value,
        layer1_guard=layer1_guard,
    )


def _commit_promoted_raw_calculation(
    checkpoint: Mapping[str, object],
    *,
    leaf: object,
    queue_ordinal: int,
    route: str,
    outcome: PromotedPassOutcome,
    execution_preflight: PromotedExecutionPreflight | None,
    layer1_lock_receipt_sha256: str | None,
    scientific_computation_identity: str,
    layer1_guard: object | None = None,
) -> dict[str, object]:
    """Persist a returned worker artifact before a reducer can inspect it."""

    if (
        execution_preflight is None
        or execution_preflight.mode is not PromotedExecutionMode.CALCULATE_ONLY
        or layer1_lock_receipt_sha256 is None
        or outcome.calculation_artifact is None
    ):
        raise ValueError("raw promoted calculation lacks authenticated route policy")
    result = validate_schema11_checkpoint(checkpoint)
    queue_entry = result["promotion_queue"]["entries"][queue_ordinal]
    stage = _retained_promoted_stage(
        leaf=leaf,
        queue_entry=queue_entry,
        queue_ordinal=queue_ordinal,
        route=route,
        outcome=outcome,
        preflight=execution_preflight,
        layer1_lock_receipt_sha256=layer1_lock_receipt_sha256,
        scientific_computation_identity=scientific_computation_identity,
        admission_state="CALCULATED_PENDING_DERIVATION",
        numerical_disposition="RAW_CALCULATION_RETAINED",
    )
    return retain_promoted_raw_calculation(
        result,
        queue_ordinal=queue_ordinal,
        promoted_stage=stage,
        execution_mode=execution_preflight.mode.value,
        disposition_receipt={
            "schema": "windows-solver.promoted-raw-calculation-retention/2",
            "queue_ordinal": queue_ordinal,
            "leaf_id": str(queue_entry["leaf_id"]),
            "route": route,
            "reason_code": "RAW_PROMOTED_CALCULATION_RETAINED",
            "calculation_sha256": outcome.calculation_artifact[
                "calculation_sha256"
            ],
        },
        layer1_guard=layer1_guard,
    )


def _commit_promoted_outcome(
    checkpoint: Mapping[str, object],
    *,
    leaf: object,
    leaf_id: str,
    queue_ordinal: int,
    queue_kind: PromotionQueueKind,
    outcome: PromotedPassOutcome,
    route: str,
    execution_preflight: PromotedExecutionPreflight | None,
    layer1_lock_receipt_sha256: str | None,
    scientific_computation_identity: str,
    record_validator: RecordValidator | None = None,
    layer1_guard: object | None = None,
) -> dict[str, object]:
    result = validate_schema11_checkpoint(checkpoint)
    retained_exterior_worker_limit = (
        execution_preflight is not None
        and execution_preflight.mode is PromotedExecutionMode.CALCULATE_ONLY
        and route == "EXTERIOR_BF40"
    )
    worker_launch_limit = (
        (4 if queue_kind is PromotionQueueKind.RESPONSE else 5)
        if retained_exterior_worker_limit
        else (
            2
            if queue_kind is PromotionQueueKind.RESPONSE
            else outcome.worker_launch_limit
        )
    )
    if execution_preflight is not None and (
        execution_preflight.mode is PromotedExecutionMode.CALCULATE_ONLY
        and outcome.disposition
        in {
            SurveyDisposition.COMPLETED,
            SurveyDisposition.CALCULATED_AWAITING_ADMISSION,
            SurveyDisposition.UNRESOLVED,
            SurveyDisposition.DEFERRED,
            SurveyDisposition.REJECTED,
        }
    ):
        if layer1_lock_receipt_sha256 is None:
            raise ValueError("retained promoted stage lacks the Layer-1 lock receipt")
        queue_entry = result["promotion_queue"]["entries"][queue_ordinal]
        promoted_stage = _retained_promoted_stage(
            leaf=leaf,
            queue_entry=queue_entry,
            queue_ordinal=queue_ordinal,
            route=route,
            outcome=outcome,
            preflight=execution_preflight,
            layer1_lock_receipt_sha256=layer1_lock_receipt_sha256,
            scientific_computation_identity=scientific_computation_identity,
        )
        background_receipts = [
            copy.deepcopy(dict(receipt))
            for receipt in outcome.evidence_receipts
            if isinstance(receipt, Mapping)
            and receipt.get("schema") == _PROMOTED_BACKGROUND_RECEIPT_SCHEMA
        ]
        root_receipts = [
            copy.deepcopy(dict(receipt))
            for receipt in outcome.evidence_receipts
            if isinstance(receipt, Mapping)
            and receipt.get("schema") == _PROMOTED_ROOT_RECEIPT_SCHEMA
        ]
        promoted_background = (
            None
            if not background_receipts
            else {
                "schema": "windows-solver.promoted-background-retention/1",
                "route": route,
                "background_receipts": background_receipts,
            }
        )
        promoted_root = (
            None
            if not root_receipts and route != "HORIZON_BF80"
            else {
                "schema": "windows-solver.promoted-root-retention/1",
                "route": route,
                "root_receipts": root_receipts,
                "source_root_seal_sha256": queue_entry[
                    "source_root_seal_sha256"
                ],
                "retained_horizon_record": (
                    copy.deepcopy(dict(outcome.record))
                    if route == "HORIZON_BF80"
                    and isinstance(outcome.record, Mapping)
                    else None
                ),
            }
        )
        provisional_reuse_receipt = next(
            (
                receipt
                for receipt in outcome.evidence_receipts
                if isinstance(receipt, Mapping)
                and receipt.get("schema")
                == EXTERIOR_PROVISIONAL_REUSE_RECEIPT_SCHEMA
            ),
            None,
        )
        result = retain_promoted_calculation(
            result,
            queue_ordinal=queue_ordinal,
            promoted_stage=promoted_stage,
            execution_mode=execution_preflight.mode.value,
            disposition_receipt={
                "schema": "windows-solver.promoted-admission-pending/1",
                "leaf_id": leaf_id,
                "queue_ordinal": queue_ordinal,
                "route": route,
                "reason_code": "AWAITING_INDEPENDENT_REVIEW_ADMISSION",
                "calibration_receipt_sha256": (
                    execution_preflight.calibration_receipt_sha256
                ),
            },
            provisional_reuse_receipt=provisional_reuse_receipt,
            promoted_background=promoted_background,
            promoted_root=promoted_root,
            layer1_guard=layer1_guard,
        )
        return record_survey_disposition(
            result,
            survey_pass=SurveyPass.PROMOTED,
            leaf_id=leaf_id,
            disposition=SurveyDisposition.CALCULATED_AWAITING_ADMISSION,
            source_record_sha256=outcome.source_record_sha256,
            result_record_sha256=None,
            operation_identity=outcome.operation_identity,
            precision_tiers=outcome.precision_tiers,
            reason_code="AWAITING_INDEPENDENT_REVIEW_ADMISSION",
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
            worker_launch_limit=worker_launch_limit,
            tier_timing=outcome.tier_timing,
            session_fragments=outcome.session_fragments,
            layer1_guard=layer1_guard,
        )
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
        layer1_guard=layer1_guard,
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
        layer1_guard=layer1_guard,
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
    layer1_guard: object | None = None,
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
        layer1_guard=layer1_guard,
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
        layer1_guard=layer1_guard,
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
    provisional_stage_lookup: Callable[
        [object, Mapping[str, object]], Mapping[str, object] | None
    ] | None = None,
    layer1_guard: object | None = None,
    locked_routes_by_ordinal: Mapping[int, object] | None = None,
    promoted_preflights_by_ordinal: Mapping[
        int, PromotedExecutionPreflight
    ] | None = None,
    layer1_lock_receipt_sha256: str | None = None,
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

    result = _intake_checkpoint_records(
        plan,
        checkpoint,
        source_path=checkpoint_path,
        diagnostic_session=diagnostic_session,
    )
    if (
        result["campaign_id"] != selection.campaign_id
        or result["selection_id"] != selection.selection_id
    ):
        raise ValueError("promoted survey checkpoint identity mismatch")
    if (layer1_guard is None) != (locked_routes_by_ordinal is None):
        raise ValueError(
            "promoted survey requires both the Layer-1 guard and typed routes"
        )
    if (promoted_preflights_by_ordinal is None) != (
        layer1_lock_receipt_sha256 is None
    ):
        raise ValueError(
            "promoted survey preflights require the Layer-1 lock receipt"
        )
    if layer1_lock_receipt_sha256 is not None and (
        not isinstance(layer1_lock_receipt_sha256, str)
        or len(layer1_lock_receipt_sha256) != 64
    ):
        raise ValueError("promoted survey Layer-1 lock receipt digest is invalid")
    if layer1_guard is not None:
        for method_name in ("pre_write", "post_write", "post_callback"):
            if not callable(getattr(layer1_guard, method_name, None)):
                raise ValueError("promoted survey Layer-1 guard is invalid")
        if not isinstance(locked_routes_by_ordinal, Mapping):
            raise ValueError("promoted survey locked routes are invalid")
        if provisional_stage_lookup is not None:
            raise ValueError(
                "promoted survey cannot mix typed locked routes with a raw provisional lookup"
            )
        if promoted_preflights_by_ordinal is None:
            raise ValueError("locked promoted survey requires route preflights")
    preflight_campaign_supports(plan, selection.ordered_leaf_ids)
    leaves = {leaf.leaf_id: leaf for leaf in getattr(plan, "leaves")}
    path = Path(checkpoint_path)
    operational_timing = timing_log or CampaignTimingLog(
        path.with_name(f"{path.name}.timing.jsonl")
    )
    make_session_id = session_id_factory or (lambda: uuid4().hex)
    failure_monitor = ProductionFailureMonitor(diagnostic_session=diagnostic_session)

    def persist(value: Mapping[str, object]) -> dict[str, object]:
        candidate = validate_schema11_checkpoint(value)
        if layer1_guard is not None:
            layer1_guard.pre_write(candidate)
        _atomic_json(path, candidate)
        durable = _load_durable_schema11_checkpoint(path)
        if layer1_guard is not None:
            layer1_guard.post_write(durable)
        if checkpoint_committed is not None:
            durable = validate_schema11_checkpoint(checkpoint_committed(durable))
        if layer1_guard is not None:
            layer1_guard.post_callback(durable)
        return durable


    result = persist(result)
    existing_records = {
        record["leaf_id"]: record for record in result["records"]
    }
    completed = unresolved = deferred = rejected = skipped = cache_reused = 0
    terminal_publications = 0
    review_pending = policy_blocked = 0
    route_results: list[PromotedRouteExecutionResult] = []
    promoted_background_cache = _load_promoted_background_cache(result)
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
        if item["disposition"] in _ACTIVE_PROMOTED_QUEUE_DISPOSITIONS
    )
    root_group_members: dict[str, tuple[RootDependencyKey, set[str]]] = {}
    for snapshot in entries:
        if (
            snapshot["disposition"] not in _ACTIVE_PROMOTED_QUEUE_DISPOSITIONS
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
        if snapshot["disposition"] not in _ACTIVE_PROMOTED_QUEUE_DISPOSITIONS:
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
        locked_route = None
        expected_route = (
            "HORIZON_BF80"
            if getattr(leaves[leaf_id], "mechanism_id") == "horizon-admittance"
            else "EXTERIOR_BF40"
        )
        if locked_routes_by_ordinal is not None:
            locked_route = locked_routes_by_ordinal.get(ordinal)
            if locked_route is None:
                raise ValueError("pending promotion has no locked route")
            if (
                getattr(locked_route, "queue_ordinal", None) != ordinal
                or getattr(locked_route, "leaf_id", None) != leaf_id
                or getattr(locked_route, "route", None) != expected_route
                or getattr(locked_route, "minimum_requested_tier", None)
                != snapshot["minimum_requested_tier"]
                or getattr(locked_route, "source_stage_sha256", None)
                != snapshot["source_stage_sha256"]
                or getattr(locked_route, "source_root_seal_sha256", None)
                != snapshot["source_root_seal_sha256"]
                or getattr(locked_route, "source_fingerprint_sha256", None)
                != snapshot.get("source_fingerprint_sha256")
            ):
                raise ValueError("pending promotion diverges from its locked route")
        execution_preflight = (
            None
            if promoted_preflights_by_ordinal is None
            else promoted_preflights_by_ordinal.get(ordinal)
        )
        if promoted_preflights_by_ordinal is not None and execution_preflight is None:
            raise ValueError("pending promotion has no route preflight")
        if execution_preflight is not None and (
            not isinstance(execution_preflight, PromotedExecutionPreflight)
            or execution_preflight.route != expected_route
        ):
            raise ValueError("promoted route preflight binding is invalid")
        execution_mode = (
            PromotedExecutionMode.CALCULATE_AND_ADMIT
            if execution_preflight is None
            else execution_preflight.mode
        )
        continuation_stage: Mapping[str, object] | None = None
        raw_calculation_stage: Mapping[str, object] | None = None
        retained_stage_sha256 = snapshot.get("retained_promoted_stage_sha256")
        if retained_stage_sha256 is not None:
            stage_bucket = result["promoted_stage_ledger"].get(str(ordinal))
            candidate = (
                stage_bucket.get(leaf_id)
                if isinstance(stage_bucket, Mapping)
                else None
            )
            if (
                not isinstance(candidate, Mapping)
                or candidate.get("stage_sha256") != retained_stage_sha256
                or candidate.get("route") != expected_route
                or candidate.get("execution_mode") != execution_mode.value
                or candidate.get("scientific_computation_identity")
                != selection.scientific_identities[leaf_id]
            ):
                raise ValueError("pending promotion retained state is invalid")
            if candidate.get("admission_state") == "NUMERICAL_CONTINUATION":
                continuation_stage = candidate
            elif candidate.get("admission_state") == "CALCULATED_PENDING_DERIVATION":
                raw_calculation_stage = candidate
            else:
                raise ValueError("pending promotion retained state is unsupported")
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

        def checkpoint_raw_outcome(raw: PromotedPassOutcome) -> str:
            """Persist a promoted worker return before a reducer sees it."""

            nonlocal result, committed_before_leaf
            result = guarded(lambda: _commit_promoted_raw_calculation(
                result,
                leaf=leaf,
                queue_ordinal=ordinal,
                route=expected_route,
                outcome=raw,
                execution_preflight=execution_preflight,
                layer1_lock_receipt_sha256=layer1_lock_receipt_sha256,
                scientific_computation_identity=(
                    selection.scientific_identities[leaf_id]
                ),
                layer1_guard=layer1_guard,
            ))
            assert isinstance(result, dict)
            result = persist(result)
            committed_before_leaf = result
            digest = result["promotion_queue"]["entries"][ordinal][
                "retained_promoted_stage_sha256"
            ]
            if not isinstance(digest, str):
                raise ValueError("raw promoted checkpoint digest is invalid")
            return digest

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

        # PR69 cache-first architecture: terminal-cache discovery and
        # conflict detection precede the exterior provisional-stage
        # requirement. If a promoted leaf already has an exact
        # authenticated terminal record — from the checkpoint or the
        # solved-leaf store — reuse it and skip backend, provisional
        # lookup, and root work entirely. If two exact terminal sources
        # disagree, that is a system failure before backend construction.
        # The provisional-stage check only runs on a genuine cache miss,
        # further down in the exterior branch.
        provisional_predecessor_receipt: Mapping[str, object] | None = None

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
            if cache_lookup.status in {
                SolvedLeafLookupStatus.HIT,
                SolvedLeafLookupStatus.STALE,
            }:
                cache_record = guarded(
                    lambda: _current_terminal_cache_record(
                        plan,
                        leaf_id,
                        cache_lookup,
                        record_validator=record_validator,
                        diagnostic_session=diagnostic_session,
                    )
                )
                if cache_record is not None:
                    assert isinstance(cache_record, Mapping)
                    if (
                        retained is not None
                        and canonical_json_bytes(retained)
                        != canonical_json_bytes(cache_record)
                    ):
                        guarded(
                            lambda: (_ for _ in ()).throw(
                                TerminalCacheConflictError()
                            )
                        )
                    if retained is None:
                        retained = cache_record
                        result = guarded(
                            lambda: add_numerical_record(result, retained)
                        )
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
                layer1_guard=layer1_guard,
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

        if raw_calculation_stage is not None:
            if expected_route == "EXTERIOR_BF40":
                outcome = guarded(lambda: _resumed_promoted_exterior_outcome(
                    raw_calculation_stage,
                    promoted_background_cache=promoted_background_cache,
                ))
            elif expected_route == "HORIZON_BF80":
                outcome = guarded(lambda: _resumed_promoted_horizon_outcome(
                    raw_calculation_stage
                ))
            else:
                raise ValueError("retained promoted calculation route is invalid")
        elif execution_mode is PromotedExecutionMode.BLOCK_ALL:
            outcome = PromotedPassOutcome(
                disposition=SurveyDisposition.DEFERRED,
                reason_code="BLOCKED_BY_ADMISSION_POLICY",
                precision_tiers=(),
                operation_identity="promoted-policy-preflight/v1",
                sample_limit=0,
                root_read_limit=0,
                worker_launch_limit=0,
            )
        elif leaf.mechanism_id == "horizon-admittance":
            if execution_mode is not PromotedExecutionMode.CALCULATE_ONLY:
                raise ValueError(
                    "promoted horizon calculation requires independent admission"
                )
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
            if outcome.calculation_artifact is None:
                raise ValueError("promoted horizon worker return lacks an artifact")
            source_calculation_stage_sha256 = guarded(
                lambda: checkpoint_raw_outcome(outcome)
            )
            outcome = replace(
                outcome,
                reason_code="AWAITING_INDEPENDENT_REVIEW_ADMISSION",
                source_calculation_stage_sha256=source_calculation_stage_sha256,
            )
        else:
            # Cache-first: this branch is only reached on a genuine
            # terminal-cache miss for exterior leaves. Only here does the
            # exterior RESPONSE provisional-stage requirement apply.
            if (
                snapshot["queue_kind"] == PromotionQueueKind.RESPONSE.value
                and snapshot.get("source_record_sha256") is None
                and continuation_stage is None
            ):
                if locked_route is not None:
                    provisional_stage = locked_route.provisional_stage
                elif provisional_stage_lookup is not None:
                    provisional_stage = guarded(
                        lambda: provisional_stage_lookup(leaf, snapshot)
                    )
                else:
                    provisional_stage = None
                if not isinstance(provisional_stage, Mapping):
                    guarded(
                        lambda: (_ for _ in ()).throw(
                            ValueError(
                                "exterior RESPONSE promotion lacks a provisional stage"
                            )
                        )
                    )
                    raise AssertionError(
                        "missing provisional stage guard returned"
                    )
                source_root_seal_sha256 = snapshot.get("source_root_seal_sha256")
                if not isinstance(source_root_seal_sha256, str):
                    guarded(
                        lambda: (_ for _ in ()).throw(
                            ValueError(
                                "exterior provisional promotion lacks a root seal"
                            )
                        )
                    )
                    raise AssertionError(
                        "missing provisional root guard returned"
                    )
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

            def execute_exterior() -> PromotedPassOutcome:
                recorder = TimingSessionRecorder(
                    log=operational_timing,
                    session_id=make_session_id(),
                    leaf_id=leaf_id,
                    execution_profile="SURVEY",
                    survey_pass="promoted",
                    clock=clock,
                )
                prior_tier_timing: tuple[Mapping[str, object], ...] = ()
                prior_session_fragments: tuple[Mapping[str, object], ...] = ()
                if continuation_stage is not None:
                    saved_tier_timing = continuation_stage.get("tier_timing")
                    saved_session_fragments = continuation_stage.get(
                        "session_fragments"
                    )
                    if (
                        not isinstance(saved_tier_timing, list)
                        or not isinstance(saved_session_fragments, list)
                        or not all(
                            isinstance(item, Mapping)
                            for item in saved_tier_timing + saved_session_fragments
                        )
                    ):
                        raise ValueError("promoted continuation timing is invalid")
                    prior_tier_timing = tuple(saved_tier_timing)
                    prior_session_fragments = tuple(saved_session_fragments)

                def checkpoint_bf40(partial: PromotedPassOutcome) -> None:
                    nonlocal result, committed_before_leaf
                    summary = fold_timing_fragments(recorder.fragments)
                    retained_partial = replace(
                        partial,
                        tier_timing=summary.tier_timing_mappings(),
                        session_fragments=tuple(
                            fragment.to_mapping() for fragment in recorder.fragments
                        ),
                    )
                    result = guarded(lambda: _commit_promoted_continuation(
                        result,
                        leaf=leaf,
                        queue_ordinal=ordinal,
                        route=expected_route,
                        outcome=retained_partial,
                        execution_preflight=execution_preflight,
                        layer1_lock_receipt_sha256=layer1_lock_receipt_sha256,
                        scientific_computation_identity=(
                            selection.scientific_identities[leaf_id]
                        ),
                        layer1_guard=layer1_guard,
                    ))
                    assert isinstance(result, dict)
                    result = persist(result)
                    committed_before_leaf = result

                def checkpoint_background(
                    receipt: Mapping[str, object],
                ) -> None:
                    """Commit shared samples before their mechanism samples run."""

                    nonlocal result, committed_before_leaf
                    result = guarded(lambda: retain_promoted_background(
                        result,
                        queue_ordinal=ordinal,
                        route=expected_route,
                        background_receipt=receipt,
                        layer1_guard=layer1_guard,
                    ))
                    assert isinstance(result, dict)
                    result = persist(result)
                    committed_before_leaf = result

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
                            execution_mode=execution_mode,
                            promoted_background_cache=promoted_background_cache,
                            continuation_stage=continuation_stage,
                            tier_checkpoint=(
                                checkpoint_bf40
                                if execution_preflight is not None
                                and layer1_lock_receipt_sha256 is not None
                                else None
                            ),
                            background_checkpoint=(
                                checkpoint_background
                            ),
                            raw_checkpoint=(
                                lambda raw: checkpoint_raw_outcome(
                                    replace(
                                        raw,
                                        tier_timing=fold_timing_fragments(
                                            recorder.fragments
                                        ).tier_timing_mappings(),
                                        session_fragments=tuple(
                                            fragment.to_mapping()
                                            for fragment in recorder.fragments
                                        ),
                                    )
                                )
                                if execution_mode
                                is PromotedExecutionMode.CALCULATE_ONLY
                                else None
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
                    tier_timing=(
                        prior_tier_timing
                        + tuple(timed_outcome.tier_timing)
                        + summary.tier_timing_mappings()
                    ),
                    session_fragments=(
                        prior_session_fragments
                        + tuple(timed_outcome.session_fragments)
                        + tuple(
                            fragment.to_mapping() for fragment in recorder.fragments
                        )
                    ),
                )

            outcome = guarded(execute_exterior)
        assert isinstance(outcome, PromotedPassOutcome)
        result = guarded(lambda: _commit_promoted_outcome(
            result,
            leaf=leaf,
            leaf_id=leaf_id,
            queue_ordinal=ordinal,
            queue_kind=PromotionQueueKind(snapshot["queue_kind"]),
            outcome=outcome,
            route=expected_route,
            execution_preflight=execution_preflight,
            layer1_lock_receipt_sha256=layer1_lock_receipt_sha256,
            scientific_computation_identity=selection.scientific_identities[
                leaf_id
            ],
            record_validator=record_validator,
            layer1_guard=layer1_guard,
        ))
        assert isinstance(result, dict)
        queue_disposition = result["promotion_queue"]["entries"][ordinal][
            "disposition"
        ]
        if queue_disposition == PromotionQueueDisposition.AWAITING_ADMISSION.value:
            review_pending += 1
        elif outcome.disposition is SurveyDisposition.COMPLETED:
            completed += 1
        elif outcome.disposition is SurveyDisposition.UNRESOLVED:
            unresolved += 1
        elif outcome.disposition is SurveyDisposition.DEFERRED:
            deferred += 1
            if execution_mode is PromotedExecutionMode.BLOCK_ALL:
                policy_blocked += 1
        elif outcome.disposition is SurveyDisposition.REJECTED:
            rejected += 1
        result = persist(result)
        route_results.append(PromotedRouteExecutionResult(
            queue_ordinal=ordinal,
            leaf_id=leaf_id,
            route=expected_route,
            execution_mode=execution_mode.value,
            result_code=(
                "AWAITING_ADMISSION"
                if result["promotion_queue"]["entries"][ordinal]["disposition"]
                == PromotionQueueDisposition.AWAITING_ADMISSION.value
                else outcome.reason_code
            ),
            numerical_work_performed=(
                outcome.sample_count > 0
                or outcome.root_read_count > 0
                or outcome.worker_launch_count > 0
            ),
            admission_state=(
                "AWAITING_ADMISSION"
                if result["promotion_queue"]["entries"][ordinal]["disposition"]
                == PromotionQueueDisposition.AWAITING_ADMISSION.value
                else "NOT_APPLICABLE"
            ),
        ))
        if (
            outcome.record is not None
            and outcome.disposition is SurveyDisposition.COMPLETED
            and execution_mode is PromotedExecutionMode.CALCULATE_AND_ADMIT
            and outcome.record.get("state") == "PRODUCED"
            and terminal_record_committed is not None
        ):
            try:
                terminal_record_committed(leaf, outcome.record)
                terminal_publications += 1
            except KeyboardInterrupt:
                raise
            except Exception as error:
                abort_unexpected_system_failure(
                    result,
                    leaf_id=leaf_id,
                    error=error,
                    persist_checkpoint=lambda value: persist(value),
                )
        if (
            queue_disposition
            != PromotionQueueDisposition.AWAITING_ADMISSION.value
            and outcome.disposition not in {
                SurveyDisposition.COMPLETED,
                SurveyDisposition.CALCULATED_AWAITING_ADMISSION,
                SurveyDisposition.CACHE_REUSED,
                SurveyDisposition.SUPERSEDED_BY_CACHE,
            }
            and execution_mode is not PromotedExecutionMode.BLOCK_ALL
        ):
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
        reported_worker_launch_limit = (
            (4 if PromotionQueueKind(snapshot["queue_kind"])
             is PromotionQueueKind.RESPONSE else 5)
            if (
                execution_mode is PromotedExecutionMode.CALCULATE_ONLY
                and expected_route == "EXTERIOR_BF40"
            )
            else (
                2
                if PromotionQueueKind(snapshot["queue_kind"])
                is PromotionQueueKind.RESPONSE
                else outcome.worker_launch_limit
            )
        )
        effective_disposition = (
            SurveyDisposition.CALCULATED_AWAITING_ADMISSION
            if result["promotion_queue"]["entries"][ordinal]["disposition"]
            == PromotionQueueDisposition.AWAITING_ADMISSION.value
            else outcome.disposition
        )
        with progress_scope(
            leaf_id=leaf_id,
            execution_profile="SURVEY",
            survey_pass="promoted",
            pass_disposition=effective_disposition.value,
            evidence_level=(
                "SCREENED"
                if effective_disposition is SurveyDisposition.COMPLETED
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
            worker_launch_limit=reported_worker_launch_limit,
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
    final_checkpoint = validate_schema11_checkpoint(result)
    if isinstance(locked_routes_by_ordinal, Mapping):
        route_by_ordinal = {
            int(ordinal): str(route.route)
            for ordinal, route in locked_routes_by_ordinal.items()
        }
    else:
        route_by_ordinal = {
            int(entry["queue_ordinal"]): (
                "HORIZON_BF80"
                if entry["minimum_requested_tier"] == "BF80"
                else "EXTERIOR_BF40"
            )
            for entry in final_checkpoint["promotion_queue"]["entries"]
        }
    binary64_ledger = final_checkpoint["survey_pass_ledger"]["binary64"]
    binary64_predecessor_evaluations = sum(
        int(binary64_ledger.get(leaf_id, {}).get("sample_count", 0))
        for leaf_id in selection.ordered_leaf_ids
        if isinstance(binary64_ledger.get(leaf_id), Mapping)
    )
    background_acquired = background_reused = 0
    v2_background_sources: dict[str, int] = {}
    seen_v2_background_receipts: set[str] = set()
    for bucket in final_checkpoint["promoted_background_ledger"].values():
        if not isinstance(bucket, Mapping):
            continue
        for entry in bucket.values():
            payload = entry.get("payload") if isinstance(entry, Mapping) else None
            receipts = (
                payload.get("background_receipts")
                if isinstance(payload, Mapping)
                else None
            )
            if not isinstance(receipts, list):
                continue
            for receipt in receipts:
                if not isinstance(receipt, Mapping):
                    continue
                if receipt.get("schema") == PROMOTED_CANONICAL_BACKGROUND_RECEIPT_SCHEMA:
                    digest = receipt.get("receipt_sha256")
                    source_ordinal = receipt.get("source_queue_ordinal")
                    if (
                        isinstance(digest, str)
                        and isinstance(source_ordinal, int)
                        and digest not in seen_v2_background_receipts
                    ):
                        seen_v2_background_receipts.add(digest)
                        v2_background_sources[digest] = source_ordinal
                        background_acquired += 1
                elif receipt.get("status") == "ACQUIRED":
                    background_acquired += 1
                elif receipt.get("status") == "REUSED":
                    background_reused += 1
    for stage_bucket in final_checkpoint["promoted_stage_ledger"].values():
        if not isinstance(stage_bucket, Mapping):
            continue
        for stage in stage_bucket.values():
            if not isinstance(stage, Mapping) or stage.get("route") != "EXTERIOR_BF40":
                continue
            artifact = stage.get("calculation_artifact")
            binding = artifact.get("background") if isinstance(artifact, Mapping) else None
            digest = (
                binding.get("background_receipt_sha256")
                if isinstance(binding, Mapping)
                else None
            )
            source_ordinal = (
                v2_background_sources.get(digest)
                if isinstance(digest, str)
                else None
            )
            if (
                isinstance(source_ordinal, int)
                and stage.get("queue_ordinal") != source_ordinal
            ):
                background_reused += 1
    queue_entries = final_checkpoint["promotion_queue"]["entries"]
    awaiting_admission = sum(
        entry["disposition"] == PromotionQueueDisposition.AWAITING_ADMISSION.value
        for entry in queue_entries
    )
    admitted = sum(
        entry["disposition"] == PromotionQueueDisposition.COMPLETED.value
        for entry in queue_entries
    )
    screened = sum(
        isinstance(entry, Mapping) and entry.get("evidence_level")
        == EvidenceLevel.SCREENED.value
        for entry in final_checkpoint["evidence_ledger"].values()
    )
    return PromotedSurveyRun(
        checkpoint=final_checkpoint,
        completed_count=completed,
        unresolved_count=unresolved,
        deferred_count=deferred,
        rejected_count=rejected,
        skipped_count=skipped,
        cache_reused_count=cache_reused,
        terminal_cache_discovery=terminal_cache_discovery,
        pass_exhausted=exhaustion.exhausted,
        incomplete_leaf_ids=exhaustion.incomplete_leaf_ids,
        review_pending_count=review_pending,
        policy_blocked_count=policy_blocked,
        route_results=tuple(route_results),
        locked_route_count=len(route_by_ordinal),
        exterior_bf40_route_count=sum(
            route == "EXTERIOR_BF40" for route in route_by_ordinal.values()
        ),
        horizon_bf80_route_count=sum(
            route == "HORIZON_BF80" for route in route_by_ordinal.values()
        ),
        exterior_bf40_executed_count=sum(
            item.route == "EXTERIOR_BF40" and item.numerical_work_performed
            for item in route_results
        ),
        horizon_bf80_executed_count=sum(
            item.route == "HORIZON_BF80" and item.numerical_work_performed
            for item in route_results
        ),
        binary64_predecessor_evaluation_count=binary64_predecessor_evaluations,
        binary64_recomputed_evaluation_count=0,
        promoted_background_acquired_count=background_acquired,
        promoted_background_reused_count=background_reused,
        calculated_awaiting_admission_count=awaiting_admission,
        admitted_count=admitted,
        screened_count=screened,
        terminal_publication_count=terminal_publications,
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


def _load_durable_schema11_checkpoint(path: Path) -> dict[str, object]:
    """Read back an atomic checkpoint before post-write lock validation."""

    try:
        return validate_schema11_checkpoint(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError(f"durable schema-11 checkpoint is invalid: {path}") from error


def dispatch_cache_first(
    selection: RecoverySelection,
    store: SolvedLeafStore,
    *,
    checkpoint_path: str | os.PathLike[str] | Path,
    backend_factory: Callable[[], object],
    execute_misses: Callable[[object], object],
    record_validator: RecordValidator | None = None,
    record_intake_assessor: RecordIntakeAssessor | None = None,
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
        if lookup.status not in {
            SolvedLeafLookupStatus.HIT,
            SolvedLeafLookupStatus.STALE,
        }:
            missing.append(leaf_id)
            continue
        if lookup.receipt is None:
            raise ValueError("solved-leaf cache result has no authenticated receipt")
        record = lookup.receipt["record"]
        if not isinstance(record, Mapping):
            raise ValueError("solved-leaf cache result record is invalid")
        if (
            record.get("schema") == "windows-solver.schema11-numerical-record/1"
            and record_intake_assessor is None
        ):
            raise ValueError("schema-11 cache dispatch requires central record intake")
        intake = (
            None
            if record_intake_assessor is None
            else record_intake_assessor(leaf_id, record)
        )
        if intake is not None:
            if not intake.response_admissible:
                missing.append(leaf_id)
                continue
            admitted = intake.record
            if not isinstance(admitted, Mapping):
                raise ValueError("central record intake result is invalid")
            record = admitted
        if lookup.status is not SolvedLeafLookupStatus.HIT:
            missing.append(leaf_id)
            continue
        if record_intake_assessor is None and record_validator is not None:
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
    "promoted_fixed_root_batch_from_mapping",
    "run_binary64_survey",
    "run_promoted_survey",
]
