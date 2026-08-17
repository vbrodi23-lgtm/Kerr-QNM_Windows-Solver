from __future__ import annotations

from pathlib import Path
import unittest


class ProductionLeaf13V14EquivalenceScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (
            Path(__file__).resolve().parents[1]
            / "M02_Production_Leaf13_V14_Equivalence_v1.ps1"
        ).read_text(encoding="utf-8")

    def test_uses_clean_production_campaign_entrypoints(self):
        self.assertIn('"campaign-run"', self.source)
        self.assertIn('"campaign-validate"', self.source)
        self.assertIn('"campaign-plan"', self.source)
        self.assertIn('"package-owned-julia-single-promoted-horizon-component"', self.source)
        self.assertNotIn("TESTER_", self.source)
        self.assertNotIn("monkeypatch", self.source.lower())
        self.assertNotIn("m02_worker.jl", self.source)
        self.assertNotIn("Set-Content -LiteralPath $Worker", self.source)

    def test_asserts_single_readout_and_zero_multipliers(self):
        for required in (
            "$JuliaAmplitudeReadouts.Count -eq 1",
            "$JuliaSignedReadouts.Count -eq 0",
            "$SelfRefinementPasses.Count -eq 0",
            "$JuliaRequests.Count -eq 1",
            "$RefinementLevelOneRequests.Count -eq 0",
            "$Promoted.scientific_runtime.refinement_level -eq 0",
            "$Baseline.worker_response_receipt.request_binding.refinement_level -eq 0",
            "$Result.finite_amplitude_readout_count -eq 0",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.source)

    def test_asserts_v14_root_kernel_budgets_and_analytic_result(self):
        for required in (
            "$Primary.post_newton_determinant_count -eq 0",
            "$Truncation.determinant_count -eq 1",
            "$Resolution.determinant_count -eq 1",
            '$Truncation.derivative_source -eq "PRIMARY_COMPLEX"',
            '$Resolution.derivative_source -eq "PRIMARY_COMPLEX"',
            "$Baseline.seed_path_required -eq $false",
            "$Baseline.seed_path_executed -eq $false",
            "$Baseline.seed_path_determinant_count -eq 0",
            '"analytic-horizon-from-promoted-primary-derivative/v1"',
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.source)


if __name__ == "__main__":
    unittest.main()
