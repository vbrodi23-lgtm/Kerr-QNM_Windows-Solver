from __future__ import annotations

import unittest

from windows_solver.response_engine import (
    BINARY64_FIXED_ROOT_SAMPLE_ROLES,
    Binary64SurveyDisposition,
    NumericalPolicy,
    screen_binary64_fixed_root_batch,
)
from windows_solver.native_response_kernel import VettedNativeDeterminantKernel
from windows_solver.response_batches import (
    PrecisionCapabilities,
    build_campaign_plan,
)


class _AnalyticNativeKernel(VettedNativeDeterminantKernel):
    def __init__(self, fixed_root: complex) -> None:
        self.fixed_root = fixed_root
        self.calls: list[tuple[complex, complex, str]] = []

    def _standard_sn(self, job, policy):
        return object()

    def read_root(self, *args, **kwargs):
        raise AssertionError("fixed-root survey attempted a root read")

    def run_component(self, *args, **kwargs):
        raise AssertionError("fixed-root survey attempted the component engine")

    def _determinant(self, sn, omega, perturbation, policy):
        self.calls.append((omega, perturbation.amplitude, perturbation.profile_id))
        offset = omega - self.fixed_root
        amplitude = perturbation.amplitude
        return 3.0 * offset + 2.0 * amplitude + 0.1 * offset**3 + amplitude**3


class Binary64FixedRootSurveyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64,)),
        )

    def test_every_exterior_mechanism_uses_one_nine_sample_fixed_root_batch(self) -> None:
        leaves = {}
        for leaf in self.plan.leaves:
            if leaf.mechanism_id != "horizon-admittance":
                leaves.setdefault(leaf.mechanism_id, leaf)

        self.assertGreater(len(leaves), 1)
        for mechanism_id, leaf in leaves.items():
            with self.subTest(mechanism=mechanism_id):
                fixed_root = leaf.job.root.omega
                kernel = _AnalyticNativeKernel(fixed_root)

                batch = kernel.fixed_root_survey_batch(
                    job=leaf.job,
                    fixed_root=fixed_root,
                    branch_identity=leaf.job.root.branch_id,
                )

                self.assertEqual(BINARY64_FIXED_ROOT_SAMPLE_ROLES, batch.sample_roles)
                self.assertEqual(9, batch.sample_count)
                self.assertEqual(9, len(kernel.calls))
                self.assertEqual(0, batch.root_read_count)
                self.assertEqual(0, batch.julia_launch_count)
                self.assertTrue(all(call[2] for call in kernel.calls))

    def test_screening_reduces_the_raw_stencils_without_a_certificate(self) -> None:
        leaf = next(
            item
            for item in self.plan.leaves
            if item.mechanism_id == "exterior-light-ring"
        )
        fixed_root = leaf.job.root.omega
        batch = _AnalyticNativeKernel(fixed_root).fixed_root_survey_batch(
            job=leaf.job,
            fixed_root=fixed_root,
            branch_identity=leaf.job.root.branch_id,
        )

        result = screen_binary64_fixed_root_batch(batch)

        self.assertIs(Binary64SurveyDisposition.PRODUCED, result.disposition)
        self.assertAlmostEqual(-2.0 / 3.0, result.response_disk.centre.real, places=5)
        self.assertAlmostEqual(0.0, result.response_disk.centre.imag, places=12)
        self.assertGreater(result.response_disk.radius, 0.0)
        self.assertLessEqual(result.root_correction_upper_bound, 2.0e-11)
        self.assertEqual("not-claimed", result.determinant_certificate_status)

    def test_nonfinite_sample_fails_closed_at_the_batch_boundary(self) -> None:
        leaf = next(
            item
            for item in self.plan.leaves
            if item.mechanism_id == "exterior-alpha-one"
        )

        class _BrokenKernel(_AnalyticNativeKernel):
            def _determinant(self, sn, omega, perturbation, policy):
                return complex(float("nan"), 0.0)

        with self.assertRaisesRegex(ValueError, "finite"):
            _BrokenKernel(leaf.job.root.omega).fixed_root_survey_batch(
                job=leaf.job,
                fixed_root=leaf.job.root.omega,
                branch_identity=leaf.job.root.branch_id,
            )


if __name__ == "__main__":
    unittest.main()
