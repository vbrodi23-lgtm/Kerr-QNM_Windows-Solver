"""Authenticated Python boundary for the package-owned Julia precision worker.

The worker performs reviewed promoted root and fixed-root response requests.
The Python response engine owns scheduling, component reduction, error ledgers,
checkpoints, resume, and admission.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from enum import Enum
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
from .operation_control import (
    FIXED_ROOT_SURVEY_BATCH_OPERATION,
    JULIA_WORKER_ORIGIN,
    PYTHON_SUPERVISOR_ORIGIN,
    REQUEST_SCOPE,
    SAMPLE_SCOPE,
    ValidatedControlReceipt,
    build_operation_control_receipt,
    execution_identity_from_request,
    operation_execution_identity,
    validate_operation_control_receipt,
)
from .adaptive_controls import (
    MissingODECalibrationError,
    ODE_CALIBRATION_BLOCKER,
    ODEErrorBudget,
)
from .response_engine import (
    BINARY64_FIXED_ROOT_SAMPLE_ROLES,
    BINARY64_FIXED_ROOT_SURVEY_IDENTITY,
    BackendIdentity,
    CANONICAL_EXTERIOR_BACKGROUND_IDENTITY,
    DecimalComplex,
    exterior_provisional_reuse_receipt,
    FixedRootDiagnosticEvidence,
    FixedRootDeterminantSample,
    DiagnosticRootReadout,
    HISTORICAL_WORKER_RESPONSE_RECEIPT_SCHEMA,
    LEGACY_PROMOTED_WORKER_RESPONSE_WIRE_SCHEMA,
    NumericalConditioningEvidence,
    NUMERICAL_CONDITIONING_SCHEMA,
    ResponseComponentJob,
    PrimaryRootAcceptanceEvidence,
    PROMOTED_ROOT_ACCEPTANCE_METRIC,
    PROMOTED_ROOT_READOUT_POLICY,
    EXTERIOR_PROVISIONAL_DETERMINANT_ERROR_MODEL,
    RawDeterminantContract,
    raw_determinant_contract_golden_cases,
    raw_determinant_contract_fields_for_model,
    raw_determinant_contract_from_request,
    _validate_current_raw_determinant_policy,
    RootAuthenticationEvidence,
    RootReadout,
    VERIFIED_ENDPOINT_ERROR_MODEL,
    WORKER_RESPONSE_RECEIPT_SCHEMA,
    WORKER_RESPONSE_WIRE_SCHEMA,
    _exterior_support,
    _validated_successful_horizon_endpoint_search_evidence,
    mode_specific_branch_enclosure_radius,
    regularised_gsn_mechanism_contract,
    regularised_gsn_precision_policy,
)
from .precision_tiers import PrecisionTier, precision_tier
from .promoted_control_calibration import (
    EXTERIOR_DETERMINANT_ABSOLUTE_ERROR_CERTIFICATE,
    EXTERIOR_DETERMINANT_CERTIFICATE_UNAVAILABLE,
    EmpiricalControlProfile,
    PromotedControlCalibrationReceipt,
    load_default_calibration_receipt,
)
from .progress import (
    PROGRESS_SCHEMA,
    ProgressEventKind,
    current_progress_context,
    emit_progress,
    ingest_external_progress,
)
from .promoted_request_preflight import (
    PROMOTED_REQUEST_PREFLIGHT_CACHE_DIRECTORY_NAME,
    PromotedRequestPreflightStore,
    promoted_request_preflight_binding,
)
from .root_readout_cache import (
    ROOT_READOUT_STORE_DIRECTORY_NAME,
    RootReadoutLookupStatus,
    RootReadoutStore,
    runtime_identity_sha256,
)


_PROMOTED_DIGITS = frozenset({40, 80, 120})
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
_PROMOTED_REQUEST_PREFLIGHT_TIMEOUT_SECONDS = 600
_PROMOTED_REQUEST_PREFLIGHT_OPERATION = "promoted-request-preflight"
FIXED_ROOT_SURVEY_BATCH_SCHEMA = "windows-solver.fixed-root-survey-batch/2"
FIXED_ROOT_SURVEY_BATCH_RESPONSE_SCHEMA = (
    "windows-solver.fixed-root-survey-batch-response/2"
)
FIXED_ROOT_SURVEY_CONDITIONING_SCHEMA = (
    "windows-solver.fixed-root-survey-conditioning/2"
)
FIXED_ROOT_RELIABILITY_RULE = (
    "minus-log10-target-plus-required-digit-guard/v1"
)
_FIXED_ROOT_SURVEY_MAXIMUM_SAMPLE_COUNT = 9
_FIXED_ROOT_SURVEY_BACKGROUND_ROLES = BINARY64_FIXED_ROOT_SAMPLE_ROLES[:5]
_FIXED_ROOT_SURVEY_COORDINATE_ROLES = BINARY64_FIXED_ROOT_SAMPLE_ROLES[5:]


class FixedRootSurveyPlan(str, Enum):
    """The only valid numerical request shapes for a promoted exterior leaf.

    A plan owns both the scientific operation identity and the ordered role
    vector.  Keeping those values coupled at this boundary prevents a caller
    from sending the canonical-background identity with a raw/full role set
    (the exact mismatch that stopped the first promoted exterior route).
    """

    FULL_NINE = "FULL_NINE"
    CANONICAL_BACKGROUND_FIVE = "CANONICAL_BACKGROUND_FIVE"
    MECHANISM_COMPONENT_FOUR = "MECHANISM_COMPONENT_FOUR"


@dataclass(frozen=True, slots=True)
class FixedRootSurveyRequestContract:
    """One authenticated worker-request shape.

    This is deliberately a small value object rather than a caller-built
    mapping: scheduler code chooses a named plan, and this module resolves the
    corresponding identity and ordered sample roles exactly once.
    """

    plan: FixedRootSurveyPlan
    scientific_operation_identity: str
    sample_roles: tuple[str, ...]


_FIXED_ROOT_SURVEY_REQUEST_CONTRACTS: Mapping[
    FixedRootSurveyPlan, FixedRootSurveyRequestContract
] = {
    FixedRootSurveyPlan.FULL_NINE: FixedRootSurveyRequestContract(
        plan=FixedRootSurveyPlan.FULL_NINE,
        scientific_operation_identity=BINARY64_FIXED_ROOT_SURVEY_IDENTITY,
        sample_roles=tuple(BINARY64_FIXED_ROOT_SAMPLE_ROLES),
    ),
    FixedRootSurveyPlan.CANONICAL_BACKGROUND_FIVE: FixedRootSurveyRequestContract(
        plan=FixedRootSurveyPlan.CANONICAL_BACKGROUND_FIVE,
        scientific_operation_identity=CANONICAL_EXTERIOR_BACKGROUND_IDENTITY,
        sample_roles=tuple(_FIXED_ROOT_SURVEY_BACKGROUND_ROLES),
    ),
    FixedRootSurveyPlan.MECHANISM_COMPONENT_FOUR: FixedRootSurveyRequestContract(
        plan=FixedRootSurveyPlan.MECHANISM_COMPONENT_FOUR,
        scientific_operation_identity=BINARY64_FIXED_ROOT_SURVEY_IDENTITY,
        sample_roles=tuple(_FIXED_ROOT_SURVEY_COORDINATE_ROLES),
    ),
}


def fixed_root_survey_request_contract(
    plan: FixedRootSurveyPlan | str,
) -> FixedRootSurveyRequestContract:
    """Resolve a named plan to its exact identity/role contract."""

    try:
        resolved = FixedRootSurveyPlan(plan)
    except (TypeError, ValueError) as error:
        raise ValueError("fixed-root survey plan is invalid") from error
    return _FIXED_ROOT_SURVEY_REQUEST_CONTRACTS[resolved]


def fixed_root_survey_plan_for_pair(
    scientific_operation_identity: str,
    sample_roles: tuple[str, ...],
) -> FixedRootSurveyPlan:
    """Return the sole named plan compatible with a persisted batch pair."""

    for plan, contract in _FIXED_ROOT_SURVEY_REQUEST_CONTRACTS.items():
        if (
            scientific_operation_identity == contract.scientific_operation_identity
            and sample_roles == contract.sample_roles
        ):
            return plan
    raise ValueError("fixed-root survey identity and roles are not one request plan")


def consume_authenticated_binary64_provisional_predecessor(
    stage: object,
    *,
    job: ResponseComponentJob,
    scientific_computation_identity: str,
    root_seal_sha256: str,
) -> dict[str, object]:
    """Validate the binary64 predecessor before BF40 dispatches new work.

    The receipt makes the cross-tier handoff explicit without presenting the
    binary64 samples as BF40 determinant-error evidence.
    """

    return exterior_provisional_reuse_receipt(
        stage,
        job=job,
        scientific_computation_identity=scientific_computation_identity,
        root_seal_sha256=root_seal_sha256,
        target_precision_tier="BF40",
    )
_FIXED_ROOT_SURVEY_CERTIFICATE_FIELDS = frozenset({
    "determinant_error_model",
    "determinant_error_channel_schema",
    "determinant_error_required_channels",
    "determinant_error_calibration_status",
    "determinant_error_missing_evidence_outcome",
    "determinant_error_preceding_precision_tier",
})
_EXTERIOR_ADDITIVE_CHANNEL_SCHEMA = (
    "exterior-determinant-additive-channels/provisional-v1"
)
_EXTERIOR_ADDITIVE_CHANNELS = [
    "precision",
    "ode_controls",
    "endpoint_order",
    "match_readout",
    "angular_data",
    "arithmetic_rounding",
]
_EXTERIOR_EMPIRICAL_TERM_CLASSES = [
    "delta_same_point",
    "delta_cross_precision",
    "delta_endpoint_series",
]
_EXTERIOR_EMPIRICAL_CERTIFICATE_STATEMENT = (
    "conservative empirical certificate; not a formal interval enclosure"
)


def _is_uncalibrated_exterior_error_policy(policy: Mapping[str, object]) -> bool:
    """Identify the v3-style exterior gate without treating it as a disk."""

    return policy.get("determinant_error_model") == _EXTERIOR_ADDITIVE_CHANNEL_SCHEMA
_FIXED_ROOT_SURVEY_REVIEW_ONLY_POLICY_FIELDS = frozenset({
    "human_math_review_receipt_status",
    "human_math_review_receipt_sha256",
    "independent_reference_fixture_receipt_status",
    "independent_reference_fixture_receipt_sha256",
    "promoted_root_readout_policy",
})
_FIXED_ROOT_SURVEY_ROOT_ONLY_POLICY_FIELDS = frozenset({
    "branch_enclosure_radius_abs",
    "frequency_step",
    "frequency_step_minimum",
    "frequency_step_maximum",
    "max_newton_iterations",
    "root_correction_tolerance",
})
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
    # An exterior promoted determinant lacked one of its mandatory empirical
    # same-point, preceding-tier, or endpoint/series comparisons.
    "EXTERIOR_DETERMINANT_CERTIFICATE_UNAVAILABLE",
    # The finite-difference ladder was exhausted without a step at which the
    # derivative estimates agree and determinant noise does not dominate.
    "FINITE_DIFFERENCE_NOISE_LIMIT",
    "HORIZON_GEOMETRY_EXHAUSTED",
    "HORIZON_MAXIMUM_ORDER_INADEQUATE",
    "HORIZON_ARITHMETIC_INADEQUATE",
    "HORIZON_COORDINATE_INVERSION_FAILED",
    "HORIZON_ONLY_ONE_ENDPOINT",
    "COORDINATE_IDENTITY_MISMATCH",
    "ODE_SOLVER_FAILURE",
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

    def __init__(
        self,
        message: str,
        failure_code: str,
        *,
        control_receipt: ValidatedControlReceipt | None = None,
    ) -> None:
        if failure_code not in NUMERICAL_CONTROL_FAILURE_CODES:
            raise ValueError("numerical-control failure code is not recognized")
        super().__init__(message)
        self.failure_code = failure_code
        self.control_receipt = control_receipt


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
    """Return the provisional promoted control profile.

    Scientific root acceptance uses the solver's established binary64
    correction threshold of 2e-11 at base and refinement, for both the 80- and
    120-digit tiers. The former 1e-18 and 1e-20 promoted thresholds were
    uncalibrated policy choices, not scientific requirements. Working precision
    supplies guard digits against cancellation, carrier changes, and finite
    differencing; it does not silently tighten the root-acceptance criterion.

    The previous table derived the 120-digit controls mechanically from the
    stored digit count (``10**-(digits - 18)``), which demanded a 1e-102 root
    target -- hence 108 required reliable digits -- and applied that same
    tolerance to the coordinate map. That is what pinned Leaf 13's coordinate
    solve at 8.1e-17 steps: 2,000,002 RHS evaluations and 87.8 s to cover
    1.01e-11 of a 5000 span. More stored digits do not make a QNM root more
    accurately defined.

    The 120-digit tier therefore spends its extra digits as guard. Its ODE
    controls are tightened by a bounded factor over the demonstrated-healthy
    80-digit level (1e-18 / 1e-20 homogeneous, reached in 2,978 RHS evaluations
    on the exact Leaf 13 leg), not driven to the arithmetic floor.

    The coordinate map gets its own, looser controls. It is a scalar quadrature
    for r(rho) and only has to avoid dominating the determinant error budget;
    it does not need the homogeneous solve's local-error target.

    The ODE, coordinate, and finite-difference control values remain explicitly
    ``UNMEASURED``. The root-acceptance threshold is not a calibration claim:
    it is the existing binary64 scientific standard. The horizon request policy
    carries the control-profile status, and release admission remains blocked
    until ``tools/calibrate_leaf13_horizon_controls.jl`` produces a valid native
    receipt and a reviewed profile is committed. Arithmetic work can use this
    bounded provisional profile to obtain that evidence; it cannot call the
    profile calibrated merely because the values are present in source.
    """

    return {
        "80": {
            "base": {
                "root_correction_tolerance": "2e-11",
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
                "root_correction_tolerance": "2e-11",
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
                "root_correction_tolerance": "2e-11",
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
                "root_correction_tolerance": "2e-11",
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

    The initial candidate ladder is shallow on purpose, but adaptive recovery
    may deepen it to rho = -400.  The real-inner contour and the recovery
    search therefore share that same authenticated floor; otherwise recovery
    would manufacture candidates outside the contour that must evaluate them.
    """

    return {
        "horizon_rho_inner_min": "-400",
        "horizon_endpoint_rho_floor": "-400",
        "horizon_endpoint_rho_candidates": [
            "-10", "-25", "-50", "-75", "-100",
        ],
        "horizon_maximum_endpoint_distance": "0.1",
    }


def _merge_policy_fragments(
    *fragments: Mapping[str, object],
) -> dict[str, object]:
    """Merge authenticated policy fragments without last-writer-wins drift."""

    merged: dict[str, object] = {}
    for fragment in fragments:
        for key, value in fragment.items():
            if key in merged:
                raise ValueError(f"duplicate promoted policy field: {key}")
            merged[key] = value
    return merged


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
    candidate = structured.get("execution_resource_policy")
    if structured.get("schema") == "windows-solver.operation-control-receipt/1":
        identity = structured.get("execution_identity")
        if isinstance(identity, Mapping):
            candidate = identity.get("execution_resource_policy_identity")
    if _worker_resource_identity_matches(candidate, execution_resource):
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


def _control_receipt_diagnostics_validator(
    receipt: Mapping[str, object],
    *,
    request_binding: Mapping[str, object],
) -> bool:
    code = receipt.get("failure_code")
    retryable_evidence = receipt.get("retryable_evidence")
    legacy = {
        "failure_code": code,
        "stage": receipt.get("stage"),
        "diagnostics": receipt.get("diagnostics"),
        "retryable": (
            retryable_evidence.get("retryable")
            if isinstance(retryable_evidence, Mapping)
            else None
        ),
        "request_binding": dict(request_binding),
    }
    if code in NUMERICAL_CONTROL_FAILURE_CODES:
        return _valid_numerical_control_diagnostics(
            legacy,
            request_binding=request_binding,
        )
    diagnostics = receipt.get("diagnostics")
    if code in {"ODE_RESOURCE_LIMIT", "ROOT_READOUT_RESOURCE_INFEASIBLE"}:
        return isinstance(diagnostics, Mapping) and bool(diagnostics)
    if code == "WORKER_TIMEOUT":
        return (
            receipt.get("origin") == PYTHON_SUPERVISOR_ORIGIN
            and receipt.get("stage") == "worker-supervision"
            and isinstance(diagnostics, Mapping)
            and diagnostics.get("limiting_resource")
            == "worker_request_wall_clock"
            and isinstance(diagnostics.get("elapsed_request_seconds"), int)
            and diagnostics["elapsed_request_seconds"] > 0
        )
    return False


def validate_persisted_operation_control_receipt(
    receipt: Mapping[str, object],
    canonical_request: Mapping[str, object],
) -> ValidatedControlReceipt:
    """Revalidate a checkpointed worker/supervisor CONTROL proof."""

    try:
        _validated_execution_resource_policy(
            canonical_request.get("execution_resource")
        )
    except JuliaResponseBackendError as error:
        raise ValueError(
            "persisted operation-control resource policy is invalid"
        ) from error
    request_sha256 = hashlib.sha256(
        canonical_json_bytes(dict(canonical_request))
    ).hexdigest()
    return validate_operation_control_receipt(
        receipt,
        request=canonical_request,
        request_sha256=request_sha256,
        diagnostics_validator=lambda value: _control_receipt_diagnostics_validator(
            value,
            request_binding=canonical_request,
        ),
    )


def _bind_control_failure_to_request(
    details: Mapping[str, object],
    request_document: Mapping[str, object],
    request_sha256: str,
) -> tuple[dict[str, object], ValidatedControlReceipt | None]:
    """Validate every CONTROL receipt against the exact canonical request."""

    bound = dict(details)
    structured = bound.get("failure")
    if not isinstance(structured, Mapping) or structured.get("failure_class") != "CONTROL":
        return bound, None
    expected_sha256 = hashlib.sha256(
        canonical_json_bytes(request_document)
    ).hexdigest()
    try:
        if request_sha256 != expected_sha256:
            raise ValueError("request digest mismatch")
        validated = validate_operation_control_receipt(
            structured,
            request=request_document,
            request_sha256=request_sha256,
            diagnostics_validator=lambda receipt: _control_receipt_diagnostics_validator(
                receipt,
                request_binding=request_document,
            ),
        )
    except ValueError as error:
        message = "M02 Julia operation-control request identity mismatch"
        fatal_details = {
            name: details.get(name) for name in _WORKER_FAILURE_BASE_FIELDS
        }
        fatal_details["worker_error_type"] = "OperationControlReceiptError"
        fatal_details["worker_error_message"] = f"{message}: {error}"
        failure = JuliaResponseBackendError(message)
        failure.worker_failure = fatal_details
        raise failure from error
    bound["failure"] = validated.to_mapping()
    return bound, validated


