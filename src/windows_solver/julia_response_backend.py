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
import signal
import subprocess
import sys
import tempfile
from threading import Event, Thread
import time
from types import SimpleNamespace
from typing import Callable, Mapping

from .contracts import canonical_json_bytes
from .response_engine import (
    BackendIdentity,
    DiagnosticRootReadout,
    NumericalConditioningEvidence,
    NUMERICAL_CONDITIONING_SCHEMA,
    ResponseComponentJob,
    RootAuthenticationEvidence,
    RootReadout,
    WORKER_RESPONSE_RECEIPT_SCHEMA,
    _exterior_support,
    mode_specific_branch_enclosure_radius,
    regularised_gsn_mechanism_contract,
    regularised_gsn_precision_policy,
)
from .progress import (
    PROGRESS_SCHEMA,
    ProgressEventKind,
    current_progress_context,
    emit_progress,
    ingest_external_progress,
)
from .root_readout_cache import (
    ROOT_READOUT_STORE_DIRECTORY_NAME,
    RootReadoutLookupStatus,
    RootReadoutStore,
    runtime_identity_sha256,
)


_PROMOTED_DIGITS = frozenset({80, 120})
JULIA_PROGRESS_PREFIX = "@@KERR_QNM_PROGRESS@@"
_WORKER_HEARTBEAT_SECONDS = 2.0
_PROCESS_REAP_SECONDS = 10.0
_IS_WINDOWS = os.name == "nt"
_CREATE_NEW_PROCESS_GROUP = getattr(
    subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200
)
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
_WINDOWS_JOB_START_TOKEN = "G"
_WINDOWS_JOB_BOOTSTRAP = (
    "import subprocess,sys; "
    "token=sys.stdin.read(1); "
    "sys.exit(125 if token != 'G' else subprocess.run(sys.argv[1:]).returncode)"
)
_EXECUTION_RESOURCE_SCHEMA = "windows-solver.execution-resource-policy/1"
_EXECUTION_RESOURCE_VERSION = 1
_DEFAULT_REQUEST_TIMEOUT_SECONDS = 7200
_DEFAULT_COOPERATIVE_MARGIN_SECONDS = 120
_DEFAULT_HOMOGENEOUS_ODE_MAXITERS = 10_000_000
_DEFAULT_HOMOGENEOUS_MAX_ACCEPTED_STEPS = 1_000_000
_DEFAULT_HOMOGENEOUS_MAX_RHS_EVALUATIONS = 2_000_000
_DEFAULT_COORDINATE_STALL_RHS_THRESHOLD = 200_000
_DEFAULT_COORDINATE_STALL_MINIMUM_SPAN_FRACTION = "1e-6"
_DEFAULT_COORDINATE_STALL_MINIMUM_STEP_FRACTION = "1e-12"
NUMERICAL_CONTROL_FAILURE_CODES = frozenset({
    "SCATTERING_BASIS_ILL_CONDITIONED",
    "SCATTERING_CHART_ILL_CONDITIONED",
    "ASYMPTOTIC_SERIES_INVALID",
    "INSUFFICIENT_ASYMPTOTIC_PRECISION",
    "PHYSICAL_SINGULAR_LIMIT",
    "ALGEBRAIC_REPRESENTATION_SINGULAR",
    "CARRIER_CHANGE_INCONSISTENT",
    "INVALID_FACTORED_PROPAGATION_INPUT",
    "FACTORED_PROPAGATION_PRECISION_MISMATCH",
    "NONFINITE_FACTORED_PROPAGATION_DATA",
    "FACTORED_ODE_FAILURE",
    # Fewer than two horizon endpoints passed the radial-approach and
    # dual-series gate. Raised before any homogeneous ODE starts.
    "NO_VERIFIED_HORIZON_ENDPOINT",
    # The coordinate map made no meaningful progress. Distinguishes an
    # impossible local-error target from an exhausted resource budget.
    "COORDINATE_INVERSION_STALLED",
    # The central determinant is small but its absolute error is too large to
    # call the root located. Never reported as a solved root.
    "DETERMINANT_UNCERTAINTY_TOO_LARGE",
    # The finite-difference ladder was exhausted without a step at which the
    # derivative estimates agree and determinant noise does not dominate.
    "FINITE_DIFFERENCE_NOISE_LIMIT",
})


def _mode_specific_branch_enclosure_radius(
    job: ResponseComponentJob,
) -> float:
    return mode_specific_branch_enclosure_radius(job.root)


class JuliaResponseBackendError(RuntimeError):
    """The package-owned Julia precision worker is unavailable or rejected work."""


class JuliaProgressProtocolError(JuliaResponseBackendError):
    """A reserved Julia progress record violated its authenticated protocol."""


class JuliaWorkerTimeoutError(JuliaResponseBackendError):
    """The Julia worker exceeded the request wall-clock timeout."""


class JuliaODEResourceLimitError(JuliaResponseBackendError):
    """The Julia worker reported an existing ODE solver resource limit."""


class JuliaRootReadoutResourceLimitError(JuliaResponseBackendError):
    """The Julia worker proved mandatory root-readout work cannot fit."""


class JuliaNumericalControlError(JuliaResponseBackendError):
    """The worker stopped at one recognized, bounded numerical-control gate."""

    def __init__(self, message: str, failure_code: str) -> None:
        if failure_code not in NUMERICAL_CONTROL_FAILURE_CODES:
            raise ValueError("numerical-control failure code is not recognized")
        super().__init__(message)
        self.failure_code = failure_code


