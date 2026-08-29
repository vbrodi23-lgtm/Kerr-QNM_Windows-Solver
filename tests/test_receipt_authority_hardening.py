from __future__ import annotations

from types import SimpleNamespace
import unittest

from windows_solver.campaign_survey import _promoted_control_receipt
from windows_solver.julia_response_backend import (
    JuliaODEResourceLimitError,
    JuliaResponseBackendError,
    _execution_resource_policy,
)
from windows_solver.operation_control import (
    JULIA_PRODUCER_RETRYABILITY_BASIS,
    JULIA_WORKER_ORIGIN,
    build_operation_control_receipt,
    canonical_sha256,
    execution_identity_from_request,
    validate_operation_control_receipt,
)
from windows_solver.production_wiring import _PROMOTED_RUNTIME_IDENTITY_FILES
from windows_solver.promoted_control_authority import (
    classify_control_receipt_material,
)
from tests.test_operation_control import _fixed_request


def _generic_insufficiency_receipt():
    request = _fixed_request()
    request["execution_resource"] = _execution_resource_policy()
    request_sha256 = canonical_sha256(request)
    identity = execution_identity_from_request(
        request,
        request_sha256=request_sha256,
        sample_index=0,
        sample_role="D0",
    )
    mapping = build_operation_control_receipt(
        origin=JULIA_WORKER_ORIGIN,
        failure_code="INSUFFICIENT_ASYMPTOTIC_PRECISION",
        stage="asymptotic-preflight",
        identity=identity,
        retryable=True,
        retryable_basis=JULIA_PRODUCER_RETRYABILITY_BASIS,
        diagnostics={"reason": "INSUFFICIENT_ASYMPTOTIC_PRECISION"},
    )
    return validate_operation_control_receipt(
        mapping,
        request=request,
        request_sha256=request_sha256,
        diagnostics_validator=lambda _receipt: True,
    )


class ReceiptAuthorityHardeningTests(unittest.TestCase):
    def test_generic_structural_receipt_cannot_classify(self) -> None:
        with self.assertRaises(ValueError):
            classify_control_receipt_material(
                _generic_insufficiency_receipt(),
                current_tier="BF40",
                current_action_kind="RESPONSE",
            )

    def test_exterior_exception_class_must_match_receipt_code(self) -> None:
        receipt = _generic_insufficiency_receipt()
        error = JuliaODEResourceLimitError("wrong exception class")
        error.control_receipt = receipt
        leaf = SimpleNamespace(job=SimpleNamespace(
            leaf_id="leaf-fixed",
            job_id="job-fixed",
            backend_identity=SimpleNamespace(identity_sha256="b" * 64),
        ))

        with self.assertRaisesRegex(
            JuliaResponseBackendError,
            "exception identity",
        ):
            _promoted_control_receipt(
                error,
                leaf=leaf,
                digits=40,
                current_action_kind="RESPONSE",
            )

    def test_promoted_resolution_identity_includes_all_authority_owners(self) -> None:
        self.assertTrue({
            "operation_control.py",
            "julia_response_backend.py",
            "fixed_root_reliability.py",
            "data/fixed_root_reliability_projection_authority_v1.json",
            "promoted_control_authority.py",
        }.issubset(_PROMOTED_RUNTIME_IDENTITY_FILES))


if __name__ == "__main__":
    unittest.main()
