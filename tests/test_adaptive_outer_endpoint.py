from __future__ import annotations

from pathlib import Path
import unittest

from windows_solver.adaptive_controls import (
    NoAdequateOuterEndpointError,
    OuterEndpointCandidate,
    select_outer_endpoint,
)
from windows_solver.precision_tiers import PrecisionTier


def candidate(
    rho_out: float,
    digits: float,
    *,
    regularity_ok: bool = True,
    last_term_ok: bool = True,
    series_spread_abs: float = 1.0e-10,
    cancellation_digits: float = 1.25,
) -> OuterEndpointCandidate:
    return OuterEndpointCandidate(
        rho_out=rho_out,
        best_prefix_order=28,
        predicted_reliable_digits=digits,
        last_term_ratio=1.0e-12,
        series_spread_abs=series_spread_abs,
        cancellation_digits=cancellation_digits,
        regularity_ok=regularity_ok,
        last_term_ok=last_term_ok,
    )


class AdaptiveOuterEndpointTests(unittest.TestCase):
    def test_production_worker_reuses_cap_geometry_and_selects_nearest_adequate(self) -> None:
        root = Path(__file__).resolve().parents[1]
        worker = (root / "src/windows_solver/data/julia/m02_worker.jl").read_text(
            encoding="utf-8"
        )
        backend = (root / "src/windows_solver/julia_response_backend.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"rho_out_candidate_schedule"', backend)
        self.assertIn('"100", "250", "500", "1000", "2000", "5000"', backend)
        self.assertIn("select_worker_outer_endpoint", worker)
        self.assertIn("cap_contour.radius_from_rho", worker)
        self.assertIn("sort(unique(candidate_schedule))", worker)
        self.assertIn("assessment.adequate", worker)
        self.assertIn('"selected_rho_out"', worker)
        self.assertIn('"candidates"', worker)
        self.assertLess(
            worker.index("select_worker_outer_endpoint("),
            worker.index('progress_operation("Xup")'),
        )

    def test_selects_nearest_adequate_candidate_and_records_all_evidence(self) -> None:
        selection = select_outer_endpoint(
            [candidate(5000.0, 40.0), candidate(100.0, 18.9), candidate(250.0, 21.0)],
            required_reliable_digits=18.0,
            safety_margin_digits=2.0,
            maximum_series_spread_abs=1.0e-8,
            maximum_cancellation_digits=6.0,
            precision_tier=PrecisionTier.BIGFLOAT_40,
        )
        self.assertEqual(selection.selected.rho_out, 250.0)
        self.assertEqual([item.rho_out for item in selection.candidates], [100.0, 250.0, 5000.0])
        self.assertEqual(
            [item.reason for item in selection.candidates],
            ["INSUFFICIENT_RELIABLE_DIGITS", "SELECTED_NEAREST_ADEQUATE", "ADEQUATE_NOT_SELECTED"],
        )
        self.assertEqual(selection.to_mapping()["precision_tier"], "bigfloat-40")
        self.assertEqual(selection.to_mapping()["nominal_decimal_digits"], 40)
        self.assertEqual(selection.to_mapping()["working_precision_bits"], 165)

    def test_regularity_and_last_term_are_hard_gates(self) -> None:
        with self.assertRaisesRegex(NoAdequateOuterEndpointError, "no outer endpoint"):
            select_outer_endpoint(
                [
                    candidate(100.0, 30.0, regularity_ok=False),
                    candidate(250.0, 30.0, last_term_ok=False),
                    candidate(500.0, 30.0, series_spread_abs=1.0e-6),
                    candidate(1000.0, 30.0, cancellation_digits=8.0),
                ],
                required_reliable_digits=18.0,
                safety_margin_digits=2.0,
                maximum_series_spread_abs=1.0e-8,
                maximum_cancellation_digits=6.0,
                precision_tier=PrecisionTier.BIGFLOAT_40,
            )

    def test_spread_and_cancellation_have_explicit_rejection_reasons(self) -> None:
        selection = select_outer_endpoint(
            [
                candidate(100.0, 30.0, series_spread_abs=1.0e-6),
                candidate(250.0, 30.0, cancellation_digits=8.0),
                candidate(500.0, 30.0),
            ],
            required_reliable_digits=18.0,
            safety_margin_digits=2.0,
            maximum_series_spread_abs=1.0e-8,
            maximum_cancellation_digits=6.0,
            precision_tier=PrecisionTier.BIGFLOAT_40,
        )
        self.assertEqual(
            [item.reason for item in selection.candidates],
            ["SERIES_SPREAD_GATE_FAILED", "CANCELLATION_GATE_FAILED", "SELECTED_NEAREST_ADEQUATE"],
        )

    def test_reliable_digits_must_strictly_exceed_requirement_plus_margin(self) -> None:
        selection = select_outer_endpoint(
            [candidate(100.0, 20.0), candidate(250.0, 20.0001)],
            required_reliable_digits=18.0,
            safety_margin_digits=2.0,
            maximum_series_spread_abs=1.0e-8,
            maximum_cancellation_digits=6.0,
            precision_tier=PrecisionTier.BIGFLOAT_40,
        )
        self.assertEqual(selection.selected.rho_out, 250.0)
        self.assertEqual(selection.candidates[0].reason, "INSUFFICIENT_RELIABLE_DIGITS")


if __name__ == "__main__":
    unittest.main()
