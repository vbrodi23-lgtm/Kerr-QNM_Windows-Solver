"""Build and authenticate the PR75 real-Julia/no-solver case matrix."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Mapping

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
from windows_solver.operation_control import ValidatedControlReceipt
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


CASE_BATCH_SCHEMA = "windows-solver.pr75-fixed-root-case-batch/1"
RESULT_BATCH_SCHEMA = "windows-solver.pr75-fixed-root-result-batch/1"
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
    return {"schema": CASE_BATCH_SCHEMA, "cases": cases}


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
    if not isinstance(value, dict) or set(value) != {"schema", "cases"}:
        raise ValueError("PR75 case batch fields are invalid")
    if value["schema"] != CASE_BATCH_SCHEMA or not isinstance(value["cases"], list):
        raise ValueError("PR75 case batch schema is invalid")
    return value


def parsed_result_batch(path: Path) -> dict[str, object]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict) or set(value) != {"schema", "results"}:
        raise ValueError("PR75 result batch fields are invalid")
    if value["schema"] != RESULT_BATCH_SCHEMA or not isinstance(
        value["results"], list
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
    return {"success_count": success_count, "failure_count": failure_count}


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
