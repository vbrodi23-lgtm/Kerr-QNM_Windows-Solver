from pathlib import Path
import unittest


class JuliaPrecisionContextStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).parents[1]
        cls.worker = (
            root / "src/windows_solver/data/julia/m02_worker.jl"
        ).read_text(encoding="utf-8")
        cls.spec = (
            root
            / "src/windows_solver/data/julia/m02_worker_finite_difference_spec.jl"
        ).read_text(encoding="utf-8")

    def test_context_conversion_accepts_distinct_source_and_target_types(self):
        start = self.worker.index("function precision_guard_context(")
        end = self.worker.index("\nend", start) + len("\nend")
        function = self.worker[start:end]
        self.assertIn(
            "evaluation_context::DeterminantRequestContext{S}", function
        )
        self.assertIn(
            "where {T<:AbstractFloat,S<:AbstractFloat}", function
        )
        self.assertIn("GSNBranchConvention{T}", function)
        self.assertIn("ConditioningAccumulator(T)", function)
        self.assertIn("AuthenticatedDeterminantEvidenceStore()", function)
        self.assertIn(
            "guard_cell == evaluation_context.frozen_branch_cell", function
        )

    def test_direct_specs_cover_every_required_conversion_and_guard(self):
        for marker in (
            "BigFloat source context converts to Float64",
            "BF80 ambient context converts to BF40 ambient context",
            "BF120 ambient context converts to BF80 ambient context",
            "precision context conversion fails on branch-cell change",
            "precision context conversion does not mutate its source",
        ):
            self.assertIn(marker, self.spec)

    def test_survey_batch_cannot_reach_precision_guard_context(self):
        start = self.worker.index("function fixed_root_survey_batch_fields")
        end = self.worker.index(
            "\nfunction fixed_root_determinant_sample_fields", start
        )
        self.assertNotIn("precision_guard_context", self.worker[start:end])


if __name__ == "__main__":
    unittest.main()
