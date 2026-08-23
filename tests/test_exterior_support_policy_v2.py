from __future__ import annotations

import math
from types import SimpleNamespace
import unittest

from windows_solver.campaign_survey import preflight_campaign_supports
from windows_solver.response_batches import (
    PrecisionCapabilities,
    _scientific_computation_identity_material,
    _leaf_precision_contract,
    build_campaign_plan,
)
from windows_solver.response_engine import (
    EXTERIOR_SUPPORT_POLICY_ID,
    NumericalPolicy,
    VettedNativeDeterminantKernel,
    _exterior_support,
)


EXTERIOR_MECHANISMS = (
    "exterior-fixed-r3",
    "exterior-light-ring",
    "exterior-throat-kappa",
    "exterior-alpha-zero",
    "exterior-alpha-half",
    "exterior-alpha-one",
)


def _old_support(spin: float, mechanism_id: str) -> tuple[float, float, float, float]:
    horizon = 1.0 + math.sqrt(max(0.0, 1.0 - spin * spin))
    kappa = math.sqrt(max(0.0, 1.0 - spin * spin)) / (2.0 * horizon)
    if mechanism_id == "exterior-fixed-r3":
        centre, width = 3.0, 0.45
    elif mechanism_id == "exterior-light-ring":
        centre = 2.0 * (1.0 + math.cos((2.0 / 3.0) * math.acos(-spin)))
        width = max(0.012, 0.25 * max(centre - horizon, 1.0e-8))
    elif mechanism_id == "exterior-throat-kappa":
        centre, width = horizon + 3.0 * kappa, max(0.012, 0.6 * kappa)
    elif mechanism_id == "exterior-alpha-zero":
        centre, width = horizon + 2.0, 0.5
    elif mechanism_id == "exterior-alpha-half":
        scale = math.sqrt(max(kappa, 1.0e-300))
        centre, width = horizon + 2.0 * scale, max(0.012, 0.5 * scale)
    else:
        centre, width = horizon + 4.0 * kappa, max(0.012, kappa)
    width = min(width, centre - (horizon + 5.0e-4))
    return centre - width, centre + width, centre, width


class ExteriorSupportPolicyV2Tests(unittest.TestCase):
    def test_near_extremal_support_matrix_stays_strictly_outside_horizon(self) -> None:
        for spin in (0.95, 0.99, 0.999, 0.9999, 0.99999, 0.999998, 0.9999999):
            horizon = 1.0 + math.sqrt(1.0 - spin * spin)
            for mechanism_id in EXTERIOR_MECHANISMS:
                with self.subTest(spin=spin, mechanism=mechanism_id):
                    support = _exterior_support(spin, mechanism_id)
                    gap = support.centre - horizon
                    standoff = min(5.0e-4, gap / 4.0)
                    self.assertGreater(gap, 0.0)
                    self.assertGreater(standoff, 0.0)
                    self.assertGreater(support.half_width, 0.0)
                    self.assertEqual(
                        support.lower, support.centre - support.half_width
                    )
                    self.assertEqual(
                        support.upper, support.centre + support.half_width
                    )
                    self.assertGreaterEqual(support.lower, horizon + standoff)
                    self.assertLess(support.upper, 6.0)

    def test_moderate_spin_mapping_is_byte_for_byte_unchanged(self) -> None:
        for mechanism_id in EXTERIOR_MECHANISMS:
            with self.subTest(mechanism=mechanism_id):
                support = _exterior_support(0.95, mechanism_id)
                self.assertEqual(
                    _old_support(0.95, mechanism_id),
                    (
                        support.lower,
                        support.upper,
                        support.centre,
                        support.half_width,
                    ),
                )

    def test_scientific_identity_binds_policy_and_realised_mapping(self) -> None:
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64,)),
        )
        leaf = next(
            item for item in plan.leaves if item.mechanism_id != "horizon-admittance"
        )

        material = _scientific_computation_identity_material(
            plan, leaf, _leaf_precision_contract(leaf)
        )

        support = material["exterior_support"]
        self.assertEqual(EXTERIOR_SUPPORT_POLICY_ID, support["policy_identity"])
        self.assertEqual(
            _exterior_support(leaf.job.spin, leaf.mechanism_id).to_mapping(),
            support["realised_mapping"],
        )

    def test_invalid_selected_support_aborts_full_plan_preflight(self) -> None:
        leaf = SimpleNamespace(
            leaf_id="leaf-1",
            mechanism_id="exterior-fixed-r3",
            job=SimpleNamespace(spin=0.95),
        )
        plan = SimpleNamespace(
            leaves=(leaf,), policy=SimpleNamespace(readout_radius=3.2)
        )

        with self.assertRaisesRegex(ValueError, "readout radius"):
            preflight_campaign_supports(plan, ("leaf-1",))


if __name__ == "__main__":
    unittest.main()
