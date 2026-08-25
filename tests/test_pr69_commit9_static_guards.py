"""Source-level guards for PR69 Commit 9 fail-closed wiring."""

from __future__ import annotations

import inspect
import unittest

from windows_solver import reviewed_determinant_error_issuance
from windows_solver.native_response_kernel import VettedNativeDeterminantKernel
from windows_solver.response_batches import NativeCampaignStageBackend
from windows_solver.response_uncertainty import horizon_response_disk


class Commit9StaticGuards(unittest.TestCase):
    def test_binary64_horizon_adapter_cannot_reach_slow_or_worker_paths(self) -> None:
        source = inspect.getsource(NativeCampaignStageBackend.execute_horizon_stage)
        implementation = source.split('"""', 2)[-1]
        for forbidden in (
            "run_component(",
            "execute_stage(",
            "LadderLevel",
            "TRUNCATION",
            "RESOLUTION",
            "SEED-PATH",
        ):
            self.assertNotIn(forbidden, implementation)
        self.assertIn('"worker_launch_count": 0', implementation)
        self.assertIn('"julia_worker": False', implementation)
        self.assertIn("signed_root_crosscheck=None", implementation)

    def test_horizon_kernel_exposes_raw_partials_without_r_finite_difference(self) -> None:
        source = inspect.getsource(VettedNativeDeterminantKernel.horizon_partials)
        self.assertIn("dD_dR", source)
        self.assertIn("dD_domega", source)
        self.assertNotIn("R + h", source)
        self.assertNotIn("R - h", source)

    def test_v3_quotient_has_explicit_negative_d_h_numerator(self) -> None:
        source = inspect.getsource(horizon_response_disk)
        self.assertIn("(-horizon_numerator) / denominator", source)
        self.assertNotIn("1.0 / denominator", source)

    def test_exterior_issuance_cannot_reintroduce_an_unreviewed_factor(self) -> None:
        source = inspect.getsource(
            reviewed_determinant_error_issuance.retain_uncalibrated_determinant_error_evidence
        )
        self.assertNotIn("certificate_safety_factor", source)
        self.assertNotIn(".issue(", source)
        self.assertNotIn("max(", source)


if __name__ == "__main__":
    unittest.main()
