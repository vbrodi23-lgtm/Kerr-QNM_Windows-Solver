from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests.test_linear_response_batches import _produced_stage_outcome

from windows_solver.contracts import canonical_json_bytes
from windows_solver.gsn_cache_producer import GeneratedGsnCache, GsnParameterPair
from windows_solver.julia_response_backend import (
    JuliaNumericalControlError,
    JuliaPrecisionRootBackend,
)
from windows_solver.operation_control import (
    JULIA_PRODUCER_RETRYABILITY_BASIS,
    JULIA_WORKER_ORIGIN,
    build_operation_control_receipt,
    execution_identity_from_request,
    validate_operation_control_receipt,
)
from windows_solver.response_batches import (
    B_PRIME_RELEASE_DOMAIN,
    CampaignExecutionAttempt,
    NativeCampaignStageBackend,
    PrecisionCapabilities,
    build_campaign_selection,
    build_campaign_plan,
    _execution_attempt_from_failure,
    run_campaign_selection,
    synthetic_stage_signed_error_channels,
    validate_campaign_checkpoint,
)
from windows_solver.response_engine import (
    ComponentResult,
    ComponentStatus,
    DiagnosticRootReadout,
    NativeDeterminantAdapter,
    NumericalPolicy,
    RootReadout,
    VettedNativeDeterminantKernel,
    ERROR_CHANNELS,
    run_promoted_horizon_component,
)
from tests.fixtures import (
    control_failure_stage,
    synthetic_ode_error_budget,
    valid_control_failure_diagnostics,
)


def _lineage(job):
    return {
        "leaf_id": job.leaf_id,
        "root_reference_id": job.root.root_reference_id,
        "root_identity_sha256": job.root.identity_sha256,
        "policy_sha256": job.policy.identity_sha256,
        "backend_identity_sha256": job.backend_identity.identity_sha256,
        "equation_id": job.equation_id,
        "sampling_coordinate": job.sampling_coordinate.to_mapping(),
        "source_root_mapping": None,
    }


def _result(job, response: complex, *, radius: float = 1.0e-7):
    baseline = RootReadout(
        omega=job.root.omega,
        determinant_residual_abs=1.0e-15,
        determinant_derivative_abs=2.0,
        converged=True,
        root_reference_id=job.root.root_reference_id,
        branch_id=job.root.branch_id,
        equation_id=job.equation_id,
        truncation_radius=radius,
        resolution_radius=radius,
        seed_path_radius=radius,
    )
    return ComponentResult(
        job_id=job.job_id,
        leaf_id=job.leaf_id,
        mechanism_id=job.mechanism_id,
        status=ComponentStatus.CONVERGED,
        convergence_basis="ORDER_RESOLVED",
        response=response,
        signed_root_crosscheck=response,
        closed_form_response=None,
        error_channels={
            "signed-root": radius,
            "truncation": radius,
            "resolution": radius,
            "seed-path": radius,
            "axis": radius,
            "amplitude": radius,
        },
        baseline=baseline,
        levels=(),
        lineage=_lineage(job),
    )


