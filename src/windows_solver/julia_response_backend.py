"""Authenticated Python boundary for the package-owned Julia precision worker.

The worker performs only promoted 80/120-decimal-digit root readouts.  The
existing Python response engine still owns the signed-amplitude ladder,
component reduction, error ledger, checkpoints, resume, and admission schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
import math
import os
from pathlib import Path
from queue import Empty, Queue
import subprocess
import tempfile
from threading import Thread
import time
from types import SimpleNamespace
from typing import Callable, Mapping

from .contracts import canonical_json_bytes
from .response_engine import (
    BackendIdentity,
    ROOT_BRANCH_CONTINUATION_TOLERANCE_ABS,
    ResponseComponentJob,
    RootReadout,
    _exterior_support,
)
from .progress import ProgressEventKind, emit_progress, ingest_external_progress


_PROMOTED_DIGITS = frozenset({80, 120})
JULIA_PROGRESS_PREFIX = "@@KERR_QNM_PROGRESS@@"
_WORKER_HEARTBEAT_SECONDS = 2.0
_BRANCH_TOLERANCE_DECIMAL = Decimal(
    str(ROOT_BRANCH_CONTINUATION_TOLERANCE_ABS)
)


def _forward_julia_progress_line(line: str) -> bool:
    """Forward one reserved worker event; return whether the line was reserved."""

    if not line.startswith(JULIA_PROGRESS_PREFIX):
        return False
    try:
        value = json.loads(line[len(JULIA_PROGRESS_PREFIX):])
        ingest_external_progress(value)
    except Exception as error:
        emit_progress(
            ProgressEventKind.ERROR,
            source="julia-progress",
            error_type=type(error).__name__,
            message=str(error),
        )
    return True


def _run_streamed_julia(
    command: tuple[str, ...], *, cwd: Path, env: Mapping[str, str], timeout: int
) -> object:
    """Drain worker pipes concurrently and forward progress before completion."""

    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=dict(env),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    progress_lines: Queue[str | None] = Queue()

    def read_stdout() -> None:
        assert process.stdout is not None
        try:
            for line in process.stdout:
                stripped = line.rstrip("\r\n")
                if stripped.startswith(JULIA_PROGRESS_PREFIX):
                    progress_lines.put(stripped)
                else:
                    stdout_lines.append(line)
        finally:
            progress_lines.put(None)

    def read_stderr() -> None:
        assert process.stderr is not None
        stderr_lines.extend(process.stderr)

    stdout_thread = Thread(target=read_stdout, daemon=True)
    stderr_thread = Thread(target=read_stderr, daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    timed_out = False
    deadline = time.monotonic() + timeout
    next_heartbeat = time.monotonic() + _WORKER_HEARTBEAT_SECONDS
    returncode: int | None = None
    stdout_done = False
    while returncode is None or not stdout_done:
        if returncode is None:
            returncode = process.poll()
            if returncode is None and time.monotonic() >= deadline:
                timed_out = True
                process.kill()
                returncode = process.wait()
                stderr_lines.append(
                    f"Julia worker timed out after {timeout} seconds\n"
                )
        now = time.monotonic()
        wait_seconds = 0.05
        if returncode is None:
            wait_seconds = min(
                wait_seconds,
                max(0.0, next_heartbeat - now),
                max(0.0, deadline - now),
            )
        try:
            line = progress_lines.get(timeout=wait_seconds)
        except Empty:
            line = ""
        if line is None:
            stdout_done = True
        elif line:
            _forward_julia_progress_line(line)
        now = time.monotonic()
        if returncode is None and now >= next_heartbeat:
            emit_progress(
                ProgressEventKind.WORKER_HEARTBEAT,
                worker="Julia",
                worker_alive=True,
                heartbeat_interval_seconds=_WORKER_HEARTBEAT_SECONDS,
            )
            next_heartbeat = now + _WORKER_HEARTBEAT_SECONDS
    stdout_thread.join()
    stderr_thread.join()
    if process.stdout is not None:
        process.stdout.close()
    if process.stderr is not None:
        process.stderr.close()
    return SimpleNamespace(
        returncode=returncode,
        stdout="".join(stdout_lines)[-4000:],
        stderr="".join(stderr_lines)[-4000:],
        timed_out=timed_out,
    )


class JuliaResponseBackendError(RuntimeError):
    """The package-owned Julia precision worker is unavailable or rejected work."""


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise JuliaResponseBackendError(
                f"Julia response contains duplicate key {key!r}"
            )
        value[key] = item
    return value


def _regular_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise JuliaResponseBackendError(f"{label} is absent: {path}")
    if path.is_symlink():
        raise JuliaResponseBackendError(f"{label} must not be a symlink: {path}")
    return path.resolve()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _strict_json_file(path: Path, label: str) -> dict[str, object]:
    _regular_file(path, label)
    try:
        value = json.loads(
            path.read_bytes(),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda item: (_ for _ in ()).throw(
                JuliaResponseBackendError(
                    f"{label} contains non-finite constant {item}"
                )
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise JuliaResponseBackendError(f"{label} is invalid JSON") from error
    if not isinstance(value, dict):
        raise JuliaResponseBackendError(f"{label} must be a JSON object")
    return value


def _worker_failure_details(
    completed: object,
    response_path: Path,
    *,
    response: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Extract an operational failure receipt without treating it as science."""

    error_response = response
    if error_response is None:
        try:
            error_response = _strict_json_file(
                response_path, "M02 Julia worker failure response"
            )
        except JuliaResponseBackendError:
            error_response = None
    error_type: str | None = None
    error_message: str | None = None
    if (
        isinstance(error_response, Mapping)
        and set(error_response) == {
            "schema_version", "status", "error_type", "message"
        }
        and error_response["schema_version"] == 1
        and error_response["status"] == "error"
        and isinstance(error_response["error_type"], str)
        and isinstance(error_response["message"], str)
    ):
        error_type = error_response["error_type"]
        error_message = error_response["message"]
    raw_exit_code = getattr(completed, "returncode", None)
    exit_code = (
        raw_exit_code
        if isinstance(raw_exit_code, int) and not isinstance(raw_exit_code, bool)
        else None
    )
    return {
        "worker_exit_code": exit_code,
        "worker_timed_out": bool(getattr(completed, "timed_out", False)),
        "worker_stderr_tail": str(getattr(completed, "stderr", ""))[-4000:],
        "worker_error_type": error_type,
        "worker_error_message": error_message,
    }


