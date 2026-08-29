from __future__ import annotations

import copy
import unittest
from typing import Mapping

from windows_solver.operation_control import (
    FIXED_ROOT_DETERMINANT_SAMPLE_OPERATION,
    FIXED_ROOT_SURVEY_BATCH_OPERATION,
    JULIA_WORKER_ORIGIN,
    NUMERICAL_CONTROL_FAILURE_CODES,
    OPERATION_CONTROL_RECEIPT_SCHEMA,
    PROMOTED_CONTROL_TRANSITIONS,
    PYTHON_SUPERVISOR_ORIGIN,
    REQUEST_SCOPE,
    ROOT_READOUT_OPERATION,
    SAMPLE_SCOPE,
    ValidatedControlReceipt,
    build_operation_control_receipt,
    canonical_sha256,
    expected_operation_control_retryability,
    execution_identity_from_request,
    operation_execution_identity,
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
        "schema_version": 3,
        "schema": "windows-solver.fixed-root-survey-batch/3",
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


def _fixed_sample_request() -> dict[str, object]:
    request = _root_request()
    request.update({
        "operation": FIXED_ROOT_DETERMINANT_SAMPLE_OPERATION,
        "fixed_omega": {"real": "0.5", "imaginary": "-0.1"},
        "readout_role": "coordinate-real-plus-h",
    })
    request["policy"] = {
        **request["policy"],
        "branch_convention": "gsn-complex-rho/v1",
    }
    return request


def _identity(
    operation: str,
    scope: str,
    *,
    tier: str,
):
    request = (
        _root_request()
        if operation == ROOT_READOUT_OPERATION
        else _fixed_sample_request()
        if operation == FIXED_ROOT_DETERMINANT_SAMPLE_OPERATION
        else _fixed_request()
    )
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
        retryable=expected_operation_control_retryability(
            transition.failure_code
        ),
        retryable_basis="registry-test/v1",
        diagnostics={"reason": transition.failure_code},
    )
    return validate_operation_control_receipt(
        receipt,
        request=request,
        request_sha256=identity.request_sha256,
    )


