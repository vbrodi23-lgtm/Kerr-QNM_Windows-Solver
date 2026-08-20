#!/usr/bin/env python3
"""Generate or run the no-solver M02 promoted-request contract preflight."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

from windows_solver.contracts import canonical_json_bytes
from windows_solver.julia_response_backend import (
    JuliaResponseAdapter,
    _promoted_request_set,
    _validate_promoted_request_preflight_response,
    build_promoted_request_contract_fixture,
    promoted_request_preflight_documents,
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


def _inputs(adapter: object):
    plan = build_campaign_plan(
        policy=NumericalPolicy(),
        backend_identity=VettedNativeDeterminantKernel.identity,
        precision_capabilities=PrecisionCapabilities((64, 80, 120)),
    )
    jobs = {
        leaf.mechanism_id: leaf.job
        for leaf in plan.leaves
        if leaf.role == "primary"
        and leaf.mechanism_id in {
            "exterior-light-ring", "horizon-admittance"
        }
        and (leaf.job.mode.ell, leaf.job.mode.m, leaf.job.mode.n) == (2, 2, 1)
        and leaf.job.spin == 0.95
    }
    receipt = load_default_calibration_receipt()
    requests = promoted_request_preflight_documents(
        jobs["exterior-light-ring"],
        jobs["horizon-admittance"],
        adapter,
        receipt,
    )
    return plan, receipt, requests


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write-contract-fixture",
        type=Path,
        help="write canonical production requests for the Julia contract spec",
    )
    parser.add_argument(
        "--write-preflight-batch",
        type=Path,
        help="write the canonical batch consumed by the Julia worker CLI",
    )
    parser.add_argument(
        "--verify-preflight-response",
        nargs=2,
        metavar=("BATCH_JSON", "RESPONSE_JSON"),
        type=Path,
        help="authenticate a Julia worker CLI preflight response",
    )
    parser.add_argument(
        "--runtime-root",
        type=Path,
        help="override the provisioned runtime used for an actual preflight",
    )
    arguments = parser.parse_args()

    selected_actions = sum(
        action is not None
        for action in (
            arguments.write_contract_fixture,
            arguments.write_preflight_batch,
            arguments.verify_preflight_response,
        )
    )
    if selected_actions > 1:
        parser.error("select only one fixture or verification action")

    if arguments.write_contract_fixture is not None:
        _, _, requests = _inputs(SimpleNamespace(runtime_provenance={}))
        fixture = build_promoted_request_contract_fixture(requests)
        arguments.write_contract_fixture.parent.mkdir(parents=True, exist_ok=True)
        arguments.write_contract_fixture.write_bytes(canonical_json_bytes(fixture))
        return 0

    if arguments.write_preflight_batch is not None:
        _, _, requests = _inputs(SimpleNamespace(runtime_provenance={}))
        batch, _ = _promoted_request_set(requests)
        arguments.write_preflight_batch.parent.mkdir(parents=True, exist_ok=True)
        arguments.write_preflight_batch.write_bytes(canonical_json_bytes(batch))
        return 0

    if arguments.verify_preflight_response is not None:
        batch_path, response_path = arguments.verify_preflight_response
        batch = json.loads(batch_path.read_text(encoding="utf-8"))
        response = json.loads(response_path.read_text(encoding="utf-8"))
        documents = batch["requests"]
        _validate_promoted_request_preflight_response(
            response,
            request_set_sha256=batch["request_set_sha256"],
            request_sha256s=tuple(
                document["request_sha256"] for document in documents
            ),
        )
        return 0

    adapter = JuliaResponseAdapter.from_runtime_receipt(
        runtime_root=arguments.runtime_root
    )
    plan, receipt, requests = _inputs(adapter)
    result = adapter.preflight_promoted_requests(
        requests,
        calibration_receipt_sha256=receipt.sha256,
        policy_sha256=plan.policy.identity_sha256,
        precision_capabilities_sha256=(
            plan.precision_capabilities.identity_sha256
        ),
    )
    print(json.dumps(
        {
            "status": "ok",
            "reused": result.reused,
            "binding": dict(result.binding),
            "response": dict(result.response),
        },
        sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