def _raise_worker_failure(
    details: Mapping[str, object],
    *,
    control_receipt: ValidatedControlReceipt | None = None,
) -> None:
    """Raise an operational error while retaining bounded worker diagnostics."""

    details = dict(details)
    structured = details.get("failure")
    if (
        isinstance(structured, Mapping)
        and structured.get("schema") != "windows-solver.operation-control-receipt/1"
    ):
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
        and control_receipt is not None
    ):
        error_class = JuliaNumericalControlError
    else:
        error_class = JuliaResponseBackendError
    if error_class is JuliaNumericalControlError:
        failure = JuliaNumericalControlError(
            message,
            str(structured["failure_code"]),
            control_receipt=control_receipt,
        )
    else:
        failure = error_class(message)
        if control_receipt is not None:
            failure.control_receipt = control_receipt
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


_FACTORED_DIAGNOSTIC_FIELDS = frozenset({
    "reason",
    "precision_bits",
    "factored_homogeneous_rhs_evaluations",
    "avoided_ode_scope",
})
_FACTORED_FAILURE_STAGES = {
    "ASYMPTOTIC_SERIES_INVALID": "asymptotic-preflight",
    "PHYSICAL_SINGULAR_LIMIT": "homogeneous-propagation",
    "CARRIER_CHANGE_INCONSISTENT": "homogeneous-propagation",
    "INVALID_FACTORED_PROPAGATION_INPUT": "homogeneous-propagation",
    "FACTORED_PROPAGATION_PRECISION_MISMATCH": "homogeneous-propagation",
    "NONFINITE_FACTORED_PROPAGATION_DATA": "homogeneous-propagation",
    "FACTORED_ODE_FAILURE": "homogeneous-propagation",
    "NO_VERIFIED_HORIZON_ENDPOINT": "horizon-endpoint-geometry",
}
_ASYMPTOTIC_SERIES_INVALID_REASONS = frozenset({
    "INVALID_ASYMPTOTIC_INPUT",
    "PRECISION_MISMATCH",
    "NONFINITE_ASYMPTOTIC_DATA",
})

_HORIZON_RECOVERY_FAILURES = {
    "HORIZON_GEOMETRY_EXHAUSTED": (
        "no-geometry-valid-candidate/v1",
        "horizon-endpoint-geometry",
        False,
    ),
    "HORIZON_MAXIMUM_ORDER_INADEQUATE": (
        "maximum-series-order-inadequate/v1",
        "horizon-endpoint-geometry",
        False,
    ),
    "HORIZON_ARITHMETIC_INADEQUATE": (
        "arithmetic-precision-inadequate/v1",
        "horizon-endpoint-geometry",
        True,
    ),
    "HORIZON_COORDINATE_INVERSION_FAILED": (
        "coordinate-inversion-failure/v1",
        "coordinate-inversion",
        False,
    ),
    "HORIZON_ONLY_ONE_ENDPOINT": (
        "fewer-than-two-verified-endpoints/v1",
        "horizon-endpoint-geometry",
        False,
    ),
}


def _has_exact_fields(
    value: Mapping[str, object], fields: frozenset[str]
) -> bool:
    return set(value) == fields


def _is_nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def _is_positive_int(value: object) -> bool:
    return type(value) is int and value > 0


def _diagnostic_decimal(
    diagnostics: Mapping[str, object],
    name: str,
    *,
    nonnegative: bool = False,
    positive: bool = False,
) -> Decimal | None:
    try:
        value = _finite_decimal_text(
            diagnostics.get(name), f"failure {name}", nonnegative=nonnegative
        )
    except JuliaResponseBackendError:
        return None
    if positive and value <= 0:
        return None
    return value


def _valid_factored_diagnostics(
    code: str, stage: object, diagnostics: Mapping[str, object]
) -> bool:
    if stage != _FACTORED_FAILURE_STAGES.get(code):
        return False
    if not _has_exact_fields(diagnostics, _FACTORED_DIAGNOSTIC_FIELDS):
        return False
    reason = diagnostics.get("reason")
    if code == "ASYMPTOTIC_SERIES_INVALID":
        if reason not in _ASYMPTOTIC_SERIES_INVALID_REASONS:
            return False
    elif reason != code:
        return False
    rhs = diagnostics.get("factored_homogeneous_rhs_evaluations")
    return (
        _is_positive_int(diagnostics.get("precision_bits"))
        and _is_nonnegative_int(rhs)
        and diagnostics.get("avoided_ode_scope")
        == "factored-homogeneous-gsn/v1"
        and (code != "NO_VERIFIED_HORIZON_ENDPOINT" or rhs == 0)
    )


def _valid_horizon_recovery_diagnostics(
    code: str,
    stage: object,
    diagnostics: Mapping[str, object],
    request_binding: Mapping[str, object] | None,
    *,
    allow_historical_schema7_policy: bool = False,
) -> bool:
    """Authenticate the typed endpoint-recovery outcome and its evidence."""

    expected = _HORIZON_RECOVERY_FAILURES.get(code)
    if expected is None or stage != expected[1]:
        return False
    if not _has_exact_fields(
        diagnostics,
        frozenset({
            "recovery_outcome",
            "recovery_evidence",
            "next_precision_tier_allowed",
        }),
    ):
        return False
    outcome, _, next_tier = expected
    if (
        diagnostics.get("recovery_outcome") != outcome
        or diagnostics.get("next_precision_tier_allowed") is not next_tier
    ):
        return False
    evidence = diagnostics.get("recovery_evidence")
    if not isinstance(evidence, Mapping) or not _has_exact_fields(
        evidence,
        frozenset({
            "outcome",
            "policy_identity",
            "selected_pair",
            "rejected_candidates",
            "endpoint_orders",
            "homogeneous_rhs_evaluations_before_pair",
        }),
    ):
        return False
    if request_binding is None:
        return False
    try:
        _validated_successful_horizon_endpoint_search_evidence(
            [dict(evidence)],
            request_binding,
            expected_outcome=outcome,
            required_selected_count=0,
            allow_historical_schema7_policy=(
                allow_historical_schema7_policy
            ),
            require_complete_candidate_schedule=(
                code != "HORIZON_COORDINATE_INVERSION_FAILED"
                and not allow_historical_schema7_policy
            ),
        )
    except ValueError:
        return False
    return True


def _valid_insufficient_precision_diagnostics(
    stage: object, diagnostics: Mapping[str, object]
) -> bool:
    fields = _FACTORED_DIAGNOSTIC_FIELDS | {
        "predicted_reliable_digits",
        "required_reliable_digits",
        "asymptotic_preflight_avoided_ode",
        "asymptotic_preflight_reason",
        "maximum_series_digits_lost",
        "maximum_recurrence_digits_lost",
    }
    if stage != "asymptotic-preflight" or not _has_exact_fields(
        diagnostics, frozenset(fields)
    ):
        return False
    predicted = _diagnostic_decimal(
        diagnostics, "predicted_reliable_digits"
    )
    required = _diagnostic_decimal(
        diagnostics, "required_reliable_digits", positive=True
    )
    series_loss = _diagnostic_decimal(
        diagnostics, "maximum_series_digits_lost", nonnegative=True
    )
    recurrence_loss = _diagnostic_decimal(
        diagnostics, "maximum_recurrence_digits_lost", nonnegative=True
    )
    return (
        predicted is not None
        and required is not None
        and predicted < required
        and series_loss is not None
        and recurrence_loss is not None
        and diagnostics.get("reason")
        == "INSUFFICIENT_ASYMPTOTIC_PRECISION"
        and _is_positive_int(diagnostics.get("precision_bits"))
        and diagnostics.get("factored_homogeneous_rhs_evaluations") == 0
        and diagnostics.get("avoided_ode_scope")
        == "factored-homogeneous-gsn/v1"
        and diagnostics.get("asymptotic_preflight_avoided_ode") is True
        and diagnostics.get("asymptotic_preflight_reason")
        == "INSUFFICIENT_ASYMPTOTIC_PRECISION"
    )


def _valid_scattering_diagnostics(
    code: str, stage: object, diagnostics: Mapping[str, object]
) -> bool:
    expected_stage = (
        "scattering-extraction"
        if code == "SCATTERING_BASIS_ILL_CONDITIONED"
        else "determinant-chart"
    )
    if stage != expected_stage:
        return False
    package_fields = frozenset({"reason", "precision_bits"})
    if _has_exact_fields(diagnostics, package_fields):
        return (
            diagnostics.get("reason") == code
            and _is_positive_int(diagnostics.get("precision_bits"))
        )
    if code != "SCATTERING_CHART_ILL_CONDITIONED" or not _has_exact_fields(
        diagnostics,
        frozenset({
            "chart_denominator_abs",
            "chart_scale_abs",
            "chart_relative_margin",
        }),
    ):
        return False
    denominator = _diagnostic_decimal(
        diagnostics, "chart_denominator_abs", positive=True
    )
    scale = _diagnostic_decimal(diagnostics, "chart_scale_abs", positive=True)
    margin = _diagnostic_decimal(
        diagnostics, "chart_relative_margin", positive=True
    )
    return denominator is not None and scale is not None and margin is not None


def _valid_coordinate_stall_diagnostics(
    stage: object, diagnostics: Mapping[str, object]
) -> bool:
    fields = frozenset({
        "reason",
        "range_status",
        "operation",
        "stall_reason",
        "ode_leg",
        "ode_t_current",
        "ode_t_end",
        "ode_span_abs",
        "ode_span_fraction",
        "ode_rhs_evaluations",
        "ode_accepted_steps",
        "ode_rejected_steps",
        "ode_last_accepted_step_abs",
        "ode_min_accepted_step_abs",
        "current_r_re",
        "current_r_im",
        "coordinate_identity_residual_abs",
        "elapsed_leg_seconds",
    })
    if stage != "coordinate-inversion" or not _has_exact_fields(
        diagnostics, fields
    ):
        return False
    if (
        diagnostics.get("reason") != "COORDINATE_INVERSION_STALLED"
        or diagnostics.get("range_status")
        != "coordinate-inversion-stalled/v1"
        or diagnostics.get("operation") != "coordinate-inversion/v1"
        or not isinstance(diagnostics.get("stall_reason"), str)
        or not diagnostics["stall_reason"]
        or not isinstance(diagnostics.get("ode_leg"), str)
        or not diagnostics["ode_leg"].startswith("r_from_rho")
        or not _is_nonnegative_int(diagnostics.get("ode_rhs_evaluations"))
        or not _is_nonnegative_int(diagnostics.get("ode_accepted_steps"))
        or not _is_nonnegative_int(diagnostics.get("ode_rejected_steps"))
    ):
        return False
    for name in (
        "ode_t_current",
        "ode_t_end",
        "current_r_re",
        "current_r_im",
    ):
        if _diagnostic_decimal(diagnostics, name) is None:
            return False
    if _diagnostic_decimal(
        diagnostics, "ode_span_abs", positive=True
    ) is None:
        return False
    if _diagnostic_decimal(
        diagnostics, "coordinate_identity_residual_abs", nonnegative=True
    ) is None:
        return False
    for name in (
        "ode_span_fraction",
        "ode_last_accepted_step_abs",
        "ode_min_accepted_step_abs",
    ):
        value = diagnostics.get(name)
        if value is not None and _diagnostic_decimal(
            diagnostics, name, nonnegative=True
        ) is None:
            return False
    elapsed = diagnostics.get("elapsed_leg_seconds")
    try:
        elapsed_seconds = _finite_text(elapsed, "failure elapsed_leg_seconds")
    except JuliaResponseBackendError:
        return False
    return elapsed_seconds >= 0


def _valid_finite_difference_noise_diagnostics(
    stage: object, diagnostics: Mapping[str, object]
) -> bool:
    fields = frozenset({
        "nominal_step",
        "minimum_step",
        "maximum_step",
        "attempts",
    })
    if stage != "finite-difference" or not _has_exact_fields(
        diagnostics, fields
    ):
        return False
    nominal = _diagnostic_decimal(diagnostics, "nominal_step", positive=True)
    minimum = _diagnostic_decimal(diagnostics, "minimum_step", positive=True)
    maximum = _diagnostic_decimal(diagnostics, "maximum_step", positive=True)
    attempts = diagnostics.get("attempts")
    if (
        nominal is None
        or minimum is None
        or maximum is None
        or not minimum <= nominal <= maximum
        or not isinstance(attempts, list)
        or not 1 <= len(attempts) <= 64
    ):
        return False
    attempt_fields = frozenset({
        "h",
        "real_step_convergent",
        "complex_axis_consistent",
        "noise_resolved",
        "derivative_abs",
        "derivative_uncertainty_abs",
        "base_derivative_error_abs",
        "half_derivative_error_abs",
        "double_derivative_error_abs",
        "imaginary_derivative_error_abs",
        "derivative_error_abs",
        "accepted",
    })
    numeric_fields = attempt_fields - {
        "real_step_convergent",
        "complex_axis_consistent",
        "noise_resolved",
        "accepted",
    }
    for attempt in attempts:
        if not isinstance(attempt, Mapping) or not _has_exact_fields(
            attempt, attempt_fields
        ):
            return False
        if any(
            type(attempt.get(name)) is not bool
            for name in (
                "real_step_convergent",
                "complex_axis_consistent",
                "noise_resolved",
                "accepted",
            )
        ):
            return False
        for name in numeric_fields:
            if _diagnostic_decimal(
                attempt,
                name,
                nonnegative=True,
                positive=name == "h",
            ) is None:
                return False
        h = _diagnostic_decimal(attempt, "h", positive=True)
        if h is None or not minimum <= h <= maximum:
            return False
        if attempt["derivative_error_abs"] != attempt[
            "half_derivative_error_abs"
        ]:
            return False
        gates_pass = (
            attempt["real_step_convergent"]
            and attempt["complex_axis_consistent"]
            and attempt["noise_resolved"]
        )
        if attempt["accepted"] is not gates_pass or attempt["accepted"]:
            return False
    return True


def _valid_determinant_uncertainty_diagnostics(
    stage: object, diagnostics: Mapping[str, object]
) -> bool:
    if stage != "root-authentication":
        return False
    newton_fields = frozenset({
        "determinant_abs",
        "determinant_error_abs",
        "derivative_abs",
        "derivative_error_abs",
        "derivative_lower_bound_abs",
        "frequency_step",
    })
    authenticated_derivative_fields = newton_fields | {
        "derivative_uncertainty_abs"
    }
    small_determinant_fields = frozenset({
        "determinant_abs",
        "determinant_error_abs",
        "correction_upper_bound",
        "correction_without_error",
        "root_correction_tolerance",
        "derivative_lower_bound_abs",
        "root_authentication",
    })
    fields = frozenset(diagnostics)
    if fields in {newton_fields, authenticated_derivative_fields}:
        for name in fields - {"derivative_lower_bound_abs"}:
            if _diagnostic_decimal(
                diagnostics,
                name,
                nonnegative=True,
                positive=name == "frequency_step",
            ) is None:
                return False
        lower = _diagnostic_decimal(
            diagnostics, "derivative_lower_bound_abs"
        )
        return lower is not None and lower <= 0
    if fields != small_determinant_fields:
        return False
    numeric_small_determinant_fields = (
        small_determinant_fields - {"root_authentication"}
    )
    values = {
        name: _diagnostic_decimal(
            diagnostics,
            name,
            nonnegative=True,
            positive=name
            in {"root_correction_tolerance", "derivative_lower_bound_abs"},
        )
        for name in numeric_small_determinant_fields
    }
    if any(value is None for value in values.values()):
        return False
    try:
        authentication = RootAuthenticationEvidence.from_mapping(
            diagnostics["root_authentication"]
        )
        authentication.validate_binding(
            determinant_abs=values["determinant_abs"],
            derivative_abs=authentication.derivative_estimate.magnitude(),
            expected_error_model_id=VERIFIED_ENDPOINT_ERROR_MODEL,
            root_correction_tolerance=values[
                "root_correction_tolerance"
            ],
            accepted=False,
        )
    except (KeyError, ValueError):
        return False
    if (
        authentication.accepted
        or authentication.error_breakdown is None
        or authentication.error_breakdown.numerical_error_abs
        != values["determinant_error_abs"]
        or authentication.derivative_lower_bound_abs
        != values["derivative_lower_bound_abs"]
        or authentication.correction_upper_bound
        != values["correction_upper_bound"]
    ):
        return False
    return (
        values["correction_upper_bound"]
        > values["root_correction_tolerance"]
        and values["correction_without_error"]
        <= values["root_correction_tolerance"]
    )


def _valid_exterior_certificate_unavailable_diagnostics(
    stage: object, diagnostics: Mapping[str, object]
) -> bool:
    """Validate the fail-closed receipt when an exterior term is missing."""

    if stage not in {"asymptotic-preflight", "determinant-chart"}:
        return False
    reason = diagnostics.get("reason")
    if reason not in {
        "TWO_AUTHENTICATED_EXTERIOR_ENDPOINTS_REQUIRED",
        "ENDPOINT_SERIES_DISAGREEMENT_UNAVAILABLE",
        "BASE_ENDPOINT_SERIES_EVIDENCE_UNAVAILABLE",
        "TIGHT_ENDPOINT_SERIES_EVIDENCE_UNAVAILABLE",
        "SAME_POINT_DISAGREEMENT_UNAVAILABLE",
        "CROSS_PRECISION_DISAGREEMENT_UNAVAILABLE",
        "CROSS_PRECISION_FAMILY_MISMATCH",
        "CROSS_PRECISION_DISAGREEMENT_NONFINITE",
        "EXTERIOR_CERTIFICATE_TERM_NONFINITE",
    }:
        return False
    allowed = {
        "reason",
        "available_adequate_endpoint_count",
        "candidates",
        "factored_homogeneous_rhs_evaluations_before_pair",
        "preceding_precision_tier",
        "cause_type",
    }
    if not set(diagnostics).issubset(allowed):
        return False
    if reason == "TWO_AUTHENTICATED_EXTERIOR_ENDPOINTS_REQUIRED":
        return (
            stage == "asymptotic-preflight"
            and isinstance(diagnostics.get("available_adequate_endpoint_count"), int)
            and diagnostics["available_adequate_endpoint_count"] < 2
            and isinstance(diagnostics.get("candidates"), list)
            and diagnostics.get("factored_homogeneous_rhs_evaluations_before_pair")
            == 0
        )
    return stage == "determinant-chart"