def _failed_preflight_attempt(leaf, *, primary_predictor=None):
    request_binding = JuliaPrecisionRootBackend(
        leaf.job.backend_identity,
        object(),
        80,
        ode_error_budget=synthetic_ode_error_budget(80),
    )._request(
        leaf.job,
        0.0j,
        primary_predictor=primary_predictor,
    )
    failure = {
        "failure_code": "INSUFFICIENT_ASYMPTOTIC_PRECISION",
        "failure_class": "CONTROL",
        "retryable": True,
        # Where the failure happened, not only what failed.
        "stage": "asymptotic-preflight",
        "precision_digits": 80,
        "request_sha256": hashlib.sha256(
            canonical_json_bytes(request_binding)
        ).hexdigest(),
        "request_binding": request_binding,
        "job_id": leaf.job.job_id,
        "leaf_id": leaf.leaf_id,
        "role": leaf.role,
        "job_policy_sha256": leaf.job.policy.identity_sha256,
        "backend_identity_sha256": leaf.job.backend_identity.identity_sha256,
        "refinement_level": 0,
        "execution_resource_policy": {
            name: request_binding["execution_resource"][name]
            for name in ("schema", "version", "sha256")
        },
        "diagnostics": {
            "reason": "INSUFFICIENT_ASYMPTOTIC_PRECISION",
            "precision_bits": request_binding["working_precision_bits"],
            "predicted_reliable_digits": "11",
            "required_reliable_digits": "24",
            "maximum_series_digits_lost": "41",
            "maximum_recurrence_digits_lost": "39",
            "asymptotic_preflight_avoided_ode": True,
            "asymptotic_preflight_reason": (
                "INSUFFICIENT_ASYMPTOTIC_PRECISION"
            ),
            "factored_homogeneous_rhs_evaluations": 0,
            "avoided_ode_scope": "factored-homogeneous-gsn/v1",
        },
        "promotion_decision": {
            "schema": "windows-solver.precision-promotion-decision/2",
            "from_precision_digits": 80,
            "to_precision_digits": 120,
            "state": "REQUESTED",
            "reason": "INSUFFICIENT_ASYMPTOTIC_PRECISION",
            "predicted_reliable_digits": "11",
            "required_reliable_digits": "24",
            "precision_limited": True,
            "asymptotic_preflight_avoided_ode": True,
        },
    }
    return CampaignExecutionAttempt(
        attempt_ordinal=1,
        leaf_id=leaf.leaf_id,
        leaf_index=1,
        role=leaf.role,
        state="NUMERICAL_CONTROL_FAILURE",
        precision_digits=80,
        failure_code="INSUFFICIENT_ASYMPTOTIC_PRECISION",
        failure_receipt={
            "worker_exit_code": 1,
            "worker_timed_out": False,
            "worker_stderr_tail": "synthetic",
            "worker_error_type": "Synthetic",
            "worker_error_message": "insufficient",
            "failure": failure,
        },
        created_at_utc="2026-08-14T00:00:00.000Z",
    )


def _endpoint_arithmetic_attempt(
    leaf,
    *,
    primary_predictor,
    request_backend=None,
):
    attempt = _failed_preflight_attempt(
        leaf, primary_predictor=primary_predictor
    )
    mapping = copy.deepcopy(attempt.to_mapping())
    failure = mapping["failure_receipt"]["failure"]
    failure["failure_code"] = "HORIZON_ARITHMETIC_INADEQUATE"
    failure["stage"] = control_failure_stage(
        "HORIZON_ARITHMETIC_INADEQUATE"
    )
    if request_backend is not None:
        request_binding = request_backend._request(
            leaf.job,
            0.0j,
            primary_predictor=primary_predictor,
        )
        failure["request_binding"] = request_binding
        failure["request_sha256"] = hashlib.sha256(
            canonical_json_bytes(request_binding)
        ).hexdigest()
        failure["execution_resource_policy"] = {
            name: request_binding["execution_resource"][name]
            for name in ("schema", "version", "sha256")
        }
    failure["diagnostics"] = valid_control_failure_diagnostics(
        "HORIZON_ARITHMETIC_INADEQUATE",
        precision_bits=failure["request_binding"]["working_precision_bits"],
    )
    failure["promotion_decision"] = {
        "schema": "windows-solver.precision-promotion-decision/2",
        "from_precision_digits": 80,
        "to_precision_digits": 120,
        "state": "REQUESTED",
        "reason": "HORIZON_ARITHMETIC_INADEQUATE",
        "predicted_reliable_digits": None,
        "required_reliable_digits": None,
        "precision_limited": None,
        "asymptotic_preflight_avoided_ode": None,
    }
    mapping["failure_code"] = "HORIZON_ARITHMETIC_INADEQUATE"
    mapping["failure_receipt"]["worker_error_message"] = (
        "endpoint arithmetic inadequate"
    )
    content = {
        key: value for key, value in mapping.items() if key != "attempt_sha256"
    }
    mapping["attempt_sha256"] = hashlib.sha256(
        canonical_json_bytes(content)
    ).hexdigest()
    return CampaignExecutionAttempt.from_mapping(mapping)


