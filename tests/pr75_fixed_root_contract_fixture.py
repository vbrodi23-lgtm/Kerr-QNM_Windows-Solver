"""Build and authenticate the PR75 real-Julia/no-solver case matrix."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Mapping

from tests.fixtures import (
    valid_julia_root_response,
    valid_numerical_conditioning,
)
from windows_solver.julia_response_backend import (
    FIXED_ROOT_SURVEY_BATCH_RESPONSE_SCHEMA,
    FixedRootSurveyPlan,
    JuliaFixedRootSurveyBatch,
    JuliaNumericalControlError,
    JuliaPrecisionRootBackend,
    JuliaResponseEvaluation,
    _bind_control_failure_to_request,
    _raise_worker_failure,
    _worker_request_document,
)
from windows_solver.operation_control import (
    FIXED_ROOT_DETERMINANT_SAMPLE_OPERATION,
    ROOT_READOUT_OPERATION,
    ValidatedControlReceipt,
)
from windows_solver.promoted_control_calibration import (
    load_default_calibration_receipt,
)
from windows_solver.response_batches import (
    PrecisionCapabilities,
    build_campaign_plan,
)
from windows_solver.response_engine import (
    NumericalPolicy,
    VettedNativeDeterminantKernel,
)


CASE_BATCH_SCHEMA = "windows-solver.pr75-fixed-root-case-batch/2"
RESULT_BATCH_SCHEMA = "windows-solver.pr75-fixed-root-result-batch/2"
ROOT_SEAL_SHA256 = "1" * 64
RUNTIME_PROVENANCE = {
    "julia_version": "1.10.11-pr75-no-solver",
    "julia_executable_sha256": "a" * 64,
    "julia_manifest_sha256": "b" * 64,
    "worker_sha256": "c" * 64,
    "runtime_policy_sha256": "d" * 64,
    "scientific_sources": [],
}


def _job():
    plan = build_campaign_plan(
        policy=NumericalPolicy(),
        backend_identity=VettedNativeDeterminantKernel.identity,
        precision_capabilities=PrecisionCapabilities((64, 80, 120)),
    )
    return next(
        leaf.job
        for leaf in plan.leaves
        if leaf.job.mechanism_id == "exterior-light-ring"
    )


def _backend(adapter: object, digits: int) -> JuliaPrecisionRootBackend:
    calibration = load_default_calibration_receipt()
    return JuliaPrecisionRootBackend(
        VettedNativeDeterminantKernel.identity,
        adapter,
        digits,
        empirical_control_profile=calibration.budget_for(
            "exterior-wronskian/v1", digits
        ),
        calibration_receipt=calibration,
    )


def build_case_batch() -> dict[str, object]:
    job = _job()
    preview_adapter = SimpleNamespace(runtime_provenance=RUNTIME_PROVENANCE)
    cases: list[dict[str, object]] = []
    for digits in (40, 80):
        backend = _backend(preview_adapter, digits)
        for plan in FixedRootSurveyPlan:
            request = backend.preview_fixed_root_survey_request(
                job,
                fixed_root=job.root.omega,
                root_seal_sha256=ROOT_SEAL_SHA256,
                branch_identity=job.root.branch_id,
                plan=plan,
            )
            request_binding, wire_request, _ = _worker_request_document(request)
            base = {
                "digits": digits,
                "plan": plan.value,
                "request_binding": request_binding,
                "request": wire_request,
            }
            cases.append({
                **base,
                "case_id": f"success:{digits}:{plan.value}",
                "failure_sample_index": None,
            })
            for sample_index in range(len(request["samples"])):
                cases.append({
                    **base,
                    "case_id": (
                        f"failure:{digits}:{plan.value}:{sample_index}"
                    ),
                    "failure_sample_index": sample_index,
                })
    if len(cases) != 42:
        raise AssertionError("PR75 case matrix must contain 6 success and 36 failure cases")

    compatibility_backend = _backend(preview_adapter, 80)
    root_request = compatibility_backend.preview_root_request(job, 0.0j)
    root_binding, root_wire, _ = _worker_request_document(root_request)
    root_success = valid_julia_root_response(root_wire)
    for field in (
        "schema_version",
        "status",
        "adapter",
        "operation",
        "request_sha256",
        "execution_identity",
    ):
        root_success.pop(field)

    readout_role = "coordinate-real-plus-h"
    amplitude = 0.003 + 0.0j
    fixed_request = compatibility_backend.preview_fixed_root_request(
        job, job.root.omega, amplitude, readout_role
    )
    fixed_binding, fixed_wire, _ = _worker_request_document(fixed_request)
    fixed_policy = fixed_wire["policy"]
    fixed_success = {
        "omega_re": fixed_wire["fixed_omega"]["real"],
        "omega_im": fixed_wire["fixed_omega"]["imaginary"],
        "amplitude_re": fixed_wire["amplitude"]["real"],
        "amplitude_im": fixed_wire["amplitude"]["imaginary"],
        "determinant_re": "0.006000000001",
        "determinant_im": "0.009",
        "determinant_error_abs": "4e-12",
        "determinant_error_status": "available/v1",
        "determinant_error_model_id": fixed_policy["determinant_error_model"],
        "determinant_family": fixed_policy["determinant_family"],
        "determinant_normalisation": fixed_policy["determinant_normalisation"],
        "branch_identity": fixed_policy["branch_convention"],
        "branch_authenticated": True,
        "semantic_precision_tier": fixed_wire["semantic_precision_tier"],
        "working_precision_bits": fixed_wire["working_precision_bits"],
        "readout_role": readout_role,
        "numerical_conditioning": valid_numerical_conditioning(
            job.mechanism_id
        ),
    }
    compatibility_cases = []
    for operation, binding, wire, success_fields in (
        (ROOT_READOUT_OPERATION, root_binding, root_wire, root_success),
        (
            FIXED_ROOT_DETERMINANT_SAMPLE_OPERATION,
            fixed_binding,
            fixed_wire,
            fixed_success,
        ),
    ):
        compatibility_cases.extend((
            {
                "case_id": f"compatibility:{operation}:success",
                "outcome": "success",
                "request_binding": binding,
                "request": wire,
                "success_fields": success_fields,
            },
            {
                "case_id": f"compatibility:{operation}:control",
                "outcome": "control",
                "request_binding": binding,
                "request": wire,
                "success_fields": None,
            },
        ))
    return {
        "schema": CASE_BATCH_SCHEMA,
        "cases": cases,
        "compatibility_cases": compatibility_cases,
    }


class CapturedJuliaAdapter:
    """Feed real Julia bytes through the production Python binding seam."""

    runtime_provenance = RUNTIME_PROVENANCE

    def __init__(self, case: Mapping[str, object], response: Mapping[str, object]):
        self.case = case
        self.response = response

    def evaluate_for_validation(
        self, request: Mapping[str, object]
    ) -> JuliaResponseEvaluation:
        request_binding, document, request_sha256 = _worker_request_document(request)
        if request_binding != self.case["request_binding"] or document != self.case[
            "request"
        ]:
            raise AssertionError("Python reconstructed different PR75 request bytes")
        response = dict(self.response)
        if response.get("status") == "ok":
            return JuliaResponseEvaluation(
                response=response,
                request_binding=request_binding,
                request_sha256=request_sha256,
                runtime_identity_sha256="e" * 64,
                reused=False,
                cached_worker_response_receipt=None,
            )
        if set(response) != {
            "schema_version",
            "status",
            "error_type",
            "message",
            "failure",
        }:
            raise AssertionError("Julia PR75 error envelope is not canonical")
        details = {
            "worker_exit_code": 21,
            "worker_timed_out": False,
            "worker_stderr_tail": "",
            "worker_error_type": response["error_type"],
            "worker_error_message": response["message"],
            "failure": response["failure"],
        }
        bound, receipt = _bind_control_failure_to_request(
            details, request_binding, request_sha256
        )
        _raise_worker_failure(bound, control_receipt=receipt)
        raise AssertionError("worker failure translator returned")


def parsed_case_batch(path: Path) -> dict[str, object]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict) or set(value) != {
        "schema", "cases", "compatibility_cases"
    }:
        raise ValueError("PR75 case batch fields are invalid")
    if (
        value["schema"] != CASE_BATCH_SCHEMA
        or not isinstance(value["cases"], list)
        or not isinstance(value["compatibility_cases"], list)
    ):
        raise ValueError("PR75 case batch schema is invalid")
    return value


def parsed_result_batch(path: Path) -> dict[str, object]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict) or set(value) != {
        "schema", "results", "compatibility_results",
        "reliability_negative_count",
    }:
        raise ValueError("PR75 result batch fields are invalid")
    if (
        value["schema"] != RESULT_BATCH_SCHEMA
        or not isinstance(value["results"], list)
        or not isinstance(value["compatibility_results"], list)
        or value["reliability_negative_count"] != 10
    ):
        raise ValueError("PR75 result batch schema is invalid")
    return value


def verify_case_matrix(
    case_batch: Mapping[str, object], result_batch: Mapping[str, object]
) -> dict[str, int]:
    cases = case_batch["cases"]
    results = result_batch["results"]
    if not isinstance(cases, list) or not isinstance(results, list):
        raise ValueError("PR75 matrix collections are invalid")
    by_id = {
        result["case_id"]: result
        for result in results
        if isinstance(result, Mapping) and isinstance(result.get("case_id"), str)
    }
    if len(by_id) != len(results) or set(by_id) != {
        case["case_id"] for case in cases
    }:
        raise ValueError("PR75 Julia results do not cover the exact case matrix")
    job = _job()
    success_count = failure_count = 0
    for case in cases:
        result = by_id[case["case_id"]]
        if result.get("determinant_kernel_calls") != 0:
            raise AssertionError("PR75 no-solver case reached determinant work")
        response = result.get("response")
        if not isinstance(response, Mapping):
            raise ValueError("PR75 Julia response is invalid")
        digits = int(case["digits"])
        plan = FixedRootSurveyPlan(str(case["plan"]))
        backend = _backend(CapturedJuliaAdapter(case, response), digits)
        target = case["failure_sample_index"]
        if target is None:
            batch = backend.fixed_root_survey_batch(
                job,
                fixed_root=job.root.omega,
                root_seal_sha256=ROOT_SEAL_SHA256,
                branch_identity=job.root.branch_id,
                plan=plan,
            )
            if not isinstance(batch, JuliaFixedRootSurveyBatch):
                raise AssertionError("PR75 success did not authenticate as a batch")
            if batch.to_mapping()["schema"] != FIXED_ROOT_SURVEY_BATCH_RESPONSE_SCHEMA:
                raise AssertionError("PR75 success response schema is invalid")
            success_count += 1
            continue
        try:
            backend.fixed_root_survey_batch(
                job,
                fixed_root=job.root.omega,
                root_seal_sha256=ROOT_SEAL_SHA256,
                branch_identity=job.root.branch_id,
                plan=plan,
            )
        except JuliaNumericalControlError as error:
            receipt = error.control_receipt
            if not isinstance(receipt, ValidatedControlReceipt):
                raise AssertionError("PR75 failure lacks a validated receipt")
            identity = receipt.identity.mapping
            expected_sample = case["request"]["samples"][int(target)]
            diagnostics = receipt.mapping["diagnostics"]
            if (
                receipt.failure_code != "INSUFFICIENT_ASYMPTOTIC_PRECISION"
                or identity["scope"] != "SAMPLE"
                or identity["sample_index"] != target
                or identity["sample_role"] != expected_sample["sample_role"]
                or diagnostics["factored_homogeneous_rhs_evaluations"] != 0
                or diagnostics["avoided_ode_scope"]
                != "factored-homogeneous-gsn/v1"
            ):
                raise AssertionError("PR75 failure identity or zero-RHS proof is invalid")
            failure_count += 1
        else:
            raise AssertionError("PR75 failure case returned success")
    if (success_count, failure_count) != (6, 36):
        raise AssertionError("PR75 matrix cardinality is invalid")
    compatibility = verify_compatibility_cases(
        case_batch["compatibility_cases"],
        result_batch["compatibility_results"],
    )
    return {
        "success_count": success_count,
        "failure_count": failure_count,
        "reliability_negative_count": int(
            result_batch["reliability_negative_count"]
        ),
        **compatibility,
    }


def verify_compatibility_cases(
    cases: object, results: object
) -> dict[str, int]:
    if not isinstance(cases, list) or not isinstance(results, list):
        raise ValueError("PR75 compatibility collections are invalid")
    if len(cases) != 4 or len(results) != 4:
        raise ValueError("PR75 compatibility matrix cardinality is invalid")
    by_id = {
        result["case_id"]: result
        for result in results
        if isinstance(result, Mapping) and isinstance(result.get("case_id"), str)
    }
    if len(by_id) != 4 or set(by_id) != {case["case_id"] for case in cases}:
        raise ValueError("PR75 compatibility results are incomplete")

    job = _job()
    success_count = control_count = 0
    for case in cases:
        result = by_id[case["case_id"]]
        if result.get("determinant_kernel_calls") != 0:
            raise AssertionError("compatibility case reached determinant work")
        response = result.get("response")
        if not isinstance(response, Mapping):
            raise ValueError("PR75 compatibility response is invalid")
        operation = case["request"]["operation"]
        backend = _backend(CapturedJuliaAdapter(case, response), 80)
        try:
            if operation == ROOT_READOUT_OPERATION:
                outcome = backend.read_root(job, 0.0j)
            elif operation == FIXED_ROOT_DETERMINANT_SAMPLE_OPERATION:
                outcome = backend.sample_fixed_root_determinant(
                    job,
                    job.root.omega,
                    0.003 + 0.0j,
                    readout_role="coordinate-real-plus-h",
                )
            else:
                raise AssertionError("unknown compatibility operation")
        except JuliaNumericalControlError as error:
            if case["outcome"] != "control":
                raise
            receipt = error.control_receipt
            if not isinstance(receipt, ValidatedControlReceipt):
                raise AssertionError("compatibility control lacks validated receipt")
            identity = receipt.identity.mapping
            if identity["operation"] != operation or identity["scope"] != "REQUEST":
                raise AssertionError("compatibility control identity is invalid")
            if operation == FIXED_ROOT_DETERMINANT_SAMPLE_OPERATION and (
                identity["fixed_omega"] != case["request"]["fixed_omega"]
                or identity["branch_identity"]
                != case["request"]["policy"]["branch_convention"]
                or identity["readout_role"] != case["request"]["readout_role"]
            ):
                raise AssertionError("fixed-sample compatibility identity is invalid")
            control_count += 1
        else:
            if case["outcome"] != "success" or outcome is None:
                raise AssertionError("compatibility success returned invalid outcome")
            success_count += 1
    if (success_count, control_count) != (2, 2):
        raise AssertionError("PR75 compatibility matrix result is invalid")
    return {
        "compatibility_success_count": success_count,
        "compatibility_control_count": control_count,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    write = subparsers.add_parser("write")
    write.add_argument("output", type=Path)
    verify = subparsers.add_parser("verify")
    verify.add_argument("cases", type=Path)
    verify.add_argument("results", type=Path)
    args = parser.parse_args()
    if args.command == "write":
        args.output.write_bytes(
            json.dumps(
                build_case_batch(), sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        )
        return
    summary = verify_case_matrix(
        parsed_case_batch(args.cases), parsed_result_batch(args.results)
    )
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
