"""Production adapters joining schema-11 pass schedulers to package backends."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import math
import os
from pathlib import Path
from typing import Mapping

from .campaign_evidence import (
    EvidencePassOutcome,
    EvidencePassRequest,
    EvidenceStrengtheningPolicy,
    run_evidence_pass,
)
from .campaign_failures import (
    FailureDisposition,
    FailureReport,
    classify_failure,
)
from .campaign_policy import (
    ExecutionProfile,
    PromotionQueueDisposition,
    PromotionQueueKind,
    SurveyDisposition,
    promotion_source_fingerprint_sha256,
    validate_schema11_checkpoint,
)
from .campaign_recovery import RecoverySelection
from .campaign_record_intake import (
    assess_campaign_record_for_current_runtime,
    emit_forensic_record_excluded,
)
from .campaign_reports import (
    refresh_schema11_reports,
    write_schema11_projective,
    write_schema11_triage,
)
from .campaign_survey import (
    AuthenticatedRootSeal,
    Binary64PassOutcome,
    Binary64SurveyRun,
    PromotedPassOutcome,
    PromotedRootSolveResult,
    PromotedSurveyRun,
    run_binary64_survey,
    run_promoted_survey,
)
from .binary64_layer_lock import (
    Layer1Guard,
    binary64_layer_lock_path,
    build_binary64_layer_auxiliary_evidence_manifest,
    build_binary64_layer_lock,
    load_binary64_layer_lock,
    write_binary64_layer_lock,
)
from .contracts import canonical_json_bytes
from .structural_diagnostics import StructuralDiagnosticSession
from .gsn_cache_producer import (
    load_generated_gsn_cache,
    parameter_pairs_for_selection,
)
from .native_response_kernel import VettedNativeDeterminantKernel
from .response_batches import (
    CampaignLeafRecord,
    CampaignStageRecord,
    HORIZON_PROMOTION_TRIGGER_RECEIPT_SCHEMA,
    HORIZON_PROMOTED_COMPARISON_RECEIPT_SCHEMA,
    HORIZON_SCREENING_STAGE_SCHEMA,
    NativeCampaignStageBackend,
    PrecisionCapabilities,
    StageOutcome,
    _ode_error_budget_from_mapping,
    _component_stage_signed_error_channels,
    _sealed_root_for_result,
    _run_promoted_exterior_component_with_progress,
    build_horizon_promotion_trigger_receipt,
    derive_horizon_promotion_decision,
    scientific_computation_identity_sha256,
    synthetic_stage_signed_error_channels,
    validate_schema11_horizon_stage,
    validate_schema11_horizon_record,
    validate_campaign_recovery_record,
)
from .response_engine import (
    Binary64FixedRootBatch,
    Binary64FixedRootScreening,
    Binary64SurveyDisposition,
    BINARY64_HORIZON_OPERATION_V3,
    ComponentStatus,
    ComponentResult,
    EXTERIOR_PROVISIONAL_STAGE_SCHEMA,
    NativeDeterminantAdapter,
    PromotedRootSeal,
    raw_determinant_contract_from_request,
    _validate_current_raw_determinant_policy,
    root_readout_preserves_authenticated_branch,
    run_promoted_horizon_component,
    validate_exterior_provisional_stage,
)
from .julia_response_backend import (
    JuliaPrecisionRootBackend,
    JuliaNumericalControlError,
    JuliaODEResourceLimitError,
    JuliaResponseBackendError,
    JuliaResponseEvaluation,
    JuliaRootReadoutResourceLimitError,
    _validated_execution_resource_policy,
)
from .promoted_control_calibration import load_default_calibration_receipt
from .root_evidence import AuthenticatedRootEvidence, RootDependencyKey
from .root_readout_cache import RootEvidenceStore, RootReadoutStore
from .reviewed_determinant_error import ReviewedDeterminantErrorStore
from .reviewed_determinant_error_issuance import (
    require_locked_bf40_determinant_error_issuance_authority,
)
from .background_evidence_store import CanonicalBackgroundEvidenceStore
from .solved_leaf_cache import SolvedLeafLookupStatus, SolvedLeafStore
from .validation_admission import SAME_BACKEND_REFINEMENT_ROUTE
from .progress import ProgressEventKind, emit_progress, progress_scope


_SCHEMA11_NUMERICAL_RECORD = "windows-solver.schema11-numerical-record/1"
_FIXED_ROOT_STAGE = "windows-solver.fixed-root-screening-stage/1"
_ROOT_READOUT_RECOVERY_INDEX_SCHEMA = (
    "windows-solver.root-readout-recovery-index/v1"
)


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _layer1_leaf_mechanism_ids(
    plan: object, recovery_selection: RecoverySelection
) -> dict[str, str]:
    leaves = {leaf.leaf_id: leaf for leaf in plan.leaves}
    if set(recovery_selection.ordered_leaf_ids) - set(leaves):
        raise ValueError("Layer-1 selection contains a leaf absent from the plan")
    return {
        leaf_id: leaves[leaf_id].mechanism_id
        for leaf_id in recovery_selection.ordered_leaf_ids
    }


def _complex_mapping(value: complex) -> dict[str, float]:
    converted = complex(value)
    return {"real": converted.real, "imaginary": converted.imag}


def build_schema11_horizon_stage(
    outcome: StageOutcome,
    *,
    precision_tier: str,
    operation_identity: str,
) -> tuple[dict[str, object], str]:
    """Build one digest-bound schema-11 horizon screening stage."""

    expected_digits = {"binary64": 64, "BF80": 80}.get(precision_tier)
    if expected_digits != outcome.digits:
        raise ValueError("horizon stage precision tier does not match outcome")
    if not isinstance(operation_identity, str) or not operation_identity:
        raise ValueError("horizon stage operation identity is invalid")
    raw_result = outcome.component_result.get("result")
    if not isinstance(raw_result, Mapping):
        raise ValueError("horizon stage lacks an authenticated component result")
    result = ComponentResult.from_mapping(raw_result)
    if result.to_mapping() != raw_result:
        raise ValueError("horizon stage component result is not canonical")
    response_disk = None
    if result.response is not None:
        radius = float(outcome.local_disk_radius_abs)
        response_disk = {
            "centre": _complex_mapping(result.response),
            "radius": radius,
            "exact_zero_radius": radius == 0.0,
        }
    component_payload = dict(outcome.component_result)
    if outcome.deep_diagnostics is not None:
        component_payload["deep_diagnostics"] = dict(outcome.deep_diagnostics)
    content = {
        "schema": HORIZON_SCREENING_STAGE_SCHEMA,
        "operation_identity": operation_identity,
        "precision_tier": precision_tier,
        "component_result": component_payload,
        "response_disk": response_disk,
        "numerical_state": outcome.numerical_state,
    }
    stage = {**content, "stage_sha256": _sha256(content)}
    return stage, str(stage["stage_sha256"])


def build_schema11_horizon_record(
    plan: object,
    leaf: object,
    *,
    stages: tuple[Mapping[str, object], ...],
    retained_centre: Mapping[str, object] | None,
    state: str,
) -> dict[str, object]:
    """Build and immediately authenticate a new schema-11 horizon record."""

    if state not in {"PRODUCED", "UNRESOLVED", "REJECTED"}:
        raise ValueError("horizon record state is invalid")
    content: dict[str, object] = {
        "schema": _SCHEMA11_NUMERICAL_RECORD,
        "leaf_id": leaf.leaf_id,
        "role": leaf.role,
        "state": state,
        "scientific_computation_identity": scientific_computation_identity_sha256(
            plan, leaf
        ),
        "retained_centre": (
            None if retained_centre is None else dict(retained_centre)
        ),
        "stages": [dict(stage) for stage in stages],
    }
    terminal_stage = stages[-1] if stages else None
    if (
        isinstance(terminal_stage, Mapping)
        and terminal_stage.get("operation_identity")
        == "binary64-horizon-production/v3"
    ):
        payload = terminal_stage.get("component_result")
        raw_result = payload.get("result") if isinstance(payload, Mapping) else None
        evidence = (
            raw_result.get("analytic_horizon_evidence")
            if isinstance(raw_result, Mapping)
            else None
        )
        mathematics = evidence.get("mathematics") if isinstance(evidence, Mapping) else None
        if not isinstance(mathematics, Mapping):
            raise ValueError("v3 horizon record lacks mathematical policy")
        content["horizon_mathematics"] = dict(mathematics)
    record = {**content, "record_sha256": _sha256(content)}
    validate_schema11_horizon_record(plan, leaf, record)
    return record


def _disk_mapping(value: object) -> Mapping[str, object] | None:
    if value is None:
        return None
    mapping = getattr(value, "to_mapping", None)
    if not callable(mapping):
        raise ValueError("screening disk is not serializable")
    result = mapping()
    if not isinstance(result, Mapping):
        raise ValueError("screening disk mapping is invalid")
    return dict(result)


def _refresh_runtime_reports(
    plan: object,
    selection: object,
    checkpoint_path: Path,
    checkpoint: Mapping[str, object],
    *,
    include_triage: bool,
) -> dict[str, object]:
    selected = tuple(selection.leaf_ids)
    binary = checkpoint["survey_pass_ledger"]["binary64"]
    pending = tuple(
        item for item in checkpoint["promotion_queue"]["entries"]
        if item["disposition"] == "PENDING"
    )
    triage_ready = (
        include_triage
        and all(leaf_id in binary for leaf_id in selected)
        and not pending
    )
    return refresh_schema11_reports(
        plan,
        selection,
        checkpoint,
        checkpoint_path,
        advanced_projective=(
            (lambda value, directory: write_schema11_projective(
                plan, selection, value, directory
            ))
            if triage_ready else None
        ),
        advanced_triage=(
            (lambda value, directory: write_schema11_triage(
                plan, selection, value, directory
            ))
            if triage_ready else None
        ),
    )


def _promotion_bound_source_record_sha256(
    checkpoint: Mapping[str, object],
    plan: object | None = None,
) -> set[str]:
    """Return retained records whose mandatory promotion is not successful."""

    entries = checkpoint["promotion_queue"]["entries"]
    return {
        source
        for entry in entries
        if isinstance((source := entry["source_record_sha256"]), str)
        and (
            entry["disposition"]
            != PromotionQueueDisposition.COMPLETED.value
            or not _completed_horizon_source_is_authenticated(
                checkpoint, entry, plan
            )
        )
    }


def _publish_admissible_checkpoint_records(
    plan: object,
    recovery_selection: RecoverySelection,
    checkpoint: Mapping[str, object],
    store: SolvedLeafStore,
    *,
    source_path: Path,
    diagnostic_session: StructuralDiagnosticSession | None,
) -> None:
    """Publish only centrally classified current terminal response records."""

    authenticated = validate_schema11_checkpoint(checkpoint)
    promotion_bound = _promotion_bound_source_record_sha256(authenticated, plan)
    checkpoint_records = {
        str(item["leaf_id"]): item
        for item in authenticated["records"]
        if isinstance(item, Mapping)
    }
    for leaf_id in recovery_selection.ordered_leaf_ids:
        record = checkpoint_records.get(leaf_id)
        if record is None:
            continue
        intake = assess_campaign_record_for_current_runtime(plan, leaf_id, record)
        if not intake.response_admissible:
            if intake.forensic_only:
                emit_forensic_record_excluded(
                    diagnostic_session,
                    intake,
                    leaf_id=leaf_id,
                    source_kind="checkpoint-to-solved-store",
                    source_path=source_path,
                    stale_cache_hit_prevented=False,
                )
            continue
        if (
            record.get("state") != "PRODUCED"
            or record.get("record_sha256") in promotion_bound
        ):
            continue
        lookup = store.publish_if_missing(
            scientific_identity_sha256=(
                recovery_selection.scientific_identities[leaf_id]
            ),
            leaf_id=leaf_id,
            record=intake.record,
            source_type="imported-authenticated-checkpoint",
        )
        if lookup.status is not SolvedLeafLookupStatus.HIT or lookup.receipt is None:
            raise ValueError("checkpoint terminal publication was not exact")
        # An existing, separately authenticated record for the same current
        # identity is left in place. The scheduler owns exact source-conflict
        # classification and turns disagreement into its durable system
        # failure rather than letting checkpoint reconciliation overwrite it.


def _is_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _receipt_digest_is_valid(receipt: Mapping[str, object]) -> bool:
    supplied = receipt.get("receipt_sha256")
    content = {
        key: value for key, value in receipt.items()
        if key != "receipt_sha256"
    }
    return _is_sha256(supplied) and supplied == _sha256(content)


def _completed_horizon_source_is_authenticated(
    checkpoint: Mapping[str, object],
    queue_entry: Mapping[str, object],
    plan: object | None,
) -> bool:
    """Prove a retained source completed its mandatory BF80 comparison."""

    leaf_id = queue_entry.get("leaf_id")
    source_record_sha256 = queue_entry.get("source_record_sha256")
    source_stage_sha256 = queue_entry.get("source_stage_sha256")
    queue_ordinal = queue_entry.get("queue_ordinal")
    promoted_ledger = checkpoint.get("survey_pass_ledger", {}).get(
        "promoted", {}
    )
    promoted = (
        promoted_ledger.get(leaf_id)
        if isinstance(promoted_ledger, Mapping)
        else None
    )
    leaf = next(
        (
            item for item in getattr(plan, "leaves", ())
            if item.leaf_id == leaf_id
        ),
        None,
    )
    if (
        not isinstance(leaf_id, str)
        or leaf is None
        or leaf.mechanism_id != "horizon-admittance"
        or not _is_sha256(source_record_sha256)
        or not _is_sha256(source_stage_sha256)
        or not isinstance(queue_ordinal, int)
        or not isinstance(promoted, Mapping)
        or promoted.get("disposition") != SurveyDisposition.COMPLETED.value
        or promoted.get("operation_identity")
        != "promoted-horizon-comparison/v2"
        or promoted.get("reason_code")
        != "PROMOTED_HORIZON_COMPARISON_AGREES"
        or promoted.get("precision_tiers") != ["BF80"]
        or promoted.get("source_record_sha256") != source_record_sha256
        or promoted.get("result_record_sha256") != source_record_sha256
    ):
        return False
    queue_receipt = {
        "schema": "windows-solver.promoted-queue-disposition/1",
        "leaf_id": leaf_id,
        "queue_ordinal": queue_ordinal,
        "disposition": SurveyDisposition.COMPLETED.value,
        "reason_code": promoted["reason_code"],
        "precision_tiers": list(promoted["precision_tiers"]),
        "result_record_sha256": source_record_sha256,
        "source_record_sha256": source_record_sha256,
    }
    supplied_fingerprint = queue_entry.get("source_fingerprint_sha256")
    if supplied_fingerprint is not None:
        if not _is_sha256(supplied_fingerprint):
            return False
        try:
            expected_fingerprint = promotion_source_fingerprint_sha256(queue_entry)
        except ValueError:
            return False
        if supplied_fingerprint != expected_fingerprint:
            return False
        queue_receipt["source_fingerprint_sha256"] = expected_fingerprint
    if queue_entry.get("disposition_receipt_sha256") != _sha256(
        queue_receipt
    ):
        return False

    records = checkpoint.get("records", ())
    source_record = next(
        (
            item for item in records
            if isinstance(item, Mapping)
            and item.get("record_sha256") == source_record_sha256
        ),
        None,
    )
    stages = source_record.get("stages") if isinstance(source_record, Mapping) else None
    source_stage = stages[0] if isinstance(stages, list) and stages else None
    source_disk = (
        source_stage.get("response_disk")
        if isinstance(source_stage, Mapping)
        else None
    )
    if (
        not isinstance(source_stage, Mapping)
        or source_stage.get("stage_sha256") != source_stage_sha256
        or not isinstance(source_disk, Mapping)
    ):
        return False

    evidence_ledger = checkpoint.get("evidence_ledger", {})
    evidence = (
        evidence_ledger.get(leaf_id)
        if isinstance(evidence_ledger, Mapping)
        else None
    )
    receipts = evidence.get("receipts") if isinstance(evidence, Mapping) else None
    if (
        not isinstance(evidence, Mapping)
        or evidence.get("central_record_sha256") != source_record_sha256
        or evidence.get("central_stage_sha256") != source_stage_sha256
        or not isinstance(receipts, list)
    ):
        return False

    triggers = {
        receipt.get("receipt_sha256")
        for receipt in receipts
        if isinstance(receipt, Mapping)
        and receipt.get("schema") == HORIZON_PROMOTION_TRIGGER_RECEIPT_SCHEMA
        and receipt.get("leaf_id") == leaf_id
        and receipt.get("binary64_stage_sha256") == source_stage_sha256
        and receipt.get("promotion_required") is True
        and _receipt_digest_is_valid(receipt)
    }
    comparison_fields = {
        "schema", "leaf_id", "source_record_sha256", "source_stage_sha256",
        "source_centre", "source_disk_radius",
        "promotion_trigger_receipt_sha256", "bf80_operation_identity",
        "bf80_result_sha256", "bf80_stage", "bf80_centre",
        "bf80_disk_radius",
        "centre_discrepancy", "reviewed_comparison_threshold", "agrees",
        "outcome_code", "runtime_identity", "backend_identity",
        "receipt_sha256",
    }
    for receipt in receipts:
        bf80_stage = (
            receipt.get("bf80_stage")
            if isinstance(receipt, Mapping)
            else None
        )
        if isinstance(bf80_stage, Mapping):
            try:
                validate_schema11_horizon_stage(plan, leaf, bf80_stage)
            except (TypeError, ValueError):
                bf80_stage = None
        bf80_payload = (
            bf80_stage.get("component_result")
            if isinstance(bf80_stage, Mapping)
            else None
        )
        bf80_result = (
            bf80_payload.get("result")
            if isinstance(bf80_payload, Mapping)
            else None
        )
        bf80_disk = (
            bf80_stage.get("response_disk")
            if isinstance(bf80_stage, Mapping)
            else None
        )
        if (
            not isinstance(receipt, Mapping)
            or set(receipt) != comparison_fields
            or receipt.get("schema")
            != HORIZON_PROMOTED_COMPARISON_RECEIPT_SCHEMA
            or receipt.get("leaf_id") != leaf_id
            or receipt.get("source_record_sha256") != source_record_sha256
            or receipt.get("source_stage_sha256") != source_stage_sha256
            or receipt.get("source_centre") != source_disk.get("centre")
            or receipt.get("source_disk_radius") != source_disk.get("radius")
            or receipt.get("promotion_trigger_receipt_sha256") not in triggers
            or receipt.get("agrees") is not True
            or receipt.get("outcome_code") != "AGREES"
            or not isinstance(bf80_result, Mapping)
            or bf80_stage.get("precision_tier") != "BF80"
            or receipt.get("bf80_result_sha256") != _sha256(bf80_result)
            or receipt.get("bf80_operation_identity")
            != bf80_stage.get("operation_identity")
            or not isinstance(bf80_disk, Mapping)
            or receipt.get("bf80_centre") != bf80_disk.get("centre")
            or receipt.get("bf80_disk_radius") != bf80_disk.get("radius")
            or receipt.get("runtime_identity")
            != bf80_payload.get("scientific_runtime")
            or receipt.get("backend_identity")
            != leaf.job.backend_identity.identity_sha256
            or not isinstance(receipt.get("bf80_operation_identity"), str)
            or not receipt.get("bf80_operation_identity")
            or not _receipt_digest_is_valid(receipt)
        ):
            continue
        try:
            source_centre = complex(
                float(source_disk["centre"]["real"]),
                float(source_disk["centre"]["imaginary"]),
            )
            bf80_centre = complex(
                float(receipt["bf80_centre"]["real"]),
                float(receipt["bf80_centre"]["imaginary"]),
            )
            source_radius = float(source_disk["radius"])
            bf80_radius = float(receipt["bf80_disk_radius"])
            discrepancy = float(receipt["centre_discrepancy"])
            threshold = float(receipt["reviewed_comparison_threshold"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        expected_discrepancy = abs(source_centre - bf80_centre)
        expected_threshold = source_radius + bf80_radius
        if (
            all(math.isfinite(value) and value >= 0.0 for value in (
                source_radius, bf80_radius, discrepancy, threshold
            ))
            and discrepancy == expected_discrepancy
            and threshold == expected_threshold
            and discrepancy <= threshold
        ):
            return True
    return False


def build_fixed_root_screening_record(
    plan: object,
    leaf: object,
    batch: object,
    screening: Binary64FixedRootScreening,
    *,
    precision_tier: str,
    root_seal_sha256: str,
) -> tuple[dict[str, object], str]:
    """Seal one survey centre without claiming certificate evidence."""

    if screening.disposition is not Binary64SurveyDisposition.PRODUCED:
        raise ValueError("only a bounded screening result can become a record")
    response_disk = screening.response_disk
    if response_disk is None:
        raise ValueError("bounded screening result lacks a response disk")
    if not isinstance(root_seal_sha256, str) or len(root_seal_sha256) != 64:
        raise ValueError("fixed-root screening record lacks a root seal")
    batch_mapping = getattr(batch, "to_mapping", lambda: None)()
    if not isinstance(batch_mapping, Mapping):
        raise ValueError("fixed-root screening batch is invalid")
    stage_content: dict[str, object] = {
        "schema": _FIXED_ROOT_STAGE,
        "operation_identity": batch_mapping.get("operation_identity"),
        "precision_tier": precision_tier,
        "fixed_root": batch_mapping.get("fixed_root"),
        "root_seal_sha256": root_seal_sha256,
        "branch_identity": batch_mapping.get("branch_identity"),
        "batch": dict(batch_mapping),
        "response_disk": dict(_disk_mapping(response_disk) or {}),
        "frequency_derivative_disk": dict(
            _disk_mapping(screening.frequency_derivative_disk) or {}
        ),
        "coordinate_derivative_disk": dict(
            _disk_mapping(screening.coordinate_derivative_disk) or {}
        ),
        "root_correction_upper_bound": screening.root_correction_upper_bound,
        "determinant_certificate_status": screening.determinant_certificate_status,
    }
    stage = {**stage_content, "stage_sha256": _sha256(stage_content)}
    content: dict[str, object] = {
        "schema": _SCHEMA11_NUMERICAL_RECORD,
        "leaf_id": leaf.leaf_id,
        "role": leaf.role,
        "state": "PRODUCED",
        "scientific_computation_identity": scientific_computation_identity_sha256(
            plan, leaf
        ),
        "retained_centre": _complex_mapping(response_disk.centre),
        "stages": [stage],
    }
    return {**content, "record_sha256": _sha256(content)}, stage["stage_sha256"]


def _binary64_backend(plan: object, selection: object) -> NativeCampaignStageBackend:
    """Construct the Python binary64 kernel without touching Julia runtime code."""

    pairs = parameter_pairs_for_selection(plan, selection)
    generated = load_generated_gsn_cache(pairs)
    kernel = VettedNativeDeterminantKernel.from_generated_resource(
        generated.path, generated.sha256
    )
    adapter = NativeDeterminantAdapter(identity=kernel.identity, kernel=kernel)
    return NativeCampaignStageBackend(
        adapter,
        PrecisionCapabilities((64,)),
        generated,
        julia_adapter=None,
    )


def _old_record_root_seal(
    record: Mapping[str, object],
) -> AuthenticatedRootSeal | None:
    try:
        parsed = CampaignLeafRecord.from_mapping(record)
    except (TypeError, ValueError):
        return None
    if not parsed.stages:
        return None
    raw = parsed.stages[-1].outcome.component_result.get("result")
    if not isinstance(raw, Mapping):
        return None
    try:
        result = ComponentResult.from_mapping(raw)
        seal = _sealed_root_for_result(result)
    except (TypeError, ValueError):
        return None
    if seal is None:
        return None
    return AuthenticatedRootSeal(
        fixed_root=seal.root_readout.omega,
        branch_identity=seal.branch_identity,
        root_seal_sha256=seal.sha256,
    )


def _new_record_root_seal(
    record: Mapping[str, object],
) -> AuthenticatedRootSeal | None:
    if record.get("schema") != _SCHEMA11_NUMERICAL_RECORD:
        return None
    stages = record.get("stages")
    if not isinstance(stages, list) or not stages:
        return None
    stage = stages[-1]
    if not isinstance(stage, Mapping):
        return None
    root = stage.get("fixed_root")
    branch = stage.get("branch_identity")
    root_digest = stage.get("root_seal_sha256")
    if not isinstance(root, Mapping):
        # Schema-11 horizon stages retain the authenticated central root in
        # the component baseline rather than copying legacy fixed-root
        # fields into the numerical stage envelope.
        payload = stage.get("component_result")
        raw = payload.get("result") if isinstance(payload, Mapping) else None
        if not isinstance(raw, Mapping):
            return None
        try:
            result = ComponentResult.from_mapping(raw)
            root = result.baseline.to_mapping().get("omega")
            branch = result.baseline.branch_id
            root_digest = _sha256({
                "schema": "windows-solver.horizon-root-seal/1",
                "root_readout": result.baseline.to_mapping(),
            })
        except (TypeError, ValueError):
            return None
    if not isinstance(root, Mapping):
        return None
    try:
        fixed_root = complex(float(root["real"]), float(root["imaginary"]))
        return AuthenticatedRootSeal(
            fixed_root=fixed_root,
            branch_identity=str(branch),
            root_seal_sha256=str(root_digest),
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


class _CachedReadoutValidationAdapter:
    """Pure provenance holder used to parse an already-completed worker reply."""

    runtime_provenance: Mapping[str, object] = {}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _request_complex(value: object, subject: str) -> complex:
    if not isinstance(value, Mapping) or set(value) != {"real", "imaginary"}:
        raise ValueError(f"cached root-readout {subject} is invalid")
    try:
        result = complex(float(value["real"]), float(value["imaginary"]))
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"cached root-readout {subject} is invalid") from error
    if not math.isfinite(result.real) or not math.isfinite(result.imag):
        raise ValueError(f"cached root-readout {subject} is invalid")
    return result


def _cached_readout_backend(source: object, request: Mapping[str, object]):
    digits = request.get("precision_digits")
    refinement = request.get("refinement_level")
    policy = request.get("policy")
    if (
        type(digits) is not int
        or digits not in {40, 80, 120}
        or type(refinement) is not int
        or refinement not in {0, 1}
        or not isinstance(policy, Mapping)
    ):
        raise ValueError("cached root-readout request precision is invalid")
    diagnostic_model_identity = request.get("diagnostic_model_identity")
    current_contract = None
    if diagnostic_model_identity is not None:
        try:
            current_contract = raw_determinant_contract_from_request(request)
            _validate_current_raw_determinant_policy(request, current_contract)
        except ValueError as error:
            raise ValueError(
                "cached root-readout diagnostic contract is invalid"
            ) from error
    budget = _ode_error_budget_from_mapping(policy.get("ode_error_budget"))
    if budget is not None:
        return JuliaPrecisionRootBackend(
            source.job.backend_identity,
            _CachedReadoutValidationAdapter(),
            digits,
            refinement=refinement,
            ode_error_budget=budget,
            diagnostic_model_identity=diagnostic_model_identity,
        )
    receipt = load_default_calibration_receipt()
    family = (
        "horizon-scattering/v1"
        if source.mechanism_id == "horizon-admittance"
        else "exterior-wronskian/v1"
    )
    profile = receipt.budget_for(family, digits)
    if current_contract is None and (
        policy.get("promoted_control_calibration_receipt_sha256")
        != receipt.sha256
        or policy.get("empirical_control_profile_sha256")
        != _sha256(profile.to_mapping())
    ):
        raise ValueError("cached root-readout control receipt is incompatible")
    return JuliaPrecisionRootBackend(
        source.job.backend_identity,
        _CachedReadoutValidationAdapter(),
        digits,
        refinement=refinement,
        empirical_control_profile=profile,
        calibration_receipt=receipt,
        diagnostic_model_identity=diagnostic_model_identity,
    )


def _validated_cached_readout(
    leaf_by_id: Mapping[str, object], entry: object
) -> tuple[object, PromotedRootSeal]:
    """Authenticate one retained worker readout against its originating leaf."""

    response = getattr(entry, "response", None)
    receipt = getattr(entry, "worker_response_receipt", None)
    request_sha256 = getattr(entry, "request_sha256", None)
    runtime_identity_sha256 = getattr(entry, "runtime_identity_sha256", None)
    if (
        not isinstance(response, Mapping)
        or not isinstance(receipt, Mapping)
        or not _is_sha256(request_sha256)
        or not _is_sha256(runtime_identity_sha256)
        or receipt.get("request_sha256") != request_sha256
        or receipt.get("worker_response_schema_version")
        != response.get("schema_version")
        or not isinstance(receipt.get("request_binding"), Mapping)
    ):
        raise ValueError("cached root-readout receipt binding is invalid")
    request = dict(receipt["request_binding"])
    source = leaf_by_id.get(request.get("leaf_id"))
    if source is None:
        raise ValueError("cached root-readout source leaf is not in the plan")
    if (
        request.get("schema_version") != 1
        or request.get("operation") != "root-readout"
        or request.get("job_id") != source.job.job_id
        or request.get("leaf_id") != source.leaf_id
        or request.get("role") != source.role
        or request.get("mechanism_id") != source.mechanism_id
        or request.get("job_policy_sha256")
        != source.job.policy.identity_sha256
        or request.get("backend_identity_sha256")
        != source.job.backend_identity.identity_sha256
    ):
        raise ValueError("cached root-readout source request is incompatible")
    amplitude = _request_complex(request.get("amplitude"), "amplitude")
    if amplitude != 0.0j:
        raise ValueError("cached root-readout is not a zero-coupling root request")
    predictor = (
        None
        if "primary_predictor" not in request
        else _request_complex(request["primary_predictor"], "primary predictor")
    )
    predictor_kind = request.get("primary_predictor_kind")
    if predictor_kind is not None and not isinstance(predictor_kind, str):
        raise ValueError("cached root-readout predictor kind is invalid")
    backend = _cached_readout_backend(source, request)
    try:
        resource = _validated_execution_resource_policy(
            request.get("execution_resource")
        )
        expected_request = backend.preview_root_request(
            source.job, amplitude, predictor, predictor_kind
        )
    except (JuliaResponseBackendError, ValueError) as error:
        raise ValueError("cached root-readout request is invalid") from error
    expected_request["execution_resource"] = resource
    if request != expected_request:
        raise ValueError("cached root-readout request is not canonical")
    try:
        parsed = backend._read_root_response(
            source.job,
            request,
            JuliaResponseEvaluation(
                response=dict(response),
                request_binding=request,
                request_sha256=request_sha256,
                runtime_identity_sha256=runtime_identity_sha256,
                reused=False,
                cached_worker_response_receipt=None,
            ),
        )
        parsed = replace(parsed, worker_response_receipt=dict(receipt))
        return source, PromotedRootSeal.derive(source.job, parsed)
    except (JuliaResponseBackendError, ValueError) as error:
        raise ValueError("cached root-readout response is invalid") from error


def _root_readout_compatible(source: object, target: object, seal: PromotedRootSeal) -> bool:
    """Allow cross-leaf reuse only for the same root-solving identity."""

    if (
        source.job.root.to_mapping() != target.job.root.to_mapping()
        or source.job.policy.identity_sha256 != target.job.policy.identity_sha256
        or source.job.backend_identity.identity_sha256
        != target.job.backend_identity.identity_sha256
        or source.job.equation_id != target.job.equation_id
        or source.job.sampling_coordinate.to_mapping()
        != target.job.sampling_coordinate.to_mapping()
    ):
        return False
    return root_readout_preserves_authenticated_branch(
        seal.root_readout,
        target.job.root,
        equation_id=target.job.equation_id,
        source_root_mapping=target.job.source_root_mapping,
    )


def _recovery_root_readout_references(
    checkpoint: Mapping[str, object],
) -> dict[Path, dict[str, Mapping[str, object]]]:
    result: dict[Path, dict[str, Mapping[str, object]]] = {}
    receipts = checkpoint.get("recovery_receipts")
    if not isinstance(receipts, list):
        raise ValueError("schema-11 recovery receipts are invalid")
    fields = {
        "path",
        "source_sha256",
        "readout_identity_sha256",
        "request_sha256",
        "runtime_identity_sha256",
        "worker_response_receipt_sha256",
    }
    for receipt in receipts:
        if not isinstance(receipt, Mapping):
            continue
        if receipt.get("schema") != _ROOT_READOUT_RECOVERY_INDEX_SCHEMA:
            continue
        if set(receipt) != {"schema", "store_path", "entries"}:
            raise ValueError("root-readout recovery index fields are invalid")
        store_path = receipt.get("store_path")
        entries = receipt.get("entries")
        if not isinstance(store_path, str) or not store_path or not isinstance(entries, list):
            raise ValueError("root-readout recovery index is invalid")
        by_identity = result.setdefault(Path(store_path), {})
        for entry in entries:
            if (
                not isinstance(entry, Mapping)
                or set(entry) != fields
                or not isinstance(entry.get("path"), str)
                or any(not _is_sha256(entry.get(name)) for name in fields - {"path"})
            ):
                raise ValueError("root-readout recovery index entry is invalid")
            identity = str(entry["readout_identity_sha256"])
            if identity in by_identity and dict(by_identity[identity]) != dict(entry):
                raise ValueError("conflicting root-readout recovery index entry")
            by_identity[identity] = dict(entry)
    return result


def _recovered_root_readout_entries(
    checkpoint: Mapping[str, object],
) -> tuple[object, ...]:
    references = _recovery_root_readout_references(checkpoint)
    if os.environ.get("KERR_QNM_ROOT_READOUT_CACHE", "1").strip() != "0":
        references.setdefault(RootReadoutStore.default().root, {})
    result: list[object] = []
    for root, expected in sorted(references.items(), key=lambda item: str(item[0])):
        try:
            entries = RootReadoutStore(root).entries()
        except ValueError as error:
            raise ValueError(
                f"trusted root-readout store is corrupt: {root}: {error}"
            ) from error
        observed: set[str] = set()
        for entry in entries:
            indexed = expected.get(entry.readout_identity_sha256)
            if expected and indexed is None:
                continue
            if indexed is not None:
                if (
                    Path(str(indexed["path"])) != entry.path
                    or indexed["request_sha256"] != entry.request_sha256
                    or indexed["runtime_identity_sha256"]
                    != entry.runtime_identity_sha256
                    or _file_sha256(entry.path) != indexed["source_sha256"]
                    or not isinstance(entry.worker_response_receipt, Mapping)
                    or entry.worker_response_receipt.get("receipt_sha256")
                    != indexed["worker_response_receipt_sha256"]
                ):
                    raise ValueError("recovered root-readout source no longer matches its index")
                observed.add(entry.readout_identity_sha256)
            result.append(entry)
        missing = set(expected) - observed
        if missing:
            raise ValueError("recovered root-readout source is missing")
    return tuple(result)


@dataclass(frozen=True, slots=True)
class _RootSealCandidate:
    source_leaf: object
    seal: AuthenticatedRootSeal
    source_kind: str
    promoted_root_seal: PromotedRootSeal | None = None
    root_evidence: AuthenticatedRootEvidence | None = None


def _root_solving_identity_compatible(source: object, target: object) -> bool:
    return (
        source.job.root.to_mapping() == target.job.root.to_mapping()
        and source.leaf.mode == target.leaf.mode
        and source.job.spin == target.job.spin
        and source.job.policy.identity_sha256 == target.job.policy.identity_sha256
        and source.job.backend_identity.identity_sha256
        == target.job.backend_identity.identity_sha256
        and source.job.equation_id == target.job.equation_id
        and source.job.sampling_coordinate.to_mapping()
        == target.job.sampling_coordinate.to_mapping()
    )


class AuthenticatedRootSealProvider:
    """Single live production owner for exact authenticated root-seal reuse."""

    def __init__(
        self,
        plan: object,
        selection: object,
        checkpoint: Mapping[str, object],
        solved_leaf_store: SolvedLeafStore,
        root_evidence_store: RootEvidenceStore,
        diagnostic_session: StructuralDiagnosticSession | None = None,
    ) -> None:
        self._leaf_by_id = {leaf.leaf_id: leaf for leaf in plan.leaves}
        self._checkpoint: list[_RootSealCandidate] = []
        self._solved: list[_RootSealCandidate] = []
        self._readouts: list[_RootSealCandidate] = []
        self._published: list[_RootSealCandidate] = []
        self._root_evidence_store = root_evidence_store
        self.lookup_count = 0
        self.hit_count = 0

        authenticated_checkpoint = validate_schema11_checkpoint(checkpoint)
        for record in authenticated_checkpoint["records"]:
            if not isinstance(record, Mapping):
                continue
            leaf_id = record.get("leaf_id")
            if not isinstance(leaf_id, str):
                raise ValueError("checkpoint record leaf identity is invalid")
            intake = assess_campaign_record_for_current_runtime(
                plan, leaf_id, record
            )
            source = self._leaf_by_id[leaf_id]
            if not intake.response_admissible:
                if intake.forensic_only:
                    emit_forensic_record_excluded(
                        diagnostic_session,
                        intake,
                        leaf_id=source.leaf_id,
                        source_kind="checkpoint-forensic-root-seed",
                        source_path=(
                            "in-memory-checkpoint"
                            if diagnostic_session is None
                            else diagnostic_session.checkpoint_path
                        ),
                        stale_cache_hit_prevented=False,
                    )
                    if intake.root_seed is not None:
                        seed = intake.root_seed
                        self._checkpoint.append(
                            _RootSealCandidate(
                                source,
                                AuthenticatedRootSeal(
                                    fixed_root=seed.fixed_root,
                                    branch_identity=seed.branch_identity,
                                    root_seal_sha256=seed.root_seal_sha256,
                                ),
                                "checkpoint-forensic-root-seed",
                                root_evidence=seed,
                            )
                        )
                continue
            seal = _old_record_root_seal(record) or _new_record_root_seal(record)
            if seal is not None:
                self._checkpoint.append(
                    _RootSealCandidate(source, seal, "checkpoint-terminal")
                )

        for leaf_id in selection.leaf_ids:
            source = self._leaf_by_id[leaf_id]
            lookup = solved_leaf_store.lookup_readonly(
                scientific_computation_identity_sha256(plan, source),
                leaf_id,
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
                continue
            if lookup.receipt is None or not isinstance(
                lookup.receipt.get("record"), Mapping
            ):
                raise ValueError("solved-leaf cache result lacks a valid record")
            record = lookup.receipt["record"]
            intake = assess_campaign_record_for_current_runtime(plan, leaf_id, record)
            if not intake.response_admissible:
                if intake.forensic_only:
                    emit_forensic_record_excluded(
                        diagnostic_session,
                        intake,
                        leaf_id=leaf_id,
                        source_kind="solved-leaf-forensic-root-seed",
                        source_path=(
                            "solved-leaf-store"
                            if lookup.path is None
                            else lookup.path
                        ),
                        stale_cache_hit_prevented=False,
                    )
                    if intake.root_seed is not None:
                        seed = intake.root_seed
                        self._solved.append(
                            _RootSealCandidate(
                                source,
                                AuthenticatedRootSeal(
                                    fixed_root=seed.fixed_root,
                                    branch_identity=seed.branch_identity,
                                    root_seal_sha256=seed.root_seal_sha256,
                                ),
                                "solved-leaf-forensic-root-seed",
                                root_evidence=seed,
                            )
                        )
                continue
            if lookup.status is not SolvedLeafLookupStatus.HIT:
                continue
            seal = _old_record_root_seal(record) or _new_record_root_seal(record)
            if seal is not None:
                self._solved.append(
                    _RootSealCandidate(source, seal, "solved-leaf-terminal")
                )

        for entry in _recovered_root_readout_entries(authenticated_checkpoint):
            source, promoted = _validated_cached_readout(self._leaf_by_id, entry)
            self._readouts.append(
                _RootSealCandidate(
                    source,
                    AuthenticatedRootSeal(
                        fixed_root=promoted.root_readout.omega,
                        branch_identity=promoted.root_readout.branch_id,
                        root_seal_sha256=promoted.sha256,
                    ),
                    "root-readout-store",
                    promoted,
                )
            )

    def _compatible(
        self, candidate: _RootSealCandidate, target: object
    ) -> bool:
        if not _root_solving_identity_compatible(candidate.source_leaf, target):
            return False
        if candidate.seal.branch_identity != target.job.root.branch_id:
            return False
        if candidate.source_kind == "root-readout-store":
            promoted = candidate.promoted_root_seal
            if promoted is None or not _root_readout_compatible(
                candidate.source_leaf, target, promoted
            ):
                return False
        return True

    def lookup(self, leaf: object) -> AuthenticatedRootSeal | None:
        """Resolve immediately before work, preserving the mandated order."""

        self.lookup_count += 1
        groups = (
            self._checkpoint,
            self._solved,
            self._readouts,
            self._published,
        )
        compatible_groups = tuple(
            tuple(item for item in group if self._compatible(item, leaf))
            for group in groups
        )
        all_candidates = tuple(
            item for group in compatible_groups for item in group
        )
        identities = {
            (
                item.seal.fixed_root,
                item.seal.branch_identity,
            )
            for item in all_candidates
        }
        if len(identities) > 1:
            raise ValueError("SYSTEM_FAILURE ROOT_SEAL_CONFLICT")
        key = RootDependencyKey.from_leaf(leaf)
        persisted = self._root_evidence_store.lookup(key)
        if persisted is not None:
            persisted.validate_for(leaf)
            durable = AuthenticatedRootSeal(
                fixed_root=persisted.fixed_root,
                branch_identity=persisted.branch_identity,
                root_seal_sha256=persisted.root_seal_sha256,
            )
            if identities and next(iter(identities)) != (
                durable.fixed_root,
                durable.branch_identity,
            ):
                raise ValueError("SYSTEM_FAILURE ROOT_SEAL_CONFLICT")
            self.hit_count += 1
            return durable
        for group in compatible_groups:
            if group:
                candidate = group[0]
                source = candidate.seal
                evidence = candidate.root_evidence
                if evidence is None:
                    evidence = AuthenticatedRootEvidence.from_seal(
                        leaf,
                        fixed_root=source.fixed_root,
                        branch_identity=source.branch_identity,
                        source_receipt_sha256=source.root_seal_sha256,
                    )
                else:
                    evidence.validate_for(leaf)
                self._root_evidence_store.publish(evidence)
                self.hit_count += 1
                return AuthenticatedRootSeal(
                    fixed_root=evidence.fixed_root,
                    branch_identity=evidence.branch_identity,
                    root_seal_sha256=evidence.root_seal_sha256,
                )
        evidence = AuthenticatedRootEvidence.from_bound_leaf(leaf)
        self._root_evidence_store.publish(evidence)
        return AuthenticatedRootSeal(
            fixed_root=evidence.fixed_root,
            branch_identity=evidence.branch_identity,
            root_seal_sha256=evidence.root_seal_sha256,
        )

    def evidence_for(self, leaf: object) -> AuthenticatedRootEvidence:
        """Return the durable root object consumed by the v3 horizon adapter."""

        key = RootDependencyKey.from_leaf(leaf)
        evidence = self._root_evidence_store.lookup(key)
        if evidence is None:
            self.lookup(leaf)
            evidence = self._root_evidence_store.lookup(key)
        if evidence is None:
            raise ValueError("ROOT_SEAL_UNAVAILABLE")
        evidence.validate_for(leaf)
        return evidence

    def publish(self, leaf: object, seal: AuthenticatedRootSeal) -> None:
        """Make a newly authenticated PRIMARY root visible in the same pass."""

        if not isinstance(seal, AuthenticatedRootSeal):
            raise ValueError("published root seal is invalid")
        if seal.branch_identity != leaf.job.root.branch_id:
            raise ValueError("published root seal branch mismatch")
        candidate = _RootSealCandidate(leaf, seal, "same-pass-primary")
        self._published.append(candidate)
        try:
            resolved = self.lookup(leaf)
        except BaseException:
            self._published.pop()
            raise
        if (
            resolved is None
            or resolved.fixed_root != seal.fixed_root
            or resolved.branch_identity != seal.branch_identity
        ):
            self._published.pop()
            raise ValueError("SYSTEM_FAILURE ROOT_SEAL_CONFLICT")


def _horizon_outcome(
    plan: object,
    backend: NativeCampaignStageBackend,
    leaf: object,
    *,
    root_evidence: AuthenticatedRootEvidence,
) -> Binary64PassOutcome:
    # Horizon work has its own fixed-root analytic boundary.  Calling the
    # generic stage runner here would silently reintroduce the finite-
    # amplitude epsilon ladder and its signed-root diagnostics.
    outcome = backend.execute_horizon_stage(leaf, root_evidence=root_evidence)
    raw = outcome.component_result.get("result")
    result = ComponentResult.from_mapping(raw) if isinstance(raw, Mapping) else None
    if result is None:
        raise ValueError("SYSTEM_FAILURE binary64 horizon component result is missing")
    operation_identity = BINARY64_HORIZON_OPERATION_V3
    if result.response is not None and result.status.value == "CONVERGED":
        stage, stage_sha256 = build_schema11_horizon_stage(
            outcome,
            precision_tier="binary64",
            operation_identity=operation_identity,
        )
        decision = derive_horizon_promotion_decision(leaf, outcome)
        response_disk = stage["response_disk"]
        if not isinstance(response_disk, Mapping):
            raise ValueError("SYSTEM_FAILURE bounded horizon lacks a response disk")
        record = build_schema11_horizon_record(
            plan,
            leaf,
            stages=(stage,),
            retained_centre=response_disk["centre"],
            state="PRODUCED",
        )
        receipts = (
            build_horizon_promotion_trigger_receipt(
                plan, leaf, outcome, stage
            ),
        ) if decision.promotion_required else ()
        if decision.promotion_required:
            return Binary64PassOutcome(
                disposition=SurveyDisposition.PROMOTION_PENDING_RESPONSE,
                operation_identity=operation_identity,
                reason_code=decision.reason_code or "HORIZON_PROMOTION_REQUIRED",
                record=record,
                stage_sha256=stage_sha256,
                queue_kind=PromotionQueueKind.RESPONSE,
                minimum_requested_tier="BF80",
                evidence_receipts=receipts,
            )
        return Binary64PassOutcome.produced(
            record=record,
            stage_sha256=stage_sha256,
            operation_identity=operation_identity,
            reason_code="BOUNDED_HORIZON_RESPONSE",
        )
    code = _typed_horizon_failure_code(result, binary64=True)
    decision = classify_failure(FailureReport(
        failure_code=code,
        failure_class="HORIZON_COMPONENT",
        stage="binary64-horizon",
        worker_operation=BINARY64_HORIZON_OPERATION_V3,
        request_schema="windows-solver.response-component-job/1",
        backend_identity=leaf.job.backend_identity.identity_sha256,
        policy_identity=leaf.job.policy.identity_sha256,
        precision_tier="binary64",
        cause_type="ComponentStatus",
        diagnostics={
            "schema": "windows-solver.horizon-component-failure/1",
            "complete": True,
            "component_status": result.status.value,
            "failure_code": code,
        },
    ))
    if decision.disposition is FailureDisposition.SYSTEM_FAILURE:
        raise ValueError(f"unclassified binary64 horizon failure: {code}")
    if decision.disposition is FailureDisposition.PROMOTION_PENDING:
        provisional_stage = None
        provisional_stage_sha256 = None
        provisional_operation_identity = None
        if isinstance(raw, Mapping):
            provisional_stage, provisional_stage_sha256 = build_schema11_horizon_stage(
                outcome,
                precision_tier="binary64",
                operation_identity=operation_identity,
            )
            provisional_operation_identity = operation_identity
        return Binary64PassOutcome(
            disposition=SurveyDisposition.PROMOTION_PENDING_RESPONSE,
            operation_identity=operation_identity,
            reason_code=code,
            queue_kind=PromotionQueueKind.RESPONSE,
            minimum_requested_tier="BF80",
            provisional_stage=provisional_stage,
            provisional_stage_sha256=provisional_stage_sha256,
            provisional_operation_identity=provisional_operation_identity,
        )
    dispositions = {
        FailureDisposition.UNRESOLVED: SurveyDisposition.UNRESOLVED,
        FailureDisposition.DEFERRED: SurveyDisposition.DEFERRED,
        FailureDisposition.REJECTED: SurveyDisposition.REJECTED,
    }
    return Binary64PassOutcome(
        disposition=dispositions[decision.disposition],
        operation_identity=operation_identity,
        reason_code=code,
    )


def _typed_horizon_failure_code(
    result: ComponentResult, *, binary64: bool = False
) -> str:
    for evidence in (
        result.analytic_horizon_evidence,
        result.derivative_evidence,
        result.resolved_window,
    ):
        if isinstance(evidence, Mapping):
            code = evidence.get("failure_code")
            if isinstance(code, str) and code:
                return code
    reviewed = {
        ComponentStatus.NOISE_FLOOR: "FINITE_DIFFERENCE_NOISE_LIMIT",
        ComponentStatus.AXIS_MISMATCH: "HORIZON_AXIS_MISMATCH",
        ComponentStatus.BRANCH_LOSS: "HORIZON_BRANCH_LOSS",
        ComponentStatus.NOT_CONVERGED: "HORIZON_LADDER_EXHAUSTED",
        ComponentStatus.DERIVATIVE_UNRESOLVED: (
            "HORIZON_ARITHMETIC_INADEQUATE"
            if binary64
            else "HORIZON_DERIVATIVE_UNRESOLVED"
        ),
    }
    code = reviewed.get(result.status)
    if code is None:
        raise ValueError(
            f"unknown horizon failure status: {result.status.value}"
        )
    return code



def _provisional_stage_publication_metadata(
    plan: object,
    leaf: object,
    stage: Mapping[str, object],
) -> tuple[str, str, Mapping[str, object]]:
    """Authenticate one durable provisional stage for publication diagnostics.

    Horizon and exterior provisional stages intentionally use different
    envelopes.  The horizon root seal belongs to its authenticated analytic
    evidence; exterior stages retain the seal at the stage top level.
    """

    if not isinstance(stage, Mapping):
        raise ValueError("provisional stage publication is invalid")

    schema = stage.get("schema")
    if schema == HORIZON_SCREENING_STAGE_SCHEMA:
        if (
            getattr(leaf, "mechanism_id", None) != "horizon-admittance"
            or stage.get("precision_tier") != "binary64"
            or stage.get("operation_identity") != BINARY64_HORIZON_OPERATION_V3
        ):
            raise ValueError("horizon provisional stage identity is invalid")

        validate_schema11_horizon_stage(plan, leaf, stage)
        stage_sha256 = stage.get("stage_sha256")
        payload = stage.get("component_result")
        raw_result = payload.get("result") if isinstance(payload, Mapping) else None
        if not isinstance(raw_result, Mapping):
            raise ValueError("horizon provisional stage result is invalid")
        result = ComponentResult.from_mapping(raw_result)
        if result.to_mapping() != raw_result:
            raise ValueError("horizon provisional stage result is not canonical")
        evidence = result.analytic_horizon_evidence
        if not isinstance(evidence, Mapping):
            raise ValueError("horizon provisional stage evidence is invalid")
        root_seal_sha256 = evidence.get("root_seal_sha256")
        if not _is_sha256(stage_sha256) or not _is_sha256(root_seal_sha256):
            raise ValueError("horizon provisional stage seal is invalid")
        return (
            str(stage_sha256),
            str(root_seal_sha256),
            {
                "stage_schema": HORIZON_SCREENING_STAGE_SCHEMA,
                "numerical_state": stage.get("numerical_state"),
                "failure_code": evidence.get("failure_code"),
            },
        )

    if schema != EXTERIOR_PROVISIONAL_STAGE_SCHEMA:
        raise ValueError("provisional stage publication schema is invalid")
    root_seal_sha256 = stage.get("root_seal_sha256")
    if not _is_sha256(root_seal_sha256):
        raise ValueError("exterior provisional stage root seal is invalid")
    authenticated = validate_exterior_provisional_stage(
        stage,
        job=leaf.job,
        scientific_computation_identity=scientific_computation_identity_sha256(
            plan, leaf
        ),
        root_seal_sha256=str(root_seal_sha256),
    )
    stage_sha256 = authenticated.get("stage_sha256")
    if not _is_sha256(stage_sha256):
        raise ValueError("exterior provisional stage digest is invalid")
    return (
        str(stage_sha256),
        str(root_seal_sha256),
        {
            "raw_sample_count": authenticated.get("raw_sample_count"),
            "raw_sample_limit": authenticated.get("raw_sample_limit"),
            "nonadmission_reason_code": authenticated.get(
                "nonadmission_reason_code"
            ),
        },
    )


def run_native_binary64_pass(
    plan: object,
    selection: object,
    recovery_selection: RecoverySelection,
    checkpoint: Mapping[str, object],
    *,
    checkpoint_path: Path,
    solved_leaf_store: SolvedLeafStore | None = None,
    determinant_error_store: ReviewedDeterminantErrorStore | None = None,
    background_evidence_store: CanonicalBackgroundEvidenceStore | None = None,
    diagnostic_session: StructuralDiagnosticSession | None = None,
) -> Binary64SurveyRun:
    """Execute the real binary64 scheduler with a Julia-free backend factory."""

    store = solved_leaf_store or SolvedLeafStore.default()
    error_store = determinant_error_store or ReviewedDeterminantErrorStore(
        checkpoint_path.parent
        / f"{checkpoint_path.name}.reviewed-determinant-errors"
    )
    background_store = background_evidence_store or CanonicalBackgroundEvidenceStore(
        checkpoint_path.parent
        / f"{checkpoint_path.name}.canonical-backgrounds"
    )
    root_evidence_store = RootEvidenceStore.for_checkpoint(checkpoint_path)
    backend_holder: dict[str, NativeCampaignStageBackend] = {}
    root_provider_holder: dict[str, AuthenticatedRootSealProvider] = {}

    def root_provider() -> AuthenticatedRootSealProvider:
        if "value" not in root_provider_holder:
            root_provider_holder["value"] = AuthenticatedRootSealProvider(
                plan,
                selection,
                checkpoint,
                store,
                root_evidence_store,
                diagnostic_session,
            )
        return root_provider_holder["value"]

    def backend() -> NativeCampaignStageBackend:
        if "value" not in backend_holder:
            backend_holder["value"] = _binary64_backend(plan, selection)
        return backend_holder["value"]

    def build(leaf, batch, screening):
        seal = root_provider().lookup(leaf)
        if seal is None:
            raise ValueError("fixed-root record builder lost its root seal")
        return build_fixed_root_screening_record(
            plan,
            leaf,
            batch,
            screening,
            precision_tier="binary64",
            root_seal_sha256=seal.root_seal_sha256,
        )

    def equivalence_lookup(leaf, background):
        return background_store.lookup(
            leaf.job, background.reuse_key
        ).receipt

    def publish_terminal_record(leaf, record):
        """Publish one committed terminal record and expose horizon roots."""

        validate_campaign_recovery_record(plan, leaf.leaf_id, record)
        identity = scientific_computation_identity_sha256(plan, leaf)
        lookup = store.publish_if_missing(
            scientific_identity_sha256=identity,
            leaf_id=leaf.leaf_id,
            record=record,
            source_type="originating-campaign",
        )
        if (
            lookup.status is not SolvedLeafLookupStatus.HIT
            or lookup.receipt is None
            or canonical_json_bytes(lookup.receipt.get("record"))
            != canonical_json_bytes(record)
        ):
            raise ValueError("terminal numerical record was not published exactly")
        with progress_scope(
            leaf_id=leaf.leaf_id,
            execution_profile="SURVEY",
            survey_pass="binary64",
        ):
            emit_progress(
                ProgressEventKind.LEAF_CACHE_PUBLISHED,
                source_type="originating-campaign",
                record_sha256=record["record_sha256"],
            )
        if leaf.mechanism_id == "horizon-admittance":
            seal = _old_record_root_seal(record) or _new_record_root_seal(record)
            if seal is not None:
                root_provider().publish(leaf, seal)

    def publish_provisional_stage(leaf, stage):
        """Publish one authenticated checkpoint-committed provisional stage."""

        stage_sha256, root_seal_sha256, compact_diagnostics = (
            _provisional_stage_publication_metadata(plan, leaf, stage)
        )
        if diagnostic_session is not None:
            diagnostic_session.append(
                "PROVISIONAL_STAGE_PUBLISHED",
                leaf={"leaf_id": leaf.leaf_id},
                execution={
                    "profile": "SURVEY",
                    "pass": "binary64",
                    "tier": "binary64",
                    "operation_identity": str(stage.get("operation_identity")),
                },
                connections={
                    "scientific_computation_identity": (
                        scientific_computation_identity_sha256(plan, leaf)
                    ),
                    "root_seal_sha256": root_seal_sha256,
                    "source_stage_sha256": stage_sha256,
                    "provisional_stage_sha256": stage_sha256,
                },
                compact_diagnostics=compact_diagnostics,
                durable=True,
            )

    # Reconcile authenticated terminal checkpoint records before cache
    # discovery. Mixed-version classification precedes current publication.
    _publish_admissible_checkpoint_records(
        plan,
        recovery_selection,
        checkpoint,
        store,
        source_path=checkpoint_path,
        diagnostic_session=diagnostic_session,
    )

    survey_run = run_binary64_survey(
        plan,
        recovery_selection,
        checkpoint,
        checkpoint_path=checkpoint_path,
        root_seal_lookup=lambda leaf: root_provider().lookup(leaf),
        native_backend_factory=lambda: backend().adapter.kernel,
        horizon_runner=lambda leaf: _horizon_outcome(
            plan,
            backend(),
            leaf,
            root_evidence=root_provider().evidence_for(leaf),
        ),
        produced_record_builder=build,
        provisional_stage_committed=publish_provisional_stage,
        equivalence_receipt_lookup=equivalence_lookup,
        determinant_error_store=error_store,
        background_evidence_store=background_store,
        solved_leaf_store=store,
        record_validator=lambda leaf_id, record: validate_campaign_recovery_record(
            plan, leaf_id, record
        ),
        terminal_record_committed=publish_terminal_record,
        checkpoint_committed=lambda value: _refresh_runtime_reports(
            plan,
            selection,
            checkpoint_path,
            value,
            include_triage=True,
        ),
        diagnostic_session=diagnostic_session,
    )
    if survey_run.pass_exhausted:
        final_checkpoint = validate_schema11_checkpoint(survey_run.checkpoint)
        manifest = build_binary64_layer_auxiliary_evidence_manifest(
            plan,
            final_checkpoint,
            root_evidence_store=root_evidence_store,
            background_evidence_store=background_store,
        )
        lock = build_binary64_layer_lock(
            final_checkpoint,
            selection=recovery_selection,
            leaf_mechanism_ids=_layer1_leaf_mechanism_ids(
                plan, recovery_selection
            ),
            auxiliary_evidence_manifest=manifest,
        )
        write_binary64_layer_lock(binary64_layer_lock_path(checkpoint_path), lock)
    return survey_run


def _promoted_root_result(leaf: object, backend: object, digits: int):
    readout = backend.read_root(
        leaf.job,
        0.0j,
        primary_predictor=leaf.job.root.omega,
    )
    seal = PromotedRootSeal.derive(leaf.job, readout)
    return PromotedRootSolveResult(
        seal=AuthenticatedRootSeal(
            fixed_root=readout.omega,
            branch_identity=readout.branch_id,
            root_seal_sha256=seal.sha256,
        ),
        precision_tier=f"BF{digits}",
        root_read_count=1,
        worker_launch_count=1,
    )


def _promoted_horizon_outcome(
    plan: object,
    backend: NativeCampaignStageBackend,
    leaf: object,
    *,
    queue_entry: Mapping[str, object] | None = None,
    source_record: Mapping[str, object] | None = None,
    trigger_receipts: tuple[Mapping[str, object], ...] = (),
) -> PromotedPassOutcome:
    operation_identity = "promoted-horizon-component/v2"
    source_record_sha256 = None
    source_stage_sha256 = None
    trigger_receipt = None
    if source_record is not None:
        validate_schema11_horizon_record(plan, leaf, source_record)
        stages = source_record["stages"]
        assert isinstance(stages, list)
        source_stage = stages[0]
        assert isinstance(source_stage, Mapping)
        source_record_sha256 = str(source_record["record_sha256"])
        source_stage_sha256 = str(source_stage["stage_sha256"])
        if queue_entry is None or (
            queue_entry.get("source_record_sha256") != source_record_sha256
            or queue_entry.get("source_stage_sha256") != source_stage_sha256
            or not isinstance(
                queue_entry.get("source_binary64_disposition_receipt_sha256"),
                str,
            )
        ):
            raise ValueError("horizon promotion source provenance is invalid")
        candidates = tuple(
            receipt
            for receipt in trigger_receipts
            if receipt.get("schema") == HORIZON_PROMOTION_TRIGGER_RECEIPT_SCHEMA
        )
        if len(candidates) != 1:
            raise ValueError("horizon promotion trigger receipt is missing")
        trigger_receipt = candidates[0]
        source_payload = source_stage.get("component_result")
        if not isinstance(source_payload, Mapping):
            raise ValueError("horizon source stage component payload is invalid")
        source_disk = source_stage.get("response_disk")
        source_radius = (
            0.0
            if not isinstance(source_disk, Mapping)
            else float(source_disk.get("radius", 0.0))
        )
        source_stage_outcome = StageOutcome(
            digits=64,
            numerical_state=str(source_stage["numerical_state"]),
            component_result=source_payload,
            local_disk_radius_abs=source_radius,
            signed_error_channels=synthetic_stage_signed_error_channels(
                source_payload,
                source_radius,
                precision_ladder_applicable=False,
            ),
            deep_diagnostics=(
                source_payload.get("deep_diagnostics")
                if isinstance(source_payload.get("deep_diagnostics"), Mapping)
                else None
            ),
        )
        expected_trigger_receipt = build_horizon_promotion_trigger_receipt(
            plan,
            leaf,
            source_stage_outcome,
            source_stage,
        )
        if dict(trigger_receipt) != expected_trigger_receipt:
            raise ValueError("horizon promotion trigger receipt is not recomputable")
        trigger_content = {
            key: value
            for key, value in trigger_receipt.items()
            if key != "receipt_sha256"
        }
        if (
            trigger_receipt.get("receipt_sha256")
            != _sha256(trigger_content)
            or trigger_receipt.get("leaf_id") != leaf.leaf_id
            or trigger_receipt.get("scientific_computation_identity")
            != scientific_computation_identity_sha256(plan, leaf)
            or trigger_receipt.get("binary64_stage_sha256") != source_stage_sha256
            or trigger_receipt.get("promotion_required")
            != (
                bool(trigger_receipt.get("trigger_ids"))
                or trigger_receipt.get("sentinel") is True
            )
        ):
            raise ValueError("horizon promotion trigger receipt binding is invalid")
        if trigger_receipt.get("promotion_required") is not True:
            raise ValueError(
                "horizon promotion trigger receipt does not require promoted work"
            )

    precision = backend._julia_precision_backend_for(leaf.job, 80)
    try:
        result = run_promoted_horizon_component(
            leaf.job,
            precision,
            leaf.job.root.omega,
        )
    except KeyboardInterrupt:
        raise
    except (
        JuliaNumericalControlError,
        JuliaODEResourceLimitError,
        JuliaRootReadoutResourceLimitError,
    ) as error:
        if isinstance(error, JuliaNumericalControlError):
            code = error.failure_code
        elif isinstance(error, JuliaODEResourceLimitError):
            code = "ODE_RESOURCE_LIMIT"
        else:
            code = "ROOT_READOUT_RESOURCE_INFEASIBLE"
        decision = classify_failure(FailureReport(
            failure_code=code,
            failure_class="PROMOTED_HORIZON_EXECUTION",
            stage="promoted-horizon",
            worker_operation=operation_identity,
            request_schema="windows-solver.response-component-job/1",
            backend_identity=leaf.job.backend_identity.identity_sha256,
            policy_identity=leaf.job.policy.identity_sha256,
            precision_tier="BF80",
            cause_type=type(error).__name__,
            diagnostics={
                "schema": "windows-solver.promoted-horizon-failure/1",
                "complete": True,
                "failure_code": code,
            },
        ))
        if decision.disposition is FailureDisposition.SYSTEM_FAILURE:
            raise
        disposition = {
            FailureDisposition.PROMOTION_PENDING: SurveyDisposition.UNRESOLVED,
            FailureDisposition.UNRESOLVED: SurveyDisposition.UNRESOLVED,
            FailureDisposition.DEFERRED: SurveyDisposition.DEFERRED,
            FailureDisposition.REJECTED: SurveyDisposition.REJECTED,
        }[decision.disposition]
        return PromotedPassOutcome(
            disposition=disposition,
            reason_code=code,
            precision_tiers=("BF80",),
            operation_identity=operation_identity,
            source_record_sha256=source_record_sha256,
            source_stage_sha256=source_stage_sha256,
            root_read_limit=1,
            worker_launch_count=1,
        )
    component_result = {
        "evidence_kind": "package-owned-julia-promoted-horizon-survey",
        "result": result.to_mapping(),
        "scientific_runtime": precision.scientific_runtime_for(leaf.job),
    }
    stage_outcome = StageOutcome(
        digits=80,
        numerical_state=result.status.value,
        component_result=component_result,
        local_disk_radius_abs=sum(result.error_channels.values()),
        signed_error_channels=_component_stage_signed_error_channels(
            component_result,
            result,
            repeat_applicable=False,
            precision_ladder_applicable=False,
        ),
        self_refinement_enclosed=None,
        discrepancy_from_previous_abs=None,
        discrepancy_enclosed=None,
    )
    stage, stage_sha256 = build_schema11_horizon_stage(
        stage_outcome,
        precision_tier="BF80",
        operation_identity=operation_identity,
    )
    if result.response is None or result.status.value != "CONVERGED":
        code = _typed_horizon_failure_code(result)
        decision = classify_failure(FailureReport(
            failure_code=code,
            failure_class="HORIZON_COMPONENT",
            stage="promoted-horizon",
            worker_operation=operation_identity,
            request_schema="windows-solver.response-component-job/1",
            backend_identity=leaf.job.backend_identity.identity_sha256,
            policy_identity=leaf.job.policy.identity_sha256,
            precision_tier="BF80",
            cause_type="ComponentStatus",
            diagnostics={
                "schema": "windows-solver.promoted-horizon-failure/1",
                "complete": True,
                "component_status": result.status.value,
                "failure_code": code,
            },
        ))
        if decision.disposition is FailureDisposition.SYSTEM_FAILURE:
            raise ValueError(f"unclassified promoted horizon failure: {code}")
        disposition = {
            FailureDisposition.PROMOTION_PENDING: SurveyDisposition.UNRESOLVED,
            FailureDisposition.UNRESOLVED: SurveyDisposition.UNRESOLVED,
            FailureDisposition.DEFERRED: SurveyDisposition.DEFERRED,
            FailureDisposition.REJECTED: SurveyDisposition.REJECTED,
        }[decision.disposition]
        if source_record is None and disposition in {
            SurveyDisposition.UNRESOLVED,
            SurveyDisposition.REJECTED,
        }:
            record = build_schema11_horizon_record(
                plan,
                leaf,
                stages=(stage,),
                retained_centre=None,
                state=disposition.value,
            )
        else:
            record = None
        return PromotedPassOutcome(
            disposition=disposition,
            reason_code=code,
            precision_tiers=("BF80",),
            operation_identity=operation_identity,
            record=record,
            stage_sha256=stage_sha256 if record is not None else None,
            source_record_sha256=source_record_sha256,
            source_stage_sha256=source_stage_sha256,
            root_read_count=1,
            root_read_limit=1,
            worker_launch_count=1,
        )

    if source_record is not None:
        source_stages = source_record["stages"]
        assert isinstance(source_stages, list)
        source_stage = source_stages[0]
        assert isinstance(source_stage, Mapping)
        source_disk = source_stage.get("response_disk")
        bf80_disk = stage.get("response_disk")
        if not isinstance(source_disk, Mapping):
            raise ValueError("horizon source record lacks a response disk")
        source_centre = source_disk["centre"]
        source_radius = float(source_disk["radius"])
        bf80_centre = (
            None if not isinstance(bf80_disk, Mapping) else bf80_disk["centre"]
        )
        bf80_radius = (
            None if not isinstance(bf80_disk, Mapping) else float(bf80_disk["radius"])
        )
        discrepancy = (
            None
            if bf80_centre is None
            else abs(
                complex(
                    float(source_centre["real"]),
                    float(source_centre["imaginary"]),
                )
                - complex(float(bf80_centre["real"]), float(bf80_centre["imaginary"]))
            )
        )
        threshold = (
            None if bf80_radius is None else source_radius + bf80_radius
        )
        agrees = discrepancy is not None and threshold is not None and discrepancy <= threshold
        comparison_content = {
            "schema": HORIZON_PROMOTED_COMPARISON_RECEIPT_SCHEMA,
            "leaf_id": leaf.leaf_id,
            "source_record_sha256": source_record_sha256,
            "source_stage_sha256": source_stage_sha256,
            "source_centre": source_centre,
            "source_disk_radius": source_radius,
            "promotion_trigger_receipt_sha256": (
                trigger_receipt["receipt_sha256"]
                if trigger_receipt is not None else None
            ),
            "bf80_operation_identity": operation_identity,
            "bf80_result_sha256": _sha256(result.to_mapping()),
            "bf80_stage": stage,
            "bf80_centre": bf80_centre,
            "bf80_disk_radius": bf80_radius,
            "centre_discrepancy": discrepancy,
            "reviewed_comparison_threshold": threshold,
            "agrees": agrees,
            "outcome_code": "AGREES" if agrees else "DISAGREES_OR_UNBOUNDED",
            "runtime_identity": precision.scientific_runtime_for(leaf.job),
            "backend_identity": leaf.job.backend_identity.identity_sha256,
        }
        comparison_receipt = {
            **comparison_content,
            "receipt_sha256": _sha256(comparison_content),
        }
        return PromotedPassOutcome(
            disposition=(
                SurveyDisposition.COMPLETED
                if agrees else SurveyDisposition.UNRESOLVED
            ),
            reason_code=(
                "PROMOTED_HORIZON_COMPARISON_AGREES"
                if agrees else "PROMOTED_HORIZON_COMPARISON_DISAGREES"
            ),
            precision_tiers=("BF80",),
            operation_identity="promoted-horizon-comparison/v2",
            source_record_sha256=source_record_sha256,
            source_stage_sha256=source_stage_sha256,
            evidence_receipts=(comparison_receipt,),
            root_read_count=1,
            root_read_limit=1,
            worker_launch_count=1,
        )

    provisional = None if queue_entry is None else queue_entry.get("provisional_stage")
    stages = (stage,)
    if provisional is not None:
        if not isinstance(provisional, Mapping):
            raise ValueError("horizon provisional stage is invalid")
        validate_schema11_horizon_stage(plan, leaf, provisional)
        if queue_entry.get("provisional_stage_sha256") != provisional.get("stage_sha256"):
            raise ValueError("horizon provisional stage digest is invalid")
        stages = (provisional, stage)
    response_disk = stage.get("response_disk")
    retained_centre = (
        None if not isinstance(response_disk, Mapping) else response_disk["centre"]
    )
    record = build_schema11_horizon_record(
        plan,
        leaf,
        stages=stages,
        retained_centre=retained_centre,
        state="PRODUCED" if retained_centre is not None else "UNRESOLVED",
    )
    return PromotedPassOutcome(
        disposition=SurveyDisposition.COMPLETED,
        reason_code="BOUNDED_PROMOTED_HORIZON_RESPONSE",
        precision_tiers=("BF80",),
        operation_identity="promoted-horizon-production/v2",
        record=record,
        stage_sha256=stage_sha256,
        root_read_count=1,
        root_read_limit=1,
        worker_launch_count=1,
    )


def run_native_promoted_pass(
    plan: object,
    selection: object,
    recovery_selection: RecoverySelection,
    checkpoint: Mapping[str, object],
    *,
    checkpoint_path: Path,
    binary64_lock_path: Path,
    calibration_receipt: object | None = None,
    solved_leaf_store: SolvedLeafStore | None = None,
    determinant_error_store: ReviewedDeterminantErrorStore | None = None,
    background_evidence_store: CanonicalBackgroundEvidenceStore | None = None,
    diagnostic_session: StructuralDiagnosticSession | None = None,
) -> PromotedSurveyRun:
    """Execute only locked queued BF40/BF80 work through the survey operation."""

    root_evidence_store = RootEvidenceStore.for_checkpoint(checkpoint_path)
    background_store = background_evidence_store or CanonicalBackgroundEvidenceStore(
        checkpoint_path.parent / f"{checkpoint_path.name}.canonical-backgrounds"
    )
    lock = load_binary64_layer_lock(binary64_lock_path)
    manifest = build_binary64_layer_auxiliary_evidence_manifest(
        plan,
        checkpoint,
        root_evidence_store=root_evidence_store,
        background_evidence_store=background_store,
    )
    layer1_guard = Layer1Guard.from_authenticated_lock(
        lock,
        checkpoint,
        selection=recovery_selection,
        leaf_mechanism_ids=_layer1_leaf_mechanism_ids(plan, recovery_selection),
        auxiliary_evidence_manifest=manifest,
    )
    if any(
        route.route == "EXTERIOR_BF40"
        for route in layer1_guard.locked_routes_by_ordinal.values()
    ):
        require_locked_bf40_determinant_error_issuance_authority()

    store = solved_leaf_store or SolvedLeafStore.default()
    error_store = determinant_error_store or ReviewedDeterminantErrorStore(
        checkpoint_path.parent
        / f"{checkpoint_path.name}.reviewed-determinant-errors"
    )
    backend_holder: dict[str, NativeCampaignStageBackend] = {}
    root_provider_holder: dict[str, AuthenticatedRootSealProvider] = {}

    def root_provider() -> AuthenticatedRootSealProvider:
        if "value" not in root_provider_holder:
            root_provider_holder["value"] = AuthenticatedRootSealProvider(
                plan,
                selection,
                checkpoint,
                store,
                root_evidence_store,
                diagnostic_session,
            )
        return root_provider_holder["value"]

    def backend() -> NativeCampaignStageBackend:
        if "value" not in backend_holder:
            backend_holder["value"] = NativeCampaignStageBackend.from_selection(
                plan,
                selection,
                calibration_receipt=calibration_receipt,
            )
        return backend_holder["value"]

    def seal_lookup(leaf, entry):
        candidate = root_provider().lookup(leaf)
        expected = entry.get("source_root_seal_sha256")
        if (
            candidate is not None
            and expected is not None
            and candidate.root_seal_sha256 != expected
            and entry.get("queue_kind") == PromotionQueueKind.RESPONSE.value
        ):
            raise ValueError("promoted response root seal digest mismatch")
        return candidate

    def build(leaf, batch, screening, digits):
        root_sha = batch.root_seal_sha256
        return build_fixed_root_screening_record(
            plan,
            leaf,
            batch,
            screening,
            precision_tier=f"BF{digits}",
            root_seal_sha256=root_sha,
        )

    def publish_terminal_record(leaf, record):
        validate_campaign_recovery_record(plan, leaf.leaf_id, record)
        identity = scientific_computation_identity_sha256(plan, leaf)
        lookup = store.publish_if_missing(
            scientific_identity_sha256=identity,
            leaf_id=leaf.leaf_id,
            record=record,
            source_type="originating-campaign",
        )
        if (
            lookup.status is not SolvedLeafLookupStatus.HIT
            or lookup.receipt is None
            or canonical_json_bytes(lookup.receipt.get("record"))
            != canonical_json_bytes(record)
        ):
            raise ValueError("promoted terminal record was not published exactly")
        with progress_scope(
            leaf_id=leaf.leaf_id,
            execution_profile="SURVEY",
            survey_pass="promoted",
        ):
            emit_progress(
                ProgressEventKind.LEAF_CACHE_PUBLISHED,
                source_type="originating-campaign",
                record_sha256=record["record_sha256"],
            )
        if leaf.mechanism_id == "horizon-admittance":
            seal = _old_record_root_seal(record) or _new_record_root_seal(record)
            if seal is not None:
                root_provider().publish(leaf, seal)

    _publish_admissible_checkpoint_records(
        plan,
        recovery_selection,
        checkpoint,
        store,
        source_path=checkpoint_path,
        diagnostic_session=diagnostic_session,
    )

    return run_promoted_survey(
        plan,
        recovery_selection,
        checkpoint,
        checkpoint_path=checkpoint_path,
        root_seal_lookup=seal_lookup,
        root_seal_publish=lambda leaf, seal: root_provider().publish(leaf, seal),
        layer1_guard=layer1_guard,
        locked_routes_by_ordinal=layer1_guard.locked_routes_by_ordinal,
        backend_factory=lambda leaf, digits: backend()._julia_precision_backend_for(
            leaf.job, digits
        ),
        primary_root_runner=_promoted_root_result,
        horizon_runner=lambda leaf: _promoted_horizon_outcome(plan, backend(), leaf),
        promoted_horizon_runner=(
            lambda leaf, entry, source, receipts: _promoted_horizon_outcome(
                plan,
                backend(),
                leaf,
                queue_entry=entry,
                source_record=source,
                trigger_receipts=receipts,
            )
        ),
        produced_record_builder=build,
        determinant_error_store=error_store,
        solved_leaf_store=store,
        record_validator=lambda leaf_id, record: validate_campaign_recovery_record(
            plan, leaf_id, record
        ),
        terminal_record_committed=publish_terminal_record,
        checkpoint_committed=lambda value: _refresh_runtime_reports(
            plan,
            selection,
            checkpoint_path,
            value,
            include_triage=True,
        ),
        diagnostic_session=diagnostic_session,
    )


def _central_evidence(
    record: Mapping[str, object],
) -> tuple[complex, float, str]:
    if record.get("schema") == _SCHEMA11_NUMERICAL_RECORD:
        centre = record.get("retained_centre")
        stages = record.get("stages")
        if not isinstance(centre, Mapping) or not isinstance(stages, list) or not stages:
            raise ValueError("schema-11 centre evidence is invalid")
        stage = stages[-1]
        if not isinstance(stage, Mapping):
            raise ValueError("schema-11 centre stage is invalid")
        disk = stage.get("response_disk")
        if not isinstance(disk, Mapping):
            raise ValueError("schema-11 centre response disk is invalid")
        return (
            complex(float(centre["real"]), float(centre["imaginary"])),
            float(disk["radius"]),
            str(stage["stage_sha256"]),
        )
    parsed = CampaignLeafRecord.from_mapping(record)
    if not parsed.stages:
        raise ValueError("campaign centre lacks a stage")
    raw = parsed.stages[-1].outcome.component_result.get("result")
    if not isinstance(raw, Mapping):
        raise ValueError("campaign centre result is missing")
    result = ComponentResult.from_mapping(raw)
    if result.response is None:
        raise ValueError("campaign centre is unresolved")
    return (
        result.response,
        sum(result.error_channels.values()),
        parsed.stages[-1].stage_sha256,
    )


def run_native_evidence_pass(
    plan: object,
    selection: object,
    checkpoint: Mapping[str, object],
    request: EvidencePassRequest,
    policy: EvidenceStrengtheningPolicy,
    *,
    checkpoint_path: Path,
    calibration_receipt: object | None = None,
) -> dict[str, object]:
    """Run explicit heavy evidence while retaining each numerical centre."""

    backend = NativeCampaignStageBackend.from_selection(
        plan,
        selection,
        calibration_receipt=calibration_receipt,
    )
    leaf_by_id = {leaf.leaf_id: leaf for leaf in plan.leaves}
    record_by_id = {record["leaf_id"]: record for record in checkpoint["records"]}

    def execute(leaf_id: str, reviewed_policy: EvidenceStrengtheningPolicy):
        leaf = leaf_by_id[leaf_id]
        record = record_by_id[leaf_id]
        centre, centre_radius, stage_sha = _central_evidence(record)
        refinement = (
            1
            if reviewed_policy.profile is ExecutionProfile.VALIDATE
            else 0
        )
        precision = backend._julia_precision_backend_for(
            leaf.job, 80, refinement=refinement
        )
        if leaf.mechanism_id == "horizon-admittance":
            independent = run_promoted_horizon_component(
                leaf.job,
                precision,
                leaf.job.root.omega,
            )
        else:
            independent = _run_promoted_exterior_component_with_progress(
                leaf.job,
                precision,
                leaf.job.root.omega,
            )
        agrees = independent.response is not None and (
            abs(independent.response - centre)
            <= centre_radius + sum(independent.error_channels.values())
        )
        discrepancy = None if agrees else "INDEPENDENT_CENTRE_DISAGREEMENT"
        receipt_content = {
            "schema": "windows-solver.native-evidence-result/1",
            "profile": reviewed_policy.profile.value,
            "evidence_policy_identity": reviewed_policy.identity_sha256,
            "leaf_id": leaf_id,
            "central_record_sha256": record["record_sha256"],
            "central_stage_sha256": stage_sha,
            "precision_tier": "BF80",
            "refinement": refinement,
            "operation_identity": (
                "production-certification-comparator/v1"
                if reviewed_policy.profile is ExecutionProfile.CERTIFY
                else "independent-validation-comparator/v1"
            ),
            "backend_identity": leaf.job.backend_identity.identity_sha256,
            "runtime_identity": _sha256(
                precision.scientific_runtime_for(leaf.job)
            ),
            "calculation_route_identity": SAME_BACKEND_REFINEMENT_ROUTE,
            "calculation_route_family": (
                "HORIZON"
                if leaf.mechanism_id == "horizon-admittance"
                else "EXTERIOR"
            ),
            "route_output_sha256": _sha256(independent.to_mapping()),
            "human_mathematics_review_receipt": None,
            "centre_agrees": agrees,
            "discrepancy_code": discrepancy,
            "independent_result": independent.to_mapping(),
        }
        receipt = {
            **receipt_content,
            "receipt_sha256": _sha256(receipt_content),
        }
        return EvidencePassOutcome(
            leaf_id=leaf_id,
            profile=reviewed_policy.profile,
            central_record_sha256=record["record_sha256"],
            central_stage_sha256=stage_sha,
            centre_agrees=agrees,
            discrepancy_code=discrepancy,
            receipt=receipt,
        )

    return run_evidence_pass(
        checkpoint,
        request,
        policy,
        checkpoint_path=checkpoint_path,
        execute_leaf=execute,
        checkpoint_committed=lambda value: _refresh_runtime_reports(
            plan,
            selection,
            checkpoint_path,
            value,
            include_triage=False,
        ),
    )


__all__ = [
    "build_fixed_root_screening_record",
    "run_native_binary64_pass",
    "run_native_evidence_pass",
    "run_native_promoted_pass",
]
