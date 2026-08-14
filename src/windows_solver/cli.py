"""One deterministic command surface for The Windows Solver."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import types
from typing import Mapping, Sequence

from .artifacts import ArtifactStore, ArtifactVerificationError
from .builtin import default_registry
from .contracts import canonical_json_bytes, load_study
from .engine import ExecutionEngine, RunRecord, verify_run_integrity
from .evidence_intake import load_evidence_bundle
from .linear_response_admission import (
    AdmittedLinearResponseProvider,
    LinearResponseAdmissionPackage,
    admit_linear_response_bundle,
    load_linear_response_admission,
    validate_linear_response_bundle,
)
from .planner import build_plan
from .providers import ProviderUnavailableError
from .progress import (
    ProgressEventKind,
    ProgressMode,
    activate_progress,
    emit_progress,
)
from .progress_output import CampaignProgressReporter
from .response_engine import (
    BackendIdentity,
    ComponentResult,
    NumericalPolicy,
    RECORDED_REPLAY_BACKEND_ID,
    RECORDED_SMOKE_CASES,
    RecordedReplayBackend,
    ResponsePlan,
    build_response_plan,
    run_response_plan,
    validate_response_checkpoint,
)
from .response_batches import (
    CampaignLeafRecord,
    CampaignRunSummary,
    NativeCampaignStageBackend,
    PrecisionCapabilities,
    PrecisionFactoryIdentity,
    STAGE_SIGNED_ERROR_FAMILIES,
    build_campaign_plan,
    build_campaign_selection,
    import_campaign_checkpoint_to_solved_leaf_store,
    merge_campaign_checkpoints,
    resolve_campaign_relative_path,
    run_campaign_selection,
    run_predeclared_campaign_smoke,
    validate_campaign_checkpoint,
    worker_failure_payload,
)
from .solved_leaf_cache import SolvedLeafStore
from .response_engine import VettedNativeDeterminantKernel, NativeResourceUnavailableError
from .response_reduction import (
    ComputedUnresolvedComponentEvidence,
    ResolvedComponentEvidence,
    component_evidence_from_mapping,
    reduce_projective_rows,
)


def _validate_reduction_component_checkpoint_binding(
    component: ResolvedComponentEvidence | ComputedUnresolvedComponentEvidence,
    record: CampaignLeafRecord,
    authenticated_receipts: frozenset[str],
) -> None:
    if component.evidence_kind != "authenticated-campaign":
        raise ValueError("campaign reduction CLI accepts authenticated evidence only")
    if record.state not in {"PRODUCED", "UNRESOLVED"} or not record.stages:
        raise ValueError("campaign reduction component checkpoint is not terminal")
    outcome = record.stages[-1].outcome
    raw_result = outcome.component_result.get("result")
    if not isinstance(raw_result, Mapping):
        raise ValueError(
            "campaign reduction component lacks a checkpoint production result"
        )
    result = ComponentResult.from_mapping(raw_result)
    expected_channels: list[dict[str, object]] = []
    for raw_channel in outcome.signed_error_channels:
        channel = dict(raw_channel)
        if channel["scope"] == "local":
            channel_id = f"local:{record.leaf_id}:{channel['family']}"
            shared_group = record.leaf_id
        else:
            channel_id = channel["channel_id"]
            shared_group = channel["shared_group"]
        expected_channels.append({
            "channel_id": channel_id,
            "family": channel["family"],
            "shared_group": shared_group,
            "signed_delta": channel["signed_delta"],
            "units": channel["units"],
            "scope": channel["scope"],
        })
    actual_channels = [item.to_mapping() for item in component.contributions]
    if len(actual_channels) != len(expected_channels):
        raise ValueError(
            "campaign reduction signed channels do not match checkpoint"
        )
    for actual, expected in zip(actual_channels, expected_channels):
        receipt = actual.pop("source_receipt")
        if receipt not in authenticated_receipts or actual != expected:
            raise ValueError(
                "campaign reduction signed channels do not match checkpoint"
            )
    units = {item["units"] for item in expected_channels}
    if len(units) != 1 or component.units != next(iter(units)):
        raise ValueError("campaign reduction component units do not match checkpoint")
    discrepancies = tuple(
        stage.outcome.discrepancy_from_previous_abs
        for stage in record.stages
        if stage.outcome.discrepancy_from_previous_abs is not None
    )
    if isinstance(component, ResolvedComponentEvidence):
        if (
            record.state != "PRODUCED"
            or result.response is None
            or component.centre != result.response
            or component.required_families != STAGE_SIGNED_ERROR_FAMILIES
            or component.recorded_discrepancies != discrepancies
        ):
            raise ValueError(
                "campaign reduction resolved component does not match checkpoint"
            )
    elif (
        record.state != "UNRESOLVED"
        or result.response is not None
        or component.source_receipt not in authenticated_receipts
    ):
        raise ValueError(
            "campaign reduction unresolved component does not match checkpoint"
        )


class CommandParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = CommandParser(prog="solver")
    commands = parser.add_subparsers(dest="command", required=True)

    plan = commands.add_parser("plan", help="show the requested dependency closure")
    plan.add_argument("study", type=Path)
    plan.add_argument("--linear-response-admission", type=Path)
    plan.add_argument("--linear-response-admission-id")

    run = commands.add_parser("run", help="execute one requested dependency closure")
    run.add_argument("study", type=Path)
    run.add_argument("--store", type=Path, default=Path(".solver-store"))
    run.add_argument("--linear-response-admission", type=Path)
    run.add_argument("--linear-response-admission-id")

    verify = commands.add_parser("verify", help="verify one run and its artifacts")
    verify.add_argument("run_id")
    verify.add_argument("--store", type=Path, default=Path(".solver-store"))
    verify.add_argument(
        "--profile", choices=("research", "publication"), default="research"
    )

    inspect = commands.add_parser("inspect", help="inspect one run and its artifacts")
    inspect.add_argument("run_id")
    inspect.add_argument("--store", type=Path, default=Path(".solver-store"))

    export = commands.add_parser("export", help="export a self-contained run package")
    export.add_argument("run_id")
    export.add_argument("--store", type=Path, default=Path(".solver-store"))
    export.add_argument("--output", type=Path, required=True)

    evidence = commands.add_parser(
        "validate-evidence",
        help="validate an operator evidence bundle without admitting it",
    )
    evidence.add_argument(
        "bundle",
        type=Path,
        help="bundle directory or evidence-bundle.json path",
    )

    for name, help_text in (
        ("response-plan", "plan a selected authenticated response replay"),
        ("response-run", "run a selected authenticated response replay cold"),
        ("response-resume", "resume a selected authenticated response replay"),
        ("response-validate", "validate a selected response replay checkpoint"),
    ):
        response = commands.add_parser(name, help=help_text)
        response.add_argument("selection", type=Path)
        response.add_argument("--checkpoint", type=Path, required=True)
    campaign_plan = commands.add_parser(
        "campaign-plan", help="materialize the exact B-prime campaign plan"
    )
    campaign_plan.add_argument("selection", type=Path)
    for name, help_text in (
        ("campaign-run", "execute one selected campaign cold"),
        ("campaign-resume", "resume one compatible selected campaign"),
        ("campaign-validate", "validate one campaign checkpoint"),
    ):
        campaign = commands.add_parser(name, help=help_text)
        campaign.add_argument("selection", type=Path)
        campaign.add_argument("--checkpoint", type=Path, required=True)
        if name in {"campaign-run", "campaign-resume"}:
            campaign.add_argument(
                "--progress",
                choices=tuple(mode.value for mode in ProgressMode),
                default=ProgressMode.NORMAL.value,
            )
        if name == "campaign-validate":
            campaign.add_argument("--full", action="store_true")
    campaign_merge = commands.add_parser(
        "campaign-merge", help="merge compatible campaign checkpoints"
    )
    campaign_merge.add_argument("manifest", type=Path)
    campaign_merge.add_argument("--output", type=Path, required=True)
    campaign_import = commands.add_parser(
        "campaign-cache-import",
        help="import terminal authenticated leaves from a campaign checkpoint",
    )
    campaign_import.add_argument("selection", type=Path)
    campaign_import.add_argument("--checkpoint", type=Path, required=True)
    campaign_import.add_argument("--store", type=Path)
    campaign_reduce = commands.add_parser(
        "campaign-reduce",
        help="reduce authenticated campaign checkpoints without backend work",
    )
    campaign_reduce.add_argument("bundle", type=Path)
    campaign_reduce.add_argument("--output", type=Path, required=True)
    commands.add_parser(
        "campaign-smoke", help="run exactly ten predeclared orchestration cases"
    )
    m02_validate = commands.add_parser(
        "m02-validate", help="validate one complete M02 admission input"
    )
    m02_validate.add_argument("manifest", type=Path)
    m02_admit = commands.add_parser(
        "m02-admit", help="seal one complete M02 admission package"
    )
    m02_admit.add_argument("manifest", type=Path)
    m02_admit.add_argument("--output", type=Path, required=True)
    m02_export = commands.add_parser(
        "m02-export", help="revalidate and export an admitted M02 package"
    )
    m02_export.add_argument("admission", type=Path)
    m02_export.add_argument("--admission-id", required=True)
    m02_export.add_argument("--output", type=Path, required=True)
    return parser


def _emit(value: object, *, stream=None) -> None:
    if stream is None:
        stream = sys.stdout
    stream.write(canonical_json_bytes(value).decode("utf-8"))
    stream.write("\n")


def _load_run(store: ArtifactStore, run_id: str) -> RunRecord:
    return RunRecord.from_mapping(
        store.load_run_mapping(run_id), expected_run_id=run_id
    )


def _artifact_mappings(
    store: ArtifactStore, record: RunRecord
) -> dict[str, dict[str, object]]:
    return {
        capability: store.load_artifact(artifact_id).to_mapping()
        for capability, artifact_id in record.artifact_ids.items()
    }


def _atomic_export(path: Path, value: object) -> None:
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


def _runtime_registry(
    admission_path: Path | None,
    expected_admission_id: str | None,
):
    if admission_path is None:
        if expected_admission_id is not None:
            raise ValueError(
                "linear-response admission identity requires a package path"
            )
        return default_registry()
    if expected_admission_id is None:
        raise ValueError(
            "linear-response admission package requires its detached admission ID"
        )
    package = load_linear_response_admission(
        admission_path, expected_admission_id=expected_admission_id
    )
    return default_registry(AdmittedLinearResponseProvider(
        package, expected_admission_id=expected_admission_id
    ))


def _plan(
    study_path: Path,
    admission_path: Path | None = None,
    expected_admission_id: str | None = None,
) -> tuple[int, object]:
    request = load_study(study_path)
    plan = build_plan(request.target)
    registry = _runtime_registry(admission_path, expected_admission_id)
    unavailable: list[str] = []
    providers: list[dict[str, object]] = []
    for capability in plan.capabilities:
        try:
            provider = registry.resolve(capability)
        except ProviderUnavailableError:
            unavailable.append(capability.value)
        else:
            providers.append(provider.descriptor.to_mapping())
    return 0, {
        "command": "plan",
        "plan": plan.to_mapping(),
        "providers": providers,
        "unavailable_capabilities": unavailable,
    }


def _run(
    study_path: Path,
    store_path: Path,
    admission_path: Path | None = None,
    expected_admission_id: str | None = None,
) -> tuple[int, object]:
    request = load_study(study_path)
    record = ExecutionEngine(
        ArtifactStore(store_path),
        _runtime_registry(admission_path, expected_admission_id),
    ).run(request)
    if record.unavailable_capability is not None:
        return 3, record.to_mapping()
    return (0 if record.status == "SUCCEEDED" else 1), record.to_mapping()


def _verify(run_id: str, store_path: Path, profile: str) -> tuple[int, object]:
    store = ArtifactStore(store_path)
    record = _load_run(store, run_id)
    artifacts = verify_run_integrity(store, record, profile=profile)
    return 0, {
        "command": "verify",
        "run_id": run_id,
        "profile": profile,
        "verified": True,
        "artifact_count": len(artifacts),
    }


def _inspect(run_id: str, store_path: Path) -> tuple[int, object]:
    store = ArtifactStore(store_path)
    record = _load_run(store, run_id)
    return 0, {
        "command": "inspect",
        "run": record.to_mapping(),
        "artifacts": _artifact_mappings(store, record),
    }


def _export(run_id: str, store_path: Path, output: Path) -> tuple[int, object]:
    store = ArtifactStore(store_path)
    resolved_output = output.resolve()
    if resolved_output.is_relative_to(store.root):
        raise ArtifactVerificationError(
            "export output must be outside the artifact store"
        )
    record = _load_run(store, run_id)
    verified = verify_run_integrity(store, record, profile="research")
    artifacts = {
        capability: envelope.to_mapping()
        for capability, envelope in verified.items()
    }
    package = {
        "schema_version": 1,
        "run": record.to_mapping(),
        "artifacts": artifacts,
    }
    _atomic_export(resolved_output, package)
    return 0, {
        "command": "export",
        "run_id": run_id,
        "output": str(resolved_output),
        "artifact_count": len(artifacts),
    }


def _validate_evidence(bundle: Path) -> tuple[int, object]:
    summary = load_evidence_bundle(bundle)
    return 0, {"command": "validate-evidence", **summary.to_mapping()}


def _reject_response_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate response selection JSON key: {key}")
        value[key] = item
    return value


def _load_response_selection(path: Path) -> tuple[ResponsePlan, RecordedReplayBackend]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_response_duplicate_keys,
            parse_constant=lambda item: (_ for _ in ()).throw(
                ValueError(f"response selection contains non-finite constant {item}")
            ),
        )
    except json.JSONDecodeError as error:
        raise ValueError("response selection is not valid JSON") from error
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "backend_id",
        "leaf_ids",
    }:
        raise ValueError("response selection fields are invalid")
    if value["schema_version"] != 1:
        raise ValueError("response selection schema version is invalid")
    if value["backend_id"] != RECORDED_REPLAY_BACKEND_ID:
        raise ValueError("response selection backend is unavailable")
    leaf_ids = value["leaf_ids"]
    if not isinstance(leaf_ids, list) or any(
        not isinstance(item, str) for item in leaf_ids
    ):
        raise ValueError("response selection leaf_ids must be a string array")
    replay_leaf_ids = {case.leaf_id for case in RECORDED_SMOKE_CASES}
    if any(leaf_id not in replay_leaf_ids for leaf_id in leaf_ids):
        raise ValueError("response selection contains a leaf without recorded replay")
    backend = RecordedReplayBackend.load()
    plan = build_response_plan(
        leaf_ids,
        policy=NumericalPolicy(),
        backend_identity=backend.identity,
        job_binder=backend.bind_job,
    )
    return plan, backend


def _selected_response(
    command: str, selection: Path, checkpoint: Path
) -> tuple[int, object]:
    plan, backend = _load_response_selection(selection)
    if command == "response-plan":
        return 0, {
            "command": command,
            "plan_id": plan.plan_id,
            "job_count": len(plan.jobs),
            "jobs": [job.to_mapping() for job in plan.jobs],
            "checkpoint_path": str(checkpoint),
            "release_admissible": False,
        }
    if command == "response-run":
        summary = run_response_plan(plan, backend, checkpoint, resume=False)
    elif command == "response-resume":
        summary = run_response_plan(plan, backend, checkpoint, resume=True)
    elif command == "response-validate":
        summary = validate_response_checkpoint(plan, checkpoint)
    else:
        raise ValueError(f"unknown selected response command: {command}")
    return 0, {"command": command, **summary.to_mapping()}


def _load_strict_json(path: Path, subject: str) -> dict[str, object]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_response_duplicate_keys,
            parse_constant=lambda item: (_ for _ in ()).throw(
                ValueError(f"{subject} contains non-finite constant {item}")
            ),
        )
    except json.JSONDecodeError as error:
        raise ValueError(f"{subject} is not valid JSON") from error
    if not isinstance(value, dict):
        raise ValueError(f"{subject} must be a JSON object")
    return value


def _campaign_plan_and_selection(path: Path):
    value = _load_strict_json(path, "campaign selection")
    if set(value) != {
        "schema_version",
        "backend_id",
        "precision_digits",
        "precision_backend",
        "role",
        "leaf_ids",
        "cohort_ids",
    }:
        raise ValueError("campaign selection fields are invalid")
    if value["schema_version"] != 1:
        raise ValueError("campaign selection schema is invalid")
    backend_identity, descriptor = _campaign_backend_descriptor(
        value["precision_backend"], path.parent
    )
    if value["backend_id"] != backend_identity.backend_id:
        raise ValueError("campaign selection backend identity is invalid")
    digits = value["precision_digits"]
    if not isinstance(digits, list):
        raise ValueError("campaign precision_digits must be an array")
    capabilities = PrecisionCapabilities(tuple(digits))
    plan = build_campaign_plan(
        policy=NumericalPolicy(),
        backend_identity=backend_identity,
        precision_capabilities=capabilities,
        precision_factory_identity=(
            None if descriptor is None else descriptor["factory_identity"]
        ),
    )
    leaf_ids = value["leaf_ids"]
    cohort_ids = value["cohort_ids"]
    if leaf_ids is not None and (
        not isinstance(leaf_ids, list)
        or any(not isinstance(item, str) for item in leaf_ids)
    ):
        raise ValueError("campaign leaf_ids must be a string array or null")
    if cohort_ids is not None and (
        not isinstance(cohort_ids, list)
        or any(not isinstance(item, str) for item in cohort_ids)
    ):
        raise ValueError("campaign cohort_ids must be a string array or null")
    selection = build_campaign_selection(
        plan,
        role=value["role"],
        leaf_ids=leaf_ids,
        cohort_ids=cohort_ids,
    )
    return plan, selection, descriptor


def _backend_identity_from_mapping(value: object) -> BackendIdentity:
    if not isinstance(value, Mapping) or set(value) != {
        "backend_id",
        "implementation_version",
        "source_commit",
        "source_blobs",
        "runtime_fingerprint",
    }:
        raise ValueError("precision backend identity fields are invalid")
    raw_blobs = value["source_blobs"]
    if not isinstance(raw_blobs, list):
        raise ValueError("precision backend source_blobs must be an array")
    blobs: list[tuple[str, str]] = []
    for raw in raw_blobs:
        if not isinstance(raw, Mapping) or set(raw) != {"path", "git_blob_sha"}:
            raise ValueError("precision backend source blob is invalid")
        if not isinstance(raw["path"], str) or not isinstance(
            raw["git_blob_sha"], str
        ):
            raise ValueError("precision backend source blob types are invalid")
        blobs.append((raw["path"], raw["git_blob_sha"]))
    fields = {
        name: value[name]
        for name in (
            "backend_id",
            "implementation_version",
            "source_commit",
            "runtime_fingerprint",
        )
    }
    if any(not isinstance(item, str) for item in fields.values()):
        raise ValueError("precision backend identity types are invalid")
    identity = BackendIdentity(source_blobs=tuple(blobs), **fields)
    if identity.to_mapping() != value:
        raise ValueError("precision backend identity is not canonical")
    return identity


def _campaign_backend_descriptor(value: object, base: Path):
    if value is None:
        return VettedNativeDeterminantKernel.identity, None
    if not isinstance(value, Mapping) or set(value) != {
        "factory",
        "module_path",
        "module_sha256",
        "backend_identity",
        "available_precision_digits",
    }:
        raise ValueError("precision backend descriptor fields are invalid")
    factory = value["factory"]
    module_path = value["module_path"]
    digest = value["module_sha256"]
    digits = value["available_precision_digits"]
    if (
        not isinstance(factory, str)
        or re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*:[A-Za-z_][A-Za-z0-9_]*", factory
        ) is None
        or not isinstance(module_path, str)
        or not isinstance(digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        or not isinstance(digits, list)
    ):
        raise ValueError("precision backend descriptor types are invalid")
    module_name, _ = factory.split(":", 1)
    if module_path != f"{module_name}.py":
        raise ValueError("precision backend module path does not match factory")
    resolved = resolve_campaign_relative_path(base, module_path)
    module_bytes = resolved.read_bytes()
    if hashlib.sha256(module_bytes).hexdigest() != digest:
        raise ValueError("precision backend module SHA-256 is invalid")
    identity = _backend_identity_from_mapping(value["backend_identity"])
    capabilities = PrecisionCapabilities(tuple(digits))
    return identity, {
        "factory": factory,
        "module_path": resolved,
        "module_sha256": digest,
        "module_bytes": module_bytes,
        "factory_identity": PrecisionFactoryIdentity(factory, digest),
        "backend_identity": identity,
        "precision_capabilities": capabilities,
    }


def _load_campaign_backend(descriptor, *, plan=None, selection=None):
    if descriptor is None:
        if plan is None or selection is None:
            raise ValueError("native campaign backend requires the selected campaign leaves")
        return NativeCampaignStageBackend.from_selection(plan, selection)
    module_name, factory_name = descriptor["factory"].split(":", 1)
    module_path = descriptor["module_path"]
    module = types.ModuleType(module_name)
    module.__file__ = str(module_path)
    module.__package__ = ""
    code = compile(descriptor["module_bytes"], str(module_path), "exec")
    exec(code, module.__dict__)
    factory = getattr(module, factory_name, None)
    if not callable(factory):
        raise ValueError("precision backend factory is unavailable")
    backend = factory()
    if getattr(backend, "identity", None) != descriptor["backend_identity"]:
        raise ValueError("precision backend factory identity is invalid")
    if (
        getattr(backend, "precision_capabilities", None)
        != descriptor["precision_capabilities"]
    ):
        raise ValueError("precision backend factory capabilities are invalid")
    return backend


def _validate_campaign_capability_superset(summary, descriptor, plan) -> None:
    available = (
        plan.precision_capabilities
        if descriptor is None
        else descriptor["precision_capabilities"]
    )
    current = set(available.digits)
    for record in summary.records:
        for stage in record.stages:
            prior = set(stage.runner_provenance["available_precision_digits"])
            if not prior.issubset(current):
                raise ValueError(
                    "campaign precision availability is not a permitted superset"
                )


def _campaign_selected(
    command: str,
    selection_path: Path,
    checkpoint: Path,
    *,
    full: bool = False,
    reporter: CampaignProgressReporter | None = None,
):
    if command in {"campaign-run", "campaign-resume"}:
        emit_progress(
            ProgressEventKind.REQUEST_STARTED,
            operation=command,
            selection_path=str(selection_path),
            checkpoint_path=str(checkpoint),
        )
    plan, selection, descriptor = _campaign_plan_and_selection(selection_path)
    if command in {"campaign-run", "campaign-resume"}:
        emit_progress(
            ProgressEventKind.REQUEST_VALIDATED,
            campaign_id=plan.campaign_id,
            selection_id=selection.selection_id,
            leaf_count=len(selection.leaf_ids),
        )
    if command == "campaign-plan":
        return 0, {
            "command": command,
            "campaign_id": plan.campaign_id,
            "leaf_count": len(plan.leaves),
            "selected_leaf_count": len(selection.leaf_ids),
            "role_counts": plan.role_counts,
            "mechanism_counts": plan.mechanism_counts,
            "bindings": plan.bindings,
            "cohorts": [cohort.to_mapping() for cohort in plan.cohorts],
            "selection": selection.to_mapping(),
            "campaign": plan.to_mapping(),
            "release_admissible": False,
        }
    checkpoint = resolve_campaign_relative_path(Path.cwd(), str(checkpoint))
    if command == "campaign-validate":
        summary = validate_campaign_checkpoint(
            plan, checkpoint, require_complete_campaign=full
        )
        _validate_campaign_capability_superset(summary, descriptor, plan)
        if not full and summary.selection_id != selection.selection_id:
            raise ValueError("campaign checkpoint selection does not match request")
    else:
        if command == "campaign-run" and checkpoint.exists():
            raise ValueError("campaign cold execution refuses an existing checkpoint")
        if command == "campaign-resume" and not checkpoint.exists():
            raise ValueError("campaign resume requires an existing checkpoint")
        if command == "campaign-resume":
            cached = validate_campaign_checkpoint(plan, checkpoint)
            _validate_campaign_capability_superset(cached, descriptor, plan)
            if cached.selection_id != selection.selection_id:
                raise ValueError("campaign checkpoint selection does not match request")
            if reporter is not None:
                reporter.bind_campaign_reports(plan)
            if cached.state == "COMPLETE":
                import_campaign_checkpoint_to_solved_leaf_store(
                    plan, checkpoint, SolvedLeafStore.default()
                )
                return 0, _campaign_console_mapping(command, cached)
        elif reporter is not None:
            reporter.bind_campaign_reports(plan)
        backend = _load_campaign_backend(descriptor, plan=plan, selection=selection)
        summary = run_campaign_selection(
            plan,
            selection,
            backend,
            checkpoint,
            resume=command == "campaign-resume",
            solved_leaf_store=SolvedLeafStore.default(),
        )
    return 0, _campaign_console_mapping(command, summary)


def _campaign_cache_import(
    selection_path: Path,
    checkpoint: Path,
    store_path: Path | None,
) -> tuple[int, object]:
    plan, _, _ = _campaign_plan_and_selection(selection_path)
    resolved_checkpoint = resolve_campaign_relative_path(
        Path.cwd(), str(checkpoint)
    )
    store = SolvedLeafStore.default() if store_path is None else SolvedLeafStore(store_path)
    summary = import_campaign_checkpoint_to_solved_leaf_store(
        plan, resolved_checkpoint, store
    )
    return 0, {"command": "campaign-cache-import", **summary.to_mapping()}


def _campaign_console_mapping(
    command: str, summary: CampaignRunSummary
) -> dict[str, object]:
    return {
        "command": command,
        "campaign_id": summary.campaign_id,
        "selection_id": summary.selection_id,
        "state": summary.state,
        "executed_stage_count": summary.executed_stage_count,
        "reused_stage_count": summary.reused_stage_count,
        "result_count": summary.result_count,
        "checkpoint_path": summary.checkpoint_path,
        "release_admissible": False,
    }


def _campaign_merge(manifest: Path, output: Path) -> tuple[int, object]:
    value = _load_strict_json(manifest, "campaign merge manifest")
    if set(value) != {
        "schema_version", "backend_id", "precision_digits", "precision_backend",
        "checkpoint_paths"
    }:
        raise ValueError("campaign merge manifest fields are invalid")
    if value["schema_version"] != 1:
        raise ValueError("campaign merge manifest schema is invalid")
    backend_identity, descriptor = _campaign_backend_descriptor(
        value["precision_backend"], manifest.parent
    )
    if value["backend_id"] != backend_identity.backend_id:
        raise ValueError("campaign merge backend identity is invalid")
    digits = value["precision_digits"]
    paths = value["checkpoint_paths"]
    if not isinstance(digits, list) or not isinstance(paths, list) or any(
        not isinstance(item, str) for item in paths
    ):
        raise ValueError("campaign merge manifest arrays are invalid")
    plan = build_campaign_plan(
        policy=NumericalPolicy(),
        backend_identity=backend_identity,
        precision_capabilities=PrecisionCapabilities(tuple(digits)),
        precision_factory_identity=(
            None if descriptor is None else descriptor["factory_identity"]
        ),
    )
    resolved_output = resolve_campaign_relative_path(Path.cwd(), str(output))
    resolved = tuple(
        resolve_campaign_relative_path(manifest.parent, path) for path in paths
    )
    for path in resolved:
        _validate_campaign_capability_superset(
            validate_campaign_checkpoint(plan, path), descriptor, plan
        )
    summary = merge_campaign_checkpoints(plan, resolved, resolved_output)
    return 0, {"command": "campaign-merge", **summary.to_mapping()}


def _campaign_reduce(bundle_path: Path, output: Path) -> tuple[int, object]:
    bundle = resolve_campaign_relative_path(Path.cwd(), str(bundle_path))
    resolved_output = resolve_campaign_relative_path(Path.cwd(), str(output))
    if resolved_output.exists():
        raise ValueError("campaign reduction refuses an existing output")
    value = _load_strict_json(bundle, "campaign reduction bundle")
    expected_fields = {
        "schema_version", "campaign_id", "backend_id", "precision_digits",
        "precision_backend", "checkpoint_paths", "selected_row_ids",
        "component_evidence", "source_hashes", "bundle_sha256",
    }
    if set(value) != expected_fields or value["schema_version"] != 1:
        raise ValueError("campaign reduction bundle fields or schema are invalid")
    sealed = {key: item for key, item in value.items() if key != "bundle_sha256"}
    expected_digest = hashlib.sha256(canonical_json_bytes(sealed)).hexdigest()
    if value["bundle_sha256"] != expected_digest:
        raise ValueError("campaign reduction bundle digest is invalid")
    backend_identity, descriptor = _campaign_backend_descriptor(
        value["precision_backend"], bundle.parent
    )
    if value["backend_id"] != backend_identity.backend_id:
        raise ValueError("campaign reduction backend identity is invalid")
    digits = value["precision_digits"]
    checkpoint_paths = value["checkpoint_paths"]
    selected_row_ids = value["selected_row_ids"]
    raw_components = value["component_evidence"]
    declared_hashes = value["source_hashes"]
    if (
        not isinstance(digits, list)
        or not isinstance(checkpoint_paths, list)
        or not checkpoint_paths
        or any(not isinstance(item, str) for item in checkpoint_paths)
        or len(checkpoint_paths) != len(set(checkpoint_paths))
        or not isinstance(selected_row_ids, list)
        or any(not isinstance(item, str) for item in selected_row_ids)
        or not isinstance(raw_components, list)
        or not isinstance(declared_hashes, list)
        or any(not isinstance(item, str) for item in declared_hashes)
    ):
        raise ValueError("campaign reduction bundle arrays are invalid")
    plan = build_campaign_plan(
        policy=NumericalPolicy(),
        backend_identity=backend_identity,
        precision_capabilities=PrecisionCapabilities(tuple(digits)),
        precision_factory_identity=(
            None if descriptor is None else descriptor["factory_identity"]
        ),
    )
    if value["campaign_id"] != plan.campaign_id:
        raise ValueError("campaign reduction campaign lineage is stale or mixed")
    resolved_checkpoints = tuple(
        resolve_campaign_relative_path(bundle.parent, item)
        for item in checkpoint_paths
    )
    computed_hashes = tuple(
        "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        for path in resolved_checkpoints
    )
    if tuple(declared_hashes) != computed_hashes:
        raise ValueError("campaign reduction checkpoint source hashes are invalid")
    records_by_id: dict[str, CampaignLeafRecord] = {}
    receipts_by_id: dict[str, set[str]] = {}
    for checkpoint, checkpoint_receipt in zip(
        resolved_checkpoints, computed_hashes
    ):
        summary = validate_campaign_checkpoint(plan, checkpoint)
        _validate_campaign_capability_superset(summary, descriptor, plan)
        for record in summary.records:
            existing = records_by_id.get(record.leaf_id)
            if (
                existing is not None
                and existing.to_mapping() != record.to_mapping()
            ):
                raise ValueError(
                    "campaign reduction checkpoint overlap disagrees"
                )
            records_by_id[record.leaf_id] = record
            receipts_by_id.setdefault(record.leaf_id, set()).add(
                checkpoint_receipt
            )
    components = tuple(
        component_evidence_from_mapping(item) for item in raw_components
    )
    component_ids = tuple(item.component_id for item in components)
    if len(component_ids) != len(set(component_ids)):
        raise ValueError("campaign reduction component evidence contains duplicates")
    for component in components:
        record = records_by_id.get(component.component_id)
        if record is None:
            raise ValueError(
                "campaign reduction component is absent from authenticated checkpoint"
            )
        _validate_reduction_component_checkpoint_binding(
            component,
            record,
            frozenset(receipts_by_id[component.component_id]),
        )
    reduction = reduce_projective_rows(
        plan.campaign_id,
        selected_row_ids,
        {item.component_id: item for item in components},
        source_hashes=computed_hashes,
    )
    output_mapping = reduction.to_mapping()
    _atomic_export(resolved_output, output_mapping)
    return 0, {"command": "campaign-reduce", **output_mapping}


def _m02_summary(
    command: str,
    package: LinearResponseAdmissionPackage,
    *,
    release_admissible: bool,
    output: Path | None = None,
) -> dict[str, object]:
    summary: dict[str, object] = {
        "command": command,
        "admission_id": package.admission_id,
        "produced_leaf_count": package.evidence_receipt["produced_count"],
        "missing_leaf_count": package.evidence_receipt["missing_count"],
        "unresolved_leaf_count": len(
            package.evidence_receipt["unresolved_leaf_ids"]
        ),
        "projective_row_count": package.reduction_receipt["row_count"],
        "scientific_claims_admitted": False,
        "release_admissible": release_admissible,
    }
    if output is not None:
        summary["output"] = str(output)
    return summary


def _m02_validate(manifest: Path) -> tuple[int, object]:
    return 0, {
        "command": "m02-validate",
        **validate_linear_response_bundle(manifest),
    }


def _m02_admit(manifest: Path, output: Path) -> tuple[int, object]:
    package = admit_linear_response_bundle(manifest)
    resolved_output = resolve_campaign_relative_path(Path.cwd(), str(output))
    if resolved_output.exists():
        raise ValueError("M02 admission refuses an existing output")
    _atomic_export(resolved_output, package.to_mapping())
    return 0, _m02_summary(
        "m02-admit", package, release_admissible=True, output=resolved_output
    )


def _m02_export(
    admission: Path, expected_admission_id: str, output: Path
) -> tuple[int, object]:
    package = load_linear_response_admission(
        admission, expected_admission_id=expected_admission_id
    )
    resolved_output = resolve_campaign_relative_path(Path.cwd(), str(output))
    if resolved_output.exists():
        raise ValueError("M02 export refuses an existing output")
    _atomic_export(resolved_output, package.to_mapping())
    return 0, _m02_summary(
        "m02-export", package, release_admissible=True, output=resolved_output
    )


def main(argv: Sequence[str] | None = None) -> int:
    try:
        arguments = build_parser().parse_args(argv)
        if arguments.command == "plan":
            status, output = _plan(
                arguments.study,
                arguments.linear_response_admission,
                arguments.linear_response_admission_id,
            )
        elif arguments.command == "run":
            status, output = _run(
                arguments.study,
                arguments.store,
                arguments.linear_response_admission,
                arguments.linear_response_admission_id,
            )
        elif arguments.command == "verify":
            status, output = _verify(
                arguments.run_id, arguments.store, arguments.profile
            )
        elif arguments.command == "inspect":
            status, output = _inspect(arguments.run_id, arguments.store)
        elif arguments.command == "export":
            status, output = _export(
                arguments.run_id, arguments.store, arguments.output
            )
        elif arguments.command == "validate-evidence":
            status, output = _validate_evidence(arguments.bundle)
        elif arguments.command.startswith("response-"):
            status, output = _selected_response(
                arguments.command, arguments.selection, arguments.checkpoint
            )
        elif arguments.command == "campaign-plan":
            status, output = _campaign_selected(
                arguments.command, arguments.selection, Path("unused")
            )
        elif arguments.command in {
            "campaign-run", "campaign-resume", "campaign-validate"
        }:
            reporter = None
            if arguments.command in {"campaign-run", "campaign-resume"}:
                progress_checkpoint = resolve_campaign_relative_path(
                    Path.cwd(), str(arguments.checkpoint)
                )
                reporter = CampaignProgressReporter(
                    arguments.progress, progress_checkpoint
                )
            if reporter is None:
                status, output = _campaign_selected(
                    arguments.command,
                    arguments.selection,
                    arguments.checkpoint,
                    full=getattr(arguments, "full", False),
                )
            else:
                try:
                    with activate_progress(reporter):
                        try:
                            status, output = _campaign_selected(
                                arguments.command,
                                arguments.selection,
                                arguments.checkpoint,
                                reporter=reporter,
                            )
                        except KeyboardInterrupt:
                            emit_progress(
                                ProgressEventKind.REQUEST_INTERRUPTED,
                                operation=arguments.command,
                                message="operator interrupt",
                            )
                            raise
                        except BaseException as error:
                            worker_failure = worker_failure_payload(error)
                            emit_progress(
                                ProgressEventKind.REQUEST_FAILED,
                                operation=arguments.command,
                                error_type=type(error).__name__,
                                message=str(error),
                                **(
                                    {} if worker_failure is None
                                    else {"worker_failure": worker_failure}
                                ),
                            )
                            raise
                        else:
                            emit_progress(
                                ProgressEventKind.REQUEST_COMPLETED,
                                operation=arguments.command,
                                status=status,
                                state=output.get("state"),
                                checkpoint_path=output.get("checkpoint_path"),
                            )
                finally:
                    reporter.close()
        elif arguments.command == "campaign-merge":
            status, output = _campaign_merge(arguments.manifest, arguments.output)
        elif arguments.command == "campaign-cache-import":
            status, output = _campaign_cache_import(
                arguments.selection, arguments.checkpoint, arguments.store
            )
        elif arguments.command == "campaign-reduce":
            status, output = _campaign_reduce(arguments.bundle, arguments.output)
        elif arguments.command == "campaign-smoke":
            status, output = 0, {
                "command": "campaign-smoke",
                **run_predeclared_campaign_smoke().to_mapping(),
            }
        elif arguments.command == "m02-validate":
            status, output = _m02_validate(arguments.manifest)
        elif arguments.command == "m02-admit":
            status, output = _m02_admit(arguments.manifest, arguments.output)
        elif arguments.command == "m02-export":
            status, output = _m02_export(
                arguments.admission, arguments.admission_id, arguments.output
            )
        else:
            raise ValueError(f"unknown command: {arguments.command}")
    except KeyboardInterrupt:
        _emit(
            {
                "error": {
                    "code": "INTERRUPTED",
                    "message": (
                        "operation interrupted by user; committed checkpoints "
                        "remain resumable"
                    ),
                }
            },
            stream=sys.stderr,
        )
        return 130
    except ArtifactVerificationError as error:
        _emit(
            {"error": {"code": "VERIFICATION_FAILED", "message": str(error)}},
            stream=sys.stderr,
        )
        return 4
    except NativeResourceUnavailableError as error:
        _emit(
            {"error": {"code": "PROVIDER_UNAVAILABLE", "message": str(error)}},
            stream=sys.stderr,
        )
        return 3
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ) as error:
        _emit(
            {"error": {"code": "INVALID_INPUT", "message": str(error)}},
            stream=sys.stderr,
        )
        return 2
    except OSError as error:
        _emit(
            {"error": {"code": "IO_FAILED", "message": str(error)}},
            stream=sys.stderr,
        )
        return 5
    if arguments.command == "run" and status != 0:
        code = (
            "PROVIDER_UNAVAILABLE"
            if status == 3
            else "EXECUTION_FAILED"
        )
        _emit(
            {
                "error": {
                    "code": code,
                    "message": output.get("error", "run failed"),
                    "run": output,
                }
            },
            stream=sys.stderr,
        )
        return status
    _emit(output)
    return status
