"""One deterministic command surface for The Windows Solver."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Sequence

from .artifacts import ArtifactStore, ArtifactVerificationError
from .builtin import default_registry
from .contracts import canonical_json_bytes, load_study
from .engine import ExecutionEngine, RunRecord, verify_run_integrity
from .planner import build_plan
from .providers import ProviderUnavailableError


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
        else:
            raise ValueError(f"unknown command: {arguments.command}")
    except ArtifactVerificationError as error:
        _emit(
            {"error": {"code": "VERIFICATION_FAILED", "message": str(error)}},
            stream=sys.stderr,
        )
        return 4
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
