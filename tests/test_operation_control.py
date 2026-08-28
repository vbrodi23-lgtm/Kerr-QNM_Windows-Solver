from __future__ import annotations

import copy
import unittest

from windows_solver.operation_control import (
    FIXED_ROOT_SURVEY_BATCH_OPERATION,
    JULIA_WORKER_ORIGIN,
    OPERATION_CONTROL_RECEIPT_SCHEMA,
    PROMOTED_CONTROL_TRANSITIONS,
    PYTHON_SUPERVISOR_ORIGIN,
    REQUEST_SCOPE,
    ROOT_READOUT_OPERATION,
    SAMPLE_SCOPE,
    ValidatedControlReceipt,
    build_operation_control_receipt,
    canonical_sha256,
    execution_identity_from_request,
    promoted_control_transition,
    validate_operation_control_receipt,
)


def _resource() -> dict[str, object]:
    return {
        "schema": "windows-solver.execution-resource-policy/1",
        "version": 1,
        "sha256": "e" * 64,
    }


def _fixed_request() -> dict[str, object]:
    return {
        "schema_version": 2,
        "schema": "windows-solver.fixed-root-survey-batch/2",
        "operation": FIXED_ROOT_SURVEY_BATCH_OPERATION,
        "leaf_id": "leaf-fixed",
        "job_id": "job-fixed",
        "backend_identity_sha256": "b" * 64,
        "precision_digits": 40,
        "working_precision_bits": 165,
        "semantic_precision_tier": "bigfloat-40",
        "plan": "CANONICAL_BACKGROUND_FIVE",
        "scientific_operation_identity": (
            "canonical-exterior-background-wronskian/v1"
        ),
        "root_reference_id": "root-1",
        "root_seal_sha256": "a" * 64,
        "branch_identity": "gsn-complex-rho/v1",
        "sample_roles": ["D0", "DOMEGA_REAL_PLUS_H"],
        "samples": [
            {"sample_index": 0, "sample_role": "D0"},
            {"sample_index": 1, "sample_role": "DOMEGA_REAL_PLUS_H"},
        ],
        "policy": {"fixed_root_gate": "strict/v1"},
        "execution_resource": _resource(),
    }


def _root_request() -> dict[str, object]:
    return {
        "schema_version": 1,
        "operation": ROOT_READOUT_OPERATION,
        "leaf_id": "leaf-root",
        "job_id": "job-root",
        "backend_identity_sha256": "c" * 64,
        "precision_digits": 40,
        "working_precision_bits": 165,
        "semantic_precision_tier": "bigfloat-40",
        "role": "primary-root",
        "job_policy_sha256": "d" * 64,
        "refinement_level": 0,
        "policy": {"root_gate": "strict/v1"},
        "execution_resource": _resource(),
    }


def _identity(
    operation: str,
    scope: str,
    *,
    tier: str,
):
    request = _root_request() if operation == ROOT_READOUT_OPERATION else _fixed_request()
    digits = int(tier[2:])
    request["precision_digits"] = digits
    request["working_precision_bits"] = {40: 165, 80: 298}[digits]
    request["semantic_precision_tier"] = f"bigfloat-{digits}"
    request_sha256 = canonical_sha256(request)
    if scope == SAMPLE_SCOPE:
        return request, execution_identity_from_request(
            request,
            request_sha256=request_sha256,
            sample_index=0,
            sample_role="D0",
        )
    return request, execution_identity_from_request(
        request,
        request_sha256=request_sha256,
    )


def _validated_for_transition(transition):
    request, identity = _identity(
        transition.operation,
        transition.scope,
        tier=transition.current_tier,
    )
    receipt = build_operation_control_receipt(
        origin=transition.origin,
        failure_code=transition.failure_code,
        stage=transition.stage,
        identity=identity,
        retryable=transition.containable,
        retryable_basis="registry-test/v1",
        diagnostics={"reason": transition.failure_code},
    )
    return validate_operation_control_receipt(
        receipt,
        request=request,
        request_sha256=identity.request_sha256,
    )


