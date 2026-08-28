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
    PROMOTED_CALCULATION_STAGE_SCHEMA,
    PROMOTED_CONTROL_CONTINUATION_PROOF_SCHEMA,
    PROMOTED_CONTROL_CONTINUATION_STAGE_SCHEMA,
    PROMOTED_CONTROL_DECISION_SCHEMA,
    PROMOTED_CONTROL_DECISION_STAGE_SCHEMA,
    PROMOTED_HORIZON_CONTROL_DECISION_SCHEMA,
    PROMOTED_HORIZON_CONTROL_RETURN_SCHEMA,
    PROMOTED_POLICY_TERMINAL_DECISION_SCHEMA,
    PROMOTED_POLICY_TERMINAL_STAGE_SCHEMA,
    PROMOTED_CONTROL_RETURN_SCHEMA,
    PROMOTED_CONTROL_RETURN_STAGE_SCHEMA,
    PromotionQueueDisposition,
    PromotionQueueKind,
    SurveyDisposition,
    SurveyPass,
    add_numerical_record,
    append_promotion,
    empty_schema11_checkpoint,
    finish_promotion,
    promoted_artifact_digest,
    promoted_control_terminal_disposition_receipt,
    promoted_policy_terminal_disposition_receipt,
    record_evidence,
    record_survey_disposition,
    retain_promoted_background,
    retain_promoted_calculation,
    retain_promoted_continuation,
    retain_promoted_control_decision,
    retain_promoted_control_return,
    retain_promoted_control_terminal,
    retain_promoted_policy_terminal,
    retain_promoted_raw_calculation,
    retain_promoted_terminal_reduction,
    validate_schema11_checkpoint,
)
from .campaign_recovery import (
    RecoverySelection,
    validate_checkpoint_bound_promoted_recovery_selection,
)
from .campaign_record_intake import (
    CampaignRecordIntake,
    archive_excluded_record_in_checkpoint,
    assess_campaign_record_for_current_runtime,
    emit_forensic_record_excluded,
)
from .campaign_failures import (
    FailureDisposition,
    FailureReport,
    ProductionFailureMonitor,
    abort_unexpected_system_failure,
    classify_validated_control_receipt,
    classify_failure,
    require_system_failures_resolved_for_binary64_resume,
    reviewed_screening_promotion_queue,
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
    ComponentResult,
    DecimalComplex,
    EXTERIOR_PROVISIONAL_REUSE_RECEIPT_SCHEMA,
    PROMOTED_ROOT_SEAL_SCHEMA,
    PromotedRootSeal,
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
    require_locked_bf40_determinant_error_issuance_authority,
    retain_uncalibrated_determinant_error_evidence,
)
from .promoted_control_calibration import PromotedExecutionMode
from .promoted_control_authority import (
    PersistedControlAuthority,
    authenticate_persisted_control_decision,
    authenticate_persisted_control_return,
)
from .background_evidence_store import CanonicalBackgroundEvidenceStore
from .julia_response_backend import (
    ExteriorDeterminantErrorEvidence,
    FIXED_ROOT_SURVEY_BATCH_SCHEMA,
    FIXED_ROOT_SURVEY_BATCH_RESPONSE_SCHEMA,
    FixedRootSurveyPlan,
    FixedRootSurveyConditioning,
    JuliaFixedRootSurveyBatch,
    JuliaFixedRootSurveySample,
    JuliaNumericalControlError,
    JuliaODEResourceLimitError,
    PreparedFixedRootSurveyRequest,
    JuliaResponseBackendError,
    JuliaRootReadoutResourceLimitError,
    JuliaWorkerTimeoutError,
    consume_authenticated_binary64_provisional_predecessor,
    fixed_root_survey_request_contract,
    validate_persisted_operation_control_receipt,
)
from .operation_control import (
    ValidatedControlReceipt,
    execution_identity_from_request,
    operation_execution_identity,
)
from .promoted_artifacts import (
    PROMOTED_CANONICAL_BACKGROUND_RECEIPT_SCHEMA,
    PROMOTED_EXTERIOR_CALCULATION_SCHEMA,
    PromotedBackgroundBinding,
    PromotedBackgroundReuseKey,
    PromotedCanonicalBackgroundReceipt,
    PromotedExteriorCalculationResult,
    PromotedFixedRootComposite,
    PromotedHorizonCalculationResult,
)
from .response_batches import (
    StageOutcome,
    _ANALYTIC_HORIZON_EVIDENCE_KIND,
    _component_stage_signed_error_channels,
    promoted_stage_precision_policy,
    synthetic_stage_signed_error_channels,
)
from .precision_tiers import PrecisionTier
from .progress import ProgressEventKind, emit_progress, progress_scope
from .root_evidence import (
    AuthenticatedRootEvidence,
    ROOT_DEPENDENCY_KEY_SCHEMA,
    ROOT_EVIDENCE_SCHEMA,
    RootDependencyKey,
)
from .structural_diagnostics import StructuralDiagnosticSession


RecordValidator = Callable[[str, Mapping[str, object]], None]
RecordIntakeAssessor = Callable[
    [str, Mapping[str, object]], CampaignRecordIntake
]
_ROOT_PROMOTION_ARITHMETIC_TIER = "root-promotion"
_ACTIVE_PROMOTED_QUEUE_DISPOSITIONS = frozenset({
    PromotionQueueDisposition.PENDING.value,
    PromotionQueueDisposition.CALCULATED_PENDING_DERIVATION.value,
    PromotionQueueDisposition.CONTROL_RETURN_RETAINED.value,
    PromotionQueueDisposition.CONTROL_DECISION_RETAINED.value,
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
    root_success_evidence: Mapping[str, object] | None = field(
        default=None,
        compare=False,
        repr=False,
    )

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
        if self.root_success_evidence is not None:
            if not isinstance(self.root_success_evidence, Mapping):
                raise ValueError("authenticated root seal evidence is invalid")
            object.__setattr__(
                self,
                "root_success_evidence",
                json.loads(canonical_json_bytes(dict(self.root_success_evidence))),
            )


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
    root_success_evidence: Mapping[str, object]
    root_read_count: int = 1
    worker_launch_count: int = 1
    diagnostic_root_read_count: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.seal, AuthenticatedRootSeal):
            raise ValueError("promoted root result lacks an authenticated seal")
        if self.precision_tier not in {"BF40", "BF80"}:
            raise ValueError("promoted root result precision tier is invalid")
        canonical, fixed_root, branch_identity, root_seal_sha256 = (
            _validated_promoted_root_success_authority(
                self.root_success_evidence,
                precision_tier=self.precision_tier,
            )
        )
        if (
            fixed_root != self.seal.fixed_root
            or branch_identity != self.seal.branch_identity
            or root_seal_sha256 != self.seal.root_seal_sha256
        ):
            raise ValueError(
                "promoted root result disagrees with its success evidence"
            )
        object.__setattr__(self, "root_success_evidence", canonical)
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
    require_system_failures_resolved_for_binary64_resume(result)
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
                    queue_name = reviewed_screening_promotion_queue(reason_code)
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


def _promoted_control_receipt(
    error: Exception,
    *,
    leaf: object,
    digits: int,
    current_action_kind: str,
    expected_action: Mapping[str, object] | None = None,
) -> ValidatedControlReceipt | None:
    if not isinstance(
        error,
        (
            JuliaNumericalControlError,
            JuliaODEResourceLimitError,
            JuliaRootReadoutResourceLimitError,
            JuliaWorkerTimeoutError,
        ),
    ):
        return None
    receipt = getattr(error, "control_receipt", None)
    if not isinstance(receipt, ValidatedControlReceipt):
        raise JuliaResponseBackendError(
            "promoted CONTROL exception lacks a validated receipt"
        )
    identity = receipt.identity.mapping
    expected_operation = (
        "root-readout" if current_action_kind == "ROOT"
        else "fixed-root-survey-batch"
    )
    if (
        identity.get("operation") != expected_operation
        or identity.get("leaf_id") != leaf.job.leaf_id
        or identity.get("job_id") != leaf.job.job_id
        or identity.get("backend_identity_sha256")
        != leaf.job.backend_identity.identity_sha256
        or identity.get("precision_digits") != digits
        or identity.get("semantic_precision_tier") != f"bigfloat-{digits}"
        or receipt.canonical_request is None
    ):
        raise JuliaResponseBackendError(
            "promoted CONTROL receipt does not match the active operation"
        )
    expected_code = (
        error.failure_code
        if isinstance(error, JuliaNumericalControlError)
        else "ODE_RESOURCE_LIMIT"
        if isinstance(error, JuliaODEResourceLimitError)
        else "ROOT_READOUT_RESOURCE_INFEASIBLE"
        if isinstance(error, JuliaRootReadoutResourceLimitError)
        else "WORKER_TIMEOUT"
        if isinstance(error, JuliaWorkerTimeoutError)
        else None
    )
    if (
        expected_code != receipt.failure_code
        or type(error).__name__
        not in {
            "JuliaNumericalControlError",
            "JuliaODEResourceLimitError",
            "JuliaRootReadoutResourceLimitError",
            "JuliaWorkerTimeoutError",
        }
    ):
        raise JuliaResponseBackendError(
            "promoted CONTROL exception identity is invalid"
        )
    if current_action_kind == "RESPONSE":
        if expected_action is None:
            raise JuliaResponseBackendError(
                "promoted fixed-root CONTROL receipt lacks expected action authority"
            )
        _bind_promoted_control_receipt_to_expected_action(receipt, expected_action)
    return receipt


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
_PROMOTED_ROOT_RECEIPT_SCHEMA = "windows-solver.promoted-root-evidence-receipt/2"
_PROMOTED_CONTROL_RETURN_SCHEMA = PROMOTED_CONTROL_RETURN_SCHEMA
_PROMOTED_CONTROL_DECISION_SCHEMA = PROMOTED_CONTROL_DECISION_SCHEMA
_PROMOTED_CONTROL_RETURN_SCHEMAS = frozenset({
    PROMOTED_CONTROL_RETURN_SCHEMA,
    PROMOTED_HORIZON_CONTROL_RETURN_SCHEMA,
})
_PROMOTED_CONTROL_DECISION_SCHEMAS = frozenset({
    PROMOTED_CONTROL_DECISION_SCHEMA,
    PROMOTED_HORIZON_CONTROL_DECISION_SCHEMA,
})
_PROMOTED_PARTIAL_WORK_SCHEMA = "windows-solver.promoted-partial-work/2"
_PROMOTED_EXPECTED_ACTION_SCHEMA = (
    "windows-solver.promoted-expected-fixed-root-action/1"
)
_PROMOTED_ATTEMPT_RECORD_SCHEMA = "windows-solver.promoted-worker-attempt/1"
_PROMOTED_BACKGROUND_SAMPLE_ROLES = BINARY64_FIXED_ROOT_SAMPLE_ROLES[:5]
_PROMOTED_COMPONENT_SAMPLE_ROLES = BINARY64_FIXED_ROOT_SAMPLE_ROLES[5:]


def _promoted_root_dependency_key_from_mapping(
    value: object,
) -> RootDependencyKey:
    fields = {
        "schema",
        "root_reference_id",
        "root_identity_sha256",
        "mode",
        "sampling_coordinate",
        "spin",
        "branch_identity",
        "equation_id",
        "backend_identity",
        "root_acceptance_policy_identity",
        "arithmetic_tier",
    }
    if (
        not isinstance(value, Mapping)
        or set(value) != fields
        or value.get("schema") != ROOT_DEPENDENCY_KEY_SCHEMA
    ):
        raise ValueError("promoted root dependency key is invalid")
    try:
        return RootDependencyKey(
            root_reference_id=str(value["root_reference_id"]),
            root_identity_sha256=str(value["root_identity_sha256"]),
            mode=value["mode"],  # type: ignore[arg-type]
            sampling_coordinate=value["sampling_coordinate"],  # type: ignore[arg-type]
            spin=value["spin"],  # type: ignore[arg-type]
            branch_identity=str(value["branch_identity"]),
            equation_id=str(value["equation_id"]),
            backend_identity=str(value["backend_identity"]),
            root_acceptance_policy_identity=str(
                value["root_acceptance_policy_identity"]
            ),
            arithmetic_tier=str(value["arithmetic_tier"]),
        )
    except (TypeError, ValueError) as error:
        raise ValueError("promoted root dependency key is invalid") from error


def _promoted_root_request_matches_success(
    request: Mapping[str, object],
    authority: PromotedRootSeal,
    *,
    precision_tier: str,
    leaf: object | None,
) -> bool:
    """Bind a successful root result to the exact worker request it answered."""

    digits = int(precision_tier[2:])
    amplitude = request.get("amplitude")
    if not isinstance(amplitude, Mapping):
        return False
    try:
        zero_amplitude = (
            Decimal(str(amplitude["real"])) == 0
            and Decimal(str(amplitude["imaginary"])) == 0
        )
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return False
    if (
        not zero_amplitude
        or request.get("operation") != "root-readout"
        or request.get("leaf_id") != authority.leaf_id
        or request.get("job_id") != authority.job_id
        or request.get("mechanism_id") != authority.mechanism_id
        or request.get("job_policy_sha256") != authority.policy_sha256
        or request.get("backend_identity_sha256")
        != authority.backend_identity_sha256
        or request.get("precision_digits") != digits
        or request.get("semantic_precision_tier") != f"bigfloat-{digits}"
    ):
        return False
    if leaf is None:
        return True
    job = leaf.job
    mode = request.get("mode")
    predictor = request.get("primary_predictor")
    expected_predictor = {
        "real": format(job.root.omega.real, ".17g"),
        "imaginary": format(job.root.omega.imag, ".17g"),
    }
    return (
        request.get("leaf_id") == job.leaf_id
        and request.get("job_id") == job.job_id
        and request.get("role") == job.role
        and request.get("mechanism_id") == job.mechanism_id
        and request.get("job_policy_sha256") == job.policy.identity_sha256
        and request.get("backend_identity_sha256")
        == job.backend_identity.identity_sha256
        and mode
        == {
            "s": job.mode.s,
            "ell": job.mode.ell,
            "m": job.mode.m,
            "n": job.mode.n,
        }
        and request.get("spin") == format(job.spin, ".17g")
        and predictor == expected_predictor
    )


def _validated_promoted_root_success_authority(
    value: object,
    *,
    precision_tier: str,
    leaf: object | None = None,
) -> tuple[dict[str, object], complex, str, str]:
    """Authenticate either worker success evidence or durable root authority."""

    if precision_tier not in {"BF40", "BF80"} or not isinstance(value, Mapping):
        raise ValueError("promoted root success authority is invalid")
    canonical = json.loads(canonical_json_bytes(dict(value)))
    schema = canonical.get("schema")
    if schema == PROMOTED_ROOT_SEAL_SCHEMA:
        try:
            authority = PromotedRootSeal.from_mapping(canonical)
            if leaf is not None:
                authority.validate_for(leaf.job)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "promoted worker root success authority is invalid"
            ) from error
        receipt = authority.root_readout.worker_response_receipt
        request = (
            receipt.get("request_binding")
            if isinstance(receipt, Mapping)
            else None
        )
        if (
            not isinstance(request, Mapping)
            or not _promoted_root_request_matches_success(
                request,
                authority,
                precision_tier=precision_tier,
                leaf=leaf,
            )
        ):
            raise ValueError(
                "promoted worker root success request identity is invalid"
            )
        return (
            canonical,
            authority.root_readout.omega,
            authority.root_readout.branch_id,
            authority.sha256,
        )
    if schema == ROOT_EVIDENCE_SCHEMA:
        try:
            authority = AuthenticatedRootEvidence.from_mapping(canonical)
            if leaf is not None:
                authority.validate_for(leaf)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "promoted durable root authority is invalid"
            ) from error
        return (
            canonical,
            authority.fixed_root,
            authority.branch_identity,
            authority.root_seal_sha256,
        )
    raise ValueError("promoted root success authority schema is unsupported")


