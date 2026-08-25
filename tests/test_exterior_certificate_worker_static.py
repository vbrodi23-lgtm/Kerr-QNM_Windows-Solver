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

    def test_exterior_policy_declares_the_six_named_channels_and_gate(self):
        validation = self._slice("validate_regularised_gsn_policy", "parse_real")
        for field in (
            "determinant_error_channel_schema",
            "determinant_error_required_channels",
            "determinant_error_calibration_status",
            "determinant_error_missing_evidence_outcome",
        ):
            self.assertIn(field, validation)
        for channel in (
            "precision",
            "ode_controls",
            "endpoint_order",
            "match_readout",
            "angular_data",
            "arithmetic_rounding",
        ):
            self.assertIn(f'"{channel}"', self.worker)
        self.assertIn('"BLOCKED_BY_REVIEWED_ERROR_EVIDENCE"', self.worker)

    def test_current_exterior_policy_does_not_require_a_safety_factor(self):
        validation = self._slice("validate_fixed_root_survey_policy", "validate_fixed_root_survey_request")
        self.assertNotIn("determinant_error_safety_factor", validation)
        self.assertNotIn("EXTERIOR_EMPIRICAL_ERROR_SAFETY_FACTOR", validation)
        gate = self._slice("exterior_empirical_certificate_required", "determinant_progress")
        self.assertIn("EXTERIOR_ADDITIVE_CHANNEL_SCHEMA_ID && return false", gate)

    def test_exterior_endpoint_pair_remains_raw_provisional_evidence(self):
        exterior = self._slice("evaluate_exterior_determinant", "determinant")
        self.assertIn("select_worker_outer_endpoint_pair(", exterior)
        self.assertGreaterEqual(
            exterior.count("CF.solve_factored_xup_to_match("), 2
        )
        self.assertIn("endpoint_series_disagreement_abs", exterior)

    def test_cross_precision_helper_remains_available_for_future_calibration(self):
        guard = self._slice(
            "exterior_preceding_precision_policy", "precision_guard_disagreement"
        )
        self.assertIn('"binary64"', guard)
        self.assertIn('"bigfloat-40"', guard)
        self.assertIn('"bigfloat-80"', guard)


if __name__ == "__main__":
    unittest.main()