class OperationControlTests(unittest.TestCase):
    def test_request_and_sample_identity_are_disjoint(self) -> None:
        request = _fixed_request()
        request_sha256 = canonical_sha256(request)
        outer = execution_identity_from_request(
            request, request_sha256=request_sha256
        )
        selected = outer.select_sample(1, "DOMEGA_REAL_PLUS_H")

        self.assertEqual(REQUEST_SCOPE, outer.scope)
        self.assertNotIn("sample_index", outer.mapping)
        self.assertNotIn("sample_role", outer.mapping)
        self.assertEqual(SAMPLE_SCOPE, selected.scope)
        self.assertEqual(1, selected.mapping["sample_index"])
        self.assertEqual("DOMEGA_REAL_PLUS_H", selected.mapping["sample_role"])
        with self.assertRaises(ValueError):
            outer.select_sample(0, "DOMEGA_REAL_PLUS_H")

    def test_root_and_fixed_root_identity_cannot_cross_bind(self) -> None:
        fixed_request, fixed_identity = _identity(
            FIXED_ROOT_SURVEY_BATCH_OPERATION, SAMPLE_SCOPE, tier="BF40"
        )
        receipt = build_operation_control_receipt(
            origin=JULIA_WORKER_ORIGIN,
            failure_code="INSUFFICIENT_ASYMPTOTIC_PRECISION",
            stage="asymptotic-preflight",
            identity=fixed_identity,
            retryable=True,
            retryable_basis="precision-insufficiency/v1",
            diagnostics={"reason": "INSUFFICIENT_ASYMPTOTIC_PRECISION"},
        )
        root_request = _root_request()
        with self.assertRaises(ValueError):
            validate_operation_control_receipt(
                receipt,
                request=root_request,
                request_sha256=canonical_sha256(root_request),
            )
        validated = validate_operation_control_receipt(
            receipt,
            request=fixed_request,
            request_sha256=fixed_identity.request_sha256,
        )
        with self.assertRaises(ValueError):
            promoted_control_transition(
                validated,
                current_tier="BF40",
                current_action_kind="ROOT",
            )

    def test_receipt_digest_binding_and_diagnostics_fail_closed(self) -> None:
        request, identity = _identity(
            FIXED_ROOT_SURVEY_BATCH_OPERATION, SAMPLE_SCOPE, tier="BF40"
        )
        receipt = build_operation_control_receipt(
            origin=JULIA_WORKER_ORIGIN,
            failure_code="INSUFFICIENT_ASYMPTOTIC_PRECISION",
            stage="asymptotic-preflight",
            identity=identity,
            retryable=True,
            retryable_basis="precision-insufficiency/v1",
            diagnostics={"reason": "INSUFFICIENT_ASYMPTOTIC_PRECISION"},
        )
        validated = validate_operation_control_receipt(
            receipt,
            request=request,
            request_sha256=identity.request_sha256,
        )
        self.assertIsInstance(validated, ValidatedControlReceipt)
        self.assertEqual(OPERATION_CONTROL_RECEIPT_SCHEMA, validated.mapping["schema"])

        tampered = copy.deepcopy(receipt)
        tampered["failure_code"] = "FACTORED_ODE_FAILURE"
        with self.assertRaises(ValueError):
            validate_operation_control_receipt(tampered)

        incomplete = build_operation_control_receipt(
            origin=JULIA_WORKER_ORIGIN,
            failure_code="INSUFFICIENT_ASYMPTOTIC_PRECISION",
            stage="asymptotic-preflight",
            identity=identity,
            retryable=True,
            retryable_basis="precision-insufficiency/v1",
            diagnostics={},
        )
        with self.assertRaises(ValueError):
            validate_operation_control_receipt(incomplete)

        with self.assertRaises(TypeError):
            ValidatedControlReceipt(receipt, identity, _token=object())

    def test_registry_is_exact_closed_and_self_consistent(self) -> None:
        self.assertTrue(PROMOTED_CONTROL_TRANSITIONS)
        for key, transition in PROMOTED_CONTROL_TRANSITIONS.items():
            with self.subTest(key=key):
                self.assertEqual(key, transition.key)
                validated = _validated_for_transition(transition)
                self.assertEqual(
                    transition,
                    promoted_control_transition(
                        validated,
                        current_tier=transition.current_tier,
                        current_action_kind=transition.current_action_kind,
                    ),
                )

    def test_observed_bf40_failure_promotes_only_response_to_bf80(self) -> None:
        transition = next(
            item
            for item in PROMOTED_CONTROL_TRANSITIONS.values()
            if item.operation == FIXED_ROOT_SURVEY_BATCH_OPERATION
            and item.failure_code == "INSUFFICIENT_ASYMPTOTIC_PRECISION"
            and item.current_tier == "BF40"
        )
        self.assertEqual(JULIA_WORKER_ORIGIN, transition.origin)
        self.assertEqual(SAMPLE_SCOPE, transition.scope)
        self.assertEqual("PROMOTION_PENDING", transition.disposition)
        self.assertEqual("RESPONSE", transition.queue_kind)
        self.assertEqual("BF80", transition.next_tier)
        self.assertEqual("RESPONSE", transition.next_action_kind)

    def test_timeout_is_request_scoped_and_never_precision_promotion(self) -> None:
        fixed_timeouts = [
            item
            for item in PROMOTED_CONTROL_TRANSITIONS.values()
            if item.operation == FIXED_ROOT_SURVEY_BATCH_OPERATION
            and item.failure_code == "WORKER_TIMEOUT"
        ]
        self.assertEqual(2, len(fixed_timeouts))
        for transition in fixed_timeouts:
            self.assertEqual(PYTHON_SUPERVISOR_ORIGIN, transition.origin)
            self.assertEqual(REQUEST_SCOPE, transition.scope)
            self.assertEqual("DEFERRED", transition.disposition)
            self.assertIsNone(transition.next_tier)
            self.assertIsNone(transition.queue_kind)


if __name__ == "__main__":
    unittest.main()
