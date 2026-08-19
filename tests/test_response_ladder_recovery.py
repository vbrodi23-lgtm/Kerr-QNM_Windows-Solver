from __future__ import annotations

import unittest

from windows_solver.precision_tiers import PrecisionTier
from windows_solver.response_ladder_recovery import (
    LadderLevel,
    LadderPolicy,
    LadderReadout,
    RecoveryDisposition,
    recover_response_ladder,
)


CAPTURED_SIGNAL_RATIOS = {
    "220": ((0.004, 2.582, 2.662), (0.002, 2.523, 2.893), (0.001, 0.912, 6.710), (0.0005, 0.626, 0.693)),
    "330": ((0.004, 2.233, 2.499), (0.002, 1.600, 3.394), (0.001, 1.053, 0.767), (0.0005, 0.432, 1.455)),
    "440": ((0.004, 1.164, 1.085), (0.002, 0.644, 1.403), (0.001, 0.682, 0.990), (0.0005, 0.355, 0.579)),
}


def _readout(omega: complex, error: float) -> LadderReadout:
    return LadderReadout(
        omega=omega,
        root_error=error,
        branch_ok=True,
        diagnostic_ok=True,
        precision_tier=PrecisionTier.BINARY64,
    )


def _level(
    epsilon: float,
    real_ratio: float,
    imaginary_ratio: float,
    *,
    response: complex = 2.0e-8 + 1.0e-8j,
    quadratic: complex = 3.0e-5 - 2.0e-5j,
) -> LadderLevel:
    # Literal factor-8 fixture construction: for a centred pair with root
    # error e on each side, ratio = eps*|secant|/(16e).
    secant = response + quadratic * epsilon**2
    real_error = epsilon * abs(secant) / (16.0 * real_ratio)
    imaginary_error = epsilon * abs(secant) / (16.0 * imaginary_ratio)
    baseline = 1.0 - 0.01j
    return LadderLevel.from_signed_readouts(
        epsilon=epsilon,
        real_plus=_readout(baseline + epsilon * secant, real_error),
        real_minus=_readout(baseline - epsilon * secant, real_error),
        imaginary_plus=_readout(baseline + 1j * epsilon * secant, imaginary_error),
        imaginary_minus=_readout(baseline - 1j * epsilon * secant, imaginary_error),
    )


def _captured(mode: str) -> tuple[LadderLevel, ...]:
    return tuple(_level(*row) for row in CAPTURED_SIGNAL_RATIOS[mode])


def _policy(*, maximum_epsilon: float = 0.032) -> LadderPolicy:
    return LadderPolicy(
        signal_factor=8.0,
        minimum_window=4,
        maximum_epsilon=maximum_epsilon,
        required_order=2.0,
        order_tolerance=0.6,
        axis_tolerance_factor=2.0,
        even_remainder_factor=2.0,
    )


class ResponseLadderRecoveryTests(unittest.TestCase):
    def test_captured_ratios_and_exact_amplitude_expansion_requests(self) -> None:
        expected_additions = {
            "220": (0.008, 0.016),
            "330": (0.008, 0.016),
            "440": (0.008, 0.016, 0.032),
        }
        for mode, captured in CAPTURED_SIGNAL_RATIOS.items():
            with self.subTest(mode=mode):
                levels = _captured(mode)
                observed = tuple(
                    (level.epsilon, *level.signal_ratios(8.0)) for level in levels
                )
                for actual, wanted in zip(observed, captured, strict=True):
                    self.assertEqual(actual[0], wanted[0])
                    self.assertAlmostEqual(actual[1], wanted[1], places=3)
                    self.assertAlmostEqual(actual[2], wanted[2], places=3)
                result = recover_response_ladder(levels, policy=_policy())
                self.assertEqual(result.disposition, RecoveryDisposition.EXPAND_AMPLITUDE)
                self.assertEqual(result.amplitudes_to_add, expected_additions[mode])
                self.assertEqual(result.readouts_to_promote, ())

    def test_finest_admissible_window_excludes_noisy_fine_levels_with_reasons(self) -> None:
        expanded = (
            _level(0.016, 20.0, 20.0),
            _level(0.008, 20.0, 20.0),
            *_captured("220"),
        )
        result = recover_response_ladder(expanded, policy=_policy())
        self.assertEqual(result.disposition, RecoveryDisposition.RECOVERED)
        self.assertEqual(result.selected_epsilons, (0.016, 0.008, 0.004, 0.002))
        self.assertEqual(
            tuple(item.epsilon for item in result.excluded_fine_levels),
            (0.001, 0.0005),
        )
        self.assertTrue(
            all("SIGNAL_GATE" in item.reasons for item in result.excluded_fine_levels)
        )
        self.assertGreaterEqual(len(result.candidate_windows), 6)
        self.assertTrue(all(item.signal_ok for item in result.selected_window.levels))
        self.assertTrue(result.selected_window.real_order_ok)
        self.assertTrue(result.selected_window.imaginary_order_ok)
        self.assertTrue(result.selected_window.axis_ok)
        self.assertTrue(result.selected_window.even_remainder_ok)
        self.assertTrue(result.selected_window.branch_ok)
        self.assertTrue(result.selected_window.diagnostic_ok)

    def test_nonlinear_expansion_fails_closed_then_promotes_only_failing_axis_pair(self) -> None:
        nonlinear = list(_captured("440"))
        nonlinear.insert(0, _level(0.008, 20.0, 20.0, response=8.0e-4 + 3.0e-4j))
        nonlinear.insert(0, _level(0.016, 20.0, 20.0, response=-7.0e-4 + 2.0e-4j))
        nonlinear.insert(0, _level(0.032, 20.0, 20.0, response=9.0e-4 - 8.0e-4j))

        result = recover_response_ladder(tuple(nonlinear), policy=_policy())
        self.assertEqual(result.disposition, RecoveryDisposition.PROMOTE_READOUTS)
        self.assertEqual(result.next_precision_tier, PrecisionTier.BIGFLOAT_40)
        self.assertTrue(any("ORDER_GATE" in item.reasons for item in result.candidate_windows))
        self.assertIn((0.002, "real_plus"), result.readouts_to_promote)
        self.assertIn((0.002, "real_minus"), result.readouts_to_promote)
        self.assertNotIn((0.002, "imaginary_plus"), result.readouts_to_promote)
        self.assertNotIn((0.002, "imaginary_minus"), result.readouts_to_promote)


if __name__ == "__main__":
    unittest.main()
