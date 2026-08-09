from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from windows_solver.gsn_cache_producer import GeneratedGsnCache, GsnParameterPair
from windows_solver.response_batches import (
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


if __name__ == "__main__":
    unittest.main()
