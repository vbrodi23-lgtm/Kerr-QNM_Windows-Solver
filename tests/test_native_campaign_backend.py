from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from windows_solver.contracts import canonical_json_bytes
from windows_solver.gsn_cache_producer import GeneratedGsnCache, GsnParameterPair
from windows_solver.julia_response_backend import JuliaPrecisionRootBackend
from windows_solver.response_batches import (
    CampaignExecutionAttempt,
    NativeCampaignStageBackend,
    PrecisionCapabilities,
    build_campaign_plan,
)
from windows_solver.response_engine import (
    ComponentResult,
    ComponentStatus,
    NativeDeterminantAdapter,
    NumericalPolicy,
    RootReadout,
    VettedNativeDeterminantKernel,
    ERROR_CHANNELS,
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


def _failed_preflight_attempt(leaf):
    request_binding = JuliaPrecisionRootBackend(
        leaf.job.backend_identity, object(), 80
    )._request(leaf.job, 0.0j)
    failure = {
        "failure_code": "INSUFFICIENT_ASYMPTOTIC_PRECISION",
        "failure_class": "CONTROL",
        "retryable": True,
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
            "predicted_reliable_digits": "11",
            "required_reliable_digits": "24",
            "asymptotic_preflight_avoided_ode": True,
            "asymptotic_preflight_reason": (
                "INSUFFICIENT_ASYMPTOTIC_PRECISION"
            ),
            "factored_homogeneous_rhs_evaluations": 0,
            "avoided_ode_scope": "factored-homogeneous-gsn/v1",
        },
        "promotion_decision": {
            "schema": "windows-solver.precision-promotion-decision/1",
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


class NativeCampaignBackendTests(unittest.TestCase):
    def setUp(self):
        self.capabilities = PrecisionCapabilities((64, 80, 120))
        self.plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=self.capabilities,
        )
        self.leaf = next(leaf for leaf in self.plan.leaves if leaf.role == "deep")
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
            native, self.capabilities, generated, julia
        )

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
        repeat = _result(self.leaf.job, 1.0 + 2.5e-8j)
        previous = SimpleNamespace(
            digits=64,
            component_result={"result": previous_result.to_mapping()},
            local_disk_radius_abs=1.0e-6,
        )
        with patch(
            "windows_solver.response_batches.run_component",
            side_effect=(primary, repeat),
        ) as run:
            outcome = self.backend.execute_promoted_stage(
                self.leaf, 80, (previous,)
            )

        self.assertEqual(run.call_count, 2)
        self.assertAlmostEqual(outcome.discrepancy_from_previous_abs, 2.0e-8)
        self.assertTrue(outcome.discrepancy_enclosed)
        self.assertTrue(outcome.self_refinement_enclosed)
        self.assertIsNotNone(
            outcome.component_result["self_refinement_result"]
        )
        ledger_radius = sum(
            abs(complex(
                item["signed_delta"]["real"],
                item["signed_delta"]["imaginary"],
            ))
            for item in outcome.signed_error_channels
        )
        self.assertAlmostEqual(ledger_radius, outcome.local_disk_radius_abs)

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
            "windows_solver.response_batches.run_component",
            return_value=primary,
        ) as run:
            outcome = self.backend.execute_promoted_stage(
                self.leaf, 80, (previous,)
            )

        self.assertEqual(run.call_count, 1)
        self.assertEqual(outcome.numerical_state, "NOT_CONVERGED")
        self.assertIs(outcome.self_refinement_enclosed, False)
        self.assertIsNone(outcome.component_result["self_refinement_result"])
        self.assertEqual(
            outcome.component_result["self_refinement_skipped_reason"],
            "PRIMARY_NOT_CONVERGED",
        )

    def test_failed_preflight_recovery_runs_120_base_and_refinement(self):
        predecessor = _failed_preflight_attempt(self.leaf)
        base = _result(self.leaf.job, 1.0 + 2.0e-8j)
        refinement = _result(self.leaf.job, 1.0 + 2.5e-8j)

        with patch(
            "windows_solver.response_batches.run_component",
            side_effect=(base, refinement),
        ) as run:
            outcome = self.backend.execute_promoted_stage_after_failed_preflight(
                self.leaf, 120, predecessor
            )

        self.assertEqual(run.call_count, 2)
        self.assertEqual(outcome.digits, 120)
        self.assertIsNone(outcome.discrepancy_from_previous_abs)
        self.assertIsNone(outcome.discrepancy_enclosed)
        self.assertTrue(outcome.self_refinement_enclosed)
        component = outcome.component_result
        self.assertEqual(
            component["failed_preflight_predecessor"],
            predecessor.to_mapping(),
        )
        self.assertEqual(
            component["comparison_kind"],
            "same-precision-120-base-vs-refinement/v1",
        )
        self.assertIs(
            component["precision_ladder_discrepancy_applicable"], False
        )
        self.assertEqual(
            component["self_refinement_scientific_runtime"][
                "refinement_level"
            ],
            1,
        )


if __name__ == "__main__":
    unittest.main()