def _validated_promoted_root_receipt(
    value: object,
    *,
    queue_ordinal: int,
    leaf_id: str,
    leaf: object | None = None,
    expected_precision_tier: str | None = None,
) -> tuple[dict[str, object], AuthenticatedRootSeal]:
    """Validate one root receipt against scientific and scheduler authority."""

    fields = {
        "schema",
        "queue_ordinal",
        "leaf_id",
        "job_id",
        "precision_tier",
        "root_seal_sha256",
        "branch_identity",
        "fixed_root",
        "root_dependency_key",
        "root_dependency_key_sha256",
        "root_success_authority",
        "root_success_authority_sha256",
        "receipt_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError("promoted root work receipt is invalid")
    content = {key: item for key, item in value.items() if key != "receipt_sha256"}
    if (
        value.get("schema") != _PROMOTED_ROOT_RECEIPT_SCHEMA
        or value.get("queue_ordinal") != queue_ordinal
        or value.get("leaf_id") != leaf_id
        or value.get("precision_tier") not in {"BF40", "BF80"}
        or (
            expected_precision_tier is not None
            and value.get("precision_tier") != expected_precision_tier
        )
        or value.get("receipt_sha256")
        != hashlib.sha256(canonical_json_bytes(content)).hexdigest()
    ):
        raise ValueError("promoted root work receipt is invalid")
    dependency = _promoted_root_dependency_key_from_mapping(
        value["root_dependency_key"]
    )
    if (
        value.get("root_dependency_key_sha256") != dependency.sha256
        or dependency.arithmetic_tier != _ROOT_PROMOTION_ARITHMETIC_TIER
    ):
        raise ValueError("promoted root work dependency is invalid")
    authority_value = value["root_success_authority"]
    if (
        not isinstance(authority_value, Mapping)
        or value.get("root_success_authority_sha256")
        != hashlib.sha256(canonical_json_bytes(dict(authority_value))).hexdigest()
    ):
        raise ValueError("promoted root success authority digest is invalid")
    canonical_authority, fixed_root, branch_identity, root_seal_sha256 = (
        _validated_promoted_root_success_authority(
            authority_value,
            precision_tier=str(value["precision_tier"]),
            leaf=leaf,
        )
    )
    fixed_root_mapping = value.get("fixed_root")
    if not isinstance(fixed_root_mapping, Mapping) or set(fixed_root_mapping) != {
        "real",
        "imaginary",
    }:
        raise ValueError("promoted root work fixed root is invalid")
    try:
        retained_root = complex(
            float(fixed_root_mapping["real"]),
            float(fixed_root_mapping["imaginary"]),
        )
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("promoted root work fixed root is invalid") from error
    if not math.isfinite(retained_root.real) or not math.isfinite(retained_root.imag):
        raise ValueError("promoted root work fixed root is invalid")
    if (
        retained_root != fixed_root
        or value.get("branch_identity") != branch_identity
        or value.get("root_seal_sha256") != root_seal_sha256
        or dependency.branch_identity != branch_identity
    ):
        raise ValueError("promoted root work evidence binding is invalid")
    if leaf is not None:
        expected_dependency = RootDependencyKey.from_leaf(
            leaf, arithmetic_tier=_ROOT_PROMOTION_ARITHMETIC_TIER
        )
        if (
            value.get("job_id") != leaf.job.job_id
            or dependency != expected_dependency
            or leaf_id != leaf.job.leaf_id
        ):
            raise ValueError("promoted root work leaf binding is invalid")
    elif (
        canonical_authority.get("leaf_id") is not None
        and (
            canonical_authority.get("leaf_id") != leaf_id
            or canonical_authority.get("job_id") != value.get("job_id")
        )
    ):
        raise ValueError("promoted root work result identity is invalid")
    canonical = json.loads(canonical_json_bytes(dict(value)))
    return canonical, AuthenticatedRootSeal(
        retained_root,
        branch_identity,
        root_seal_sha256,
    )


def _promoted_root_receipt(
    result: PromotedRootSolveResult,
    *,
    entry: Mapping[str, object],
    leaf: object,
    dependency_key: RootDependencyKey,
) -> dict[str, object]:
    canonical_authority, fixed_root, branch_identity, root_seal_sha256 = (
        _validated_promoted_root_success_authority(
            result.root_success_evidence,
            precision_tier=result.precision_tier,
            leaf=leaf,
        )
    )
    if (
        fixed_root != result.seal.fixed_root
        or branch_identity != result.seal.branch_identity
        or root_seal_sha256 != result.seal.root_seal_sha256
        or dependency_key
        != RootDependencyKey.from_leaf(
            leaf, arithmetic_tier=_ROOT_PROMOTION_ARITHMETIC_TIER
        )
    ):
        raise ValueError("promoted root success evidence is not scheduler-bound")
    content: dict[str, object] = {
        "schema": _PROMOTED_ROOT_RECEIPT_SCHEMA,
        "queue_ordinal": entry["queue_ordinal"],
        "leaf_id": entry["leaf_id"],
        "job_id": leaf.job.job_id,
        "precision_tier": result.precision_tier,
        "root_seal_sha256": root_seal_sha256,
        "branch_identity": branch_identity,
        "fixed_root": {
            "real": format(fixed_root.real, ".17g"),
            "imaginary": format(fixed_root.imag, ".17g"),
        },
        "root_dependency_key": dependency_key.to_mapping(),
        "root_dependency_key_sha256": dependency_key.sha256,
        "root_success_authority": canonical_authority,
        "root_success_authority_sha256": hashlib.sha256(
            canonical_json_bytes(canonical_authority)
        ).hexdigest(),
    }
    receipt = {
        **content,
        "receipt_sha256": hashlib.sha256(canonical_json_bytes(content)).hexdigest(),
    }
    canonical, _seal = _validated_promoted_root_receipt(
        receipt,
        queue_ordinal=int(entry["queue_ordinal"]),
        leaf_id=str(entry["leaf_id"]),
        leaf=leaf,
        expected_precision_tier=result.precision_tier,
    )
    return canonical


def _promoted_control_schemas_for_route(route: str) -> tuple[str, str]:
    """Return the only CONTROL return/decision schema pair for one route."""

    if route == "EXTERIOR_BF40":
        return PROMOTED_CONTROL_RETURN_SCHEMA, PROMOTED_CONTROL_DECISION_SCHEMA
    if route == "HORIZON_BF80":
        return (
            PROMOTED_HORIZON_CONTROL_RETURN_SCHEMA,
            PROMOTED_HORIZON_CONTROL_DECISION_SCHEMA,
        )
    raise ValueError("promoted CONTROL route is unsupported")


def _promoted_expected_fixed_root_action(
    prepared: PreparedFixedRootSurveyRequest,
    *,
    entry: Mapping[str, object],
    leaf: object,
    tier: str,
    plan: FixedRootSurveyPlan,
) -> dict[str, object]:
    """Seal the scheduler-owned action before its exact request is dispatched."""

    if not isinstance(prepared, PreparedFixedRootSurveyRequest):
        raise ValueError("promoted fixed-root prepared request is invalid")
    contract = fixed_root_survey_request_contract(plan)
    identity = operation_execution_identity(
        prepared.document.get("execution_identity")
    )
    mapping = identity.mapping
    expected_tier = f"BF{mapping.get('precision_digits')}"
    if (
        identity.scope != "REQUEST"
        or identity.operation != "fixed-root-survey-batch"
        or expected_tier != tier
        or mapping.get("request_sha256") != prepared.request_sha256
        or identity.sha256 != prepared.execution_identity_sha256
        or mapping.get("leaf_id") != entry.get("leaf_id")
        or mapping.get("leaf_id") != leaf.job.leaf_id
        or mapping.get("job_id") != leaf.job.job_id
        or mapping.get("backend_identity_sha256")
        != leaf.job.backend_identity.identity_sha256
        or mapping.get("plan") != contract.plan.value
        or mapping.get("scientific_operation_identity")
        != contract.scientific_operation_identity
        or tuple(mapping.get("sample_roles", ())) != contract.sample_roles
        or mapping.get("root_reference_id") != leaf.job.root.root_reference_id
        or mapping.get("branch_identity") != leaf.job.root.branch_id
    ):
        raise ValueError("promoted prepared action does not match scheduler authority")
    content: dict[str, object] = {
        "schema": _PROMOTED_EXPECTED_ACTION_SCHEMA,
        "queue_ordinal": entry.get("queue_ordinal"),
        "leaf_id": leaf.job.leaf_id,
        "job_id": leaf.job.job_id,
        "backend_identity_sha256": leaf.job.backend_identity.identity_sha256,
        "tier": tier,
        "current_action_kind": "RESPONSE",
        "operation": identity.operation,
        "plan": contract.plan.value,
        "scientific_operation_identity": contract.scientific_operation_identity,
        "sample_roles": list(contract.sample_roles),
        "root_reference_id": mapping.get("root_reference_id"),
        "root_seal_sha256": mapping.get("root_seal_sha256"),
        "branch_identity": mapping.get("branch_identity"),
        "precision_digits": mapping.get("precision_digits"),
        "request_sha256": prepared.request_sha256,
        "request_execution_identity_sha256": prepared.execution_identity_sha256,
    }
    return {
        **content,
        "action_sha256": hashlib.sha256(canonical_json_bytes(content)).hexdigest(),
    }


def _validated_promoted_expected_action(
    value: object,
    *,
    queue_ordinal: int | None = None,
    leaf_id: str | None = None,
    tier: str | None = None,
) -> dict[str, object]:
    fields = {
        "schema",
        "queue_ordinal",
        "leaf_id",
        "job_id",
        "backend_identity_sha256",
        "tier",
        "current_action_kind",
        "operation",
        "plan",
        "scientific_operation_identity",
        "sample_roles",
        "root_reference_id",
        "root_seal_sha256",
        "branch_identity",
        "precision_digits",
        "request_sha256",
        "request_execution_identity_sha256",
        "action_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError("promoted expected-action fields are invalid")
    content = {key: item for key, item in value.items() if key != "action_sha256"}
    contract = fixed_root_survey_request_contract(str(value.get("plan")))
    precision_digits = value.get("precision_digits")
    expected_tier = (
        None
        if isinstance(precision_digits, bool) or not isinstance(precision_digits, int)
        else f"BF{precision_digits}"
    )
    if (
        value.get("schema") != _PROMOTED_EXPECTED_ACTION_SCHEMA
        or value.get("action_sha256")
        != hashlib.sha256(canonical_json_bytes(content)).hexdigest()
        or value.get("operation") != "fixed-root-survey-batch"
        or value.get("current_action_kind") != "RESPONSE"
        or value.get("scientific_operation_identity")
        != contract.scientific_operation_identity
        or tuple(value.get("sample_roles", ())) != contract.sample_roles
        or expected_tier not in {"BF40", "BF80"}
        or value.get("tier") != expected_tier
        or any(
            not isinstance(value.get(name), str) or not value.get(name)
            for name in (
                "leaf_id",
                "job_id",
                "backend_identity_sha256",
                "root_reference_id",
                "root_seal_sha256",
                "branch_identity",
                "request_sha256",
                "request_execution_identity_sha256",
            )
        )
        or (queue_ordinal is not None and value.get("queue_ordinal") != queue_ordinal)
        or (leaf_id is not None and value.get("leaf_id") != leaf_id)
        or (tier is not None and value.get("tier") != tier)
    ):
        raise ValueError("promoted expected action is invalid")
    return json.loads(canonical_json_bytes(dict(value)))


def _bind_promoted_control_receipt_to_expected_action(
    receipt: ValidatedControlReceipt,
    expected_action: Mapping[str, object],
) -> None:
    """Require a CONTROL receipt to prove the scheduler's exact active phase."""

    expected = _validated_promoted_expected_action(expected_action)
    canonical_request = receipt.canonical_request
    if canonical_request is None:
        raise JuliaResponseBackendError(
            "promoted CONTROL receipt lost its canonical request"
        )
    request_identity = execution_identity_from_request(
        canonical_request,
        request_sha256=receipt.identity.request_sha256,
    )
    receipt_identity = receipt.identity.mapping
    shared = {
        "operation": expected["operation"],
        "leaf_id": expected["leaf_id"],
        "job_id": expected["job_id"],
        "backend_identity_sha256": expected["backend_identity_sha256"],
        "precision_digits": expected["precision_digits"],
        "plan": expected["plan"],
        "scientific_operation_identity": expected[
            "scientific_operation_identity"
        ],
        "root_reference_id": expected["root_reference_id"],
        "root_seal_sha256": expected["root_seal_sha256"],
        "branch_identity": expected["branch_identity"],
    }
    if (
        receipt.identity.request_sha256 != expected["request_sha256"]
        or request_identity.sha256
        != expected["request_execution_identity_sha256"]
        or any(request_identity.mapping.get(name) != item for name, item in shared.items())
        or any(receipt_identity.get(name) != item for name, item in shared.items())
        or tuple(request_identity.mapping.get("sample_roles", ()))
        != tuple(expected["sample_roles"])
        or tuple(receipt_identity.get("sample_roles", ()))
        != tuple(expected["sample_roles"])
    ):
        raise JuliaResponseBackendError(
            "promoted CONTROL receipt does not match scheduler expected action"
        )


def _promoted_sample_from_mapping(value: object) -> JuliaFixedRootSurveySample:
    if not isinstance(value, Mapping) or set(value) != {
        "sample_index",
        "sample_role",
        "execution_identity",
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
        sample_index=int(value["sample_index"]),
        sample_role=str(value["sample_role"]),
        omega=parse_complex(value["omega"], "sample frequency"),
        amplitude=parse_complex(value["amplitude"], "sample amplitude"),
        determinant=decimal_determinant,
        numerical_conditioning=FixedRootSurveyConditioning(
            value["numerical_conditioning"]
        ),
        execution_identity=value["execution_identity"],
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
        "plan",
        "execution_identity",
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
    if value.get("schema") != FIXED_ROOT_SURVEY_BATCH_RESPONSE_SCHEMA:
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
        plan=FixedRootSurveyPlan(str(value["plan"])),
        execution_identity=value["execution_identity"],
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
    """Name one exact promoted five-sample background request.

    The key contains only zero-coupling Dω context.  It is constructed before
    the worker call and retained with the original five-sample receipt, then
    bound by digest into each consuming four-sample mechanism artifact.
    """

    if digits not in (40, 80):
        raise ValueError("promoted background precision is invalid")
    contract = fixed_root_survey_request_contract(
        FixedRootSurveyPlan.CANONICAL_BACKGROUND_FIVE
    )
    root = seal.fixed_root
    frequency_step = 1.0e-5 * (1.0 + abs(root))
    angular_identity = hashlib.sha256(canonical_json_bytes({
        "angular_separation_constant": {
            "real": format(leaf.job.root.angular_separation_constant.real, ".17g"),
            "imaginary": format(
                leaf.job.root.angular_separation_constant.imag, ".17g"
            ),
        },
        "angular_owner": leaf.job.root.owner_data_sha256,
    })).hexdigest()
    key = PromotedBackgroundReuseKey(
        root_seal_sha256=seal.root_seal_sha256,
        root_identity_sha256=leaf.job.root.identity_sha256,
        branch_identity=seal.branch_identity,
        angular_identity_sha256=angular_identity,
        backend_identity_sha256=leaf.job.backend_identity.identity_sha256,
        numerical_controls_sha256=leaf.job.policy.identity_sha256,
        fixed_root={
            "real": format(root.real, ".17g"),
            "imaginary": format(root.imag, ".17g"),
        },
        precision_tier=f"bigfloat-{digits}",
        working_precision_bits=math.ceil(digits * math.log2(10)) + 32,
        frequency_step=format(frequency_step, ".17g"),
        background_operation_identity=contract.scientific_operation_identity,
        sample_roles=contract.sample_roles,
    )
    return key.sha256, key.to_mapping()


def _promoted_canonical_background_receipt_from_mapping(
    value: object,
) -> tuple[PromotedCanonicalBackgroundReceipt, dict[str, object]]:
    """Rehydrate one v3 background receipt from checkpoint data only."""

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
        "background_reuse_key_sha256",
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
        background_reuse_key_sha256=str(
            binding_value["background_reuse_key_sha256"]
        ),
    )
    calculation = PromotedExteriorCalculationResult(
        component_batch=component,
        background=binding,
    )
    canonical = calculation.to_mapping()
    if canonical != dict(value):
        raise ValueError("promoted exterior calculation artifact is not canonical")
    return calculation, canonical


def _authenticated_promoted_raw_stage(
    checkpoint: Mapping[str, object],
    *,
    queue_ordinal: int,
    route: str,
) -> tuple[dict[str, object], Mapping[str, object], Mapping[str, object]]:
    """Return one authenticated raw stage from the existing stage ledger."""

    result = validate_schema11_checkpoint(checkpoint)
    entries = result["promotion_queue"]["entries"]
    if (
        isinstance(queue_ordinal, bool)
        or not isinstance(queue_ordinal, int)
        or queue_ordinal < 0
        or queue_ordinal >= len(entries)
    ):
        raise ValueError("promoted reduction queue ordinal is invalid")
    entry = entries[queue_ordinal]
    bucket = result["promoted_stage_ledger"].get(str(queue_ordinal))
    stage = bucket.get(str(entry["leaf_id"])) if isinstance(bucket, Mapping) else None
    if not isinstance(stage, Mapping):
        raise ValueError("promoted raw checkpoint stage is invalid")
    stage_kind = (
        entry.get("disposition"),
        stage.get("admission_state"),
        stage.get("schema"),
    )
    if (
        stage_kind
        not in {
            (
                PromotionQueueDisposition.CALCULATED_PENDING_DERIVATION.value,
                PromotionQueueDisposition.CALCULATED_PENDING_DERIVATION.value,
                PROMOTED_CALCULATION_STAGE_SCHEMA,
            ),
            (
                PromotionQueueDisposition.CONTROL_RETURN_RETAINED.value,
                PromotionQueueDisposition.CONTROL_RETURN_RETAINED.value,
                PROMOTED_CONTROL_RETURN_STAGE_SCHEMA,
            ),
        }
        or stage.get("stage_sha256")
        != entry.get("retained_promoted_stage_sha256")
        or stage.get("route") != route
    ):
        raise ValueError("promoted raw checkpoint stage is invalid")
    return result, entry, stage


def _raw_stage_artifact(stage: Mapping[str, object]) -> Mapping[str, object]:
    """Return the payload owned by one authenticated raw stage schema."""

    schema = stage.get("schema")
    field = {
        PROMOTED_CALCULATION_STAGE_SCHEMA: "calculation_artifact",
        PROMOTED_CONTROL_RETURN_STAGE_SCHEMA: "control_return",
    }.get(schema)
    artifact = stage.get(field) if field is not None else None
    if not isinstance(artifact, Mapping):
        raise ValueError("promoted raw stage payload is invalid")
    _promoted_artifact_digest(artifact)
    return artifact


def _raw_stage_chain(
    retained_stage: Mapping[str, object],
) -> tuple[Mapping[str, object], ...]:
    chain = retained_stage.get("calculation_chain")
    if not isinstance(chain, list) or not all(
        isinstance(item, Mapping) for item in chain
    ):
        raise ValueError("retained promoted calculation chain is invalid")
    return (
        *(copy.deepcopy(dict(item)) for item in chain),
        copy.deepcopy(dict(retained_stage)),
    )


def _authenticated_promoted_control_decision_stage(
    checkpoint: Mapping[str, object],
    *,
    queue_ordinal: int,
    route: str,
) -> tuple[dict[str, object], Mapping[str, object], Mapping[str, object]]:
    """Return one independently retained and authenticated CONTROL decision."""

    result = validate_schema11_checkpoint(checkpoint)
    entries = result["promotion_queue"]["entries"]
    if (
        isinstance(queue_ordinal, bool)
        or not isinstance(queue_ordinal, int)
        or queue_ordinal < 0
        or queue_ordinal >= len(entries)
    ):
        raise ValueError("promoted decision queue ordinal is invalid")
    entry = entries[queue_ordinal]
    bucket = result["promoted_stage_ledger"].get(str(queue_ordinal))
    stage = bucket.get(str(entry["leaf_id"])) if isinstance(bucket, Mapping) else None
    if (
        entry.get("disposition")
        != PromotionQueueDisposition.CONTROL_DECISION_RETAINED.value
        or not isinstance(stage, Mapping)
        or stage.get("schema") != PROMOTED_CONTROL_DECISION_STAGE_SCHEMA
        or stage.get("admission_state")
        != PromotionQueueDisposition.CONTROL_DECISION_RETAINED.value
        or stage.get("stage_sha256")
        != entry.get("retained_promoted_stage_sha256")
        or stage.get("route") != route
    ):
        raise ValueError("promoted control-decision checkpoint is invalid")
    return result, entry, stage


def _promoted_artifact_digest(
    artifact: Mapping[str, object],
) -> tuple[str, str]:
    """Return the schema-owned digest field and authenticated digest."""

    return promoted_artifact_digest(artifact)


def _promoted_attempt_record(
    control_receipt: ValidatedControlReceipt,
    *,
    tier: str,
    current_action_kind: str,
    expected_action: Mapping[str, object] | None,
) -> dict[str, object]:
    canonical_request = control_receipt.canonical_request
    if canonical_request is None:
        raise ValueError("promoted CONTROL attempt lost its canonical request")
    content: dict[str, object] = {
        "schema": _PROMOTED_ATTEMPT_RECORD_SCHEMA,
        "current_tier": tier,
        "current_action_kind": current_action_kind,
        "expected_action": (
            None
            if expected_action is None
            else _validated_promoted_expected_action(expected_action)
        ),
        "canonical_request": copy.deepcopy(dict(canonical_request)),
        "control_receipt": control_receipt.to_mapping(),
        "control_receipt_sha256": control_receipt.sha256,
    }
    return {
        **content,
        "attempt_sha256": hashlib.sha256(canonical_json_bytes(content)).hexdigest(),
    }


def _validated_promoted_attempt_record(
    value: object,
    *,
    queue_ordinal: int,
    leaf_id: str,
) -> dict[str, object]:
    fields = {
        "schema",
        "current_tier",
        "current_action_kind",
        "expected_action",
        "canonical_request",
        "control_receipt",
        "control_receipt_sha256",
        "attempt_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError("promoted worker-attempt fields are invalid")
    content = {key: item for key, item in value.items() if key != "attempt_sha256"}
    canonical_request = value.get("canonical_request")
    control_receipt = value.get("control_receipt")
    if (
        value.get("schema") != _PROMOTED_ATTEMPT_RECORD_SCHEMA
        or value.get("attempt_sha256")
        != hashlib.sha256(canonical_json_bytes(content)).hexdigest()
        or value.get("current_tier") not in {"BF40", "BF80"}
        or value.get("current_action_kind") not in {"ROOT", "RESPONSE"}
        or not isinstance(canonical_request, Mapping)
        or not isinstance(control_receipt, Mapping)
    ):
        raise ValueError("promoted worker attempt is invalid")
    receipt = validate_persisted_operation_control_receipt(
        control_receipt, canonical_request
    )
    expected_operation = (
        "root-readout"
        if value["current_action_kind"] == "ROOT"
        else "fixed-root-survey-batch"
    )
    if (
        receipt.sha256 != value.get("control_receipt_sha256")
        or receipt.identity.operation != expected_operation
        or receipt.identity.mapping.get("leaf_id") != leaf_id
        or receipt.identity.mapping.get("semantic_precision_tier")
        != f"bigfloat-{str(value['current_tier'])[2:]}"
    ):
        raise ValueError("promoted worker attempt identity is invalid")
    if value["current_action_kind"] == "RESPONSE":
        expected_action = value.get("expected_action")
        if not isinstance(expected_action, Mapping):
            raise ValueError("promoted response attempt lacks expected action")
        _validated_promoted_expected_action(
            expected_action,
            queue_ordinal=queue_ordinal,
            leaf_id=leaf_id,
            tier=str(value["current_tier"]),
        )
        _bind_promoted_control_receipt_to_expected_action(receipt, expected_action)
    elif value.get("expected_action") is not None:
        raise ValueError("promoted root attempt has an inapplicable expected action")
    return json.loads(canonical_json_bytes(dict(value)))


def _validated_promoted_partial_work(
    value: object,
    *,
    queue_ordinal: int,
    leaf_id: str,
    leaf: object | None = None,
) -> dict[str, object]:
    """Derive route work solely from authenticated receipts and attempts."""

    fields = {"schema", "evidence_receipts", "attempt_records"}
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError("promoted partial-work accounting fields are invalid")
    if value.get("schema") != _PROMOTED_PARTIAL_WORK_SCHEMA:
        raise ValueError("promoted partial-work accounting schema is invalid")
    receipts = value["evidence_receipts"]
    attempts = value["attempt_records"]
    if (
        not isinstance(receipts, list)
        or not all(isinstance(item, Mapping) for item in receipts)
        or not isinstance(attempts, list)
        or not all(isinstance(item, Mapping) for item in attempts)
    ):
        raise ValueError("promoted partial-work evidence is invalid")

    sample_count = root_read_count = worker_launch_count = 0
    canonical_receipts: list[dict[str, object]] = []
    canonical_attempts: list[dict[str, object]] = []
    seen_receipts: set[tuple[str, str]] = set()
    for receipt in receipts:
        schema = receipt.get("schema")
        digest = receipt.get("receipt_sha256")
        if not isinstance(digest, str):
            raise ValueError("promoted partial-work receipt digest is invalid")
        key = (str(schema), digest)
        if key in seen_receipts:
            raise ValueError("promoted partial-work receipt is duplicated")
        seen_receipts.add(key)
        if schema == PROMOTED_CANONICAL_BACKGROUND_RECEIPT_SCHEMA:
            parsed, canonical = _promoted_canonical_background_receipt_from_mapping(
                receipt
            )
            if (
                parsed.source_queue_ordinal == queue_ordinal
                and parsed.source_leaf_id == leaf_id
            ):
                if (
                    parsed.batch.sample_count != 5
                    or parsed.batch.julia_launch_count != 1
                    or parsed.batch.root_read_count != 0
                ):
                    raise ValueError("promoted background work budget is invalid")
                sample_count += parsed.batch.sample_count
                worker_launch_count += parsed.batch.julia_launch_count
            canonical_receipts.append(canonical)
            continue
        content = {
            name: item for name, item in receipt.items() if name != "receipt_sha256"
        }
        if digest != hashlib.sha256(canonical_json_bytes(content)).hexdigest():
            raise ValueError("promoted partial-work receipt digest is invalid")
        if schema == _PROMOTED_ROOT_RECEIPT_SCHEMA:
            canonical_root, _root_seal = _validated_promoted_root_receipt(
                receipt,
                queue_ordinal=queue_ordinal,
                leaf_id=leaf_id,
                leaf=leaf,
            )
            root_read_count += 1
            worker_launch_count += 1
        elif schema == EXTERIOR_PROVISIONAL_REUSE_RECEIPT_SCHEMA:
            provisional_fields = {
                "schema",
                "status",
                "leaf_id",
                "provisional_stage_sha256",
                "root_seal_sha256",
                "target_precision_tier",
                "decision",
                "receipt_sha256",
            }
            if (
                set(receipt) != provisional_fields
                or receipt.get("status") != "COMPATIBLE"
                or receipt.get("leaf_id") != leaf_id
                or receipt.get("target_precision_tier") != "BF40"
                or receipt.get("decision")
                != "AUTHENTICATED_BINARY64_PREDECESSOR_CONSUMED"
            ):
                raise ValueError("promoted predecessor receipt is invalid")
        else:
            raise ValueError("promoted partial-work receipt schema is unsupported")
        canonical_receipts.append(
            canonical_root
            if schema == _PROMOTED_ROOT_RECEIPT_SCHEMA
            else json.loads(canonical_json_bytes(dict(receipt)))
        )

    seen_attempts: set[str] = set()
    for attempt in attempts:
        canonical = _validated_promoted_attempt_record(
            attempt,
            queue_ordinal=queue_ordinal,
            leaf_id=leaf_id,
        )
        digest = str(canonical["attempt_sha256"])
        if digest in seen_attempts:
            raise ValueError("promoted worker attempt is duplicated")
        seen_attempts.add(digest)
        worker_launch_count += 1
        if canonical["current_action_kind"] == "ROOT":
            root_read_count += 1
        canonical_attempts.append(canonical)
    return {
        "schema": _PROMOTED_PARTIAL_WORK_SCHEMA,
        "evidence_receipts": canonical_receipts,
        "attempt_records": canonical_attempts,
        "sample_count": sample_count,
        "root_read_count": root_read_count,
        "worker_launch_count": worker_launch_count,
    }


def _revalidate_promoted_control_proof(
    control_return: Mapping[str, object],
    control_decision: Mapping[str, object],
    *,
    queue_ordinal: int,
    leaf_id: str,
    route: str = "EXTERIOR_BF40",
    leaf: object | None = None,
) -> None:
    """Re-hash, re-bind, and reclassify a retained continuation proof."""

    return_schema, decision_schema = _promoted_control_schemas_for_route(route)
    if (
        control_return.get("schema") != return_schema
        or control_decision.get("schema") != decision_schema
        or not isinstance(control_return.get("control_receipt"), Mapping)
        or not isinstance(control_return.get("canonical_request"), Mapping)
    ):
        raise ValueError("promoted control proof schemas are invalid")
    if route == "HORIZON_BF80":
        authenticate_persisted_control_decision(
            control_return,
            control_decision,
            expected_return_schema=return_schema,
            expected_decision_schema=decision_schema,
            expected_leaf_id=leaf_id,
            expected_current_action_kind="RESPONSE",
        )
        return
    return_fields = {
        "schema",
        "operation",
        "request_schema",
        "request_sha256",
        "execution_identity_sha256",
        "effective_policy_identity",
        "current_tier",
        "current_action_kind",
        "expected_action",
        "canonical_request",
        "control_receipt",
        "control_receipt_sha256",
        "partial_work",
        "control_return_sha256",
    }
    decision_fields = {
        "schema",
        "control_return_sha256",
        "control_receipt_sha256",
        "failure_code",
        "failure_fingerprint_sha256",
        "fingerprint_material",
        "disposition",
        "queue_kind",
        "current_tier",
        "current_action_kind",
        "next_tier",
        "next_action_kind",
        "control_decision_sha256",
    }
    if set(control_return) != return_fields or set(control_decision) != decision_fields:
        raise ValueError("promoted control proof fields are invalid")
    partial_work = _validated_promoted_partial_work(
        control_return["partial_work"],
        queue_ordinal=queue_ordinal,
        leaf_id=leaf_id,
        leaf=leaf,
    )
    _, return_sha256 = _promoted_artifact_digest(control_return)
    _, decision_sha256 = _promoted_artifact_digest(control_decision)
    del decision_sha256
    receipt = validate_persisted_operation_control_receipt(
        control_return["control_receipt"],
        control_return["canonical_request"],
    )
    identity = receipt.identity
    effective_policy = identity.mapping["effective_policy_identity"]
    effective_policy_sha256 = (
        str(effective_policy["sha256"])
        if isinstance(effective_policy, Mapping)
        else str(effective_policy)
    )
    if (
        control_return["operation"] != identity.operation
        or control_return["request_schema"]
        != identity.mapping["request_schema"]
        or control_return["request_sha256"] != identity.request_sha256
        or control_return["execution_identity_sha256"] != identity.sha256
        or control_return["effective_policy_identity"]
        != effective_policy_sha256
        or control_return["control_receipt_sha256"] != receipt.sha256
        or control_return["current_tier"] not in {"BF40", "BF80"}
        or control_return["current_action_kind"] not in {"ROOT", "RESPONSE"}
    ):
        raise ValueError("promoted control return identity is invalid")
    if control_return["current_action_kind"] == "RESPONSE":
        expected_action = _validated_promoted_expected_action(
            control_return["expected_action"],
            queue_ordinal=queue_ordinal,
            leaf_id=leaf_id,
            tier=str(control_return["current_tier"]),
        )
        _bind_promoted_control_receipt_to_expected_action(receipt, expected_action)
    elif control_return.get("expected_action") is not None:
        raise ValueError("promoted root control return has invalid expected action")
    attempts = partial_work["attempt_records"]
    current_attempt = attempts[-1] if attempts else None
    if (
        not isinstance(current_attempt, Mapping)
        or current_attempt.get("current_tier") != control_return["current_tier"]
        or current_attempt.get("current_action_kind")
        != control_return["current_action_kind"]
        or current_attempt.get("expected_action")
        != control_return["expected_action"]
        or current_attempt.get("canonical_request")
        != control_return["canonical_request"]
        or current_attempt.get("control_receipt")
        != control_return["control_receipt"]
        or current_attempt.get("control_receipt_sha256") != receipt.sha256
    ):
        raise ValueError("promoted control return attempt lineage is invalid")
    report, decision = classify_validated_control_receipt(
        receipt,
        current_tier=str(control_return.get("current_tier")),
        current_action_kind=str(control_return.get("current_action_kind")),
    )
    expected = {
        "control_return_sha256": return_sha256,
        "control_receipt_sha256": receipt.sha256,
        "failure_code": decision.failure_code,
        "failure_fingerprint_sha256": decision.fingerprint_sha256,
        "fingerprint_material": report.fingerprint_material,
        "disposition": decision.disposition.value,
        "queue_kind": decision.queue_kind,
        "current_tier": control_return.get("current_tier"),
        "current_action_kind": control_return.get("current_action_kind"),
        "next_tier": decision.next_precision_tier,
        "next_action_kind": decision.next_action_kind,
    }
    if any(control_decision.get(name) != value for name, value in expected.items()):
        raise ValueError("promoted control decision no longer matches registry")


def _authenticated_horizon_control_stage(
    control_return: Mapping[str, object],
    retained_stage: Mapping[str, object],
    *,
    leaf_id: str,
) -> tuple[
    PersistedControlAuthority,
    list[Mapping[str, object]],
    tuple[int, int, int],
]:
    """Authenticate BF80 horizon CONTROL evidence and derive its work counts."""

    fields = {
        "schema",
        "operation",
        "request_schema",
        "request_sha256",
        "execution_identity_sha256",
        "effective_policy_identity",
        "current_tier",
        "current_action_kind",
        "canonical_request",
        "control_receipt",
        "control_receipt_sha256",
        "predecessor_stage_sha256",
        "source_fingerprint_sha256",
        "layer1_lock_receipt_sha256",
        "control_return_sha256",
    }
    if (
        set(control_return) != fields
        or control_return.get("schema") != PROMOTED_HORIZON_CONTROL_RETURN_SCHEMA
        or control_return.get("current_tier") != "BF80"
        or control_return.get("current_action_kind") != "RESPONSE"
        or control_return.get("predecessor_stage_sha256")
        != retained_stage.get("predecessor_stage_sha256")
        or control_return.get("source_fingerprint_sha256")
        != retained_stage.get("source_fingerprint_sha256")
        or control_return.get("layer1_lock_receipt_sha256")
        != retained_stage.get("layer1_lock_receipt_sha256")
    ):
        raise ValueError("promoted horizon CONTROL return is invalid")
    authority = authenticate_persisted_control_return(
        control_return,
        expected_schema=PROMOTED_HORIZON_CONTROL_RETURN_SCHEMA,
        expected_leaf_id=leaf_id,
        expected_current_action_kind="RESPONSE",
    )
    identity = authority.classification.receipt.identity
    expected_root_reads = 1 if identity.operation == "root-readout" else 0
    receipts = retained_stage.get("receipts")
    tiers = retained_stage.get("precision_tiers")
    counters = (
        retained_stage.get("sample_count"),
        retained_stage.get("root_read_count"),
        retained_stage.get("worker_launch_count"),
    )
    if (
        tiers != ["BF80"]
        or not isinstance(receipts, list)
        or receipts
        or counters != (0, expected_root_reads, 1)
    ):
        raise ValueError("promoted horizon CONTROL accounting is invalid")
    return authority, receipts, (0, expected_root_reads, 1)


def _control_decision_authorizes_bf80(
    outcome: PromotedPassOutcome,
    *,
    action_kind: str | None = None,
) -> bool:
    decision = outcome.calculation_artifact
    if not isinstance(decision, Mapping):
        return False
    return (
        decision.get("schema") == _PROMOTED_CONTROL_DECISION_SCHEMA
        and decision.get("disposition")
        == FailureDisposition.PROMOTION_PENDING.value
        and decision.get("queue_kind") == decision.get("current_action_kind")
        and decision.get("next_action_kind") == decision.get("current_action_kind")
        and decision.get("next_tier") == "BF80"
        and (action_kind is None or decision.get("current_action_kind") == action_kind)
    )


def _outcome_authorizes_bf80(outcome: PromotedPassOutcome) -> bool:
    artifact = outcome.calculation_artifact
    if isinstance(artifact, Mapping) and artifact.get("schema") == (
        _PROMOTED_CONTROL_DECISION_SCHEMA
    ):
        return _control_decision_authorizes_bf80(outcome)
    return False


def _control_trace_fields(outcome: PromotedPassOutcome) -> dict[str, object]:
    decision = outcome.calculation_artifact
    if (
        not isinstance(decision, Mapping)
        or decision.get("schema") not in _PROMOTED_CONTROL_DECISION_SCHEMAS
    ):
        return {}
    raw: Mapping[str, object] | None = None
    for stage in reversed(outcome.calculation_chain):
        candidate = stage.get("control_return")
        if (
            isinstance(candidate, Mapping)
            and candidate.get("schema") in _PROMOTED_CONTROL_RETURN_SCHEMAS
        ):
            raw = candidate
            break
    receipt = raw.get("control_receipt") if isinstance(raw, Mapping) else None
    identity = (
        receipt.get("execution_identity")
        if isinstance(receipt, Mapping)
        else None
    )
    return {
        "operation": (
            raw.get("operation")
            if isinstance(raw, Mapping)
            else decision.get("fingerprint_material", {}).get("worker_operation")
        ),
        "execution_identity_sha256": (
            raw.get("execution_identity_sha256") if isinstance(raw, Mapping) else None
        ),
        "request_sha256": (
            raw.get("request_sha256") if isinstance(raw, Mapping) else None
        ),
        "plan": identity.get("plan") if isinstance(identity, Mapping) else None,
        "scope": identity.get("scope") if isinstance(identity, Mapping) else None,
        "sample_index": (
            identity.get("sample_index") if isinstance(identity, Mapping) else None
        ),
        "sample_role": (
            identity.get("sample_role") if isinstance(identity, Mapping) else None
        ),
        "control_receipt_sha256": decision.get("control_receipt_sha256"),
        "control_return_sha256": decision.get("control_return_sha256"),
        "control_decision_sha256": decision.get("control_decision_sha256"),
        "current_action_kind": decision.get("current_action_kind"),
        "current_tier": decision.get("current_tier"),
        "next_tier": decision.get("next_tier"),
    }


def reduce_promoted_exterior_from_checkpoint(
    checkpoint: Mapping[str, object],
    *,
    queue_ordinal: int,
) -> PromotedPassOutcome:
    """Purely reduce one authenticated exterior raw checkpoint stage."""

    result, entry, retained_stage = _authenticated_promoted_raw_stage(
        checkpoint, queue_ordinal=queue_ordinal, route="EXTERIOR_BF40"
    )

    artifact = _raw_stage_artifact(retained_stage)
    if isinstance(artifact, Mapping) and artifact.get("schema") == (
        "windows-solver.promoted-exterior-control-return/1"
    ):
        raise ValueError(
            "fixed-root control return /1 is forensic history only"
        )
    if isinstance(artifact, Mapping) and artifact.get("schema") == (
        _PROMOTED_CONTROL_RETURN_SCHEMA
    ):
        artifact_fields = {
            "schema",
            "operation",
            "request_schema",
            "request_sha256",
            "execution_identity_sha256",
            "effective_policy_identity",
            "current_tier",
            "current_action_kind",
            "expected_action",
            "canonical_request",
            "control_receipt",
            "control_receipt_sha256",
            "partial_work",
            "control_return_sha256",
        }
        receipts = retained_stage.get("receipts")
        tiers = retained_stage.get("precision_tiers")
        counters = (
            retained_stage.get("sample_count"),
            retained_stage.get("root_read_count"),
            retained_stage.get("worker_launch_count"),
        )
        if (
            set(artifact) != artifact_fields
            or artifact.get("current_tier") not in {"BF40", "BF80"}
            or artifact.get("current_action_kind") not in {"ROOT", "RESPONSE"}
            or not isinstance(artifact.get("canonical_request"), Mapping)
            or not isinstance(artifact.get("control_receipt"), Mapping)
            or not isinstance(receipts, list)
            or not all(isinstance(item, Mapping) for item in receipts)
            or not isinstance(tiers, list)
            or not all(isinstance(item, str) for item in tiers)
            or not all(isinstance(item, int) and item >= 0 for item in counters)
        ):
            raise ValueError("promoted exterior control return is invalid")
        partial_work = _validated_promoted_partial_work(
            artifact["partial_work"],
            queue_ordinal=queue_ordinal,
            leaf_id=str(entry["leaf_id"]),
        )
        if (
            partial_work["sample_count"] != counters[0]
            or partial_work["root_read_count"] != counters[1]
            or partial_work["worker_launch_count"] != counters[2]
            or partial_work["evidence_receipts"] != receipts
        ):
            raise ValueError(
                "promoted exterior control partial work does not match checkpoint"
            )
        _, control_return_sha256 = _promoted_artifact_digest(artifact)
        validated_receipt = validate_persisted_operation_control_receipt(
            artifact["control_receipt"], artifact["canonical_request"]
        )
        identity = validated_receipt.identity
        effective_policy = identity.mapping["effective_policy_identity"]
        effective_policy_sha256 = (
            str(effective_policy["sha256"])
            if isinstance(effective_policy, Mapping)
            else str(effective_policy)
        )
        if (
            artifact.get("operation") != identity.operation
            or artifact.get("request_schema")
            != identity.mapping["request_schema"]
            or artifact.get("request_sha256") != identity.request_sha256
            or artifact.get("execution_identity_sha256") != identity.sha256
            or artifact.get("effective_policy_identity")
            != effective_policy_sha256
            or artifact.get("control_receipt_sha256")
            != validated_receipt.sha256
        ):
            raise ValueError("promoted exterior control identity is invalid")
        attempts = partial_work["attempt_records"]
        current_attempt = attempts[-1] if attempts else None
        if (
            not isinstance(current_attempt, Mapping)
            or current_attempt.get("current_tier") != artifact["current_tier"]
            or current_attempt.get("current_action_kind")
            != artifact["current_action_kind"]
            or current_attempt.get("expected_action") != artifact["expected_action"]
            or current_attempt.get("canonical_request")
            != artifact["canonical_request"]
            or current_attempt.get("control_receipt")
            != artifact["control_receipt"]
            or current_attempt.get("control_receipt_sha256")
            != validated_receipt.sha256
        ):
            raise ValueError("promoted exterior control attempt lineage is invalid")
        report, decision = classify_validated_control_receipt(
            validated_receipt,
            current_tier=str(artifact["current_tier"]),
            current_action_kind=str(artifact["current_action_kind"]),
        )
        if (
            decision.disposition is FailureDisposition.PROMOTION_PENDING
            and (
                decision.queue_kind != artifact["current_action_kind"]
                or decision.next_action_kind != artifact["current_action_kind"]
                or decision.next_precision_tier != "BF80"
            )
        ):
            raise ValueError("promoted control queue transition is invalid")
        decision_content: dict[str, object] = {
            "schema": _PROMOTED_CONTROL_DECISION_SCHEMA,
            "control_return_sha256": control_return_sha256,
            "control_receipt_sha256": validated_receipt.sha256,
            "failure_code": decision.failure_code,
            "failure_fingerprint_sha256": decision.fingerprint_sha256,
            "fingerprint_material": report.fingerprint_material,
            "disposition": decision.disposition.value,
            "queue_kind": decision.queue_kind,
            "current_tier": artifact["current_tier"],
            "current_action_kind": artifact["current_action_kind"],
            "next_tier": decision.next_precision_tier,
            "next_action_kind": decision.next_action_kind,
        }
        decision_artifact = {
            **decision_content,
            "control_decision_sha256": hashlib.sha256(
                canonical_json_bytes(decision_content)
            ).hexdigest(),
        }
        disposition = decision.disposition
        survey_disposition = {
            FailureDisposition.PROMOTION_PENDING: SurveyDisposition.UNRESOLVED,
            FailureDisposition.UNRESOLVED: SurveyDisposition.UNRESOLVED,
            FailureDisposition.DEFERRED: SurveyDisposition.DEFERRED,
            FailureDisposition.REJECTED: SurveyDisposition.REJECTED,
            FailureDisposition.SYSTEM_FAILURE: SurveyDisposition.UNRESOLVED,
        }[disposition]
        return PromotedPassOutcome(
            disposition=survey_disposition,
            reason_code=decision.failure_code,
            precision_tiers=tuple(tiers),
            operation_identity="promoted-exterior-control-decision/v1",
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
            worker_launch_count=int(counters[2]),
            evidence_receipts=tuple(
                copy.deepcopy(dict(item)) for item in receipts
            ),
            calculation_artifact=decision_artifact,
            source_calculation_stage_sha256=str(retained_stage["stage_sha256"]),
            calculation_chain=_raw_stage_chain(retained_stage),
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
    calculation, canonical_artifact = _promoted_exterior_calculation_from_mapping(
        artifact
    )
    promoted_background_cache = _load_promoted_background_cache(result)
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
    composite = PromotedFixedRootComposite(
        background_batch=background,
        component_batch=calculation.component_batch,
        background_receipt_sha256=calculation.background.background_receipt_sha256,
    )
    receipts = retained_stage.get("receipts")
    tiers = retained_stage.get("precision_tiers")
    counters = (
        retained_stage.get("sample_count"),
        retained_stage.get("root_read_count"),
        retained_stage.get("worker_launch_count"),
    )
    if (
        not isinstance(receipts, list)
        or not isinstance(tiers, list)
        or not all(isinstance(item, Mapping) for item in receipts)
        or not all(isinstance(item, int) and item >= 0 for item in counters)
    ):
        raise ValueError("retained exterior calculation state is invalid")
    stage_sha256 = retained_stage.get("stage_sha256")
    if not isinstance(stage_sha256, str) or len(stage_sha256) != 64:
        raise ValueError("retained exterior calculation stage digest is invalid")
    limited_families = tuple(
        family
        for family, roles in (
            ("DOMEGA", BINARY64_FIXED_ROOT_SAMPLE_ROLES[1:5]),
            ("D_C", BINARY64_FIXED_ROOT_SAMPLE_ROLES[5:]),
        )
        if all(
            sample.numerical_conditioning.mapping["precision_limited"] is True
            for sample in composite.samples
            if sample.role in roles
        )
    )
    precision_insufficient = bool(limited_families)
    return PromotedPassOutcome(
        disposition=(
            SurveyDisposition.UNRESOLVED
            if precision_insufficient
            else SurveyDisposition.CALCULATED_AWAITING_ADMISSION
        ),
        reason_code=(
            "INSUFFICIENT_ASYMPTOTIC_PRECISION"
            if precision_insufficient
            else "AWAITING_INDEPENDENT_REVIEW_ADMISSION"
        ),
        precision_tiers=tuple(str(item) for item in tiers),
        operation_identity="promoted-exterior-checkpoint-reduction/v1",
        sample_count=int(counters[0]),
        root_read_count=int(counters[1]),
        worker_launch_count=int(counters[2]),
        evidence_receipts=tuple(copy.deepcopy(dict(item)) for item in receipts),
        calculation_artifact=canonical_artifact,
        source_calculation_stage_sha256=stage_sha256,
        calculation_chain=_raw_stage_chain(retained_stage),
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


def reduce_promoted_control_decision_from_checkpoint(
    checkpoint: Mapping[str, object],
    *,
    queue_ordinal: int,
    route: str = "EXTERIOR_BF40",
) -> PromotedPassOutcome:
    """Reload and reclassify one durable CONTROL decision before use."""

    _result, entry, decision_stage = (
        _authenticated_promoted_control_decision_stage(
            checkpoint, queue_ordinal=queue_ordinal, route=route
        )
    )
    decision = decision_stage.get("control_decision")
    chain = decision_stage.get("calculation_chain")
    return_stage = chain[-1] if isinstance(chain, list) and chain else None
    control_return = (
        return_stage.get("control_return")
        if isinstance(return_stage, Mapping)
        else None
    )
    if (
        not isinstance(decision, Mapping)
        or not isinstance(return_stage, Mapping)
        or return_stage.get("schema") != PROMOTED_CONTROL_RETURN_STAGE_SCHEMA
        or not isinstance(control_return, Mapping)
    ):
        raise ValueError("durable promoted CONTROL proof chain is invalid")
    _revalidate_promoted_control_proof(
        control_return,
        decision,
        queue_ordinal=queue_ordinal,
        leaf_id=str(entry["leaf_id"]),
        route=route,
    )
    receipts = decision_stage.get("receipts")
    counters = (
        decision_stage.get("sample_count"),
        decision_stage.get("root_read_count"),
        decision_stage.get("worker_launch_count"),
    )
    if route == "HORIZON_BF80":
        _authority, horizon_receipts, horizon_counters = (
            _authenticated_horizon_control_stage(
                control_return,
                decision_stage,
                leaf_id=str(entry["leaf_id"]),
            )
        )
        if receipts != horizon_receipts or counters != horizon_counters:
            raise ValueError("durable promoted CONTROL accounting is invalid")
    else:
        partial_work = _validated_promoted_partial_work(
            control_return["partial_work"],
            queue_ordinal=queue_ordinal,
            leaf_id=str(entry["leaf_id"]),
        )
        if (
            not isinstance(receipts, list)
            or not all(isinstance(item, Mapping) for item in receipts)
            or not all(isinstance(item, int) and item >= 0 for item in counters)
            or partial_work["sample_count"] != counters[0]
            or partial_work["root_read_count"] != counters[1]
            or partial_work["worker_launch_count"] != counters[2]
            or partial_work["evidence_receipts"] != receipts
        ):
            raise ValueError("durable promoted CONTROL accounting is invalid")
    failure_disposition = FailureDisposition(str(decision["disposition"]))
    survey_disposition = {
        FailureDisposition.PROMOTION_PENDING: SurveyDisposition.UNRESOLVED,
        FailureDisposition.UNRESOLVED: SurveyDisposition.UNRESOLVED,
        FailureDisposition.DEFERRED: SurveyDisposition.DEFERRED,
        FailureDisposition.REJECTED: SurveyDisposition.REJECTED,
        # This temporary survey value is never committed.  The caller aborts
        # after the SYSTEM_FAILURE decision has itself been durably retained.
        FailureDisposition.SYSTEM_FAILURE: SurveyDisposition.UNRESOLVED,
    }[failure_disposition]
    return PromotedPassOutcome(
        disposition=survey_disposition,
        reason_code=str(decision["failure_code"]),
        precision_tiers=tuple(str(item) for item in decision_stage["precision_tiers"]),
        operation_identity=(
            "promoted-horizon-control-decision/v1"
            if route == "HORIZON_BF80"
            else "promoted-exterior-control-decision/v1"
        ),
        source_record_sha256=(
            None
            if decision_stage.get("source_record_sha256") is None
            else str(decision_stage["source_record_sha256"])
        ),
        source_stage_sha256=(
            None
            if decision_stage.get("source_record_stage_sha256") is None
            else str(decision_stage["source_record_stage_sha256"])
        ),
        sample_count=int(counters[0]),
        root_read_count=int(counters[1]),
        worker_launch_count=int(counters[2]),
        evidence_receipts=tuple(copy.deepcopy(dict(item)) for item in receipts),
        calculation_artifact=copy.deepcopy(dict(decision)),
        source_calculation_stage_sha256=str(decision_stage["stage_sha256"]),
        calculation_chain=_raw_stage_chain(decision_stage),
        tier_timing=tuple(
            copy.deepcopy(dict(item))
            for item in decision_stage.get("tier_timing", [])
            if isinstance(item, Mapping)
        ),
        session_fragments=tuple(
            copy.deepcopy(dict(item))
            for item in decision_stage.get("session_fragments", [])
            if isinstance(item, Mapping)
        ),
    )


def reduce_promoted_horizon_from_checkpoint(
    checkpoint: Mapping[str, object],
    *,
    queue_ordinal: int,
) -> PromotedPassOutcome:
    """Purely reduce one authenticated horizon BF80 checkpoint stage."""

    _result, _entry, retained_stage = _authenticated_promoted_raw_stage(
        checkpoint, queue_ordinal=queue_ordinal, route="HORIZON_BF80"
    )

    retained_artifact = _raw_stage_artifact(retained_stage)
    if retained_artifact.get("schema") == PROMOTED_HORIZON_CONTROL_RETURN_SCHEMA:
        authority, receipts, counters = _authenticated_horizon_control_stage(
            retained_artifact,
            retained_stage,
            leaf_id=str(_entry["leaf_id"]),
        )
        decision_artifact = authority.normalized_decision(
            schema=PROMOTED_HORIZON_CONTROL_DECISION_SCHEMA,
            current_tier="BF80",
            current_action_kind="RESPONSE",
        )
        disposition = FailureDisposition(
            authority.classification.transition.disposition
        )
        survey_disposition = {
            FailureDisposition.PROMOTION_PENDING: SurveyDisposition.UNRESOLVED,
            FailureDisposition.UNRESOLVED: SurveyDisposition.UNRESOLVED,
            FailureDisposition.DEFERRED: SurveyDisposition.DEFERRED,
            FailureDisposition.REJECTED: SurveyDisposition.REJECTED,
            FailureDisposition.SYSTEM_FAILURE: SurveyDisposition.UNRESOLVED,
        }[disposition]
        return PromotedPassOutcome(
            disposition=survey_disposition,
            reason_code=authority.classification.receipt.failure_code,
            precision_tiers=("BF80",),
            operation_identity="promoted-horizon-control-decision/v1",
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
            evidence_receipts=tuple(
                copy.deepcopy(dict(item)) for item in receipts
            ),
            calculation_artifact=decision_artifact,
            source_calculation_stage_sha256=str(retained_stage["stage_sha256"]),
            calculation_chain=_raw_stage_chain(retained_stage),
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
    calculation = PromotedHorizonCalculationResult.from_mapping(retained_artifact)
    artifact = calculation.to_mapping()
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
    retained_receipts = retained_stage.get("receipts")
    if not isinstance(retained_receipts, list) or not all(
        isinstance(item, Mapping) for item in retained_receipts
    ):
        raise ValueError("retained horizon calculation receipts are invalid")
    stage_sha256 = retained_stage.get("stage_sha256")
    if not isinstance(stage_sha256, str) or len(stage_sha256) != 64:
        raise ValueError("retained horizon calculation stage digest is invalid")
    raw_outcome = calculation.numerical_outcome
    authenticated_raw_outcome = StageOutcome(
        digits=raw_outcome["digits"],
        numerical_state=str(raw_outcome["numerical_state"]),
        component_result=raw_outcome["component_result"],
        local_disk_radius_abs=raw_outcome["local_disk_radius_abs"],
        signed_error_channels=tuple(raw_outcome["signed_error_channels"]),
        deep_diagnostics=raw_outcome["deep_diagnostics"],
        self_refinement_enclosed=raw_outcome["self_refinement_enclosed"],
        discrepancy_from_previous_abs=raw_outcome[
            "discrepancy_from_previous_abs"
        ],
        discrepancy_enclosed=raw_outcome["discrepancy_enclosed"],
    )
    raw_component = dict(authenticated_raw_outcome.component_result)
    raw_result_mapping = raw_component.get("result")
    if not isinstance(raw_result_mapping, Mapping):
        raise ValueError("retained horizon component result is missing")
    horizon_result = ComponentResult.from_mapping(raw_result_mapping)
    if horizon_result.to_mapping() != raw_result_mapping:
        raise ValueError("retained horizon component result is not canonical")
    predecessor: StageOutcome | None = None
    source_record_sha256 = retained_stage.get("source_record_sha256")
    source_stage_sha256 = retained_stage.get("source_record_stage_sha256")
    if source_record_sha256 is not None:
        source_record = next(
            (
                item
                for item in _result["records"]
                if item.get("record_sha256") == source_record_sha256
            ),
            None,
        )
        source_stages = (
            source_record.get("stages")
            if isinstance(source_record, Mapping)
            else None
        )
        source_stage = (
            next(
                (
                    item
                    for item in source_stages
                    if isinstance(item, Mapping)
                    and item.get("stage_sha256") == source_stage_sha256
                ),
                None,
            )
            if isinstance(source_stages, list)
            else None
        )
        source_component = (
            source_stage.get("component_result")
            if isinstance(source_stage, Mapping)
            else None
        )
        source_disk = (
            source_stage.get("response_disk")
            if isinstance(source_stage, Mapping)
            else None
        )
        if (
            not isinstance(source_stage, Mapping)
            or source_stage.get("stage_sha256") != source_stage_sha256
            or not isinstance(source_component, Mapping)
            or not isinstance(source_disk, Mapping)
        ):
            raise ValueError("retained horizon predecessor is invalid")
        source_radius = float(source_disk["radius"])
        predecessor = StageOutcome(
            digits=64,
            numerical_state=str(source_stage["numerical_state"]),
            component_result=source_component,
            local_disk_radius_abs=source_radius,
            signed_error_channels=synthetic_stage_signed_error_channels(
                source_component,
                source_radius,
                precision_ladder_applicable=False,
            ),
            deep_diagnostics=(
                source_component.get("deep_diagnostics")
                if isinstance(source_component.get("deep_diagnostics"), Mapping)
                else None
            ),
        )
    previous_result = None
    if predecessor is not None:
        previous_mapping = predecessor.component_result.get("result")
        if not isinstance(previous_mapping, Mapping):
            raise ValueError("retained horizon predecessor result is missing")
        previous_result = ComponentResult.from_mapping(previous_mapping)
        if previous_result.to_mapping() != previous_mapping:
            raise ValueError("retained horizon predecessor result is not canonical")
    comparison_applicable = (
        previous_result is not None
        and previous_result.response is not None
        and horizon_result.response is not None
    )
    precision_delta = (
        horizon_result.response - previous_result.response
        if comparison_applicable
        and horizon_result.response is not None
        and previous_result is not None
        and previous_result.response is not None
        else 0.0j
    )
    discrepancy = abs(precision_delta) if comparison_applicable else None
    discrepancy_enclosed = (
        discrepancy
        <= sum(horizon_result.error_channels.values())
        + predecessor.local_disk_radius_abs
        if discrepancy is not None and predecessor is not None
        else None
    )
    reduced_component = {
        **raw_component,
        # The retained worker artifact keeps the campaign-wire evidence kind.
        # Policy reduction consumes the canonical analytic-component identity;
        # this derived view does not rewrite the authenticated raw artifact.
        "evidence_kind": _ANALYTIC_HORIZON_EVIDENCE_KIND,
        "precision_ladder_discrepancy_applicable": comparison_applicable,
        "precision_ladder_discrepancy_reason": (
            None
            if comparison_applicable
            else "BINARY64_COMPONENT_RESPONSE_UNAVAILABLE"
        ),
    }
    numerical_outcome = StageOutcome(
        digits=80,
        numerical_state=authenticated_raw_outcome.numerical_state,
        component_result=reduced_component,
        local_disk_radius_abs=(
            sum(horizon_result.error_channels.values())
            + (0.0 if discrepancy is None else discrepancy)
        ),
        signed_error_channels=_component_stage_signed_error_channels(
            reduced_component,
            horizon_result,
            precision_delta=precision_delta,
            repeat_applicable=False,
            precision_ladder_applicable=comparison_applicable,
        ),
        deep_diagnostics=authenticated_raw_outcome.deep_diagnostics,
        self_refinement_enclosed=None,
        discrepancy_from_previous_abs=discrepancy,
        discrepancy_enclosed=discrepancy_enclosed,
    )
    policy = promoted_stage_precision_policy(
        numerical_outcome, predecessor=predecessor
    )
    decision = policy["precision120_decision"]
    if not isinstance(decision, Mapping):
        raise ValueError("promoted horizon precision decision is invalid")
    higher_precision_required = (
        decision.get("state") == "REQUESTED"
        or policy["response_repair_precision_digits"] == 120
    )
    terminal_admissible = policy["terminal_admissible"] is True
    return PromotedPassOutcome(
        disposition=(
            SurveyDisposition.CALCULATED_AWAITING_ADMISSION
            if terminal_admissible and not higher_precision_required
            else SurveyDisposition.UNRESOLVED
        ),
        reason_code=(
            "AWAITING_INDEPENDENT_REVIEW_ADMISSION"
            if terminal_admissible and not higher_precision_required
            else str(decision.get("reason") or "HORIZON_BF80_NOT_TERMINAL")
        ),
        precision_tiers=("BF80",),
        operation_identity="promoted-horizon-checkpoint-reduction/v1",
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
        calculation_chain=_raw_stage_chain(retained_stage),
        evidence_receipts=(
            *(copy.deepcopy(dict(item)) for item in retained_receipts),
            copy.deepcopy(dict(policy)),
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
    entry: Mapping[str, object],
    fallback_seal: AuthenticatedRootSeal | None,
) -> AuthenticatedRootSeal | None:
    """Recover the exact BF40 root seal retained before a BF80 continuation."""

    if continuation_stage is None:
        return None
    receipts = continuation_stage.get("receipts")
    if not isinstance(receipts, list):
        raise ValueError("promoted continuation receipts are invalid")
    chain = continuation_stage.get("calculation_chain")
    decision_stage = chain[-1] if isinstance(chain, list) and chain else None
    decision = (
        decision_stage.get("control_decision")
        if isinstance(decision_stage, Mapping)
        else None
    )
    decision_chain = (
        decision_stage.get("calculation_chain")
        if isinstance(decision_stage, Mapping)
        else None
    )
    return_stage = (
        decision_chain[-1]
        if isinstance(decision_chain, list) and decision_chain
        else None
    )
    control_return = (
        return_stage.get("control_return")
        if isinstance(return_stage, Mapping)
        else None
    )
    expected_action = (
        control_return.get("expected_action")
        if isinstance(control_return, Mapping)
        else None
    )
    retained_root_required = (
        entry.get("queue_kind") == PromotionQueueKind.ROOT.value
        and isinstance(decision, Mapping)
        and decision.get("next_action_kind") == "RESPONSE"
    )
    restored: AuthenticatedRootSeal | None = None
    for receipt in receipts:
        if (
            not isinstance(receipt, Mapping)
            or receipt.get("schema") != _PROMOTED_ROOT_RECEIPT_SCHEMA
        ):
            continue
        try:
            _canonical, candidate = _validated_promoted_root_receipt(
                receipt,
                queue_ordinal=int(entry["queue_ordinal"]),
                leaf_id=str(entry["leaf_id"]),
                leaf=leaf,
                expected_precision_tier="BF40",
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("promoted continuation root receipt is invalid") from error
        if restored is not None and restored != candidate:
            raise ValueError("conflicting promoted continuation root")
        if restored is not None:
            raise ValueError("promoted continuation root receipt is duplicated")
        restored = candidate
    if retained_root_required and restored is None:
        if fallback_seal is None:
            raise ValueError(
                "promoted continuation lacks authenticated root success evidence"
            )
        fallback_authority = fallback_seal.root_success_evidence
        if not isinstance(fallback_authority, Mapping):
            raise ValueError(
                "promoted continuation lacks authenticated root success evidence"
            )
        try:
            _canonical, fixed_root, branch_identity, root_seal_sha256 = (
                _validated_promoted_root_success_authority(
                    fallback_authority,
                    precision_tier="BF40",
                    leaf=leaf,
                )
            )
        except (TypeError, ValueError) as error:
            raise ValueError(
                "promoted continuation lacks authenticated root success evidence"
            ) from error
        if (
            fixed_root != fallback_seal.fixed_root
            or branch_identity != fallback_seal.branch_identity
            or root_seal_sha256 != fallback_seal.root_seal_sha256
        ):
            raise ValueError(
                "promoted continuation durable root authority is inconsistent"
            )
        restored = fallback_seal
    if (
        isinstance(decision, Mapping)
        and decision.get("next_action_kind") == "RESPONSE"
        and restored is not None
    ):
        if not isinstance(expected_action, Mapping):
            raise ValueError(
                "promoted continuation root lacks its fixed-root action binding"
            )
        bound_action = _validated_promoted_expected_action(
            expected_action,
            queue_ordinal=int(entry["queue_ordinal"]),
            leaf_id=str(entry["leaf_id"]),
            tier="BF40",
        )
        if (
            bound_action["root_seal_sha256"] != restored.root_seal_sha256
            or bound_action["branch_identity"] != restored.branch_identity
            or bound_action["root_reference_id"]
            != leaf.job.root.root_reference_id
        ):
            raise ValueError("promoted continuation root action binding is invalid")
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
    timing_recorder: TimingSessionRecorder,
    determinant_error_store: ReviewedDeterminantErrorStore | None,
    root_promotion_group: _RootPromotionGroup | None,
    provisional_predecessor_receipt: Mapping[str, object] | None,
    execution_mode: PromotedExecutionMode,
    promoted_background_cache: dict[str, dict[str, object]],
    continuation_stage: Mapping[str, object] | None = None,
    tier_checkpoint: Callable[
        [PromotedPassOutcome], Mapping[str, object]
    ] | None = None,
    background_checkpoint: Callable[[Mapping[str, object]], None] | None = None,
    raw_checkpoint: Callable[[PromotedPassOutcome], PromotedPassOutcome] | None = None,
    trace_event: Callable[[str, Mapping[str, object]], None] | None = None,
) -> PromotedPassOutcome:
    if execution_mode is not PromotedExecutionMode.CALCULATE_ONLY:
        raise ValueError(
            "promoted exterior scheduler is calculation-only; admission owns records"
        )
    queue_kind = PromotionQueueKind(entry["queue_kind"])
    seal = root_seal_lookup(leaf, entry)
    retained_root_seal = _continuation_root_seal(
        continuation_stage,
        leaf=leaf,
        entry=entry,
        fallback_seal=seal,
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
    attempt_records: list[Mapping[str, object]] = []
    calculation_chain: list[Mapping[str, object]] = []
    source_calculation_stage_sha256: str | None = None
    sample_count = root_reads = worker_launches = 0
    digits_to_run = (40, 80)
    if continuation_stage is not None:
        if (
            continuation_stage.get("schema")
            != PROMOTED_CONTROL_CONTINUATION_STAGE_SCHEMA
            or continuation_stage.get("admission_state")
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
        retained_chain = continuation_stage.get("calculation_chain")
        if not isinstance(retained_chain, list) or not all(
            isinstance(item, Mapping) for item in retained_chain
        ):
            raise ValueError("promoted continuation chain is invalid")
        calculation_chain = [
            *(copy.deepcopy(dict(item)) for item in retained_chain),
            copy.deepcopy(dict(continuation_stage)),
        ]
        decision_stage = retained_chain[-1] if retained_chain else None
        retained_decision = (
            decision_stage.get("control_decision")
            if isinstance(decision_stage, Mapping)
            else None
        )
        decision_chain = (
            decision_stage.get("calculation_chain")
            if isinstance(decision_stage, Mapping)
            else None
        )
        return_stage = (
            decision_chain[-1]
            if isinstance(decision_chain, list) and decision_chain
            else None
        )
        raw_control_return = (
            return_stage.get("control_return")
            if isinstance(return_stage, Mapping)
            else None
        )
        proof = continuation_stage.get("control_proof")
        if (
            not isinstance(decision_stage, Mapping)
            or decision_stage.get("schema")
            != PROMOTED_CONTROL_DECISION_STAGE_SCHEMA
            or not isinstance(retained_decision, Mapping)
            or retained_decision.get("schema")
            != PROMOTED_CONTROL_DECISION_SCHEMA
            or not isinstance(return_stage, Mapping)
            or return_stage.get("schema") != PROMOTED_CONTROL_RETURN_STAGE_SCHEMA
            or not isinstance(raw_control_return, Mapping)
            or not isinstance(proof, Mapping)
            or proof.get("schema")
            != PROMOTED_CONTROL_CONTINUATION_PROOF_SCHEMA
            or proof.get("control_return_stage_sha256")
            != return_stage.get("stage_sha256")
            or proof.get("control_return_sha256")
            != raw_control_return.get("control_return_sha256")
            or proof.get("control_decision_stage_sha256")
            != decision_stage.get("stage_sha256")
            or proof.get("control_decision_sha256")
            != retained_decision.get("control_decision_sha256")
        ):
            raise ValueError("promoted continuation lacks mandatory CONTROL proof")
        _revalidate_promoted_control_proof(
            raw_control_return,
            retained_decision,
            queue_ordinal=int(entry["queue_ordinal"]),
            leaf_id=str(entry["leaf_id"]),
            leaf=leaf,
        )
        partial_work = _validated_promoted_partial_work(
            raw_control_return["partial_work"],
            queue_ordinal=int(entry["queue_ordinal"]),
            leaf_id=str(entry["leaf_id"]),
            leaf=leaf,
        )
        if (
            partial_work["sample_count"] != sample_count
            or partial_work["root_read_count"] != root_reads
            or partial_work["worker_launch_count"] != worker_launches
            or partial_work["evidence_receipts"] != retained_receipts
        ):
            raise ValueError(
                "promoted continuation partial work is not authenticated"
            )
        attempt_records = [
            copy.deepcopy(dict(attempt))
            for attempt in partial_work["attempt_records"]
        ]
        if not _control_decision_authorizes_bf80(
            PromotedPassOutcome(
                disposition=SurveyDisposition.UNRESOLVED,
                reason_code=str(retained_decision.get("failure_code")),
                precision_tiers=("BF40",),
                calculation_artifact=retained_decision,
            )
        ):
            raise ValueError("promoted continuation does not authorize BF80")
        source_calculation_stage_sha256 = str(
            continuation_stage["stage_sha256"]
        )
        digits_to_run = (80,)
    elif provisional_predecessor_receipt is not None:
        receipts.append(dict(provisional_predecessor_receipt))

    def checkpoint_control_return(
        control_receipt: ValidatedControlReceipt,
        *,
        tier: str,
        current_action_kind: str,
        expected_action: Mapping[str, object] | None,
    ) -> PromotedPassOutcome:
        nonlocal sample_count, root_reads, worker_launches, receipts, attempt_records
        if raw_checkpoint is None:
            raise ValueError("promoted control return is not checkpointable")
        canonical_request = control_receipt.canonical_request
        if canonical_request is None:
            raise ValueError("promoted control receipt lost its canonical request")
        identity = control_receipt.identity
        effective_policy = identity.mapping["effective_policy_identity"]
        effective_policy_sha256 = (
            str(effective_policy["sha256"])
            if isinstance(effective_policy, Mapping)
            else str(effective_policy)
        )
        attempt_records.append(_promoted_attempt_record(
            control_receipt,
            tier=tier,
            current_action_kind=current_action_kind,
            expected_action=expected_action,
        ))
        partial_work = {
            "schema": _PROMOTED_PARTIAL_WORK_SCHEMA,
            "evidence_receipts": copy.deepcopy(receipts),
            "attempt_records": copy.deepcopy(attempt_records),
        }
        derived = _validated_promoted_partial_work(
            partial_work,
            queue_ordinal=int(entry["queue_ordinal"]),
            leaf_id=str(entry["leaf_id"]),
            leaf=leaf,
        )
        sample_count = int(derived["sample_count"])
        root_reads = int(derived["root_read_count"])
        worker_launches = int(derived["worker_launch_count"])
        receipts = [
            copy.deepcopy(dict(item)) for item in derived["evidence_receipts"]
        ]
        content: dict[str, object] = {
            "schema": _PROMOTED_CONTROL_RETURN_SCHEMA,
            "operation": identity.operation,
            "request_schema": identity.mapping["request_schema"],
            "request_sha256": identity.request_sha256,
            "execution_identity_sha256": identity.sha256,
            "effective_policy_identity": effective_policy_sha256,
            "current_tier": tier,
            "current_action_kind": current_action_kind,
            "expected_action": (
                None
                if expected_action is None
                else _validated_promoted_expected_action(expected_action)
            ),
            "canonical_request": copy.deepcopy(dict(canonical_request)),
            "control_receipt": control_receipt.to_mapping(),
            "control_receipt_sha256": control_receipt.sha256,
            "partial_work": partial_work,
        }
        artifact = {
            **content,
            "control_return_sha256": hashlib.sha256(
                canonical_json_bytes(content)
            ).hexdigest(),
        }
        timing_recorder.complete_tier()
        return raw_checkpoint(PromotedPassOutcome(
            disposition=SurveyDisposition.UNRESOLVED,
            reason_code=control_receipt.failure_code,
            precision_tiers=tuple(tiers),
            operation_identity="promoted-exterior-control-return/v2",
            sample_count=sample_count,
            root_read_count=root_reads,
            worker_launch_count=worker_launches,
            evidence_receipts=tuple(receipts),
            calculation_artifact=artifact,
            source_calculation_stage_sha256=source_calculation_stage_sha256,
            calculation_chain=tuple(calculation_chain),
        ))

    def retain_continuation_chain(
        reduced: PromotedPassOutcome,
    ) -> tuple[list[Mapping[str, object]], str]:
        if tier_checkpoint is None:
            raise ValueError("BF40 precision continuation is not checkpointable")
        continuation = tier_checkpoint(reduced)
        if (
            not isinstance(continuation, Mapping)
            or continuation.get("admission_state") != "NUMERICAL_CONTINUATION"
        ):
            raise ValueError("BF40 continuation checkpoint is invalid")
        prior_chain = continuation.get("calculation_chain")
        if not isinstance(prior_chain, list) or not all(
            isinstance(item, Mapping) for item in prior_chain
        ):
            raise ValueError("BF40 continuation chain is invalid")
        return (
            [
                *(copy.deepcopy(dict(item)) for item in prior_chain),
                copy.deepcopy(dict(continuation)),
            ],
            str(continuation["stage_sha256"]),
        )

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
                control_receipt = _promoted_control_receipt(
                    error,
                    leaf=leaf,
                    digits=digits,
                    current_action_kind="ROOT",
                )
                if control_receipt is None:
                    raise
                reduced = checkpoint_control_return(
                    control_receipt,
                    tier=tier,
                    current_action_kind="ROOT",
                    expected_action=None,
                )
                control_decision = reduced.calculation_artifact
                if (
                    digits == 40
                    and isinstance(control_decision, Mapping)
                    and control_decision.get("schema")
                    == _PROMOTED_CONTROL_DECISION_SCHEMA
                    and control_decision.get("disposition")
                    == FailureDisposition.PROMOTION_PENDING.value
                    and control_decision.get("queue_kind") == "ROOT"
                    and control_decision.get("current_action_kind") == "ROOT"
                    and control_decision.get("next_action_kind") == "ROOT"
                    and control_decision.get("next_tier") == "BF80"
                ):
                    calculation_chain, source_calculation_stage_sha256 = (
                        retain_continuation_chain(reduced)
                    )
                    continue
                if root_promotion_group is not None:
                    root_promotion_group.fail(reduced)
                return reduced
            if not isinstance(root_result, PromotedRootSolveResult):
                raise ValueError("promoted PRIMARY runner returned an invalid result")
            if root_result.precision_tier != tier:
                raise ValueError("promoted PRIMARY result tier mismatch")
            seal = root_result.seal
            if seal.branch_identity != leaf.job.root.branch_id:
                raise ValueError("promoted PRIMARY root seal branch mismatch")
            if root_promotion_group is None:
                raise ValueError("promoted root success lacks dependency authority")
            root_receipt = _promoted_root_receipt(
                root_result,
                entry=entry,
                leaf=leaf,
                dependency_key=root_promotion_group.dependency_key,
            )
            root_seal_publish(leaf, seal)
            root_promotion_group.publish(seal, tier)
            receipts.append(root_receipt)

        background_cache_key, background_reuse_key = _promoted_background_key(
            leaf, seal, digits
        )
        cached_background = promoted_background_cache.get(background_cache_key)
        acquired_background = False
        immediate_background_receipt: Mapping[str, object] | None = None
        resumed_own_background = False
        background_receipt_retained = False
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
            retained_background_receipt = cached_background.get(
                "background_receipt"
            )
            if isinstance(retained_background_receipt, Mapping):
                receipts.append(
                    copy.deepcopy(dict(retained_background_receipt))
                )
                background_receipt_retained = True
            if trace_event is not None:
                receipt = cached_background.get("background_receipt")
                trace_event(
                    "PROMOTED_BACKGROUND_REUSED",
                    {
                        "tier": tier,
                        "background_receipt_sha256": (
                            None
                            if not isinstance(receipt, Mapping)
                            else receipt.get("receipt_sha256")
                        ),
                        "background_reuse_key_sha256": background_cache_key,
                        "source_queue_ordinal": cached_background.get(
                            "queue_ordinal"
                        ),
                        "source_leaf_id": cached_background.get("leaf_id"),
                    },
                )
        requested_sample_roles = tuple(_PROMOTED_COMPONENT_SAMPLE_ROLES)
        prepare_request = getattr(backend, "prepare_fixed_root_survey_request", None)
        if not callable(prepare_request):
            raise ValueError(
                "promoted backend lacks prepared fixed-root request authority"
            )
        if cached_background is None:
            if background_checkpoint is None:
                raise ValueError(
                    "promoted work requires background checkpointing before "
                    "mechanism samples"
                )
            prepared_background = prepare_request(
                leaf.job,
                fixed_root=seal.fixed_root,
                root_seal_sha256=seal.root_seal_sha256,
                branch_identity=seal.branch_identity,
                plan=FixedRootSurveyPlan.CANONICAL_BACKGROUND_FIVE,
            )
            expected_background = _promoted_expected_fixed_root_action(
                prepared_background,
                entry=entry,
                leaf=leaf,
                tier=tier,
                plan=FixedRootSurveyPlan.CANONICAL_BACKGROUND_FIVE,
            )
            worker_launches += 1
            if trace_event is not None:
                trace_event(
                    "PROMOTED_BACKGROUND_REQUESTED",
                    {
                        "tier": tier,
                        "operation": "fixed-root-survey-batch",
                        "scope": "REQUEST",
                        "background_reuse_key_sha256": background_cache_key,
                        "worker_plan": expected_background["plan"],
                        "request_sha256": expected_background["request_sha256"],
                        "execution_identity_sha256": expected_background[
                            "request_execution_identity_sha256"
                        ],
                    },
                )
            try:
                background_batch = backend.fixed_root_survey_batch(
                    leaf.job,
                    fixed_root=seal.fixed_root,
                    root_seal_sha256=seal.root_seal_sha256,
                    branch_identity=seal.branch_identity,
                    plan=FixedRootSurveyPlan.CANONICAL_BACKGROUND_FIVE,
                    prepared_request=prepared_background,
                )
            except KeyboardInterrupt:
                raise
            except Exception as error:
                control_receipt = _promoted_control_receipt(
                    error,
                    leaf=leaf,
                    digits=digits,
                    current_action_kind="RESPONSE",
                    expected_action=expected_background,
                )
                if control_receipt is None:
                    raise
                reduced = checkpoint_control_return(
                    control_receipt,
                    tier=tier,
                    current_action_kind="RESPONSE",
                    expected_action=expected_background,
                )
                control_decision = reduced.calculation_artifact
                if (
                    digits == 40
                    and isinstance(control_decision, Mapping)
                    and control_decision.get("schema")
                    == _PROMOTED_CONTROL_DECISION_SCHEMA
                    and control_decision.get("disposition")
                    == FailureDisposition.PROMOTION_PENDING.value
                    and control_decision.get("queue_kind") == "RESPONSE"
                    and control_decision.get("current_action_kind") == "RESPONSE"
                    and control_decision.get("next_action_kind") == "RESPONSE"
                    and control_decision.get("next_tier") == "BF80"
                ):
                    calculation_chain, source_calculation_stage_sha256 = (
                        retain_continuation_chain(reduced)
                    )
                    continue
                return reduced
            if not isinstance(background_batch, JuliaFixedRootSurveyBatch):
                raise ValueError("promoted backend returned an invalid survey batch")
            if (
                background_batch.precision_tier.value != f"bigfloat-{digits}"
                or background_batch.root_seal_sha256 != seal.root_seal_sha256
                or background_batch.root_read_count != 0
                or background_batch.julia_launch_count != 1
                or background_batch.sample_roles
                != tuple(_PROMOTED_BACKGROUND_SAMPLE_ROLES)
                or background_batch.request_sha256
                != prepared_background.request_sha256
                or hashlib.sha256(canonical_json_bytes(
                    dict(background_batch.execution_identity)
                )).hexdigest() != prepared_background.execution_identity_sha256
            ):
                raise ValueError("promoted background acquisition batch is invalid")
            if trace_event is not None:
                trace_event(
                    "PROMOTED_BACKGROUND_RETURNED",
                    {
                        "tier": tier,
                        "operation": "fixed-root-survey-batch",
                        "scope": "REQUEST",
                        "plan": background_batch.plan.value,
                        "execution_identity_sha256": (
                            prepared_background.execution_identity_sha256
                        ),
                        "background_reuse_key_sha256": background_cache_key,
                        "worker_request_sha256": background_batch.request_sha256,
                        "sample_count": len(background_batch.samples),
                    },
                )
            background_samples = tuple(background_batch.samples)
            immediate_background_receipt = _promoted_background_receipt(
                batch=background_batch,
                cache_key_sha256=background_cache_key,
                reuse_key=background_reuse_key,
                source_queue_ordinal=int(entry["queue_ordinal"]),
                source_leaf_id=str(entry["leaf_id"]),
            )
            # The durable receipt is the accounting authority.  Only publish
            # the in-memory cache and route counters after its commit returns.
            background_checkpoint(immediate_background_receipt)
            cache_entry = {
                "background_sha256": immediate_background_receipt[
                    "background_sha256"
                ],
                "background_batch": background_batch,
                "background_samples": background_samples,
                "background_receipt": immediate_background_receipt,
                "queue_ordinal": int(entry["queue_ordinal"]),
                "leaf_id": str(entry["leaf_id"]),
                "reuse_key": copy.deepcopy(dict(background_reuse_key)),
            }
            promoted_background_cache[background_cache_key] = cache_entry
            sample_count += len(_PROMOTED_BACKGROUND_SAMPLE_ROLES)
            receipts.append(copy.deepcopy(dict(immediate_background_receipt)))
            background_receipt_retained = True
            acquired_background = True
            cached_background = cache_entry

        prepared_component = prepare_request(
            leaf.job,
            fixed_root=seal.fixed_root,
            root_seal_sha256=seal.root_seal_sha256,
            branch_identity=seal.branch_identity,
            plan=FixedRootSurveyPlan.MECHANISM_COMPONENT_FOUR,
        )
        expected_component = _promoted_expected_fixed_root_action(
            prepared_component,
            entry=entry,
            leaf=leaf,
            tier=tier,
            plan=FixedRootSurveyPlan.MECHANISM_COMPONENT_FOUR,
        )
        worker_launches += 1
        if trace_event is not None:
            trace_event(
                "PROMOTED_COMPONENT_REQUESTED",
                {
                    "tier": tier,
                    "operation": "fixed-root-survey-batch",
                    "scope": "REQUEST",
                    "background_reuse_key_sha256": background_cache_key,
                    "worker_plan": expected_component["plan"],
                    "request_sha256": expected_component["request_sha256"],
                    "execution_identity_sha256": expected_component[
                        "request_execution_identity_sha256"
                    ],
                },
            )
        try:
            executed_batch = backend.fixed_root_survey_batch(
                leaf.job,
                fixed_root=seal.fixed_root,
                root_seal_sha256=seal.root_seal_sha256,
                branch_identity=seal.branch_identity,
                plan=FixedRootSurveyPlan.MECHANISM_COMPONENT_FOUR,
                prepared_request=prepared_component,
            )
        except KeyboardInterrupt:
            raise
        except Exception as error:
            control_receipt = _promoted_control_receipt(
                error,
                leaf=leaf,
                digits=digits,
                current_action_kind="RESPONSE",
                expected_action=expected_component,
            )
            if control_receipt is None:
                raise
            reduced = checkpoint_control_return(
                control_receipt,
                tier=tier,
                current_action_kind="RESPONSE",
                expected_action=expected_component,
            )
            control_decision = reduced.calculation_artifact
            if (
                digits == 40
                and isinstance(control_decision, Mapping)
                and control_decision.get("schema")
                == _PROMOTED_CONTROL_DECISION_SCHEMA
                and control_decision.get("disposition")
                == FailureDisposition.PROMOTION_PENDING.value
                and control_decision.get("queue_kind") == "RESPONSE"
                and control_decision.get("current_action_kind") == "RESPONSE"
                and control_decision.get("next_action_kind") == "RESPONSE"
                and control_decision.get("next_tier") == "BF80"
            ):
                calculation_chain, source_calculation_stage_sha256 = (
                    retain_continuation_chain(reduced)
                )
                continue
            return reduced
        if not isinstance(executed_batch, JuliaFixedRootSurveyBatch):
            raise ValueError("promoted backend returned an invalid survey batch")
        if (
            executed_batch.precision_tier.value != f"bigfloat-{digits}"
            or executed_batch.root_seal_sha256 != seal.root_seal_sha256
            or executed_batch.root_read_count != 0
            or executed_batch.julia_launch_count != 1
            or executed_batch.request_sha256 != prepared_component.request_sha256
            or hashlib.sha256(canonical_json_bytes(
                dict(executed_batch.execution_identity)
            )).hexdigest() != prepared_component.execution_identity_sha256
        ):
            raise ValueError("promoted fixed-root survey batch budget mismatch")
        if executed_batch.sample_roles != tuple(_PROMOTED_COMPONENT_SAMPLE_ROLES):
            raise ValueError("promoted mechanism sample plan is invalid")
        if trace_event is not None:
            trace_event(
                "PROMOTED_COMPONENT_RETURNED",
                {
                    "tier": tier,
                    "operation": "fixed-root-survey-batch",
                    "scope": "REQUEST",
                    "plan": executed_batch.plan.value,
                    "execution_identity_sha256": (
                        prepared_component.execution_identity_sha256
                    ),
                    "background_reuse_key_sha256": background_cache_key,
                    "worker_request_sha256": executed_batch.request_sha256,
                    "sample_count": len(executed_batch.samples),
                },
            )
        if cached_background is None:
            raise ValueError("promoted background was not retained before component")
        background_batch = cached_background.get("background_batch")
        background_receipt = cached_background.get("background_receipt")
        if not isinstance(background_batch, JuliaFixedRootSurveyBatch) or not isinstance(
            background_receipt, Mapping
        ):
            raise ValueError(
                "legacy promoted background cannot be mixed into a v3 component"
            )
        cached_sha256 = cached_background.get("background_sha256")
        if cached_sha256 != background_receipt.get("background_sha256"):
            raise ValueError("conflicting promoted background")
        binding = PromotedBackgroundBinding(
            background_receipt_sha256=str(background_receipt["receipt_sha256"]),
            background_worker_request_sha256=background_batch.request_sha256,
            background_sha256=str(cached_sha256),
            background_reuse_key_sha256=PromotedBackgroundReuseKey.from_mapping(
                background_receipt["reuse_key"]
            ).sha256,
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
        if not background_receipt_retained:
            receipts.append(copy.deepcopy(dict(background_receipt)))
        calculation_mapping = calculation.to_mapping()
        receipts.append({
            "schema": "windows-solver.promoted-exterior-calculation-receipt/3",
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
        if raw_checkpoint is None:
            raise ValueError(
                "CALCULATE_ONLY promoted work requires raw calculation checkpointing"
            )
        raw_outcome = PromotedPassOutcome(
            disposition=SurveyDisposition.CALCULATED_AWAITING_ADMISSION,
            reason_code="RAW_PROMOTED_EXTERIOR_CALCULATION_RETAINED",
            precision_tiers=tuple(tiers),
            operation_identity="promoted-exterior-calculation/v3",
            sample_count=sample_count,
            root_read_count=root_reads,
            worker_launch_count=worker_launches,
            evidence_receipts=tuple(receipts),
            calculation_artifact=calculation_mapping,
            source_calculation_stage_sha256=(
                source_calculation_stage_sha256
            ),
            calculation_chain=tuple(calculation_chain),
        )
        # The checkpoint must include the completed numerical timing too; an
        # interrupt after this point must not erase a returned worker result.
        timing_recorder.complete_tier()
        reduced = raw_checkpoint(raw_outcome)
        if not isinstance(reduced, PromotedPassOutcome):
            raise ValueError("raw promoted calculation reduction is invalid")
        if (
            digits == 40
            and reduced.disposition is SurveyDisposition.UNRESOLVED
            and _outcome_authorizes_bf80(reduced)
        ):
            calculation_chain, source_calculation_stage_sha256 = (
                retain_continuation_chain(reduced)
            )
            continue
        return reduced
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
        _promoted_artifact_digest(calculation_artifact)
    stage_schema = PROMOTED_CALCULATION_STAGE_SCHEMA
    stage_payload: dict[str, object] = {
        "calculation_artifact": calculation_artifact,
    }
    if preflight.mode is PromotedExecutionMode.BLOCK_ALL:
        if (
            admission_state
            not in {
                PromotionQueueDisposition.UNRESOLVED.value,
                PromotionQueueDisposition.DEFERRED.value,
                PromotionQueueDisposition.REJECTED.value,
            }
            or calculation_artifact is not None
            or calculation_chain
        ):
            raise ValueError("policy terminal stage authority is invalid")
        policy_content: dict[str, object] = {
            "schema": PROMOTED_POLICY_TERMINAL_DECISION_SCHEMA,
            "disposition": admission_state,
            "reason_code": outcome.reason_code,
            "operation_identity": outcome.operation_identity,
            "route": route,
            "execution_mode": preflight.mode.value,
        }
        stage_schema = PROMOTED_POLICY_TERMINAL_STAGE_SCHEMA
        stage_payload = {
            "policy_terminal": {
                **policy_content,
                "policy_terminal_sha256": hashlib.sha256(
                    canonical_json_bytes(policy_content)
                ).hexdigest(),
            }
        }
    elif admission_state == PromotionQueueDisposition.CONTROL_RETURN_RETAINED.value:
        expected_return_schema, _decision_schema = (
            _promoted_control_schemas_for_route(route)
        )
        if (
            not isinstance(calculation_artifact, Mapping)
            or calculation_artifact.get("schema")
            != expected_return_schema
        ):
            raise ValueError("CONTROL-return stage lacks its typed artifact")
        stage_schema = PROMOTED_CONTROL_RETURN_STAGE_SCHEMA
        stage_payload = {"control_return": calculation_artifact}
    elif admission_state == PromotionQueueDisposition.CONTROL_DECISION_RETAINED.value:
        _return_schema, expected_decision_schema = (
            _promoted_control_schemas_for_route(route)
        )
        if (
            not isinstance(calculation_artifact, Mapping)
            or calculation_artifact.get("schema")
            != expected_decision_schema
        ):
            raise ValueError("CONTROL-decision stage lacks its typed artifact")
        stage_schema = PROMOTED_CONTROL_DECISION_STAGE_SCHEMA
        stage_payload = {"control_decision": calculation_artifact}
    elif admission_state == PromotionQueueDisposition.NUMERICAL_CONTINUATION.value:
        decision_stage = calculation_chain[-1] if calculation_chain else None
        decision = (
            decision_stage.get("control_decision")
            if isinstance(decision_stage, Mapping)
            else None
        )
        decision_chain = (
            decision_stage.get("calculation_chain")
            if isinstance(decision_stage, Mapping)
            else None
        )
        return_stage = (
            decision_chain[-1]
            if isinstance(decision_chain, list) and decision_chain
            else None
        )
        control_return = (
            return_stage.get("control_return")
            if isinstance(return_stage, Mapping)
            else None
        )
        if (
            not isinstance(decision_stage, Mapping)
            or decision_stage.get("schema")
            != PROMOTED_CONTROL_DECISION_STAGE_SCHEMA
            or not isinstance(decision, Mapping)
            or calculation_artifact != decision
            or not isinstance(return_stage, Mapping)
            or return_stage.get("schema")
            != PROMOTED_CONTROL_RETURN_STAGE_SCHEMA
            or not isinstance(control_return, Mapping)
        ):
            raise ValueError("BF80 continuation lacks its durable CONTROL chain")
        proof_content: dict[str, object] = {
            "schema": PROMOTED_CONTROL_CONTINUATION_PROOF_SCHEMA,
            "control_return_stage_sha256": return_stage["stage_sha256"],
            "control_return_sha256": control_return["control_return_sha256"],
            "control_decision_stage_sha256": decision_stage["stage_sha256"],
            "control_decision_sha256": decision["control_decision_sha256"],
            "current_tier": decision["current_tier"],
            "current_action_kind": decision["current_action_kind"],
            "next_tier": decision["next_tier"],
            "next_action_kind": decision["next_action_kind"],
        }
        stage_schema = PROMOTED_CONTROL_CONTINUATION_STAGE_SCHEMA
        stage_payload = {
            "control_proof": {
                **proof_content,
                "proof_sha256": hashlib.sha256(
                    canonical_json_bytes(proof_content)
                ).hexdigest(),
            }
        }
    material: dict[str, object] = {
        "schema": stage_schema,
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
        **stage_payload,
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


def _commit_promoted_control_return(
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
    """Persist a typed raw CONTROL return before classification."""

    artifact = outcome.calculation_artifact
    expected_return_schema, _decision_schema = _promoted_control_schemas_for_route(
        route
    )
    if (
        execution_preflight is None
        or execution_preflight.mode is not PromotedExecutionMode.CALCULATE_ONLY
        or layer1_lock_receipt_sha256 is None
        or not isinstance(artifact, Mapping)
        or artifact.get("schema") != expected_return_schema
    ):
        raise ValueError("CONTROL return lacks authenticated route policy")
    result = validate_schema11_checkpoint(checkpoint)
    queue_entry = result["promotion_queue"]["entries"][queue_ordinal]
    _digest_field, artifact_sha256 = _promoted_artifact_digest(artifact)
    stage = _retained_promoted_stage(
        leaf=leaf,
        queue_entry=queue_entry,
        queue_ordinal=queue_ordinal,
        route=route,
        outcome=outcome,
        preflight=execution_preflight,
        layer1_lock_receipt_sha256=layer1_lock_receipt_sha256,
        scientific_computation_identity=scientific_computation_identity,
        admission_state=PromotionQueueDisposition.CONTROL_RETURN_RETAINED.value,
        numerical_disposition="CONTROL_RETURN_RETAINED",
    )
    return retain_promoted_control_return(
        result,
        queue_ordinal=queue_ordinal,
        promoted_stage=stage,
        execution_mode=execution_preflight.mode.value,
        disposition_receipt={
            "schema": "windows-solver.promoted-control-return-retention/1",
            "queue_ordinal": queue_ordinal,
            "leaf_id": str(queue_entry["leaf_id"]),
            "route": route,
            "reason_code": outcome.reason_code,
            "control_return_sha256": artifact_sha256,
        },
        layer1_guard=layer1_guard,
    )


def _commit_promoted_control_decision(
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
    """Persist a classified CONTROL decision as its own checkpoint stage."""

    artifact = outcome.calculation_artifact
    _return_schema, expected_decision_schema = _promoted_control_schemas_for_route(
        route
    )
    if (
        execution_preflight is None
        or execution_preflight.mode is not PromotedExecutionMode.CALCULATE_ONLY
        or layer1_lock_receipt_sha256 is None
        or not isinstance(artifact, Mapping)
        or artifact.get("schema") != expected_decision_schema
    ):
        raise ValueError("CONTROL decision lacks authenticated route policy")
    result = validate_schema11_checkpoint(checkpoint)
    queue_entry = result["promotion_queue"]["entries"][queue_ordinal]
    _promoted_artifact_digest(artifact)
    stage = _retained_promoted_stage(
        leaf=leaf,
        queue_entry=queue_entry,
        queue_ordinal=queue_ordinal,
        route=route,
        outcome=outcome,
        preflight=execution_preflight,
        layer1_lock_receipt_sha256=layer1_lock_receipt_sha256,
        scientific_computation_identity=scientific_computation_identity,
        admission_state=PromotionQueueDisposition.CONTROL_DECISION_RETAINED.value,
        numerical_disposition=str(artifact["disposition"]),
    )
    return retain_promoted_control_decision(
        result,
        queue_ordinal=queue_ordinal,
        promoted_stage=stage,
        execution_mode=execution_preflight.mode.value,
        disposition_receipt={
            "schema": "windows-solver.promoted-control-decision-retention/1",
            "queue_ordinal": queue_ordinal,
            "leaf_id": str(queue_entry["leaf_id"]),
            "route": route,
            "reason_code": outcome.reason_code,
            "control_return_sha256": artifact["control_return_sha256"],
            "control_decision_sha256": artifact["control_decision_sha256"],
        },
        layer1_guard=layer1_guard,
    )


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
    """Persist BF80 authority from a reloaded durable CONTROL decision."""

    if (
        execution_preflight is None
        or execution_preflight.mode is not PromotedExecutionMode.CALCULATE_ONLY
        or layer1_lock_receipt_sha256 is None
    ):
        raise ValueError(
            "promoted continuation requires calculation-only route policy"
        )
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
    if outcome.calculation_artifact.get("schema") in (
        _PROMOTED_CONTROL_RETURN_SCHEMAS | _PROMOTED_CONTROL_DECISION_SCHEMAS
    ):
        raise ValueError("CONTROL artifact cannot enter calculation retention")
    digest_field, artifact_sha256 = _promoted_artifact_digest(
        outcome.calculation_artifact
    )
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
            "schema": "windows-solver.promoted-raw-return-retention/3",
            "queue_ordinal": queue_ordinal,
            "leaf_id": str(queue_entry["leaf_id"]),
            "route": route,
            "reason_code": "RAW_PROMOTED_RETURN_RETAINED",
            "artifact_digest_field": digest_field,
            "artifact_sha256": artifact_sha256,
        },
        layer1_guard=layer1_guard,
    )


def _validate_promoted_scheduler_preflight(
    value: PromotedExecutionPreflight | None,
) -> PromotedExecutionPreflight:
    """Accept only a calculation-only or fully blocked scheduler authority.

    A calibration receipt can express general admission authority, but this
    scheduler is not an admission actor.  It may retain numerical work or
    defer it; it may never turn that work into a terminal record.
    """

    if (
        not isinstance(value, PromotedExecutionPreflight)
        or not isinstance(value.mode, PromotedExecutionMode)
    ):
        raise ValueError("promoted scheduler route preflight is invalid")
    if value.mode not in {
        PromotedExecutionMode.CALCULATE_ONLY,
        PromotedExecutionMode.BLOCK_ALL,
    }:
        raise ValueError(
            "promoted scheduler is calculation-only; use independent admission"
        )
    return value


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
    layer1_guard: object | None = None,
) -> dict[str, object]:
    result = validate_schema11_checkpoint(checkpoint)
    execution_preflight = _validate_promoted_scheduler_preflight(
        execution_preflight
    )
    retained_exterior_worker_limit = (
        execution_preflight.mode is PromotedExecutionMode.CALCULATE_ONLY
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
    if execution_preflight.mode is PromotedExecutionMode.CALCULATE_ONLY:
        if outcome.record is not None:
            raise ValueError(
                "calculation-only promoted outcome cannot carry a terminal record"
            )
        if outcome.disposition is SurveyDisposition.COMPLETED:
            raise ValueError(
                "calculation-only promoted outcome cannot complete a record"
            )
        if layer1_lock_receipt_sha256 is None:
            raise ValueError("retained promoted stage lacks the Layer-1 lock receipt")
        queue_entry = result["promotion_queue"]["entries"][queue_ordinal]
        terminal_queue_disposition = {
            SurveyDisposition.UNRESOLVED: PromotionQueueDisposition.UNRESOLVED,
            SurveyDisposition.DEFERRED: PromotionQueueDisposition.DEFERRED,
            SurveyDisposition.REJECTED: PromotionQueueDisposition.REJECTED,
        }.get(outcome.disposition)
        if terminal_queue_disposition is not None:
            is_control_decision = (
                isinstance(outcome.calculation_artifact, Mapping)
                and outcome.calculation_artifact.get("schema")
                in _PROMOTED_CONTROL_DECISION_SCHEMAS
            )
            disposition_receipt = {
                "schema": "windows-solver.promoted-checkpoint-reduction/1",
                "leaf_id": leaf_id,
                "queue_ordinal": queue_ordinal,
                "route": route,
                "reason_code": outcome.reason_code,
                "precision_tiers": list(outcome.precision_tiers),
                "source_calculation_stage_sha256": (
                    outcome.source_calculation_stage_sha256
                ),
            }
            if is_control_decision:
                retained_bucket = result["promoted_stage_ledger"].get(
                    str(queue_ordinal)
                )
                retained_decision_stage = (
                    retained_bucket.get(leaf_id)
                    if isinstance(retained_bucket, Mapping)
                    else None
                )
                if not isinstance(retained_decision_stage, Mapping):
                    raise ValueError("durable CONTROL decision stage is missing")
                disposition_receipt = (
                    promoted_control_terminal_disposition_receipt(
                        queue_entry,
                        retained_decision_stage,
                    )
                )
                result = retain_promoted_control_terminal(
                    result,
                    queue_ordinal=queue_ordinal,
                    disposition=terminal_queue_disposition,
                    disposition_receipt=disposition_receipt,
                    layer1_guard=layer1_guard,
                )
            else:
                promoted_stage = _retained_promoted_stage(
                    leaf=leaf,
                    queue_entry=queue_entry,
                    queue_ordinal=queue_ordinal,
                    route=route,
                    outcome=outcome,
                    preflight=execution_preflight,
                    layer1_lock_receipt_sha256=layer1_lock_receipt_sha256,
                    scientific_computation_identity=scientific_computation_identity,
                    admission_state=terminal_queue_disposition.value,
                    numerical_disposition=outcome.disposition.value,
                )
                result = retain_promoted_terminal_reduction(
                    result,
                    queue_ordinal=queue_ordinal,
                    promoted_stage=promoted_stage,
                    disposition=terminal_queue_disposition,
                    disposition_receipt=disposition_receipt,
                    layer1_guard=layer1_guard,
                )
            return record_survey_disposition(
                result,
                survey_pass=SurveyPass.PROMOTED,
                leaf_id=leaf_id,
                disposition=outcome.disposition,
                source_record_sha256=outcome.source_record_sha256,
                result_record_sha256=None,
                operation_identity=outcome.operation_identity,
                precision_tiers=outcome.precision_tiers,
                reason_code=outcome.reason_code,
                sample_count=outcome.sample_count,
                sample_limit=outcome.sample_limit,
                root_read_count=outcome.root_read_count,
                root_read_limit=outcome.root_read_limit,
                worker_launch_count=outcome.worker_launch_count,
                worker_launch_limit=worker_launch_limit,
                tier_timing=outcome.tier_timing,
                session_fragments=outcome.session_fragments,
                layer1_guard=layer1_guard,
            )
        if outcome.disposition is not SurveyDisposition.CALCULATED_AWAITING_ADMISSION:
            raise ValueError("promoted checkpoint reduction disposition is invalid")
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
    if outcome.record is not None:
        raise ValueError("promoted scheduler cannot retain a terminal record")
    if outcome.disposition is SurveyDisposition.COMPLETED:
        raise ValueError("promoted scheduler cannot complete a terminal record")
    if execution_preflight.mode is not PromotedExecutionMode.BLOCK_ALL:
        raise ValueError("promoted scheduler execution mode is unsupported")
    record_sha256 = None
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
    if provisional_reuse_receipt is not None:
        raise ValueError("blocked policy terminal cannot carry reuse evidence")
    policy_stage = _retained_promoted_stage(
        leaf=leaf,
        queue_entry=result["promotion_queue"]["entries"][queue_ordinal],
        queue_ordinal=queue_ordinal,
        route=route,
        outcome=outcome,
        preflight=execution_preflight,
        layer1_lock_receipt_sha256=layer1_lock_receipt_sha256,
        scientific_computation_identity=scientific_computation_identity,
        admission_state=queue_disposition.value,
        numerical_disposition=outcome.disposition.value,
    )
    policy_receipt = promoted_policy_terminal_disposition_receipt(
        result["promotion_queue"]["entries"][queue_ordinal],
        policy_stage,
    )
    result = retain_promoted_policy_terminal(
        result,
        queue_ordinal=queue_ordinal,
        promoted_stage=policy_stage,
        disposition=queue_disposition,
        disposition_receipt=policy_receipt,
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
    root_seal_publish: Callable[
        [object, AuthenticatedRootSeal], None
    ],
    layer1_guard: object,
    locked_routes_by_ordinal: Mapping[int, object],
    promoted_preflights_by_ordinal: Mapping[int, PromotedExecutionPreflight],
    layer1_lock_receipt_sha256: str,
    determinant_error_store: ReviewedDeterminantErrorStore | None = None,
    solved_leaf_store: SolvedLeafStore | None = None,
    record_validator: RecordValidator | None = None,
    timing_log: CampaignTimingLog | None = None,
    clock: Callable[[], float] = time.monotonic,
    session_id_factory: Callable[[], str] | None = None,
    checkpoint_committed: Callable[
        [Mapping[str, object]], Mapping[str, object]
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
    historical_handover = getattr(plan, "campaign_id", None) != selection.campaign_id
    if historical_handover:
        validate_checkpoint_bound_promoted_recovery_selection(
            plan, selection, result
        )
    if layer1_guard is None or locked_routes_by_ordinal is None:
        raise ValueError(
            "promoted survey requires the Layer-1 guard and typed routes"
        )
    if promoted_preflights_by_ordinal is None or layer1_lock_receipt_sha256 is None:
        raise ValueError(
            "promoted survey preflights require the Layer-1 lock receipt"
        )
    if not isinstance(layer1_lock_receipt_sha256, str) or (
        len(layer1_lock_receipt_sha256) != 64
    ):
        raise ValueError("promoted survey Layer-1 lock receipt digest is invalid")
    for method_name in ("pre_write", "post_write", "post_callback"):
        if not callable(getattr(layer1_guard, method_name, None)):
            raise ValueError("promoted survey Layer-1 guard is invalid")
    if not isinstance(locked_routes_by_ordinal, Mapping):
        raise ValueError("promoted survey locked routes are invalid")
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
        layer1_guard.pre_write(candidate)
        _atomic_json(path, candidate)
        durable = _load_durable_schema11_checkpoint(path)
        layer1_guard.post_write(durable)
        if checkpoint_committed is not None:
            durable = validate_schema11_checkpoint(checkpoint_committed(durable))
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
        execution_preflight = promoted_preflights_by_ordinal.get(ordinal)
        if execution_preflight is None:
            raise ValueError("pending promotion has no route preflight")
        if (
            not isinstance(execution_preflight, PromotedExecutionPreflight)
            or execution_preflight.route != expected_route
        ):
            raise ValueError("promoted route preflight binding is invalid")
        execution_preflight = _validate_promoted_scheduler_preflight(
            execution_preflight
        )
        execution_mode = execution_preflight.mode
        continuation_stage: Mapping[str, object] | None = None
        raw_calculation_stage: Mapping[str, object] | None = None
        control_return_stage: Mapping[str, object] | None = None
        control_decision_stage: Mapping[str, object] | None = None
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
            if (
                candidate.get("admission_state") == "NUMERICAL_CONTINUATION"
                and candidate.get("schema")
                == PROMOTED_CONTROL_CONTINUATION_STAGE_SCHEMA
            ):
                continuation_stage = candidate
            elif (
                candidate.get("admission_state") == "CALCULATED_PENDING_DERIVATION"
                and candidate.get("schema") == PROMOTED_CALCULATION_STAGE_SCHEMA
            ):
                raw_calculation_stage = candidate
            elif (
                candidate.get("admission_state")
                == PromotionQueueDisposition.CONTROL_RETURN_RETAINED.value
                and candidate.get("schema") == PROMOTED_CONTROL_RETURN_STAGE_SCHEMA
            ):
                control_return_stage = candidate
            elif (
                candidate.get("admission_state")
                == PromotionQueueDisposition.CONTROL_DECISION_RETAINED.value
                and candidate.get("schema") == PROMOTED_CONTROL_DECISION_STAGE_SCHEMA
            ):
                control_decision_stage = candidate
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

        def append_promoted_structural_event(
            event_kind: str,
            *,
            phase: str,
            tier: str | None = None,
            operation_identity: str | None = None,
            prior_state: str | None = None,
            next_state: str | None = None,
            reason_code: str | None = None,
            background_receipt_sha256: str | None = None,
            cache_receipt_sha256: str | None = None,
            pre_commit: Mapping[str, object] | None = None,
            post_commit: Mapping[str, object] | None = None,
            compact_diagnostics: Mapping[str, object] | None = None,
            durable: bool = False,
        ) -> None:
            """Append a non-scientific trace event around one durable seam."""

            if diagnostic_session is None:
                return
            diagnostics = {
                "route": expected_route,
                "execution_mode": execution_mode.value,
                "phase": phase,
            }
            if compact_diagnostics is not None:
                diagnostics.update(dict(compact_diagnostics))
            def diagnostic_value(*names: str) -> object:
                for name in names:
                    if diagnostics.get(name) is not None:
                        return diagnostics[name]
                return None
            diagnostic_session.append(
                event_kind,
                leaf={
                    "index": leaf_context["leaf_index"],
                    "count": leaf_context["leaf_count"],
                    "leaf_id": leaf_id,
                    "role": leaf.role,
                    "mode": "-".join(str(item) for item in leaf.leaf.mode),
                    "exact_coordinate": leaf.job.sampling_coordinate.to_mapping(),
                    "spin_display": str(leaf.job.spin),
                    "mechanism": leaf.mechanism_id,
                },
                execution={
                    "profile": "SURVEY",
                    "pass": "promoted",
                    "tier": tier,
                    "operation_identity": operation_identity,
                    "operation": diagnostic_value("operation"),
                    "execution_identity_sha256": diagnostic_value(
                        "execution_identity_sha256"
                    ),
                    "request_sha256": diagnostic_value(
                        "request_sha256", "worker_request_sha256"
                    ),
                    "plan": diagnostic_value("plan", "worker_plan"),
                    "scope": diagnostic_value("scope"),
                    "sample_index": diagnostic_value("sample_index"),
                    "sample_role": diagnostic_value("sample_role"),
                    "control_receipt_sha256": diagnostic_value(
                        "control_receipt_sha256"
                    ),
                    "control_return_sha256": diagnostic_value(
                        "control_return_sha256"
                    ),
                    "control_decision_sha256": diagnostic_value(
                        "control_decision_sha256"
                    ),
                    "current_action_kind": diagnostic_value(
                        "current_action_kind"
                    ),
                    "current_tier": diagnostic_value("current_tier"),
                    "next_tier": diagnostic_value("next_tier"),
                },
                transition={
                    "prior_state": (
                        snapshot["disposition"]
                        if prior_state is None
                        else prior_state
                    ),
                    "next_state": next_state,
                    "reason_code": reason_code,
                },
                connections={
                    "scientific_computation_identity": (
                        selection.scientific_identities[leaf_id]
                    ),
                    "root_seal_sha256": snapshot.get("source_root_seal_sha256"),
                    "source_record_sha256": snapshot.get("source_record_sha256"),
                    "source_stage_sha256": snapshot.get("source_stage_sha256"),
                    "provisional_stage_sha256": snapshot.get(
                        "provisional_stage_sha256"
                    ),
                    "cache_receipt_sha256": cache_receipt_sha256,
                    "background_receipt_sha256": background_receipt_sha256,
                    "queue_ordinal": ordinal,
                    "disposition_receipt_sha256": snapshot.get(
                        "disposition_receipt_sha256"
                    ),
                },
                checkpoint={
                    "pre_commit_sha256": (
                        None
                        if pre_commit is None
                        else hashlib.sha256(canonical_json_bytes(pre_commit)).hexdigest()
                    ),
                    "post_commit_sha256": (
                        None
                        if post_commit is None
                        else hashlib.sha256(canonical_json_bytes(post_commit)).hexdigest()
                    ),
                },
                compact_diagnostics=diagnostics,
                durable=durable,
            )

        append_promoted_structural_event(
            "PROMOTED_ROUTE_SELECTED",
            phase="route-selected",
            tier=snapshot.get("minimum_requested_tier"),
            next_state=snapshot["disposition"],
            reason_code=str(snapshot["reason_code"]),
            pre_commit=result,
        )
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

        def checkpoint_raw_outcome(raw: PromotedPassOutcome) -> PromotedPassOutcome:
            """Persist a promoted worker return before a reducer sees it."""

            nonlocal result, committed_before_leaf
            pre_commit = result
            raw_artifact = raw.calculation_artifact
            is_control_return = (
                isinstance(raw_artifact, Mapping)
                and raw_artifact.get("schema") in _PROMOTED_CONTROL_RETURN_SCHEMAS
            )
            commit_arguments = {
                "leaf": leaf,
                "queue_ordinal": ordinal,
                "route": expected_route,
                "outcome": raw,
                "execution_preflight": execution_preflight,
                "layer1_lock_receipt_sha256": layer1_lock_receipt_sha256,
                "scientific_computation_identity": (
                    selection.scientific_identities[leaf_id]
                ),
                "layer1_guard": layer1_guard,
            }
            result = guarded(
                lambda: (
                    _commit_promoted_control_return(result, **commit_arguments)
                    if is_control_return
                    else _commit_promoted_raw_calculation(
                        result, **commit_arguments
                    )
                )
            )
            assert isinstance(result, dict)
            result = persist(result)
            committed_before_leaf = result
            digest = result["promotion_queue"]["entries"][ordinal][
                "retained_promoted_stage_sha256"
            ]
            if not isinstance(digest, str):
                raise ValueError("raw promoted checkpoint digest is invalid")
            raw_artifact_fields: dict[str, object] = {}
            if isinstance(raw_artifact, Mapping):
                receipt = raw_artifact.get("control_receipt")
                identity = (
                    receipt.get("execution_identity")
                    if isinstance(receipt, Mapping)
                    else None
                )
                raw_artifact_fields = {
                    "operation": raw_artifact.get("operation"),
                    "execution_identity_sha256": raw_artifact.get(
                        "execution_identity_sha256"
                    ),
                    "request_sha256": raw_artifact.get("request_sha256"),
                    "plan": (
                        identity.get("plan")
                        if isinstance(identity, Mapping)
                        else None
                    ),
                    "scope": (
                        identity.get("scope")
                        if isinstance(identity, Mapping)
                        else None
                    ),
                    "sample_index": (
                        identity.get("sample_index")
                        if isinstance(identity, Mapping)
                        else None
                    ),
                    "sample_role": (
                        identity.get("sample_role")
                        if isinstance(identity, Mapping)
                        else None
                    ),
                    "control_receipt_sha256": raw_artifact.get(
                        "control_receipt_sha256"
                    ),
                    "control_return_sha256": raw_artifact.get(
                        "control_return_sha256"
                    ),
                    "current_action_kind": raw_artifact.get(
                        "current_action_kind"
                    ),
                    "current_tier": raw_artifact.get("current_tier"),
                }
            append_promoted_structural_event(
                (
                    "PROMOTED_CONTROL_RETURN_CHECKPOINTED"
                    if is_control_return
                    else "PROMOTED_RAW_CALCULATION_CHECKPOINTED"
                ),
                phase="raw-return-checkpoint",
                tier=(None if not raw.precision_tiers else raw.precision_tiers[-1]),
                operation_identity=raw.operation_identity,
                next_state=(
                    PromotionQueueDisposition.CONTROL_RETURN_RETAINED.value
                    if is_control_return
                    else PromotionQueueDisposition.CALCULATED_PENDING_DERIVATION.value
                ),
                reason_code=raw.reason_code,
                pre_commit=pre_commit,
                post_commit=result,
                compact_diagnostics={
                    "retained_promoted_stage_sha256": digest,
                    "calculation_artifact_sha256": (
                        None
                        if not isinstance(raw_artifact, Mapping)
                        else raw_artifact.get("calculation_sha256")
                    ),
                    **raw_artifact_fields,
                },
                durable=True,
            )
            progress_context = {
                key: value
                for key, value in raw_artifact_fields.items()
                if key in {
                    "operation",
                    "execution_identity_sha256",
                    "request_sha256",
                    "plan",
                    "scope",
                    "sample_index",
                    "sample_role",
                    "control_receipt_sha256",
                    "control_return_sha256",
                    "current_action_kind",
                    "current_tier",
                }
                and value is not None
            }
            if progress_context:
                with progress_scope(**progress_context):
                    emit_progress(
                        ProgressEventKind.REQUEST_FAILED,
                        failure_code=raw.reason_code,
                        persistence_state="CONTROL_RETURN_COMMITTED",
                    )
            reduced = guarded(
                lambda: (
                    reduce_promoted_exterior_from_checkpoint(
                        result, queue_ordinal=ordinal
                    )
                    if expected_route == "EXTERIOR_BF40"
                    else reduce_promoted_horizon_from_checkpoint(
                        result, queue_ordinal=ordinal
                    )
                )
            )
            if not isinstance(reduced, PromotedPassOutcome):
                raise ValueError("promoted checkpoint reducer returned invalid data")
            reduced_artifact = reduced.calculation_artifact
            durable_control_decision = (
                isinstance(reduced_artifact, Mapping)
                and reduced_artifact.get("schema")
                in _PROMOTED_CONTROL_DECISION_SCHEMAS
            )
            reduction_prior_state = (
                PromotionQueueDisposition.CALCULATED_PENDING_DERIVATION.value
            )
            if durable_control_decision:
                decision_pre_commit = result
                result = guarded(lambda: _commit_promoted_control_decision(
                    result,
                    leaf=leaf,
                    queue_ordinal=ordinal,
                    route=expected_route,
                    outcome=reduced,
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
                decision_stage_sha256 = result["promotion_queue"]["entries"][
                    ordinal
                ]["retained_promoted_stage_sha256"]
                if not isinstance(decision_stage_sha256, str):
                    raise ValueError("durable CONTROL decision digest is invalid")
                reduced = guarded(
                    lambda: reduce_promoted_control_decision_from_checkpoint(
                        result,
                        queue_ordinal=ordinal,
                        route=expected_route,
                    )
                )
                if not isinstance(reduced, PromotedPassOutcome):
                    raise ValueError("durable CONTROL decision reload is invalid")
                digest = decision_stage_sha256
                reduction_prior_state = (
                    PromotionQueueDisposition.CONTROL_DECISION_RETAINED.value
                )
                append_promoted_structural_event(
                    "PROMOTED_CONTROL_DECISION_CHECKPOINTED",
                    phase="control-decision-checkpoint",
                    tier=(
                        None
                        if not reduced.precision_tiers
                        else reduced.precision_tiers[-1]
                    ),
                    operation_identity=reduced.operation_identity,
                    prior_state=(
                        PromotionQueueDisposition.CONTROL_RETURN_RETAINED.value
                    ),
                    next_state=(
                        PromotionQueueDisposition.CONTROL_DECISION_RETAINED.value
                    ),
                    reason_code=reduced.reason_code,
                    pre_commit=decision_pre_commit,
                    post_commit=result,
                    compact_diagnostics={
                        **_control_trace_fields(reduced),
                        "retained_promoted_stage_sha256": decision_stage_sha256,
                    },
                    durable=True,
                )
            append_promoted_structural_event(
                "PROMOTED_CHECKPOINT_REDUCED",
                phase="checkpoint-only-reduction",
                tier=(
                    None
                    if not reduced.precision_tiers
                    else reduced.precision_tiers[-1]
                ),
                operation_identity=reduced.operation_identity,
                prior_state=reduction_prior_state,
                next_state=(
                    PromotionQueueDisposition.CONTROL_DECISION_RETAINED.value
                    if durable_control_decision
                    else (
                        PromotionQueueDisposition.NUMERICAL_CONTINUATION.value
                        if reduced.precision_tiers[-1:] == ("BF40",)
                        and _outcome_authorizes_bf80(reduced)
                        else (
                            PromotionQueueDisposition.AWAITING_ADMISSION.value
                            if reduced.disposition
                            is SurveyDisposition.CALCULATED_AWAITING_ADMISSION
                            else reduced.disposition.value
                        )
                    )
                ),
                reason_code=reduced.reason_code,
                compact_diagnostics={
                    "source_calculation_stage_sha256": digest,
                    "backend_calls": 0,
                    "julia_launches": 0,
                    "root_reads": 0,
                    **raw_artifact_fields,
                    **(
                        {
                            "operation": reduced.calculation_artifact.get(
                                "fingerprint_material", {}
                            ).get("worker_operation"),
                            "control_receipt_sha256": reduced.calculation_artifact.get(
                                "control_receipt_sha256"
                            ),
                            "control_return_sha256": reduced.calculation_artifact.get(
                                "control_return_sha256"
                            ),
                            "control_decision_sha256": reduced.calculation_artifact.get(
                                "control_decision_sha256"
                            ),
                            "current_action_kind": reduced.calculation_artifact.get(
                                "current_action_kind"
                            ),
                            "current_tier": reduced.calculation_artifact.get(
                                "current_tier"
                            ),
                            "next_tier": reduced.calculation_artifact.get(
                                "next_tier"
                            ),
                        }
                        if isinstance(reduced.calculation_artifact, Mapping)
                        and reduced.calculation_artifact.get("schema")
                        in _PROMOTED_CONTROL_DECISION_SCHEMAS
                        else {}
                    ),
                },
                durable=False,
            )
            decision_trace = _control_trace_fields(reduced)
            if decision_trace:
                with progress_scope(**{
                    key: value
                    for key, value in decision_trace.items()
                    if value is not None
                }):
                    emit_progress(
                        ProgressEventKind.LEAF_PASS_DISPOSITION_RECORDED,
                        failure_code=reduced.reason_code,
                        persistence_state="CONTROL_DECISION_COMMITTED",
                    )
            if (
                durable_control_decision
                and isinstance(reduced.calculation_artifact, Mapping)
                and reduced.calculation_artifact.get("disposition")
                == FailureDisposition.SYSTEM_FAILURE.value
            ):
                guarded(lambda: (_ for _ in ()).throw(
                    JuliaResponseBackendError(
                        "durable CONTROL decision classified a system failure"
                    )
                ))
            return reduced

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
            pre_cache_commit = result
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
            append_promoted_structural_event(
                "PROMOTED_ROUTE_SUPERSEDED_BY_CACHE",
                phase="terminal-cache-supersession",
                operation_identity="solved-leaf-cache/v1",
                next_state=PromotionQueueDisposition.SUPERSEDED_BY_CACHE.value,
                reason_code="EXACT_AUTHENTICATED_CACHE_HIT",
                cache_receipt_sha256=retained.get("record_sha256"),
                pre_commit=pre_cache_commit,
                post_commit=result,
                compact_diagnostics={
                    "record_sha256": retained.get("record_sha256"),
                    "numerical_work_performed": False,
                },
                durable=True,
            )
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

        outcome: PromotedPassOutcome | None = None
        if control_return_stage is not None:
            classified = guarded(
                lambda: (
                    reduce_promoted_exterior_from_checkpoint(
                        result, queue_ordinal=ordinal
                    )
                    if expected_route == "EXTERIOR_BF40"
                    else reduce_promoted_horizon_from_checkpoint(
                        result, queue_ordinal=ordinal
                    )
                    if expected_route == "HORIZON_BF80"
                    else (_ for _ in ()).throw(
                        ValueError("CONTROL return is retained on an unsupported route")
                    )
                )
            )
            if not isinstance(classified, PromotedPassOutcome):
                raise ValueError("resumed CONTROL return classification is invalid")
            decision_pre_commit = result
            result = guarded(lambda: _commit_promoted_control_decision(
                result,
                leaf=leaf,
                queue_ordinal=ordinal,
                route=expected_route,
                outcome=classified,
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
            outcome = guarded(
                lambda: reduce_promoted_control_decision_from_checkpoint(
                    result, queue_ordinal=ordinal, route=expected_route
                )
            )
            if not isinstance(outcome, PromotedPassOutcome):
                raise ValueError("resumed CONTROL decision reload is invalid")
            append_promoted_structural_event(
                "PROMOTED_CONTROL_DECISION_CHECKPOINTED",
                phase="resumed-control-decision-checkpoint",
                tier=(None if not outcome.precision_tiers else outcome.precision_tiers[-1]),
                operation_identity=outcome.operation_identity,
                prior_state=PromotionQueueDisposition.CONTROL_RETURN_RETAINED.value,
                next_state=PromotionQueueDisposition.CONTROL_DECISION_RETAINED.value,
                reason_code=outcome.reason_code,
                pre_commit=decision_pre_commit,
                post_commit=result,
                compact_diagnostics=_control_trace_fields(outcome),
                durable=True,
            )
            control_return_stage = None
        elif control_decision_stage is not None:
            outcome = guarded(
                lambda: reduce_promoted_control_decision_from_checkpoint(
                    result, queue_ordinal=ordinal, route=expected_route
                )
            )
            if not isinstance(outcome, PromotedPassOutcome):
                raise ValueError("resumed CONTROL decision is invalid")

        if (
            outcome is not None
            and isinstance(outcome.calculation_artifact, Mapping)
            and outcome.calculation_artifact.get("schema")
            in _PROMOTED_CONTROL_DECISION_SCHEMAS
        ):
            if (
                outcome.calculation_artifact.get("disposition")
                == FailureDisposition.SYSTEM_FAILURE.value
            ):
                guarded(lambda: (_ for _ in ()).throw(
                    JuliaResponseBackendError(
                        "durable CONTROL decision classified a system failure"
                    )
                ))
            append_promoted_structural_event(
                "PROMOTED_CONTROL_DECISION_RELOADED",
                phase="resumed-control-decision-reload",
                tier=(None if not outcome.precision_tiers else outcome.precision_tiers[-1]),
                operation_identity=outcome.operation_identity,
                prior_state=PromotionQueueDisposition.CONTROL_DECISION_RETAINED.value,
                next_state=PromotionQueueDisposition.CONTROL_DECISION_RETAINED.value,
                reason_code=outcome.reason_code,
                compact_diagnostics={
                    **_control_trace_fields(outcome),
                    "backend_calls": 0,
                    "julia_launches": 0,
                    "root_reads": 0,
                },
                durable=True,
            )
            if (
                expected_route == "EXTERIOR_BF40"
                and outcome.calculation_artifact.get("schema")
                == PROMOTED_CONTROL_DECISION_SCHEMA
                and outcome.precision_tiers[-1:] == ("BF40",)
                and _outcome_authorizes_bf80(outcome)
            ):
                continuation_pre_commit = result
                result = guarded(lambda: _commit_promoted_continuation(
                    result,
                    leaf=leaf,
                    queue_ordinal=ordinal,
                    route=expected_route,
                    outcome=outcome,
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
                stage_bucket = result["promoted_stage_ledger"].get(str(ordinal))
                continuation_stage = (
                    stage_bucket.get(leaf_id)
                    if isinstance(stage_bucket, Mapping)
                    else None
                )
                if not isinstance(continuation_stage, Mapping):
                    raise ValueError("resumed CONTROL continuation is missing")
                append_promoted_structural_event(
                    "PROMOTED_NUMERICAL_CONTINUATION_CHECKPOINTED",
                    phase="resumed-control-continuation-checkpoint",
                    tier="BF40",
                    operation_identity=outcome.operation_identity,
                    prior_state=PromotionQueueDisposition.CONTROL_DECISION_RETAINED.value,
                    next_state=PromotionQueueDisposition.NUMERICAL_CONTINUATION.value,
                    reason_code=outcome.reason_code,
                    pre_commit=continuation_pre_commit,
                    post_commit=result,
                    compact_diagnostics={
                        **_control_trace_fields(outcome),
                        "retained_promoted_stage_sha256": continuation_stage.get(
                            "stage_sha256"
                        ),
                        "next_precision_tier": "BF80",
                        "numerical_work_performed": False,
                    },
                    durable=True,
                )
                outcome = None

        if outcome is None and raw_calculation_stage is not None:
            if expected_route == "EXTERIOR_BF40":
                outcome = guarded(lambda: reduce_promoted_exterior_from_checkpoint(
                    result, queue_ordinal=ordinal
                ))
            elif expected_route == "HORIZON_BF80":
                outcome = guarded(lambda: reduce_promoted_horizon_from_checkpoint(
                    result, queue_ordinal=ordinal
                ))
            else:
                raise ValueError("retained promoted calculation route is invalid")
            assert isinstance(outcome, PromotedPassOutcome)
            append_promoted_structural_event(
                "PROMOTED_CHECKPOINT_REDUCED",
                phase="resumed-checkpoint-only-reduction",
                tier=(
                    None
                    if not outcome.precision_tiers
                    else outcome.precision_tiers[-1]
                ),
                operation_identity=outcome.operation_identity,
                prior_state=(
                    PromotionQueueDisposition.CALCULATED_PENDING_DERIVATION.value
                ),
                next_state=(
                    PromotionQueueDisposition.NUMERICAL_CONTINUATION.value
                    if outcome.precision_tiers[-1:] == ("BF40",)
                    and _outcome_authorizes_bf80(outcome)
                    else (
                        PromotionQueueDisposition.AWAITING_ADMISSION.value
                        if outcome.disposition
                        is SurveyDisposition.CALCULATED_AWAITING_ADMISSION
                        else outcome.disposition.value
                    )
                ),
                reason_code=outcome.reason_code,
                compact_diagnostics={
                    "source_calculation_stage_sha256": (
                        outcome.source_calculation_stage_sha256
                    ),
                    "backend_calls": 0,
                    "julia_launches": 0,
                    "root_reads": 0,
                },
                durable=False,
            )
            if (
                expected_route == "EXTERIOR_BF40"
                and outcome.precision_tiers[-1:] == ("BF40",)
                and outcome.disposition is SurveyDisposition.UNRESOLVED
                and _outcome_authorizes_bf80(outcome)
            ):
                pre_commit = result
                result = guarded(lambda: _commit_promoted_continuation(
                    result,
                    leaf=leaf,
                    queue_ordinal=ordinal,
                    route=expected_route,
                    outcome=outcome,
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
                stage_bucket = result["promoted_stage_ledger"].get(str(ordinal))
                continuation_stage = (
                    stage_bucket.get(leaf_id)
                    if isinstance(stage_bucket, Mapping)
                    else None
                )
                if not isinstance(continuation_stage, Mapping):
                    raise ValueError("resumed BF40 continuation stage is missing")
                append_promoted_structural_event(
                    "PROMOTED_NUMERICAL_CONTINUATION_CHECKPOINTED",
                    phase="bf40-resume-continuation-checkpoint",
                    tier="BF40",
                    operation_identity=outcome.operation_identity,
                    prior_state=(
                        PromotionQueueDisposition.CALCULATED_PENDING_DERIVATION.value
                    ),
                    next_state=PromotionQueueDisposition.NUMERICAL_CONTINUATION.value,
                    reason_code=outcome.reason_code,
                    pre_commit=pre_commit,
                    post_commit=result,
                    compact_diagnostics={
                        **_control_trace_fields(outcome),
                        "retained_promoted_stage_sha256": (
                            continuation_stage.get("stage_sha256")
                        ),
                        "next_precision_tier": "BF80",
                        "numerical_work_performed": False,
                    },
                    durable=True,
                )
                raw_calculation_stage = None
                outcome = None
        if outcome is None and execution_mode is PromotedExecutionMode.BLOCK_ALL:
            outcome = PromotedPassOutcome(
                disposition=SurveyDisposition.DEFERRED,
                reason_code="BLOCKED_BY_ADMISSION_POLICY",
                precision_tiers=(),
                operation_identity="promoted-policy-preflight/v1",
                sample_limit=0,
                root_read_limit=0,
                worker_launch_limit=0,
            )
        elif outcome is None and leaf.mechanism_id == "horizon-admittance":
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
            append_promoted_structural_event(
                "PROMOTED_HORIZON_STARTED",
                phase="composite-runner-started",
                tier="BF80",
                operation_identity="promoted-horizon-component/v2",
                next_state=PromotionQueueDisposition.PENDING.value,
                reason_code="LOCKED_HORIZON_BF80_ROUTE",
            )
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
            horizon_artifact = outcome.calculation_artifact
            horizon_control_return = (
                isinstance(horizon_artifact, Mapping)
                and horizon_artifact.get("schema")
                == PROMOTED_HORIZON_CONTROL_RETURN_SCHEMA
            )
            append_promoted_structural_event(
                "PROMOTED_HORIZON_RETURNED",
                phase="worker-return",
                tier="BF80",
                operation_identity=outcome.operation_identity,
                next_state=(
                    PromotionQueueDisposition.CONTROL_RETURN_RETAINED.value
                    if horizon_control_return
                    else PromotionQueueDisposition.CALCULATED_PENDING_DERIVATION.value
                ),
                reason_code=outcome.reason_code,
                compact_diagnostics={
                    "calculation_artifact_sha256": (
                        None
                        if not isinstance(horizon_artifact, Mapping)
                        else horizon_artifact.get("calculation_sha256")
                    ),
                    "operation": (
                        horizon_artifact.get("operation")
                        if isinstance(horizon_artifact, Mapping)
                        else None
                    ),
                    "request_sha256": (
                        horizon_artifact.get("request_sha256")
                        if isinstance(horizon_artifact, Mapping)
                        else None
                    ),
                    "execution_identity_sha256": (
                        horizon_artifact.get("execution_identity_sha256")
                        if isinstance(horizon_artifact, Mapping)
                        else None
                    ),
                    "control_receipt_sha256": (
                        horizon_artifact.get("control_receipt_sha256")
                        if isinstance(horizon_artifact, Mapping)
                        else None
                    ),
                    "control_return_sha256": (
                        horizon_artifact.get("control_return_sha256")
                        if isinstance(horizon_artifact, Mapping)
                        else None
                    ),
                    "current_action_kind": (
                        horizon_artifact.get("current_action_kind")
                        if isinstance(horizon_artifact, Mapping)
                        else None
                    ),
                    "current_tier": (
                        horizon_artifact.get("current_tier")
                        if isinstance(horizon_artifact, Mapping)
                        else None
                    ),
                    "sample_count": outcome.sample_count,
                    "root_read_count": outcome.root_read_count,
                    "worker_launch_count": outcome.worker_launch_count,
                },
            )
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
            outcome = guarded(lambda: checkpoint_raw_outcome(outcome))
        elif outcome is None:
            # Cache-first: this branch is only reached on a genuine
            # terminal-cache miss for exterior leaves. Only here does the
            # exterior RESPONSE provisional-stage requirement apply.
            if (
                snapshot["queue_kind"] == PromotionQueueKind.RESPONSE.value
                and snapshot.get("source_record_sha256") is None
                and continuation_stage is None
                and not historical_handover
            ):
                provisional_stage = locked_route.provisional_stage
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

                def checkpoint_bf40(
                    partial: PromotedPassOutcome,
                ) -> Mapping[str, object]:
                    nonlocal result, committed_before_leaf
                    pre_commit = result
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
                    retained_stage_sha256 = result["promotion_queue"]["entries"][
                        ordinal
                    ].get("retained_promoted_stage_sha256")
                    append_promoted_structural_event(
                        "PROMOTED_NUMERICAL_CONTINUATION_CHECKPOINTED",
                        phase="bf40-continuation-checkpoint",
                        tier="BF40",
                        operation_identity=retained_partial.operation_identity,
                        next_state=PromotionQueueDisposition.NUMERICAL_CONTINUATION.value,
                        reason_code=retained_partial.reason_code,
                        pre_commit=pre_commit,
                        post_commit=result,
                        compact_diagnostics={
                            **_control_trace_fields(retained_partial),
                            "retained_promoted_stage_sha256": retained_stage_sha256,
                            "next_precision_tier": "BF80",
                        },
                        durable=True,
                    )
                    stage_bucket = result["promoted_stage_ledger"].get(str(ordinal))
                    stage = (
                        stage_bucket.get(leaf_id)
                        if isinstance(stage_bucket, Mapping)
                        else None
                    )
                    if not isinstance(stage, Mapping):
                        raise ValueError("promoted continuation stage is missing")
                    return stage

                def checkpoint_background(
                    receipt: Mapping[str, object],
                ) -> None:
                    """Commit shared samples before their mechanism samples run."""

                    nonlocal result, committed_before_leaf
                    pre_commit = result
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
                    receipt_sha256 = receipt.get("receipt_sha256")
                    if not isinstance(receipt_sha256, str):
                        raise ValueError("promoted background receipt digest is invalid")
                    append_promoted_structural_event(
                        "PROMOTED_BACKGROUND_CHECKPOINTED",
                        phase="background-checkpoint",
                        tier=(
                            None
                            if not isinstance(receipt.get("reuse_key"), Mapping)
                            else receipt["reuse_key"].get("precision_tier")
                        ),
                        operation_identity=(
                            None
                            if not isinstance(receipt.get("reuse_key"), Mapping)
                            else receipt["reuse_key"].get(
                                "background_operation_identity"
                            )
                        ),
                        next_state=PromotionQueueDisposition.PENDING.value,
                        reason_code="PROMOTED_BACKGROUND_RETAINED",
                        background_receipt_sha256=receipt_sha256,
                        pre_commit=pre_commit,
                        post_commit=result,
                        compact_diagnostics={
                            "background_worker_request_sha256": receipt.get(
                                "background_worker_request_sha256"
                            ),
                            "background_reuse_key_sha256": (
                                None
                                if not isinstance(receipt.get("reuse_key"), Mapping)
                                else receipt["reuse_key"].get("reuse_key_sha256")
                            ),
                            "source_queue_ordinal": receipt.get(
                                "source_queue_ordinal"
                            ),
                            "source_leaf_id": receipt.get("source_leaf_id"),
                        },
                        durable=True,
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
                            timing_recorder=recorder,
                            determinant_error_store=determinant_error_store,
                            root_promotion_group=root_promotion_group,
                            provisional_predecessor_receipt=(
                                provisional_predecessor_receipt
                            ),
                            execution_mode=execution_mode,
                            promoted_background_cache=promoted_background_cache,
                            continuation_stage=continuation_stage,
                            tier_checkpoint=checkpoint_bf40,
                            background_checkpoint=(
                                checkpoint_background
                            ),
                            raw_checkpoint=lambda raw: checkpoint_raw_outcome(
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
                            ),
                            trace_event=lambda event_kind, details: (
                                append_promoted_structural_event(
                                    event_kind,
                                    phase="worker-request-or-return",
                                    tier=(
                                        details.get("tier")
                                        if isinstance(details.get("tier"), str)
                                        else None
                                    ),
                                    operation_identity=(
                                        "promoted-fixed-root-survey/v2"
                                    ),
                                    background_receipt_sha256=(
                                        details.get("background_receipt_sha256")
                                        if isinstance(
                                            details.get("background_receipt_sha256"),
                                            str,
                                        )
                                        else None
                                    ),
                                    compact_diagnostics=details,
                                )
                            ),
                        )
                except BaseException:
                    if recorder.active_tier is not None:
                        recorder.interrupt_tier()
                    raise
                if recorder.active_tier is not None:
                    raise ValueError("promoted survey left an active timing tier")
                return replace(
                    timed_outcome,
                    tier_timing=(
                        prior_tier_timing
                        + tuple(timed_outcome.tier_timing)
                    ),
                    session_fragments=(
                        prior_session_fragments
                        + tuple(timed_outcome.session_fragments)
                    ),
                )

            outcome = guarded(execute_exterior)
        assert isinstance(outcome, PromotedPassOutcome)
        pre_stage_commit = result
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
        retained_stage_sha256 = result["promotion_queue"]["entries"][ordinal].get(
            "retained_promoted_stage_sha256"
        )
        retained_stage = None
        stage_bucket = result["promoted_stage_ledger"].get(str(ordinal))
        if isinstance(stage_bucket, Mapping):
            candidate_stage = stage_bucket.get(leaf_id)
            if isinstance(candidate_stage, Mapping):
                retained_stage = candidate_stage
        append_promoted_structural_event(
            "PROMOTED_STAGE_CHECKPOINTED",
            phase="stage-reduction-and-checkpoint",
            tier=(
                None
                if not outcome.precision_tiers
                else outcome.precision_tiers[-1]
            ),
            operation_identity=outcome.operation_identity,
            prior_state=(
                PromotionQueueDisposition.CALCULATED_PENDING_DERIVATION.value
                if raw_calculation_stage is not None
                or outcome.source_calculation_stage_sha256 is not None
                else snapshot["disposition"]
            ),
            next_state=queue_disposition,
            reason_code=outcome.reason_code,
            pre_commit=pre_stage_commit,
            post_commit=result,
            compact_diagnostics={
                "retained_promoted_stage_sha256": retained_stage_sha256,
                "admission_state": (
                    None
                    if retained_stage is None
                    else retained_stage.get("admission_state")
                ),
                "numerical_work_performed": (
                    outcome.sample_count > 0
                    or outcome.root_read_count > 0
                    or outcome.worker_launch_count > 0
                ),
            },
            durable=True,
        )
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
    bf40_background_sources: dict[str, int] = {}
    seen_bf40_background_receipts: set[str] = set()
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
                    reuse_key = receipt.get("reuse_key")
                    if (
                        isinstance(digest, str)
                        and isinstance(source_ordinal, int)
                        and isinstance(reuse_key, Mapping)
                        and reuse_key.get("precision_tier") == "bigfloat-40"
                        and digest not in seen_bf40_background_receipts
                    ):
                        seen_bf40_background_receipts.add(digest)
                        bf40_background_sources[digest] = source_ordinal
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
            chain = stage.get("calculation_chain")
            stage_history = (
                [*chain, stage]
                if isinstance(chain, list)
                and all(isinstance(item, Mapping) for item in chain)
                else [stage]
            )
            bf40_raw_stage = next(
                (
                    item
                    for item in stage_history
                    if item.get("admission_state")
                    == "CALCULATED_PENDING_DERIVATION"
                    and isinstance(item.get("calculation_artifact"), Mapping)
                    and isinstance(
                        item["calculation_artifact"].get(
                            "component_worker_batch"
                        ),
                        Mapping,
                    )
                    and item["calculation_artifact"][
                        "component_worker_batch"
                    ].get("precision_tier")
                    == "bigfloat-40"
                ),
                None,
            )
            artifact = (
                bf40_raw_stage.get("calculation_artifact")
                if isinstance(bf40_raw_stage, Mapping)
                else None
            )
            binding = (
                artifact.get("background")
                if isinstance(artifact, Mapping)
                else None
            )
            digest = (
                binding.get("background_receipt_sha256")
                if isinstance(binding, Mapping)
                else None
            )
            source_ordinal = (
                bf40_background_sources.get(digest)
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
    "reduce_promoted_exterior_from_checkpoint",
    "reduce_promoted_horizon_from_checkpoint",
    "run_binary64_survey",
    "run_promoted_survey",
]