def _raise_worker_failure(details: Mapping[str, object]) -> None:
    """Raise an operational error while retaining bounded worker diagnostics."""

    timed_out = details["worker_timed_out"] is True
    exit_code = details["worker_exit_code"]
    prefix = "M02 Julia worker timed out" if timed_out else "M02 Julia worker failed"
    message = f"{prefix} with code {exit_code}"
    error_type = details["worker_error_type"]
    error_message = details["worker_error_message"]
    stderr = details["worker_stderr_tail"]
    if isinstance(error_type, str) and isinstance(error_message, str):
        message += f": {error_type}: {error_message}"
    elif isinstance(stderr, str) and stderr:
        message += f": {stderr}"
    failure = JuliaResponseBackendError(message)
    failure.worker_failure = dict(details)
    raise failure


def _finite_text(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise JuliaResponseBackendError(f"Julia response {label} is not numeric")
    converted = float(value)
    if not math.isfinite(converted):
        raise JuliaResponseBackendError(f"Julia response {label} is not finite")
    return converted


def _finite_decimal_text(
    value: object, label: str, *, nonnegative: bool = False
) -> Decimal:
    """Preserve promoted-precision branch evidence without binary64 rounding."""

    if not isinstance(value, str) or not value:
        raise JuliaResponseBackendError(
            f"Julia response {label} is not precision-preserving numeric text"
        )
    try:
        converted = Decimal(value)
    except InvalidOperation as error:
        raise JuliaResponseBackendError(
            f"Julia response {label} is not numeric"
        ) from error
    if not converted.is_finite() or (nonnegative and converted < 0):
        raise JuliaResponseBackendError(
            f"Julia response {label} is not finite and nonnegative"
        )
    return converted


def _runtime_root() -> Path:
    override = os.environ.get("KERR_QNM_RUNTIME_ROOT")
    if override:
        return Path(override)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if os.name == "nt" and local_app_data:
        return Path(local_app_data) / "Kerr-QNM_Windows-Solver" / "runtime-1"
    return Path.cwd() / ".runtime"


@dataclass(frozen=True, slots=True)
class JuliaResponseAdapter:
    julia_executable: Path
    julia_project: Path
    julia_depot: Path
    worker_script: Path
    runtime_provenance: Mapping[str, object]
    runner: Callable[..., object] = subprocess.run
    julia_prefix_arguments: tuple[str, ...] = ()

    @classmethod
    def from_runtime_receipt(
        cls,
        *,
        runtime_root: Path | None = None,
        runner: Callable[..., object] = subprocess.run,
    ) -> "JuliaResponseAdapter":
        runtime = Path(runtime_root or _runtime_root())
        receipt_path = runtime / "python-runtime.json"
        receipt = _strict_json_file(receipt_path, "M02 runtime receipt")
        julia = receipt.get("julia_runtime")
        if not isinstance(julia, Mapping) or julia.get("requested") is not True:
            raise JuliaResponseBackendError(
                "M02 Julia runtime is not provisioned; run "
                ".\\runtime\\bootstrap.ps1 -WithM02"
            )
        required = {"requested", "executable", "depot", "project"}
        if not required.issubset(julia):
            raise JuliaResponseBackendError(
                "M02 Julia runtime receipt predates the precision worker; rerun "
                ".\\runtime\\bootstrap.ps1 -WithM02"
            )
        executable = _regular_file(
            Path(str(julia["executable"])), "M02 Julia executable"
        )
        project = Path(str(julia["project"]))
        project_file = _regular_file(project / "Project.toml", "M02 Julia project")
        manifest = _regular_file(project / "Manifest.toml", "M02 Julia manifest")
        declared_worker = julia.get("worker")
        worker = _regular_file(
            (
                Path(str(declared_worker))
                if isinstance(declared_worker, str) and declared_worker
                else Path(__file__).resolve().parent / "data" / "julia" / "m02_worker.jl"
            ),
            "M02 Julia worker",
        )
        depot = Path(str(julia["depot"]))
        if not depot.is_dir() or depot.is_symlink():
            raise JuliaResponseBackendError(f"M02 Julia depot is invalid: {depot}")
        observed_executable_sha256 = _sha256(executable)
        observed_manifest_sha256 = _sha256(manifest)
        observed_worker_sha256 = _sha256(worker)
        for key, observed, label in (
            ("executable_sha256", observed_executable_sha256, "executable"),
            ("manifest_sha256", observed_manifest_sha256, "manifest"),
            ("worker_sha256", observed_worker_sha256, "worker"),
        ):
            declared = julia.get(key)
            if declared is not None and (
                not isinstance(declared, str) or declared != observed
            ):
                raise JuliaResponseBackendError(
                    f"M02 Julia {label} receipt digest does not match the installed runtime"
                )
        declared_arguments = julia.get("arguments", [])
        if (
            not isinstance(declared_arguments, list)
            or any(not isinstance(item, str) or not item for item in declared_arguments)
        ):
            raise JuliaResponseBackendError(
                "M02 Julia runtime invocation arguments are invalid"
            )
        provenance = {
            "julia_version": julia.get("version", "unrecorded"),
            "julia_executable_sha256": observed_executable_sha256,
            "julia_arguments": list(declared_arguments),
            "julia_manifest_sha256": observed_manifest_sha256,
            "worker_sha256": observed_worker_sha256,
            "runtime_policy_sha256": receipt.get("policy_sha256"),
            "scientific_sources": list(julia.get("sources", ())),
        }
        return cls(
            executable,
            project_file.parent,
            depot.resolve(),
            worker,
            provenance,
            runner,
            tuple(declared_arguments),
        )

    def evaluate(self, request: Mapping[str, object]) -> dict[str, object]:
        request_sha256 = hashlib.sha256(canonical_json_bytes(request)).hexdigest()
        document = dict(request)
        document["request_sha256"] = request_sha256
        timeout_text = os.environ.get("KERR_QNM_JULIA_REQUEST_TIMEOUT_SECONDS", "7200")
        try:
            timeout = int(timeout_text)
        except ValueError as error:
            raise JuliaResponseBackendError(
                "KERR_QNM_JULIA_REQUEST_TIMEOUT_SECONDS must be an integer"
            ) from error
        if timeout < 60:
            raise JuliaResponseBackendError(
                "KERR_QNM_JULIA_REQUEST_TIMEOUT_SECONDS must be at least 60"
            )
        with tempfile.TemporaryDirectory(prefix="m02-julia-readout-") as temporary:
            directory = Path(temporary)
            request_path = directory / "request.json"
            response_path = directory / "response.json"
            request_path.write_bytes(canonical_json_bytes(document))
            environment = os.environ.copy()
            environment["JULIA_DEPOT_PATH"] = str(self.julia_depot)
            environment["JULIA_PKG_OFFLINE"] = "true"
            environment["KERR_QNM_PROGRESS"] = "1"
            command = (
                    str(self.julia_executable),
                    *self.julia_prefix_arguments,
                    "--startup-file=no",
                    "--history-file=no",
                    f"--project={self.julia_project}",
                    str(self.worker_script),
                    str(request_path),
                    str(response_path),
                )
            if self.runner is subprocess.run:
                completed = _run_streamed_julia(
                    command, cwd=directory, env=environment, timeout=timeout
                )
            else:
                completed = self.runner(
                    command,
                    cwd=directory,
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=timeout,
                )
            returncode = getattr(completed, "returncode", None)
            if returncode != 0:
                _raise_worker_failure(_worker_failure_details(
                    completed, response_path
                ))
            response = _strict_json_file(response_path, "M02 Julia response")
        if response.get("status") != "ok":
            _raise_worker_failure(_worker_failure_details(
                completed, response_path, response=response
            ))
        if response.get("request_sha256") != request_sha256:
            raise JuliaResponseBackendError("M02 Julia response request digest mismatch")
        return response


def _precision_policy(job: ResponseComponentJob, digits: int, refinement: int) -> dict[str, object]:
    if digits not in _PROMOTED_DIGITS:
        raise ValueError("Julia response precision must be 80 or 120 digits")
    if refinement not in (0, 1):
        raise ValueError("Julia response refinement level must be zero or one")
    effective = digits - (18 if refinement == 0 else 14)
    return {
        "readout_radius": format(job.policy.readout_radius, ".17g"),
        "ode_relative_tolerance": f"1e-{effective}",
        "ode_absolute_tolerance": f"1e-{effective + 2}",
        "endpoint_series_order": job.policy.endpoint_series_order + 8 * refinement,
        "support_subinterval_count": job.policy.support_subinterval_count * (2 ** refinement),
        "angular_pad": 18 + 8 * refinement,
        "rho_in": "-5000",
        "rho_out": "5000",
        "frequency_step": f"1e-{max(24, digits // 2)}",
        "root_tolerance": f"1e-{effective}",
        "max_newton_iterations": 16,
    }


@dataclass(slots=True)
class JuliaPrecisionRootBackend:
    """Root-readout adapter consumed by the existing component engine."""

    identity: BackendIdentity
    adapter: JuliaResponseAdapter
    digits: int
    refinement: int = 0

    def __post_init__(self) -> None:
        if self.digits not in _PROMOTED_DIGITS:
            raise ValueError("Julia precision backend requires 80 or 120 digits")
        if self.refinement not in (0, 1):
            raise ValueError("Julia precision refinement level is invalid")

    @property
    def scientific_runtime(self) -> dict[str, object]:
        return {
            **dict(self.adapter.runtime_provenance),
            "precision_digits": self.digits,
            "working_precision_bits": math.ceil(self.digits * math.log2(10)) + 32,
            "refinement_level": self.refinement,
        }

    def _request(
        self,
        job: ResponseComponentJob,
        amplitude: complex,
        primary_predictor: complex | None = None,
        primary_predictor_kind: str | None = None,
    ) -> dict[str, object]:
        request: dict[str, object] = {
            "schema_version": 1,
            "operation": "root-readout",
            "mode": {
                "s": job.mode.s,
                "ell": job.mode.ell,
                "m": job.mode.m,
                "n": job.mode.n,
            },
            "spin": format(job.spin, ".17g"),
            "omega": {
                "real": format(job.root.omega.real, ".17g"),
                "imaginary": format(job.root.omega.imag, ".17g"),
            },
            "angular_A": {
                "real": format(job.root.angular_separation_constant.real, ".17g"),
                "imaginary": format(job.root.angular_separation_constant.imag, ".17g"),
            },
            "mechanism_id": job.mechanism_id,
            "amplitude": {
                "real": format(complex(amplitude).real, ".17g"),
                "imaginary": format(complex(amplitude).imag, ".17g"),
            },
            "precision_digits": self.digits,
            "working_precision_bits": math.ceil(self.digits * math.log2(10)) + 32,
            "policy": _precision_policy(job, self.digits, self.refinement),
        }
        if primary_predictor is not None:
            predictor = complex(primary_predictor)
            if math.isfinite(predictor.real) and math.isfinite(predictor.imag):
                request["primary_predictor"] = {
                    "real": format(predictor.real, ".17g"),
                    "imaginary": format(predictor.imag, ".17g"),
                }
                if primary_predictor_kind is not None:
                    if primary_predictor_kind not in {
                        "EPSILON_CONTINUATION",
                        "SPIN_CONTINUATION",
                    }:
                        raise ValueError("primary predictor kind is invalid")
                    request["primary_predictor_kind"] = primary_predictor_kind
        if job.mechanism_id != "horizon-admittance":
            support = _exterior_support(job.spin, job.mechanism_id)
            request["support"] = {
                name: format(value, ".17g")
                for name, value in support.to_mapping().items()
            }
        return request

    def read_root(
        self,
        job: ResponseComponentJob,
        amplitude: complex,
        primary_predictor: complex | None = None,
    ) -> RootReadout:
        return self._read_root(
            job, amplitude, primary_predictor, primary_predictor_kind=None
        )

    def read_root_with_predictor_kind(
        self,
        job: ResponseComponentJob,
        amplitude: complex,
        primary_predictor: complex,
        primary_predictor_kind: str,
    ) -> RootReadout:
        return self._read_root(
            job,
            amplitude,
            primary_predictor,
            primary_predictor_kind=primary_predictor_kind,
        )

    def _read_root(
        self,
        job: ResponseComponentJob,
        amplitude: complex,
        primary_predictor: complex | None,
        *,
        primary_predictor_kind: str | None,
    ) -> RootReadout:
        if job.backend_identity != self.identity:
            raise ValueError("response job backend identity does not match Julia adapter")
        response = self.adapter.evaluate(
            self._request(
                job,
                complex(amplitude),
                primary_predictor,
                primary_predictor_kind,
            )
        )
        expected_fields = {
            "schema_version",
            "status",
            "adapter",
            "request_sha256",
            "precision_digits",
            "working_precision_bits",
            "root_omega_re",
            "root_omega_im",
            "root_residual_abs",
            "root_derivative_abs",
            "root_converged",
            "branch_authentication_contract_version",
            "root_branch_continuation_valid",
            "branch_tolerance_abs",
            "root_displacement_abs",
            "truncation_radius_abs",
            "resolution_radius_abs",
            "seed_path_radius_abs",
        }
        if set(response) != expected_fields:
            raise JuliaResponseBackendError("M02 Julia response fields are invalid")
        if (
            response["schema_version"] != 1
            or response["adapter"] != "package-owned-julia-gsn-root-readout"
            or response["precision_digits"] != self.digits
            or response["working_precision_bits"]
            != math.ceil(self.digits * math.log2(10)) + 32
            or not isinstance(response["root_converged"], bool)
            or response["branch_authentication_contract_version"] != 2
            or not isinstance(response["root_branch_continuation_valid"], bool)
            or (
                response["root_converged"]
                and not response["root_branch_continuation_valid"]
            )
        ):
            raise JuliaResponseBackendError("M02 Julia response contract is invalid")
        converged = response["root_converged"]
        branch_continuation_valid = response[
            "root_branch_continuation_valid"
        ]
        branch_tolerance_decimal = _finite_decimal_text(
            response["branch_tolerance_abs"],
            "branch_tolerance_abs",
            nonnegative=True,
        )
        root_real_decimal = _finite_decimal_text(
            response["root_omega_re"], "root_omega_re"
        )
        root_imaginary_decimal = _finite_decimal_text(
            response["root_omega_im"], "root_omega_im"
        )
        root_displacement_decimal = _finite_decimal_text(
            response["root_displacement_abs"],
            "root_displacement_abs",
            nonnegative=True,
        )
        diagnostic_radii_decimal = (
            _finite_decimal_text(
                response["truncation_radius_abs"],
                "truncation_radius_abs",
                nonnegative=True,
            ),
            _finite_decimal_text(
                response["resolution_radius_abs"],
                "resolution_radius_abs",
                nonnegative=True,
            ),
            _finite_decimal_text(
                response["seed_path_radius_abs"],
                "seed_path_radius_abs",
                nonnegative=True,
            ),
        )
        with localcontext() as context:
            context.prec = self.digits + 64
            delta_real = root_real_decimal - Decimal(
                format(job.root.omega.real, ".17g")
            )
            delta_imaginary = root_imaginary_decimal - Decimal(
                format(job.root.omega.imag, ".17g")
            )
            derived_displacement = (
                delta_real * delta_real + delta_imaginary * delta_imaginary
            ).sqrt()
            # The worker has at least ``digits`` significant decimal digits;
            # this bound allows only its final serialized decimal place.
            serialization_allowance = Decimal(1).scaleb(-self.digits)
            inconsistent_branch_evidence = (
                abs(branch_tolerance_decimal - _BRANCH_TOLERANCE_DECIMAL)
                > serialization_allowance
                or abs(derived_displacement - root_displacement_decimal)
                > serialization_allowance
                or branch_continuation_valid
                != (
                    derived_displacement <= branch_tolerance_decimal
                    and all(
                        radius <= branch_tolerance_decimal
                        for radius in diagnostic_radii_decimal
                    )
                )
            )
            if inconsistent_branch_evidence:
                raise JuliaResponseBackendError(
                    "M02 Julia branch-continuation evidence is inconsistent"
                )
        root = complex(
            _finite_text(response["root_omega_re"], "root_omega_re"),
            _finite_text(response["root_omega_im"], "root_omega_im"),
        )
        truncation_radius = _finite_text(
            response["truncation_radius_abs"], "truncation_radius_abs"
        )
        resolution_radius = _finite_text(
            response["resolution_radius_abs"], "resolution_radius_abs"
        )
        seed_path_radius = _finite_text(
            response["seed_path_radius_abs"], "seed_path_radius_abs"
        )
        return RootReadout(
            omega=root,
            determinant_residual_abs=_finite_text(
                response["root_residual_abs"], "root_residual_abs"
            ),
            determinant_derivative_abs=_finite_text(
                response["root_derivative_abs"], "root_derivative_abs"
            ),
            converged=converged,
            root_reference_id=job.root.root_reference_id,
            branch_id=(
                job.root.branch_id
                if branch_continuation_valid
                else "nonmatching-julia-continuation"
            ),
            equation_id=job.equation_id,
            truncation_radius=truncation_radius,
            resolution_radius=resolution_radius,
            seed_path_radius=seed_path_radius,
        )

    def closed_form_horizon_response(
        self, job: ResponseComponentJob
    ) -> complex | None:
        if job.backend_identity != self.identity:
            raise ValueError("response job backend identity does not match Julia adapter")
        return None
