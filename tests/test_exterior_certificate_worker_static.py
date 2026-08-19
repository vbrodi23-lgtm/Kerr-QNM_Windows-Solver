from __future__ import annotations

import unittest
from pathlib import Path


WORKER = (
    Path(__file__).resolve().parents[1]
    / "src/windows_solver/data/julia/m02_worker.jl"
)


class ExteriorCertificateWorkerStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.worker = WORKER.read_text(encoding="utf-8")

    def _slice(self, name: str, next_name: str) -> str:
        start = self.worker.index(f"function {name}(")
        end = self.worker.index(f"function {next_name}(", start + 1)
        return self.worker[start:end]

    def test_exterior_policy_requires_the_empirical_certificate_identity(self):
        self.assertIn(
            '"exterior-determinant-absolute-error-certificate/empirical-v1"',
            self.worker,
        )
        validation = self._slice("validate_regularised_gsn_policy", "parse_real")
        for field in (
            "determinant_error_required_term_classes",
            "determinant_error_missing_evidence_outcome",
            "determinant_error_certificate_statement",
            "determinant_error_preceding_precision_tier",
        ):
            self.assertIn(field, validation)

    def test_exterior_endpoint_pair_produces_an_absolute_disagreement(self):
        exterior = self._slice("evaluate_exterior_determinant", "determinant")
        self.assertIn("select_worker_outer_endpoint_pair(", exterior)
        self.assertGreaterEqual(
            exterior.count("CF.solve_factored_xup_to_match("), 2
        )
        self.assertIn("endpoint_series_disagreement_abs", exterior)
        self.assertIn("EXTERIOR_EMPIRICAL_ERROR_MODEL_ID", exterior)

    def test_promoted_exterior_determinants_route_through_authentication(self):
        routed = self._slice("determinant_progress", "enforce_root_readout_feasibility")
        authenticated = self._slice(
            "authenticated_determinant_progress", "diagnostic_determinant_progress"
        )
        self.assertIn("exterior_empirical_certificate_required", routed)
        self.assertIn("authenticated_determinant_progress(", routed)
        self.assertIn("raw_determinant_progress(", authenticated)
        self.assertNotIn("base.error_breakdown === nothing && return base", authenticated)

    def test_resource_estimator_uses_one_complete_certificate_cost(self):
        routed = self._slice("determinant_progress", "enforce_root_readout_feasibility")
        self.assertIn("LAST_DETERMINANT_SECONDS[] =", routed)
        self.assertIn("LAST_DETERMINANT_PURPOSE[] = purpose", routed)

    def test_all_three_exterior_disagreement_classes_are_mandatory(self):
        authenticated = self._slice(
            "authenticated_determinant_progress", "diagnostic_determinant_progress"
        )
        for term in (
            "delta_same_point",
            "delta_cross_precision",
            "delta_endpoint_series",
        ):
            self.assertIn(term, authenticated)
        self.assertIn("EXTERIOR_DETERMINANT_CERTIFICATE_UNAVAILABLE", authenticated)
        self.assertIn("EXTERIOR_EMPIRICAL_ERROR_MODEL_ID", authenticated)

    def test_cross_precision_comparison_uses_the_immediate_predecessor(self):
        guard = self._slice(
            "exterior_preceding_precision_policy", "precision_guard_disagreement"
        )
        self.assertIn('"binary64"', guard)
        self.assertIn('"bigfloat-40"', guard)
        self.assertIn('"bigfloat-80"', guard)
        self.assertIn("Float64", guard)
        self.assertIn("working_precision_bits_for(40)", guard)
        self.assertIn("working_precision_bits_for(80)", guard)


if __name__ == "__main__":
    unittest.main()
