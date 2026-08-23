"""Production adapters joining schema-11 pass schedulers to package backends."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Mapping

from .campaign_evidence import (
    EvidencePassOutcome,
    EvidencePassRequest,
    EvidenceStrengtheningPolicy,
    run_evidence_pass,
)
from .campaign_policy import (
    ExecutionProfile,
    PromotionQueueKind,
    SurveyDisposition,
)
from .campaign_recovery import RecoverySelection
from .campaign_reports import refresh_schema11_reports, write_schema11_triage
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
from .contracts import canonical_json_bytes
from .native_response_kernel import VettedNativeDeterminantKernel
from .response_batches import (
    CampaignLeafRecord,
    CampaignStageRecord,
    NativeCampaignStageBackend,
    PrecisionCapabilities,
    _sealed_root_for_result,
    _run_promoted_exterior_component_with_progress,
    ensure_generated_gsn_cache,
    parameter_pairs_for_selection,
    scientific_computation_identity_sha256,
    validate_campaign_recovery_record,
)
from .response_engine import (
    Binary64FixedRootBatch,
    Binary64FixedRootScreening,
    Binary64SurveyDisposition,
    ComponentResult,
    NativeDeterminantAdapter,
    PromotedRootSeal,
    run_promoted_horizon_component,
)
from .solved_leaf_cache import SolvedLeafLookupStatus, SolvedLeafStore


_SCHEMA11_NUMERICAL_RECORD = "windows-solver.schema11-numerical-record/1"
_FIXED_ROOT_STAGE = "windows-solver.fixed-root-screening-stage/1"


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _complex_mapping(value: complex) -> dict[str, float]:
    converted = complex(value)
    return {"real": converted.real, "imaginary": converted.imag}


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
        advanced_triage=(
            (lambda value, directory: write_schema11_triage(
                plan, selection, value, directory
            ))
            if triage_ready else None
        ),
    )


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
    generated = ensure_generated_gsn_cache(pairs)
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
    if not isinstance(root, Mapping):
        return None
    try:
        fixed_root = complex(float(root["real"]), float(root["imaginary"]))
        return AuthenticatedRootSeal(
            fixed_root=fixed_root,
            branch_identity=str(stage["branch_identity"]),
            root_seal_sha256=str(stage["root_seal_sha256"]),
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def _root_index(
    plan: object,
    selection: object,
    checkpoint: Mapping[str, object],
    store: SolvedLeafStore,
) -> dict[object, tuple[AuthenticatedRootSeal, ...]]:
    leaf_by_id = {leaf.leaf_id: leaf for leaf in plan.leaves}
    records = list(checkpoint["records"])
    for leaf_id in selection.leaf_ids:
        lookup = store.lookup_readonly(
            scientific_computation_identity_sha256(plan, leaf_by_id[leaf_id]),
            leaf_id,
        )
        if lookup.status is SolvedLeafLookupStatus.CORRUPT:
            raise ValueError(
                f"trusted solved-leaf cache receipt is corrupt: {lookup.path}: "
                f"{lookup.reason}"
            )
        if lookup.status is SolvedLeafLookupStatus.HIT:
            if lookup.receipt is None or not isinstance(
                lookup.receipt.get("record"), Mapping
            ):
                raise ValueError("solved-leaf cache hit lacks a valid record")
            records.append(lookup.receipt["record"])
    result: dict[object, list[AuthenticatedRootSeal]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            continue
        source = leaf_by_id.get(record.get("leaf_id"))
        if source is None:
            continue
        seal = _old_record_root_seal(record) or _new_record_root_seal(record)
        if seal is None:
            continue
        result.setdefault(source.job.root, []).append(seal)
    return {key: tuple(value) for key, value in result.items()}


def _seal_for_leaf(
    index: Mapping[object, tuple[AuthenticatedRootSeal, ...]], leaf: object
) -> AuthenticatedRootSeal | None:
    candidates = tuple(
        seal
        for seal in index.get(leaf.job.root, ())
        if seal.branch_identity == leaf.job.root.branch_id
    )
    identities = {
        (seal.fixed_root, seal.branch_identity, seal.root_seal_sha256)
        for seal in candidates
    }
    if len(identities) > 1:
        raise ValueError("conflicting authenticated root seals")
    return None if not candidates else candidates[0]


def _horizon_outcome(
    plan: object,
    backend: NativeCampaignStageBackend,
    leaf: object,
) -> Binary64PassOutcome:
    outcome = backend.execute_stage(leaf, 64)
    raw = outcome.component_result.get("result")
    result = ComponentResult.from_mapping(raw) if isinstance(raw, Mapping) else None
    if result is not None and result.response is not None and result.status.value == "CONVERGED":
        stage = CampaignStageRecord(
            outcome,
            {
                "precision_factory_identity": plan.precision_factory_identity.to_mapping(),
                "available_precision_digits": [64],
            },
        )
        record = CampaignLeafRecord(
            leaf_id=leaf.leaf_id,
            role=leaf.role,
            state="PRODUCED",
            stages=(stage,),
            trigger_ids=leaf.trigger_ids,
            sentinel=leaf.sentinel,
        )
        return Binary64PassOutcome.produced(
            record=record.to_mapping(),
            stage_sha256=stage.stage_sha256,
            operation_identity="binary64-horizon-production/v1",
            reason_code="BOUNDED_HORIZON_RESPONSE",
        )
    return Binary64PassOutcome(
        disposition=SurveyDisposition.PROMOTION_PENDING_RESPONSE,
        operation_identity="binary64-horizon-production/v1",
        reason_code="DETERMINANT_UNCERTAINTY_TOO_LARGE",
        queue_kind=PromotionQueueKind.RESPONSE,
    )


def run_native_binary64_pass(
    plan: object,
    selection: object,
    recovery_selection: RecoverySelection,
    checkpoint: Mapping[str, object],
    *,
    checkpoint_path: Path,
    solved_leaf_store: SolvedLeafStore | None = None,
) -> Binary64SurveyRun:
    """Execute the real binary64 scheduler with a Julia-free backend factory."""

    store = solved_leaf_store or SolvedLeafStore.default()
    roots = _root_index(plan, selection, checkpoint, store)
    backend_holder: dict[str, NativeCampaignStageBackend] = {}

    def backend() -> NativeCampaignStageBackend:
        if "value" not in backend_holder:
            backend_holder["value"] = _binary64_backend(plan, selection)
        return backend_holder["value"]

    def build(leaf, batch, screening):
        seal = _seal_for_leaf(roots, leaf)
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

    return run_binary64_survey(
        plan,
        recovery_selection,
        checkpoint,
        checkpoint_path=checkpoint_path,
        root_seal_lookup=lambda leaf: _seal_for_leaf(roots, leaf),
        native_backend_factory=lambda: backend().adapter.kernel,
        horizon_runner=lambda leaf: _horizon_outcome(plan, backend(), leaf),
        produced_record_builder=build,
        equivalence_receipt_lookup=None,
        solved_leaf_store=store,
        record_validator=lambda leaf_id, record: validate_campaign_recovery_record(
            plan, leaf_id, record
        ),
        checkpoint_committed=lambda value: _refresh_runtime_reports(
            plan,
            selection,
            checkpoint_path,
            value,
            include_triage=True,
        ),
    )


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
) -> PromotedPassOutcome:
    precision = backend._julia_precision_backend_for(leaf.job, 80)
    result = run_promoted_horizon_component(
        leaf.job,
        precision,
        leaf.job.root.omega,
    )
    if result.response is None or result.status.value != "CONVERGED":
        return PromotedPassOutcome(
            disposition=SurveyDisposition.UNRESOLVED,
            reason_code=result.status.value,
            precision_tiers=("BF80",),
            root_read_count=1,
            worker_launch_count=1,
        )
    component_result = {
        "evidence_kind": "package-owned-julia-promoted-horizon-survey",
        "result": result.to_mapping(),
        "scientific_runtime": precision.scientific_runtime_for(leaf.job),
    }
    from .response_batches import StageOutcome, _component_stage_signed_error_channels

    outcome = StageOutcome(
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
    stage = CampaignStageRecord(
        outcome,
        {
            "precision_factory_identity": plan.precision_factory_identity.to_mapping(),
            "available_precision_digits": list(plan.precision_capabilities.digits),
        },
    )
    record = CampaignLeafRecord(
        leaf_id=leaf.leaf_id,
        role=leaf.role,
        state="PRODUCED",
        stages=(stage,),
        trigger_ids=leaf.trigger_ids,
        sentinel=leaf.sentinel,
    )
    return PromotedPassOutcome(
        disposition=SurveyDisposition.COMPLETED,
        reason_code="BOUNDED_PROMOTED_HORIZON_RESPONSE",
        precision_tiers=("BF80",),
        record=record.to_mapping(),
        stage_sha256=stage.stage_sha256,
        root_read_count=1,
        worker_launch_count=1,
    )


def run_native_promoted_pass(
    plan: object,
    selection: object,
    recovery_selection: RecoverySelection,
    checkpoint: Mapping[str, object],
    *,
    checkpoint_path: Path,
    calibration_receipt: object | None = None,
) -> PromotedSurveyRun:
    """Execute only queued BF40/BF80 work through the survey-only operation."""

    backend = NativeCampaignStageBackend.from_selection(
        plan,
        selection,
        calibration_receipt=calibration_receipt,
    )
    roots = _root_index(plan, selection, checkpoint, SolvedLeafStore.default())

    def seal_lookup(leaf, entry):
        candidates = roots.get(leaf.job.root, ())
        expected = entry.get("source_root_seal_sha256")
        exact = tuple(
            item
            for item in candidates
            if item.branch_identity == leaf.job.root.branch_id
            and (expected is None or item.root_seal_sha256 == expected)
        )
        if len(
            {
                (item.fixed_root, item.branch_identity, item.root_seal_sha256)
                for item in exact
            }
        ) > 1:
            raise ValueError("conflicting promoted root seals")
        return None if not exact else exact[0]

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

    return run_promoted_survey(
        plan,
        recovery_selection,
        checkpoint,
        checkpoint_path=checkpoint_path,
        root_seal_lookup=seal_lookup,
        backend_factory=lambda leaf, digits: backend._julia_precision_backend_for(
            leaf.job, digits
        ),
        primary_root_runner=_promoted_root_result,
        horizon_runner=lambda leaf: _promoted_horizon_outcome(plan, backend, leaf),
        produced_record_builder=build,
        checkpoint_committed=lambda value: _refresh_runtime_reports(
            plan,
            selection,
            checkpoint_path,
            value,
            include_triage=True,
        ),
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
            "leaf_id": leaf_id,
            "central_record_sha256": record["record_sha256"],
            "central_stage_sha256": stage_sha,
            "precision_tier": "BF80",
            "refinement": refinement,
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