class NativeCampaignBackendTests(unittest.TestCase):
    def setUp(self):
        self.capabilities = PrecisionCapabilities((64, 80, 120))
        self.plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=self.capabilities,
        )
        self.leaf = next(
            leaf
            for leaf in self.plan.leaves
            if leaf.role == "deep"
            and leaf.mechanism_id != "horizon-admittance"
        )
        generated = GeneratedGsnCache(
            ("gsn-000001",),
            Path(".runtime/generated/gsn/gsn-selection-test.json"),
            "a" * 64,
            (GsnParameterPair(19, 20, self.leaf.job.mode.m),),
        )
        julia = SimpleNamespace(runtime_provenance={
            "julia_version": "1.10.11",
            "julia_executable_sha256": "b" * 64,
            "julia_manifest_sha256": "c" * 64,
            "worker_sha256": "d" * 64,
            "runtime_policy_sha256": "e" * 64,
            "scientific_sources": [],
        })
        native = NativeDeterminantAdapter(
            identity=VettedNativeDeterminantKernel.identity,
            kernel=SimpleNamespace(),
        )
        self.backend = NativeCampaignStageBackend(
            native,
            self.capabilities,
            generated,
            julia,
            ode_error_budgets={
                80: synthetic_ode_error_budget(80),
                120: synthetic_ode_error_budget(120),
            },
        )

    def test_main_era_full_resource_policy_attempt_remains_readable(self):
        """Catches a same-version policy expansion breaking attempt history."""

        mapping = copy.deepcopy(_failed_preflight_attempt(self.leaf).to_mapping())
        failure = mapping["failure_receipt"]["failure"]
        current_policy = failure["request_binding"]["execution_resource"]
        legacy_policy = {
            name: value
            for name, value in current_policy.items()
            if name not in {
                "coordinate_stall_rhs_threshold",
                "coordinate_stall_minimum_span_fraction",
                "coordinate_stall_minimum_step_fraction",
                "sha256",
            }
        }
        legacy_policy["sha256"] = hashlib.sha256(
            canonical_json_bytes(legacy_policy)
        ).hexdigest()
        failure["execution_resource_policy"] = legacy_policy
        material = {
            name: value
            for name, value in mapping.items()
            if name != "attempt_sha256"
        }
        mapping["attempt_sha256"] = hashlib.sha256(
            canonical_json_bytes(material)
        ).hexdigest()

        restored = CampaignExecutionAttempt.from_mapping(mapping)

        restored_policy = restored.failure_receipt["failure"][
            "execution_resource_policy"
        ]
        self.assertEqual(restored_policy, legacy_policy)

    def test_operation_control_attempt_round_trips_exact_receipt_and_request(self):
        legacy = _failed_preflight_attempt(self.leaf)
        legacy_failure = legacy.failure_receipt["failure"]
        request = legacy_failure["request_binding"]
        request_sha256 = hashlib.sha256(
            canonical_json_bytes(request)
        ).hexdigest()
        identity = execution_identity_from_request(
            request,
            request_sha256=request_sha256,
        )
        control_mapping = build_operation_control_receipt(
            origin=JULIA_WORKER_ORIGIN,
            failure_code="INSUFFICIENT_ASYMPTOTIC_PRECISION",
            stage="asymptotic-preflight",
            identity=identity,
            retryable=True,
            retryable_basis=JULIA_PRODUCER_RETRYABILITY_BASIS,
            diagnostics=legacy_failure["diagnostics"],
        )
        control = validate_operation_control_receipt(
            control_mapping,
            request=request,
            request_sha256=request_sha256,
        )
        error = JuliaNumericalControlError(
            "synthetic operation-control failure",
            "INSUFFICIENT_ASYMPTOTIC_PRECISION",
            control_receipt=control,
        )
        error.worker_failure = {
            "worker_exit_code": 21,
            "worker_timed_out": False,
            "worker_stderr_tail": "synthetic",
            "worker_error_type": "AsymptoticPrecisionError",
            "worker_error_message": "preflight rejected 80 digits",
            "failure": control.to_mapping(),
        }

        attempt = _execution_attempt_from_failure(
            error,
            leaf=self.leaf,
            context={"leaf_index": 1},
            digits=80,
            attempt_ordinal=1,
        )

        self.assertIsNotNone(attempt)
        receipt = attempt.failure_receipt
        self.assertEqual(
            receipt["schema"],
            "windows-solver.campaign-operation-control-attempt/1",
        )
        self.assertEqual(receipt["control_receipt"], control.to_mapping())
        self.assertNotIn("promotion_decision", receipt["control_receipt"])
        self.assertEqual(receipt["canonical_request"], request)
        restored = CampaignExecutionAttempt.from_mapping(attempt.to_mapping())
        self.assertEqual(restored, attempt)

    def test_deep_binary64_stage_derives_trigger_diagnostics(self):
        result = _result(self.leaf.job, 1.0 + 0.5j)
        with patch(
            "windows_solver.response_batches.run_component", return_value=result
        ):
            outcome = self.backend.execute_stage(self.leaf, 64)

        self.assertEqual(outcome.digits, 64)
        self.assertEqual(
            set(outcome.deep_diagnostics),
            {
                "condition_amplifier_abs",
                "predicted_reliable_decimal_digits",
                "step_richardson_disagreement_abs",
                "repeat_polish_delta_abs",
                "angular_refinement_delta_abs",
                "independent_path_delta_abs",
                "diagnostic_ceiling_abs",
                "denominator_or_calibration_disk_contains_zero",
            },
        )
        runtime = outcome.component_result["scientific_runtime"]
        self.assertEqual(runtime["record_artifact_ids"], ["gsn-000001"])
        self.assertEqual(runtime["cache_sha256_observed"], "a" * 64)

    def test_promoted_stage_records_repeat_and_prior_discrepancies(self):
        previous_result = _result(self.leaf.job, 1.0 + 0.0j)
        primary = _result(self.leaf.job, 1.0 + 2.0e-8j)
        previous = SimpleNamespace(
            digits=64,
            component_result={"result": previous_result.to_mapping()},
            local_disk_radius_abs=1.0e-6,
        )
        with patch(
            "windows_solver.response_batches.run_promoted_exterior_component",
            return_value=primary,
        ) as run:
            outcome = self.backend.execute_promoted_stage(
                self.leaf, 80, (previous,)
            )

        self.assertEqual(run.call_count, 1)
        self.assertAlmostEqual(outcome.discrepancy_from_previous_abs, 2.0e-8)
        self.assertTrue(outcome.discrepancy_enclosed)
        self.assertIsNone(outcome.self_refinement_enclosed)
        self.assertIsNone(outcome.component_result["self_refinement_result"])
        self.assertEqual(
            outcome.component_result["self_refinement_skipped_reason"],
            "NOT_REQUIRED_BY_FIXED_ROOT_DERIVATIVE_POLICY",
        )
        self.assertIs(
            outcome.component_result[
                "precision_ladder_discrepancy_applicable"
            ],
            True,
        )
        self.assertIsNone(
            outcome.component_result[
                "precision_ladder_discrepancy_reason"
            ]
        )
        repeat_channel = next(
            item
            for item in outcome.signed_error_channels
            if item["family"] == "repeat-polish"
        )
        self.assertEqual(
            repeat_channel["provenance"]["derivation"],
            "not-applicable-repeat-polish",
        )
        ledger_radius = sum(
            abs(complex(
                item["signed_delta"]["real"],
                item["signed_delta"]["imaginary"],
            ))
            for item in outcome.signed_error_channels
        )
        self.assertAlmostEqual(ledger_radius, outcome.local_disk_radius_abs)

    def test_promoted_exterior_never_labels_root_delta_as_response_delta(self):
        job = self.leaf.job
        unavailable = ComponentResult(
            job_id=job.job_id,
            leaf_id=job.leaf_id,
            mechanism_id=job.mechanism_id,
            status=ComponentStatus.NOT_CONVERGED,
            convergence_basis="UNRESOLVED",
            response=None,
            signed_root_crosscheck=None,
            closed_form_response=None,
            error_channels={name: 0.0 for name in ERROR_CHANNELS},
            baseline=RootReadout(
                omega=job.root.omega + complex(1.0e-3, -2.0e-3),
                determinant_residual_abs=1.0e-12,
                determinant_derivative_abs=2.0,
                converged=False,
                root_reference_id=job.root.root_reference_id,
                branch_id=job.root.branch_id,
                equation_id=job.equation_id,
                truncation_radius=None,
                resolution_radius=None,
                seed_path_radius=None,
                diagnostics_skipped_reason="PRIMARY_NOT_CONVERGED",
            ),
            levels=(),
            lineage=_lineage(job),
        )
        promoted = _result(job, 1.0 + 2.0e-8j)
        previous = SimpleNamespace(
            digits=64,
            component_result={"result": unavailable.to_mapping()},
            local_disk_radius_abs=1.0e-6,
        )

        with patch(
            "windows_solver.response_batches.run_promoted_exterior_component",
            return_value=promoted,
        ):
            outcome = self.backend.execute_promoted_stage(
                self.leaf, 80, (previous,)
            )

        self.assertIsNone(outcome.discrepancy_from_previous_abs)
        self.assertIsNone(outcome.discrepancy_enclosed)
        self.assertIs(
            outcome.component_result[
                "precision_ladder_discrepancy_applicable"
            ],
            False,
        )
        self.assertEqual(
            outcome.component_result[
                "precision_ladder_discrepancy_reason"
            ],
            "BINARY64_COMPONENT_RESPONSE_UNAVAILABLE",
        )
        precision_channel = next(
            item
            for item in outcome.signed_error_channels
            if item["family"] == "precision-ladder-discrepancy"
        )
        self.assertEqual(
            precision_channel["provenance"]["derivation"],
            "not-applicable-precision-ladder-discrepancy",
        )
        self.assertEqual(
            precision_channel["signed_delta"],
            {"real": 0.0, "imaginary": 0.0},
        )

    def test_default_promoted_stage_uses_committed_empirical_profile(self):
        previous_result = _result(self.leaf.job, 1.0 + 0.0j)
        promoted_result = _result(self.leaf.job, 1.0 + 2.0e-8j)
        previous = SimpleNamespace(
            digits=64,
            component_result={"result": previous_result.to_mapping()},
            local_disk_radius_abs=1.0e-6,
        )
        backend = NativeCampaignStageBackend(
            self.backend.adapter,
            self.capabilities,
            self.backend.generated_cache,
            self.backend.julia_adapter,
        )

        with patch(
            "windows_solver.response_batches.run_promoted_exterior_component",
            return_value=promoted_result,
        ) as run:
            backend.execute_promoted_stage(self.leaf, 80, (previous,))

        promoted_backend = run.call_args.args[1]
        self.assertIsNone(promoted_backend.ode_error_budget)
        self.assertEqual(
            promoted_backend.empirical_control_profile.determinant_family,
            "exterior-wronskian/v1",
        )
        self.assertEqual(
            promoted_backend.calibration_receipt.sha256,
            "3353a1836e520f1e360cf30feb898e132c63db8ba5e691eb01b1ed01533243de",
        )

    def test_default_native_contract_never_requests_legacy_ode_budget(self):
        """Regression for the PowerShell campaign's prior startup blocker."""

        backend = NativeCampaignStageBackend(
            self.backend.adapter,
            self.capabilities,
            self.backend.generated_cache,
            self.backend.julia_adapter,
        )

        contract = backend.scientific_execution_contract_for(self.leaf)

        self.assertEqual(
            contract["schema"],
            "windows-solver.m02-scientific-execution-contract/2",
        )
        self.assertNotIn("ode_error_budgets_by_nominal_decimal_digits", contract)
        self.assertEqual(
            contract["calibration_receipt"]["identity"],
            "promoted-control-empirical-calibration/v1",
        )
        self.assertEqual(
            contract["determinant_family"], "exterior-wronskian/v1"
        )
        self.assertEqual(
            set(contract["empirical_control_profiles_by_nominal_decimal_digits"]),
            {"80", "120"},
        )

    def test_unsuccessful_promoted_primary_skips_self_refinement(self):
        previous_result = _result(self.leaf.job, 1.0 + 0.0j)
        baseline = RootReadout(
            omega=self.leaf.job.root.omega,
            determinant_residual_abs=1.0e-12,
            determinant_derivative_abs=2.0,
            converged=False,
            root_reference_id=self.leaf.job.root.root_reference_id,
            branch_id=self.leaf.job.root.branch_id,
            equation_id=self.leaf.job.equation_id,
            truncation_radius=None,
            resolution_radius=None,
            seed_path_radius=None,
            diagnostics_skipped_reason="PRIMARY_NOT_CONVERGED",
        )
        primary = ComponentResult(
            job_id=self.leaf.job.job_id,
            leaf_id=self.leaf.job.leaf_id,
            mechanism_id=self.leaf.job.mechanism_id,
            status=ComponentStatus.NOT_CONVERGED,
            convergence_basis="UNRESOLVED",
            response=None,
            signed_root_crosscheck=None,
            closed_form_response=None,
            error_channels={name: 0.0 for name in ERROR_CHANNELS},
            baseline=baseline,
            levels=(),
            lineage=_lineage(self.leaf.job),
        )
        previous = SimpleNamespace(
            digits=64,
            component_result={"result": previous_result.to_mapping()},
            local_disk_radius_abs=1.0e-6,
        )
        with patch(
            "windows_solver.response_batches.run_promoted_exterior_component",
            return_value=primary,
        ) as run:
            outcome = self.backend.execute_promoted_stage(
                self.leaf, 80, (previous,)
            )

        self.assertEqual(run.call_count, 1)
        self.assertEqual(outcome.numerical_state, "NOT_CONVERGED")
        self.assertIsNone(outcome.self_refinement_enclosed)
        self.assertIsNone(outcome.component_result["self_refinement_result"])
        self.assertEqual(
            outcome.component_result["self_refinement_skipped_reason"],
            "NOT_REQUIRED_BY_FIXED_ROOT_DERIVATIVE_POLICY",
        )

    def test_failed_preflight_recovery_uses_fixed_root_derivative_once(self):
        predecessor = _failed_preflight_attempt(self.leaf)
        base = _result(self.leaf.job, 1.0 + 2.0e-8j)

        with patch(
            "windows_solver.response_batches.run_promoted_exterior_component",
            return_value=base,
        ) as run:
            outcome = self.backend.execute_promoted_stage_after_failed_preflight(
                self.leaf, 120, predecessor
            )

        self.assertEqual(run.call_count, 1)
        self.assertEqual(outcome.digits, 120)
        self.assertIsNone(outcome.discrepancy_from_previous_abs)
        self.assertIsNone(outcome.discrepancy_enclosed)
        self.assertIsNone(outcome.self_refinement_enclosed)
        component = outcome.component_result
        self.assertEqual(
            component["failed_preflight_predecessor"],
            predecessor.to_mapping(),
        )
        self.assertEqual(
            component["comparison_kind"],
            "failed-preflight-120-fixed-root-exterior-derivative/v1",
        )
        self.assertIs(
            component["precision_ladder_discrepancy_applicable"], False
        )
        self.assertEqual(
            component["precision_ladder_discrepancy_reason"],
            "BINARY64_COMPONENT_RESPONSE_UNAVAILABLE",
        )
        self.assertIsNone(component["self_refinement_result"])
        self.assertEqual(
            component["self_refinement_skipped_reason"],
            "NOT_REQUIRED_BY_FIXED_ROOT_DERIVATIVE_POLICY",
        )

    def test_endpoint_arithmetic_recovery_accepts_authenticated_missing_80_stage(self):
        leaf = next(
            item
            for item in self.plan.leaves
            if item.role == "primary"
            and item.mechanism_id == "horizon-admittance"
        )
        predictor = leaf.job.root.omega + complex(1.0e-5, -2.0e-5)
        predecessor = _endpoint_arithmetic_attempt(
            leaf, primary_predictor=predictor
        )
        recovered = _result(leaf.job, 0.25 - 0.125j, radius=1.0e-12)
        with patch(
            "windows_solver.response_batches.run_promoted_horizon_component",
            return_value=recovered,
        ) as run:
            outcome = self.backend.execute_promoted_stage_after_endpoint_arithmetic(
                leaf, 120, predecessor
            )

        self.assertEqual(run.call_count, 1)
        self.assertEqual(outcome.digits, 120)
        self.assertEqual(
            run.call_args.args[2], predictor
        )
        self.assertNotIn(
            "failed_preflight_predecessor", outcome.component_result
        )

    def test_deep_horizon_campaign_accepts_bounded_analytic_stage(self):
        from tests.test_promoted_horizon_component import (
            FakeJuliaPrecisionBackend,
            _promoted_baseline,
            _with_worker_receipt,
        )

        deep = next(
            leaf
            for leaf in self.plan.leaves
            if leaf.role == "deep"
            and leaf.mechanism_id == "horizon-admittance"
            and leaf.leaf.mode_label == "221"
            and leaf.job.spin < 0.9999
        )
        self.assertNotIn(
            deep.leaf_id,
            set(B_PRIME_RELEASE_DOMAIN.fixed_precision_sentinel_leaf_ids),
        )
        generated = GeneratedGsnCache(
            ("gsn-000001",),
            Path(".runtime/generated/gsn/gsn-selection-test.json"),
            "a" * 64,
            (GsnParameterPair(19, 20, deep.job.mode.m),),
        )
        backend = NativeCampaignStageBackend(
            self.backend.adapter,
            self.capabilities,
            generated,
            self.backend.julia_adapter,
        )
        predictor = deep.job.root.omega
        promoted = _with_worker_receipt(
            deep.job,
            _promoted_baseline(deep.job, omega=predictor),
            80,
            predictor,
        )
        julia = FakeJuliaPrecisionBackend(deep.job, promoted, 80)
        selection = build_campaign_selection(
            self.plan, role="deep", leaf_ids=(deep.leaf_id,)
        )
        promoted_result = run_promoted_horizon_component(
            deep.job, julia, predictor
        )
        assert promoted_result.response is not None
        binary = ComponentResult.from_mapping(
            _produced_stage_outcome(
                deep, promoted_result.response
            ).component_result["result"]
        )
        binary = replace(
            binary,
            baseline=replace(
                binary.baseline,
                truncation_radius=1.0e-12,
                resolution_radius=1.0e-12,
                seed_path_radius=1.0e-12,
                diagnostic_readouts={
                    family: DiagnosticRootReadout(
                        omega_delta_from_primary=delta,
                        determinant_residual_abs=1.0e-13,
                        determinant_derivative_abs=1.0,
                        converged=True,
                    )
                    for family, delta in {
                        "truncation": complex(1.0e-12, 0.0),
                        "resolution": complex(0.0, 1.0e-12),
                        "seed-path": complex(-1.0e-12, 0.0),
                    }.items()
                },
            ),
        )

        with tempfile.TemporaryDirectory() as temporary, patch(
            "windows_solver.response_batches.run_component",
            return_value=binary,
        ), patch(
            "windows_solver.response_batches.JuliaPrecisionRootBackend",
            return_value=julia,
        ):
            checkpoint = Path(temporary) / "deep-horizon.json"
            summary = run_campaign_selection(
                self.plan,
                selection,
                backend,
                checkpoint,
                resume=False,
            )
            validated = validate_campaign_checkpoint(self.plan, checkpoint)
            resumed = run_campaign_selection(
                self.plan,
                selection,
                backend,
                checkpoint,
                resume=True,
            )

        self.assertEqual(summary.state, "COMPLETE")
        self.assertEqual(validated.state, "COMPLETE")
        self.assertEqual(resumed.executed_stage_count, 0)
        self.assertEqual(resumed.reused_stage_count, 2)
        self.assertEqual(summary.records[0].state, "PRODUCED")
        self.assertEqual(
            tuple(stage.outcome.digits for stage in summary.records[0].stages),
            (64, 80),
        )

    def test_deep_endpoint_arithmetic_uses_bounded_horizon_terminal_rule(self):
        import windows_solver.response_batches as response_batches
        from tests.test_promoted_horizon_component import (
            FakeJuliaPrecisionBackend,
            _promoted_baseline,
            _with_worker_receipt,
        )

        cases = (
            ("221", False, "PRODUCED"),
            ("220", True, "UNRESOLVED"),
        )
        for mode_label, sentinel, expected_state in cases:
            with self.subTest(
                mode_label=mode_label,
                sentinel=sentinel,
            ):
                deep = min(
                    (
                        leaf
                        for leaf in self.plan.leaves
                        if leaf.role == "deep"
                        and leaf.mechanism_id == "horizon-admittance"
                        and leaf.leaf.mode_label == mode_label
                        and (
                            leaf.leaf_id
                            in set(
                                B_PRIME_RELEASE_DOMAIN.fixed_precision_sentinel_leaf_ids
                            )
                        )
                        is sentinel
                    ),
                    key=lambda leaf: leaf.job.spin,
                )
                predictor = deep.job.root.omega
                promoted120 = _with_worker_receipt(
                    deep.job,
                    _promoted_baseline(deep.job, omega=predictor),
                    120,
                    predictor,
                )
                worker120 = FakeJuliaPrecisionBackend(
                    deep.job, promoted120, 120
                )
                calibration_receipt = worker120._production_request_backend(
                    deep.job
                ).calibration_receipt
                backend = NativeCampaignStageBackend(
                    self.backend.adapter,
                    self.capabilities,
                    self.backend.generated_cache,
                    self.backend.julia_adapter,
                    calibration_receipt=calibration_receipt,
                )
                class EndpointFailingJuliaBackend(
                    FakeJuliaPrecisionBackend
                ):
                    def read_root(
                        self,
                        job,
                        amplitude,
                        primary_predictor=None,
                    ):
                        self.calls.append(
                            (job, amplitude, primary_predictor)
                        )
                        raise error

                promoted80 = _with_worker_receipt(
                    deep.job,
                    _promoted_baseline(deep.job, omega=predictor),
                    80,
                    predictor,
                )
                request_backend80 = FakeJuliaPrecisionBackend(
                    deep.job, promoted80, 80
                )._production_request_backend(deep.job)
                predecessor = _endpoint_arithmetic_attempt(
                    deep,
                    primary_predictor=predictor,
                    request_backend=request_backend80,
                )
                error = JuliaNumericalControlError(
                    "synthetic endpoint arithmetic inadequate",
                    "HORIZON_ARITHMETIC_INADEQUATE",
                )
                error.worker_failure = copy.deepcopy(
                    predecessor.failure_receipt
                )
                worker80 = EndpointFailingJuliaBackend(
                    deep.job, promoted80, 80
                )
                binary = ComponentResult.from_mapping(
                    _produced_stage_outcome(
                        deep, complex(1.0e-8, 2.0e-8)
                    ).component_result["result"]
                )
                binary = replace(
                    binary,
                    baseline=replace(
                        binary.baseline,
                        truncation_radius=1.0e-12,
                        resolution_radius=1.0e-12,
                        seed_path_radius=1.0e-12,
                        diagnostic_readouts={
                            family: DiagnosticRootReadout(
                                omega_delta_from_primary=delta,
                                determinant_residual_abs=1.0e-13,
                                determinant_derivative_abs=1.0,
                                converged=True,
                            )
                            for family, delta in {
                                "truncation": complex(1.0e-12, 0.0),
                                "resolution": complex(0.0, 1.0e-12),
                                "seed-path": complex(-1.0e-12, 0.0),
                            }.items()
                        },
                    ),
                )

                selection = build_campaign_selection(
                    self.plan, role="deep", leaf_ids=(deep.leaf_id,)
                )
                workers = {80: worker80, 120: worker120}
                with tempfile.TemporaryDirectory() as temporary, patch(
                    "windows_solver.response_batches.run_component",
                    return_value=binary,
                ), patch.object(
                    backend,
                    "_julia_precision_backend_for",
                    side_effect=lambda job, digits, refinement=0: workers[
                        digits
                    ],
                ) as precision_backend_for, patch.object(
                    backend,
                    "execute_promoted_stage_with_predictor",
                    wraps=backend.execute_promoted_stage_with_predictor,
                ) as execute_promoted, patch.object(
                    backend,
                    (
                        "execute_promoted_stage_after_endpoint_arithmetic_"
                        "with_predictor"
                    ),
                    wraps=(
                        backend
                        .execute_promoted_stage_after_endpoint_arithmetic_with_predictor
                    ),
                ) as execute_recovery, patch.object(
                    response_batches,
                    "_execute_endpoint_arithmetic_recovery_with_progress",
                    wraps=(
                        response_batches
                        ._execute_endpoint_arithmetic_recovery_with_progress
                    ),
                ) as recovery_with_progress:
                    checkpoint = Path(temporary) / "deep-arithmetic.json"
                    summary = run_campaign_selection(
                        self.plan,
                        selection,
                        backend,
                        checkpoint,
                        resume=False,
                    )
                    validated = validate_campaign_checkpoint(
                        self.plan, checkpoint
                    )

                self.assertEqual(summary.records[0].state, expected_state)
                self.assertEqual(validated.records[0].state, expected_state)
                self.assertEqual(execute_promoted.call_count, 1)
                self.assertEqual(execute_recovery.call_count, 1)
                self.assertEqual(recovery_with_progress.call_count, 1)
                self.assertEqual(
                    [
                        call.args[1]
                        for call in precision_backend_for.call_args_list
                    ],
                    [80, 120],
                )
                self.assertEqual(
                    worker80.calls,
                    [(deep.job, 0.0j, predictor)],
                )
                self.assertEqual(
                    worker120.calls,
                    [(deep.job, 0.0j, predictor)],
                )
                self.assertEqual(len(summary.attempts), 1)
                self.assertEqual(
                    summary.attempts[0].failure_code,
                    "HORIZON_ARITHMETIC_INADEQUATE",
                )
                self.assertEqual(
                    execute_recovery.call_args.args[2].to_mapping(),
                    summary.attempts[0].to_mapping(),
                )
                self.assertEqual(
                    summary.records[0].stages[-1].outcome.component_result[
                        "endpoint_arithmetic_predecessor"
                    ],
                    summary.attempts[0].to_mapping(),
                )
                self.assertEqual(
                    tuple(
                        stage.outcome.digits
                        for stage in summary.records[0].stages
                    ),
                    (64, 120),
                )


if __name__ == "__main__":
    unittest.main()
