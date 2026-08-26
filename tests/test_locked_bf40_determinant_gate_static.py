"""Regressions for typed promoted calculation/admission preflight."""

from __future__ import annotations

import inspect
import unittest

from windows_solver import campaign_survey
from windows_solver.promoted_control_calibration import (
    PromotedExecutionMode,
    load_default_calibration_receipt,
)
from windows_solver.reviewed_determinant_error_issuance import (
    PromotedExecutionPreflight,
    require_locked_bf40_determinant_error_issuance_authority,
)


class LockedBf40DeterminantGateTests(unittest.TestCase):
    def test_known_publication_boundary_returns_calculate_only_preflight(self) -> None:
        """Break caught: a known admission boundary raises as software."""

        result = require_locked_bf40_determinant_error_issuance_authority(
            load_default_calibration_receipt(),
            route="EXTERIOR_BF40",
        )

        self.assertIsInstance(result, PromotedExecutionPreflight)
        self.assertIs(result.mode, PromotedExecutionMode.CALCULATE_ONLY)
        self.assertEqual("EXTERIOR_BF40", result.route)
        self.assertTrue(result.calculation_permitted)
        self.assertTrue(result.checkpointing_permitted)
        self.assertFalse(result.admission_permitted)
        self.assertFalse(result.publication_permitted)
        self.assertEqual("REVIEW_PENDING", result.result_code)

    def test_promoted_persist_reloads_and_checks_every_guard_phase(self) -> None:
        """Break caught: a promoted write bypasses a Layer-1 guard phase."""

        source = inspect.getsource(campaign_survey.run_promoted_survey)
        pre_write = source.index("layer1_guard.pre_write(candidate)")
        atomic_write = source.index("_atomic_json(path, candidate)")
        durable_read = source.index("_load_durable_schema11_checkpoint(path)")
        post_write = source.index("layer1_guard.post_write(durable)")
        callback = source.index("checkpoint_committed(durable)")
        post_callback = source.index("layer1_guard.post_callback(durable)")
        self.assertLess(pre_write, atomic_write)
        self.assertLess(atomic_write, durable_read)
        self.assertLess(durable_read, post_write)
        self.assertLess(post_write, callback)
        self.assertLess(callback, post_callback)


if __name__ == "__main__":
    unittest.main()
