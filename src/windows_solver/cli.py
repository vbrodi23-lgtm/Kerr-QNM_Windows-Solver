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
from .planner import build_plan
from .providers import ProviderUnavailableError
from .response_engine import (
    BackendIdentity,
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
    NativeCampaignStageBackend,
    PrecisionCapabilities,
    PrecisionFactoryIdentity,
    build_campaign_plan,
    build_campaign_selection,
    merge_campaign_checkpoints,
    resolve_campaign_relative_path,
    run_campaign_selection,
    run_predeclared_campaign_smoke,
    validate_campaign_checkpoint,
)
from .response_engine import VettedNativeDeterminantKernel, NativeResourceUnavailableError
from .response_reduction import (
    ComputedUnresolvedComponentEvidence,
    component_evidence_from_mapping,
    reduce_projective_rows,
)


class CommandParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = CommandParser(prog="solver")
    commands = parser.add_subparsers(dest="command", required=True)

    plan = commands.add_parser("plan", help="show the requested dependency closure")
    plan.add_argument("study", type=Path)

    run = commands.add_parser("run", help="execute one requested dependency closure")
    run.add_argument("study", type=Path)
    run.add_argument("--store", type=Path, default=Path(".solver-store"))

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
        if name == "campaign-validate":
            campaign.add_argument("--full", action="store_true")
    campaign_merge = commands.add_parser(
        "campaign-merge", help="merge compatible campaign checkpoints"
    )
    campaign_merge.add_argument("manifest", type=Path)
    campaign_merge.add_argument("--output", type=Path, required=True)
    campaign_reduce = commands.add_parser(
        "campaign-reduce",
        help="reduce authenticated campaign checkpoints without backend work",
    )
    campaign_reduce.add_argument("bundle", type=Path)
    campaign_reduce.add_argument("--output", type=Path, required=True)
    commands.add_parser(
        "campaign-smoke", help="run exactly ten predeclared orchestration cases"
    )
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


def _plan(study_path: Path) -> tuple[int, object]:
    request = load_study(study_path)
    plan = build_plan(request.target)
    registry = default_registry()
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


def _run(study_path: Path, store_path: Path) -> tuple[int, object]:
    request = load_study(study_path)
    record = ExecutionEngine(ArtifactStore(store_path), default_registry()).run(request)
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


def _load_campaign_backend(descriptor):
    if descriptor is None:
        return NativeCampaignStageBackend.from_environment()
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


def _validate_campaign_capability_superset(summary, descriptor) -> None:
    available = (
        PrecisionCapabilities((64,))
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


def _campaign_selected(command: str, selection_path: Path, checkpoint: Path, *, full=False):
    plan, selection, descriptor = _campaign_plan_and_selection(selection_path)
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
        _validate_campaign_capability_superset(summary, descriptor)
        if not full and summary.selection_id != selection.selection_id:
            raise ValueError("campaign checkpoint selection does not match request")
    else:
        if command == "campaign-run" and checkpoint.exists():
            raise ValueError("campaign cold execution refuses an existing checkpoint")
        if command == "campaign-resume" and not checkpoint.exists():
            raise ValueError("campaign resume requires an existing checkpoint")
        if command == "campaign-resume":
            cached = validate_campaign_checkpoint(plan, checkpoint)
            _validate_campaign_capability_superset(cached, descriptor)
            if cached.selection_id != selection.selection_id:
                raise ValueError("campaign checkpoint selection does not match request")
            if cached.state == "COMPLETE":
                return 0, {"command": command, **cached.to_mapping()}
        backend = _load_campaign_backend(descriptor)
        summary = run_campaign_selection(
            plan,
            selection,
            backend,
            checkpoint,
            resume=command == "campaign-resume",
        )
    return 0, {"command": command, **summary.to_mapping()}


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
            validate_campaign_checkpoint(plan, path), descriptor
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
    for checkpoint in resolved_checkpoints:
        summary = validate_campaign_checkpoint(plan, checkpoint)
        _validate_campaign_capability_superset(summary, descriptor)
    components = tuple(
        component_evidence_from_mapping(item) for item in raw_components
    )
    component_ids = tuple(item.component_id for item in components)
    if len(component_ids) != len(set(component_ids)):
        raise ValueError("campaign reduction component evidence contains duplicates")
    authenticated_receipts = set(computed_hashes)
    for component in components:
        if component.evidence_kind != "authenticated-campaign":
            raise ValueError("campaign reduction CLI accepts authenticated evidence only")
        if isinstance(component, ComputedUnresolvedComponentEvidence):
            if component.source_receipt not in authenticated_receipts:
                raise ValueError("unresolved component source receipt is not authenticated")
        if any(
            contribution.source_receipt not in authenticated_receipts
            for contribution in component.contributions
        ):
            raise ValueError("signed channel source receipt is not authenticated")
    reduction = reduce_projective_rows(
        plan.campaign_id,
        selected_row_ids,
        {item.component_id: item for item in components},
        source_hashes=computed_hashes,
    )
    output_mapping = reduction.to_mapping()
    _atomic_export(resolved_output, output_mapping)
    return 0, {"command": "campaign-reduce", **output_mapping}


def main(argv: Sequence[str] | None = None) -> int:
    try:
        arguments = build_parser().parse_args(argv)
        if arguments.command == "plan":
            status, output = _plan(arguments.study)
        elif arguments.command == "run":
            status, output = _run(arguments.study, arguments.store)
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
            status, output = _campaign_selected(
                arguments.command,
                arguments.selection,
                arguments.checkpoint,
                full=getattr(arguments, "full", False),
            )
        elif arguments.command == "campaign-merge":
            status, output = _campaign_merge(arguments.manifest, arguments.output)
        elif arguments.command == "campaign-reduce":
            status, output = _campaign_reduce(arguments.bundle, arguments.output)
        elif arguments.command == "campaign-smoke":
            status, output = 0, {
                "command": "campaign-smoke",
                **run_predeclared_campaign_smoke().to_mapping(),
            }
        else:
            raise ValueError(f"unknown command: {arguments.command}")
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