def _valid_algebraic_singularity_diagnostics(
    stage: object, diagnostics: Mapping[str, object]
) -> bool:
    if _has_exact_fields(diagnostics, _FACTORED_DIAGNOSTIC_FIELDS):
        return (
            stage == "homogeneous-propagation"
            and diagnostics.get("reason")
            == "ALGEBRAIC_REPRESENTATION_SINGULAR"
            and _is_positive_int(diagnostics.get("precision_bits"))
            and _is_nonnegative_int(
                diagnostics.get("factored_homogeneous_rhs_evaluations")
            )
            and diagnostics.get("avoided_ode_scope")
            == "factored-homogeneous-gsn/v1"
        )
    fd_fields = frozenset({"reason", "range_status", "operation", "axis", "h"})
    if _has_exact_fields(diagnostics, fd_fields):
        h = _diagnostic_decimal(diagnostics, "h", positive=True)
        return (
            stage == "finite-difference"
            and isinstance(diagnostics.get("reason"), str)
            and diagnostics["reason"]
            and diagnostics.get("range_status") == diagnostics["reason"]
            and diagnostics.get("operation")
            == "finite-difference-derivative/v1"
            and diagnostics.get("axis") in {"real", "imaginary"}
            and h is not None
        )
    chart_fields = frozenset({"chart_denominator_abs", "chart_scale_abs"})
    if _has_exact_fields(diagnostics, chart_fields):
        denominator = _diagnostic_decimal(
            diagnostics, "chart_denominator_abs", nonnegative=True
        )
        scale = _diagnostic_decimal(
            diagnostics, "chart_scale_abs", nonnegative=True
        )
        return (
            stage == "determinant-chart"
            and denominator == 0
            and scale is not None
        )
    guard_fields = frozenset({
        "guard_precision_digits",
        "guard_working_precision_bits",
        "determinant_abs",
        "guard_determinant_abs",
    })
    if _has_exact_fields(diagnostics, guard_fields):
        return (
            stage == "determinant-chart"
            and _is_positive_int(diagnostics.get("guard_precision_digits"))
            and _is_positive_int(
                diagnostics.get("guard_working_precision_bits")
            )
            and isinstance(diagnostics.get("determinant_abs"), str)
            and isinstance(diagnostics.get("guard_determinant_abs"), str)
        )
    policy_base = frozenset({
        "reason",
        "range_status",
        "operation",
        "axis",
        "h",
        "frequency_step",
    })
    policy_wide = policy_base | {
        "frequency_step_minimum",
        "frequency_step_maximum",
    }
    if frozenset(diagnostics) not in {policy_base, policy_wide}:
        return False
    return (
        stage in {"request-policy", "determinant-chart"}
        and diagnostics.get("reason") == "INVALID_FREQUENCY_STEP"
        and diagnostics.get("range_status") == "invalid-frequency-step/v1"
        and diagnostics.get("operation")
        == "finite-difference-request-policy/v1"
        and diagnostics.get("axis") == "request-policy"
        and all(
            isinstance(diagnostics.get(name), str)
            for name in frozenset(diagnostics) - {
                "reason",
                "range_status",
                "operation",
                "axis",
            }
        )
    )


def _valid_numerical_control_diagnostics(
    failure: Mapping[str, object],
    *,
    request_binding: Mapping[str, object] | None = None,
    allow_historical_schema7_policy: bool = False,
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
    stage = failure.get("stage")
    if stage not in CONTROL_FAILURE_STAGES:
        return False
    code = failure.get("failure_code")
    if not isinstance(code, str):
        return False
    # These two codes share the factored-propagation exception family but
    # carry richer, code-specific evidence.  Dispatch them before the generic
    # four-field factored validator or their additional proof fields make an
    # otherwise valid receipt fail exact-field validation.
    if code == "INSUFFICIENT_ASYMPTOTIC_PRECISION":
        return _valid_insufficient_precision_diagnostics(stage, diagnostics)
    if code == "ALGEBRAIC_REPRESENTATION_SINGULAR":
        return _valid_algebraic_singularity_diagnostics(stage, diagnostics)
    if code in _FACTORED_FAILURE_STAGES:
        return _valid_factored_diagnostics(code, stage, diagnostics)
    if code in _HORIZON_RECOVERY_FAILURES:
        if failure.get("retryable") is not _HORIZON_RECOVERY_FAILURES[code][2]:
            return False
        if request_binding is None:
            raw_request = failure.get("request_binding")
            request_binding = raw_request if isinstance(raw_request, Mapping) else None
        return _valid_horizon_recovery_diagnostics(
            code,
            stage,
            diagnostics,
            request_binding,
            allow_historical_schema7_policy=(
                allow_historical_schema7_policy
            ),
        )
    if code in {
        "SCATTERING_BASIS_ILL_CONDITIONED",
        "SCATTERING_CHART_ILL_CONDITIONED",
    }:
        return _valid_scattering_diagnostics(code, stage, diagnostics)
    if code == "COORDINATE_INVERSION_STALLED":
        return _valid_coordinate_stall_diagnostics(stage, diagnostics)
    if code == "FINITE_DIFFERENCE_NOISE_LIMIT":
        return _valid_finite_difference_noise_diagnostics(stage, diagnostics)
    if code == "DETERMINANT_UNCERTAINTY_TOO_LARGE":
        return _valid_determinant_uncertainty_diagnostics(stage, diagnostics)
    if code == "EXTERIOR_DETERMINANT_CERTIFICATE_UNAVAILABLE":
        return _valid_exterior_certificate_unavailable_diagnostics(
            stage, diagnostics
        )
    if code == "COORDINATE_IDENTITY_MISMATCH":
        required_fields = {
            "contour_label",
            "maximum_absolute_residual",
            "maximum_relative_residual",
            "absolute_tolerance",
            "relative_tolerance",
            "sample_count",
            "failure_reason",
        }
        return (
            stage == "coordinate-inversion"
            and required_fields.issubset(diagnostics)
            and _is_positive_int(diagnostics.get("sample_count"))
        )
    if code == "ODE_SOLVER_FAILURE":
        return (
            stage == "homogeneous-propagation"
            and isinstance(diagnostics.get("ode_leg"), str)
            and isinstance(diagnostics.get("ode_snapshot"), Mapping)
        )
    return False


def _timeout_worker_failure_details(
    details: Mapping[str, object],
    request: Mapping[str, object],
    execution_resource: Mapping[str, object],
    last_progress_event: object = None,
) -> dict[str, object]:
    """Attach a bounded control receipt to a forced outer worker timeout."""

    output = dict(details)
    raw_identity = request.get("execution_identity")
    if not isinstance(raw_identity, Mapping):
        raise JuliaResponseBackendError(
            "worker timeout request execution identity is absent"
        )
    identity = operation_execution_identity(raw_identity)
    diagnostics: dict[str, object] = {
        "elapsed_request_seconds": execution_resource[
            "worker_request_wall_clock_seconds"
        ],
        "limiting_resource": "worker_request_wall_clock",
        "precision_digits": request.get("precision_digits"),
        "execution_resource_policy": dict(execution_resource),
    }
    progress_fields = _timeout_progress_failure_fields(last_progress_event)
    if progress_fields:
        diagnostics["last_validated_progress"] = progress_fields
    output["failure"] = build_operation_control_receipt(
        origin=PYTHON_SUPERVISOR_ORIGIN,
        failure_code="WORKER_TIMEOUT",
        stage="worker-supervision",
        identity=identity,
        retryable=True,
        retryable_basis="bounded worker wall-clock resource exhausted/v1",
        diagnostics=diagnostics,
    )
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


def _resolve_promoted_request_preflight_cache(
    runtime_root: Path,
) -> PromotedRequestPreflightStore:
    override = os.environ.get("KERR_QNM_PROMOTED_REQUEST_PREFLIGHT_CACHE_ROOT")
    root = (
        Path(override)
        if override
        else Path(runtime_root) / PROMOTED_REQUEST_PREFLIGHT_CACHE_DIRECTORY_NAME
    )
    return PromotedRequestPreflightStore(root)


def _worker_request_document(
    request: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, object], str]:
    """Return the request binding, wire document, and canonical wire digest."""

    request_binding = dict(request)
    execution_resource = _validated_execution_resource_policy(
        request_binding["execution_resource"]
        if "execution_resource" in request_binding
        else _execution_resource_policy()
    )
    request_binding["execution_resource"] = execution_resource
    request_sha256 = hashlib.sha256(
        canonical_json_bytes(request_binding)
    ).hexdigest()
    document = dict(request_binding)
    document["request_sha256"] = request_sha256
    document["execution_identity"] = execution_identity_from_request(
        request_binding,
        request_sha256=request_sha256,
    ).to_mapping()
    return request_binding, document, request_sha256


def _promoted_request_set(
    requests: tuple[Mapping[str, object], ...],
) -> tuple[dict[str, object], tuple[str, ...]]:
    documents: list[dict[str, object]] = []
    request_sha256s: list[str] = []
    for request in requests:
        _, document, request_sha256 = _worker_request_document(request)
        documents.append(document)
        request_sha256s.append(request_sha256)
    payload = {
        "schema_version": 1,
        "operation": _PROMOTED_REQUEST_PREFLIGHT_OPERATION,
        "requests": documents,
    }
    request_set_sha256 = hashlib.sha256(
        canonical_json_bytes(payload)
    ).hexdigest()
    return {
        **payload,
        "request_set_sha256": request_set_sha256,
    }, tuple(request_sha256s)


def _validate_promoted_request_preflight_response(
    response: Mapping[str, object],
    *,
    request_set_sha256: str,
    request_sha256s: tuple[str, ...],
) -> dict[str, object]:
    expected_fields = {
        "schema_version",
        "status",
        "operation",
        "request_count",
        "request_set_sha256",
        "request_sha256s",
    }
    if not isinstance(response, Mapping) or set(response) != expected_fields:
        raise JuliaResponseBackendError(
            "M02 promoted-request preflight response fields are invalid"
        )
    if (
        type(response["schema_version"]) is not int
        or response["schema_version"] != 1
        or response["status"] != "ok"
        or response["operation"] != _PROMOTED_REQUEST_PREFLIGHT_OPERATION
        or type(response["request_count"]) is not int
        or response["request_count"] != len(request_sha256s)
        or response["request_set_sha256"] != request_set_sha256
        or response["request_sha256s"] != list(request_sha256s)
    ):
        raise JuliaResponseBackendError(
            "M02 promoted-request preflight response authentication failed"
        )
    return dict(response)


@dataclass(frozen=True, slots=True)
class JuliaResponseEvaluation:
    """One worker response plus the exact identities required to validate it."""

    response: Mapping[str, object]
    request_binding: Mapping[str, object]
    request_sha256: str
    runtime_identity_sha256: str
    reused: bool
    cached_worker_response_receipt: Mapping[str, object] | None


def _survey_complex_mapping(value: complex) -> dict[str, str]:
    converted = complex(value)
    if not math.isfinite(converted.real) or not math.isfinite(converted.imag):
        raise ValueError("fixed-root survey coordinate is nonfinite")
    return {
        "real": format(converted.real, ".17g"),
        "imaginary": format(converted.imag, ".17g"),
    }


def _survey_complex_from_mapping(value: object, label: str) -> complex:
    if not isinstance(value, Mapping) or set(value) != {"real", "imaginary"}:
        raise JuliaResponseBackendError(f"M02 {label} fields are invalid")
    return complex(
        float(_finite_decimal_text(value["real"], f"{label} real")),
        float(_finite_decimal_text(value["imaginary"], f"{label} imaginary")),
    )


def _survey_decimal_complex_from_mapping(
    value: object, label: str
) -> DecimalComplex:
    if not isinstance(value, Mapping) or set(value) != {"real", "imaginary"}:
        raise JuliaResponseBackendError(f"M02 {label} fields are invalid")
    return DecimalComplex(
        _finite_decimal_text(value["real"], f"{label} real"),
        _finite_decimal_text(value["imaginary"], f"{label} imaginary"),
    )


@dataclass(frozen=True, slots=True)
class FixedRootSurveyConditioning:
    """Bounded, survey-only conditioning telemetry for one raw sample."""

    mapping: Mapping[str, object]

    def __post_init__(self) -> None:
        fields = {
            "schema",
            "fixed_root_reliability_target_abs",
            "fixed_root_reliability_rule",
            "determinant_family",
            "homogeneous_representation",
            "branch_convention",
            "determinant_convention",
            "determinant_normalisation",
            "maximum_series_digits_lost",
            "maximum_recurrence_digits_lost",
            "minimum_asymptotic_predicted_reliable_digits",
            "endpoint_remainders_regular",
            "maximum_endpoint_reconstruction_error",
            "maximum_contour_angle_deformation",
            "predicted_reliable_digits",
            "required_reliable_digits",
            "precision_limited",
            "determinant_count",
        }
        if not isinstance(self.mapping, Mapping) or set(self.mapping) != fields:
            raise ValueError("fixed-root survey conditioning fields are invalid")
        if self.mapping["schema"] != FIXED_ROOT_SURVEY_CONDITIONING_SCHEMA:
            raise ValueError("fixed-root survey conditioning schema is invalid")
        target = _finite_decimal_text(
            self.mapping["fixed_root_reliability_target_abs"],
            "fixed-root survey conditioning reliability target",
            nonnegative=True,
        )
        if target <= 0 or target >= 1:
            raise ValueError(
                "fixed-root survey conditioning reliability target is invalid"
            )
        if self.mapping["fixed_root_reliability_rule"] != FIXED_ROOT_RELIABILITY_RULE:
            raise ValueError(
                "fixed-root survey conditioning reliability rule is invalid"
            )
        for name in (
            "determinant_family",
            "homogeneous_representation",
            "branch_convention",
            "determinant_convention",
            "determinant_normalisation",
        ):
            if not isinstance(self.mapping[name], str) or not self.mapping[name]:
                raise ValueError(f"fixed-root survey conditioning {name} is invalid")
        for name in (
            "maximum_series_digits_lost",
            "maximum_recurrence_digits_lost",
            "minimum_asymptotic_predicted_reliable_digits",
            "maximum_endpoint_reconstruction_error",
            "maximum_contour_angle_deformation",
            "predicted_reliable_digits",
            "required_reliable_digits",
        ):
            _finite_decimal_text(
                self.mapping[name],
                f"fixed-root survey conditioning {name}",
                nonnegative=True,
            )
        if (
            type(self.mapping["endpoint_remainders_regular"]) is not bool
            or type(self.mapping["precision_limited"]) is not bool
            or self.mapping["determinant_count"] != 1
        ):
            raise ValueError("fixed-root survey conditioning bounds are invalid")
        object.__setattr__(
            self,
            "mapping",
            json.loads(canonical_json_bytes(dict(self.mapping))),
        )

    def to_mapping(self) -> dict[str, object]:
        return dict(self.mapping)


EXTERIOR_DETERMINANT_ERROR_EVIDENCE_SCHEMA = (
    "windows-solver.exterior-determinant-error-evidence/1"
)


@dataclass(frozen=True, slots=True)
class ExteriorDeterminantErrorEvidence:
    """The worker's own per-sample empirical determinant-error certificate.

    This is raw evidence, not yet an admitted receipt: it authenticates only
    that the worker returned a well-formed, internally consistent
    certificate for this sample. Whether it is admissible as durable
    ``reviewed-determinant-error`` evidence is decided by the operator-
    approved issuance boundary, never by this parser alone.
    """

    mapping: Mapping[str, object]

    def __post_init__(self) -> None:
        fields = {
            "schema",
            "error_model_id",
            "delta_same_point",
            "delta_cross_precision",
            "delta_endpoint_series",
            "safety_factor",
            "numerical_error_abs",
        }
        if not isinstance(self.mapping, Mapping) or set(self.mapping) != fields:
            raise ValueError("exterior determinant-error evidence fields are invalid")
        if self.mapping["schema"] != EXTERIOR_DETERMINANT_ERROR_EVIDENCE_SCHEMA:
            raise ValueError("exterior determinant-error evidence schema is invalid")
        if (
            not isinstance(self.mapping["error_model_id"], str)
            or not self.mapping["error_model_id"]
        ):
            raise ValueError("exterior determinant-error evidence model is invalid")
        for name in (
            "delta_same_point",
            "delta_cross_precision",
            "delta_endpoint_series",
            "safety_factor",
            "numerical_error_abs",
        ):
            _finite_decimal_text(
                self.mapping[name],
                f"exterior determinant-error evidence {name}",
                nonnegative=True,
            )
        object.__setattr__(
            self,
            "mapping",
            json.loads(canonical_json_bytes(dict(self.mapping))),
        )

    def to_mapping(self) -> dict[str, object]:
        return dict(self.mapping)


@dataclass(frozen=True, slots=True)
class JuliaFixedRootSurveySample:
    sample_index: int
    sample_role: str
    omega: complex
    amplitude: complex
    determinant: DecimalComplex
    numerical_conditioning: FixedRootSurveyConditioning
    execution_identity: Mapping[str, object]
    determinant_error_evidence: ExteriorDeterminantErrorEvidence | None = None

    @property
    def role(self) -> str:
        """Compatibility projection; persistence uses ``sample_role``."""

        return self.sample_role


