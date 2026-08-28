from __future__ import annotations

from dataclasses import fields, replace
from decimal import Decimal, localcontext
import hashlib
import io
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from windows_solver.contracts import canonical_json_bytes
from windows_solver.julia_response_backend import (
    JULIA_PROGRESS_PREFIX,
    JuliaPrecisionRootBackend,
    JuliaResponseAdapter,
    JuliaResponseBackendError,
    _forward_julia_progress_line,
    _control_receipt_diagnostics_validator,
    _execution_resource_policy,
    _mode_specific_branch_enclosure_radius,
    _run_streamed_julia,
    _valid_numerical_control_diagnostics,
)
from windows_solver.operation_control import (
    JULIA_WORKER_ORIGIN,
    build_operation_control_receipt,
    operation_execution_identity,
)
from windows_solver.progress import (
    PROGRESS_SCHEMA,
    ProgressContext,
    ProgressEventKind,
    activate_progress,
)
from windows_solver.root_readout_cache import (
    ROOT_READOUT_STORE_DIRECTORY_NAME,
    RootReadoutStore,
    runtime_identity_sha256,
)
from windows_solver.response_batches import (
    PrecisionCapabilities,
    build_campaign_selection,
    build_campaign_plan,
    run_campaign_selection,
    scientific_computation_identity_sha256,
)
from windows_solver.response_engine import (
    DecimalComplex,
    FixedRootDiagnosticEvidence,
    FixedRootDeterminantSample,
    LadderLevel,
    NumericalPolicy,
    RootAuthenticationEvidence,
    RootReadout,
    VettedNativeDeterminantKernel,
    WORKER_RESPONSE_WIRE_SCHEMA,
    _diagnostic_response_channel,
)
from windows_solver.progress_output import CampaignProgressReporter
from windows_solver.promoted_control_calibration import (
    EXTERIOR_DETERMINANT_ABSOLUTE_ERROR_CERTIFICATE,
    load_default_calibration_receipt,
)
from tests.fixtures import (
    control_failure_stage,
    synthetic_ode_error_budget,
    valid_control_failure_diagnostics,
    valid_julia_root_response,
    valid_legacy_julia_root_response,
    valid_root_authentication,
)


def _deep_job():
    plan = build_campaign_plan(
        policy=NumericalPolicy(),
        backend_identity=VettedNativeDeterminantKernel.identity,
        precision_capabilities=PrecisionCapabilities((64, 80, 120)),
    )
    return next(leaf.job for leaf in plan.leaves if leaf.role == "deep")


def _job_for_mechanism(mechanism_id: str):
    plan = build_campaign_plan(
        policy=NumericalPolicy(),
        backend_identity=VettedNativeDeterminantKernel.identity,
        precision_capabilities=PrecisionCapabilities((64, 80, 120)),
    )
    return next(
        leaf.job
        for leaf in plan.leaves
        if leaf.job.mechanism_id == mechanism_id
    )


def _worker_control_receipt(
    request: dict[str, object],
    failure_code: str,
    *,
    request_sha256: str | None = None,
) -> dict[str, object]:
    identity_mapping = dict(request["execution_identity"])
    if request_sha256 is not None:
        identity_mapping["request_sha256"] = request_sha256
    identity = operation_execution_identity(identity_mapping)
    return build_operation_control_receipt(
        origin=JULIA_WORKER_ORIGIN,
        failure_code=failure_code,
        stage=control_failure_stage(failure_code),
        identity=identity,
        retryable=failure_code in {
            "INSUFFICIENT_ASYMPTOTIC_PRECISION",
            "HORIZON_ARITHMETIC_INADEQUATE",
        },
        retryable_basis="worker-control test fixture/v1",
        diagnostics=valid_control_failure_diagnostics(
            failure_code,
            precision_bits=int(request["working_precision_bits"]),
        ),
    )
def _production_promoted_backend(
    mechanism_id: str,
    adapter,
    *,
    diagnostic_model_identity=None,
):
    job = _job_for_mechanism(mechanism_id)
    receipt = load_default_calibration_receipt()
    family = (
        "horizon-scattering/v1"
        if mechanism_id == "horizon-admittance"
        else "exterior-wronskian/v1"
    )
    return job, JuliaPrecisionRootBackend(
        VettedNativeDeterminantKernel.identity,
        adapter,
        80,
        empirical_control_profile=receipt.budget_for(family, 80),
        calibration_receipt=receipt,
        diagnostic_model_identity=diagnostic_model_identity,
    )


def _reseal_worker_response_receipt(mapping: dict[str, object]) -> None:
    """Recompute both receipt digests after a persistence-forgery mutation."""

    receipt = mapping["worker_response_receipt"]
    request_binding = receipt["request_binding"]
    receipt["request_sha256"] = hashlib.sha256(
        canonical_json_bytes(request_binding)
    ).hexdigest()
    receipt["receipt_sha256"] = hashlib.sha256(
        canonical_json_bytes({
            key: value
            for key, value in receipt.items()
            if key != "receipt_sha256"
        })
    ).hexdigest()


class FakeAdapter:
    runtime_provenance = {
        "julia_version": "1.10.11",
        "julia_executable_sha256": "a" * 64,
        "julia_manifest_sha256": "b" * 64,
        "worker_sha256": "c" * 64,
        "runtime_policy_sha256": "d" * 64,
        "scientific_sources": [],
    }

    def __init__(self):
        self.requests = []

    @staticmethod
    def ode_error_budget_for_digits(digits):
        return synthetic_ode_error_budget(digits)

    @staticmethod
    def shifted(value, delta):
        with localcontext() as context:
            context.prec = 180
            return str(Decimal(value) + Decimal(delta))

    def evaluate(self, request):
        self.requests.append(request)
        return valid_julia_root_response(request)

    def evaluate_for_validation(self, request):
        return SimpleNamespace(
            response=self.evaluate(request),
            request_binding=dict(request),
            request_sha256=hashlib.sha256(
                canonical_json_bytes(request)
            ).hexdigest(),
            runtime_identity_sha256=hashlib.sha256(
                canonical_json_bytes(
                    JuliaPrecisionRootBackend(
                        VettedNativeDeterminantKernel.identity,
                        self,
                        request["precision_digits"],
                        refinement=request["refinement_level"],
                    ).scientific_runtime_for(_deep_job())
                )
            ).hexdigest(),
            reused=False,
            cached_worker_response_receipt=None,
        )

    def retain_validated_readout(self, evaluation, receipt):
        return None

    def invalidate_validated_readout(self, evaluation):
        return None


class LegacyFakeAdapter(FakeAdapter):
    """Exercise the preserved schema-v6 parser without claiming it is current."""

    def evaluate(self, request):
        self.requests.append(request)
        policy = dict(request["policy"])
        policy.pop("promoted_root_readout_policy", None)
        request["policy"] = policy
        response = valid_legacy_julia_root_response(request)
        response["request_sha256"] = hashlib.sha256(
            canonical_json_bytes(request)
        ).hexdigest()
        return response


def _set_distinct_derivative_binding(response, wire_derivative_abs):
    authentication = dict(response["root_authentication"])
    derivative_authentication = dict(
        authentication["derivative_authentication"]
    )
    derivative_authentication.update({
        "derivative_re": "10",
        "derivative_im": "0",
        "propagated_error_abs": "1",
        "step_disagreement_abs": "1",
        "lower_bound_abs": "8",
    })
    authentication["derivative_authentication"] = derivative_authentication
    derivative_evidence = dict(authentication["derivative_evidence"])
    derivative_evidence.update({
        "real_base": {"real": "9", "imaginary": "0"},
        "real_half": {"real": "10", "imaginary": "0"},
    })
    authentication["derivative_evidence"] = derivative_evidence
    with localcontext() as context:
        context.prec = 180
        authentication["correction_upper_bound"] = str(
            Decimal(authentication["residual_upper_bound_abs"]) / Decimal("8")
        )
    response["root_authentication"] = authentication
    response["root_derivative_abs"] = wire_derivative_abs
    return response


