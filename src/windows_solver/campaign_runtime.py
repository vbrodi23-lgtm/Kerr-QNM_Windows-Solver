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
    PromotionQueueKind,
    SurveyDisposition,
    validate_schema11_checkpoint,
)
from .campaign_recovery import RecoverySelection
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
from .contracts import canonical_json_bytes
from .native_response_kernel import VettedNativeDeterminantKernel
from .response_batches import (
    CampaignLeafRecord,
    CampaignStageRecord,
    NativeCampaignStageBackend,
    PrecisionCapabilities,
    _ode_error_budget_from_mapping,
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
    ComponentStatus,
    ComponentResult,
    NativeDeterminantAdapter,
    PromotedRootSeal,
    root_readout_preserves_authenticated_branch,
    run_promoted_horizon_component,
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
from .root_readout_cache import RootReadoutStore
from .reviewed_determinant_error import ReviewedDeterminantErrorStore
from .background_evidence_store import CanonicalBackgroundEvidenceStore
from .solved_leaf_cache import SolvedLeafLookupStatus, SolvedLeafStore
from .validation_admission import SAME_BACKEND_REFINEMENT_ROUTE


_SCHEMA11_NUMERICAL_RECORD = "windows-solver.schema11-numerical-record/1"
_FIXED_ROOT_STAGE = "windows-solver.fixed-root-screening-stage/1"
_ROOT_READOUT_RECOVERY_INDEX_SCHEMA = (
    "windows-solver.root-readout-recovery-index/v1"
)


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
    budget = _ode_error_budget_from_mapping(policy.get("ode_error_budget"))
    if budget is not None:
        return JuliaPrecisionRootBackend(
            source.job.backend_identity,
            _CachedReadoutValidationAdapter(),
            digits,
            refinement=refinement,
            ode_error_budget=budget,
        )
    receipt = load_default_calibration_receipt()
    family = (
        "horizon-scattering/v1"
        if source.mechanism_id == "horizon-admittance"
        else "exterior-wronskian/v1"
    )
    profile = receipt.budget_for(family, digits)
    if (
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


def _root_solving_identity_compatible(source: object, target: object) -> bool:
    return (
        source.job.root.to_mapping() == target.job.root.to_mapping()
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
    ) -> None:
        self._leaf_by_id = {leaf.leaf_id: leaf for leaf in plan.leaves}
        self._checkpoint: list[_RootSealCandidate] = []
        self._solved: list[_RootSealCandidate] = []
        self._readouts: list[_RootSealCandidate] = []
        self._published: list[_RootSealCandidate] = []
        self.lookup_count = 0
        self.hit_count = 0

        authenticated_checkpoint = validate_schema11_checkpoint(checkpoint)
        for record in authenticated_checkpoint["records"]:
            if not isinstance(record, Mapping):
                continue
            source = self._leaf_by_id.get(record.get("leaf_id"))
            if source is None:
                continue
            validate_campaign_recovery_record(plan, source.leaf_id, record)
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
            if lookup.status is not SolvedLeafLookupStatus.HIT:
                continue
            if lookup.receipt is None or not isinstance(
                lookup.receipt.get("record"), Mapping
            ):
                raise ValueError("solved-leaf cache hit lacks a valid record")
            record = lookup.receipt["record"]
            validate_campaign_recovery_record(plan, leaf_id, record)
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
                item.seal.root_seal_sha256,
            )
            for item in all_candidates
        }
        if len(identities) > 1:
            raise ValueError("SYSTEM_FAILURE ROOT_SEAL_CONFLICT")
        for group in compatible_groups:
            if group:
                self.hit_count += 1
                return group[0].seal
        return None

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
        if resolved != seal:
            self._published.pop()
            raise ValueError("SYSTEM_FAILURE ROOT_SEAL_CONFLICT")


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
    assert result is not None
    code = _typed_horizon_failure_code(result)
    decision = classify_failure(FailureReport(
        failure_code=code,
        failure_class="HORIZON_COMPONENT",
        stage="binary64-horizon",
        worker_operation="binary64-horizon-production/v1",
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
        return Binary64PassOutcome(
            disposition=SurveyDisposition.PROMOTION_PENDING_RESPONSE,
            operation_identity="binary64-horizon-production/v1",
            reason_code=code,
            queue_kind=PromotionQueueKind.RESPONSE,
        )
    dispositions = {
        FailureDisposition.UNRESOLVED: SurveyDisposition.UNRESOLVED,
        FailureDisposition.DEFERRED: SurveyDisposition.DEFERRED,
        FailureDisposition.REJECTED: SurveyDisposition.REJECTED,
    }
    return Binary64PassOutcome(
        disposition=dispositions[decision.disposition],
        operation_identity="binary64-horizon-production/v1",
        reason_code=code,
    )


def _typed_horizon_failure_code(result: ComponentResult) -> str:
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
            "HORIZON_DERIVATIVE_UNRESOLVED"
        ),
    }
    code = reviewed.get(result.status)
    if code is None:
        raise ValueError(
            f"unknown horizon failure status: {result.status.value}"
        )
    return code


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
    backend_holder: dict[str, NativeCampaignStageBackend] = {}
    root_provider_holder: dict[str, AuthenticatedRootSealProvider] = {}

    def root_provider() -> AuthenticatedRootSealProvider:
        if "value" not in root_provider_holder:
            root_provider_holder["value"] = AuthenticatedRootSealProvider(
                plan, selection, checkpoint, store
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

    return run_binary64_survey(
        plan,
        recovery_selection,
        checkpoint,
        checkpoint_path=checkpoint_path,
        root_seal_lookup=lambda leaf: root_provider().lookup(leaf),
        native_backend_factory=lambda: backend().adapter.kernel,
        horizon_runner=lambda leaf: _horizon_outcome(plan, backend(), leaf),
        produced_record_builder=build,
        equivalence_receipt_lookup=equivalence_lookup,
        determinant_error_store=error_store,
        background_evidence_store=background_store,
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
            worker_operation="promoted-horizon-component/v1",
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
            worker_launch_count=1,
        )
    if result.response is None or result.status.value != "CONVERGED":
        code = _typed_horizon_failure_code(result)
        decision = classify_failure(FailureReport(
            failure_code=code,
            failure_class="HORIZON_COMPONENT",
            stage="promoted-horizon",
            worker_operation="promoted-horizon-component/v1",
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
        return PromotedPassOutcome(
            disposition=disposition,
            reason_code=code,
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
    solved_leaf_store: SolvedLeafStore | None = None,
    determinant_error_store: ReviewedDeterminantErrorStore | None = None,
) -> PromotedSurveyRun:
    """Execute only queued BF40/BF80 work through the survey-only operation."""

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
                plan, selection, checkpoint, store
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

    return run_promoted_survey(
        plan,
        recovery_selection,
        checkpoint,
        checkpoint_path=checkpoint_path,
        root_seal_lookup=seal_lookup,
        root_seal_publish=lambda leaf, seal: root_provider().publish(leaf, seal),
        backend_factory=lambda leaf, digits: backend()._julia_precision_backend_for(
            leaf.job, digits
        ),
        primary_root_runner=_promoted_root_result,
        horizon_runner=lambda leaf: _promoted_horizon_outcome(plan, backend(), leaf),
        produced_record_builder=build,
        determinant_error_store=error_store,
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