@dataclass(frozen=True, slots=True)
class JuliaFixedRootSurveyBatch:
    leaf_id: str
    job_id: str
    mechanism_id: str
    root_reference_id: str
    root_seal_sha256: str
    branch_identity: str
    fixed_root: complex
    frequency_step: Decimal
    coordinate_step: Decimal
    scientific_operation_identity: str
    plan: FixedRootSurveyPlan
    execution_identity: Mapping[str, object]
    request_sha256: str
    precision_tier: PrecisionTier
    working_precision_bits: int
    samples: tuple[JuliaFixedRootSurveySample, ...]
    maximum_sample_count: int = _FIXED_ROOT_SURVEY_MAXIMUM_SAMPLE_COUNT
    operation: str = FIXED_ROOT_SURVEY_BATCH_OPERATION
    identity: str = BINARY64_FIXED_ROOT_SURVEY_IDENTITY
    julia_launch_count: int = 1
    root_read_count: int = 0

    def __post_init__(self) -> None:
        """Reject a batch whose identity and roles do not name one plan.

        The worker response is a persistence boundary as well as a numerical
        value.  Validate the pair here so an invalid construction cannot be
        cached, composed, or serialized by a later caller.
        """

        resolved_plan = fixed_root_survey_plan_for_pair(
            self.scientific_operation_identity,
            self.sample_roles,
        )
        if self.plan is not resolved_plan:
            raise ValueError("fixed-root survey batch plan is invalid")
        identity = operation_execution_identity(self.execution_identity)
        if (
            identity.scope != REQUEST_SCOPE
            or identity.operation != FIXED_ROOT_SURVEY_BATCH_OPERATION
            or identity.mapping["plan"] != self.plan.value
            or tuple(identity.mapping["sample_roles"]) != self.sample_roles
            or identity.request_sha256 != self.request_sha256
        ):
            raise ValueError("fixed-root survey execution identity is invalid")
        object.__setattr__(self, "execution_identity", identity.to_mapping())
        for index, sample in enumerate(self.samples):
            sample_identity = operation_execution_identity(
                sample.execution_identity
            )
            if (
                sample.sample_index != index
                or sample.sample_role != self.sample_roles[index]
                or sample_identity.to_mapping()
                != identity.select_sample(index, sample.sample_role).to_mapping()
            ):
                raise ValueError("fixed-root survey sample identity is invalid")
        if self.operation != FIXED_ROOT_SURVEY_BATCH_OPERATION:
            raise ValueError("fixed-root survey batch operation is invalid")
        if self.identity != BINARY64_FIXED_ROOT_SURVEY_IDENTITY:
            raise ValueError("fixed-root survey batch identity is invalid")
        if (
            isinstance(self.maximum_sample_count, bool)
            or not isinstance(self.maximum_sample_count, int)
            or self.maximum_sample_count < self.sample_count
            or self.maximum_sample_count > _FIXED_ROOT_SURVEY_MAXIMUM_SAMPLE_COUNT
        ):
            raise ValueError("fixed-root survey batch sample budget is invalid")
        if self.julia_launch_count != 1 or self.root_read_count != 0:
            raise ValueError("fixed-root survey batch worker accounting is invalid")

    @property
    def sample_roles(self) -> tuple[str, ...]:
        return tuple(sample.role for sample in self.samples)

    @property
    def sample_count(self) -> int:
        return len(self.samples)

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema": FIXED_ROOT_SURVEY_BATCH_RESPONSE_SCHEMA,
            "operation": self.operation,
            "identity": self.identity,
            "plan": self.plan.value,
            "execution_identity": copy.deepcopy(dict(self.execution_identity)),
            "scientific_operation_identity": self.scientific_operation_identity,
            "leaf_id": self.leaf_id,
            "job_id": self.job_id,
            "mechanism_id": self.mechanism_id,
            "root_reference_id": self.root_reference_id,
            "root_seal_sha256": self.root_seal_sha256,
            "branch_identity": self.branch_identity,
            "fixed_root": _survey_complex_mapping(self.fixed_root),
            "frequency_step": str(self.frequency_step),
            "coordinate_step": str(self.coordinate_step),
            "request_sha256": self.request_sha256,
            "precision_tier": self.precision_tier.value,
            "working_precision_bits": self.working_precision_bits,
            "sample_roles": list(self.sample_roles),
            "sample_count": self.sample_count,
            "maximum_sample_count": self.maximum_sample_count,
            "julia_launch_count": self.julia_launch_count,
            "root_read_count": self.root_read_count,
            "samples": [
                {
                    "sample_index": sample.sample_index,
                    "sample_role": sample.sample_role,
                    "execution_identity": copy.deepcopy(
                        dict(sample.execution_identity)
                    ),
                    "omega": _survey_complex_mapping(sample.omega),
                    "amplitude": _survey_complex_mapping(sample.amplitude),
                    "determinant": sample.determinant.to_mapping(),
                    "numerical_conditioning": (
                        sample.numerical_conditioning.to_mapping()
                    ),
                    "determinant_error_evidence": (
                        None if sample.determinant_error_evidence is None
                        else sample.determinant_error_evidence.to_mapping()
                    ),
                }
                for sample in self.samples
            ],
        }