def _positive_environment_integer(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as error:
        raise JuliaResponseBackendError(f"{name} must be an integer") from error
    if value < 1:
        raise JuliaResponseBackendError(f"{name} must be positive")
    return value


def _optional_positive_environment_integer(name: str) -> int | None:
    raw = os.environ.get(name)
    if raw is None or not raw.strip() or raw.strip() == "0":
        return None
    try:
        value = int(raw)
    except ValueError as error:
        raise JuliaResponseBackendError(
            f"{name} must be an integer or zero"
        ) from error
    if value < 1:
        raise JuliaResponseBackendError(f"{name} must be positive or zero")
    return value


def _execution_resource_policy() -> dict[str, object]:
    """Build one versioned operational policy, separate from scientific identity."""

    timeout = _positive_environment_integer(
        "KERR_QNM_JULIA_REQUEST_TIMEOUT_SECONDS",
        _DEFAULT_REQUEST_TIMEOUT_SECONDS,
    )
    if timeout < 60:
        raise JuliaResponseBackendError(
            "KERR_QNM_JULIA_REQUEST_TIMEOUT_SECONDS must be at least 60"
        )
    default_margin = min(
        _DEFAULT_COOPERATIVE_MARGIN_SECONDS,
        max(1, timeout // 20),
    )
    margin = _positive_environment_integer(
        "KERR_QNM_JULIA_COOPERATIVE_DEADLINE_MARGIN_SECONDS",
        default_margin,
    )
    if margin >= timeout:
        raise JuliaResponseBackendError(
            "KERR_QNM_JULIA_COOPERATIVE_DEADLINE_MARGIN_SECONDS must be "
            "smaller than the request timeout"
        )
    material: dict[str, object] = {
        "schema": _EXECUTION_RESOURCE_SCHEMA,
        "version": _EXECUTION_RESOURCE_VERSION,
        "worker_request_wall_clock_seconds": timeout,
        "cooperative_request_deadline_seconds": timeout - margin,
        "homogeneous_ode_maxiters": _positive_environment_integer(
            "KERR_QNM_JULIA_HOMOGENEOUS_ODE_MAXITERS",
            _DEFAULT_HOMOGENEOUS_ODE_MAXITERS,
        ),
        "max_accepted_steps_per_homogeneous_leg": _positive_environment_integer(
            "KERR_QNM_JULIA_ODE_MAX_ACCEPTED_STEPS",
            _DEFAULT_HOMOGENEOUS_MAX_ACCEPTED_STEPS,
        ),
        "max_rhs_evaluations_per_homogeneous_leg": _positive_environment_integer(
            "KERR_QNM_JULIA_ODE_MAX_RHS_EVALUATIONS",
            _DEFAULT_HOMOGENEOUS_MAX_RHS_EVALUATIONS,
        ),
        "homogeneous_leg_wall_clock_seconds": (
            _optional_positive_environment_integer(
                "KERR_QNM_JULIA_HOMOGENEOUS_LEG_TIMEOUT_SECONDS"
            )
        ),
        # Coordinate-inversion stall detection. The threshold is generous
        # relative to a healthy coordinate solve (2,978 RHS evaluations for the
        # exact 80-digit Leaf 13 positive leg) but far below the 2,000,002 the
        # stalled run consumed, so a pathological map is named rather than
        # allowed to spend the whole budget proving the same point.
        "coordinate_stall_rhs_threshold": _positive_environment_integer(
            "KERR_QNM_JULIA_COORDINATE_STALL_RHS_THRESHOLD",
            _DEFAULT_COORDINATE_STALL_RHS_THRESHOLD,
        ),
        "coordinate_stall_minimum_span_fraction": (
            _DEFAULT_COORDINATE_STALL_MINIMUM_SPAN_FRACTION
        ),
        "coordinate_stall_minimum_step_fraction": (
            _DEFAULT_COORDINATE_STALL_MINIMUM_STEP_FRACTION
        ),
    }
    return {
        **material,
        "sha256": hashlib.sha256(canonical_json_bytes(material)).hexdigest(),
    }


def _validated_execution_resource_policy(value: object) -> dict[str, object]:
    expected = {
        "schema",
        "version",
        "worker_request_wall_clock_seconds",
        "cooperative_request_deadline_seconds",
        "homogeneous_ode_maxiters",
        "max_accepted_steps_per_homogeneous_leg",
        "max_rhs_evaluations_per_homogeneous_leg",
        "homogeneous_leg_wall_clock_seconds",
        "coordinate_stall_rhs_threshold",
        "coordinate_stall_minimum_span_fraction",
        "coordinate_stall_minimum_step_fraction",
        "sha256",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise JuliaResponseBackendError("execution-resource policy fields are invalid")
    copied = dict(value)
    if (
        copied["schema"] != _EXECUTION_RESOURCE_SCHEMA
        or copied["version"] != _EXECUTION_RESOURCE_VERSION
    ):
        raise JuliaResponseBackendError("execution-resource policy version is invalid")
    for name in (
        "worker_request_wall_clock_seconds",
        "cooperative_request_deadline_seconds",
        "homogeneous_ode_maxiters",
        "max_accepted_steps_per_homogeneous_leg",
        "max_rhs_evaluations_per_homogeneous_leg",
        "coordinate_stall_rhs_threshold",
    ):
        item = copied[name]
        if isinstance(item, bool) or not isinstance(item, int) or item < 1:
            raise JuliaResponseBackendError(
                f"execution-resource policy {name} is invalid"
            )
    for name in (
        "coordinate_stall_minimum_span_fraction",
        "coordinate_stall_minimum_step_fraction",
    ):
        item = copied[name]
        if not isinstance(item, str):
            raise JuliaResponseBackendError(
                f"execution-resource policy {name} is invalid"
            )
        try:
            fraction = float(item)
        except ValueError as error:
            raise JuliaResponseBackendError(
                f"execution-resource policy {name} is invalid"
            ) from error
        if not 0.0 < fraction < 1.0:
            raise JuliaResponseBackendError(
                f"execution-resource policy {name} is invalid"
            )
    if (
        copied["coordinate_stall_rhs_threshold"]
        >= copied["max_rhs_evaluations_per_homogeneous_leg"]
    ):
        raise JuliaResponseBackendError(
            "coordinate stall threshold must fire before the RHS ceiling"
        )
    leg_timeout = copied["homogeneous_leg_wall_clock_seconds"]
    if leg_timeout is not None and (
        isinstance(leg_timeout, bool)
        or not isinstance(leg_timeout, int)
        or leg_timeout < 1
    ):
        raise JuliaResponseBackendError(
            "execution-resource policy homogeneous leg timeout is invalid"
        )
    if (
        copied["worker_request_wall_clock_seconds"] < 60
        or copied["cooperative_request_deadline_seconds"]
        >= copied["worker_request_wall_clock_seconds"]
    ):
        raise JuliaResponseBackendError("execution-resource deadlines are invalid")
    material = {key: item for key, item in copied.items() if key != "sha256"}
    expected_sha = hashlib.sha256(canonical_json_bytes(material)).hexdigest()
    if copied["sha256"] != expected_sha:
        raise JuliaResponseBackendError("execution-resource policy digest is invalid")
    return copied


class _WindowsKillOnCloseJob:
    """Own one Windows worker tree until every request pipe has drained."""

    def __init__(self, handle: object, kernel32: object) -> None:
        self._handle = handle
        self._kernel32 = kernel32

    @classmethod
    def create(cls) -> "_WindowsKillOnCloseJob":
        import ctypes
        from ctypes import wintypes

        class BasicLimitInformation(ctypes.Structure):
            _fields_ = (
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            )

        class IoCounters(ctypes.Structure):
            _fields_ = tuple(
                (name, ctypes.c_ulonglong)
                for name in (
                    "ReadOperationCount",
                    "WriteOperationCount",
                    "OtherOperationCount",
                    "ReadTransferCount",
                    "WriteTransferCount",
                    "OtherTransferCount",
                )
            )

        class ExtendedLimitInformation(ctypes.Structure):
            _fields_ = (
                ("BasicLimitInformation", BasicLimitInformation),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            )

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        )
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = (
            wintypes.HANDLE,
            wintypes.HANDLE,
        )
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        job = cls(handle, kernel32)
        information = ExtendedLimitInformation()
        information.BasicLimitInformation.LimitFlags = (
            _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        if not kernel32.SetInformationJobObject(
            handle,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
            ctypes.byref(information),
            ctypes.sizeof(information),
        ):
            error = ctypes.WinError(ctypes.get_last_error())
            job.close()
            raise error
        return job

    def assign(self, process: subprocess.Popen[str]) -> None:
        import ctypes
        from ctypes import wintypes

        process_handle = getattr(process, "_handle", None)
        if process_handle is None or not self._kernel32.AssignProcessToJobObject(
            self._handle, wintypes.HANDLE(int(process_handle))
        ):
            raise ctypes.WinError(ctypes.get_last_error())

    def terminate(self) -> None:
        """Kill every process still associated with the job, then close it."""

        handle = self._handle
        if handle is None:
            return
        try:
            self._kernel32.TerminateJobObject(handle, 1)
        finally:
            self.close()

    def close(self) -> None:
        handle = self._handle
        if handle is None:
            return
        self._handle = None
        self._kernel32.CloseHandle(handle)


def promoted_precision_numerical_controls() -> dict[str, object]:
    """Return the calibrated root/ODE/derivative controls for promoted tiers.

    The scientific root target is a property of the physics, not of the
    arithmetic: 1e-18 at base and 1e-20 at refinement, for **both** the 80- and
    120-digit tiers. Through ``required_reliable_digits`` those correspond to 24
    and 26 required reliable digits.

    The previous table derived the 120-digit controls mechanically from the
    stored digit count (``10**-(digits - 18)``), which demanded a 1e-102 root
    target -- hence 108 required reliable digits -- and applied that same
    tolerance to the coordinate map. That is what pinned Leaf 13's coordinate
    solve at 8.1e-17 steps: 2,000,002 RHS evaluations and 87.8 s to cover
    1.01e-11 of a 5000 span. More stored digits do not make a QNM root more
    accurately defined; they buy guard precision against cancellation, carrier
    changes, and finite differencing.

    So the 120-digit tier keeps the same scientific target as the 80-digit tier
    and spends its extra digits as guard: its ODE controls are tightened by a
    bounded factor over the demonstrated-healthy 80-digit level (1e-18 / 1e-20
    homogeneous, reached in 2,978 RHS evaluations on the exact Leaf 13 leg),
    not driven to the arithmetic floor.

    The coordinate map gets its own, looser controls. It is a scalar quadrature
    for r(rho) and only has to avoid dominating the determinant error budget;
    it does not need the homogeneous solve's local-error target.

    These values are the starting profile. They are not a second guessed table:
    ``tools/calibrate_leaf13_horizon_controls.jl`` measures the determinant
    response to each control and the selected profile is committed with its
    calibration receipt.
    """

    return {
        "80": {
            "base": {
                "root_correction_tolerance": "1e-18",
                "ode_relative_tolerance": "1e-18",
                "ode_absolute_tolerance": "1e-20",
                "homogeneous_ode_relative_tolerance": "1e-18",
                "homogeneous_ode_absolute_tolerance": "1e-20",
                "coordinate_ode_relative_tolerance": "1e-18",
                "coordinate_ode_absolute_tolerance": "1e-20",
                "frequency_step": "1e-6",
                "frequency_step_minimum": "1e-12",
                "frequency_step_maximum": "1e-3",
            },
            "refinement": {
                "root_correction_tolerance": "1e-20",
                "ode_relative_tolerance": "1e-20",
                "ode_absolute_tolerance": "1e-20",
                "homogeneous_ode_relative_tolerance": "1e-22",
                "homogeneous_ode_absolute_tolerance": "1e-24",
                "coordinate_ode_relative_tolerance": "1e-20",
                "coordinate_ode_absolute_tolerance": "1e-22",
                "frequency_step": "1e-7",
                "frequency_step_minimum": "1e-14",
                "frequency_step_maximum": "1e-4",
            },
        },
        "120": {
            "base": {
                "root_correction_tolerance": "1e-18",
                "ode_relative_tolerance": "1e-24",
                "ode_absolute_tolerance": "1e-26",
                "homogeneous_ode_relative_tolerance": "1e-24",
                "homogeneous_ode_absolute_tolerance": "1e-26",
                "coordinate_ode_relative_tolerance": "1e-20",
                "coordinate_ode_absolute_tolerance": "1e-22",
                "frequency_step": "1e-6",
                "frequency_step_minimum": "1e-16",
                "frequency_step_maximum": "1e-3",
            },
            "refinement": {
                "root_correction_tolerance": "1e-20",
                "ode_relative_tolerance": "1e-28",
                "ode_absolute_tolerance": "1e-30",
                "homogeneous_ode_relative_tolerance": "1e-28",
                "homogeneous_ode_absolute_tolerance": "1e-30",
                "coordinate_ode_relative_tolerance": "1e-22",
                "coordinate_ode_absolute_tolerance": "1e-24",
                "frequency_step": "1e-7",
                "frequency_step_minimum": "1e-18",
                "frequency_step_maximum": "1e-4",
            },
        },
    }


def horizon_geometry_controls() -> dict[str, object]:
    """Return the real-inner horizon endpoint gate configuration.

    The candidate ladder is bounded and shallow on purpose. The prototype
    reached 80.92/81.13 reliable digits at rho = -50 against 35.99/37.28 at
    rho = -25, so useful endpoints live within tens of units of the matching
    point, not thousands. ``horizon_rho_inner_min`` therefore bounds the
    coordinate map at -100 rather than -5000.
    """

    return {
        "horizon_rho_inner_min": "-100",
        "horizon_endpoint_rho_candidates": [
            "-10", "-25", "-50", "-75", "-100",
        ],
        "horizon_maximum_endpoint_distance": "0.1",
        "determinant_error_safety_factor": "64",
    }


def _forward_julia_progress_line(
    line: str,
    *,
    capture: list[dict[str, object]] | None = None,
) -> bool:
    """Forward one reserved worker event; return whether the line was reserved."""

    if not line.startswith(JULIA_PROGRESS_PREFIX):
        return False
    try:
        value = json.loads(line[len(JULIA_PROGRESS_PREFIX):])
        ingest_external_progress(value)
        if capture is not None:
            assert isinstance(value, dict)
            capture[:] = [value]
    except Exception as error:
        emit_progress(
            ProgressEventKind.ERROR,
            source="julia-progress",
            error_type=type(error).__name__,
            message=str(error),
        )
        raise JuliaProgressProtocolError(
            "Julia worker emitted malformed reserved progress"
        ) from error
    return True


def _terminate_process_tree(
    process: subprocess.Popen[str],
    windows_job: _WindowsKillOnCloseJob | None = None,
) -> None:
    """Force-stop the isolated worker tree and reap its direct process."""

    if _IS_WINDOWS:
        if windows_job is not None:
            windows_job.terminate()
        else:
            try:
                completed = subprocess.run(
                    ("taskkill", "/PID", str(process.pid), "/T", "/F"),
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=_PROCESS_REAP_SECONDS,
                )
                if completed.returncode != 0 and process.poll() is None:
                    process.kill()
            except (OSError, subprocess.SubprocessError):
                if process.poll() is None:
                    process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError:
            if process.poll() is None:
                process.kill()
    try:
        process.wait(timeout=_PROCESS_REAP_SECONDS)
    except subprocess.TimeoutExpired:
        if process.poll() is None:
            process.kill()
        process.wait()
    except (ChildProcessError, OSError):
        pass


def _run_streamed_julia(
    command: tuple[str, ...], *, cwd: Path, env: Mapping[str, str], timeout: int
) -> object:
    """Drain worker pipes concurrently and forward progress before completion."""

    popen_options: dict[str, object] = {
        "cwd": cwd,
        "env": dict(env),
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "bufsize": 1,
    }
    launch_command = command
    if _IS_WINDOWS:
        popen_options["creationflags"] = _CREATE_NEW_PROCESS_GROUP
        popen_options["stdin"] = subprocess.PIPE
        # The bootstrap cannot create Julia until the controller assigns it to
        # the kill-on-close job and releases the one-byte gate.  Every Julia
        # descendant is consequently born inside the owned job tree.
        launch_command = (
            sys.executable,
            "-I",
            "-S",
            "-c",
            _WINDOWS_JOB_BOOTSTRAP,
            *command,
        )
    else:
        popen_options["start_new_session"] = True
    process = subprocess.Popen(launch_command, **popen_options)
    windows_job: _WindowsKillOnCloseJob | None = None
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    progress_lines: Queue[str | None] = Queue()
    stderr_done = Event()
    last_progress_event: list[dict[str, object]] = []

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
        try:
            stderr_lines.extend(process.stderr)
        finally:
            stderr_done.set()

    stdout_thread = Thread(target=read_stdout, daemon=True)
    stderr_thread = Thread(target=read_stderr, daemon=True)
    timed_out = False
    deadline = time.monotonic() + timeout
    next_heartbeat = time.monotonic() + _WORKER_HEARTBEAT_SECONDS
    returncode: int | None = None
    stdout_done = False
    stdout_started = False
    stderr_started = False
    stdin_closed = False
    try:
        if _IS_WINDOWS:
            try:
                windows_job = _WindowsKillOnCloseJob.create()
                windows_job.assign(process)
            except OSError as error:
                if windows_job is not None:
                    windows_job.close()
                    windows_job = None
                raise JuliaResponseBackendError(
                    "M02 Julia worker could not enter a kill-on-close Windows job"
                ) from error
        stdout_thread.start()
        stdout_started = True
        stderr_thread.start()
        stderr_started = True
        if _IS_WINDOWS:
            assert process.stdin is not None
            process.stdin.write(_WINDOWS_JOB_START_TOKEN)
            process.stdin.flush()
            process.stdin.close()
            stdin_closed = True
        while returncode is None or not stdout_done or not stderr_done.is_set():
            if returncode is None:
                returncode = process.poll()
            now = time.monotonic()
            wait_seconds = min(0.05, max(0.0, deadline - now))
            if returncode is None:
                wait_seconds = min(
                    wait_seconds,
                    max(0.0, next_heartbeat - now),
                )
            try:
                line = progress_lines.get(timeout=wait_seconds)
            except Empty:
                line = ""
            if line is None:
                stdout_done = True
            elif line:
                _forward_julia_progress_line(
                    line,
                    capture=last_progress_event,
                )
            if returncode is None:
                returncode = process.poll()
            now = time.monotonic()
            if (
                not timed_out
                and now >= deadline
                and (
                    returncode is None
                    or not stdout_done
                    or not stderr_done.is_set()
                )
            ):
                timed_out = True
                _terminate_process_tree(process, windows_job)
                if returncode is None:
                    returncode = process.returncode
                stderr_lines.append(
                    f"Julia worker timed out after {timeout} seconds\n"
                )
            if returncode is None and now >= next_heartbeat:
                emit_progress(
                    ProgressEventKind.WORKER_HEARTBEAT,
                    worker="Julia",
                    worker_alive=True,
                    heartbeat_interval_seconds=_WORKER_HEARTBEAT_SECONDS,
                )
                next_heartbeat = now + _WORKER_HEARTBEAT_SECONDS
    except BaseException:
        _terminate_process_tree(process, windows_job)
        raise
    finally:
        if process.stdin is not None and not stdin_closed:
            process.stdin.close()
        if stdout_started:
            stdout_thread.join()
        if stderr_started:
            stderr_thread.join()
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()
        if windows_job is not None:
            windows_job.close()
    return SimpleNamespace(
        returncode=returncode,
        stdout="".join(stdout_lines)[-4000:],
        stderr="".join(stderr_lines)[-4000:],
        timed_out=timed_out,
        last_progress_event=(
            None if not last_progress_event else last_progress_event[0]
        ),
        last_progress_event_validated=bool(last_progress_event),
    )


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


_WORKER_FAILURE_BASE_FIELDS = frozenset({
    "worker_exit_code",
    "worker_timed_out",
    "worker_stderr_tail",
    "worker_error_type",
    "worker_error_message",
})


def _bounded_text(value: object, limit: int) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if not isinstance(value, str):
        return None
    return value[-limit:]


def _copy_failure_value(value: object, *, depth: int = 0) -> object:
    """Copy a bounded JSON failure value or reject an untrusted attribute."""

    if depth > 8:
        raise ValueError("worker failure nesting is too deep")
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        if len(value) > 4000:
            raise ValueError("worker failure text is too long")
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("worker failure number is not finite")
        return value
    if isinstance(value, Mapping):
        if len(value) > 128:
            raise ValueError("worker failure object is too large")
        copied: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key) > 128:
                raise ValueError("worker failure key is invalid")
            copied[key] = _copy_failure_value(item, depth=depth + 1)
        return copied
    if isinstance(value, list):
        if len(value) > 256:
            raise ValueError("worker failure list is too large")
        return [_copy_failure_value(item, depth=depth + 1) for item in value]
    raise ValueError("worker failure value is not JSON-compatible")


def _structured_worker_failure(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    try:
        copied = _copy_failure_value(value)
    except ValueError:
        return None
    if not isinstance(copied, dict):
        return None
    try:
        serialized = json.dumps(
            copied,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError):
        return None
    if len(serialized) > 32_000:
        return None
    for name in ("failure_code", "failure_class"):
        item = copied.get(name)
        if not isinstance(item, str) or not item:
            return None
    return copied


def worker_failure_payload(error: BaseException) -> dict[str, object] | None:
    """Return one bounded legacy-or-extended Julia worker failure receipt."""

    raw = getattr(error, "worker_failure", None)
    if not isinstance(raw, Mapping):
        return None
    allowed = _WORKER_FAILURE_BASE_FIELDS | {"failure"}
    if not _WORKER_FAILURE_BASE_FIELDS.issubset(raw) or not set(raw).issubset(
        allowed
    ):
        return None
    exit_code = raw["worker_exit_code"]
    if exit_code is not None and (
        isinstance(exit_code, bool) or not isinstance(exit_code, int)
    ):
        return None
    timed_out = raw["worker_timed_out"]
    if not isinstance(timed_out, bool):
        return None
    stderr = _bounded_text(raw["worker_stderr_tail"], 4000)
    error_type = _bounded_text(raw["worker_error_type"], 256)
    error_message = _bounded_text(raw["worker_error_message"], 4000)
    if raw["worker_stderr_tail"] is not None and stderr is None:
        return None
    if raw["worker_error_type"] is not None and error_type is None:
        return None
    if raw["worker_error_message"] is not None and error_message is None:
        return None
    receipt: dict[str, object] = {
        "worker_exit_code": exit_code,
        "worker_timed_out": timed_out,
        "worker_stderr_tail": stderr,
        "worker_error_type": error_type,
        "worker_error_message": error_message,
    }
    if "failure" in raw:
        structured = _structured_worker_failure(raw["failure"])
        if structured is not None:
            receipt["failure"] = structured
    return receipt


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
    structured_failure: dict[str, object] | None = None
    required_response_fields = {
        "schema_version", "status", "error_type", "message"
    }
    if (
        isinstance(error_response, Mapping)
        and required_response_fields.issubset(error_response)
        and set(error_response).issubset(required_response_fields | {"failure"})
        and error_response["schema_version"] == 1
        and error_response["status"] == "error"
        and isinstance(error_response["error_type"], str)
        and isinstance(error_response["message"], str)
    ):
        error_type = _bounded_text(error_response["error_type"], 256)
        error_message = _bounded_text(error_response["message"], 4000)
        if "failure" in error_response:
            structured_failure = _structured_worker_failure(
                error_response["failure"]
            )
    raw_exit_code = getattr(completed, "returncode", None)
    exit_code = (
        raw_exit_code
        if isinstance(raw_exit_code, int) and not isinstance(raw_exit_code, bool)
        else None
    )
    details: dict[str, object] = {
        "worker_exit_code": exit_code,
        "worker_timed_out": bool(getattr(completed, "timed_out", False)),
        "worker_stderr_tail": str(getattr(completed, "stderr", ""))[-4000:],
        "worker_error_type": error_type,
        "worker_error_message": error_message,
    }
    if structured_failure is not None:
        details["failure"] = structured_failure
    return details


def _execution_resource_identity(
    policy: Mapping[str, object],
) -> dict[str, object]:
    return {
        "schema": policy["schema"],
        "version": policy["version"],
        "sha256": policy["sha256"],
    }


def _worker_resource_identity_matches(
    value: object,
    execution_resource: Mapping[str, object],
) -> bool:
    if not isinstance(value, Mapping):
        return False
    identity = _execution_resource_identity(execution_resource)
    if set(value) == set(identity):
        return dict(value) == identity
    if set(value) == set(execution_resource):
        try:
            validated = _validated_execution_resource_policy(value)
        except JuliaResponseBackendError:
            return False
        return validated == dict(execution_resource)
    return False


def _require_worker_resource_identity(
    details: Mapping[str, object],
    execution_resource: Mapping[str, object],
) -> None:
    """Fail closed if a CONTROL receipt is not bound to this request policy."""

    structured = details.get("failure")
    if not isinstance(structured, Mapping) or structured.get(
        "failure_class"
    ) != "CONTROL":
        return
    if _worker_resource_identity_matches(
        structured.get("execution_resource_policy"),
        execution_resource,
    ):
        return
    message = "M02 Julia worker execution-resource policy identity mismatch"
    fatal_details = {
        name: details.get(name) for name in _WORKER_FAILURE_BASE_FIELDS
    }
    fatal_details["worker_error_type"] = "ExecutionResourcePolicyIdentityError"
    fatal_details["worker_error_message"] = message
    failure = JuliaResponseBackendError(message)
    failure.worker_failure = fatal_details
    raise failure


def _bind_failed_preflight_failure_to_request(
    details: Mapping[str, object],
    request_document: Mapping[str, object],
    request_sha256: str,
) -> dict[str, object]:
    """Attach the canonical request only after its worker identity is verified."""

    bound = dict(details)
    structured = bound.get("failure")
    if (
        not isinstance(structured, Mapping)
        or structured.get("failure_class") != "CONTROL"
        or structured.get("failure_code")
        != "INSUFFICIENT_ASYMPTOTIC_PRECISION"
    ):
        return bound
    expected_sha256 = hashlib.sha256(
        canonical_json_bytes(request_document)
    ).hexdigest()
    expected_identity = {
        "request_sha256": expected_sha256,
        "job_id": request_document.get("job_id"),
        "leaf_id": request_document.get("leaf_id"),
        "role": request_document.get("role"),
        "job_policy_sha256": request_document.get("job_policy_sha256"),
        "backend_identity_sha256": request_document.get(
            "backend_identity_sha256"
        ),
        "refinement_level": request_document.get("refinement_level"),
        "precision_digits": request_document.get("precision_digits"),
    }
    mismatch = request_sha256 != expected_sha256 or any(
        structured.get(name) != expected
        for name, expected in expected_identity.items()
    )
    if mismatch:
        message = "M02 Julia failed-preflight request identity mismatch"
        fatal_details = {
            name: details.get(name) for name in _WORKER_FAILURE_BASE_FIELDS
        }
        fatal_details["worker_error_type"] = "FailedPreflightRequestIdentityError"
        fatal_details["worker_error_message"] = message
        failure = JuliaResponseBackendError(message)
        failure.worker_failure = fatal_details
        raise failure
    enriched = dict(structured)
    enriched["request_binding"] = dict(request_document)
    bound["failure"] = enriched
    return bound


def _raise_worker_failure(details: Mapping[str, object]) -> None:
    """Raise an operational error while retaining bounded worker diagnostics."""

    details = dict(details)
    structured = details.get("failure")
    if isinstance(structured, Mapping):
        enriched = dict(structured)
        context = current_progress_context()
        for receipt_name, context_name in (
            ("readout_index", "readout_index"),
            ("readout_role", "readout_role"),
            ("root_phase", "phase"),
            ("newton_index", "newton_index"),
            ("determinant_index", "determinant_index_leaf"),
            ("phase_determinant_index", "determinant_index_phase"),
            ("determinant_purpose", "determinant_purpose"),
        ):
            value = context.get(context_name)
            if receipt_name not in enriched and value is not None:
                enriched[receipt_name] = value
        if enriched.get("root_phase") == "PRIMARY":
            code = enriched.get("failure_code")
            if code == "WORKER_TIMEOUT":
                enriched.setdefault(
                    "diagnostics_skipped_reason", "PRIMARY_TIMEOUT"
                )
            elif code in {
                "ODE_RESOURCE_LIMIT",
                "ROOT_READOUT_RESOURCE_INFEASIBLE",
            }:
                enriched.setdefault(
                    "diagnostics_skipped_reason", "PRIMARY_RESOURCE_LIMIT"
                )
        details["failure"] = enriched
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
    structured = details.get("failure")
    error_class: type[JuliaResponseBackendError]
    if timed_out:
        error_class = JuliaWorkerTimeoutError
    elif (
        isinstance(structured, Mapping)
        and structured.get("failure_code") == "ODE_RESOURCE_LIMIT"
        and structured.get("failure_class") == "CONTROL"
    ):
        error_class = JuliaODEResourceLimitError
    elif (
        isinstance(structured, Mapping)
        and structured.get("failure_code")
        == "ROOT_READOUT_RESOURCE_INFEASIBLE"
        and structured.get("failure_class") == "CONTROL"
    ):
        error_class = JuliaRootReadoutResourceLimitError
    elif (
        isinstance(structured, Mapping)
        and structured.get("failure_code") in NUMERICAL_CONTROL_FAILURE_CODES
        and structured.get("failure_class") == "CONTROL"
        and _valid_numerical_control_diagnostics(structured)
    ):
        error_class = JuliaNumericalControlError
    else:
        error_class = JuliaResponseBackendError
    if error_class is JuliaNumericalControlError:
        failure = JuliaNumericalControlError(
            message, str(structured["failure_code"])
        )
    else:
        failure = error_class(message)
    failure.worker_failure = dict(details)
    raise failure


CONTROL_FAILURE_STAGES = frozenset({
    "request-policy",
    "coordinate-inversion",
    "horizon-endpoint-geometry",
    "asymptotic-preflight",
    "homogeneous-propagation",
    "scattering-extraction",
    "determinant-chart",
    "finite-difference",
    "root-authentication",
})


def _valid_numerical_control_diagnostics(
    failure: Mapping[str, object],
) -> bool:
    """Return whether a recognized control receipt carries typed evidence.

    A failure code says what went wrong; the stage says where. Several codes can
    arise at more than one point in the pipeline, so a receipt without a stage
    cannot be attributed -- and a receipt without diagnostics degrades to a
    generic backend error, losing the named diagnosis entirely.
    """

    diagnostics = failure.get("diagnostics")
    if not isinstance(diagnostics, Mapping) or not diagnostics:
        return False
    if failure.get("stage") not in CONTROL_FAILURE_STAGES:
        return False
    code = failure.get("failure_code")
    if code != "INSUFFICIENT_ASYMPTOTIC_PRECISION":
        return True
    try:
        predicted_reliable_digits = _finite_decimal_text(
            diagnostics.get("predicted_reliable_digits"),
            "failure predicted_reliable_digits",
        )
        required_reliable_digits = _finite_decimal_text(
            diagnostics.get("required_reliable_digits"),
            "failure required_reliable_digits",
            nonnegative=True,
        )
    except JuliaResponseBackendError:
        return False
    return (
        predicted_reliable_digits < required_reliable_digits
        and diagnostics.get("asymptotic_preflight_avoided_ode") is True
        and diagnostics.get("asymptotic_preflight_reason") == code
        and type(
            diagnostics.get("factored_homogeneous_rhs_evaluations")
        ) is int
        and diagnostics["factored_homogeneous_rhs_evaluations"] == 0
        and diagnostics.get("avoided_ode_scope")
        == "factored-homogeneous-gsn/v1"
    )


def _timeout_worker_failure_details(
    details: Mapping[str, object],
    request: Mapping[str, object],
    execution_resource: Mapping[str, object],
    last_progress_event: object = None,
) -> dict[str, object]:
    """Attach a bounded control receipt to a forced outer worker timeout."""

    output = dict(details)
    failure: dict[str, object] = {
        "failure_code": "WORKER_TIMEOUT",
        "failure_class": "CONTROL",
        "retryable": True,
        "precision_digits": request.get("precision_digits"),
        "elapsed_request_seconds": execution_resource[
            "worker_request_wall_clock_seconds"
        ],
        "limiting_resource": "worker_request_wall_clock",
        "execution_resource_policy": dict(execution_resource),
    }
    failure.update(_timeout_progress_failure_fields(last_progress_event))
    output["failure"] = failure
    return output


def _timeout_progress_failure_fields(value: object) -> dict[str, object]:
    """Project the last already-validated worker event into timeout evidence."""

    if not isinstance(value, Mapping) or set(value) != {
        "schema",
        "kind",
        "context",
        "payload",
    }:
        return {}
    if value.get("schema") != PROGRESS_SCHEMA:
        return {}
    try:
        ProgressEventKind(value.get("kind"))
        copied = _copy_failure_value(value)
    except (TypeError, ValueError):
        return {}
    if not isinstance(copied, Mapping):
        return {}
    context = copied.get("context")
    payload = copied.get("payload")
    if not isinstance(context, Mapping) or not isinstance(payload, Mapping):
        return {}
    fields: dict[str, object] = {"last_progress_kind": copied["kind"]}
    for receipt_name, context_names in (
        ("readout_index", ("readout_index",)),
        ("readout_role", ("readout_role",)),
        ("root_phase", ("phase",)),
        ("newton_index", ("newton_index",)),
        ("determinant_index", ("determinant_index_leaf", "determinant_index")),
        ("phase_determinant_index", ("determinant_index_phase",)),
        ("determinant_purpose", ("determinant_purpose",)),
    ):
        for context_name in context_names:
            item = context.get(context_name)
            if item is not None:
                fields[receipt_name] = item
                break
    request_elapsed = payload.get("request_elapsed_seconds")
    if request_elapsed is not None:
        fields["elapsed_request_seconds"] = request_elapsed
    ode_kinds = {
        ProgressEventKind.ODE_SOLVE_STARTED.value,
        ProgressEventKind.ODE_SOLVE_PROGRESS.value,
        ProgressEventKind.ODE_SOLVE_COMPLETED.value,
        ProgressEventKind.ODE_SOLVE_FAILED.value,
        ProgressEventKind.ODE_RESOURCE_LIMIT.value,
    }
    if copied["kind"] in ode_kinds:
        fields["ode_snapshot"] = dict(payload)
        if payload.get("ode_leg") is not None:
            fields["ode_leg"] = payload["ode_leg"]
        if payload.get("elapsed_seconds") is not None:
            fields["elapsed_leg_seconds"] = payload["elapsed_seconds"]
    return fields


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


def _resolve_readout_cache(runtime_root: Path) -> RootReadoutStore | None:
    """Resolve the readout work cache belonging to one provisioned runtime.

    The cache is scoped to the runtime that answers the readouts rather than to
    a fixed per-user path, so a separate runtime keeps a separate cache and a
    throwaway runtime never writes into the production one.
    """

    if os.environ.get("KERR_QNM_ROOT_READOUT_CACHE", "1").strip() == "0":
        return None
    override = os.environ.get("KERR_QNM_ROOT_READOUT_CACHE_ROOT")
    if override:
        return RootReadoutStore(Path(override))
    return RootReadoutStore(Path(runtime_root) / ROOT_READOUT_STORE_DIRECTORY_NAME)


@dataclass(frozen=True, slots=True)
class JuliaResponseEvaluation:
    """One worker response plus the exact identities required to validate it."""

    response: Mapping[str, object]
    request_binding: Mapping[str, object]
    request_sha256: str
    runtime_identity_sha256: str
    reused: bool
    cached_worker_response_receipt: Mapping[str, object] | None


@dataclass(frozen=True, slots=True)
class JuliaResponseAdapter:
    julia_executable: Path
    julia_project: Path
    julia_depot: Path
    worker_script: Path
    runtime_provenance: Mapping[str, object]
    runner: Callable[..., object] = subprocess.run
    julia_prefix_arguments: tuple[str, ...] = ()
    readout_cache: RootReadoutStore | None = None

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
            _resolve_readout_cache(runtime),
        )

    def _reuse_readout(
        self, request_sha256: str
    ) -> tuple[dict[str, object], dict[str, object] | None] | None:
        """Return an already-computed readout for this exact request, if any."""

        store = self.readout_cache
        if store is None:
            return None
        try:
            identity = runtime_identity_sha256(self.runtime_provenance)
            lookup = store.lookup(
                request_sha256=request_sha256, runtime_identity=identity
            )
        except (OSError, ValueError) as error:
            # A work cache must never be able to fail a readout; fall through and
            # let the worker recompute.
            emit_progress(
                ProgressEventKind.ROOT_READOUT_CACHE_CORRUPT,
                request_sha256=request_sha256,
                error_type=type(error).__name__,
                message=str(error),
            )
            return None
        if lookup.status is RootReadoutLookupStatus.CORRUPT:
            emit_progress(
                ProgressEventKind.ROOT_READOUT_CACHE_CORRUPT,
                request_sha256=request_sha256,
                store_path=str(lookup.path),
                message=lookup.reason,
            )
            return None
        if lookup.status is not RootReadoutLookupStatus.HIT:
            return None
        emit_progress(
            ProgressEventKind.ROOT_READOUT_REUSED,
            request_sha256=request_sha256,
            store_path=str(lookup.path),
        )
        return (
            dict(lookup.response or {}),
            (
                None
                if lookup.worker_response_receipt is None
                else dict(lookup.worker_response_receipt)
            ),
        )

    def _retain_readout(
        self,
        request_sha256: str,
        response: Mapping[str, object],
        worker_response_receipt: Mapping[str, object] | None = None,
    ) -> None:
        """Retain a validated readout so an interrupted stage can resume."""

        store = self.readout_cache
        if store is None:
            return
        try:
            path = store.publish(
                request_sha256=request_sha256,
                runtime_identity=runtime_identity_sha256(self.runtime_provenance),
                response=response,
                worker_response_receipt=worker_response_receipt,
            )
        except (OSError, ValueError) as error:
            emit_progress(
                ProgressEventKind.ROOT_READOUT_CACHE_CORRUPT,
                request_sha256=request_sha256,
                error_type=type(error).__name__,
                message=str(error),
            )
            return
        emit_progress(
            ProgressEventKind.ROOT_READOUT_RETAINED,
            request_sha256=request_sha256,
            store_path=str(path),
        )

    def evaluate(self, request: Mapping[str, object]) -> dict[str, object]:
        """Generic adapter entry point retaining its successful wire response."""

        return dict(self._evaluate(request, retain_fresh=True).response)

    def evaluate_for_validation(
        self, request: Mapping[str, object]
    ) -> JuliaResponseEvaluation:
        """Return a response without publishing it before scientific validation."""

        return self._evaluate(request, retain_fresh=False)

    def retain_validated_readout(
        self,
        evaluation: JuliaResponseEvaluation,
        worker_response_receipt: Mapping[str, object],
    ) -> None:
        if evaluation.reused:
            return
        self._retain_readout(
            evaluation.request_sha256,
            evaluation.response,
            worker_response_receipt,
        )

    def invalidate_validated_readout(
        self, evaluation: JuliaResponseEvaluation
    ) -> None:
        if not evaluation.reused or self.readout_cache is None:
            return
        try:
            self.readout_cache.invalidate(
                request_sha256=evaluation.request_sha256,
                runtime_identity=evaluation.runtime_identity_sha256,
            )
        except (OSError, ValueError) as error:
            emit_progress(
                ProgressEventKind.ROOT_READOUT_CACHE_CORRUPT,
                request_sha256=evaluation.request_sha256,
                error_type=type(error).__name__,
                message=str(error),
            )

    def _evaluate(
        self, request: Mapping[str, object], *, retain_fresh: bool
    ) -> JuliaResponseEvaluation:
        request_document = dict(request)
        execution_resource = _validated_execution_resource_policy(
            request_document["execution_resource"]
            if "execution_resource" in request_document
            else _execution_resource_policy()
        )
        request_document["execution_resource"] = execution_resource
        request_sha256 = hashlib.sha256(
            canonical_json_bytes(request_document)
        ).hexdigest()
        runtime_identity = runtime_identity_sha256(self.runtime_provenance)
        reused = self._reuse_readout(request_sha256)
        if reused is not None:
            response, receipt = reused
            return JuliaResponseEvaluation(
                response=response,
                request_binding=request_document,
                request_sha256=request_sha256,
                runtime_identity_sha256=runtime_identity,
                reused=True,
                cached_worker_response_receipt=receipt,
            )
        document = dict(request_document)
        document["request_sha256"] = request_sha256
        timeout = int(execution_resource["worker_request_wall_clock_seconds"])
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
                try:
                    completed = self.runner(
                        command,
                        cwd=directory,
                        env=environment,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=timeout,
                    )
                except subprocess.TimeoutExpired as error:
                    stderr = _bounded_text(error.stderr, 4000)
                    if stderr is None:
                        stderr = _bounded_text(error.output, 4000) or ""
                    _raise_worker_failure(_timeout_worker_failure_details(
                        {
                            "worker_exit_code": None,
                            "worker_timed_out": True,
                            "worker_stderr_tail": stderr,
                            "worker_error_type": None,
                            "worker_error_message": None,
                        },
                        document,
                        execution_resource,
                    ))
            returncode = getattr(completed, "returncode", None)
            if bool(getattr(completed, "timed_out", False)) or returncode != 0:
                details = _worker_failure_details(completed, response_path)
                if bool(getattr(completed, "timed_out", False)):
                    last_progress_event = (
                        getattr(completed, "last_progress_event", None)
                        if bool(
                            getattr(
                                completed,
                                "last_progress_event_validated",
                                False,
                            )
                        )
                        else None
                    )
                    details = _timeout_worker_failure_details(
                        details,
                        document,
                        execution_resource,
                        last_progress_event,
                    )
                _require_worker_resource_identity(details, execution_resource)
                details = _bind_failed_preflight_failure_to_request(
                    details, request_document, request_sha256
                )
                _raise_worker_failure(details)
            response = _strict_json_file(response_path, "M02 Julia response")
        if response.get("status") != "ok":
            details = _worker_failure_details(
                completed, response_path, response=response
            )
            _require_worker_resource_identity(details, execution_resource)
            details = _bind_failed_preflight_failure_to_request(
                details, request_document, request_sha256
            )
            _raise_worker_failure(details)
        if response.get("request_sha256") != request_sha256:
            raise JuliaResponseBackendError("M02 Julia response request digest mismatch")
        if retain_fresh:
            self._retain_readout(request_sha256, response)
        return JuliaResponseEvaluation(
            response=dict(response),
            request_binding=request_document,
            request_sha256=request_sha256,
            runtime_identity_sha256=runtime_identity,
            reused=False,
            cached_worker_response_receipt=None,
        )


def _precision_policy(job: ResponseComponentJob, digits: int, refinement: int) -> dict[str, object]:
    if digits not in _PROMOTED_DIGITS:
        raise ValueError("Julia response precision must be 80 or 120 digits")
    if refinement not in (0, 1):
        raise ValueError("Julia response refinement level must be zero or one")
    level = "base" if refinement == 0 else "refinement"
    controls = promoted_precision_numerical_controls()[str(digits)][level]
    return {
        "readout_radius": format(job.policy.readout_radius, ".17g"),
        **controls,
        **horizon_geometry_controls(),
        **regularised_gsn_precision_policy(job.mechanism_id),
        "endpoint_series_order": job.policy.endpoint_series_order + 8 * refinement,
        "support_subinterval_count": job.policy.support_subinterval_count * (2 ** refinement),
        "angular_pad": 18 + 8 * refinement,
        "rho_in": "-5000",
        "rho_out": "5000",
        "branch_enclosure_radius_abs": format(
            _mode_specific_branch_enclosure_radius(job), ".17g"
        ),
        "max_newton_iterations": 16,
    }


def _validate_mechanism_precision_policy(
    mechanism_id: str, policy: Mapping[str, object]
) -> None:
    """Fail closed when a request authenticates the wrong determinant family."""

    expected = regularised_gsn_precision_policy(mechanism_id)
    if any(policy.get(field) != value for field, value in expected.items()):
        raise ValueError(
            "regularised GSN precision policy disagrees with response mechanism"
        )


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

    def scientific_runtime_for(
        self, job: ResponseComponentJob
    ) -> dict[str, object]:
        """Return provenance bound to the determinant family used by ``job``."""

        if job.backend_identity != self.identity:
            raise ValueError(
                "response job backend identity does not match Julia adapter"
            )
        return {
            **self.scientific_runtime,
            "regularised_gsn_precision_policy": dict(
                regularised_gsn_precision_policy(job.mechanism_id)
            ),
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
            "job_id": job.job_id,
            "leaf_id": job.leaf_id,
            "role": job.role,
            "job_policy_sha256": job.policy.identity_sha256,
            "backend_identity_sha256": job.backend_identity.identity_sha256,
            "refinement_level": self.refinement,
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
            "execution_resource": _execution_resource_policy(),
        }
        _validate_mechanism_precision_policy(
            job.mechanism_id, request["policy"]
        )
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
        request = self._request(
            job,
            complex(amplitude),
            primary_predictor,
            primary_predictor_kind,
        )
        evaluate_for_validation = getattr(
            self.adapter, "evaluate_for_validation", None
        )
        if evaluate_for_validation is None:
            response = self.adapter.evaluate(request)
            evaluation = JuliaResponseEvaluation(
                response=response,
                request_binding=dict(request),
                request_sha256=hashlib.sha256(
                    canonical_json_bytes(request)
                ).hexdigest(),
                runtime_identity_sha256=runtime_identity_sha256(
                    self.adapter.runtime_provenance
                ),
                reused=False,
                cached_worker_response_receipt=None,
            )
        else:
            evaluation = evaluate_for_validation(request)
        try:
            return self._read_root_response(job, request, evaluation)
        except JuliaResponseBackendError:
            invalidate = getattr(
                self.adapter, "invalidate_validated_readout", None
            )
            if invalidate is not None:
                invalidate(evaluation)
            raise

    def _read_root_response(
        self,
        job: ResponseComponentJob,
        request: Mapping[str, object],
        evaluation: JuliaResponseEvaluation,
    ) -> RootReadout:
        response = dict(evaluation.response)
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
            "raw_determinant_abs",
            "raw_determinant_evidence_status",
            "root_derivative_abs",
            "root_authentication",
            "root_converged",
            "branch_authentication_contract_version",
            "root_branch_continuation_valid",
            "branch_tolerance_abs",
            "root_displacement_abs",
            "truncation_radius_abs",
            "resolution_radius_abs",
            "seed_path_radius_abs",
            "diagnostic_roots",
            "numerical_conditioning",
        }
        if set(response) not in {
            frozenset(expected_fields),
            frozenset(expected_fields | {"diagnostics_skipped_reason"}),
        }:
            raise JuliaResponseBackendError("M02 Julia response fields are invalid")
        if (
            any(
                type(response[name]) is not int
                for name in (
                    "schema_version",
                    "precision_digits",
                    "working_precision_bits",
                    "branch_authentication_contract_version",
                )
            )
            or response["schema_version"] != 4
            or response["status"] != "ok"
            or response["adapter"] != "package-owned-julia-gsn-root-readout"
            or response["precision_digits"] != self.digits
            or response["working_precision_bits"]
            != math.ceil(self.digits * math.log2(10)) + 32
            or not isinstance(response["root_converged"], bool)
            or response["branch_authentication_contract_version"] != 3
            or not isinstance(response["root_branch_continuation_valid"], bool)
            or (
                response["root_converged"]
                and not response["root_branch_continuation_valid"]
            )
        ):
            raise JuliaResponseBackendError("M02 Julia response contract is invalid")
        try:
            numerical_conditioning = NumericalConditioningEvidence.from_mapping(
                response["numerical_conditioning"]
            )
        except ValueError as error:
            raise JuliaResponseBackendError(
                "M02 Julia numerical conditioning evidence is invalid"
            ) from error
        if numerical_conditioning.schema != NUMERICAL_CONDITIONING_SCHEMA:
            raise JuliaResponseBackendError(
                "M02 Julia current conditioning schema is required"
            )
        try:
            root_authentication = RootAuthenticationEvidence.from_mapping(
                response["root_authentication"]
            )
        except ValueError as error:
            raise JuliaResponseBackendError(
                "M02 Julia root authentication evidence is invalid"
            ) from error
        # The error model is published exactly by the families that compute one.
        # A horizon determinant without a breakdown would mean an error-aware
        # acceptance decision was made from an absent error term.
        horizon_family = (
            numerical_conditioning.scattering_diagnostics_applicable is True
        )
        if horizon_family != (root_authentication.error_breakdown is not None):
            raise JuliaResponseBackendError(
                "M02 Julia root authentication error model does not match the "
                "determinant family"
            )
        converged = response["root_converged"]
        diagnostics_skipped_reason = response.get("diagnostics_skipped_reason")
        diagnostics_skipped = diagnostics_skipped_reason == "PRIMARY_NOT_CONVERGED"
        if diagnostics_skipped_reason not in {None, "PRIMARY_NOT_CONVERGED"}:
            raise JuliaResponseBackendError(
                "M02 Julia diagnostic skip reason is invalid"
            )
        raw_diagnostics = response["diagnostic_roots"]
        if diagnostics_skipped and (
            converged
            or any(
                response[name] is not None
                for name in (
                    "truncation_radius_abs",
                    "resolution_radius_abs",
                    "seed_path_radius_abs",
                )
            )
            or not isinstance(raw_diagnostics, Mapping)
            or bool(raw_diagnostics)
        ):
            raise JuliaResponseBackendError(
                "M02 Julia diagnostic skip evidence is inconsistent"
            )
        branch_continuation_valid = response[
            "root_branch_continuation_valid"
        ]
        branch_tolerance_decimal = _finite_decimal_text(
            response["branch_tolerance_abs"],
            "branch_tolerance_abs",
            nonnegative=True,
        )
        policy = request["policy"]
        if not isinstance(policy, Mapping):
            raise JuliaResponseBackendError("M02 Julia request policy is invalid")
        try:
            _validate_mechanism_precision_policy(job.mechanism_id, policy)
        except ValueError as error:
            raise JuliaResponseBackendError(
                "M02 Julia request policy disagrees with response mechanism"
            ) from error
        conditioning_identity_fields = (
            "homogeneous_representation",
            "branch_convention",
            "scattering_column_convention",
            "radial_derivative_convention",
            "determinant_convention",
            "determinant_normalisation",
            "regular_remainder_contract",
            "factored_remainder_state_convention",
            "determinant_family",
            "scattering_diagnostics_applicable",
            "human_math_review_receipt_status",
            "human_math_review_receipt_sha256",
            "independent_reference_fixture_receipt_status",
            "independent_reference_fixture_receipt_sha256",
        )
        if any(
            policy.get(field) != getattr(numerical_conditioning, field)
            for field in conditioning_identity_fields
        ):
            raise JuliaResponseBackendError(
                "M02 Julia numerical conditioning identity disagrees with request policy"
            )
        mechanism_contract = regularised_gsn_mechanism_contract(
            job.mechanism_id
        )
        if any(
            getattr(numerical_conditioning, field) != expected
            for field, expected in mechanism_contract.items()
        ):
            raise JuliaResponseBackendError(
                "M02 Julia numerical conditioning determinant family disagrees "
                "with response mechanism"
            )
        expected_branch_tolerance_decimal = _finite_decimal_text(
            policy["branch_enclosure_radius_abs"],
            "branch_enclosure_radius_abs",
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
        normalised_determinant_abs = _finite_decimal_text(
            response["root_residual_abs"],
            "root_residual_abs",
            nonnegative=True,
        )
        raw_determinant_abs = (
            None
            if response["raw_determinant_abs"] is None
            else _finite_decimal_text(
                response["raw_determinant_abs"],
                "raw_determinant_abs",
                nonnegative=True,
            )
        )
        raw_determinant_evidence_status = response[
            "raw_determinant_evidence_status"
        ]
        if not isinstance(raw_determinant_evidence_status, str):
            raise JuliaResponseBackendError(
                "M02 Julia raw determinant evidence status is invalid"
            )
        if job.mechanism_id == "horizon-admittance":
            if raw_determinant_evidence_status == "available/v1":
                if raw_determinant_abs is None:
                    raise JuliaResponseBackendError(
                        "M02 Julia available raw horizon determinant lacks "
                        "its magnitude"
                    )
            elif raw_determinant_evidence_status == "unavailable-overflow/v1":
                if raw_determinant_abs is not None:
                    raise JuliaResponseBackendError(
                        "M02 Julia unavailable raw horizon determinant must "
                        "not carry a magnitude"
                    )
            else:
                raise JuliaResponseBackendError(
                    "M02 Julia horizon raw determinant evidence status is invalid"
                )
        elif (
            raw_determinant_evidence_status != "not-applicable/v1"
            or raw_determinant_abs is not None
        ):
            raise JuliaResponseBackendError(
                "M02 Julia exterior Wronskian must not claim raw horizon evidence"
            )
        diagnostic_radii_decimal = (
            {}
            if diagnostics_skipped
            else {
                "truncation": _finite_decimal_text(
                    response["truncation_radius_abs"],
                    "truncation_radius_abs",
                    nonnegative=True,
                ),
                "resolution": _finite_decimal_text(
                    response["resolution_radius_abs"],
                    "resolution_radius_abs",
                    nonnegative=True,
                ),
                "seed-path": _finite_decimal_text(
                    response["seed_path_radius_abs"],
                    "seed_path_radius_abs",
                    nonnegative=True,
                ),
            }
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
                abs(branch_tolerance_decimal - expected_branch_tolerance_decimal)
                > serialization_allowance
                or abs(derived_displacement - root_displacement_decimal)
                > serialization_allowance
                or branch_continuation_valid
                != (
                    derived_displacement <= branch_tolerance_decimal
                    and (diagnostics_skipped or all(
                        radius <= branch_tolerance_decimal
                        for radius in diagnostic_radii_decimal.values()
                    ))
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
        truncation_radius = (
            None
            if diagnostics_skipped
            else _finite_text(
                response["truncation_radius_abs"], "truncation_radius_abs"
            )
        )
        resolution_radius = (
            None
            if diagnostics_skipped
            else _finite_text(
                response["resolution_radius_abs"], "resolution_radius_abs"
            )
        )
        seed_path_radius = (
            None
            if diagnostics_skipped
            else _finite_text(
                response["seed_path_radius_abs"], "seed_path_radius_abs"
            )
        )
        if not diagnostics_skipped and (
            not isinstance(raw_diagnostics, Mapping)
            or set(raw_diagnostics) != {"truncation", "resolution", "seed-path"}
        ):
            raise JuliaResponseBackendError("M02 Julia diagnostic roots are invalid")
        diagnostics: dict[str, DiagnosticRootReadout] = {}
        for family in (() if diagnostics_skipped else (
            "truncation", "resolution", "seed-path"
        )):
            raw = raw_diagnostics[family]
            if not isinstance(raw, Mapping) or set(raw) != {
                "root_omega_re",
                "root_omega_im",
                "root_residual_abs",
                "root_derivative_abs",
                "root_converged",
            } or not isinstance(raw["root_converged"], bool):
                raise JuliaResponseBackendError("M02 Julia diagnostic root is invalid")
            diagnostic_real_decimal = _finite_decimal_text(
                raw["root_omega_re"], "diagnostic root_omega_re"
            )
            diagnostic_imaginary_decimal = _finite_decimal_text(
                raw["root_omega_im"], "diagnostic root_omega_im"
            )
            with localcontext() as context:
                context.prec = self.digits + 64
                delta_real = diagnostic_real_decimal - root_real_decimal
                delta_imaginary = (
                    diagnostic_imaginary_decimal - root_imaginary_decimal
                )
                derived_radius = (
                    delta_real * delta_real
                    + delta_imaginary * delta_imaginary
                ).sqrt()
                if (
                    abs(derived_radius - diagnostic_radii_decimal[family])
                    > serialization_allowance
                ):
                    raise JuliaResponseBackendError(
                        "M02 Julia diagnostic root evidence is inconsistent"
                    )
            diagnostics[family] = DiagnosticRootReadout(
                omega_delta_from_primary=complex(
                    _finite_text(str(delta_real), "diagnostic root delta real"),
                    _finite_text(
                        str(delta_imaginary),
                        "diagnostic root delta imaginary",
                    ),
                ),
                determinant_residual_abs=_finite_text(
                    raw["root_residual_abs"], "diagnostic root_residual_abs"
                ),
                determinant_derivative_abs=_finite_text(
                    raw["root_derivative_abs"], "diagnostic root_derivative_abs"
                ),
                converged=raw["root_converged"],
            )
        receipt_material = {
            "schema": WORKER_RESPONSE_RECEIPT_SCHEMA,
            "request_binding": dict(evaluation.request_binding),
            "request_sha256": evaluation.request_sha256,
            "scientific_runtime_sha256": hashlib.sha256(
                canonical_json_bytes(self.scientific_runtime_for(job))
            ).hexdigest(),
            "worker_response_schema_version": response["schema_version"],
            "root_residual_abs_text": response["root_residual_abs"],
            "raw_determinant_abs_text": response["raw_determinant_abs"],
            "raw_determinant_evidence_status": (
                response["raw_determinant_evidence_status"]
            ),
        }
        worker_response_receipt = {
            **receipt_material,
            "receipt_sha256": hashlib.sha256(
                canonical_json_bytes(receipt_material)
            ).hexdigest(),
        }
        if (
            evaluation.reused
            and dict(evaluation.cached_worker_response_receipt or {})
            != worker_response_receipt
        ):
            raise JuliaResponseBackendError(
                "M02 cached worker response receipt is invalid"
            )
        try:
            readout = RootReadout(
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
                diagnostic_readouts=(None if diagnostics_skipped else diagnostics),
                diagnostics_skipped_reason=diagnostics_skipped_reason,
                numerical_conditioning=numerical_conditioning,
                normalised_determinant_abs=normalised_determinant_abs,
                raw_determinant_abs=raw_determinant_abs,
                raw_determinant_evidence_status=
                    raw_determinant_evidence_status,
                worker_response_receipt=worker_response_receipt,
            )
        except ValueError as error:
            raise JuliaResponseBackendError(
                "M02 Julia diagnostic root evidence is inconsistent"
            ) from error
        retain = getattr(self.adapter, "retain_validated_readout", None)
        if retain is not None:
            retain(evaluation, worker_response_receipt)
        return readout

    def closed_form_horizon_response(
        self, job: ResponseComponentJob
    ) -> complex | None:
        if job.backend_identity != self.identity:
            raise ValueError("response job backend identity does not match Julia adapter")
        return None