class JuliaResponseBackendTests(unittest.TestCase):
    def test_operation_resource_receipts_require_code_specific_evidence(self):
        ode = {
            "failure_code": "ODE_RESOURCE_LIMIT",
            "stage": "homogeneous-propagation",
            "diagnostics": {
                "limit_kind": "ode_solver_iterations",
                "limiting_resource": "homogeneous_ode_maxiters",
                "elapsed_leg_seconds": 12.5,
                "ode_leg": "Xup_outer_to_match",
                "ode_snapshot": {
                    "ode_leg": "Xup_outer_to_match",
                    "ode_retcode": "MaxIters",
                    "ode_endpoint_reached": False,
                    "elapsed_seconds": 12.5,
                },
            },
        }
        self.assertTrue(
            _control_receipt_diagnostics_validator(ode, request_binding={})
        )
        forged_ode = json.loads(canonical_json_bytes(ode))
        forged_ode["diagnostics"]["limiting_resource"] = "rhs_evaluations"
        self.assertFalse(
            _control_receipt_diagnostics_validator(
                forged_ode, request_binding={}
            )
        )

        root = {
            "failure_code": "ROOT_READOUT_RESOURCE_INFEASIBLE",
            "stage": "request-policy",
            "diagnostics": {
                "limiting_resource": "cooperative_request_deadline",
                "measured_determinant_seconds": 800.0,
                "minimum_remaining_determinant_count": 8,
                "remaining_wall_time_seconds": 5000.0,
                "estimated_mandatory_seconds": 6400.0,
                "estimator": "first-determinant-linear-lower-bound/v1",
            },
        }
        self.assertTrue(
            _control_receipt_diagnostics_validator(root, request_binding={})
        )
        forged_root = json.loads(canonical_json_bytes(root))
        forged_root["diagnostics"]["estimated_mandatory_seconds"] = 6000.0
        self.assertFalse(
            _control_receipt_diagnostics_validator(
                forged_root, request_binding={}
            )
        )

    def test_supervisor_timeout_receipt_is_bound_to_request_resources(self):
        resource = _execution_resource_policy()
        request = {
            "precision_digits": 40,
            "execution_resource": resource,
        }
        timeout = {
            "origin": "PYTHON_SUPERVISOR",
            "failure_code": "WORKER_TIMEOUT",
            "stage": "worker-supervision",
            "diagnostics": {
                "elapsed_request_seconds": resource[
                    "worker_request_wall_clock_seconds"
                ],
                "limiting_resource": "worker_request_wall_clock",
                "precision_digits": 40,
                "execution_resource_policy": resource,
                "last_validated_progress": {
                    "schema": PROGRESS_SCHEMA,
                    "kind": "request_started",
                    "context": {},
                    "payload": {},
                },
            },
        }
        self.assertTrue(
            _control_receipt_diagnostics_validator(
                timeout, request_binding=request
            )
        )
        forged = json.loads(canonical_json_bytes(timeout))
        forged["diagnostics"]["elapsed_request_seconds"] -= 1
        self.assertFalse(
            _control_receipt_diagnostics_validator(
                forged, request_binding=request
            )
        )

    def test_empirical_exterior_root_requires_three_term_certificate(self):
        job = _job_for_mechanism("exterior-light-ring")
        receipt = load_default_calibration_receipt()
        readout = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            FakeAdapter(),
            80,
            empirical_control_profile=receipt.budget_for(
                "exterior-wronskian/v1", 80
            ),
            calibration_receipt=receipt,
            diagnostic_model_identity=(
                "exterior-determinant-absolute-error-certificate/empirical-v1"
            ),
        ).read_root(job, 0.0j)

        certificate = readout.primary_acceptance
        self.assertEqual(
            certificate.error_model_id,
            "exterior-determinant-absolute-error-certificate/empirical-v1",
        )
        self.assertEqual(
            certificate.determinant_error_abs,
            Decimal("48"),
        )
        self.assertEqual(
            certificate.derivative_authentication.determinant_error_status,
            "available/v1",
        )
        self.assertEqual(
            readout.worker_response_receipt["request_binding"]["policy"][
                "determinant_error_required_term_classes"
            ],
            [
                "delta_same_point",
                "delta_cross_precision",
                "delta_endpoint_series",
            ],
        )

    def test_horizon_endpoint_receipt_binds_attempted_rung_separately_from_best_prefix(self):
        job = _job_for_mechanism("horizon-admittance")
        backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity, FakeAdapter(), 80
        )
        mapping = backend.read_root(job, 0.0j).to_mapping()
        evidence = mapping["worker_response_receipt"][
            "horizon_endpoint_search_evidence"
        ][0]
        selected = evidence["selected_pair"][0]
        self.assertEqual(selected["attempted_endpoint_order"], 56)
        selected.update({
            "endpoint_order": 44,
            "ingoing_best_prefix_order": 40,
            "outgoing_best_prefix_order": 44,
        })

        repeated = [
            candidate
            for candidate in evidence["rejected_candidates"]
            if candidate["rho"] == "-50"
            and candidate["attempted_endpoint_order"] in (28, 56)
        ]
        self.assertEqual(len(repeated), 2)
        for candidate in repeated:
            candidate.update({
                "endpoint_order": 20,
                "ingoing_best_prefix_order": 16,
                "outgoing_best_prefix_order": 20,
            })

        receipt = mapping["worker_response_receipt"]
        receipt["receipt_sha256"] = hashlib.sha256(
            canonical_json_bytes({
                key: value for key, value in receipt.items()
                if key != "receipt_sha256"
            })
        ).hexdigest()
        RootReadout.from_mapping(mapping)

    def test_horizon_failure_outcome_cannot_be_resealed_from_arithmetic_to_order(self):
        job = _job_for_mechanism("horizon-admittance")
        request = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity, FakeAdapter(), 80
        )._request(job, 0.0j)
        failure = {
            "failure_code": "HORIZON_ARITHMETIC_INADEQUATE",
            "failure_class": "CONTROL",
            "stage": control_failure_stage("HORIZON_ARITHMETIC_INADEQUATE"),
            "retryable": True,
            "diagnostics": valid_control_failure_diagnostics(
                "HORIZON_ARITHMETIC_INADEQUATE",
                precision_bits=request["working_precision_bits"],
            ),
        }
        self.assertTrue(_valid_numerical_control_diagnostics(
            failure, request_binding=request
        ))

        forged = json.loads(canonical_json_bytes(failure))
        forged.update({
            "failure_code": "HORIZON_MAXIMUM_ORDER_INADEQUATE",
            "retryable": False,
        })
        diagnostics = forged["diagnostics"]
        diagnostics.update({
            "recovery_outcome": "maximum-series-order-inadequate/v1",
            "next_precision_tier_allowed": False,
        })
        diagnostics["recovery_evidence"]["outcome"] = (
            "maximum-series-order-inadequate/v1"
        )
        for candidate in diagnostics["recovery_evidence"][
            "rejected_candidates"
        ]:
            candidate.update({
                "limitation": "insufficient-series-order/v1",
                "precision_limited": False,
            })
        self.assertFalse(_valid_numerical_control_diagnostics(
            forged, request_binding=request
        ))

    def test_factored_coordinate_stall_survives_shared_control_binding(self):
        failure = {
            "failure_code": "COORDINATE_INVERSION_STALLED",
            "failure_class": "CONTROL",
            "stage": "coordinate-inversion",
            "retryable": False,
            "diagnostics": {
                "reason": "COORDINATE_INVERSION_STALLED",
                "precision_bits": 165,
                "factored_homogeneous_rhs_evaluations": 0,
                "avoided_ode_scope": "factored-homogeneous-gsn/v1",
            },
        }
        self.assertTrue(_valid_numerical_control_diagnostics(failure))

        forged = json.loads(canonical_json_bytes(failure))
        forged["stage"] = "homogeneous-propagation"
        self.assertFalse(_valid_numerical_control_diagnostics(forged))

    def test_horizon_failure_outcome_cannot_be_resealed_from_order_to_arithmetic(self):
        job = _job_for_mechanism("horizon-admittance")
        request = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity, FakeAdapter(), 80
        )._request(job, 0.0j)
        failure = {
            "failure_code": "HORIZON_MAXIMUM_ORDER_INADEQUATE",
            "failure_class": "CONTROL",
            "stage": control_failure_stage(
                "HORIZON_MAXIMUM_ORDER_INADEQUATE"
            ),
            "retryable": False,
            "diagnostics": valid_control_failure_diagnostics(
                "HORIZON_MAXIMUM_ORDER_INADEQUATE",
                precision_bits=request["working_precision_bits"],
            ),
        }
        self.assertTrue(_valid_numerical_control_diagnostics(
            failure, request_binding=request
        ))

        forged = json.loads(canonical_json_bytes(failure))
        forged.update({
            "failure_code": "HORIZON_ARITHMETIC_INADEQUATE",
            "retryable": True,
        })
        diagnostics = forged["diagnostics"]
        diagnostics.update({
            "recovery_outcome": "arithmetic-precision-inadequate/v1",
            "next_precision_tier_allowed": True,
        })
        diagnostics["recovery_evidence"]["outcome"] = (
            "arithmetic-precision-inadequate/v1"
        )
        for candidate in diagnostics["recovery_evidence"][
            "rejected_candidates"
        ]:
            candidate.update({
                "limitation": "insufficient-arithmetic-precision/v1",
                "precision_limited": True,
            })
        self.assertFalse(_valid_numerical_control_diagnostics(
            forged, request_binding=request
        ))

    def test_horizon_endpoint_receipt_rejects_resealed_policy_geometry_and_order_forgery(self):
        job = _job_for_mechanism("horizon-admittance")
        backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity, FakeAdapter(), 80
        )
        original = backend.read_root(job, 0.0j).to_mapping()

        for label, mutate in (
            ("policy", lambda evidence: evidence.__setitem__("policy_identity", "forged/v1")),
            ("rho", lambda evidence: evidence["selected_pair"][0].__setitem__("rho", "-399")),
            ("endpoint-order", lambda evidence: evidence["selected_pair"][0].__setitem__("endpoint_order", 99)),
            ("attempted-order", lambda evidence: evidence["selected_pair"][0].__setitem__("attempted_endpoint_order", 112)),
            ("prefix-order", lambda evidence: evidence["selected_pair"][0].__setitem__("ingoing_best_prefix_order", 27)),
            ("limitation", lambda evidence: evidence["selected_pair"][0].__setitem__("limitation", "insufficient-series-order/v1")),
            ("precision-limited", lambda evidence: evidence["selected_pair"][0].__setitem__("precision_limited", True)),
            ("pair-order", lambda evidence: evidence["selected_pair"].reverse()),
            ("omitted-candidate", lambda evidence: evidence["rejected_candidates"].pop()),
            (
                "omitted-intermediate-selected-rho-trial",
                lambda evidence: evidence["rejected_candidates"].remove(
                    next(
                        trial
                        for trial in evidence["rejected_candidates"]
                        if trial["rho"] == evidence["selected_pair"][0]["rho"]
                        and trial["attempted_endpoint_order"] == 28
                    )
                ),
            ),
        ):
            with self.subTest(label=label):
                forged = json.loads(canonical_json_bytes(original))
                receipt = forged["worker_response_receipt"]
                mutate(receipt["horizon_endpoint_search_evidence"][0])
                receipt["receipt_sha256"] = hashlib.sha256(
                    canonical_json_bytes({
                        key: value for key, value in receipt.items()
                        if key != "receipt_sha256"
                    })
                ).hexdigest()
                with self.assertRaisesRegex(ValueError, "horizon endpoint"):
                    RootReadout.from_mapping(forged)

    def test_horizon_failure_diagnostics_bind_exact_request_policy_geometry_and_orders(self):
        job = _job_for_mechanism("horizon-admittance")
        backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            FakeAdapter(),
            80,
        )
        request = backend._request(job, 0.0j)
        for code in (
            "HORIZON_ARITHMETIC_INADEQUATE",
            "HORIZON_COORDINATE_INVERSION_FAILED",
        ):
            failure = {
                "failure_code": code,
                "failure_class": "CONTROL",
                "stage": control_failure_stage(code),
                "retryable": code == "HORIZON_ARITHMETIC_INADEQUATE",
                "diagnostics": valid_control_failure_diagnostics(
                    code, precision_bits=request["working_precision_bits"]
                ),
            }
            self.assertTrue(
                _valid_numerical_control_diagnostics(
                    failure, request_binding=request
                ),
                f"canonical {code} fixture must reach the typed validator",
            )
            mutations = [
                ("policy", lambda evidence: evidence.__setitem__("policy_identity", "forged/v1")),
                ("endpoint-orders", lambda evidence: evidence.__setitem__("endpoint_orders", [28, 99, 112])),
            ]
            if code != "HORIZON_COORDINATE_INVERSION_FAILED":
                mutations.append((
                    "omitted-intermediate-order",
                    lambda evidence: evidence["rejected_candidates"].remove(
                        next(
                            trial
                            for trial in evidence["rejected_candidates"]
                            if trial["rho"] == "-10"
                            and trial["attempted_endpoint_order"] == 56
                        )
                    ),
                ))
            for label, mutate in mutations:
                with self.subTest(code=code, label=label):
                    forged = json.loads(canonical_json_bytes(failure))
                    mutate(forged["diagnostics"]["recovery_evidence"])
                    self.assertFalse(
                        _valid_numerical_control_diagnostics(
                            forged, request_binding=request
                        )
                    )

    def test_horizon_failure_schedule_rejects_invalid_or_verified_rho_retry(self):
        job = _job_for_mechanism("horizon-admittance")
        request = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            FakeAdapter(),
            80,
        )._request(job, 0.0j)
        for code, retry in (
            (
                "HORIZON_GEOMETRY_EXHAUSTED",
                {
                    "rho": "-10",
                    "attempted_endpoint_order": 28,
                    "endpoint_order": 24,
                    "ingoing_best_prefix_order": 20,
                    "outgoing_best_prefix_order": 24,
                    "ingoing_adequate": False,
                    "outgoing_adequate": False,
                    "limitation": "insufficient-series-order/v1",
                    "precision_limited": False,
                    "limitation_conditioning": {
                        "binding_predicted_reliable_digits": "20",
                        "maximum_last_term_ratio": "0.5",
                        "maximum_recurrence_digits_lost": "1",
                        "maximum_series_evaluation_digits_lost": "1",
                        "maximum_truncation_digits_lost": "3",
                    },
                },
            ),
            (
                "HORIZON_ONLY_ONE_ENDPOINT",
                {
                    "rho": "-10",
                    "attempted_endpoint_order": 56,
                    "endpoint_order": 48,
                    "ingoing_best_prefix_order": 44,
                    "outgoing_best_prefix_order": 48,
                    "ingoing_adequate": False,
                    "outgoing_adequate": False,
                    "limitation": "insufficient-series-order/v1",
                    "precision_limited": False,
                    "limitation_conditioning": {
                        "binding_predicted_reliable_digits": "20",
                        "maximum_last_term_ratio": "0.5",
                        "maximum_recurrence_digits_lost": "1",
                        "maximum_series_evaluation_digits_lost": "1",
                        "maximum_truncation_digits_lost": "3",
                    },
                },
            ),
        ):
            failure = {
                "failure_code": code,
                "failure_class": "CONTROL",
                "stage": control_failure_stage(code),
                "retryable": False,
                "diagnostics": valid_control_failure_diagnostics(
                    code, precision_bits=request["working_precision_bits"]
                ),
            }
            self.assertTrue(_valid_numerical_control_diagnostics(
                failure, request_binding=request
            ))
            forged = json.loads(canonical_json_bytes(failure))
            forged["diagnostics"]["recovery_evidence"][
                "rejected_candidates"
            ].append(retry)
            self.assertFalse(_valid_numerical_control_diagnostics(
                forged, request_binding=request
            ))

    def test_successful_horizon_endpoint_evidence_is_sealed_in_receipt(self):
        job = _job_for_mechanism("horizon-admittance")
        backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity, FakeAdapter(), 80
        )

        readout = backend.read_root(job, 0.0j)

        evidence = readout.worker_response_receipt[
            "horizon_endpoint_search_evidence"
        ]
        self.assertTrue(evidence)
        self.assertEqual(evidence[0]["outcome"], "adequate/v1")
        self.assertEqual(len(evidence[0]["selected_pair"]), 2)

        class MissingEndpointAdapter(FakeAdapter):
            def evaluate(self, request):
                response = super().evaluate(request)
                response["horizon_endpoint_search_evidence"] = []
                return response

        with self.assertRaisesRegex(
            JuliaResponseBackendError, "horizon endpoint evidence"
        ):
            JuliaPrecisionRootBackend(
                VettedNativeDeterminantKernel.identity,
                MissingEndpointAdapter(),
                80,
            ).read_root(job, 0.0j)

    def test_schema8_horizon_derivative_error_availability_is_not_zero_claim(self):
        job = _job_for_mechanism("horizon-admittance")
        backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity, FakeAdapter(), 80
        )
        request = backend._request(job, 0.0j)
        response = valid_julia_root_response(request)
        derivative = response["primary_acceptance"]["derivative_authentication"]
        self.assertEqual(derivative["determinant_error_status"], "available/v1")
        self.assertGreater(Decimal(derivative["propagated_error_abs"]), 0)
        readout = backend._read_root_response_v7(
            job,
            request,
            SimpleNamespace(
                response=response,
                request_binding=request,
                request_sha256=response["request_sha256"],
                runtime_identity_sha256="f" * 64,
                reused=False,
                cached_worker_response_receipt=None,
            ),
        )
        self.assertEqual(
            readout.primary_acceptance.derivative_authentication.determinant_error_status,
            "available/v1",
        )

        response["primary_acceptance"]["derivative_authentication"][
            "propagated_error_abs"
        ] = "0"
        with self.assertRaisesRegex(
            JuliaResponseBackendError,
            "PRIMARY acceptance evidence is invalid",
        ):
            backend._read_root_response_v7(
                job,
                request,
                SimpleNamespace(
                    response=response,
                    request_binding=request,
                    request_sha256=response["request_sha256"],
                    runtime_identity_sha256="f" * 64,
                    reused=False,
                    cached_worker_response_receipt=None,
                ),
            )

    def test_fixed_root_determinant_sample_boundary_preserves_evidence(self):
        class FixedSampleAdapter(FakeAdapter):
            def evaluate_for_validation(self, request):
                self.requests.append(request)
                request_sha256 = hashlib.sha256(
                    canonical_json_bytes(request)
                ).hexdigest()
                response = {
                    "schema_version": 1,
                    "status": "ok",
                    "operation": "fixed-root-determinant-sample",
                    "request_sha256": request_sha256,
                    "omega_re": request["fixed_omega"]["real"],
                    "omega_im": request["fixed_omega"]["imaginary"],
                    "amplitude_re": request["amplitude"]["real"],
                    "amplitude_im": request["amplitude"]["imaginary"],
                    "determinant_re": (
                        "0.0060000000010000000000000000000000000001"
                    ),
                    "determinant_im": "0.009",
                    "determinant_error_abs": "4e-12",
                    "determinant_error_status": "available/v1",
                    "determinant_error_model_id": request["policy"][
                        "determinant_error_model"
                    ],
                    "determinant_family": "exterior-wronskian/v1",
                    "determinant_normalisation": "unit-asymptotic-branch-wronskian/v1",
                    "branch_identity": "gsn-complex-rho/v1",
                    "branch_authenticated": True,
                    "semantic_precision_tier": "bigfloat-80",
                    "working_precision_bits": 298,
                    "readout_role": request["readout_role"],
                }
                return SimpleNamespace(
                    response=response,
                    request_binding=dict(request),
                    request_sha256=request_sha256,
                    runtime_identity_sha256="f" * 64,
                    reused=False,
                    cached_worker_response_receipt=None,
                )

        job = _job_for_mechanism("exterior-light-ring")
        adapter = FixedSampleAdapter()
        backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity, adapter, 80
        )
        sample = backend.sample_fixed_root_determinant(
            job,
            job.root.omega,
            0.003 + 0.0j,
            readout_role="coordinate-real-plus-h",
        )
        mapping = sample.to_mapping()

        self.assertEqual(adapter.requests[0]["operation"], "fixed-root-determinant-sample")
        self.assertEqual(mapping["omega"], {"imaginary": job.root.omega.imag, "real": job.root.omega.real})
        self.assertEqual(mapping["determinant_family"], "exterior-wronskian/v1")
        self.assertEqual(mapping["precision_tier"], "bigfloat-80")
        self.assertEqual(mapping["working_precision_bits"], 298)
        self.assertEqual(mapping["readout_role"], "coordinate-real-plus-h")
        self.assertEqual(
            str(sample.exact_determinant.real),
            "0.0060000000010000000000000000000000000001",
        )
        self.assertRegex(mapping["request_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(mapping["worker_response_receipt_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            mapping["worker_response_receipt"]["request_binding"],
            adapter.requests[0],
        )
        self.assertEqual(
            mapping["worker_response_receipt"]["response_binding"][
                "determinant_re"
            ],
            "0.0060000000010000000000000000000000000001",
        )

        for receipt_field, replacement in (
            ("request_binding", {**adapter.requests[0], "readout_role": "tampered"}),
            ("response_binding", {
                **mapping["worker_response_receipt"]["response_binding"],
                "determinant_re": "9",
            }),
        ):
            with self.subTest(receipt_field=receipt_field):
                tampered = json.loads(canonical_json_bytes(mapping))
                tampered["worker_response_receipt"][receipt_field] = replacement
                tampered["worker_response_receipt_sha256"] = hashlib.sha256(
                    canonical_json_bytes(tampered["worker_response_receipt"])
                ).hexdigest()
                with self.assertRaisesRegex(ValueError, "receipt .* mismatch"):
                    FixedRootDeterminantSample.from_mapping(tampered)

    @staticmethod
    def _cache_adapter(root, runner):
        depot = root / "depot"
        depot.mkdir()
        for name in ("julia.exe", "Project.toml", "Manifest.toml", "worker.jl"):
            (root / name).write_text(name, encoding="ascii")
        store = RootReadoutStore(root / ROOT_READOUT_STORE_DIRECTORY_NAME)
        adapter = JuliaResponseAdapter(
            root / "julia.exe",
            root,
            depot,
            root / "worker.jl",
            dict(FakeAdapter.runtime_provenance),
            runner,
            readout_cache=store,
        )
        return adapter, store

    def test_invalid_fresh_success_is_rejected_before_cache_publication(self):
        """Catches adapter-only checks retaining a mechanism-swapped success."""

        def runner(command, **kwargs):
            request = json.loads(Path(command[-2]).read_text(encoding="utf-8"))
            response = valid_julia_root_response(request)
            response["numerical_conditioning"]["determinant_family"] = (
                "cinc-over-cref-minus-R/v1"
            )
            response["numerical_conditioning"][
                "scattering_diagnostics_applicable"
            ] = True
            response["request_sha256"] = request["request_sha256"]
            Path(command[-1]).write_bytes(canonical_json_bytes(response))
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as temporary:
            adapter, store = self._cache_adapter(Path(temporary), runner)
            backend = JuliaPrecisionRootBackend(
                VettedNativeDeterminantKernel.identity, adapter, 80,
                ode_error_budget=synthetic_ode_error_budget(80),
            )
            with self.assertRaises(JuliaResponseBackendError):
                backend.read_root(_deep_job(), 0.0j)
            self.assertEqual(store.stored_count, 0)

    def test_invalid_cached_success_is_evicted_then_valid_retry_is_reused(self):
        """Catches one poisoned entry permanently blocking exact recomputation."""

        calls = []

        def runner(command, **kwargs):
            calls.append(tuple(command))
            request = json.loads(Path(command[-2]).read_text(encoding="utf-8"))
            response = valid_julia_root_response(request)
            response["request_sha256"] = request["request_sha256"]
            Path(command[-1]).write_bytes(canonical_json_bytes(response))
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as temporary:
            adapter, store = self._cache_adapter(Path(temporary), runner)
            job = _deep_job()
            backend = JuliaPrecisionRootBackend(
                VettedNativeDeterminantKernel.identity, adapter, 80,
                ode_error_budget=synthetic_ode_error_budget(80),
            )
            request = backend._request(job, 0.0j)
            request_sha256 = hashlib.sha256(
                canonical_json_bytes(request)
            ).hexdigest()
            poisoned = valid_julia_root_response(request)
            poisoned["schema_version"] = 2
            poisoned["request_sha256"] = request_sha256
            store.publish(
                request_sha256=request_sha256,
                runtime_identity=runtime_identity_sha256(
                    adapter.runtime_provenance
                ),
                response=poisoned,
            )

            with self.assertRaisesRegex(
                JuliaResponseBackendError,
                "response policy/wire schema is inconsistent",
            ):
                backend.read_root(job, 0.0j)
            self.assertEqual(store.stored_count, 0)
            self.assertEqual(calls, [])

            first = backend.read_root(job, 0.0j)
            second = backend.read_root(job, 0.0j)
            self.assertEqual(len(calls), 1)
            self.assertEqual(second.to_mapping(), first.to_mapping())
            self.assertEqual(store.stored_count, 1)

    def test_worker_response_receipt_preserves_exact_determinant_text(self):
        """Catches reducing exact worker decimal evidence to one binary64 bin."""

        readout = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity, FakeAdapter(), 80
        ).read_root(_deep_job(), 0.0j)

        receipt = readout.worker_response_receipt
        self.assertEqual(
            receipt["root_residual_abs_text"],
            str(readout.normalised_determinant_abs),
        )
        self.assertEqual(len(receipt["receipt_sha256"]), 64)

    def test_cached_receipt_rejects_sub_binary64_text_tampering(self):
        """Catches exact evidence changes hidden inside one binary64 value."""

        calls = []

        def runner(command, **kwargs):
            calls.append(tuple(command))
            request = json.loads(Path(command[-2]).read_text(encoding="utf-8"))
            response = valid_julia_root_response(request)
            response["request_sha256"] = request["request_sha256"]
            Path(command[-1]).write_bytes(canonical_json_bytes(response))
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as temporary:
            adapter, store = self._cache_adapter(Path(temporary), runner)
            backend = JuliaPrecisionRootBackend(
                VettedNativeDeterminantKernel.identity, adapter, 80,
                ode_error_budget=synthetic_ode_error_budget(80),
            )
            backend.read_root(_deep_job(), 0.0j)
            cache_path = next(store.root.glob("*.json"))
            entry = json.loads(cache_path.read_text(encoding="utf-8"))
            receipt = entry["worker_response_receipt"]
            receipt["root_residual_abs_text"] = (
                "1.0000000000000000000000000000000000000001E-60"
            )
            material = {
                key: value
                for key, value in receipt.items()
                if key != "receipt_sha256"
            }
            receipt["receipt_sha256"] = hashlib.sha256(
                canonical_json_bytes(material)
            ).hexdigest()
            cache_path.write_bytes(canonical_json_bytes(entry))

            with self.assertRaisesRegex(
                JuliaResponseBackendError,
                "cached worker response receipt is invalid",
            ):
                backend.read_root(_deep_job(), 0.0j)
            self.assertEqual(store.stored_count, 0)
            backend.read_root(_deep_job(), 0.0j)
            self.assertEqual(len(calls), 2)

    def test_success_wire_schema_is_eleven_and_worker_errors_remain_schema_one(self):
        """Catches changing the successful wire without preserving error parsing.

        The success wire and the error envelope are versioned independently.
        Schema 11 binds the explicit diagnostic model and raw-role contract;
        the error envelope stays independently
        versioned at 1.
        """

        request = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            FakeAdapter(),
            80,
        )._request(_deep_job(), 0.0j)
        self.assertEqual(
            valid_julia_root_response(request)["schema_version"],
            WORKER_RESPONSE_WIRE_SCHEMA,
        )
        self.assertEqual(WORKER_RESPONSE_WIRE_SCHEMA, 11)
        root = Path(__file__).resolve().parents[1]
        worker = (
            root / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")
        result_fields = worker[
            worker.index("function result_fields(") :
            worker.index("function evaluate_request(")
        ]
        self.assertEqual(result_fields.count('"schema_version" => 11'), 2)
        self.assertNotIn('"schema_version" => 6', result_fields)
        error_path = worker[
            worker.rindex("catch failure") : worker.index(
                "if abspath(PROGRAM_FILE)"
            )
        ]
        self.assertGreaterEqual(error_path.count('"schema_version" => 1'), 2)

    def test_fixed_root_wire_distinguishes_logical_and_raw_determinants(self):
        """Catches collapsing one authenticated result into its raw samples."""

        class CountedDiagnosticAdapter(FakeAdapter):
            def evaluate(self, request):
                response = super().evaluate(request)
                response["schema_version"] = WORKER_RESPONSE_WIRE_SCHEMA
                raw_count = request["required_raw_determinant_count"]
                for diagnostic in response["diagnostic_roots"].values():
                    diagnostic["raw_determinant_evaluation_count"] = raw_count
                return response

        cases = (
            ("horizon-admittance", None, 1),
            ("exterior-light-ring", None, 1),
            (
                "exterior-light-ring",
                "exterior-determinant-absolute-error-certificate/empirical-v1",
                3,
            ),
        )
        for mechanism, diagnostic_model, expected_raw_count in cases:
            with self.subTest(mechanism=mechanism, model=diagnostic_model):
                job, backend = _production_promoted_backend(
                    mechanism,
                    CountedDiagnosticAdapter(),
                    diagnostic_model_identity=diagnostic_model,
                )
                readout = backend.read_root(job, 0.0j)
                for diagnostic in readout.diagnostic_readouts.values():
                    evidence = diagnostic.fixed_root_evidence
                    self.assertEqual(evidence.determinant_count, 1)
                    self.assertEqual(
                        evidence.raw_determinant_evaluation_count,
                        expected_raw_count,
                    )
                    current_mapping = evidence.to_mapping()
                    self.assertEqual(
                        current_mapping[
                            "raw_determinant_evaluation_count"
                        ],
                        expected_raw_count,
                    )
                    forged_mapping = dict(current_mapping)
                    forged_mapping[
                        "raw_determinant_evaluation_count"
                    ] = None
                    with self.assertRaisesRegex(
                        ValueError, "raw determinant evaluation count"
                    ):
                        FixedRootDiagnosticEvidence.from_mapping(
                            forged_mapping
                        )
                    legacy_mapping = dict(current_mapping)
                    legacy_mapping.pop(
                        "raw_determinant_evaluation_count"
                    )
                    legacy = FixedRootDiagnosticEvidence.from_mapping(
                        legacy_mapping
                    )
                    self.assertIsNone(
                        legacy.raw_determinant_evaluation_count
                    )
                    self.assertEqual(legacy.to_mapping(), legacy_mapping)
                if mechanism == "horizon-admittance":
                    legacy_readout_mapping = readout.to_mapping()
                    for diagnostic in legacy_readout_mapping[
                        "diagnostic_readouts"
                    ].values():
                        diagnostic["fixed_root_evidence"].pop(
                            "raw_determinant_evaluation_count"
                        )
                    receipt = legacy_readout_mapping[
                        "worker_response_receipt"
                    ]
                    receipt["worker_response_schema_version"] = 9
                    receipt_material = {
                        key: value
                        for key, value in receipt.items()
                        if key != "receipt_sha256"
                    }
                    receipt["receipt_sha256"] = hashlib.sha256(
                        canonical_json_bytes(receipt_material)
                    ).hexdigest()
                    restored = RootReadout.from_mapping(
                        legacy_readout_mapping
                    )
                    self.assertEqual(
                        restored.to_mapping(), legacy_readout_mapping
                    )

    def test_fixed_root_wire_rejects_wrong_raw_count_or_json_type(self):
        """Catches accepting a forged or JSON-coerced raw evaluation count."""

        for bad_value in ("3", 3.0, True, 1, 2, 4, 0, -1, None):
            with self.subTest(bad_value=bad_value):
                class ForgedRawCountAdapter(FakeAdapter):
                    def evaluate(self, request):
                        response = super().evaluate(request)
                        response["schema_version"] = WORKER_RESPONSE_WIRE_SCHEMA
                        for diagnostic in response[
                            "diagnostic_roots"
                        ].values():
                            diagnostic[
                                "raw_determinant_evaluation_count"
                            ] = bad_value
                        return response

                with self.assertRaisesRegex(
                    JuliaResponseBackendError,
                    "fixed-root diagnostic contract",
                ):
                    _production_promoted_backend(
                        "exterior-light-ring",
                        ForgedRawCountAdapter(),
                        diagnostic_model_identity=(
                            "exterior-determinant-absolute-error-certificate/empirical-v1"
                        ),
                    )[1].read_root(
                        _job_for_mechanism("exterior-light-ring"), 0.0j
                    )

        class ForgedHorizonCountAdapter(FakeAdapter):
            def evaluate(self, request):
                response = super().evaluate(request)
                for diagnostic in response["diagnostic_roots"].values():
                    diagnostic["raw_determinant_evaluation_count"] = 3
                return response

        with self.assertRaisesRegex(
            JuliaResponseBackendError,
            "fixed-root diagnostic contract",
        ):
            _production_promoted_backend(
                "horizon-admittance", ForgedHorizonCountAdapter()
            )[1].read_root(
                _job_for_mechanism("horizon-admittance"), 0.0j
            )

    def test_current_wire_binds_raw_count_to_explicit_empirical_contract(self):
        """Catches resealing empirical evidence as an uncertified one-call result."""

        exterior_job, exterior_backend = _production_promoted_backend(
            "exterior-light-ring",
            FakeAdapter(),
            diagnostic_model_identity=(
                "exterior-determinant-absolute-error-certificate/empirical-v1"
            ),
        )
        exterior_mapping = exterior_backend.read_root(
            exterior_job, 0.0j
        ).to_mapping()
        for label, replacement in (
            ("missing", ...),
            ("null", None),
            ("horizon", "verified-endpoint-control-equivalence-absolute-error/v2"),
            ("corrupt", "forged-exterior-error-model/v1"),
        ):
            with self.subTest(mechanism="exterior", model=label):
                forged = json.loads(canonical_json_bytes(exterior_mapping))
                policy = forged["worker_response_receipt"][
                    "request_binding"
                ]["policy"]
                if replacement is ...:
                    policy.pop("determinant_error_model")
                else:
                    policy["determinant_error_model"] = replacement
                for diagnostic in forged["diagnostic_readouts"].values():
                    diagnostic["fixed_root_evidence"][
                        "raw_determinant_evaluation_count"
                    ] = 1
                _reseal_worker_response_receipt(forged)
                with self.assertRaisesRegex(
                    ValueError, "determinant.*policy|certificate"
                ):
                    RootReadout.from_mapping(forged)

        horizon_job, horizon_backend = _production_promoted_backend(
            "horizon-admittance", FakeAdapter()
        )
        forged_horizon = horizon_backend.read_root(
            horizon_job, 0.0j
        ).to_mapping()
        forged_horizon["worker_response_receipt"]["request_binding"][
            "policy"
        ]["determinant_error_model"] = (
            EXTERIOR_DETERMINANT_ABSOLUTE_ERROR_CERTIFICATE
        )
        for diagnostic in forged_horizon["diagnostic_readouts"].values():
            diagnostic["fixed_root_evidence"][
                "raw_determinant_evaluation_count"
            ] = 3
        _reseal_worker_response_receipt(forged_horizon)
        with self.assertRaisesRegex(
            ValueError, "determinant.*policy|certificate"
        ):
            RootReadout.from_mapping(forged_horizon)

    def test_persisted_wire_schema_requires_an_exact_json_integer(self):
        """Catches Python numeric equality accepting 11.0 as wire schema 11."""

        job, backend = _production_promoted_backend(
            "horizon-admittance", FakeAdapter()
        )
        valid_mapping = backend.read_root(job, 0.0j).to_mapping()
        for bad_schema in (11.0, 10.0, True, "11", None):
            with self.subTest(schema=bad_schema):
                forged = json.loads(canonical_json_bytes(valid_mapping))
                forged["worker_response_receipt"][
                    "worker_response_schema_version"
                ] = bad_schema
                _reseal_worker_response_receipt(forged)
                with self.assertRaisesRegex(
                    ValueError, "wire schema"
                ):
                    RootReadout.from_mapping(forged)

    def test_current_wire_requires_the_complete_exterior_certificate(self):
        """Catches resealing a partially stripped calibration-policy fragment."""

        job, backend = _production_promoted_backend(
            "exterior-light-ring",
            FakeAdapter(),
            diagnostic_model_identity=(
                "exterior-determinant-absolute-error-certificate/empirical-v1"
            ),
        )
        valid_mapping = backend.read_root(job, 0.0j).to_mapping()
        corrupt_values = {
            "determinant_error_required_term_classes": ["delta_same_point"],
            "determinant_error_missing_evidence_outcome": "forged-outcome/v1",
            "determinant_error_certificate_statement": "formal enclosure",
            "determinant_error_preceding_precision_tier": "bigfloat-80",
            "determinant_error_safety_factor": "64",
            "promoted_control_calibration_receipt_sha256": "0" * 64,
            "empirical_control_profile_sha256": "0" * 64,
        }
        for field, bad_value in corrupt_values.items():
            for mutation in ("missing", "corrupt"):
                with self.subTest(field=field, mutation=mutation):
                    forged = json.loads(
                        canonical_json_bytes(valid_mapping)
                    )
                    policy = forged["worker_response_receipt"][
                        "request_binding"
                    ]["policy"]
                    if mutation == "missing":
                        policy.pop(field)
                    else:
                        policy[field] = bad_value
                    _reseal_worker_response_receipt(forged)
            with self.assertRaisesRegex(
                ValueError, "determinant certificate policy"
            ):
                RootReadout.from_mapping(forged)

    def test_legacy_wire_ten_rejects_provisional_exterior_contract(self):
        """Wire 10 cannot carry the new one-evaluation exterior identity."""

        job, backend = _production_promoted_backend(
            "exterior-light-ring",
            FakeAdapter(),
            diagnostic_model_identity=(
                "exterior-determinant-additive-channels/provisional-v1"
            ),
        )
        forged = backend.read_root(job, 0.0j).to_mapping()
        forged["worker_response_receipt"]["worker_response_schema_version"] = 10
        _reseal_worker_response_receipt(forged)
        with self.assertRaisesRegex(
            ValueError, "wire.?10.*provisional|provisional.*wire.?10"
        ):
            RootReadout.from_mapping(forged)

    def test_persisted_wire_nine_rejects_schema_ten_raw_count_field(self):
        """Catches smuggling a schema-10 raw count through a wire-9 receipt."""

        job, backend = _production_promoted_backend(
            "horizon-admittance", FakeAdapter()
        )
        forged = backend.read_root(job, 0.0j).to_mapping()
        forged["worker_response_receipt"][
            "worker_response_schema_version"
        ] = 9
        _reseal_worker_response_receipt(forged)
        with self.assertRaisesRegex(
            ValueError, "wire schema.*raw determinant|raw determinant.*wire schema"
        ):
            RootReadout.from_mapping(forged)

    def test_promoted_primary_acceptance_is_raw_binary64_parity(self):
        readout = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity, FakeAdapter(), 80
        ).read_root(_job_for_mechanism("horizon-admittance"), 0.0j)

        evidence = readout.primary_acceptance
        self.assertEqual(evidence.determinant.magnitude(), Decimal("1E-12"))
        self.assertEqual(
            evidence.derivative,
            DecimalComplex(Decimal("6"), Decimal("8")),
        )
        self.assertEqual(evidence.derivative.magnitude(), Decimal("10"))
        self.assertEqual(evidence.correction_abs, Decimal("1E-13"))
        self.assertEqual(
            evidence.correction_abs,
            evidence.determinant.magnitude() / evidence.derivative.magnitude(),
        )
        # Deliberately much larger than |D|: telemetry is not acceptance.
        self.assertEqual(evidence.determinant_error_abs, Decimal("1"))
        self.assertTrue(evidence.accepted)
        self.assertEqual(evidence.post_newton_determinant_count, 0)
        self.assertIsNone(readout.root_authentication)

    def test_promoted_primary_rejects_a_forged_raw_correction(self):
        class ForgedAdapter(FakeAdapter):
            def evaluate(self, request):
                response = super().evaluate(request)
                evidence = dict(response["primary_acceptance"])
                evidence["correction_abs"] = "1E-14"
                response["primary_acceptance"] = evidence
                return response

        with self.assertRaisesRegex(
            JuliaResponseBackendError, "PRIMARY acceptance evidence"
        ):
            JuliaPrecisionRootBackend(
                VettedNativeDeterminantKernel.identity, ForgedAdapter(), 80
            ).read_root(_deep_job(), 0.0j)

    def test_promoted_fixed_root_diagnostics_reuse_primary_complex_derivative(self):
        readout = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity, FakeAdapter(), 80
        ).read_root(_job_for_mechanism("horizon-admittance"), 0.0j)

        primary_derivative = readout.primary_acceptance.derivative
        self.assertEqual(set(readout.diagnostic_readouts), {
            "truncation", "resolution"
        })
        for diagnostic in readout.diagnostic_readouts.values():
            evidence = diagnostic.fixed_root_evidence
            self.assertEqual(evidence.primary_derivative, primary_derivative)
            self.assertEqual(evidence.determinant_count, 1)
            self.assertEqual(diagnostic.omega_delta_from_primary, 0.0j)
            self.assertEqual(
                evidence.correction_abs,
                evidence.determinant.magnitude()
                / primary_derivative.magnitude(),
            )
            self.assertEqual(evidence.determinant_error_abs, Decimal("1"))
            self.assertTrue(evidence.accepted)
        self.assertFalse(readout.seed_path_required)
        self.assertFalse(readout.seed_path_executed)
        self.assertEqual(readout.seed_path_determinant_count, 0)
        self.assertIsNone(readout.seed_path_radius)

    def test_promoted_fixed_root_diagnostic_rejects_derivative_recomputation(self):
        class RecomputedDerivativeAdapter(FakeAdapter):
            def evaluate(self, request):
                response = super().evaluate(request)
                diagnostic = dict(response["diagnostic_roots"]["truncation"])
                diagnostic["primary_derivative_re"] = "9"
                diagnostic["correction_abs"] = str(Decimal("1E-12") / 9)
                response["diagnostic_roots"] = {
                    **response["diagnostic_roots"],
                    "truncation": diagnostic,
                }
                return response

        with self.assertRaisesRegex(
            JuliaResponseBackendError, "fixed-root diagnostic binding"
        ):
            JuliaPrecisionRootBackend(
                VettedNativeDeterminantKernel.identity,
                RecomputedDerivativeAdapter(),
                80,
            ).read_root(_deep_job(), 0.0j)

    def test_fixed_root_evidence_cannot_reuse_legacy_authentication_fields(self):
        readout = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity, FakeAdapter(), 80
        ).read_root(_deep_job(), 0.0j)
        diagnostic = readout.diagnostic_readouts["truncation"]

        with self.assertRaisesRegex(
            ValueError, "cannot carry legacy diagnostic workflow"
        ):
            replace(diagnostic, correction_upper_bound=1.0e-13)

    def test_promoted_truncation_or_resolution_failure_is_unresolved(self):
        for family in ("truncation", "resolution"):
            with self.subTest(family=family):
                class FailedDiagnosticAdapter(FakeAdapter):
                    def evaluate(self, request):
                        response = super().evaluate(request)
                        diagnostic = dict(response["diagnostic_roots"][family])
                        diagnostic.update({
                            "determinant_re": "1",
                            "root_residual_abs": "1",
                            "correction_abs": "0.1",
                            "root_converged": False,
                        })
                        response["diagnostic_roots"] = {
                            **response["diagnostic_roots"],
                            family: diagnostic,
                        }
                        response["root_converged"] = False
                        return response

                readout = JuliaPrecisionRootBackend(
                    VettedNativeDeterminantKernel.identity,
                    FailedDiagnosticAdapter(),
                    80,
                ).read_root(_deep_job(), 0.0j)
                self.assertFalse(readout.converged)
                self.assertFalse(readout.diagnostic_readouts[family].converged)

    def test_promoted_diagnostic_cannot_move_the_primary_frequency(self):
        class MovedDiagnosticAdapter(FakeAdapter):
            def evaluate(self, request):
                response = super().evaluate(request)
                diagnostic = dict(response["diagnostic_roots"]["resolution"])
                with localcontext() as context:
                    context.prec = 180
                    diagnostic["root_omega_re"] = str(
                        Decimal(diagnostic["root_omega_re"])
                        + Decimal("1E-40")
                    )
                response["diagnostic_roots"] = {
                    **response["diagnostic_roots"],
                    "resolution": diagnostic,
                }
                return response

        with self.assertRaisesRegex(
            JuliaResponseBackendError, "fixed-root diagnostic binding"
        ):
            JuliaPrecisionRootBackend(
                VettedNativeDeterminantKernel.identity,
                MovedDiagnosticAdapter(),
                80,
            ).read_root(_deep_job(), 0.0j)

    def test_worker_promoted_policy_reaches_the_backend_end_to_end(self):
        """The current producer and consumer agree for both determinants."""

        for mechanism, expected_model, expected_count in (
            (
                "horizon-admittance",
                "verified-endpoint-control-equivalence-absolute-error/v2",
                1,
            ),
            (
                "exterior-fixed-r3",
                "exterior-determinant-additive-channels/provisional-v1",
                1,
            ),
        ):
            with self.subTest(mechanism=mechanism):
                adapter = FakeAdapter()
                job, backend = _production_promoted_backend(
                    mechanism, adapter
                )
                readout = backend.read_root(job, 0.0j)

                self.assertTrue(readout.converged)
                self.assertIsNone(readout.root_authentication)
                primary = readout.primary_acceptance
                self.assertTrue(primary.accepted)
                self.assertEqual(primary.post_newton_determinant_count, 0)
                self.assertEqual(
                    primary.correction_abs,
                    primary.determinant.magnitude()
                    / primary.derivative.magnitude(),
                )
                self.assertEqual(
                    primary.error_model_id,
                    None if expected_count == 1 and mechanism != "horizon-admittance"
                    else expected_model,
                )
                self.assertEqual(
                    set(readout.diagnostic_readouts),
                    {"truncation", "resolution"},
                )
                for diagnostic in readout.diagnostic_readouts.values():
                    evidence = diagnostic.fixed_root_evidence
                    self.assertEqual(evidence.determinant_count, 1)
                    self.assertEqual(
                        evidence.raw_determinant_evaluation_count,
                        expected_count,
                    )
                    self.assertEqual(
                        evidence.primary_derivative, primary.derivative
                    )
                    self.assertEqual(diagnostic.omega_delta_from_primary, 0.0j)
                self.assertFalse(readout.seed_path_required)
                self.assertFalse(readout.seed_path_executed)
                self.assertEqual(readout.seed_path_determinant_count, 0)
                self.assertIsNone(readout.seed_path_radius)

    def test_legacy_staged_authentication_evidence_is_fail_closed(self):
        """Persisted v6 evidence neither omits nor invents derivative directions."""

        def drop_strategy(authentication):
            authentication.pop("authentication_strategy")

        def invent_double(authentication):
            evidence = dict(authentication["derivative_evidence"])
            evidence["real_double"] = {
                "real": authentication["derivative_authentication"][
                    "derivative_re"
                ],
                "imaginary": authentication["derivative_authentication"][
                    "derivative_im"
                ],
            }
            authentication["derivative_evidence"] = evidence

        def invent_imaginary(authentication):
            evidence = dict(authentication["derivative_evidence"])
            evidence["imaginary"] = {
                "real": authentication["derivative_authentication"][
                    "derivative_re"
                ],
                "imaginary": authentication["derivative_authentication"][
                    "derivative_im"
                ],
            }
            authentication["derivative_evidence"] = evidence

        def claim_full_ladder(authentication):
            authentication["authentication_strategy"] = (
                "full-h-h2-2h-ih-ladder/v1"
            )

        for mutate in (
            drop_strategy,
            invent_double,
            invent_imaginary,
            claim_full_ladder,
        ):
            with self.subTest(mutation=mutate.__name__):
                authentication = valid_root_authentication(
                    "horizon-admittance"
                )
                mutate(authentication)
                with self.assertRaises(ValueError):
                    RootAuthenticationEvidence.from_mapping(authentication)

    def test_current_fixed_root_workflow_identity_is_fail_closed(self):
        """A fixed-root diagnostic cannot claim authority or derivative work."""

        def claim_authority(record):
            record["authoritative"] = True

        def claim_recomputed_derivative(record):
            record["derivative_source"] = "RECOMPUTED"

        def claim_wrong_phase(record):
            record["root_phase"] = "TRUNCATION"

        def add_a_second_determinant(record):
            record["determinant_count"] = 2

        for mutate in (
            claim_authority,
            claim_recomputed_derivative,
            claim_wrong_phase,
            add_a_second_determinant,
        ):
            with self.subTest(mutation=mutate.__name__):
                class ForgedAdapter(FakeAdapter):
                    def evaluate(self, request):
                        response = super().evaluate(request)
                        record = dict(
                            response["diagnostic_roots"]["resolution"]
                        )
                        mutate(record)
                        response["diagnostic_roots"]["resolution"] = record
                        return response

                with self.assertRaises(JuliaResponseBackendError):
                    JuliaPrecisionRootBackend(
                        VettedNativeDeterminantKernel.identity,
                        ForgedAdapter(),
                        80,
                    ).read_root(
                        _job_for_mechanism("horizon-admittance"),
                        0.0j,
                    )

    def test_readout_carries_primary_acceptance_past_the_backend(self):
        """Catches convergence surviving while its evidence is discarded.

        Once the worker output is gone, a stored ``converged`` flag is an
        assertion with nothing behind it. The readout therefore carries the
        terms the decision was made on, so it can be re-checked rather than
        trusted.
        """

        for mechanism in ("horizon-admittance", "exterior-fixed-r3"):
            with self.subTest(mechanism=mechanism):
                job, backend = _production_promoted_backend(
                    mechanism, FakeAdapter()
                )

                readout = backend.read_root(job, 0.0j)

                evidence = readout.primary_acceptance
                self.assertIsNotNone(evidence)
                self.assertIsNone(readout.root_authentication)
                self.assertGreater(evidence.derivative.magnitude(), 0)
                self.assertEqual(
                    evidence.correction_abs,
                    evidence.determinant.magnitude()
                    / evidence.derivative.magnitude(),
                )
                self.assertIsInstance(evidence.determinant.real, Decimal)

    def test_primary_acceptance_survives_the_readout_round_trip(self):
        """Catches evidence dropped the first time a readout is written down.

        A readout is serialised into caches and solved-leaf material and read
        back later. Evidence the round trip discards is evidence that exists
        only inside the process that produced it, which is the same as not
        having it: the acceptance can be re-asserted from the stored flag but
        no longer re-checked.
        """

        for mechanism in ("horizon-admittance", "exterior-fixed-r3"):
            with self.subTest(mechanism=mechanism):
                job, backend = _production_promoted_backend(
                    mechanism, FakeAdapter()
                )
                readout = backend.read_root(job, 0.0j)

                restored = RootReadout.from_mapping(readout.to_mapping())
                original = readout.primary_acceptance
                recovered = restored.primary_acceptance

                self.assertIsNotNone(recovered)
                self.assertEqual(recovered, original)
                self.assertEqual(
                    recovered.derivative,
                    original.derivative,
                )
                json.loads(json.dumps(readout.to_mapping()["primary_acceptance"]))

    def test_readout_rejects_primary_acceptance_detached_after_persistence(self):
        """Catches coherent PRIMARY evidence being moved onto another readout."""

        readout = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity, FakeAdapter(), 80
        ).read_root(_job_for_mechanism("horizon-admittance"), 0.0j)
        mapping = readout.to_mapping()
        evidence = dict(mapping["primary_acceptance"])
        evidence["determinant_re"] = "2E-12"
        evidence["determinant_im"] = "0"
        evidence["correction_abs"] = "2E-13"
        mapping["primary_acceptance"] = evidence

        with self.assertRaisesRegex(
            ValueError, "root readout scalars disagree with PRIMARY acceptance"
        ):
            RootReadout.from_mapping(mapping)

    def test_main_era_exterior_worker_receipt_remains_readable(self):
        """Catches a wire migration retiring unchanged exterior readouts."""

        readout = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity, LegacyFakeAdapter(), 80
        ).read_root(_job_for_mechanism("exterior-fixed-r3"), 0.0j)
        mapping = readout.to_mapping()
        mapping["root_authentication"] = None
        receipt = dict(mapping["worker_response_receipt"])
        receipt["worker_response_schema_version"] = 3
        material = {
            key: value
            for key, value in receipt.items()
            if key != "receipt_sha256"
        }
        receipt["receipt_sha256"] = hashlib.sha256(
            canonical_json_bytes(material)
        ).hexdigest()
        mapping["worker_response_receipt"] = receipt

        restored = RootReadout.from_mapping(mapping)

        self.assertIsNone(restored.root_authentication)
        self.assertEqual(
            restored.worker_response_receipt[
                "worker_response_schema_version"
            ],
            3,
        )

    def test_backend_rejects_authentication_disagreeing_with_its_family(self):
        """Catches an error-aware decision made from an absent error term."""

        class MismatchedAdapter(LegacyFakeAdapter):
            def evaluate(self, request):
                response = super().evaluate(request)
                authentication = dict(response["root_authentication"])
                authentication["determinant_error"] = None
                authentication["central_determinant_re"] = "2.4E-60"
                authentication["central_determinant_im"] = "0"
                authentication["residual_upper_bound_abs"] = "2.4E-60"
                authentication["correction_upper_bound"] = "1E-60"
                response["root_authentication"] = authentication
                return response

        backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity, MismatchedAdapter(), 80
        )
        with self.assertRaisesRegex(
            JuliaResponseBackendError, "error model does not match"
        ):
            backend.read_root(_job_for_mechanism("horizon-admittance"), 0.0j)

    def test_backend_rejects_a_missing_root_authentication_record(self):
        class LegacyAdapter(LegacyFakeAdapter):
            def evaluate(self, request):
                response = super().evaluate(request)
                del response["root_authentication"]
                return response

        backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity, LegacyAdapter(), 80
        )
        with self.assertRaisesRegex(
            JuliaResponseBackendError, "response fields are invalid"
        ):
            backend.read_root(_deep_job(), 0.0j)

    def test_backend_rejects_a_malformed_root_authentication_record(self):
        for mutate, description in (
            (lambda record: record["derivative_authentication"].__setitem__(
                "axis", "diagonal"
            ),
             "invalid axis"),
            (lambda record: record["derivative_authentication"].__setitem__(
                "lower_bound_abs", "0"
            ),
             "non-positive derivative bound"),
            (lambda record: record["derivative_authentication"].__setitem__(
                "selected_step", "-1e-6"
            ),
             "negative step"),
            (lambda record: record.pop("determinant_error"),
             "missing determinant-error certificate"),
            (lambda record: record.pop("derivative_authentication"),
             "missing derivative certificate"),
            (lambda record: record.pop("correction_upper_bound"),
             "missing field"),
        ):
            with self.subTest(description=description):
                class BrokenAdapter(LegacyFakeAdapter):
                    def evaluate(self, request):
                        response = super().evaluate(request)
                        record = dict(response["root_authentication"])
                        mutate(record)
                        response["root_authentication"] = record
                        return response

                backend = JuliaPrecisionRootBackend(
                    VettedNativeDeterminantKernel.identity, BrokenAdapter(), 80
                )
                with self.assertRaises(JuliaResponseBackendError):
                    backend.read_root(_deep_job(), 0.0j)

    def test_backend_rejects_arithmetically_inconsistent_root_authentication(self):
        """Catches a certificate whose conclusion does not follow from its terms."""

        for field, replacement, nested in (
            ("residual_upper_bound_abs", "9E-60", False),
            ("lower_bound_abs", "2.3", True),
            ("correction_upper_bound", "1E-100", False),
        ):
            with self.subTest(field=field):
                class InconsistentAdapter(LegacyFakeAdapter):
                    def evaluate(self, request):
                        response = super().evaluate(request)
                        authentication = dict(response["root_authentication"])
                        if nested:
                            derivative = dict(
                                authentication["derivative_authentication"]
                            )
                            derivative[field] = replacement
                            authentication["derivative_authentication"] = derivative
                        else:
                            authentication[field] = replacement
                        response["root_authentication"] = authentication
                        return response

                backend = JuliaPrecisionRootBackend(
                    VettedNativeDeterminantKernel.identity,
                    InconsistentAdapter(),
                    80,
                )
                with self.assertRaisesRegex(
                    JuliaResponseBackendError, "root authentication evidence"
                ):
                    backend.read_root(
                        _job_for_mechanism("horizon-admittance"), 0.0j
                    )

    def test_backend_binds_authentication_to_response_and_policy(self):
        """Catches a coherent certificate attached to the wrong result or model."""

        def changed_central(response):
            authentication = dict(response["root_authentication"])
            authentication["central_determinant_re"] = "2E-60"
            authentication["central_determinant_im"] = "0"
            authentication["residual_upper_bound_abs"] = "3.4E-60"
            authentication["correction_upper_bound"] = str(
                Decimal("3.4E-60") / Decimal("2.4")
            )
            response["root_authentication"] = authentication

        def changed_derivative(response):
            authentication = dict(response["root_authentication"])
            derivative = dict(authentication["derivative_authentication"])
            derivative["derivative_re"] = (
                "3.000000000000000000000000000000000000000000000000000003"
            )
            derivative["derivative_im"] = "0"
            derivative["lower_bound_abs"] = "3"
            authentication["derivative_authentication"] = derivative
            authentication["correction_upper_bound"] = "8E-61"
            response["root_authentication"] = authentication

        def changed_model(response):
            authentication = dict(response["root_authentication"])
            determinant_error = dict(authentication["determinant_error"])
            determinant_error["error_model_id"] = "unrecognised-model/v999"
            authentication["determinant_error"] = determinant_error
            response["root_authentication"] = authentication

        for description, mutate in (
            ("central determinant", changed_central),
            ("derivative", changed_derivative),
            ("error model", changed_model),
        ):
            with self.subTest(description=description):
                class DetachedAdapter(LegacyFakeAdapter):
                    def evaluate(self, request):
                        response = super().evaluate(request)
                        mutate(response)
                        return response

                backend = JuliaPrecisionRootBackend(
                    VettedNativeDeterminantKernel.identity,
                    DetachedAdapter(),
                    80,
                )
                with self.assertRaises(JuliaResponseBackendError):
                    backend.read_root(
                        _job_for_mechanism("horizon-admittance"), 0.0j
                    )

    def test_backend_accepts_distinct_raw_derivative_and_wire_lower_bound(self):
        class DistinctDerivativeAdapter(LegacyFakeAdapter):
            def evaluate(self, request):
                return _set_distinct_derivative_binding(
                    super().evaluate(request), "8"
                )

        readout = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            DistinctDerivativeAdapter(),
            80,
        ).read_root(_job_for_mechanism("horizon-admittance"), 0.0j)

        authentication = readout.root_authentication
        self.assertEqual(
            authentication.derivative_estimate.magnitude(), Decimal("10")
        )
        self.assertEqual(
            authentication.derivative_lower_bound_abs, Decimal("8")
        )
        self.assertEqual(readout.determinant_derivative_abs, 10.0)

    def test_backend_rejects_incorrect_wire_derivative_lower_bound(self):
        class IncorrectLowerBoundAdapter(LegacyFakeAdapter):
            def evaluate(self, request):
                return _set_distinct_derivative_binding(
                    super().evaluate(request), "7.9"
                )

        with self.assertRaises(JuliaResponseBackendError):
            JuliaPrecisionRootBackend(
                VettedNativeDeterminantKernel.identity,
                IncorrectLowerBoundAdapter(),
                80,
            ).read_root(_job_for_mechanism("horizon-admittance"), 0.0j)

    def test_backend_rejects_raw_derivative_as_wire_lower_bound(self):
        class RawDerivativeAdapter(LegacyFakeAdapter):
            def evaluate(self, request):
                return _set_distinct_derivative_binding(
                    super().evaluate(request), "10"
                )

        with self.assertRaises(JuliaResponseBackendError):
            JuliaPrecisionRootBackend(
                VettedNativeDeterminantKernel.identity,
                RawDerivativeAdapter(),
                80,
            ).read_root(_job_for_mechanism("horizon-admittance"), 0.0j)

    def test_promoted_root_at_shared_correction_threshold_is_converged(self):
        """The raw Newton correction is accepted at the inclusive 2e-11 edge."""

        class BoundaryAdapter(FakeAdapter):
            def evaluate(self, request):
                response = super().evaluate(request)
                with localcontext() as context:
                    context.prec = 180
                    tolerance = Decimal("2e-11")
                    derivative = response["primary_acceptance"]
                    derivative_abs = (
                        Decimal(derivative["derivative_re"]) ** 2
                        + Decimal(derivative["derivative_im"]) ** 2
                    ).sqrt()
                    determinant_abs = tolerance * derivative_abs
                primary = dict(response["primary_acceptance"])
                primary["determinant_re"] = str(determinant_abs)
                primary["determinant_im"] = "0"
                primary["correction_abs"] = str(tolerance)
                response["primary_acceptance"] = primary
                response["root_residual_abs"] = str(determinant_abs)
                return response

        job = _job_for_mechanism("horizon-admittance")
        for digits, refinement in ((80, 0), (80, 1), (120, 0), (120, 1)):
            with self.subTest(digits=digits, refinement=refinement):
                readout = JuliaPrecisionRootBackend(
                    VettedNativeDeterminantKernel.identity,
                    BoundaryAdapter(),
                    digits,
                    refinement=refinement,
                ).read_root(job, 0.0j)
                self.assertTrue(readout.converged)
                self.assertEqual(
                    readout.primary_acceptance.correction_abs,
                    Decimal("2e-11"),
                )

    def test_backend_rejects_converged_root_above_declared_correction_target(self):
        """Catches a coherent large correction being labelled as solved."""

        class FalseSolvedAdapter(FakeAdapter):
            def evaluate(self, request):
                response = super().evaluate(request)
                primary = dict(response["primary_acceptance"])
                primary.update({
                    "determinant_re": "3E-10",
                    "determinant_im": "0",
                    "correction_abs": "3E-11",
                    "accepted": True,
                })
                response["primary_acceptance"] = primary
                response["root_residual_abs"] = "3E-10"
                return response

        backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            FalseSolvedAdapter(),
            80,
        )
        with self.assertRaisesRegex(
            JuliaResponseBackendError, "PRIMARY acceptance evidence"
        ):
            backend.read_root(_job_for_mechanism("horizon-admittance"), 0.0j)

    def test_non_converged_response_still_carries_primary_evidence(self):
        class NonconvergedAdapter(FakeAdapter):
            def evaluate(self, request):
                response = super().evaluate(request)
                primary = dict(response["primary_acceptance"])
                primary.update({
                    "determinant_re": "3E-10",
                    "determinant_im": "0",
                    "correction_abs": "3E-11",
                    "accepted": False,
                })
                response.update({
                    "root_residual_abs": "3E-10",
                    "primary_acceptance": primary,
                    "root_converged": False,
                    "root_displacement_abs": "0",
                    "truncation_radius_abs": None,
                    "resolution_radius_abs": None,
                    "seed_path_radius_abs": None,
                    "diagnostic_roots": {},
                    "diagnostics_skipped_reason": "PRIMARY_NOT_CONVERGED",
                })
                return response

        adapter = NonconvergedAdapter()
        backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity, adapter, 80
        )

        readout = backend.read_root(_deep_job(), 0.0j)

        self.assertFalse(readout.converged)
        response = adapter.evaluate(adapter.requests[0])
        self.assertFalse(response["primary_acceptance"]["accepted"])
        self.assertFalse(readout.primary_acceptance.accepted)

    def test_worker_control_failure_binds_request_job_and_refinement(self):
        root = Path(__file__).resolve().parents[1]
        worker = (
            root / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")
        flatten = worker[
            worker.index("function flatten_request(") :
            worker.index("function parse_real(")
        ]
        context = worker[
            worker.index("function control_failure_context(") :
            worker.index("function throw_ode_resource_limit(")
        ]
        for field in ("job_id", "leaf_id", "request_sha256"):
            self.assertIn(f'"{field}" =>', flatten)
            self.assertIn(f'required(document, "{field}")', flatten)
            self.assertIn(f'"{field}" =>', context)
            self.assertIn(f'required(request, "{field}")', context)
        for field in (
            "role",
            "job_policy_sha256",
            "refinement_level",
        ):
            self.assertIn(f'"{field}" =>', flatten)
            self.assertIn(f'required(document, "{field}")', flatten)
            self.assertIn(
                f'failure_context["{field}"] = required(identity, "{field}")',
                context,
            )
        self.assertIn('"execution_identity" => identity', context)
        self.assertIn('"operation" => required(identity, "operation")', context)

    @staticmethod
    def _force_stop_process(pid_path: Path) -> None:
        if not pid_path.is_file():
            return
        pid = int(pid_path.read_text(encoding="ascii"))
        if os.name == "nt":
            subprocess.run(
                ("taskkill", "/PID", str(pid), "/T", "/F"),
                check=False,
                capture_output=True,
            )
        else:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    @staticmethod
    def _process_tree_command(
        directory: Path, *, emit_reserved_progress: bool = False
    ) -> tuple[str, ...]:
        parent_pid = directory / "parent.pid"
        child_pid = directory / "child.pid"
        marker = directory / "child.marker"
        child = (
            "import os,sys,time; "
            "open(sys.argv[1],'w',encoding='ascii').write(str(os.getpid())); "
            "f=open(sys.argv[2],'a',encoding='ascii'); "
            "[(f.write('x'),f.flush(),time.sleep(.02)) for _ in range(3000)]"
        )
        progress = ""
        if emit_reserved_progress:
            progress = (
                f"print({(JULIA_PROGRESS_PREFIX + json.dumps({'schema': PROGRESS_SCHEMA, 'kind': 'request_started', 'context': {}, 'payload': {}}))!r}, flush=True); "
            )
        parent = (
            "import os,subprocess,sys,time; "
            "open(sys.argv[1],'w',encoding='ascii').write(str(os.getpid())); "
            f"subprocess.Popen([sys.executable,'-c',{child!r},sys.argv[2],sys.argv[3]],"
            "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
            "deadline=time.time()+5; "
            "exec(\"while not os.path.exists(sys.argv[3]) and time.time() < deadline:\\n time.sleep(.01)\"); "
            + progress
            + "time.sleep(60)"
        )
        return (
            sys.executable,
            "-c",
            parent,
            str(parent_pid),
            str(child_pid),
            str(marker),
        )

    def test_streamed_worker_progress_and_heartbeat_are_serialized(self):
        """Catches a live Julia child becoming invisible between stdout events."""

        class Observer:
            def __init__(self):
                self.events = []
                self.thread_ids = []

            def publish(self, event):
                self.events.append(event)
                self.thread_ids.append(threading.get_ident())

        worker_event = JULIA_PROGRESS_PREFIX + json.dumps({
            "schema": PROGRESS_SCHEMA,
            "kind": "suboperation_started",
            "context": {"suboperation": "r-from-rho"},
            "payload": {"suboperation": "r-from-rho"},
        })
        script = (
            "import time; "
            f"print({worker_event!r}, flush=True); "
            "time.sleep(0.08)"
        )
        observer = Observer()
        caller_thread = threading.get_ident()

        with patch(
            "windows_solver.julia_response_backend._WORKER_HEARTBEAT_SECONDS",
            0.01,
            create=True,
        ):
            with activate_progress(observer):
                completed = _run_streamed_julia(
                    (sys.executable, "-c", script),
                    cwd=Path.cwd(),
                    env=os.environ,
                    timeout=5,
                )

        kinds = [event.kind.value for event in observer.events]
        self.assertEqual(completed.returncode, 0)
        self.assertIn("suboperation_started", kinds)
        self.assertIn("worker_heartbeat", kinds)
        self.assertTrue(observer.thread_ids)
        self.assertEqual(set(observer.thread_ids), {caller_thread})

    def test_package_worker_declares_line_flushed_inner_progress_without_request_changes(self):
        worker = (
            Path(__file__).resolve().parents[1]
            / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")
        self.assertIn('const PROGRESS_PREFIX = "@@KERR_QNM_PROGRESS@@"', worker)
        self.assertIn("flush(stdout)", worker)
        for event in (
            "root_phase_started",
            "root_seed_selected",
            "newton_iteration_started",
            "newton_iteration_completed",
            "determinant_started",
            "determinant_completed",
            "suboperation_started",
            "suboperation_completed",
        ):
            self.assertIn(f'progress_emit("{event}"', worker)
        self.assertIn('"acceptance_threshold" => string(tolerance)', worker)
        self.assertIn('haskey(document, "primary_predictor")', worker)
        self.assertIn('required(document, "primary_predictor_kind")', worker)
        self.assertIn('fallback_initial=fallback_initial', worker)
        self.assertIn('fallback_reason = "PREDICTOR_SOLVE_ERROR"', worker)
        self.assertIn("failure isa InterruptException && rethrow()", worker)
        result_fields = worker[
            worker.index("function result_fields(") :
            worker.index("function evaluate_request(")
        ]
        self.assertNotIn('"INDEPENDENT_SEED_PATH"', result_fields)
        self.assertIn('"seed_path_required" => false', result_fields)
        self.assertIn('"seed_path_executed" => false', result_fields)
        self.assertIn('"seed_path_determinant_count" => 0', result_fields)
        self.assertIn('"branch_authentication_contract_version" => 4', worker)
        self.assertIn('"root_branch_continuation_valid" => branch_valid', worker)
        self.assertIn('"branch_tolerance_abs" => numeric_text(branch_tolerance)', worker)
        self.assertIn('"root_displacement_abs" => numeric_text(abs(root - omega))', worker)
        self.assertNotIn('document["progress', worker)

    def test_package_worker_carries_the_initial_determinant_into_the_first_iteration(self):
        """Catches re-solving the determinant already computed at the seed."""

        worker = (
            Path(__file__).resolve().parents[1]
            / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")

        self.assertIn("initial_determinant = determinant_evaluator(", worker)
        self.assertIn(
            "best_upper_bound = determinant_upper_bound_abs(", worker
        )
        self.assertIn("carried_residual = initial_determinant", worker)
        self.assertIn("carried_available = true", worker)
        self.assertIn("carried_available = false", worker)
        self.assertIn("carried_residual = candidate_residual", worker)
        self.assertIn("carried_available = true", worker)
        self.assertIn(
            "return value, magnitude, derivative, true, residual", worker
        )
        self.assertIn(
            "root, residual, accepted_derivative, newton_converged, "
            "root_evaluation,",
            worker,
        )
        self.assertIn("propagate_derivative_error=true", worker)
        # The accepted Newton derivative is reused only on the unauthenticated
        # single-step path. The authenticated search must not reuse it: that
        # value was computed without an authenticated error term, so reusing it
        # would place an unauthenticated estimate inside an authenticated bound.
        single_step = worker[
            worker.index("function evaluate_single_derivative_step(") :
            worker.index("function evaluate_derivative_step_ladder(")
        ]
        self.assertIn("isnothing(accepted_derivative) ?", single_step)
        ladder = worker[
            worker.index("function evaluate_derivative_step_ladder(") :
            worker.index("function root_authentication_text(")
        ]
        self.assertNotIn("accepted_derivative,\n            nothing,", ladder)
        self.assertIn(
            "authenticate_controls || return evaluate_single_derivative_step(",
            ladder,
        )
        # The seed determinant is carried, not recomputed, but every later
        # iteration still evaluates its own residual at its own frequency.
        bounded_newton = worker[
            worker.index("function bounded_newton(") :
            worker.index("numeric_text(value)")
        ]
        self.assertEqual(
            bounded_newton.count('"residual",'),
            1,
        )
        self.assertIn("magnitude = abs(residual.value)", bounded_newton)

    def test_package_worker_reports_radial_integration_interior_progress(self):
        """Catches a radial integration that cannot be told from a stalled one."""

        worker = (
            Path(__file__).resolve().parents[1]
            / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")

        self.assertIn("function observed_radial_map(", worker)
        self.assertIn('progress_emit("suboperation_progress"', worker)
        for field in (
            "rhs_evaluations",
            "rho_current",
            "rho_reached_min",
            "rho_reached_max",
            "rho_span_fraction",
        ):
            self.assertIn(f'"{field}"', worker)
        # Every package-owned contour map reports through the observed wrapper,
        # and the map itself still returns the unmodified radius.
        self.assertIn(
            "observed_radial_map(\n"
            "        raw_radius_from_rho, label, rho_in, rho_out\n"
            "    )",
            worker,
        )
        self.assertIn('lower, "Xin"', worker)
        self.assertIn('readout, "Xup"', worker)
        self.assertIn("return radial_map(rho)", worker)
        self.assertIn("progress_active() || return radial_map", worker)

    def test_package_worker_preserves_radial_tolerances_and_reports_r_from_rho(self):
        """Catches collapsing the promoted ODE tolerance pair or hiding its map."""

        worker = (
            Path(__file__).resolve().parents[1]
            / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")

        self.assertIn(
            'progress_operation("r-from-rho"; payload=Dict(', worker
        )
        # The coordinate map draws its own tolerance pair. Collapsing the pair,
        # or sharing the homogeneous solve's local-error target, is what pinned
        # Leaf 13's coordinate leg at 8.1e-17 steps.
        self.assertIn("function coordinate_ode_tolerances(", worker)
        self.assertIn(
            'reltol=parse_real(T, request, "coordinate_ode_relative_tolerance")',
            worker,
        )
        self.assertIn(
            'abstol=parse_real(T, request, "coordinate_ode_absolute_tolerance")',
            worker,
        )
        self.assertIn("reltol=tolerances.reltol", worker)
        self.assertIn("abstol=tolerances.abstol", worker)
        self.assertNotIn("tolerance = min(", worker)
        self.assertNotIn("reltol=tolerance,", worker)
        self.assertNotIn("abstol=tolerance,", worker)

    def test_package_worker_observes_every_promoted_ode_leg_before_use(self):
        root = Path(__file__).resolve().parents[1]
        worker = (root / "src/windows_solver/data/julia/m02_worker.jl").read_text(
            encoding="utf-8"
        )
        complex_frequencies = (
            root
            / "src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/src/Homogeneous/ComplexFrequencies.jl"
        ).read_text(encoding="utf-8")

        for leg in (
            "r_from_rho_positive",
            "r_from_rho_negative",
            "Xin_inner_to_match",
            "Xin_match_to_outer",
            "Xup_outer_to_match",
            "Xup_match_to_inner",
        ):
            self.assertIn(f'"{leg}"', complex_frequencies)
        self.assertIn("ode_observation_factory=nothing", complex_frequencies)
        self.assertIn("ode_solution_observer=nothing", complex_frequencies)
        self.assertIn("ode_solution_observer(", complex_frequencies)
        self.assertIn("function ode_observation_factory(", worker)
        self.assertIn("function observe_ode_solution(", worker)
        self.assertIn("DiscreteCallback(", worker)
        self.assertIn("save_positions=(false, false)", worker)
        self.assertIn("SciMLBase.u_modified!(integrator, false)", worker)
        self.assertIn("stats = solution.stats", worker)

    def test_package_worker_serializes_ode_control_failures_without_policy_drift(self):
        root = Path(__file__).resolve().parents[1]
        worker = (root / "src/windows_solver/data/julia/m02_worker.jl").read_text(
            encoding="utf-8"
        )
        complex_frequencies = (
            root
            / "src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/src/Homogeneous/ComplexFrequencies.jl"
        ).read_text(encoding="utf-8")

        self.assertIn("abstract type ODEControlFailure", worker)
        self.assertIn("SciMLBase.ReturnCode.MaxIters", worker)
        self.assertIn('"ODE_RESOURCE_LIMIT"', worker)
        self.assertIn('"ODE_SOLVER_FAILURE"', worker)
        self.assertIn("failure isa ODEControlFailure && rethrow()", worker)
        self.assertIn("operation_control_receipt(", worker)
        self.assertIn("failure_details(failure)", worker)
        self.assertIn("homogeneous_ode_maxiters", worker)
        self.assertNotIn("maxiters=Inf", worker)
        self.assertNotIn("maxiters=Inf", complex_frequencies)
        self.assertIn("maxiters=ode_maxiters", worker)
        self.assertIn("maxiters=ode_maxiters", complex_frequencies)
        for resource in (
            "max_accepted_steps_per_homogeneous_leg",
            "max_rhs_evaluations_per_homogeneous_leg",
            "homogeneous_leg_wall_clock_seconds",
            "cooperative_request_deadline_seconds",
        ):
            self.assertIn(resource, worker)

    def test_package_worker_short_circuits_infeasible_and_unsuccessful_primary(self):
        worker = (
            Path(__file__).resolve().parents[1]
            / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")

        self.assertIn('progress_emit("root_readout_resource_infeasible"', worker)
        self.assertIn('"ROOT_READOUT_RESOURCE_INFEASIBLE"', worker)
        self.assertIn("minimum_remaining_determinant_count::Int=8", worker)
        self.assertIn(
            "diagnostic_newton_remaining_determinant_count(", worker
        )
        self.assertIn(
            "minimum_remaining_determinant_count=remaining_determinants",
            worker,
        )
        self.assertIn('"estimator" => "first-determinant-linear-lower-bound/v1"', worker)
        self.assertIn('"diagnostics_skipped_reason" => "PRIMARY_NOT_CONVERGED"', worker)
        primary_guard = worker.index("if !primary_converged")
        truncation = worker.index('"TRUNCATION"', primary_guard)
        self.assertLess(primary_guard, truncation)

    def test_package_worker_gates_promoted_roots_on_raw_newton_correction(self):
        """Promoted acceptance has binary64 parity while legacy code is isolated."""

        root = Path(__file__).resolve().parents[1]
        worker = (root / "src/windows_solver/data/julia/m02_worker.jl").read_text(
            encoding="utf-8"
        )

        self.assertIn('"root_correction_tolerance"', worker)
        self.assertIn('"newton_correction_estimate_abs"', worker)
        bounded_newton = worker[
            worker.index("function bounded_newton(") :
            worker.index("function finite_difference_noise_limit(")
        ]
        self.assertIn("binary64_parity", bounded_newton)
        self.assertRegex(
            bounded_newton,
            r"correction_abs\s*=\s*binary64_parity\s*\?\s*"
            r"magnitude\s*/\s*derivative_abs",
        )
        self.assertIn("correction_abs <= tolerance", worker)
        self.assertNotIn("best_residual <= tolerance", worker)
        self.assertRegex(
            bounded_newton,
            r"candidate_improves\s*=\s*binary64_parity\s*\?\s*"
            r"candidate_abs\s*<\s*magnitude",
        )
        primary = worker[
            worker.index("function solve_binary64_parity_primary(") :
            worker.index("function solve_fixed_root_diagnostic(")
        ]
        self.assertNotIn("derivative_lower_bound", primary)
        self.assertNotIn("residual_upper_bound", primary)
        self.assertIn("post_newton_determinant_count=0", primary)

    def test_package_worker_uses_stable_two_ended_determinants(self):
        """Catches singular horizon reconstruction and common-flow exterior roots."""

        worker = (
            Path(__file__).resolve().parents[1]
            / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")

        self.assertIn("Solutions.solve_scaled_horizon_basis_at_match(", worker)
        self.assertIn("Solutions.build_match_horizon_basis(", worker)
        self.assertIn("Solutions.evaluate_normalised_horizon_determinant(", worker)
        self.assertIn(
            "reflectivity = amplitude / "
            "(T(2) * im * spectral.p_horizon - amplitude)",
            worker,
        )
        self.assertNotIn("xout_match =", worker)
        self.assertIn(
            "xup_match = CF.reconstruct_factored_match_state(",
            worker,
        )
        self.assertIn(
            "Complex{T}[xup_match.X, xup_match.dX_drstar]",
            worker,
        )
        self.assertNotIn("perturbed_Xup_real_radius", worker)
        self.assertNotIn("chart_ratio < one(T)", worker)
        self.assertIn("chart_relative_margin > sqrt(eps(T))", worker)
        self.assertIn(
            '"Cinc" => progress_complex(coefficients.Cinc)', worker
        )
        self.assertIn(
            '"Cref" => progress_complex(coefficients.Cref)', worker
        )
        self.assertIn(
            '"matching_reconstruction_residual" => string(', worker
        )

    def test_package_worker_rejects_invalid_mechanism_and_support_contracts(self):
        worker = (
            Path(__file__).resolve().parents[1]
            / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")

        for mechanism in (
            "horizon-admittance",
            "exterior-fixed-r3",
            "exterior-light-ring",
            "exterior-throat-kappa",
            "exterior-alpha-zero",
            "exterior-alpha-half",
            "exterior-alpha-one",
        ):
            self.assertIn(f'"{mechanism}"', worker)
        self.assertIn("ALLOWED_MECHANISMS", worker)
        self.assertIn("unsupported mechanism_id", worker)
        self.assertIn("half_width > zero(T)", worker)
        self.assertIn("support lower bound is inconsistent", worker)
        self.assertIn("support upper bound is inconsistent", worker)

    def test_package_worker_rejects_an_unaccepted_newton_step(self):
        worker = (
            Path(__file__).resolve().parents[1]
            / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")

        self.assertNotIn('value -= parse(T, "0.125") * step', worker)
        self.assertIn("!accepted && break", worker)
        self.assertRegex(
            worker,
            r"determinant_is_better\(\s*T,\s*candidate_residual,\s*"
            r"best_evaluation\s*\)",
        )

    def test_error_model_identity_is_the_complete_v2_certificate(self):
        root = Path(__file__).resolve().parents[1]
        worker = (root / "src/windows_solver/data/julia/m02_worker.jl").read_text(
            encoding="utf-8"
        )
        engine = (root / "src/windows_solver/response_engine.py").read_text(
            encoding="utf-8"
        )
        identity = "verified-endpoint-control-equivalence-absolute-error/v2"
        self.assertIn(identity, worker)
        self.assertIn(identity, engine)
        # The superseded single-component identity must not linger: it named an
        # error model with only the endpoint term, so reusing it would let a
        # receipt claim control and equivalence evidence it never carried.
        self.assertNotIn("verified-endpoint-absolute-error/v1", engine)
        self.assertNotIn("verified-endpoint-absolute-error/v1", worker)

    def test_package_worker_cross_checks_frequency_derivatives(self):
        worker = (
            Path(__file__).resolve().parents[1]
            / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")

        for evidence in (
            "derivative_real_half",
            "derivative_real_base",
            "derivative_real_double",
            "derivative_imaginary",
            "derivative_uncertainty_abs",
            "derivative_lower_bound_abs",
        ):
            self.assertIn(evidence, worker)
        self.assertIn("correction_upper_bound", worker)
        self.assertIn(
            "correction_upper_bound = residual_upper_bound / "
            "derivative_lower_bound_abs",
            worker,
        )
        self.assertIn(
            "converged = newton_converged && "
            "correction_upper_bound <= tolerance",
            worker,
        )
        self.assertIn("real_step_convergent", worker)
        self.assertIn("complex_axis_consistent", worker)
        self.assertIn(
            "return root, residual, derivative_lower_bound_abs, converged",
            worker,
        )
        self.assertIn("derivative_control_completed", worker)
        for contract in (
            "struct DerivativeAuthentication{T<:AbstractFloat}",
            "propagated_error_abs::T",
            "step_disagreement_abs::T",
            "lower_bound_abs::T",
            "root_authentication",
            '"central_determinant_re"',
            '"residual_upper_bound_abs"',
            '"selected_step"',
            '"error_model_id"',
        ):
            self.assertIn(contract, worker)

    def test_ci_executes_the_worker_finite_difference_spec(self):
        workflow = (
            Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml"
        ).read_text(encoding="utf-8")
        package_tests = (
            Path(__file__).resolve().parents[1]
            / "src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/test/runtests.jl"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'joinpath(ENV["GSN_PROJECT"], "test", "runtests.jl")',
            workflow,
        )
        self.assertIn('include("real_inner_horizon_spec.jl")', package_tests)
        self.assertIn("m02_worker_finite_difference_spec.jl", workflow)
        self.assertIn("m02_worker_fixed_root_diagnostic_spec.jl", workflow)
        self.assertIn("m02_worker_request_contract_spec.jl", workflow)
        self.assertIn("leaf13_horizon_harness_spec.jl", workflow)

    def test_package_worker_confines_fine_steps_and_stores_only_endpoints(self):
        worker = (
            Path(__file__).resolve().parents[1]
            / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")

        self.assertIn("function radial_rhs!(du, state, parameters, radius)", worker)
        self.assertIn("vacuum_tail_dtmax = T(0.2)", worker)
        self.assertIn("fine_dtmax = min(", worker)
        self.assertIn("tstops=[stop_radius]", worker)
        self.assertIn("save_everystep=false", worker)
        self.assertIn("save_start=false", worker)
        self.assertIn("save_end=true", worker)
        self.assertIn("dense=false", worker)
        self.assertIn("solution.u[end]", worker)
        self.assertIn('ode_leg="$(ode_leg)_compact_support"', worker)
        self.assertIn('ode_leg="$(ode_leg)_vacuum_tail"', worker)
        self.assertIn('ode_leg="perturbed_Xin"', worker)

    def test_package_worker_avoids_unused_exterior_homogeneous_half_solutions(self):
        worker = (
            Path(__file__).resolve().parents[1]
            / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")

        for retired in (
            "solve_xin_at_match",
            "solve_xup_at_match",
            "homogeneous_rho_rhs!",
            "solve_homogeneous_endpoint",
            "xup_outer_to_match_raw",
            "solve_xup_scattering_coefficients",
        ):
            self.assertNotIn(f"function {retired}(", worker)
        self.assertIn("CF.prepare_factored_horizon_ingoing(", worker)
        self.assertIn("CF.prepare_factored_infinity_outgoing(", worker)
        self.assertIn("CF.solve_factored_xin_to_match(", worker)
        self.assertIn("CF.solve_factored_xup_to_match(", worker)

    def test_promoted_branch_authentication_uses_a_mode_specific_enclosure(self):
        root = Path(__file__).resolve().parents[1]
        worker = (root / "src/windows_solver/data/julia/m02_worker.jl").read_text(
            encoding="utf-8"
        )
        backend = (
            root / "src/windows_solver/julia_response_backend.py"
        ).read_text(encoding="utf-8")

        self.assertIn('"branch_enclosure_radius_abs"', worker)
        self.assertIn('"branch_enclosure_radius_abs"', backend)
        self.assertIn("_mode_specific_branch_enclosure_radius", backend)
        self.assertIn('"branch_authentication_contract_version" => 4', worker)

    def test_reserved_julia_stdout_event_is_forwarded_to_active_reporter(self):
        class Observer:
            def __init__(self):
                self.events = []

            def publish(self, event):
                self.events.append(event)

        observer = Observer()
        line = JULIA_PROGRESS_PREFIX + json.dumps({
            "schema": PROGRESS_SCHEMA,
            "kind": "newton_iteration_started",
            "context": {
                "phase": "PRIMARY",
                "newton_index": 1,
                "newton_limit": 16,
                "current_omega": {"real": "0.5", "imaginary": "-0.1"},
            },
            "payload": {
                "current_omega": {"real": "0.5", "imaginary": "-0.1"},
                "determinant_abs": "1e-20",
                "best_determinant_abs": "1e-20",
            },
        })
        with activate_progress(observer):
            self.assertTrue(_forward_julia_progress_line(line))

        self.assertEqual(len(observer.events), 1)
        self.assertIs(observer.events[0].kind, ProgressEventKind.NEWTON_ITERATION_STARTED)
        self.assertEqual(observer.events[0].context.phase, "PRIMARY")

    def test_reserved_horizon_chart_event_is_forwarded_to_active_reporter(self):
        class Observer:
            def __init__(self):
                self.events = []

            def publish(self, event):
                self.events.append(event)

        observer = Observer()
        line = JULIA_PROGRESS_PREFIX + json.dumps({
            "schema": PROGRESS_SCHEMA,
            "kind": "horizon_chart_evaluated",
            "context": {},
            "payload": {
                "Cinc": {"real": "1.0", "imaginary": "-0.5"},
                "Cref": {"real": "0.25", "imaginary": "0.125"},
                "horizon_frequency": {"real": "0.01", "imaginary": "-0.02"},
                "reflectivity": {"real": "0.03", "imaginary": "0.04"},
                "chart_denominator": {"real": "0.05", "imaginary": "0.06"},
                "Cinc_abs": "1.118033988749895",
                "Cref_abs": "0.2795084971874737",
                "horizon_frequency_abs": "0.0223606797749979",
                "reflectivity_abs": "0.05",
                "chart_denominator_abs": "0.07810249675906655",
                "chart_scale_abs": "0.04",
                "chart_condition_abs": "1.9525624189766637",
                "chart_condition_threshold": "1e-40",
                "chart_ratio": "0.1",
            },
        })
        with activate_progress(observer):
            self.assertTrue(_forward_julia_progress_line(line))

        self.assertEqual(len(observer.events), 1)
        self.assertIs(
            observer.events[0].kind,
            ProgressEventKind.HORIZON_CHART_EVALUATED,
        )
        self.assertEqual(observer.events[0].payload["chart_ratio"], "0.1")

    def test_reserved_derivative_control_event_is_forwarded_to_active_reporter(self):
        class Observer:
            def __init__(self):
                self.events = []

            def publish(self, event):
                self.events.append(event)

        observer = Observer()
        line = JULIA_PROGRESS_PREFIX + json.dumps({
            "schema": PROGRESS_SCHEMA,
            "kind": "derivative_control_completed",
            "context": {},
            "payload": {
                "derivative_real_half": {"real": "2.0", "imaginary": "0.1"},
                "derivative_real_base": {"real": "2.1", "imaginary": "0.1"},
                "derivative_real_double": {"real": "2.2", "imaginary": "0.1"},
                "derivative_imaginary": {"real": "2.0", "imaginary": "0.2"},
                "fine_step_difference_abs": "0.1",
                "coarse_step_difference_abs": "0.2",
                "complex_axis_difference_abs": "0.1",
                "real_step_convergent": True,
                "complex_axis_consistent": True,
                "derivative_uncertainty_abs": "0.2",
                "derivative_lower_bound_abs": "1.8024984394500787",
                "correction_upper_bound": "1e-18",
                "accepted": True,
            },
        })
        with activate_progress(observer):
            self.assertTrue(_forward_julia_progress_line(line))

        self.assertEqual(len(observer.events), 1)
        self.assertIs(
            observer.events[0].kind,
            ProgressEventKind.DERIVATIVE_CONTROL_COMPLETED,
        )
        self.assertIs(observer.events[0].payload["accepted"], True)

    def test_every_literal_worker_progress_event_is_registered_in_python(self):
        worker = (
            Path(__file__).resolve().parents[1]
            / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")
        worker_kinds = set(re.findall(r'progress_emit\("([^"]+)"', worker))
        python_kinds = {kind.value for kind in ProgressEventKind}

        self.assertEqual(worker_kinds - python_kinds, set())

    def test_every_literal_worker_progress_context_field_is_registered_in_python(
        self,
    ):
        worker = (
            Path(__file__).resolve().parents[1]
            / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")
        lines = worker.splitlines()
        assignment_pattern = re.compile(
            r"^\s*(context|[A-Za-z_][A-Za-z0-9_]*_context)\s*=\s*(.*)$"
        )
        context_blocks = []
        assigned_context_names = set()
        for index, line in enumerate(lines):
            match = assignment_pattern.match(line)
            if match is None:
                continue
            name, expression = match.groups()
            if not expression.startswith(("Dict", "merge(")):
                continue
            assigned_context_names.add(name)
            balance = expression.count("(") - expression.count(")")
            cursor = index
            while balance > 0:
                cursor += 1
                self.assertLess(cursor, len(lines), name)
                continuation = lines[cursor]
                expression += "\n" + continuation
                balance += continuation.count("(") - continuation.count(")")
            self.assertEqual(balance, 0, name)
            context_blocks.append(expression)

        # This deliberately bounded inventory prevents the audit itself from
        # silently overlooking a new worker context construction style.
        self.assertEqual(len(context_blocks), 7)
        self.assertEqual(
            assigned_context_names,
            {
                "context",
                "newton_context",
                "decision_context",
                "seed_context",
                "completion_context",
            },
        )
        scoped_context_names = set(
            re.findall(r"progress_scope\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)", worker)
        )
        explicit_context_names = set(
            re.findall(r"\bcontext\s*=\s*([a-z][A-Za-z0-9_]*)", worker)
        )
        self.assertEqual(
            (scoped_context_names | explicit_context_names)
            - assigned_context_names,
            set(),
        )

        worker_context_keys = {
            key
            for block in context_blocks
            for key in re.findall(r'"([^"]+)"\s*=>', block)
        }
        self.assertEqual(
            worker_context_keys,
            {
                "suboperation",
                "determinant_purpose",
                "determinant_index",
                "determinant_index_phase",
                "current_omega",
                "candidate_omega",
                "newton_index",
                "newton_limit",
                "phase",
                "root_phase",
                "seed_omega",
                "seed_kind",
                "fallback_used",
            },
        )
        python_context_keys = {field.name for field in fields(ProgressContext)}
        self.assertEqual(worker_context_keys - python_context_keys, set())

    def test_unknown_reserved_julia_progress_kind_is_fail_closed(self):
        line = JULIA_PROGRESS_PREFIX + json.dumps({
            "schema": PROGRESS_SCHEMA,
            "kind": "unregistered_worker_event",
            "context": {},
            "payload": {},
        })

        with self.assertRaises(JuliaResponseBackendError):
            _forward_julia_progress_line(line)

    def test_malformed_reserved_julia_progress_is_fail_closed(self):
        with self.assertRaises(JuliaResponseBackendError):
            _forward_julia_progress_line(JULIA_PROGRESS_PREFIX + "{")

    def test_streamed_worker_timeout_terminates_descendant_process_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            command = self._process_tree_command(directory)
            try:
                completed = _run_streamed_julia(
                    command, cwd=directory, env=os.environ, timeout=1
                )
                self.assertTrue(completed.timed_out)
                marker = directory / "child.marker"
                before = marker.stat().st_size
                time.sleep(0.2)
                self.assertEqual(marker.stat().st_size, before)
            finally:
                self._force_stop_process(directory / "child.pid")
                self._force_stop_process(directory / "parent.pid")

    def test_streamed_worker_keyboard_interrupt_terminates_descendant_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            command = self._process_tree_command(
                directory, emit_reserved_progress=True
            )
            try:
                with patch(
                    "windows_solver.julia_response_backend._forward_julia_progress_line",
                    side_effect=KeyboardInterrupt,
                ):
                    with self.assertRaises(KeyboardInterrupt):
                        _run_streamed_julia(
                            command, cwd=directory, env=os.environ, timeout=5
                        )
                marker = directory / "child.marker"
                before = marker.stat().st_size
                time.sleep(0.2)
                self.assertEqual(marker.stat().st_size, before)
            finally:
                self._force_stop_process(directory / "child.pid")
                self._force_stop_process(directory / "parent.pid")

    def test_promoted_backend_consumes_recorded_80_digit_ode_budget(self):
        job = _deep_job()
        adapter = FakeAdapter()
        backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity, adapter, 80
        )

        readout = backend.read_root(job, complex(0.001, -0.002))

        request = adapter.requests[0]
        self.assertEqual(request["precision_digits"], 80)
        self.assertEqual(request["working_precision_bits"], 298)
        self.assertEqual(
            request["policy"]["root_correction_tolerance"], "2e-11"
        )
        budget = synthetic_ode_error_budget(80)
        self.assertEqual(
            float(request["policy"]["ode_relative_tolerance"]),
            budget.homogeneous_reltol,
        )
        self.assertEqual(
            float(request["policy"]["ode_absolute_tolerance"]),
            budget.homogeneous_abstol,
        )
        self.assertEqual(request["policy"]["ode_error_budget"], budget.to_mapping())
        self.assertEqual(request["policy"]["frequency_step"], "1e-6")
        self.assertEqual(request["amplitude"], {
            "real": "0.001",
            "imaginary": "-0.002",
        })
        self.assertEqual(readout.omega, job.root.omega)
        self.assertEqual(readout.truncation_radius, 0.0)
        self.assertEqual(readout.resolution_radius, 0.0)
        self.assertIsNone(readout.seed_path_radius)
        self.assertEqual(
            set(readout.diagnostic_readouts),
            {"truncation", "resolution"},
        )
        self.assertEqual(
            request["policy"]["promoted_root_readout_policy"],
            "binary64-parity-primary-fixed-root-diagnostics-frequency-disk/v2",
        )
        self.assertTrue(readout.converged)
        self.assertEqual(backend.scientific_runtime["precision_digits"], 80)

    def test_promoted_request_binds_job_policy_and_refinement_identity(self):
        job = _deep_job()
        request = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            FakeAdapter(),
            120,
            refinement=1,
        )._request(job, 0.0j)

        self.assertEqual(request["job_id"], job.job_id)
        self.assertEqual(request["leaf_id"], job.leaf_id)
        self.assertEqual(request["role"], job.role)
        self.assertEqual(
            request["job_policy_sha256"], job.policy.identity_sha256
        )
        self.assertEqual(
            request["backend_identity_sha256"],
            job.backend_identity.identity_sha256,
        )
        self.assertEqual(request["refinement_level"], 1)

    def test_scientific_root_target_is_independent_of_storage_digits(self):
        """Catches coupling scientific solve targets to BigFloat storage digits.

        The previous table derived the 120-digit controls from the digit count,
        producing a 1e-102 root target -- 108 required reliable digits -- for a
        calculation whose established acceptance threshold is 2e-11. More stored digits do
        not make a QNM root more accurately defined; they buy guard precision.
        """

        job = _deep_job()
        adapter = FakeAdapter()

        def policy(digits: int, refinement: int) -> dict[str, object]:
            return JuliaPrecisionRootBackend(
                VettedNativeDeterminantKernel.identity,
                adapter,
                digits,
                refinement=refinement,
            )._request(job, 0.0j)["policy"]

        policy80, policy80_refined = policy(80, 0), policy(80, 1)
        policy120, policy120_refined = policy(120, 0), policy(120, 1)

        # The scientific target is a property of the physics, so it is the
        # same at both storage tiers.
        for base, refined in ((policy80, policy80_refined),
                              (policy120, policy120_refined)):
            self.assertEqual(base["root_correction_tolerance"], "2e-11")
            self.assertEqual(refined["root_correction_tolerance"], "2e-11")
        self.assertEqual(
            policy120["root_correction_tolerance"],
            policy80["root_correction_tolerance"],
        )
        self.assertEqual(
            policy120_refined["root_correction_tolerance"],
            policy80_refined["root_correction_tolerance"],
        )

        # Storage precision cannot silently alter local ODE targets. Both
        # requests consume their own recorded calibration-derived budgets.
        for field in (
            "homogeneous_ode_relative_tolerance",
            "coordinate_ode_relative_tolerance",
        ):
            self.assertEqual(float(policy120[field]), float(policy80[field]))

        # Each channel is exactly the reviewed allocation; no cross-channel
        # ordering is inferred beyond that calibration receipt.
        for candidate in (policy80, policy80_refined,
                          policy120, policy120_refined):
            budget = candidate["ode_error_budget"]
            self.assertEqual(
                float(candidate["coordinate_ode_relative_tolerance"]),
                budget["coordinate_reltol"],
            )
            self.assertEqual(
                float(candidate["homogeneous_ode_relative_tolerance"]),
                budget["homogeneous_reltol"],
            )

        # The derivative step stays in a bounded, calibratable range rather
        # than sitting at a digit-derived 1e-60.
        for candidate in (policy80, policy120):
            self.assertEqual(candidate["frequency_step"], "1e-6")
            step = float(candidate["frequency_step"])
            self.assertLess(float(candidate["frequency_step_minimum"]), step)
            self.assertGreater(float(candidate["frequency_step_maximum"]), step)

    def test_horizon_control_profile_is_explicitly_unmeasured(self):
        job = _deep_job()
        horizon = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            FakeAdapter(),
            80,
        )._request(job, 0.0j)["policy"]
        self.assertEqual(
            horizon["control_profile_label"],
            "provisional promoted control profile",
        )
        self.assertEqual(horizon["calibration_status"], "UNMEASURED")

    def test_promoted_nonconvergence_preserves_authenticated_branch(self):
        """Catches relabelling an in-radius Julia failure as branch loss."""

        class NonconvergedAdapter(FakeAdapter):
            def evaluate(self, request):
                response = super().evaluate(request)
                primary = dict(response["primary_acceptance"])
                primary.update({
                    "determinant_re": "3E-10",
                    "determinant_im": "0",
                    "correction_abs": "3E-11",
                    "accepted": False,
                })
                response.update({
                    "root_omega_re": request["omega"]["real"],
                    "root_omega_im": request["omega"]["imaginary"],
                    "root_residual_abs": "3E-10",
                    "root_displacement_abs": "0",
                    "primary_acceptance": primary,
                    "root_converged": False,
                    "truncation_radius_abs": None,
                    "resolution_radius_abs": None,
                    "diagnostic_roots": {},
                    "diagnostics_skipped_reason": "PRIMARY_NOT_CONVERGED",
                })
                return response

        job = _deep_job()
        backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            NonconvergedAdapter(),
            80,
        )

        readout = backend.read_root(job, 0.0j)

        self.assertFalse(readout.converged)
        self.assertEqual(readout.branch_id, job.root.branch_id)

    def test_promoted_branch_radius_violation_marks_nonmatching_identity(self):
        """Catches authenticating a Julia root outside the continuation radius."""

        class OutsideBranchAdapter(FakeAdapter):
            def evaluate(self, request):
                response = super().evaluate(request)
                root_real = self.shifted(request["omega"]["real"], "0.006")
                response.update({
                    "root_omega_re": root_real,
                    "root_omega_im": request["omega"]["imaginary"],
                    "root_displacement_abs": "0.006",
                    "root_converged": False,
                    "root_branch_continuation_valid": False,
                })
                for diagnostic in response["diagnostic_roots"].values():
                    diagnostic["root_omega_re"] = root_real
                    diagnostic["branch_authenticated"] = False
                    diagnostic["root_converged"] = False
                return response

        job = _deep_job()
        backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            OutsideBranchAdapter(),
            80,
        )

        readout = backend.read_root(job, 0.0j)

        self.assertFalse(readout.converged)
        self.assertEqual(readout.branch_id, "nonmatching-julia-continuation")

    def test_promoted_branch_decision_preserves_high_precision_boundary(self):
        """Catches binary64 rounding authenticating a just-outside Julia root."""

        class BoundaryAdapter(FakeAdapter):
            def __init__(self, displacement, branch_valid):
                super().__init__()
                self.displacement = displacement
                self.branch_valid = branch_valid

            def evaluate(self, request):
                response = super().evaluate(request)
                root_real = self.shifted(
                    request["omega"]["real"], self.displacement
                )
                response.update({
                    "root_omega_re": root_real,
                    "root_omega_im": request["omega"]["imaginary"],
                    "root_displacement_abs": self.displacement,
                    "root_converged": self.branch_valid,
                    "root_branch_continuation_valid": self.branch_valid,
                })
                for diagnostic in response["diagnostic_roots"].values():
                    diagnostic["root_omega_re"] = root_real
                    diagnostic["branch_authenticated"] = self.branch_valid
                    diagnostic["root_converged"] = self.branch_valid
                return response

        job = _deep_job()
        exact_radius = Decimal(
            format(_mode_specific_branch_enclosure_radius(job), ".17g")
        )
        outside_radius = exact_radius + Decimal("1e-28")
        exact = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            BoundaryAdapter(str(exact_radius), True),
            80,
        ).read_root(job, 0.0j)
        outside = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            BoundaryAdapter(str(outside_radius), False),
            80,
        ).read_root(job, 0.0j)

        class ComplexBoundaryAdapter(FakeAdapter):
            def evaluate(self, request):
                response = super().evaluate(request)
                radius = Decimal(request["policy"]["branch_enclosure_radius_abs"])
                real_delta = Decimal("0.6") * radius
                imaginary_delta = Decimal("0.8") * radius
                response.update({
                    "root_omega_re": str(
                        Decimal(request["omega"]["real"]) + real_delta
                    ),
                    "root_omega_im": str(
                        Decimal(request["omega"]["imaginary"]) + imaginary_delta
                    ),
                    "root_displacement_abs": str(radius),
                })
                for raw in response["diagnostic_roots"].values():
                    raw["root_omega_re"] = response["root_omega_re"]
                    raw["root_omega_im"] = response["root_omega_im"]
                    raw["displacement_from_primary_abs"] = "0"
                response["truncation_radius_abs"] = "0"
                response["resolution_radius_abs"] = "0"
                return response

        complex_boundary = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            ComplexBoundaryAdapter(),
            80,
        ).read_root(job, 0.0j)

        self.assertEqual(exact.branch_id, job.root.branch_id)
        self.assertEqual(complex_boundary.branch_id, job.root.branch_id)
        self.assertEqual(outside.branch_id, "nonmatching-julia-continuation")
        self.assertEqual(float(outside_radius), float(exact_radius))

    def test_promoted_branch_decision_rejects_worker_metric_disagreement(self):
        """Catches trusting a forged Julia branch Boolean over clear radius evidence."""

        class DisagreeingAdapter(FakeAdapter):
            def evaluate(self, request):
                response = super().evaluate(request)
                root_real = self.shifted(request["omega"]["real"], "0.006")
                response.update({
                    "root_omega_re": root_real,
                    "root_omega_im": request["omega"]["imaginary"],
                    "root_displacement_abs": "0.006",
                    "root_converged": False,
                    "root_branch_continuation_valid": True,
                })
                for diagnostic in response["diagnostic_roots"].values():
                    diagnostic["root_omega_re"] = root_real
                return response

        job = _deep_job()
        backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            DisagreeingAdapter(),
            80,
        )

        with self.assertRaisesRegex(
            JuliaResponseBackendError,
            "branch-continuation evidence is inconsistent",
        ):
            backend.read_root(job, 0.0j)

        class ForgedToleranceAdapter(DisagreeingAdapter):
            def evaluate(self, request):
                response = super().evaluate(request)
                response["branch_tolerance_abs"] = "0.006"
                return response

        forged_tolerance_backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            ForgedToleranceAdapter(),
            80,
        )
        with self.assertRaisesRegex(
            JuliaResponseBackendError,
            "PRIMARY response binding is inconsistent",
        ):
            forged_tolerance_backend.read_root(job, 0.0j)

        class ImpossibleConvergenceAdapter(DisagreeingAdapter):
            def evaluate(self, request):
                response = super().evaluate(request)
                response.update({
                    "root_converged": True,
                    "root_branch_continuation_valid": False,
                })
                return response

        impossible_backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            ImpossibleConvergenceAdapter(),
            80,
        )
        with self.assertRaisesRegex(
            JuliaResponseBackendError,
            "final root convergence evidence is inconsistent",
        ):
            impossible_backend.read_root(job, 0.0j)

        class FalseInsideAdapter(FakeAdapter):
            def evaluate(self, request):
                response = super().evaluate(request)
                response.update({
                    "root_converged": False,
                    "root_branch_continuation_valid": False,
                })
                return response

        false_inside_backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            FalseInsideAdapter(),
            80,
        )
        with self.assertRaisesRegex(
            JuliaResponseBackendError,
            "branch-continuation evidence is inconsistent",
        ):
            false_inside_backend.read_root(job, 0.0j)

    def test_promoted_backend_rejects_diagnostic_root_displacement_forgery(self):
        class ForgedDiagnosticAdapter(FakeAdapter):
            def evaluate(self, request):
                response = super().evaluate(request)
                response["diagnostic_roots"]["resolution"]["root_omega_re"] = (
                    self.shifted(request["omega"]["real"], "0.001")
                )
                return response

        job = _deep_job()
        backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            ForgedDiagnosticAdapter(),
            80,
        )

        with self.assertRaisesRegex(
            JuliaResponseBackendError,
            "fixed-root diagnostic binding is inconsistent",
        ):
            backend.read_root(job, 0.0j)

    def test_promoted_backend_keeps_diagnostic_certificate_fail_closed(self):
        class MissingErrorModelAdapter(FakeAdapter):
            def evaluate(self, request):
                response = super().evaluate(request)
                response["diagnostic_roots"]["resolution"][
                    "error_model_id"
                ] = None
                return response

        class AboveToleranceAdapter(FakeAdapter):
            def evaluate(self, request):
                response = super().evaluate(request)
                resolution = response["diagnostic_roots"]["resolution"]
                resolution.update({
                    "determinant_re": "3e-10",
                    "determinant_im": "0",
                    "root_residual_abs": "3e-10",
                    "determinant_error_abs": "1e-12",
                    "correction_abs": "3e-11",
                    "root_converged": True,
                })
                return response

        job = _deep_job()
        for adapter, message in (
            (
                MissingErrorModelAdapter(),
                "fixed-root diagnostic binding is inconsistent",
            ),
            (
                AboveToleranceAdapter(),
                "fixed-root diagnostic evidence is inconsistent",
            ),
        ):
            with self.subTest(adapter=type(adapter).__name__):
                backend = JuliaPrecisionRootBackend(
                    VettedNativeDeterminantKernel.identity,
                    adapter,
                    80,
                )
                with self.assertRaisesRegex(
                    JuliaResponseBackendError, message
                ):
                    backend.read_root(job, 0.0j)

    def test_fixed_root_diagnostics_preserve_telemetry_without_moving_root(self):
        """TRUNCATION retains correction telemetry but cannot move PRIMARY."""

        job = _deep_job()
        backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            FakeAdapter(),
            80,
        )

        def level(epsilon):
            return LadderLevel(
                epsilon=epsilon,
                real_plus=backend.read_root(job, complex(epsilon, 0.0)),
                real_minus=backend.read_root(job, complex(-epsilon, 0.0)),
                imaginary_plus=backend.read_root(job, complex(0.0, epsilon)),
                imaginary_minus=backend.read_root(job, complex(0.0, -epsilon)),
            )

        levels = (level(2.0e-3), level(1.0e-3))
        channel = _diagnostic_response_channel(
            levels,
            "truncation",
            primary_center=0.0j,
            primary_radius=0.0,
        )

        for ladder_level in levels:
            for readout in (
                ladder_level.real_plus,
                ladder_level.real_minus,
                ladder_level.imaginary_plus,
                ladder_level.imaginary_minus,
            ):
                self.assertEqual(
                    readout.diagnostic_readouts[
                        "truncation"
                    ].omega_delta_from_primary,
                    0.0j,
                )
        self.assertGreater(channel, 0.0)

    def test_promoted_backend_forwards_optional_primary_predictor(self):
        """Catches promoted precision reverting to background-only PRIMARY seeds."""

        job = _deep_job()
        adapter = FakeAdapter()
        backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity, adapter, 80
        )
        predictor = job.root.omega + complex(1.0e-5, -2.0e-5)

        backend.read_root(job, 0.001 + 0.0j, primary_predictor=predictor)

        self.assertEqual(adapter.requests[0]["primary_predictor"], {
            "real": format(predictor.real, ".17g"),
            "imaginary": format(predictor.imag, ".17g"),
        })

    def test_promoted_backend_labels_cross_spin_predictor(self):
        job = _deep_job()
        adapter = FakeAdapter()
        backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity, adapter, 80
        )
        predictor = job.root.omega + complex(1.0e-5, -2.0e-5)

        backend.read_root_with_predictor_kind(
            job,
            0.001 + 0.0j,
            predictor,
            "SPIN_CONTINUATION",
        )

        self.assertEqual(
            adapter.requests[0]["primary_predictor_kind"],
            "SPIN_CONTINUATION",
        )

    def test_refinement_preserves_recorded_ode_budget_and_refines_discrete_controls(self):
        job = _deep_job()
        adapter = FakeAdapter()
        backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity, adapter, 80, refinement=1
        )

        backend.read_root(job, 0.0j)

        policy = adapter.requests[0]["policy"]
        self.assertEqual(
            float(policy["ode_relative_tolerance"]),
            synthetic_ode_error_budget(80).homogeneous_reltol,
        )
        self.assertEqual(policy["endpoint_series_order"], 36)
        self.assertEqual(policy["support_subinterval_count"], 512)
        self.assertEqual(policy["angular_pad"], 26)

    def test_unsuccessful_primary_omits_diagnostic_science(self):
        class PrimaryNotConvergedAdapter(FakeAdapter):
            def evaluate(self, request):
                response = super().evaluate(request)
                primary = dict(response["primary_acceptance"])
                primary.update({
                    "determinant_re": "3E-10",
                    "determinant_im": "0",
                    "correction_abs": "3E-11",
                    "accepted": False,
                })
                response.update({
                    "root_residual_abs": "3E-10",
                    "primary_acceptance": primary,
                    "root_converged": False,
                    "truncation_radius_abs": None,
                    "resolution_radius_abs": None,
                    "seed_path_radius_abs": None,
                    "diagnostic_roots": {},
                    "diagnostics_skipped_reason": "PRIMARY_NOT_CONVERGED",
                })
                return response

        job = _deep_job()
        backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity,
            PrimaryNotConvergedAdapter(),
            80,
        )

        readout = backend.read_root(job, 0.0j)

        self.assertFalse(readout.converged)
        self.assertEqual(readout.diagnostic_readouts, {})
        self.assertIsNone(readout.truncation_radius)
        self.assertIsNone(readout.resolution_radius)
        self.assertIsNone(readout.seed_path_radius)
        self.assertEqual(
            readout.diagnostics_skipped_reason, "PRIMARY_NOT_CONVERGED"
        )

    def test_execution_resource_policy_changes_request_digest_not_scientific_identity(self):
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        leaf = next(
            item
            for item in plan.leaves
            if (
                item.role == "primary"
                and item.leaf.mode_label == "221"
                and item.job.spin == 0.95
                and item.mechanism_id == "horizon-admittance"
            )
        )
        job = leaf.job
        solved_leaf_identity = scientific_computation_identity_sha256(plan, leaf)
        backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity, FakeAdapter(), 80
        )
        scientific_identity = (
            job.root.identity_sha256,
            job.policy.identity_sha256,
            job.backend_identity.identity_sha256,
            job.job_id,
        )

        with patch.dict(
            os.environ,
            {"KERR_QNM_JULIA_ODE_MAX_RHS_EVALUATIONS": "2000000"},
            clear=False,
        ):
            first = backend._request(job, 0.0j)
        with patch.dict(
            os.environ,
            {"KERR_QNM_JULIA_ODE_MAX_RHS_EVALUATIONS": "3000000"},
            clear=False,
        ):
            second = backend._request(job, 0.0j)

        policy = first["execution_resource"]
        self.assertEqual(
            set(policy),
            {
                "schema",
                "version",
                "worker_request_wall_clock_seconds",
                "cooperative_request_deadline_seconds",
                "homogeneous_ode_maxiters",
                "max_accepted_steps_per_homogeneous_leg",
                "max_rhs_evaluations_per_homogeneous_leg",
                "coordinate_stall_rhs_threshold",
                "coordinate_stall_minimum_span_fraction",
                "coordinate_stall_minimum_step_fraction",
                "homogeneous_leg_wall_clock_seconds",
                "sha256",
            },
        )
        self.assertEqual(policy["worker_request_wall_clock_seconds"], 7200)
        self.assertLess(
            policy["cooperative_request_deadline_seconds"],
            policy["worker_request_wall_clock_seconds"],
        )
        material = {key: value for key, value in policy.items() if key != "sha256"}
        self.assertEqual(
            policy["sha256"], hashlib.sha256(canonical_json_bytes(material)).hexdigest()
        )
        self.assertNotEqual(
            hashlib.sha256(canonical_json_bytes(first)).hexdigest(),
            hashlib.sha256(canonical_json_bytes(second)).hexdigest(),
        )
        self.assertEqual(
            scientific_identity,
            (
                job.root.identity_sha256,
                job.policy.identity_sha256,
                job.backend_identity.identity_sha256,
                job.job_id,
            ),
        )
        self.assertEqual(
            solved_leaf_identity,
            scientific_computation_identity_sha256(plan, leaf),
        )
        # The backend identity already includes the Python runtime fingerprint,
        # so its exact digest legitimately differs between supported Python
        # patch releases.  The operational policy must remain absent from the
        # runtime-bound scientific identity on every platform.
        self.assertNotIn(
            b"execution_resource",
            canonical_json_bytes({
                "leaf_id": leaf.leaf_id,
                "response_job": leaf.job.to_mapping(),
                "precision_factory_identity": (
                    plan.precision_factory_identity.to_mapping()
                ),
            }),
        )
        self.assertEqual(
            leaf.leaf_id,
            "b-prime-leaf-28b8e2f139fae4ebbb839320057a127429f7a01a3cc2cac60b526815ad0e7252",
        )
        self.assertEqual(
            job.policy.identity_sha256,
            "2d7cee336c6126a11bccd652ee35e73de60837e9418476849b9026cd27bf6171",
        )

    def test_outer_timeout_override_keeps_an_inner_cooperative_deadline(self):
        backend = JuliaPrecisionRootBackend(
            VettedNativeDeterminantKernel.identity, FakeAdapter(), 80
        )
        environment = {"KERR_QNM_JULIA_REQUEST_TIMEOUT_SECONDS": "60"}

        with patch.dict(os.environ, environment, clear=True):
            policy = backend._request(_deep_job(), 0.0j)["execution_resource"]

        self.assertEqual(policy["worker_request_wall_clock_seconds"], 60)
        self.assertEqual(policy["cooperative_request_deadline_seconds"], 57)

    def test_runtime_adapter_authenticates_receipt_worker_and_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / ".runtime"
            project = runtime / "m02-julia-project"
            depot = runtime / "julia-depot"
            project.mkdir(parents=True)
            depot.mkdir()
            julia = runtime / "julia.exe"
            manifest = project / "Manifest.toml"
            project_file = project / "Project.toml"
            worker = root / "m02_worker.jl"
            for path, data in (
                (julia, b"julia"),
                (manifest, b"manifest"),
                (project_file, b"project"),
                (worker, b"worker"),
            ):
                path.write_bytes(data)
            receipt = {
                "policy_sha256": "f" * 64,
                "julia_runtime": {
                    "requested": True,
                    "version": "1.10.11",
                    "executable": str(julia),
                    "executable_sha256": hashlib.sha256(julia.read_bytes()).hexdigest(),
                    "archive": str(runtime / "julia.zip"),
                    "archive_sha256": "1" * 64,
                    "sources": [],
                    "depot": str(depot),
                    "project": str(project),
                    "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
                    "worker_sha256": hashlib.sha256(worker.read_bytes()).hexdigest(),
                },
            }
            (runtime / "python-runtime.json").write_bytes(canonical_json_bytes(receipt))

            module_worker = (
                Path(__file__).resolve().parents[1]
                / "src/windows_solver/data/julia/m02_worker.jl"
            )
            declared = receipt["julia_runtime"]
            declared["worker_sha256"] = hashlib.sha256(
                module_worker.read_bytes()
            ).hexdigest()
            (runtime / "python-runtime.json").write_bytes(canonical_json_bytes(receipt))

            adapter = JuliaResponseAdapter.from_runtime_receipt(
                runtime_root=runtime
            )
            self.assertEqual(adapter.julia_executable, julia.resolve())
            self.assertEqual(adapter.julia_project, project.resolve())

            manifest.write_bytes(b"changed")
            with self.assertRaisesRegex(
                JuliaResponseBackendError,
                "manifest receipt digest",
            ):
                JuliaResponseAdapter.from_runtime_receipt(runtime_root=runtime)

    def test_subprocess_response_is_bound_to_exact_request_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("julia.exe", "Project.toml", "Manifest.toml", "worker.jl"):
                (root / name).write_text(name, encoding="ascii")
            depot = root / "depot"
            depot.mkdir()
            provenance = {}

            def runner(command, **kwargs):
                request = json.loads(Path(command[-2]).read_text(encoding="utf-8"))
                Path(command[-1]).write_bytes(canonical_json_bytes({
                    "status": "ok",
                    "request_sha256": "0" * 64,
                }))
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            adapter = JuliaResponseAdapter(
                root / "julia.exe",
                root,
                depot,
                root / "worker.jl",
                provenance,
                runner,
            )
            with self.assertRaisesRegex(JuliaResponseBackendError, "request digest"):
                adapter.evaluate({"schema_version": 1})

    def test_nonzero_worker_exit_exposes_structured_error_receipt(self):
        """Catches discarding the worker's own exit/error receipt on failure."""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("julia.exe", "Project.toml", "Manifest.toml", "worker.jl"):
                (root / name).write_text(name, encoding="ascii")
            depot = root / "depot"
            depot.mkdir()

            def runner(command, **kwargs):
                Path(command[-1]).write_bytes(canonical_json_bytes({
                    "schema_version": 1,
                    "status": "error",
                    "error_type": "ErrorException",
                    "message": "r-from-rho failed",
                }))
                return SimpleNamespace(
                    returncode=21,
                    stdout="",
                    stderr="synthetic Julia traceback",
                )

            adapter = JuliaResponseAdapter(
                root / "julia.exe",
                root,
                depot,
                root / "worker.jl",
                {},
                runner,
            )
            with self.assertRaisesRegex(JuliaResponseBackendError, "code 21") as raised:
                adapter.evaluate({"schema_version": 1})

        self.assertEqual(raised.exception.worker_failure, {
            "worker_exit_code": 21,
            "worker_timed_out": False,
            "worker_stderr_tail": "synthetic Julia traceback",
            "worker_error_type": "ErrorException",
            "worker_error_message": "r-from-rho failed",
        })

    def test_failed_preflight_receipt_is_bound_to_canonical_request(self):
        job = _deep_job()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("julia.exe", "Project.toml", "Manifest.toml", "worker.jl"):
                (root / name).write_text(name, encoding="ascii")
            depot = root / "depot"
            depot.mkdir()

            def runner(command, **kwargs):
                request = json.loads(
                    Path(command[-2]).read_text(encoding="utf-8")
                )
                Path(command[-1]).write_bytes(canonical_json_bytes({
                    "schema_version": 1,
                    "status": "error",
                    "error_type": "AsymptoticPrecisionError",
                    "message": "preflight rejected 80 digits",
                    "failure": _worker_control_receipt(
                        request,
                        "INSUFFICIENT_ASYMPTOTIC_PRECISION",
                    ),
                }))
                return SimpleNamespace(returncode=21, stdout="", stderr="")

            adapter = JuliaResponseAdapter(
                root / "julia.exe", root, depot, root / "worker.jl", {}, runner
            )
            request = JuliaPrecisionRootBackend(
                job.backend_identity, adapter, 80,
                ode_error_budget=synthetic_ode_error_budget(80),
            )._request(job, 0.0j)
            with self.assertRaises(JuliaResponseBackendError) as raised:
                adapter.evaluate(request)

        failure = raised.exception.worker_failure["failure"]
        self.assertEqual(
            failure["canonical_request_binding"]["request_sha256"],
            hashlib.sha256(canonical_json_bytes(request)).hexdigest(),
        )
        self.assertEqual(
            dict(raised.exception.control_receipt.canonical_request),
            request,
        )

    def test_failed_preflight_worker_cannot_substitute_valid_request_digest(self):
        job = _deep_job()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("julia.exe", "Project.toml", "Manifest.toml", "worker.jl"):
                (root / name).write_text(name, encoding="ascii")
            depot = root / "depot"
            depot.mkdir()

            def runner(command, **kwargs):
                request = json.loads(
                    Path(command[-2]).read_text(encoding="utf-8")
                )
                Path(command[-1]).write_bytes(canonical_json_bytes({
                    "schema_version": 1,
                    "status": "error",
                    "error_type": "AsymptoticPrecisionError",
                    "message": "forged request digest",
                    "failure": _worker_control_receipt(
                        request,
                        "INSUFFICIENT_ASYMPTOTIC_PRECISION",
                        request_sha256="0" * 64,
                    ),
                }))
                return SimpleNamespace(returncode=21, stdout="", stderr="")

            adapter = JuliaResponseAdapter(
                root / "julia.exe", root, depot, root / "worker.jl", {}, runner
            )
            request = JuliaPrecisionRootBackend(
                job.backend_identity, adapter, 80,
                ode_error_budget=synthetic_ode_error_budget(80),
            )._request(job, 0.0j)
            with self.assertRaisesRegex(
                JuliaResponseBackendError, "request identity mismatch"
            ) as raised:
                adapter.evaluate(request)

        self.assertNotIn("failure", raised.exception.worker_failure)

    def test_ode_resource_limit_receipt_is_a_typed_worker_failure(self):
        ode_snapshot = {
            "ode_solve_id": 17,
            "ode_leg": "Xup_outer_to_match",
            "ode_stats_scope": "leg",
            "ode_retcode": "MaxIters",
            "ode_rhs_evaluations": 9000001,
            "ode_accepted_steps": 120,
            "ode_rejected_steps": 9999880,
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("julia.exe", "Project.toml", "Manifest.toml", "worker.jl"):
                (root / name).write_text(name, encoding="ascii")
            depot = root / "depot"
            depot.mkdir()

            def runner(command, **kwargs):
                request = json.loads(
                    Path(command[-2]).read_text(encoding="utf-8")
                )
                Path(command[-1]).write_bytes(canonical_json_bytes({
                    "schema_version": 1,
                    "status": "error",
                    "error_type": "ODEResourceLimit",
                    "message": "Xup exceeded the existing solver iteration limit",
                    "failure": {
                        "failure_code": "ODE_RESOURCE_LIMIT",
                        "failure_class": "CONTROL",
                        "limit_kind": "ode_solver_iterations",
                        "ode_snapshot": ode_snapshot,
                        "execution_resource_policy": request[
                            "execution_resource"
                        ],
                    },
                }))
                return SimpleNamespace(returncode=21, stdout="", stderr="")

            adapter = JuliaResponseAdapter(
                root / "julia.exe", root, depot, root / "worker.jl", {}, runner
            )
            with self.assertRaises(JuliaResponseBackendError) as raised:
                adapter.evaluate({"schema_version": 1})

        self.assertEqual(type(raised.exception).__name__, "JuliaODEResourceLimitError")
        self.assertEqual(
            raised.exception.worker_failure["failure"]["failure_code"],
            "ODE_RESOURCE_LIMIT",
        )
        self.assertEqual(
            raised.exception.worker_failure["failure"]["ode_snapshot"],
            ode_snapshot,
        )

    def test_root_readout_feasibility_receipt_is_a_typed_worker_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("julia.exe", "Project.toml", "Manifest.toml", "worker.jl"):
                (root / name).write_text(name, encoding="ascii")
            depot = root / "depot"
            depot.mkdir()

            def runner(command, **kwargs):
                request = json.loads(
                    Path(command[-2]).read_text(encoding="utf-8")
                )
                Path(command[-1]).write_bytes(canonical_json_bytes({
                    "schema_version": 1,
                    "status": "error",
                    "error_type": "RootReadoutResourceLimit",
                    "message": "mandatory determinant work cannot fit",
                    "failure": {
                        "failure_code": "ROOT_READOUT_RESOURCE_INFEASIBLE",
                        "failure_class": "CONTROL",
                        "retryable": True,
                        "precision_digits": 80,
                        "root_phase": "PRIMARY",
                        "newton_index": 1,
                        "determinant_index": 1,
                        "measured_determinant_seconds": 1800.0,
                        "minimum_remaining_determinant_count": 8,
                        "remaining_wall_time_seconds": 5000.0,
                        "estimator": "first-determinant-linear-lower-bound/v1",
                        "execution_resource_policy": request["execution_resource"],
                    },
                }))
                return SimpleNamespace(returncode=21, stdout="", stderr="")

            adapter = JuliaResponseAdapter(
                root / "julia.exe", root, depot, root / "worker.jl", {}, runner
            )
            with self.assertRaises(JuliaResponseBackendError) as raised:
                adapter.evaluate({"schema_version": 1})

        self.assertEqual(
            type(raised.exception).__name__,
            "JuliaRootReadoutResourceLimitError",
        )
        self.assertEqual(
            raised.exception.worker_failure["failure"]["failure_code"],
            "ROOT_READOUT_RESOURCE_INFEASIBLE",
        )

    def test_control_receipt_resource_policy_mismatch_is_fatal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("julia.exe", "Project.toml", "Manifest.toml", "worker.jl"):
                (root / name).write_text(name, encoding="ascii")
            depot = root / "depot"
            depot.mkdir()

            def runner(command, **kwargs):
                request = json.loads(
                    Path(command[-2]).read_text(encoding="utf-8")
                )
                forged_identity = {
                    "schema": request["execution_resource"]["schema"],
                    "version": request["execution_resource"]["version"],
                    "sha256": "0" * 64,
                }
                Path(command[-1]).write_bytes(canonical_json_bytes({
                    "schema_version": 1,
                    "status": "error",
                    "error_type": "ODEResourceLimit",
                    "message": "forged resource identity",
                    "failure": {
                        "failure_code": "ODE_RESOURCE_LIMIT",
                        "failure_class": "CONTROL",
                        "retryable": True,
                        "precision_digits": 80,
                        "execution_resource_policy": forged_identity,
                    },
                }))
                return SimpleNamespace(returncode=21, stdout="", stderr="bounded")

            adapter = JuliaResponseAdapter(
                root / "julia.exe", root, depot, root / "worker.jl", {}, runner
            )
            with self.assertRaisesRegex(
                JuliaResponseBackendError,
                "execution-resource policy identity mismatch",
            ) as raised:
                adapter.evaluate({"schema_version": 1})

        self.assertIs(type(raised.exception), JuliaResponseBackendError)
        self.assertNotIn("failure", raised.exception.worker_failure)
        self.assertEqual(
            raised.exception.worker_failure["worker_error_type"],
            "ExecutionResourcePolicyIdentityError",
        )

    def test_worker_timeout_is_explicit_in_failure_diagnostic(self):
        """Catches a killed worker being reported as an opaque nonzero exit."""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("julia.exe", "Project.toml", "Manifest.toml", "worker.jl"):
                (root / name).write_text(name, encoding="ascii")
            depot = root / "depot"
            depot.mkdir()

            def runner(command, **kwargs):
                return SimpleNamespace(
                    returncode=-9,
                    stdout="",
                    stderr="Julia worker timed out after 60 seconds\n",
                    timed_out=True,
                    last_progress_event_validated=True,
                    last_progress_event={
                        "schema": PROGRESS_SCHEMA,
                        "kind": "ode_solve_progress",
                        "context": {
                            "readout_index": 1,
                            "readout_role": "baseline",
                            "phase": "PRIMARY",
                            "newton_index": 1,
                            "determinant_index_leaf": 3,
                            "determinant_index_phase": 3,
                            "determinant_purpose": "derivative -h",
                        },
                        "payload": {
                            "ode_leg": "Xup_match_to_inner",
                            "elapsed_seconds": 1900.0,
                            "request_elapsed_seconds": 5271.5,
                            "ode_accepted_steps": 982000,
                            "ode_rejected_steps": 0,
                            "ode_rhs_evaluations": 1960000,
                        },
                    },
                )

            adapter = JuliaResponseAdapter(
                root / "julia.exe",
                root,
                depot,
                root / "worker.jl",
                {},
                runner,
            )
            with self.assertRaisesRegex(JuliaResponseBackendError, "timed out") as raised:
                adapter.evaluate({"schema_version": 1})

        receipt = raised.exception.worker_failure
        self.assertEqual(receipt["worker_exit_code"], -9)
        self.assertIs(receipt["worker_timed_out"], True)
        self.assertEqual(
            receipt["worker_stderr_tail"],
            "Julia worker timed out after 60 seconds\n",
        )
        self.assertEqual(receipt["failure"]["failure_code"], "WORKER_TIMEOUT")
        self.assertEqual(receipt["failure"]["failure_class"], "CONTROL")
        self.assertIs(receipt["failure"]["retryable"], True)
        self.assertEqual(receipt["failure"]["root_phase"], "PRIMARY")
        self.assertEqual(receipt["failure"]["determinant_index"], 3)
        self.assertEqual(receipt["failure"]["elapsed_request_seconds"], 5271.5)
        self.assertEqual(
            receipt["failure"]["ode_leg"], "Xup_match_to_inner"
        )
        self.assertEqual(
            receipt["failure"]["ode_snapshot"]["ode_rhs_evaluations"],
            1960000,
        )
        policy = receipt["failure"]["execution_resource_policy"]
        self.assertEqual(
            policy["schema"], "windows-solver.execution-resource-policy/1"
        )
        self.assertEqual(len(policy["sha256"]), 64)

    def test_campaign_failure_status_persists_worker_diagnostic(self):
        """Catches final status overwriting the failed worker's exact diagnostic."""

        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80, 120)),
        )
        leaf = next(item for item in plan.leaves if item.role == "primary")
        selection = build_campaign_selection(
            plan,
            role="primary",
            leaf_ids=(leaf.leaf_id,),
        )
        failure = JuliaResponseBackendError("M02 Julia worker failed with code 21")
        failure.worker_failure = {
            "worker_exit_code": 21,
            "worker_timed_out": False,
            "worker_stderr_tail": "synthetic Julia traceback",
            "worker_error_type": "ErrorException",
            "worker_error_message": "r-from-rho failed",
        }

        class FailingBackend:
            identity = plan.backend_identity
            precision_capabilities = plan.precision_capabilities

            def execute_stage(self, selected_leaf, digits):
                raise failure

        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "checkpoint.json"
            reporter = CampaignProgressReporter("normal", checkpoint, io.StringIO())
            with activate_progress(reporter):
                with self.assertRaisesRegex(JuliaResponseBackendError, "code 21"):
                    run_campaign_selection(
                        plan,
                        selection,
                        FailingBackend(),
                        checkpoint,
                        resume=False,
                    )
            status = json.loads(
                Path(f"{checkpoint}.status.json").read_text(encoding="utf-8")
            )

        self.assertEqual(status["kind"], "campaign_failed")
        self.assertEqual(status["payload"]["worker_failure"], failure.worker_failure)

    def test_runtime_receipt_uses_persistent_worker_and_juliaup_channel(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            project = runtime / "m02-environments" / "m02-contract" / "project"
            depot = runtime / "julia-depot" / "m02-contract"
            source_root = runtime / "scientific-sources" / "m02-contract"
            project.mkdir(parents=True)
            depot.mkdir(parents=True)
            source_root.mkdir(parents=True)
            julia = root / "julia.exe"
            worker = source_root / "m02_worker.jl"
            for path, data in (
                (julia, b"juliaup-shim"),
                (project / "Project.toml", b"project"),
                (project / "Manifest.toml", b"manifest"),
                (worker, b"persistent worker"),
            ):
                path.write_bytes(data)
            receipt = {
                "policy_sha256": "f" * 64,
                "julia_runtime": {
                    "requested": True,
                    "version": "1.10.11",
                    "executable": str(julia),
                    "executable_sha256": hashlib.sha256(julia.read_bytes()).hexdigest(),
                    "arguments": ["+1.10.11"],
                    "worker": str(worker),
                    "worker_sha256": hashlib.sha256(worker.read_bytes()).hexdigest(),
                    "depot": str(depot),
                    "project": str(project),
                    "manifest_sha256": hashlib.sha256(
                        (project / "Manifest.toml").read_bytes()
                    ).hexdigest(),
                    "sources": [],
                },
            }
            (runtime / "python-runtime.json").write_bytes(
                canonical_json_bytes(receipt)
            )
            commands: list[tuple[str, ...]] = []

            def runner(command, **kwargs):
                commands.append(tuple(command))
                request = json.loads(
                    Path(command[-2]).read_text(encoding="utf-8")
                )
                Path(command[-1]).write_bytes(
                    canonical_json_bytes(
                        {
                            "status": "ok",
                            "request_sha256": request["request_sha256"],
                        }
                    )
                )
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            adapter = JuliaResponseAdapter.from_runtime_receipt(
                runtime_root=runtime,
                runner=runner,
            )
            adapter.evaluate({"schema_version": 1})
            self.assertTrue(Path(commands[0][0]).samefile(julia))
            self.assertEqual(commands[0][1:3], ("+1.10.11", "--startup-file=no"))
            self.assertTrue(Path(commands[0][-3]).samefile(worker))


if __name__ == "__main__":
    unittest.main()