@dataclass(frozen=True, slots=True)
class PromotedRequestPreflightResult:
    response: Mapping[str, object]
    binding: Mapping[str, object]
    reused: bool


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
    promoted_request_preflight_cache: (
        PromotedRequestPreflightStore | None
    ) = None

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
            _resolve_promoted_request_preflight_cache(runtime),
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
            emit_progress(
                ProgressEventKind.ROOT_READOUT_CACHE_CORRUPT,
                request_sha256=request_sha256,
                error_type=type(error).__name__,
                message=str(error),
            )
            raise JuliaResponseBackendError(
                "trusted root-readout store lookup failed closed"
            ) from error
        if lookup.status is RootReadoutLookupStatus.CORRUPT:
            emit_progress(
                ProgressEventKind.ROOT_READOUT_CACHE_CORRUPT,
                request_sha256=request_sha256,
                store_path=str(lookup.path),
                message=lookup.reason,
            )
            raise JuliaResponseBackendError(
                "trusted root-readout entry is corrupt: "
                f"{lookup.path}: {lookup.reason}"
            )
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
            raise JuliaResponseBackendError(
                "durable root-readout store is unavailable"
            )
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
            raise JuliaResponseBackendError(
                "validated root readout could not be durably published"
            ) from error
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

    def preflight_promoted_requests(
        self,
        requests: tuple[Mapping[str, object], ...],
        *,
        calibration_receipt_sha256: str,
        policy_sha256: str,
        precision_capabilities_sha256: str,
    ) -> PromotedRequestPreflightResult:
        """Validate actual promoted wire requests without numerical work."""

        if not isinstance(requests, tuple) or not requests:
            raise JuliaResponseBackendError(
                "M02 promoted-request preflight matrix is empty"
            )
        batch, request_sha256s = _promoted_request_set(requests)
        request_set_sha256 = str(batch["request_set_sha256"])
        worker_sha256 = self.runtime_provenance.get("worker_sha256")
        if not isinstance(worker_sha256, str):
            raise JuliaResponseBackendError(
                "M02 promoted-request preflight worker identity is absent"
            )
        try:
            binding = promoted_request_preflight_binding(
                python_backend_source_sha256=_sha256(Path(__file__).resolve()),
                julia_worker_sha256=worker_sha256,
                calibration_receipt_sha256=calibration_receipt_sha256,
                policy_sha256=policy_sha256,
                precision_capabilities_sha256=precision_capabilities_sha256,
                request_set_sha256=request_set_sha256,
            )
        except ValueError as error:
            raise JuliaResponseBackendError(str(error)) from error

        store = self.promoted_request_preflight_cache
        if store is not None:
            try:
                cached = store.lookup(binding)
                if cached is not None:
                    response = _validate_promoted_request_preflight_response(
                        cached,
                        request_set_sha256=request_set_sha256,
                        request_sha256s=request_sha256s,
                    )
                    return PromotedRequestPreflightResult(
                        response, binding, True
                    )
            except (OSError, ValueError, JuliaResponseBackendError):
                # This is a reuse optimization, not scientific evidence. A
                # malformed or unreadable entry is a miss; fresh Julia
                # validation below can atomically replace it without requiring
                # operators to delete a cache.
                pass

        with tempfile.TemporaryDirectory(
            prefix="m02-promoted-request-preflight-"
        ) as temporary:
            directory = Path(temporary)
            request_path = directory / "requests.json"
            response_path = directory / "response.json"
            request_path.write_bytes(canonical_json_bytes(batch))
            environment = os.environ.copy()
            environment["JULIA_DEPOT_PATH"] = str(self.julia_depot)
            environment["JULIA_PKG_OFFLINE"] = "true"
            command = (
                str(self.julia_executable),
                *self.julia_prefix_arguments,
                "--startup-file=no",
                "--history-file=no",
                f"--project={self.julia_project}",
                str(self.worker_script),
                "--validate-request-batch",
                str(request_path),
                str(response_path),
            )
            try:
                completed = self.runner(
                    command,
                    cwd=directory,
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=_PROMOTED_REQUEST_PREFLIGHT_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired as error:
                raise JuliaResponseBackendError(
                    "M02 promoted-request preflight timed out"
                ) from error
            except (OSError, subprocess.SubprocessError) as error:
                raise JuliaResponseBackendError(
                    "M02 promoted-request preflight could not start: "
                    f"{error}"
                ) from error
            response: dict[str, object] | None = None
            if response_path.is_file() and not response_path.is_symlink():
                response = _strict_json_file(
                    response_path, "M02 promoted-request preflight response"
                )
            if getattr(completed, "returncode", None) != 0:
                message = (
                    response.get("message")
                    if isinstance(response, Mapping)
                    else None
                )
                if not isinstance(message, str) or not message:
                    message = _bounded_text(
                        getattr(completed, "stderr", ""), 4000
                    ) or "Julia request validation failed"
                raise JuliaResponseBackendError(
                    f"M02 promoted-request preflight failed: {message}"
                )
            if response is None:
                raise JuliaResponseBackendError(
                    "M02 promoted-request preflight response is absent"
                )
        validated = _validate_promoted_request_preflight_response(
            response,
            request_set_sha256=request_set_sha256,
            request_sha256s=request_sha256s,
        )
        if store is not None:
            try:
                store.publish(binding, validated)
            except (OSError, ValueError):
                # A successful no-solver Julia validation is authoritative even
                # when its reusable optimization receipt cannot be retained.
                pass
        return PromotedRequestPreflightResult(validated, binding, False)

    def _evaluate(
        self, request: Mapping[str, object], *, retain_fresh: bool
    ) -> JuliaResponseEvaluation:
        request_document, document, request_sha256 = _worker_request_document(
            request
        )
        execution_resource = request_document["execution_resource"]
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
                    timeout_details = _timeout_worker_failure_details(
                        {
                            "worker_exit_code": None,
                            "worker_timed_out": True,
                            "worker_stderr_tail": stderr,
                            "worker_error_type": None,
                            "worker_error_message": None,
                        },
                        document,
                        execution_resource,
                    )
                    timeout_details, timeout_receipt = _bind_control_failure_to_request(
                        timeout_details, request_document, request_sha256
                    )
                    _raise_worker_failure(
                        timeout_details,
                        control_receipt=timeout_receipt,
                    )
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
                details, control_receipt = _bind_control_failure_to_request(
                    details, request_document, request_sha256
                )
                _raise_worker_failure(details, control_receipt=control_receipt)
            response = _strict_json_file(response_path, "M02 Julia response")
        if response.get("status") != "ok":
            details = _worker_failure_details(
                completed, response_path, response=response
            )
            _require_worker_resource_identity(details, execution_resource)
            details, control_receipt = _bind_control_failure_to_request(
                details, request_document, request_sha256
            )
            _raise_worker_failure(details, control_receipt=control_receipt)
        if response.get("request_sha256") != request_sha256:
            raise JuliaResponseBackendError("M02 Julia response request digest mismatch")
        if retain_fresh and self.readout_cache is not None:
            self._retain_readout(request_sha256, response)
        return JuliaResponseEvaluation(
            response=dict(response),
            request_binding=request_document,
            request_sha256=request_sha256,
            runtime_identity_sha256=runtime_identity,
            reused=False,
            cached_worker_response_receipt=None,
        )


def _adaptive_ode_request_controls(
    digits: int,
    budget: ODEErrorBudget | None,
) -> dict[str, object]:
    """Bind changed promoted requests to a reviewed, serialized ODE budget."""

    if budget is None:
        raise MissingODECalibrationError(ODE_CALIBRATION_BLOCKER)
    expected_tier = {
        40: PrecisionTier.BIGFLOAT_40,
        80: PrecisionTier.BIGFLOAT_80,
        120: PrecisionTier.BIGFLOAT_120,
    }.get(digits)
    if expected_tier is None or budget.precision_tier is not expected_tier:
        raise ValueError("ODE error budget precision tier does not match request")

    def encoded(value: float) -> str:
        return format(value, ".17g")

    return {
        "coordinate_ode_relative_tolerance": encoded(budget.coordinate_reltol),
        "coordinate_ode_absolute_tolerance": encoded(budget.coordinate_abstol),
        "homogeneous_ode_relative_tolerance": encoded(budget.homogeneous_reltol),
        "homogeneous_ode_absolute_tolerance": encoded(budget.homogeneous_abstol),
        # The generic ODE aliases are authenticated to the homogeneous share;
        # no fixed table is silently renamed for the changed identity.
        "ode_relative_tolerance": encoded(budget.homogeneous_reltol),
        "ode_absolute_tolerance": encoded(budget.homogeneous_abstol),
        "ode_error_budget": budget.to_mapping(),
    }


def _precision_policy(
    job: ResponseComponentJob,
    digits: int,
    refinement: int,
    ode_error_budget: ODEErrorBudget | None = None,
    *,
    empirical_control_profile: EmpiricalControlProfile | None = None,
    calibration_receipt: PromotedControlCalibrationReceipt | None = None,
    diagnostic_model_identity: str | None = None,
    include_control_provenance: bool = False,
) -> dict[str, object]:
    if digits not in _PROMOTED_DIGITS:
        raise ValueError("Julia response precision must be 40, 80, or 120 digits")
    if refinement not in (0, 1):
        raise ValueError("Julia response refinement level must be zero or one")
    level = "base" if refinement == 0 else "refinement"
    if diagnostic_model_identity is None:
        diagnostic_model_identity = (
            VERIFIED_ENDPOINT_ERROR_MODEL
            if job.mechanism_id == "horizon-admittance"
            else EXTERIOR_PROVISIONAL_DETERMINANT_ERROR_MODEL
        )
    if job.mechanism_id == "horizon-admittance":
        if diagnostic_model_identity != VERIFIED_ENDPOINT_ERROR_MODEL:
            raise ValueError("horizon requests require the horizon diagnostic model")
    elif diagnostic_model_identity not in {
        EXTERIOR_PROVISIONAL_DETERMINANT_ERROR_MODEL,
        EXTERIOR_DETERMINANT_ABSOLUTE_ERROR_CERTIFICATE,
    }:
        raise ValueError("exterior diagnostic model identity is invalid")

    profile_mapping: dict[str, object] | None = None
    profile_sha256: str | None = None
    if empirical_control_profile is not None or calibration_receipt is not None:
        if (
            empirical_control_profile is None
            or calibration_receipt is None
            or ode_error_budget is not None
            or empirical_control_profile.nominal_decimal_digits != digits
        ):
            raise ValueError("empirical promoted controls are invalid")
        expected_family = (
            "horizon-scattering/v1"
            if job.mechanism_id == "horizon-admittance"
            else "exterior-wronskian/v1"
        )
        if (
            empirical_control_profile.determinant_family != expected_family
            or calibration_receipt.budget_for(expected_family, digits)
            != empirical_control_profile
        ):
            raise ValueError(
                "empirical control profile disagrees with determinant request"
            )
        profile_mapping = empirical_control_profile.to_mapping()
        profile_sha256 = hashlib.sha256(
            canonical_json_bytes(profile_mapping)
        ).hexdigest()
        numerical_controls: dict[str, object] = {
            **empirical_control_profile.controls_for_refinement(refinement),
        }
    else:
        ode_controls = _adaptive_ode_request_controls(digits, ode_error_budget)
        root_search_controls = {
            (40, "base"): ("1e-6", "1e-12", "1e-3"),
            (40, "refinement"): ("1e-7", "1e-14", "1e-4"),
            (80, "base"): ("1e-6", "1e-12", "1e-3"),
            (80, "refinement"): ("1e-7", "1e-14", "1e-4"),
            (120, "base"): ("1e-6", "1e-16", "1e-3"),
            (120, "refinement"): ("1e-7", "1e-18", "1e-4"),
        }[(digits, level)]
        numerical_controls = {
            "root_correction_tolerance": "2e-11",
            "frequency_step": root_search_controls[0],
            "frequency_step_minimum": root_search_controls[1],
            "frequency_step_maximum": root_search_controls[2],
            **ode_controls,
        }
    if include_control_provenance and profile_mapping is not None:
        numerical_controls.update({
            "promoted_control_calibration_receipt_sha256": (
                calibration_receipt.sha256
                if calibration_receipt is not None
                else None
            ),
            "empirical_control_profile_sha256": profile_sha256,
        })
    if job.mechanism_id == "horizon-admittance":
        numerical_controls["determinant_error_safety_factor"] = "64"
    else:
        preceding_tier = {
            40: "binary64",
            80: "bigfloat-40",
            120: "bigfloat-80",
        }[digits]
        if diagnostic_model_identity == EXTERIOR_PROVISIONAL_DETERMINANT_ERROR_MODEL:
            numerical_controls.update({
                "determinant_error_model": _EXTERIOR_ADDITIVE_CHANNEL_SCHEMA,
                "determinant_error_channel_schema": (
                    _EXTERIOR_ADDITIVE_CHANNEL_SCHEMA
                ),
                "determinant_error_required_channels": (
                    list(_EXTERIOR_ADDITIVE_CHANNELS)
                ),
                "determinant_error_calibration_status": (
                    "MISSING_AUTHENTICATED_CALIBRATION"
                ),
                "determinant_error_missing_evidence_outcome": (
                    "BLOCKED_BY_REVIEWED_ERROR_EVIDENCE"
                ),
                "determinant_error_preceding_precision_tier": preceding_tier,
            })
        else:
            if profile_mapping is None or calibration_receipt is None:
                raise ValueError(
                    "empirical exterior diagnostics require authenticated controls"
                )
            numerical_controls.update({
                "determinant_error_model": (
                    EXTERIOR_DETERMINANT_ABSOLUTE_ERROR_CERTIFICATE
                ),
                "determinant_error_required_term_classes": (
                    list(_EXTERIOR_EMPIRICAL_TERM_CLASSES)
                ),
                "determinant_error_missing_evidence_outcome": (
                    EXTERIOR_DETERMINANT_CERTIFICATE_UNAVAILABLE
                ),
                "determinant_error_certificate_statement": (
                    _EXTERIOR_EMPIRICAL_CERTIFICATE_STATEMENT
                ),
                "determinant_error_preceding_precision_tier": preceding_tier,
                "determinant_error_safety_factor": 64,
                "promoted_control_calibration_receipt_sha256": (
                    calibration_receipt.sha256
                ),
                "empirical_control_profile_sha256": profile_sha256,
            })

    endpoint_series_order = job.policy.endpoint_series_order + 8 * refinement
    policy = _merge_policy_fragments(
        {"readout_radius": format(job.policy.readout_radius, ".17g")},
        horizon_geometry_controls(),
        numerical_controls,
        regularised_gsn_precision_policy(job.mechanism_id),
        {
            "endpoint_series_order": endpoint_series_order,
            "support_subinterval_count": (
                job.policy.support_subinterval_count * (2 ** refinement)
            ),
            "angular_pad": 18 + 8 * refinement,
            "rho_in": "-5000",
            "rho_out": "5000",
            # The worker integrates the coordinate map once to the
            # authenticated cap, then reuses that geometry while selecting the
            # nearest endpoint whose existing infinity-series gate is adequate.
            "rho_out_candidate_schedule": [
                "100", "250", "500", "1000", "2000", "5000"
            ],
            "branch_enclosure_radius_abs": format(
                _mode_specific_branch_enclosure_radius(job), ".17g"
            ),
            "max_newton_iterations": 16,
        },
        {
            "horizon_endpoint_recovery_policy_identity": (
                "adaptive-horizon-endpoint-recovery/v1"
            ),
            "horizon_endpoint_maximum_order": 4 * endpoint_series_order,
            "horizon_endpoint_prefix_minimum_order": 4,
            "horizon_endpoint_prefix_order_step": 4,
        }
        if job.mechanism_id == "horizon-admittance"
        else {},
    )
    return policy


def _validate_mechanism_precision_policy(
    mechanism_id: str,
    policy: Mapping[str, object],
    *,
    promoted_policy_required: bool = True,
) -> None:
    """Fail closed when a request authenticates the wrong determinant family."""

    expected = dict(regularised_gsn_precision_policy(mechanism_id))
    if not promoted_policy_required:
        expected.pop("promoted_root_readout_policy")
    if any(policy.get(field) != value for field, value in expected.items()):
        raise ValueError(
            "regularised GSN precision policy disagrees with response mechanism"
        )


@dataclass(slots=True)
class JuliaPrecisionRootBackend:
    """Root-readout adapter consumed by the existing component engine."""

    promoted_precision_backend = True

    identity: BackendIdentity
    adapter: JuliaResponseAdapter
    digits: int
    refinement: int = 0
    ode_error_budget: ODEErrorBudget | None = None
    empirical_control_profile: EmpiricalControlProfile | None = None
    calibration_receipt: PromotedControlCalibrationReceipt | None = None
    diagnostic_model_identity: str | None = None

    def __post_init__(self) -> None:
        if self.digits not in _PROMOTED_DIGITS:
            raise ValueError("Julia precision backend requires 40, 80, or 120 digits")
        if self.refinement not in (0, 1):
            raise ValueError("Julia precision refinement level is invalid")
        if self.ode_error_budget is not None:
            _adaptive_ode_request_controls(self.digits, self.ode_error_budget)
        if (self.empirical_control_profile is None) is not (
            self.calibration_receipt is None
        ):
            raise ValueError(
                "empirical controls require both profile and calibration receipt"
            )
        if (
            self.ode_error_budget is not None
            and self.empirical_control_profile is not None
        ):
            raise ValueError(
                "ODE error budget and empirical controls are mutually exclusive"
            )

    def _request_ode_error_budget(self) -> ODEErrorBudget | None:
        if self.empirical_control_profile is not None:
            return None
        if self.ode_error_budget is not None:
            return self.ode_error_budget
        provider = getattr(self.adapter, "ode_error_budget_for_digits", None)
        if callable(provider):
            budget = provider(self.digits)
            _adaptive_ode_request_controls(self.digits, budget)
            return budget
        return None

    @property
    def scientific_runtime(self) -> dict[str, object]:
        return {
            **dict(self.adapter.runtime_provenance),
            "precision_digits": self.digits,
            "working_precision_bits": math.ceil(self.digits * math.log2(10)) + 32,
            "semantic_precision_tier": f"bigfloat-{self.digits}",
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
        profile = self.empirical_control_profile
        receipt = self.calibration_receipt
        if profile is not None and receipt is not None:
            expected_family = (
                "horizon-scattering/v1"
                if job.mechanism_id == "horizon-admittance"
                else "exterior-wronskian/v1"
            )
            if (
                profile.determinant_family != expected_family
                or profile.nominal_decimal_digits != self.digits
                or receipt.budget_for(expected_family, self.digits) != profile
            ):
                raise ValueError(
                    "empirical control profile disagrees with determinant request"
                )
            profile_mapping = profile.to_mapping()
            return {
                **self.scientific_runtime,
                "regularised_gsn_precision_policy": dict(
                    regularised_gsn_precision_policy(job.mechanism_id)
                ),
                "promoted_control_calibration": {
                    "schema": (
                        "windows-solver.promoted-control-calibration-binding/1"
                    ),
                    "receipt_identity": receipt.identity,
                    "receipt_sha256": receipt.sha256,
                    "execution_status": receipt.execution_status,
                    "source_audit_sha256": receipt.source_audit_sha256,
                    "determinant_family": expected_family,
                    "determinant_certificate_identity": (
                        receipt.certificate_identity
                    ),
                    "determinant_certificate_safety_factor": (
                        receipt.certificate_safety_factor
                    ),
                    "derivative_floor_status": (
                        receipt.derivative_floor_status_for(expected_family)
                    ),
                },
                "empirical_control_profile": profile_mapping,
                "empirical_control_profile_sha256": hashlib.sha256(
                    canonical_json_bytes(profile_mapping)
                ).hexdigest(),
            }
        budget = self._request_ode_error_budget()
        if budget is None:
            raise MissingODECalibrationError(ODE_CALIBRATION_BLOCKER)
        budget_mapping = budget.to_mapping()
        return {
            **self.scientific_runtime,
            "regularised_gsn_precision_policy": dict(
                regularised_gsn_precision_policy(job.mechanism_id)
            ),
            "ode_error_budget": budget_mapping,
            "ode_error_budget_sha256": hashlib.sha256(
                canonical_json_bytes(budget_mapping)
            ).hexdigest(),
        }

    def _request(
        self,
        job: ResponseComponentJob,
        amplitude: complex,
        primary_predictor: complex | None = None,
        primary_predictor_kind: str | None = None,
    ) -> dict[str, object]:
        diagnostic_model_identity = self.diagnostic_model_identity
        if diagnostic_model_identity is None:
            diagnostic_model_identity = (
                VERIFIED_ENDPOINT_ERROR_MODEL
                if job.mechanism_id == "horizon-admittance"
                else EXTERIOR_PROVISIONAL_DETERMINANT_ERROR_MODEL
            )
        policy = _precision_policy(
            job,
            self.digits,
            self.refinement,
            self._request_ode_error_budget(),
            empirical_control_profile=self.empirical_control_profile,
            calibration_receipt=self.calibration_receipt,
            diagnostic_model_identity=diagnostic_model_identity,
        )
        contract_fields = raw_determinant_contract_fields_for_model(
            diagnostic_model_identity
        )
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
            "semantic_precision_tier": f"bigfloat-{self.digits}",
            **contract_fields,
            "policy": policy,
            "execution_resource": _execution_resource_policy(),
        }
        raw_determinant_contract_from_request(request)
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

    def preview_root_request(
        self,
        job: ResponseComponentJob,
        amplitude: complex,
        primary_predictor: complex | None = None,
        primary_predictor_kind: str | None = None,
        readout_role: str | None = None,
    ) -> dict[str, object]:
        """Return the exact canonical request that ``read_root`` will send."""

        del readout_role
        return self._request(
            job,
            complex(amplitude),
            primary_predictor,
            primary_predictor_kind,
        )

    def _fixed_root_survey_policy(
        self, job: ResponseComponentJob
    ) -> tuple[dict[str, object], str]:
        policy = _precision_policy(
            job,
            self.digits,
            self.refinement,
            self._request_ode_error_budget(),
            empirical_control_profile=self.empirical_control_profile,
            calibration_receipt=self.calibration_receipt,
            diagnostic_model_identity=EXTERIOR_PROVISIONAL_DETERMINANT_ERROR_MODEL,
            include_control_provenance=True,
        )
        reliability_target = policy.get("root_correction_tolerance")
        if not isinstance(reliability_target, str):
            raise ValueError(
                "fixed-root reliability target is absent from calibration"
            )
        target = _finite_decimal_text(
            reliability_target,
            "fixed-root reliability target",
            nonnegative=True,
        )
        if target <= 0 or target >= 1:
            raise ValueError(
                "fixed-root reliability target must be between zero and one"
            )
        for field in (
            _FIXED_ROOT_SURVEY_REVIEW_ONLY_POLICY_FIELDS
            | _FIXED_ROOT_SURVEY_ROOT_ONLY_POLICY_FIELDS
        ):
            policy.pop(field, None)
        if not _FIXED_ROOT_SURVEY_CERTIFICATE_FIELDS.issubset(policy):
            raise ValueError(
                "fixed-root survey policy is missing its determinant-error "
                "certificate fields"
            )
        return policy, reliability_target

    def preview_fixed_root_survey_request(
        self,
        job: ResponseComponentJob,
        *,
        fixed_root: complex,
        root_seal_sha256: str,
        branch_identity: str,
        plan: FixedRootSurveyPlan | str,
    ) -> dict[str, object]:
        """Build one strict plan-owned Julia batch without launching Julia.

        The named plan is the sole request-shape authority.  Callers cannot
        independently pair a scientific identity with a role vector.
        """

        if job.backend_identity != self.identity:
            raise ValueError("response job backend identity does not match Julia adapter")
        if job.mechanism_id == "horizon-admittance":
            raise ValueError("fixed-root survey batch requires an exterior job")
        if self.digits not in (40, 80):
            raise ValueError("promoted survey permits only BF40 or BF80")
        root = complex(fixed_root)
        if not math.isfinite(root.real) or not math.isfinite(root.imag):
            raise ValueError("fixed-root survey root is invalid")
        if (
            not isinstance(root_seal_sha256, str)
            or len(root_seal_sha256) != 64
            or any(character not in "0123456789abcdef" for character in root_seal_sha256)
        ):
            raise ValueError("fixed-root survey root seal is invalid")
        if branch_identity != job.root.branch_id:
            raise ValueError("fixed-root survey branch identity mismatch")
        contract = fixed_root_survey_request_contract(plan)
        sample_roles = contract.sample_roles
        scientific_operation_identity = contract.scientific_operation_identity
        frequency_step = 1.0e-5 * (1.0 + abs(root))
        coordinate_step = float(job.policy.epsilons[0])
        support = {
            name: format(value, ".17g")
            for name, value in _exterior_support(
                job.spin, job.mechanism_id
            ).to_mapping().items()
        }
        points = {
            "D0": (root, 0.0j),
            "DOMEGA_REAL_PLUS_H": (root + frequency_step, 0.0j),
            "DOMEGA_REAL_MINUS_H": (root - frequency_step, 0.0j),
            "DOMEGA_REAL_PLUS_HALF_H": (root + frequency_step / 2.0, 0.0j),
            "DOMEGA_REAL_MINUS_HALF_H": (root - frequency_step / 2.0, 0.0j),
            "DC_PLUS_EPSILON": (root, complex(coordinate_step, 0.0)),
            "DC_MINUS_EPSILON": (root, complex(-coordinate_step, 0.0)),
            "DC_PLUS_HALF_EPSILON": (
                root, complex(coordinate_step / 2.0, 0.0)
            ),
            "DC_MINUS_HALF_EPSILON": (
                root, complex(-coordinate_step / 2.0, 0.0)
            ),
        }
        samples: list[dict[str, object]] = []
        for sample_index, role in enumerate(sample_roles):
            omega, amplitude = points[role]
            sample: dict[str, object] = {
                "sample_index": sample_index,
                "sample_role": role,
                "omega": _survey_complex_mapping(omega),
                "amplitude": _survey_complex_mapping(amplitude),
            }
            if role in _FIXED_ROOT_SURVEY_COORDINATE_ROLES:
                sample["support"] = dict(support)
            samples.append(sample)
        fixed_root_policy, reliability_target = self._fixed_root_survey_policy(job)
        return {
            "schema_version": 2,
            "schema": FIXED_ROOT_SURVEY_BATCH_SCHEMA,
            "operation": FIXED_ROOT_SURVEY_BATCH_OPERATION,
            "identity": BINARY64_FIXED_ROOT_SURVEY_IDENTITY,
            "plan": contract.plan.value,
            "scientific_operation_identity": scientific_operation_identity,
            "leaf_id": job.leaf_id,
            "job_id": job.job_id,
            "root_reference_id": job.root.root_reference_id,
            "root_seal_sha256": root_seal_sha256,
            "branch_identity": branch_identity,
            "backend_identity_sha256": job.backend_identity.identity_sha256,
            "mode": {
                "s": job.mode.s,
                "ell": job.mode.ell,
                "m": job.mode.m,
                "n": job.mode.n,
            },
            "spin": format(job.spin, ".17g"),
            "angular_A": _survey_complex_mapping(
                job.root.angular_separation_constant
            ),
            "mechanism_id": job.mechanism_id,
            "fixed_root": _survey_complex_mapping(root),
            "precision_digits": self.digits,
            "working_precision_bits": math.ceil(self.digits * math.log2(10)) + 32,
            "semantic_precision_tier": f"bigfloat-{self.digits}",
            "fixed_root_reliability_target_abs": reliability_target,
            "fixed_root_reliability_rule": FIXED_ROOT_RELIABILITY_RULE,
            "frequency_step": format(frequency_step, ".17g"),
            "coordinate_step": format(coordinate_step, ".17g"),
            "sample_roles": list(sample_roles),
            "maximum_sample_count": _FIXED_ROOT_SURVEY_MAXIMUM_SAMPLE_COUNT,
            "samples": samples,
            "policy": fixed_root_policy,
            "execution_resource": _execution_resource_policy(),
        }

    def fixed_root_survey_batch(
        self,
        job: ResponseComponentJob,
        *,
        fixed_root: complex,
        root_seal_sha256: str,
        branch_identity: str,
        plan: FixedRootSurveyPlan | str,
    ) -> JuliaFixedRootSurveyBatch:
        """Run one Julia request for one ordered fixed-root survey batch."""

        request = self.preview_fixed_root_survey_request(
            job,
            fixed_root=fixed_root,
            root_seal_sha256=root_seal_sha256,
            branch_identity=branch_identity,
            plan=plan,
        )
        contract = fixed_root_survey_request_contract(plan)
        sample_roles = contract.sample_roles
        scientific_operation_identity = contract.scientific_operation_identity
        evaluation = self.adapter.evaluate_for_validation(request)
        response = evaluation.response
        response_fields = {
            "schema_version",
            "schema",
            "status",
            "operation",
            "identity",
            "plan",
            "execution_identity",
            "scientific_operation_identity",
            "request_sha256",
            "leaf_id",
            "job_id",
            "root_reference_id",
            "root_seal_sha256",
            "branch_identity",
            "semantic_precision_tier",
            "working_precision_bits",
            "sample_roles",
            "maximum_sample_count",
            "sample_count",
            "samples",
        }
        if not isinstance(response, Mapping) or set(response) != response_fields:
            raise JuliaResponseBackendError(
                "M02 fixed-root survey batch response fields are invalid"
            )
        expected_bindings = {
            "schema": FIXED_ROOT_SURVEY_BATCH_RESPONSE_SCHEMA,
            "operation": FIXED_ROOT_SURVEY_BATCH_OPERATION,
            "identity": BINARY64_FIXED_ROOT_SURVEY_IDENTITY,
            "plan": contract.plan.value,
            "scientific_operation_identity": scientific_operation_identity,
            "request_sha256": evaluation.request_sha256,
            "leaf_id": job.leaf_id,
            "job_id": job.job_id,
            "root_reference_id": job.root.root_reference_id,
            "root_seal_sha256": root_seal_sha256,
            "branch_identity": branch_identity,
            "semantic_precision_tier": request["semantic_precision_tier"],
            "working_precision_bits": request["working_precision_bits"],
            "sample_roles": list(sample_roles),
            "maximum_sample_count": _FIXED_ROOT_SURVEY_MAXIMUM_SAMPLE_COUNT,
            "sample_count": len(sample_roles),
        }
        if (
            response["schema_version"] != 2
            or response["status"] != "ok"
            or any(response[name] != value for name, value in expected_bindings.items())
            or not isinstance(response["samples"], list)
            or len(response["samples"]) != len(sample_roles)
        ):
            raise JuliaResponseBackendError(
                "M02 fixed-root survey batch response authentication failed"
            )
        expected_execution_identity = execution_identity_from_request(
            evaluation.request_binding,
            request_sha256=evaluation.request_sha256,
        )
        try:
            returned_execution_identity = operation_execution_identity(
                response["execution_identity"]
            )
        except ValueError as error:
            raise JuliaResponseBackendError(
                "M02 fixed-root survey execution identity is invalid"
            ) from error
        if (
            returned_execution_identity.scope != REQUEST_SCOPE
            or returned_execution_identity.to_mapping()
            != expected_execution_identity.to_mapping()
        ):
            raise JuliaResponseBackendError(
                "M02 fixed-root survey execution identity mismatch"
            )
        parsed_samples: list[JuliaFixedRootSurveySample] = []
        request_samples = request["samples"]
        policy = request["policy"]
        for index, (role, raw, requested) in enumerate(
            zip(sample_roles, response["samples"], request_samples)
        ):
            fields = {
                "sample_index", "sample_role", "execution_identity",
                "omega", "amplitude", "determinant",
                "numerical_conditioning", "determinant_error_evidence",
            }
            if (
                not isinstance(raw, Mapping)
                or set(raw) != fields
                or raw["sample_index"] != index
                or raw["sample_role"] != role
            ):
                raise JuliaResponseBackendError(
                    f"M02 fixed-root survey sample {index} is invalid"
                )
            try:
                sample_identity = operation_execution_identity(
                    raw["execution_identity"]
                )
            except ValueError as error:
                raise JuliaResponseBackendError(
                    f"M02 fixed-root survey sample {index} identity is invalid"
                ) from error
            if sample_identity.to_mapping() != expected_execution_identity.select_sample(
                index, role
            ).to_mapping():
                raise JuliaResponseBackendError(
                    f"M02 fixed-root survey sample {index} identity mismatch"
                )
            omega = _survey_complex_from_mapping(raw["omega"], "survey omega")
            amplitude = _survey_complex_from_mapping(
                raw["amplitude"], "survey amplitude"
            )
            if (
                omega != _survey_complex_from_mapping(requested["omega"], "request omega")
                or amplitude
                != _survey_complex_from_mapping(requested["amplitude"], "request amplitude")
            ):
                raise JuliaResponseBackendError(
                    "M02 fixed-root survey sample coordinates moved"
                )
            determinant = _survey_decimal_complex_from_mapping(
                raw["determinant"], "survey determinant"
            )
            try:
                conditioning = FixedRootSurveyConditioning(
                    raw["numerical_conditioning"]
                )
            except ValueError as error:
                raise JuliaResponseBackendError(
                    "M02 fixed-root survey conditioning is invalid"
                ) from error
            telemetry = conditioning.mapping
            if any(
                telemetry[name] != policy[name]
                for name in (
                    "determinant_family",
                    "homogeneous_representation",
                    "branch_convention",
                    "determinant_convention",
                    "determinant_normalisation",
                )
            ):
                raise JuliaResponseBackendError(
                    "M02 fixed-root survey conditioning disagrees with request"
                )
            if (
                telemetry["fixed_root_reliability_target_abs"]
                != request["fixed_root_reliability_target_abs"]
                or telemetry["fixed_root_reliability_rule"]
                != request["fixed_root_reliability_rule"]
            ):
                raise JuliaResponseBackendError(
                    "M02 fixed-root survey reliability telemetry disagrees "
                    "with request"
                )
            raw_evidence = raw["determinant_error_evidence"]
            determinant_error_evidence = None
            if raw_evidence is not None:
                try:
                    determinant_error_evidence = ExteriorDeterminantErrorEvidence(
                        raw_evidence
                    )
                except ValueError as error:
                    raise JuliaResponseBackendError(
                        "M02 fixed-root survey determinant-error evidence is invalid"
                    ) from error
                if (
                    determinant_error_evidence.mapping["error_model_id"]
                    != policy.get("determinant_error_model")
                ):
                    raise JuliaResponseBackendError(
                        "M02 fixed-root survey determinant-error model disagrees "
                        "with request"
                    )
            parsed_samples.append(JuliaFixedRootSurveySample(
                index,
                role,
                omega,
                amplitude,
                determinant,
                conditioning,
                sample_identity.to_mapping(),
                determinant_error_evidence,
            ))
        return JuliaFixedRootSurveyBatch(
            leaf_id=job.leaf_id,
            job_id=job.job_id,
            mechanism_id=job.mechanism_id,
            root_reference_id=job.root.root_reference_id,
            root_seal_sha256=root_seal_sha256,
            branch_identity=branch_identity,
            fixed_root=complex(fixed_root),
            frequency_step=_finite_decimal_text(
                request["frequency_step"], "survey frequency step", nonnegative=True
            ),
            coordinate_step=_finite_decimal_text(
                request["coordinate_step"], "survey coordinate step", nonnegative=True
            ),
            scientific_operation_identity=scientific_operation_identity,
            plan=contract.plan,
            execution_identity=returned_execution_identity.to_mapping(),
            request_sha256=evaluation.request_sha256,
            precision_tier=precision_tier(str(request["semantic_precision_tier"])),
            working_precision_bits=int(request["working_precision_bits"]),
            samples=tuple(parsed_samples),
        )

    def preview_fixed_root_request(
        self,
        job: ResponseComponentJob,
        omega: complex,
        amplitude: complex,
        readout_role: str,
    ) -> dict[str, object]:
        tier = {
            40: PrecisionTier.BIGFLOAT_40,
            80: PrecisionTier.BIGFLOAT_80,
            120: PrecisionTier.BIGFLOAT_120,
        }[self.digits]
        fixed_omega = complex(omega)
        return {
            **self._request(job, complex(amplitude)),
            "operation": "fixed-root-determinant-sample",
            "fixed_omega": {
                "real": format(fixed_omega.real, ".17g"),
                "imaginary": format(fixed_omega.imag, ".17g"),
            },
            "readout_role": readout_role,
            "semantic_precision_tier": tier.value,
        }

    def read_root(
        self,
        job: ResponseComponentJob,
        amplitude: complex,
        primary_predictor: complex | None = None,
    ) -> RootReadout:
        return self._read_root(
            job, amplitude, primary_predictor, primary_predictor_kind=None
        )

    def sample_fixed_root_determinant(
        self,
        job: ResponseComponentJob,
        omega: complex,
        amplitude: complex,
        *,
        readout_role: str,
    ) -> FixedRootDeterminantSample:
        """Evaluate one determinant while holding the authenticated root fixed."""

        if job.backend_identity != self.identity:
            raise ValueError("response job backend identity does not match Julia adapter")
        fixed_omega = complex(omega)
        converted_amplitude = complex(amplitude)
        if not all(math.isfinite(value) for value in (
            fixed_omega.real, fixed_omega.imag,
            converted_amplitude.real, converted_amplitude.imag,
        )):
            raise ValueError("fixed-root determinant sample coordinates are invalid")
        if not isinstance(readout_role, str) or not readout_role:
            raise ValueError("fixed-root determinant readout role is invalid")
        tier = {
            40: PrecisionTier.BIGFLOAT_40,
            80: PrecisionTier.BIGFLOAT_80,
            120: PrecisionTier.BIGFLOAT_120,
        }[self.digits]
        contract = regularised_gsn_mechanism_contract(job.mechanism_id)
        policy = _precision_policy(
            job,
            self.digits,
            self.refinement,
            self._request_ode_error_budget(),
            empirical_control_profile=self.empirical_control_profile,
            calibration_receipt=self.calibration_receipt,
        )
        request = self.preview_fixed_root_request(
            job, fixed_omega, converted_amplitude, readout_role
        )
        evaluation = self.adapter.evaluate_for_validation(request)
        response = evaluation.response
        historical_fields = {
            "schema_version", "status", "operation", "request_sha256",
            "omega_re", "omega_im", "amplitude_re", "amplitude_im",
            "determinant_re", "determinant_im", "determinant_error_abs",
            "determinant_error_status", "determinant_error_model_id",
            "determinant_family", "determinant_normalisation",
            "branch_identity", "branch_authenticated",
            "semantic_precision_tier", "working_precision_bits",
            "readout_role",
        }
        current_fields = historical_fields | {
            "numerical_conditioning",
            "execution_identity",
        }
        if (
            not isinstance(response, Mapping)
            or (
                set(response) != historical_fields
                and set(response) != current_fields
            )
            or response["schema_version"] not in {1, 2}
            or response["status"] != "ok"
            or response["operation"] != "fixed-root-determinant-sample"
            or response["request_sha256"] != evaluation.request_sha256
            or response["determinant_family"] != contract["determinant_family"]
            or response["determinant_normalisation"]
            != contract["determinant_normalisation"]
            or response["branch_identity"] != policy["branch_convention"]
            or response["branch_authenticated"] is not True
            or response["semantic_precision_tier"] != tier.value
            or response["working_precision_bits"]
            != request["working_precision_bits"]
            or response["readout_role"] != readout_role
        ):
            raise JuliaResponseBackendError(
                "M02 fixed-root determinant sample response is invalid"
            )
        if response["schema_version"] == 1:
            if set(response) != historical_fields:
                raise JuliaResponseBackendError(
                    "historical M02 fixed-root sample fields are invalid"
                )
            numerical_conditioning = None
        else:
            if set(response) != current_fields:
                raise JuliaResponseBackendError(
                    "M02 fixed-root sample conditioning fields are invalid"
                )
            try:
                returned_identity = operation_execution_identity(
                    response["execution_identity"]
                )
                expected_identity = execution_identity_from_request(
                    evaluation.request_binding,
                    request_sha256=evaluation.request_sha256,
                )
            except ValueError as error:
                raise JuliaResponseBackendError(
                    "M02 fixed-root sample execution identity is invalid"
                ) from error
            if returned_identity.to_mapping() != expected_identity.to_mapping():
                raise JuliaResponseBackendError(
                    "M02 fixed-root sample execution identity mismatch"
                )
            try:
                numerical_conditioning = NumericalConditioningEvidence.from_mapping(
                    response["numerical_conditioning"]
                )
            except ValueError as error:
                raise JuliaResponseBackendError(
                    "M02 fixed-root sample conditioning is invalid"
                ) from error
            if any(
                getattr(numerical_conditioning, field) != value
                for field, value in contract.items()
            ):
                raise JuliaResponseBackendError(
                    "M02 fixed-root sample conditioning disagrees with request"
                )
        response_omega = complex(
            float(_finite_decimal_text(response["omega_re"], "sample omega real")),
            float(_finite_decimal_text(response["omega_im"], "sample omega imaginary")),
        )
        response_amplitude = complex(
            float(_finite_decimal_text(response["amplitude_re"], "sample amplitude real")),
            float(_finite_decimal_text(response["amplitude_im"], "sample amplitude imaginary")),
        )
        if response_omega != fixed_omega or response_amplitude != converted_amplitude:
            raise JuliaResponseBackendError(
                "M02 fixed-root determinant sample moved its coordinates"
            )
        determinant_real = _finite_decimal_text(
            response["determinant_re"], "sample determinant real"
        )
        determinant_imaginary = _finite_decimal_text(
            response["determinant_im"], "sample determinant imaginary"
        )
        determinant = complex(
            float(determinant_real),
            float(determinant_imaginary),
        )
        determinant_error_decimal = _finite_decimal_text(
            response["determinant_error_abs"],
            "sample determinant error",
            nonnegative=True,
        )
        determinant_error = float(determinant_error_decimal)
        if Decimal.from_float(determinant_error) < determinant_error_decimal:
            determinant_error = math.nextafter(determinant_error, math.inf)
        determinant_error_status = response["determinant_error_status"]
        determinant_error_model_id = response["determinant_error_model_id"]
        expected_error_model_id = request["policy"].get(
            "determinant_error_model"
        )
        if (
            determinant_error_status not in {"available/v1", "unavailable/v1"}
            or (
                determinant_error_status == "available/v1"
                and (
                    not isinstance(determinant_error_model_id, str)
                    or not determinant_error_model_id
                    or determinant_error <= 0.0
                )
            )
            or (
                determinant_error_status == "unavailable/v1"
                and (determinant_error_model_id is not None or determinant_error != 0.0)
            )
        ):
            raise JuliaResponseBackendError(
                "M02 fixed-root determinant error evidence is invalid"
            )
        if (
            expected_error_model_id is not None
            and determinant_error_status == "available/v1"
            and determinant_error_model_id != expected_error_model_id
        ) or (
            determinant_error_status == "unavailable/v1"
            and expected_error_model_id is not None
            and not _is_uncalibrated_exterior_error_policy(request["policy"])
        ):
            raise JuliaResponseBackendError(
                "M02 fixed-root determinant error model disagrees with request"
            )
        request_binding = json.loads(canonical_json_bytes(request))
        response_binding = json.loads(canonical_json_bytes(dict(response)))
        receipt = {
            "schema": (
                "windows-solver.fixed-root-determinant-sample-receipt/2"
                if response["schema_version"] == 2
                else "windows-solver.fixed-root-determinant-sample-receipt/1"
            ),
            "request_binding": request_binding,
            "request_sha256": evaluation.request_sha256,
            "response_binding": response_binding,
            "response_sha256": hashlib.sha256(
                canonical_json_bytes(response_binding)
            ).hexdigest(),
            "runtime_identity_sha256": evaluation.runtime_identity_sha256,
            "scientific_runtime_sha256": hashlib.sha256(
                canonical_json_bytes(self.scientific_runtime_for(job))
            ).hexdigest(),
        }
        receipt_sha256 = hashlib.sha256(canonical_json_bytes(receipt)).hexdigest()
        return FixedRootDeterminantSample(
            omega=response_omega,
            amplitude=response_amplitude,
            determinant=determinant,
            determinant_error_abs=determinant_error,
            determinant_error_status=str(determinant_error_status),
            determinant_error_model_id=determinant_error_model_id,
            determinant_family=str(response["determinant_family"]),
            determinant_normalisation=str(response["determinant_normalisation"]),
            branch_identity=str(response["branch_identity"]),
            branch_authenticated=response["branch_authenticated"],
            request_sha256=evaluation.request_sha256,
            worker_response_receipt=receipt,
            worker_response_receipt_sha256=receipt_sha256,
            precision_tier=precision_tier(response["semantic_precision_tier"]),
            working_precision_bits=response["working_precision_bits"],
            readout_role=readout_role,
            numerical_conditioning=numerical_conditioning,
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
        response_schema = evaluation.response.get("schema_version")
        policy = request.get("policy")
        current_request = (
            isinstance(policy, Mapping)
            and policy.get("promoted_root_readout_policy")
            == PROMOTED_ROOT_READOUT_POLICY
        )
        if current_request and response_schema == WORKER_RESPONSE_WIRE_SCHEMA:
            return self._read_root_response_v7(
                job, request, evaluation, legacy_wire=False
            )
        if (
            current_request
            and response_schema == LEGACY_PROMOTED_WORKER_RESPONSE_WIRE_SCHEMA
        ):
            return self._read_root_response_v7(
                job, request, evaluation, legacy_wire=True
            )
        if response_schema == 6 and not current_request:
            return self._read_root_response_v6(job, request, evaluation)
        raise JuliaResponseBackendError(
            "M02 Julia response policy/wire schema is inconsistent"
        )

    def _read_root_response_v7(
        self,
        job: ResponseComponentJob,
        request: Mapping[str, object],
        evaluation: JuliaResponseEvaluation,
        *,
        legacy_wire: bool = False,
    ) -> RootReadout:
        response = dict(evaluation.response)
        expected_fields = {
            "schema_version",
            "status",
            "adapter",
            "request_sha256",
            "precision_digits",
            "working_precision_bits",
            "promoted_root_readout_policy",
            "root_omega_re",
            "root_omega_im",
            "root_residual_abs",
            "raw_determinant_abs",
            "raw_determinant_evidence_status",
            "root_derivative_abs",
            "primary_acceptance",
            "root_converged",
            "branch_authentication_contract_version",
            "root_branch_continuation_valid",
            "branch_tolerance_abs",
            "root_displacement_abs",
            "truncation_radius_abs",
            "resolution_radius_abs",
            "seed_path_radius_abs",
            "seed_path_required",
            "seed_path_executed",
            "seed_path_determinant_count",
            "diagnostic_roots",
            "diagnostics_skipped_reason",
            "numerical_conditioning",
            "horizon_endpoint_search_evidence",
        }
        if not legacy_wire:
            expected_fields.update({
                "operation",
                "execution_identity",
                "diagnostic_model_identity",
                "required_raw_determinant_roles",
                "required_raw_determinant_count",
            })
        if set(response) != expected_fields:
            raise JuliaResponseBackendError("M02 Julia response fields are invalid")
        if (
            any(
                type(response[name]) is not int
                for name in (
                    "schema_version",
                    "precision_digits",
                    "working_precision_bits",
                    "branch_authentication_contract_version",
                    "seed_path_determinant_count",
                )
            )
            or response["schema_version"]
            != (
                LEGACY_PROMOTED_WORKER_RESPONSE_WIRE_SCHEMA
                if legacy_wire
                else WORKER_RESPONSE_WIRE_SCHEMA
            )
            or response["status"] != "ok"
            or response["adapter"] != "package-owned-julia-gsn-root-readout"
            or (
                not legacy_wire
                and response["operation"] != "root-readout"
            )
            or response["request_sha256"] != evaluation.request_sha256
            or response["precision_digits"] != self.digits
            or response["working_precision_bits"]
            != math.ceil(self.digits * math.log2(10)) + 32
            or response["promoted_root_readout_policy"]
            != PROMOTED_ROOT_READOUT_POLICY
            or type(response["root_converged"]) is not bool
            or response["branch_authentication_contract_version"] != 4
            or type(response["root_branch_continuation_valid"]) is not bool
            or response["seed_path_required"] is not False
            or response["seed_path_executed"] is not False
            or response["seed_path_determinant_count"] != 0
            or response["seed_path_radius_abs"] is not None
        ):
            raise JuliaResponseBackendError("M02 Julia response contract is invalid")
        if not legacy_wire:
            try:
                returned_identity = operation_execution_identity(
                    response["execution_identity"]
                )
                expected_identity = execution_identity_from_request(
                    evaluation.request_binding,
                    request_sha256=evaluation.request_sha256,
                )
            except ValueError as error:
                raise JuliaResponseBackendError(
                    "M02 root-readout execution identity is invalid"
                ) from error
            if returned_identity.to_mapping() != expected_identity.to_mapping():
                raise JuliaResponseBackendError(
                    "M02 root-readout execution identity mismatch"
                )

        policy = request.get("policy")
        if not isinstance(policy, Mapping):
            raise JuliaResponseBackendError("M02 Julia request policy is invalid")
        try:
            _validate_mechanism_precision_policy(job.mechanism_id, policy)
        except ValueError as error:
            raise JuliaResponseBackendError(
                "M02 Julia request policy disagrees with response mechanism"
            ) from error
        if policy.get("promoted_root_readout_policy") != (
            PROMOTED_ROOT_READOUT_POLICY
        ):
            raise JuliaResponseBackendError(
                "M02 Julia promoted root policy identity is invalid"
            )

        diagnostic_contract: RawDeterminantContract | None = None
        if not legacy_wire:
            try:
                diagnostic_contract = raw_determinant_contract_from_request(
                    request
                )
            except ValueError as error:
                raise JuliaResponseBackendError(
                    "M02 Julia request raw determinant contract is invalid"
                ) from error
            try:
                _validate_current_raw_determinant_policy(
                    request, diagnostic_contract
                )
            except ValueError as error:
                raise JuliaResponseBackendError(
                    "M02 Julia determinant certificate policy is invalid"
                ) from error
            if (
                response["diagnostic_model_identity"]
                != diagnostic_contract.diagnostic_model_identity
                or response["required_raw_determinant_roles"]
                != list(diagnostic_contract.required_raw_determinant_roles)
                or type(response["required_raw_determinant_count"]) is not int
                or response["required_raw_determinant_count"]
                != diagnostic_contract.required_raw_determinant_count
            ):
                raise JuliaResponseBackendError(
                    "M02 Julia response raw determinant contract is invalid"
                )

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
        endpoint_evidence = response["horizon_endpoint_search_evidence"]
        if job.mechanism_id == "horizon-admittance":
            try:
                endpoint_evidence = (
                    _validated_successful_horizon_endpoint_search_evidence(
                        endpoint_evidence, request
                    )
                )
            except ValueError as error:
                raise JuliaResponseBackendError(
                    "M02 Julia successful horizon endpoint evidence is invalid"
                ) from error
        elif endpoint_evidence is not None:
            raise JuliaResponseBackendError(
                "M02 Julia exterior response carries horizon endpoint evidence"
            )

        try:
            primary_acceptance = PrimaryRootAcceptanceEvidence.from_mapping(
                response["primary_acceptance"]
            )
        except ValueError as error:
            raise JuliaResponseBackendError(
                "M02 Julia PRIMARY acceptance evidence is invalid"
            ) from error
        if legacy_wire:
            legacy_model = policy.get("determinant_error_model")
            if legacy_model == _EXTERIOR_ADDITIVE_CHANNEL_SCHEMA:
                raise JuliaResponseBackendError(
                    "M02 Julia wire-10 cannot carry a provisional exterior contract"
                )
            uncalibrated_exterior = False
            expected_error_model_id = (
                VERIFIED_ENDPOINT_ERROR_MODEL
                if legacy_model == VERIFIED_ENDPOINT_ERROR_MODEL
                else EXTERIOR_DETERMINANT_ABSOLUTE_ERROR_CERTIFICATE
            )
        else:
            assert diagnostic_contract is not None
            uncalibrated_exterior = not diagnostic_contract.empirical_certificate_required
            expected_error_model_id = (
                diagnostic_contract.permitted_response_receipt_identity
            )
        if (
            legacy_wire
            and job.mechanism_id == "horizon-admittance"
            and policy.get("determinant_error_model")
            != VERIFIED_ENDPOINT_ERROR_MODEL
        ):
            raise JuliaResponseBackendError(
                "M02 Julia determinant certificate policy is invalid"
            )
        if primary_acceptance.error_model_id != expected_error_model_id:
            raise JuliaResponseBackendError(
                "M02 Julia PRIMARY determinant telemetry identity is invalid"
            )

        root_real_decimal = _finite_decimal_text(
            response["root_omega_re"], "root_omega_re"
        )
        root_imaginary_decimal = _finite_decimal_text(
            response["root_omega_im"], "root_omega_im"
        )
        normalised_determinant_abs = _finite_decimal_text(
            response["root_residual_abs"],
            "root_residual_abs",
            nonnegative=True,
        )
        root_derivative_abs_decimal = _finite_decimal_text(
            response["root_derivative_abs"],
            "root_derivative_abs",
            nonnegative=True,
        )
        root_correction_tolerance = _finite_decimal_text(
            policy.get("root_correction_tolerance"),
            "root_correction_tolerance",
            nonnegative=True,
        )
        branch_tolerance_decimal = _finite_decimal_text(
            response["branch_tolerance_abs"],
            "branch_tolerance_abs",
            nonnegative=True,
        )
        expected_branch_tolerance_decimal = _finite_decimal_text(
            policy["branch_enclosure_radius_abs"],
            "branch_enclosure_radius_abs",
            nonnegative=True,
        )
        root_displacement_decimal = _finite_decimal_text(
            response["root_displacement_abs"],
            "root_displacement_abs",
            nonnegative=True,
        )
        with localcontext() as context:
            context.prec = self.digits + 64
            serialization_allowance = Decimal(1).scaleb(-self.digits)

            def inconsistent(left: Decimal, right: Decimal) -> bool:
                scale = max(abs(left), abs(right), Decimal(1))
                return abs(left - right) > serialization_allowance * scale

            primary_residual = primary_acceptance.determinant.magnitude()
            primary_derivative_abs = primary_acceptance.derivative.magnitude()
            delta_real = root_real_decimal - Decimal(
                format(job.root.omega.real, ".17g")
            )
            delta_imaginary = root_imaginary_decimal - Decimal(
                format(job.root.omega.imag, ".17g")
            )
            derived_displacement = (
                delta_real * delta_real + delta_imaginary * delta_imaginary
            ).sqrt()
            if (
                inconsistent(primary_residual, normalised_determinant_abs)
                or inconsistent(primary_derivative_abs, root_derivative_abs_decimal)
                or inconsistent(
                    primary_acceptance.root_correction_tolerance,
                    root_correction_tolerance,
                )
                or inconsistent(
                    branch_tolerance_decimal,
                    expected_branch_tolerance_decimal,
                )
                or inconsistent(derived_displacement, root_displacement_decimal)
            ):
                raise JuliaResponseBackendError(
                    "M02 Julia PRIMARY response binding is inconsistent"
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
        raw_status = response["raw_determinant_evidence_status"]
        if job.mechanism_id == "horizon-admittance":
            if raw_status == "available/v1":
                if raw_determinant_abs is None:
                    raise JuliaResponseBackendError(
                        "M02 Julia available raw horizon determinant lacks its magnitude"
                    )
            elif raw_status == "unavailable-overflow/v1":
                if raw_determinant_abs is not None:
                    raise JuliaResponseBackendError(
                        "M02 Julia unavailable raw horizon determinant carries a magnitude"
                    )
            else:
                raise JuliaResponseBackendError(
                    "M02 Julia horizon raw determinant evidence status is invalid"
                )
        elif raw_status != "not-applicable/v1" or raw_determinant_abs is not None:
            raise JuliaResponseBackendError(
                "M02 Julia exterior Wronskian claims raw horizon evidence"
            )

        diagnostics_skipped_reason = response["diagnostics_skipped_reason"]
        diagnostics_skipped = diagnostics_skipped_reason == (
            "PRIMARY_NOT_CONVERGED"
        )
        expected_skip_reason = (
            None
            if primary_acceptance.accepted
            else "PRIMARY_NOT_CONVERGED"
        )
        if diagnostics_skipped_reason != expected_skip_reason:
            raise JuliaResponseBackendError(
                "M02 Julia diagnostic skip evidence is inconsistent"
            )
        raw_diagnostics = response["diagnostic_roots"]
        diagnostic_wire_fields = {
            "policy_id",
            "root_phase",
            "fixed_root",
            "root_omega_re",
            "root_omega_im",
            "determinant_re",
            "determinant_im",
            "root_residual_abs",
            "primary_derivative_re",
            "primary_derivative_im",
            "derivative_source",
            "acceptance_metric",
            "correction_abs",
            "root_correction_tolerance",
            "determinant_error_abs",
            "error_model_id",
            "displacement_from_primary_abs",
            "branch_identity",
            "branch_authenticated",
            "control_identity",
            "solve_role",
            "authoritative",
            "determinant_count",
            "raw_determinant_evaluation_count",
            "root_converged",
        }
        if legacy_wire:
            legacy_model = policy.get("determinant_error_model")
            if legacy_model == VERIFIED_ENDPOINT_ERROR_MODEL:
                expected_raw_determinant_count = 1
            elif legacy_model == EXTERIOR_DETERMINANT_ABSOLUTE_ERROR_CERTIFICATE:
                expected_raw_determinant_count = 3
            elif legacy_model == _EXTERIOR_ADDITIVE_CHANNEL_SCHEMA:
                raise JuliaResponseBackendError(
                    "M02 Julia wire-10 cannot carry a provisional exterior contract"
                )
            else:
                raise JuliaResponseBackendError(
                    "M02 Julia legacy raw determinant model is invalid"
                )
        else:
            assert diagnostic_contract is not None
            expected_raw_determinant_count = (
                diagnostic_contract.required_raw_determinant_count
            )
        expected_families = {"truncation", "resolution"}
        if (
            not isinstance(raw_diagnostics, Mapping)
            or (
                bool(raw_diagnostics)
                if diagnostics_skipped
                else set(raw_diagnostics) != expected_families
            )
        ):
            raise JuliaResponseBackendError(
                "M02 Julia fixed-root diagnostics are invalid"
            )
        radii_decimal: dict[str, Decimal] = {}
        diagnostics: dict[str, DiagnosticRootReadout] = {}
        for family in (() if diagnostics_skipped else ("truncation", "resolution")):
            raw = raw_diagnostics[family]
            expected_phase = {
                "truncation": "TRUNCATION",
                "resolution": "RESOLUTION",
            }[family]
            if (
                not isinstance(raw, Mapping)
                or set(raw) != diagnostic_wire_fields
                or raw["root_phase"] != expected_phase
                or raw["solve_role"] != "FIXED_ROOT_DIAGNOSTIC"
                or raw["authoritative"] is not False
                or raw["fixed_root"] is not True
                or raw["derivative_source"] != "PRIMARY_COMPLEX"
                or raw["acceptance_metric"]
                != PROMOTED_ROOT_ACCEPTANCE_METRIC
                or type(raw["root_converged"]) is not bool
                or type(raw["branch_authenticated"]) is not bool
                or type(raw["determinant_count"]) is not int
                or raw["determinant_count"] != 1
                or type(raw["raw_determinant_evaluation_count"])
                is not int
                or raw["raw_determinant_evaluation_count"]
                != expected_raw_determinant_count
            ):
                raise JuliaResponseBackendError(
                    "M02 Julia fixed-root diagnostic contract is invalid"
                )
            diagnostic_real = _finite_decimal_text(
                raw["root_omega_re"], "fixed-root omega real"
            )
            diagnostic_imaginary = _finite_decimal_text(
                raw["root_omega_im"], "fixed-root omega imaginary"
            )
            reported_residual = _finite_decimal_text(
                raw["root_residual_abs"],
                "fixed-root residual",
                nonnegative=True,
            )
            displacement = _finite_decimal_text(
                raw["displacement_from_primary_abs"],
                "fixed-root displacement",
                nonnegative=True,
            )
            if (
                diagnostic_real != root_real_decimal
                or diagnostic_imaginary != root_imaginary_decimal
                or displacement != 0
                or raw["primary_derivative_re"]
                != str(primary_acceptance.derivative.real)
                or raw["primary_derivative_im"]
                != str(primary_acceptance.derivative.imaginary)
                or raw["branch_identity"] != policy["branch_convention"]
                or raw["error_model_id"] != expected_error_model_id
            ):
                raise JuliaResponseBackendError(
                    "M02 Julia fixed-root diagnostic binding is inconsistent"
                )
            evidence_mapping = {
                "policy_id": raw["policy_id"],
                "acceptance_metric": raw["acceptance_metric"],
                "root_phase": raw["root_phase"],
                "determinant_re": raw["determinant_re"],
                "determinant_im": raw["determinant_im"],
                "primary_derivative_re": raw["primary_derivative_re"],
                "primary_derivative_im": raw["primary_derivative_im"],
                "correction_abs": raw["correction_abs"],
                "root_correction_tolerance": raw[
                    "root_correction_tolerance"
                ],
                "determinant_error_abs": raw["determinant_error_abs"],
                "error_model_id": raw["error_model_id"],
                "control_identity": raw["control_identity"],
                "branch_identity": raw["branch_identity"],
                "branch_authenticated": raw["branch_authenticated"],
                "determinant_count": raw["determinant_count"],
                "raw_determinant_evaluation_count": raw[
                    "raw_determinant_evaluation_count"
                ],
                "accepted": raw["root_converged"],
                "fixed_root": raw["fixed_root"],
                "derivative_source": raw["derivative_source"],
            }
            try:
                evidence = FixedRootDiagnosticEvidence.from_mapping(
                    evidence_mapping
                )
            except ValueError as error:
                raise JuliaResponseBackendError(
                    "M02 Julia fixed-root diagnostic evidence is inconsistent"
                ) from error
            with localcontext() as context:
                context.prec = self.digits + 64
                if inconsistent(
                    evidence.determinant.magnitude(), reported_residual
                ) or inconsistent(
                    evidence.root_correction_tolerance,
                    root_correction_tolerance,
                ):
                    raise JuliaResponseBackendError(
                        "M02 Julia fixed-root diagnostic scalar is inconsistent"
                    )
            radii_decimal[family] = displacement
            diagnostics[family] = DiagnosticRootReadout(
                omega_delta_from_primary=0.0j,
                determinant_residual_abs=float(reported_residual),
                determinant_derivative_abs=float(
                    evidence.primary_derivative.magnitude()
                ),
                converged=evidence.accepted,
                fixed_root_evidence=evidence,
            )

        if diagnostics_skipped:
            if (
                response["truncation_radius_abs"] is not None
                or response["resolution_radius_abs"] is not None
            ):
                raise JuliaResponseBackendError(
                    "M02 Julia skipped diagnostic radii are inconsistent"
                )
            truncation_radius = None
            resolution_radius = None
        else:
            for family, field in (
                ("truncation", "truncation_radius_abs"),
                ("resolution", "resolution_radius_abs"),
            ):
                radius = _finite_decimal_text(
                    response[field], field, nonnegative=True
                )
                if radius != 0 or radius != radii_decimal[family]:
                    raise JuliaResponseBackendError(
                        "M02 Julia fixed-root diagnostic radius is inconsistent"
                    )
            truncation_radius = 0.0
            resolution_radius = 0.0

        derived_branch_valid = (
            derived_displacement <= branch_tolerance_decimal
            and all(
                evidence.fixed_root_evidence.branch_authenticated
                for evidence in diagnostics.values()
            )
        )
        if response["root_branch_continuation_valid"] != derived_branch_valid:
            raise JuliaResponseBackendError(
                "M02 Julia branch-continuation evidence is inconsistent"
            )
        expected_converged = (
            primary_acceptance.accepted
            and not diagnostics_skipped
            and all(item.converged for item in diagnostics.values())
            and derived_branch_valid
        )
        if response["root_converged"] != expected_converged:
            raise JuliaResponseBackendError(
                "M02 Julia final root convergence evidence is inconsistent"
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
            "raw_determinant_evidence_status": raw_status,
            "promoted_root_readout_policy": PROMOTED_ROOT_READOUT_POLICY,
            "primary_acceptance_sha256": hashlib.sha256(
                canonical_json_bytes(primary_acceptance.to_mapping())
            ).hexdigest(),
            "horizon_endpoint_search_evidence": endpoint_evidence,
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

        root = complex(float(root_real_decimal), float(root_imaginary_decimal))
        try:
            readout = RootReadout(
                omega=root,
                determinant_residual_abs=float(normalised_determinant_abs),
                determinant_derivative_abs=float(root_derivative_abs_decimal),
                converged=response["root_converged"],
                root_reference_id=job.root.root_reference_id,
                branch_id=(
                    job.root.branch_id
                    if derived_branch_valid
                    else "nonmatching-julia-continuation"
                ),
                equation_id=job.equation_id,
                truncation_radius=truncation_radius,
                resolution_radius=resolution_radius,
                seed_path_radius=None,
                diagnostic_readouts=(
                    None if diagnostics_skipped else diagnostics
                ),
                diagnostics_skipped_reason=diagnostics_skipped_reason,
                numerical_conditioning=numerical_conditioning,
                normalised_determinant_abs=normalised_determinant_abs,
                raw_determinant_abs=raw_determinant_abs,
                raw_determinant_evidence_status=raw_status,
                worker_response_receipt=worker_response_receipt,
                root_authentication=None,
                promoted_root_readout_policy=PROMOTED_ROOT_READOUT_POLICY,
                primary_acceptance=primary_acceptance,
                seed_path_required=False,
                seed_path_executed=False,
                seed_path_determinant_count=0,
            )
        except ValueError as error:
            raise JuliaResponseBackendError(
                "M02 Julia promoted root evidence is inconsistent"
            ) from error
        retain = getattr(self.adapter, "retain_validated_readout", None)
        if retain is not None:
            retain(evaluation, worker_response_receipt)
        return readout

    def _read_root_response_v6(
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
            or response["schema_version"] != 6
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
            if "accepted flag is inconsistent" in str(error):
                raise JuliaResponseBackendError(
                    "M02 Julia converged root exceeds its correction target"
                ) from error
            raise JuliaResponseBackendError(
                "M02 Julia root authentication evidence is invalid"
            ) from error
        if root_authentication.authentication_strategy is None:
            raise JuliaResponseBackendError(
                "M02 Julia current root authentication strategy is missing"
            )
        # Any request carrying an error-model identity must carry a matching
        # breakdown.  The empirical exterior certificate deliberately joins
        # the existing horizon error-aware route here.
        horizon_family = (
            numerical_conditioning.scattering_diagnostics_applicable is True
        )
        policy = request["policy"]
        if not isinstance(policy, Mapping):
            raise JuliaResponseBackendError("M02 Julia request policy is invalid")
        expected_error_model_id = (
            None if _is_uncalibrated_exterior_error_policy(policy)
            else policy.get("determinant_error_model")
        )
        if (
            (expected_error_model_id is not None)
            != (root_authentication.error_breakdown is not None)
        ):
            raise JuliaResponseBackendError(
                "M02 Julia root authentication error model does not match the "
                "request policy"
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
        try:
            _validate_mechanism_precision_policy(
                job.mechanism_id,
                policy,
                promoted_policy_required=False,
            )
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
        root_derivative_abs_decimal = _finite_decimal_text(
            response["root_derivative_abs"],
            "root_derivative_abs",
            nonnegative=True,
        )
        if root_derivative_abs_decimal <= 0:
            raise JuliaResponseBackendError(
                "M02 Julia root derivative lower bound is invalid"
            )
        if (
            root_derivative_abs_decimal
            != root_authentication.derivative_lower_bound_abs
        ):
            raise JuliaResponseBackendError(
                "M02 Julia root derivative lower bound is inconsistent"
            )
        root_correction_tolerance = _finite_decimal_text(
            policy.get("root_correction_tolerance"),
            "root_correction_tolerance",
            nonnegative=True,
        )
        if root_correction_tolerance <= 0:
            raise JuliaResponseBackendError(
                "M02 Julia root correction tolerance is invalid"
            )
        try:
            root_authentication.validate_binding(
                determinant_abs=normalised_determinant_abs,
                derivative_abs=root_authentication.derivative_estimate.magnitude(),
                expected_error_model_id=expected_error_model_id,
                root_correction_tolerance=root_correction_tolerance,
                accepted=converged,
            )
        except ValueError as error:
            raise JuliaResponseBackendError(
                "M02 Julia root authentication evidence is inconsistent"
            ) from error
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
        diagnostic_fields = {
            "root_omega_re",
            "root_omega_im",
            "root_residual_abs",
            "root_phase",
            "root_derivative_abs",
            "determinant_error_abs",
            "error_model_id",
            "residual_upper_bound_abs",
            "derivative_lower_bound_abs",
            "required_derivative_lower_bound_abs",
            "correction_upper_bound",
            "root_correction_tolerance",
            "raw_step_disagreement_abs",
            "guarded_step_disagreement_abs",
            "propagated_derivative_error_abs",
            "displacement_from_primary_abs",
            "branch_identity",
            "branch_authenticated",
            "control_identity",
            "solve_role",
            "authentication_mode",
            "authoritative",
            "full_authentication_escalated",
            "escalation_reason",
            "authenticated_evidence_reused",
            "determinant_count",
            "determinant_count_phase",
            "root_converged",
        }
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
            if (
                not isinstance(raw, Mapping)
                or set(raw) != diagnostic_fields
                or not isinstance(raw["root_converged"], bool)
                or type(raw["branch_authenticated"]) is not bool
                or type(raw["authoritative"]) is not bool
                or raw["authoritative"] is not False
                or type(raw["full_authentication_escalated"]) is not bool
                or type(raw["authenticated_evidence_reused"]) is not bool
                or type(raw["determinant_count"]) is not int
                or raw["determinant_count"] < 0
                or type(raw["determinant_count_phase"]) is not int
                or raw["determinant_count_phase"] != raw["determinant_count"]
                or raw["solve_role"] != "DIAGNOSTIC_CONSISTENCY"
                or raw["authentication_mode"] not in {
                    "DIAGNOSTIC_CONSISTENCY",
                    "FULL_AUTHENTICATION_ESCALATION",
                }
                or raw["root_phase"] != {
                    "truncation": "TRUNCATION",
                    "resolution": "RESOLUTION",
                    "seed-path": "SEED-PATH",
                }[family]
                or not isinstance(raw["control_identity"], str)
                or not raw["control_identity"]
            ):
                raise JuliaResponseBackendError("M02 Julia diagnostic root is invalid")
            escalated = raw["full_authentication_escalated"]
            escalation_reason = raw["escalation_reason"]
            if (
                escalated
                != (
                    isinstance(escalation_reason, str)
                    and bool(escalation_reason)
                )
                or escalated
                != (
                    raw["authentication_mode"]
                    == "FULL_AUTHENTICATION_ESCALATION"
                )
            ):
                raise JuliaResponseBackendError(
                    "M02 Julia diagnostic escalation evidence is invalid"
                )
            diagnostic_real_decimal = _finite_decimal_text(
                raw["root_omega_re"], "diagnostic root_omega_re"
            )
            diagnostic_imaginary_decimal = _finite_decimal_text(
                raw["root_omega_im"], "diagnostic root_omega_im"
            )
            diagnostic_residual_decimal = _finite_decimal_text(
                raw["root_residual_abs"],
                "diagnostic root_residual_abs",
                nonnegative=True,
            )
            diagnostic_derivative_decimal = _finite_decimal_text(
                raw["root_derivative_abs"],
                "diagnostic root_derivative_abs",
                nonnegative=True,
            )
            determinant_error_decimal = _finite_decimal_text(
                raw["determinant_error_abs"],
                "diagnostic determinant_error_abs",
                nonnegative=True,
            )
            residual_upper_bound_decimal = _finite_decimal_text(
                raw["residual_upper_bound_abs"],
                "diagnostic residual_upper_bound_abs",
                nonnegative=True,
            )
            required_derivative_lower_bound_decimal = _finite_decimal_text(
                raw["required_derivative_lower_bound_abs"],
                "diagnostic required_derivative_lower_bound_abs",
                nonnegative=True,
            )
            propagated_derivative_error_decimal = _finite_decimal_text(
                raw["propagated_derivative_error_abs"],
                "diagnostic propagated_derivative_error_abs",
                nonnegative=True,
            )
            raw_step_disagreement_decimal = (
                None
                if raw["raw_step_disagreement_abs"] is None
                else _finite_decimal_text(
                    raw["raw_step_disagreement_abs"],
                    "diagnostic raw_step_disagreement_abs",
                    nonnegative=True,
                )
            )
            guarded_step_disagreement_decimal = (
                None
                if raw["guarded_step_disagreement_abs"] is None
                else _finite_decimal_text(
                    raw["guarded_step_disagreement_abs"],
                    "diagnostic guarded_step_disagreement_abs",
                    nonnegative=True,
                )
            )
            derivative_lower_bound_decimal = _finite_decimal_text(
                raw["derivative_lower_bound_abs"],
                "diagnostic derivative_lower_bound_abs",
                nonnegative=True,
            )
            correction_upper_bound_decimal = _finite_decimal_text(
                raw["correction_upper_bound"],
                "diagnostic correction_upper_bound",
                nonnegative=True,
            )
            diagnostic_tolerance_decimal = _finite_decimal_text(
                raw["root_correction_tolerance"],
                "diagnostic root_correction_tolerance",
                nonnegative=True,
            )
            reported_displacement_decimal = _finite_decimal_text(
                raw["displacement_from_primary_abs"],
                "diagnostic displacement_from_primary_abs",
                nonnegative=True,
            )
            if (
                derivative_lower_bound_decimal <= 0
                or diagnostic_tolerance_decimal <= 0
                or raw["error_model_id"] != expected_error_model_id
                or raw["branch_identity"] != policy["branch_convention"]
            ):
                raise JuliaResponseBackendError(
                    "M02 Julia diagnostic scientific identity is invalid"
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
                expected_residual_upper_bound = (
                    diagnostic_residual_decimal + determinant_error_decimal
                )
                expected_required_derivative_lower_bound = (
                    residual_upper_bound_decimal
                    / diagnostic_tolerance_decimal
                )
                expected_correction = (
                    residual_upper_bound_decimal
                    / derivative_lower_bound_decimal
                )

                def inconsistent(left: Decimal, right: Decimal) -> bool:
                    scale = max(abs(left), abs(right), Decimal(1))
                    return abs(left - right) > serialization_allowance * scale

                branch_authenticated = (
                    derived_radius <= branch_tolerance_decimal
                )
                invalid_evidence = (
                    inconsistent(
                        derived_radius,
                        diagnostic_radii_decimal[family],
                    )
                    or inconsistent(
                        derived_radius,
                        reported_displacement_decimal,
                    )
                    or inconsistent(
                        diagnostic_derivative_decimal,
                        derivative_lower_bound_decimal,
                    )
                    or inconsistent(
                        expected_residual_upper_bound,
                        residual_upper_bound_decimal,
                    )
                    or inconsistent(
                        expected_required_derivative_lower_bound,
                        required_derivative_lower_bound_decimal,
                    )
                    or inconsistent(
                        expected_correction,
                        correction_upper_bound_decimal,
                    )
                    or inconsistent(
                        diagnostic_tolerance_decimal,
                        root_correction_tolerance,
                    )
                    or raw["branch_authenticated"] != branch_authenticated
                    or (
                        raw["root_converged"]
                        and (
                            not branch_authenticated
                            or correction_upper_bound_decimal
                            > diagnostic_tolerance_decimal
                        )
                    )
                )
                if invalid_evidence:
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
                correction_upper_bound=_finite_text(
                    raw["correction_upper_bound"],
                    "diagnostic correction_upper_bound",
                ),
                determinant_error_abs=_finite_text(
                    raw["determinant_error_abs"],
                    "diagnostic determinant_error_abs",
                ),
                error_model_id=raw["error_model_id"],
                derivative_lower_bound_abs=_finite_text(
                    raw["derivative_lower_bound_abs"],
                    "diagnostic derivative_lower_bound_abs",
                ),
                root_correction_tolerance=_finite_text(
                    raw["root_correction_tolerance"],
                    "diagnostic root_correction_tolerance",
                ),
                displacement_from_primary_abs=_finite_text(
                    raw["displacement_from_primary_abs"],
                    "diagnostic displacement_from_primary_abs",
                ),
                branch_identity=raw["branch_identity"],
                branch_authenticated=raw["branch_authenticated"],
                control_identity=raw["control_identity"],
                solve_role=raw["solve_role"],
                full_authentication_escalated=escalated,
                escalation_reason=escalation_reason,
                authenticated_evidence_reused=(
                    raw["authenticated_evidence_reused"]
                ),
                determinant_count=raw["determinant_count"],
                root_phase=raw["root_phase"],
                authentication_mode=raw["authentication_mode"],
                authoritative=raw["authoritative"],
                residual_upper_bound_abs=_finite_text(
                    raw["residual_upper_bound_abs"],
                    "diagnostic residual_upper_bound_abs",
                ),
                required_derivative_lower_bound_abs=_finite_text(
                    raw["required_derivative_lower_bound_abs"],
                    "diagnostic required_derivative_lower_bound_abs",
                ),
                raw_step_disagreement_abs=(
                    None
                    if raw["raw_step_disagreement_abs"] is None
                    else _finite_text(
                        raw["raw_step_disagreement_abs"],
                        "diagnostic raw_step_disagreement_abs",
                    )
                ),
                guarded_step_disagreement_abs=(
                    None
                    if raw["guarded_step_disagreement_abs"] is None
                    else _finite_text(
                        raw["guarded_step_disagreement_abs"],
                        "diagnostic guarded_step_disagreement_abs",
                    )
                ),
                propagated_derivative_error_abs=_finite_text(
                    raw["propagated_derivative_error_abs"],
                    "diagnostic propagated_derivative_error_abs",
                ),
                determinant_count_phase=raw["determinant_count_phase"],
            )
        receipt_material = {
            "schema": HISTORICAL_WORKER_RESPONSE_RECEIPT_SCHEMA,
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
                determinant_derivative_abs=float(
                    root_authentication.derivative_estimate.magnitude()
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
                root_authentication=root_authentication,
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


def promoted_request_preflight_documents(
    exterior_job: ResponseComponentJob,
    horizon_job: ResponseComponentJob,
    adapter: object,
    calibration_receipt: PromotedControlCalibrationReceipt,
) -> tuple[dict[str, object], ...]:
    """Build every promoted root and fixed-root wire shape through production."""

    if exterior_job.mechanism_id != "exterior-light-ring":
        raise ValueError("promoted-request preflight exterior job is invalid")
    if horizon_job.mechanism_id != "horizon-admittance":
        raise ValueError("promoted-request preflight horizon job is invalid")
    matrix: list[tuple[ResponseComponentJob, str, int, int]] = []
    for digits in (40, 80, 120):
        for refinement in (0, 1):
            matrix.append((
                exterior_job,
                "exterior-wronskian/v1",
                digits,
                refinement,
            ))
    for digits in (80, 120):
        for refinement in (0, 1):
            matrix.append((
                horizon_job,
                "horizon-scattering/v1",
                digits,
                refinement,
            ))
    requests: list[dict[str, object]] = []
    for job, determinant_family, digits, refinement in matrix:
        backend = JuliaPrecisionRootBackend(
            job.backend_identity,
            adapter,
            digits,
            refinement=refinement,
            empirical_control_profile=calibration_receipt.budget_for(
                determinant_family, digits
            ),
            calibration_receipt=calibration_receipt,
        )
        requests.append(backend.preview_root_request(job, 0.0j))
    # This digest is a contract-preflight placeholder, not root evidence.  It
    # exists only so the real fixed-root parser can authenticate the complete
    # production envelope without asking a root provider or running numerics.
    preflight_root_seal_sha256 = hashlib.sha256(canonical_json_bytes({
        "schema": "windows-solver.fixed-root-survey-preflight-root/1",
        "root_reference_id": exterior_job.root.root_reference_id,
        "branch_identity": exterior_job.root.branch_id,
        "fixed_root": {
            "real": format(exterior_job.root.omega.real, ".17g"),
            "imaginary": format(exterior_job.root.omega.imag, ".17g"),
        },
    })).hexdigest()
    for digits in (40, 80):
        backend = JuliaPrecisionRootBackend(
            exterior_job.backend_identity,
            adapter,
            digits,
            empirical_control_profile=calibration_receipt.budget_for(
                "exterior-wronskian/v1", digits
            ),
            calibration_receipt=calibration_receipt,
        )
        for plan in (
            FixedRootSurveyPlan.FULL_NINE,
            FixedRootSurveyPlan.CANONICAL_BACKGROUND_FIVE,
            FixedRootSurveyPlan.MECHANISM_COMPONENT_FOUR,
        ):
            requests.append(backend.preview_fixed_root_survey_request(
                exterior_job,
                fixed_root=exterior_job.root.omega,
                root_seal_sha256=preflight_root_seal_sha256,
                branch_identity=exterior_job.root.branch_id,
                plan=plan,
            ))
    return tuple(requests)


def build_promoted_request_contract_fixture(
    requests: tuple[Mapping[str, object], ...],
) -> dict[str, object]:
    """Build the canonical Python-owned fixture consumed by the Julia spec."""

    batch, _ = _promoted_request_set(requests)
    documents = list(batch["requests"])
    exterior = next(
        document
        for document in documents
        if document["operation"] == "root-readout"
        and document["mechanism_id"] == "exterior-light-ring"
        and document["precision_digits"] == 80
        and document["refinement_level"] == 0
    )
    # invalid_exterior_cases prove that empirical-only fields such as
    # determinant_error_safety_factor are forbidden on a PROVISIONAL
    # exterior policy. Injecting the field with any value must fail the
    # raw-determinant-contract disjointness check — the value's own JSON
    # type is irrelevant here, only the mode-boundary is under test.
    invalid_provisional_injection_values = (
        ("string", "64"),
        ("floating-point", 64.0),
        ("boolean", True),
        ("wrong-integer", 63),
        ("null", None),
    )
    invalid_cases: list[dict[str, object]] = []
    for label, value in invalid_provisional_injection_values:
        request = copy.deepcopy(exterior)
        request.pop("request_sha256")
        request["policy"]["determinant_error_safety_factor"] = value
        _, document, _ = _worker_request_document(request)
        invalid_cases.append({"label": label, "document": document})
    golden_contracts = copy.deepcopy(
        list(raw_determinant_contract_golden_cases())
    )
    default_receipt = load_default_calibration_receipt()
    empirical_profile = default_receipt.budget_for(
        "exterior-wronskian/v1", int(exterior["precision_digits"])
    )
    empirical_request = copy.deepcopy(exterior)
    empirical_request.pop("request_sha256", None)
    empirical_request.update({
        "diagnostic_model_identity": (
            EXTERIOR_DETERMINANT_ABSOLUTE_ERROR_CERTIFICATE
        ),
        "required_raw_determinant_roles": [
            "PRIMARY", "TRUNCATION", "RESOLUTION"
        ],
        "required_raw_determinant_count": 3,
    })
    empirical_policy = empirical_request["policy"]
    assert isinstance(empirical_policy, dict)
    for field in (
        "determinant_error_channel_schema",
        "determinant_error_required_channels",
        "determinant_error_calibration_status",
        "determinant_error_missing_evidence_outcome",
        "determinant_error_preceding_precision_tier",
        "determinant_error_required_term_classes",
        "determinant_error_certificate_statement",
        "determinant_error_safety_factor",
        "promoted_control_calibration_receipt_sha256",
        "empirical_control_profile_sha256",
    ):
        empirical_policy.pop(field, None)
    empirical_policy.update({
        "determinant_error_model": (
            EXTERIOR_DETERMINANT_ABSOLUTE_ERROR_CERTIFICATE
        ),
        "determinant_error_required_term_classes": list(
            _EXTERIOR_EMPIRICAL_TERM_CLASSES
        ),
        "determinant_error_missing_evidence_outcome": (
            EXTERIOR_DETERMINANT_CERTIFICATE_UNAVAILABLE
        ),
        "determinant_error_certificate_statement": (
            _EXTERIOR_EMPIRICAL_CERTIFICATE_STATEMENT
        ),
        "determinant_error_preceding_precision_tier": "bigfloat-40",
        "determinant_error_safety_factor": 64,
        "promoted_control_calibration_receipt_sha256": (
            default_receipt.sha256
        ),
        "empirical_control_profile_sha256": hashlib.sha256(
            canonical_json_bytes(empirical_profile.to_mapping())
        ).hexdigest(),
    })
    _, empirical_document, _ = _worker_request_document(empirical_request)
    # empirical_safety_factor_invalid_cases exercise the empirical
    # validator's own JSON type/value enforcement of
    # determinant_error_safety_factor. The mode is empirical, the field
    # is required, and the empirical validator requires an exact int 64.
    empirical_safety_factor_invalid_values = (
        ("string", "64"),
        ("floating-point", 64.0),
        ("boolean", True),
        ("wrong-integer", 63),
        ("null", None),
    )
    empirical_safety_factor_invalid_cases: list[dict[str, object]] = []
    for label, value in empirical_safety_factor_invalid_values:
        broken = copy.deepcopy(empirical_request)
        broken.pop("request_sha256", None)
        broken["policy"]["determinant_error_safety_factor"] = value
        _, broken_document, _ = _worker_request_document(broken)
        empirical_safety_factor_invalid_cases.append(
            {"label": label, "document": broken_document}
        )
    wire_documents = {
        "horizon-analytic": next(
            document
            for document in documents
            if document["mechanism_id"] == "horizon-admittance"
            and document["precision_digits"] == 80
            and document["refinement_level"] == 0
        ),
        "exterior-provisional-additive": exterior,
        "exterior-empirical-certificate": empirical_document,
    }
    for case in golden_contracts:
        case["wire_request"] = wire_documents[case["label"]]
    return {
        "schema_version": 1,
        "operation": "promoted-request-contract-fixture",
        "requests": documents,
        "invalid_exterior_cases": invalid_cases,
        "empirical_safety_factor_invalid_cases": (
            empirical_safety_factor_invalid_cases
        ),
        "golden_contracts": golden_contracts,
    }
