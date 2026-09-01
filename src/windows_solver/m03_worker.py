"""Persistent JSON-RPC process boundary for the sole M03 scientific engine."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
from typing import IO, Mapping, Sequence

from .contracts import canonical_json_bytes


RPC_SCHEMA = "windows-solver.m03-json-rpc/2"


class M03WorkerError(RuntimeError):
    """Operational failure of the persistent Julia process."""


class M03IdentityRejection(M03WorkerError):
    """Fail-closed request or response identity mismatch."""


class M03PolicyRejection(M03WorkerError):
    """The request contradicts the frozen M03 numerical policy."""


class M03SystemFailure(M03WorkerError):
    """The Julia process or its protocol boundary failed operationally."""


def request_identity(value: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _powershell_object_identity(value: Mapping[str, object]) -> str:
    """Match bootstrap's ordered ``ConvertTo-Json -Compress`` identity."""

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def worker_from_runtime_receipt(
    runtime_receipt: str | os.PathLike[str] | Path,
    *,
    stderr_sink: IO[str] | None = None,
) -> "PersistentM03Worker":
    """Authenticate and construct the installed M03 worker invocation."""

    receipt_path = Path(runtime_receipt)
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise M03WorkerError("M03 runtime receipt is absent or invalid") from error
    julia = receipt.get("julia_runtime") if isinstance(receipt, Mapping) else None
    m03 = julia.get("m03") if isinstance(julia, Mapping) else None
    if not isinstance(julia, Mapping) or julia.get("requested") is not True or not isinstance(m03, Mapping):
        raise M03WorkerError(
            "M03 Julia runtime is not staged; run .\\runtime\\bootstrap.ps1 -WithM03"
        )
    if m03.get("schema") != "windows-solver.m03-runtime-receipt/2":
        raise M03IdentityRejection("installed M03 runtime receipt schema is stale")
    expected_m03_fields = {
        "schema",
        "contract",
        "contract_sha256",
        "worker",
        "worker_sha256",
        "core",
        "core_sha256",
        "project",
        "project_sha256",
        "manifest_sha256",
        "depot",
        "source_root",
    }
    if set(m03) != expected_m03_fields:
        raise M03IdentityRejection("installed M03 runtime receipt fields changed")
    contract = m03.get("contract")
    expected_contract_fields = {
        "schema",
        "worker_sha256",
        "core_sha256",
        "project_sha256",
        "manifest_seed_sha256",
        "julia_version",
        "m02_dependency_contract_sha256",
    }
    if (
        not isinstance(contract, Mapping)
        or set(contract) != expected_contract_fields
        or contract.get("schema") != "windows-solver.m03-runtime-contract/2"
        or contract.get("worker_sha256") != m03.get("worker_sha256")
        or contract.get("core_sha256") != m03.get("core_sha256")
        or contract.get("project_sha256") != m03.get("project_sha256")
        or _powershell_object_identity(contract) != m03.get("contract_sha256")
        or contract.get("julia_version") != julia.get("version")
        or contract.get("m02_dependency_contract_sha256")
        != julia.get("dependency_contract_sha256")
    ):
        raise M03IdentityRejection("installed M03 runtime contract is stale")
    executable = Path(str(julia.get("executable", "")))
    project = Path(str(m03.get("project", "")))
    worker = Path(str(m03.get("worker", "")))
    core = Path(str(m03.get("core", "")))
    depot = Path(str(m03.get("depot", "")))
    manifest = project / "Manifest.toml"
    project_file = project / "Project.toml"
    for path, label in (
        (executable, "Julia executable"),
        (worker, "M03 worker"),
        (core, "M03 core"),
        (manifest, "M03 Manifest"),
        (project_file, "M03 Project"),
    ):
        if not path.is_file() or path.is_symlink():
            raise M03WorkerError(f"installed {label} is invalid: {path}")
    if core.parent != worker.parent:
        raise M03IdentityRejection("installed M03 core is not adjacent to its worker")
    if not depot.is_dir() or depot.is_symlink():
        raise M03WorkerError(f"installed M03 Julia depot is invalid: {depot}")
    for key, path in (
        ("executable_sha256", executable),
        ("worker_sha256", worker),
        ("core_sha256", core),
        ("manifest_sha256", manifest),
        ("project_sha256", project_file),
    ):
        declared = julia.get(key) if key == "executable_sha256" else m03.get(key)
        observed = hashlib.sha256(path.read_bytes()).hexdigest()
        if declared != observed:
            raise M03IdentityRejection(f"installed M03 {key} digest is stale")
    arguments = julia.get("arguments", [])
    if not isinstance(arguments, list) or any(not isinstance(item, str) or not item for item in arguments):
        raise M03WorkerError("installed Julia invocation arguments are invalid")
    environment = os.environ.copy()
    environment["JULIA_DEPOT_PATH"] = str(depot)
    command = [
        str(executable),
        *arguments,
        "--startup-file=no",
        "--history-file=no",
        f"--project={project}",
        str(worker),
    ]
    return PersistentM03Worker(
        command=command,
        cwd=project,
        environment=environment,
        stderr_sink=stderr_sink,
    )


