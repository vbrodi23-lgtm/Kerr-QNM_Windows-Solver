"""Authenticated Python boundary for the package-owned Julia precision worker.

The worker performs only promoted 80/120-decimal-digit root readouts.  The
existing Python response engine still owns the signed-amplitude ladder,
component reduction, error ledger, checkpoints, resume, and admission schema.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Callable, Mapping

from .contracts import canonical_json_bytes
from .response_engine import (
    BackendIdentity,
    ResponseComponentJob,
    RootReadout,
    _exterior_support,
)


_PROMOTED_DIGITS = frozenset({80, 120})


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


def _finite_text(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise JuliaResponseBackendError(f"Julia response {label} is not numeric")
    converted = float(value)
    if not math.isfinite(converted):
        raise JuliaResponseBackendError(f"Julia response {label} is not finite")
    return converted


def _runtime_root() -> Path:
    override = os.environ.get("KERR_QNM_RUNTIME_ROOT")
    return Path(override) if override else Path.cwd() / ".runtime"


@dataclass(frozen=True, slots=True)
class JuliaResponseAdapter:
    julia_executable: Path
    julia_project: Path
    julia_depot: Path
    worker_script: Path
    runtime_provenance: Mapping[str, object]
    runner: Callable[..., object] = subprocess.run

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
            Path(str(julia["executable"])), "package-local Julia executable"
        )
        project = Path(str(julia["project"]))
        project_file = _regular_file(project / "Project.toml", "M02 Julia project")
        manifest = _regular_file(project / "Manifest.toml", "M02 Julia manifest")
        worker = _regular_file(
            Path(__file__).resolve().parent / "data" / "julia" / "m02_worker.jl",
            "package-owned M02 Julia worker",
        )
        depot = Path(str(julia["depot"]))
        if not depot.is_dir() or depot.is_symlink():
            raise JuliaResponseBackendError(f"M02 Julia depot is invalid: {depot}")
        provenance = {
            "julia_version": julia.get("version", "unrecorded"),
            "julia_executable_sha256": _sha256(executable),
            "julia_manifest_sha256": _sha256(manifest),
            "worker_sha256": _sha256(worker),
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
            completed = self.runner(
                (
                    str(self.julia_executable),
                    "--startup-file=no",
                    "--history-file=no",
                    f"--project={self.julia_project}",
                    str(self.worker_script),
                    str(request_path),
                    str(response_path),
                ),
                cwd=directory,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
            returncode = getattr(completed, "returncode", None)
            if returncode != 0:
                stderr = str(getattr(completed, "stderr", ""))[-4000:]
                raise JuliaResponseBackendError(
                    f"M02 Julia worker failed with code {returncode}: {stderr}"
                )
            response = _strict_json_file(response_path, "M02 Julia response")
        if response.get("status") != "ok":
            raise JuliaResponseBackendError(
                f"M02 Julia worker rejected the request: {response.get('message')}"
            )
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

    def _request(self, job: ResponseComponentJob, amplitude: complex) -> dict[str, object]:
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
        if job.mechanism_id != "horizon-admittance":
            support = _exterior_support(job.spin, job.mechanism_id)
            request["support"] = {
                name: format(value, ".17g")
                for name, value in support.to_mapping().items()
            }
        return request

    def read_root(self, job: ResponseComponentJob, amplitude: complex) -> RootReadout:
        if job.backend_identity != self.identity:
            raise ValueError("response job backend identity does not match Julia adapter")
        response = self.adapter.evaluate(self._request(job, complex(amplitude)))
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
        ):
            raise JuliaResponseBackendError("M02 Julia response contract is invalid")
        converged = response["root_converged"]
        return RootReadout(
            omega=complex(
                _finite_text(response["root_omega_re"], "root_omega_re"),
                _finite_text(response["root_omega_im"], "root_omega_im"),
            ),
            determinant_residual_abs=_finite_text(
                response["root_residual_abs"], "root_residual_abs"
            ),
            determinant_derivative_abs=_finite_text(
                response["root_derivative_abs"], "root_derivative_abs"
            ),
            converged=converged,
            root_reference_id=job.root.root_reference_id,
            branch_id=(
                job.root.branch_id if converged else "nonmatching-julia-continuation"
            ),
            equation_id=job.equation_id,
            truncation_radius=_finite_text(
                response["truncation_radius_abs"], "truncation_radius_abs"
            ),
            resolution_radius=_finite_text(
                response["resolution_radius_abs"], "resolution_radius_abs"
            ),
            seed_path_radius=_finite_text(
                response["seed_path_radius_abs"], "seed_path_radius_abs"
            ),
        )

    def closed_form_horizon_response(
        self, job: ResponseComponentJob
    ) -> complex | None:
        if job.backend_identity != self.identity:
            raise ValueError("response job backend identity does not match Julia adapter")
        return None
