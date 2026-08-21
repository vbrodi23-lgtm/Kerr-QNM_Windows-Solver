from __future__ import annotations

from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKER_SOURCE = REPO_ROOT / "src/windows_solver/data/julia/m02_worker.jl"


class ExteriorPrimaryDerivativeErrorRegressionTests(unittest.TestCase):
    def test_promoted_primary_propagates_error_for_any_certified_determinant(self) -> None:
        worker = WORKER_SOURCE.read_text(encoding="utf-8")
        start = worker.index("function solve_binary64_parity_primary(")
        end = worker.index("required_raw_determinant_evaluation_count", start)
        primary = worker[start:end]

        self.assertIn(
            'propagate_primary_derivative_error =\n'
            '        haskey(request, "determinant_error_model")',
            primary,
        )
        self.assertNotIn(
            'string(required(request, "mechanism_id")) == "horizon-admittance"',
            primary,
        )
        self.assertIn(
            "propagate_derivative_error=propagate_primary_derivative_error",
            primary,
        )

    def test_existing_stencil_propagation_uses_sample_error_without_extra_samples(self) -> None:
        worker = WORKER_SOURCE.read_text(encoding="utf-8")
        start = worker.index("function finite_difference_pair(")
        end = worker.index("function determinant_error_abs(", start)
        pair = worker[start:end]

        self.assertEqual(pair.count("d_plus = evaluator("), 1)
        self.assertEqual(pair.count("d_minus = evaluator("), 1)
        self.assertIn("propagated_centered_difference_error(", pair)
        self.assertIn("determinant_error_abs(T, d_plus)", pair)
        self.assertIn("determinant_error_abs(T, d_minus)", pair)


if __name__ == "__main__":
    unittest.main()