class OperationControlTests(unittest.TestCase):
    def test_all_identity_variants_reject_omission_and_cross_fields(self) -> None:
        root_request = _root_request()
        fixed_sample_request = _fixed_sample_request()
        fixed_request = _fixed_request()
        fixed_sha256 = canonical_sha256(fixed_request)
        identities = (
            execution_identity_from_request(
                root_request,
                request_sha256=canonical_sha256(root_request),
            ),
            execution_identity_from_request(
                fixed_sample_request,
                request_sha256=canonical_sha256(fixed_sample_request),
            ),
            execution_identity_from_request(
                fixed_request,
                request_sha256=fixed_sha256,
            ),
            execution_identity_from_request(
                fixed_request,
                request_sha256=fixed_sha256,
                sample_index=0,
                sample_role="D0",
            ),
        )
        for identity in identities:
            for field in identity.mapping:
                with self.subTest(
                    operation=identity.operation,
                    scope=identity.scope,
                    missing=field,
                ):
                    incomplete = identity.to_mapping()
                    incomplete.pop(field)
                    with self.assertRaises(ValueError):
                        operation_execution_identity(incomplete)

        root_identity = identities[0].to_mapping()
        root_identity["plan"] = "FULL_NINE"
        with self.assertRaises(ValueError):
            operation_execution_identity(root_identity)

        outer_identity = identities[2].to_mapping()
        outer_identity["sample_index"] = 0
        outer_identity["sample_role"] = "D0"
        with self.assertRaises(ValueError):
            operation_execution_identity(outer_identity)

        fixed_sample_identity = identities[1].to_mapping()
        fixed_sample_identity["sample_index"] = 0
        fixed_sample_identity["sample_role"] = "D0"
        with self.assertRaises(ValueError):
            operation_execution_identity(fixed_sample_identity)

    def test_fixed_root_determinant_identity_requires_sample_contract(self) -> None:
        request = _fixed_sample_request()
        request_sha256 = canonical_sha256(request)
        identity = execution_identity_from_request(
            request, request_sha256=request_sha256
        )

        self.assertEqual(FIXED_ROOT_DETERMINANT_SAMPLE_OPERATION, identity.operation)
        self.assertEqual(request["fixed_omega"], identity.mapping["fixed_omega"])
        self.assertEqual(
            request["policy"]["branch_convention"],
            identity.mapping["branch_identity"],
        )
        self.assertEqual(request["readout_role"], identity.mapping["readout_role"])

        for field in ("fixed_omega", "branch_identity", "readout_role"):
            with self.subTest(field=field):
                forged = identity.to_mapping()
                forged.pop(field)
                receipt = build_operation_control_receipt(
                    origin=JULIA_WORKER_ORIGIN,
                    failure_code="INSUFFICIENT_ASYMPTOTIC_PRECISION",
                    stage="asymptotic-preflight",
                    identity=identity,
                    retryable=False,
                    retryable_basis="fixed-sample-contract/v1",
                    diagnostics={"reason": "INSUFFICIENT_ASYMPTOTIC_PRECISION"},
                )
                receipt["execution_identity"] = forged
                receipt["receipt_sha256"] = canonical_sha256({
                    key: value
                    for key, value in receipt.items()
                    if key != "receipt_sha256"
                })
                with self.assertRaises(ValueError):
                    validate_operation_control_receipt(receipt)

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

    def test_execution_identity_recursively_freezes_nested_values(self) -> None:
        request = _fixed_request()
        identity = execution_identity_from_request(
            request,
            request_sha256=canonical_sha256(request),
        )

        roles = identity.mapping["sample_roles"]
        resource = identity.mapping["execution_resource_policy_identity"]
        self.assertIsInstance(roles, tuple)
        self.assertIsInstance(resource, Mapping)
        with self.assertRaises(TypeError):
            roles[0] = "FORGED"  # type: ignore[index]
        with self.assertRaises(AttributeError):
            roles.append("FORGED")  # type: ignore[attr-defined]
        with self.assertRaises(TypeError):
            resource["sha256"] = "f" * 64  # type: ignore[index]

    def test_execution_identity_is_detached_from_source_and_exports(self) -> None:
        request = _fixed_request()
        source = execution_identity_from_request(
            request,
            request_sha256=canonical_sha256(request),
        ).to_mapping()
        identity = operation_execution_identity(source)
        digest = identity.sha256
        selected = identity.select_sample(0, "D0")

        source["sample_roles"][0] = "FORGED"  # type: ignore[index]
        source["execution_resource_policy_identity"]["sha256"] = (  # type: ignore[index]
            "f" * 64
        )
        exported = identity.to_mapping()
        exported["sample_roles"].append("FORGED")  # type: ignore[union-attr]
        exported["execution_resource_policy_identity"]["sha256"] = (  # type: ignore[index]
            "f" * 64
        )

        self.assertEqual(digest, identity.sha256)
        self.assertEqual(
            ["D0", "DOMEGA_REAL_PLUS_H"],
            identity.to_mapping()["sample_roles"],
        )
        self.assertEqual(
            "e" * 64,
            identity.mapping["execution_resource_policy_identity"]["sha256"],
        )
        self.assertEqual("D0", selected.mapping["sample_role"])
        self.assertEqual(selected, identity.select_sample(0, "D0"))
        with self.assertRaises(ValueError):
            identity.select_sample(0, "FORGED")

    def test_root_and_fixed_root_identity_cannot_cross_bind(self) -> None:
        fixed_request, fixed_identity = _identity(
            FIXED_ROOT_SURVEY_BATCH_OPERATION, SAMPLE_SCOPE, tier="BF40"
        )
        receipt = build_operation_control_receipt(
            origin=JULIA_WORKER_ORIGIN,
            failure_code="INSUFFICIENT_ASYMPTOTIC_PRECISION",
            stage="asymptotic-preflight",
            identity=fixed_identity,
            retryable=False,
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
            retryable=False,
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
            retryable=False,
            retryable_basis="precision-insufficiency/v1",
            diagnostics={},
        )
        with self.assertRaises(ValueError):
            validate_operation_control_receipt(incomplete)

        with self.assertRaises(TypeError):
            ValidatedControlReceipt(receipt, identity, _token=object())

    def test_validated_receipt_recursively_freezes_authority(self) -> None:
        request, identity = _identity(
            FIXED_ROOT_SURVEY_BATCH_OPERATION, SAMPLE_SCOPE, tier="BF40"
        )
        diagnostics = {
            "reason": "INSUFFICIENT_ASYMPTOTIC_PRECISION",
            "nested": {"attempts": [{"accepted": False}]},
        }
        receipt = build_operation_control_receipt(
            origin=JULIA_WORKER_ORIGIN,
            failure_code="INSUFFICIENT_ASYMPTOTIC_PRECISION",
            stage="asymptotic-preflight",
            identity=identity,
            retryable=False,
            retryable_basis="precision-insufficiency/v1",
            diagnostics=diagnostics,
        )
        validated = validate_operation_control_receipt(
            receipt,
            request=request,
            request_sha256=identity.request_sha256,
        )
        digest = validated.sha256

        diagnostics["nested"]["attempts"][0]["accepted"] = True
        receipt["diagnostics"]["nested"]["attempts"].append(  # type: ignore[index,union-attr]
            {"accepted": True}
        )
        request["samples"][0]["sample_role"] = "FORGED"  # type: ignore[index]
        exported = validated.to_mapping()
        exported["diagnostics"]["nested"]["attempts"][0][  # type: ignore[index]
            "accepted"
        ] = True
        exported_request = validated.canonical_request
        assert exported_request is not None
        exported_request["samples"][0]["sample_role"] = "FORGED"  # type: ignore[index]

        self.assertEqual(digest, validated.sha256)
        self.assertFalse(
            validated.mapping["diagnostics"]["nested"]["attempts"][0][  # type: ignore[index]
                "accepted"
            ]
        )
        self.assertEqual(
            "D0",
            validated.canonical_request["samples"][0]["sample_role"],  # type: ignore[index]
        )
        exported_mapping = validated.mapping
        exported_mapping["diagnostics"]["reason"] = "FORGED"  # type: ignore[index]
        exported_mapping["diagnostics"]["nested"]["attempts"].append(  # type: ignore[index,union-attr]
            {"accepted": True}
        )
        self.assertEqual(digest, validated.sha256)
        self.assertEqual(
            "INSUFFICIENT_ASYMPTOTIC_PRECISION",
            validated.mapping["diagnostics"]["reason"],  # type: ignore[index]
        )

    def test_retryability_is_derived_from_failure_code(self) -> None:
        request, identity = _identity(
            FIXED_ROOT_SURVEY_BATCH_OPERATION, SAMPLE_SCOPE, tier="BF40"
        )
        receipt = build_operation_control_receipt(
            origin=JULIA_WORKER_ORIGIN,
            failure_code="INSUFFICIENT_ASYMPTOTIC_PRECISION",
            stage="asymptotic-preflight",
            identity=identity,
            retryable=True,
            retryable_basis="caller-declared non-retryable/v1",
            diagnostics={"reason": "INSUFFICIENT_ASYMPTOTIC_PRECISION"},
        )

        with self.assertRaisesRegex(ValueError, "retryability contradicts"):
            validate_operation_control_receipt(
                receipt,
                request=request,
                request_sha256=identity.request_sha256,
            )

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

        root_codes = {
            transition.failure_code
            for transition in PROMOTED_CONTROL_TRANSITIONS.values()
            if transition.operation == ROOT_READOUT_OPERATION
        }
        self.assertTrue(NUMERICAL_CONTROL_FAILURE_CODES.issubset(root_codes))
        fixed_codes = {
            transition.failure_code
            for transition in PROMOTED_CONTROL_TRANSITIONS.values()
            if transition.operation == FIXED_ROOT_SURVEY_BATCH_OPERATION
        }
        self.assertEqual(
            (NUMERICAL_CONTROL_FAILURE_CODES
            - {
                "FINITE_DIFFERENCE_NOISE_LIMIT",
                "DETERMINANT_UNCERTAINTY_TOO_LARGE",
            }) | {
                "EXTERIOR_ENDPOINT_MAXIMUM_ORDER_INADEQUATE",
                "EXTERIOR_ENDPOINT_GEOMETRY_EXHAUSTED",
                "EXTERIOR_ENDPOINT_ARITHMETIC_INADEQUATE",
            },
            fixed_codes - {"ODE_RESOURCE_LIMIT", "WORKER_TIMEOUT"},
        )
        determinant_codes = {
            transition.failure_code
            for transition in PROMOTED_CONTROL_TRANSITIONS.values()
            if transition.operation == FIXED_ROOT_DETERMINANT_SAMPLE_OPERATION
        }
        self.assertEqual(
            fixed_codes - {
                "EXTERIOR_ENDPOINT_MAXIMUM_ORDER_INADEQUATE",
                "EXTERIOR_ENDPOINT_GEOMETRY_EXHAUSTED",
                "EXTERIOR_ENDPOINT_ARITHMETIC_INADEQUATE",
            },
            determinant_codes,
        )

    def test_promoted_horizon_worker_operations_use_response_authority(self) -> None:
        for operation in (
            ROOT_READOUT_OPERATION,
            FIXED_ROOT_DETERMINANT_SAMPLE_OPERATION,
        ):
            with self.subTest(operation=operation):
                transition = next(
                    item
                    for item in PROMOTED_CONTROL_TRANSITIONS.values()
                    if item.operation == operation
                    and item.failure_code == "INSUFFICIENT_ASYMPTOTIC_PRECISION"
                    and item.stage == "asymptotic-preflight"
                    and item.current_tier == "BF80"
                    and item.current_action_kind == "RESPONSE"
                )
                validated = _validated_for_transition(transition)
                self.assertEqual(
                    transition,
                    promoted_control_transition(
                        validated,
                        current_tier="BF80",
                        current_action_kind="RESPONSE",
                    ),
                )
                self.assertEqual("UNRESOLVED", transition.disposition)
                self.assertIsNone(transition.next_tier)

    def test_unknown_control_and_retryable_evidence_cannot_schedule(self) -> None:
        request, identity = _identity(
            FIXED_ROOT_SURVEY_BATCH_OPERATION, SAMPLE_SCOPE, tier="BF80"
        )
        with self.assertRaisesRegex(ValueError, "not registered"):
            validate_operation_control_receipt(
                build_operation_control_receipt(
                    origin=JULIA_WORKER_ORIGIN,
                    failure_code="UNKNOWN_CONTROL_OUTCOME",
                    stage="unknown-stage",
                    identity=identity,
                    retryable=True,
                    retryable_basis="worker-requested-retry/v1",
                    diagnostics={"reason": "UNKNOWN_CONTROL_OUTCOME"},
                ),
                request=request,
                request_sha256=identity.request_sha256,
            )

        known = validate_operation_control_receipt(
            build_operation_control_receipt(
                origin=JULIA_WORKER_ORIGIN,
                failure_code="INSUFFICIENT_ASYMPTOTIC_PRECISION",
                stage="asymptotic-preflight",
                identity=identity,
                retryable=False,
                retryable_basis="worker-requested-retry/v1",
                diagnostics={"reason": "INSUFFICIENT_ASYMPTOTIC_PRECISION"},
            ),
            request=request,
            request_sha256=identity.request_sha256,
        )
        transition = promoted_control_transition(
            known,
            current_tier="BF80",
            current_action_kind="RESPONSE",
        )
        self.assertEqual("UNRESOLVED", transition.disposition)
        self.assertIsNone(transition.next_tier)

    def test_arithmetic_only_bf40_failure_promotes_response_to_bf80(self) -> None:
        transition = next(
            item
            for item in PROMOTED_CONTROL_TRANSITIONS.values()
            if item.operation == FIXED_ROOT_SURVEY_BATCH_OPERATION
            and item.failure_code == "EXTERIOR_ENDPOINT_ARITHMETIC_INADEQUATE"
            and item.current_tier == "BF40"
        )
        self.assertEqual(JULIA_WORKER_ORIGIN, transition.origin)
        self.assertEqual(SAMPLE_SCOPE, transition.scope)
        self.assertEqual("PROMOTION_PENDING", transition.disposition)
        self.assertEqual("RESPONSE", transition.queue_kind)
        self.assertEqual("BF80", transition.next_tier)
        self.assertEqual("RESPONSE", transition.next_action_kind)

    def test_root_only_control_stage_is_prohibited_for_fixed_root(self) -> None:
        request, identity = _identity(
            FIXED_ROOT_SURVEY_BATCH_OPERATION, SAMPLE_SCOPE, tier="BF40"
        )
        with self.assertRaisesRegex(ValueError, "not registered"):
            validate_operation_control_receipt(
                build_operation_control_receipt(
                    origin=JULIA_WORKER_ORIGIN,
                    failure_code="FINITE_DIFFERENCE_NOISE_LIMIT",
                    stage="finite-difference",
                    identity=identity,
                    retryable=True,
                    retryable_basis="forged fixed-root derivative outcome/v1",
                    diagnostics={"reason": "FINITE_DIFFERENCE_NOISE_LIMIT"},
                ),
                request=request,
                request_sha256=identity.request_sha256,
            )

    def test_multi_stage_worker_codes_have_exact_registry_entries(self) -> None:
        expected = {
            "ALGEBRAIC_REPRESENTATION_SINGULAR": {
                "request-policy",
                "finite-difference",
                "determinant-chart",
                "homogeneous-propagation",
            },
            "EXTERIOR_DETERMINANT_CERTIFICATE_UNAVAILABLE": {
                "asymptotic-preflight",
                "determinant-chart",
            },
        }
        operation_stages = (
            (ROOT_READOUT_OPERATION, "ROOT", REQUEST_SCOPE, expected),
            (ROOT_READOUT_OPERATION, "RESPONSE", REQUEST_SCOPE, expected),
            (
                FIXED_ROOT_SURVEY_BATCH_OPERATION,
                "RESPONSE",
                SAMPLE_SCOPE,
                {
                    **expected,
                    "ALGEBRAIC_REPRESENTATION_SINGULAR": {
                        "determinant-chart",
                        "homogeneous-propagation",
                    },
                },
            ),
            (
                FIXED_ROOT_DETERMINANT_SAMPLE_OPERATION,
                "RESPONSE",
                REQUEST_SCOPE,
                {
                    **expected,
                    "ALGEBRAIC_REPRESENTATION_SINGULAR": {
                        "determinant-chart",
                        "homogeneous-propagation",
                    },
                },
            ),
        )
        for operation, action, scope, expected_stages in operation_stages:
            for code, stages in expected_stages.items():
                with self.subTest(operation=operation, failure_code=code):
                    observed = {
                        transition.stage
                        for transition in PROMOTED_CONTROL_TRANSITIONS.values()
                        if transition.operation == operation
                        and transition.current_action_kind == action
                        and transition.scope == scope
                        and transition.failure_code == code
                    }
                    self.assertEqual(stages, observed)

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
