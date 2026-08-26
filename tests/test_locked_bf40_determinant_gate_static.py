"""Static regressions for the locked BF40 determinant-error stop gate."""

from __future__ import annotations

import inspect
import unittest

from windows_solver import campaign_runtime, campaign_survey
from windows_solver.reviewed_determinant_error_issuance import (
    LOCKED_BF40_DETERMINANT_ERROR_ISSUANCE_BLOCKER,
    require_locked_bf40_determinant_error_issuance_authority,
)


class LockedBf40DeterminantGateTests(unittest.TestCase):
    def test_gate_fails_with_the_governing_contract_literal(self) -> None:
        """Break caught: BF40 exterior issuance resumes without calibration."""

        with self.assertRaisesRegex(
            RuntimeError,
            "current promoted-control receipt does not authorize production exterior",
        ):
            require_locked_bf40_determinant_error_issuance_authority()
        self.assertEqual(
            "TODO: [HUMAN NUMERICAL CALIBRATION REQUIRED — the current "
            "promoted-control receipt does not authorize production exterior "
            "determinant-error issuance for the locked BF40 handoff]",
            LOCKED_BF40_DETERMINANT_ERROR_ISSUANCE_BLOCKER,
        )

    def test_gate_precedes_every_exterior_backend_construction(self) -> None:
        """Break caught: an exterior worker can launch before the hard stop."""

        source = inspect.getsource(
            campaign_survey._run_promoted_exterior_queue_entry
        )
        self.assertLess(
            source.index("require_locked_bf40_determinant_error_issuance_authority"),
            source.index("backend = backend_factory"),
        )

    def test_runtime_preflight_stops_before_any_publication_or_provider(self) -> None:
        """Break caught: the composition root mutates before BF40 admission."""

        source = inspect.getsource(campaign_runtime.run_native_promoted_pass)
        gate = source.index("require_locked_bf40_determinant_error_issuance_authority")
        self.assertLess(gate, source.index("store = solved_leaf_store"))
        self.assertLess(gate, source.index("_publish_admissible_checkpoint_records"))
        self.assertLess(gate, source.index("root_provider().lookup"))

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