class PersistentM03Worker:
    """One long-lived Julia process serving all nodes in a campaign."""

    def __init__(
        self,
        *,
        command: Sequence[str],
        cwd: str | os.PathLike[str] | Path,
        environment: Mapping[str, str] | None = None,
        stderr_sink: IO[str] | None = None,
    ) -> None:
        if not command:
            raise ValueError("M03 Julia command is empty")
        self._command = tuple(command)
        self._cwd = Path(cwd)
        self._environment = None if environment is None else dict(environment)
        self._stderr_sink = stderr_sink
        self._process: subprocess.Popen[str] | None = None
        self._stderr_thread: threading.Thread | None = None
        self.launch_count = 0
        self.request_count = 0

    @property
    def alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> None:
        if self.alive:
            return
        self._process = subprocess.Popen(
            self._command,
            cwd=self._cwd,
            env=self._environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="strict",
            bufsize=1,
        )
        self.launch_count += 1
        assert self._process.stderr is not None
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr,
            args=(self._process.stderr,),
            name="m03-julia-stderr",
            daemon=True,
        )
        self._stderr_thread.start()
        hello = self.call("hello", {})
        if (
            hello.get("worker_kind") != "m03-julia-protocol-worker"
            or hello.get("worker_version") != "m03-worker-v2"
            or hello.get("core_schema") != "windows-solver.m03-core/1"
            or hello.get("core_version") != "m03-core-v1"
            or hello.get("rpc_schema") != RPC_SCHEMA
        ):
            self.close(force=True)
            raise M03IdentityRejection(
                "Julia process does not expose the authenticated M03 worker/core pair"
            )

    def _drain_stderr(self, stream: IO[str]) -> None:
        for line in stream:
            if self._stderr_sink is not None:
                self._stderr_sink.write(line)
                self._stderr_sink.flush()

    def call(self, method: str, params: Mapping[str, object]) -> dict[str, object]:
        if not self.alive:
            if method == "hello":
                raise M03WorkerError("M03 Julia worker failed during startup")
            self.start()
        assert self._process is not None
        assert self._process.stdin is not None
        assert self._process.stdout is not None
        request_number = self.request_count
        self.request_count += 1
        material = {
            "schema": RPC_SCHEMA,
            "request_id": request_number,
            "method": method,
            "params": dict(params),
        }
        request = {**material, "request_identity_sha256": request_identity(material)}
        try:
            self._process.stdin.write(canonical_json_bytes(request).decode("utf-8") + "\n")
            self._process.stdin.flush()
            line = self._process.stdout.readline()
        except (BrokenPipeError, OSError) as error:
            raise M03WorkerError("M03 Julia worker pipe failed") from error
        if not line:
            code = self._process.poll()
            raise M03WorkerError(f"M03 Julia worker exited without a response ({code})")
        try:
            response = json.loads(line)
        except json.JSONDecodeError as error:
            raise M03WorkerError("M03 Julia stdout contained malformed RPC") from error
        if not isinstance(response, dict) or set(response) != {
            "schema",
            "request_id",
            "request_identity_sha256",
            "ok",
            "result",
            "error",
            "response_identity_sha256",
        }:
            raise M03WorkerError("M03 Julia response envelope is invalid")
        sealed = {
            key: value for key, value in response.items() if key != "response_identity_sha256"
        }
        if response["response_identity_sha256"] != request_identity(sealed):
            raise M03IdentityRejection("M03 Julia response digest is invalid")
        if (
            response["schema"] != RPC_SCHEMA
            or response["request_id"] != request_number
            or response["request_identity_sha256"] != request["request_identity_sha256"]
        ):
            raise M03IdentityRejection("M03 Julia response does not echo the request identity")
        if response["ok"] is not True:
            error = response["error"]
            error_class = error.get("class") if isinstance(error, Mapping) else None
            message = (
                str(error.get("message"))
                if isinstance(error, Mapping)
                else "M03 Julia request failed"
            )
            if error_class == "IDENTITY_REJECTION":
                raise M03IdentityRejection(message)
            if error_class == "POLICY_REJECTION":
                raise M03PolicyRejection(message)
            raise M03SystemFailure(message)
        result = response["result"]
        if not isinstance(result, dict) or response["error"] is not None:
            raise M03WorkerError("M03 Julia successful response payload is invalid")
        metadata_fields = {
            "rpc_request_identity_sha256",
            "rpc_response_identity_sha256",
        }
        if metadata_fields.intersection(result):
            raise M03IdentityRejection(
                "M03 Julia result attempted to shadow RPC identity metadata"
            )
        return {
            **result,
            "rpc_request_identity_sha256": response[
                "request_identity_sha256"
            ],
            "rpc_response_identity_sha256": response[
                "response_identity_sha256"
            ],
        }

    def close(self, *, force: bool = False) -> None:
        process = self._process
        if process is None:
            return
        if process.poll() is None and not force:
            try:
                self.call("shutdown", {})
            except M03WorkerError:
                force = True
        if process.poll() is None:
            if force:
                process.kill()
            else:
                process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        self._process = None

    def restart(self) -> None:
        self.close(force=True)
        self.start()

    def __enter__(self) -> "PersistentM03Worker":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


__all__ = [
    "M03IdentityRejection",
    "M03PolicyRejection",
    "M03SystemFailure",
    "M03WorkerError",
    "PersistentM03Worker",
    "RPC_SCHEMA",
    "request_identity",
    "worker_from_runtime_receipt",
]
