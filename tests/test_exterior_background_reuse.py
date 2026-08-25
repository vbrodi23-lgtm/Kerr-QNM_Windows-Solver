from __future__ import annotations

import copy
import unittest

from windows_solver.response_engine import (
    BACKGROUND_EQUIVALENCE_IDENTITY,
    CANONICAL_EXTERIOR_BACKGROUND_IDENTITY,
    BackgroundEquivalenceReceipt,
    NumericalPolicy,
    VettedNativeDeterminantKernel,
    build_exterior_background_reuse_key,
    canonical_background_from_binary64_batch,
    screen_binary64_reused_background_batch,
)
from windows_solver.response_batches import (
    PrecisionCapabilities,
    build_campaign_plan,
)


class _AnalyticKernel(VettedNativeDeterminantKernel):
    def __init__(self, fixed_root: complex) -> None:
        self.fixed_root = fixed_root
        self.calls = []

    def _standard_sn(self, job, policy):
        return object()

    def _determinant(self, sn, omega, perturbation, policy):
        self.calls.append((omega, perturbation))
        amplitude = getattr(perturbation, "amplitude", 0.0j)
        return 3.0 * (omega - self.fixed_root) + 2.0 * amplitude


class ExteriorBackgroundReuseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64,)),
        )
        exterior = [
            leaf for leaf in cls.plan.leaves
            if leaf.mechanism_id != "horizon-admittance"
        ]
        cls.first = exterior[0]
        cls.second = next(
            leaf for leaf in exterior
            if leaf.mechanism_id != cls.first.mechanism_id
            and leaf.job.root.identity_sha256 == cls.first.job.root.identity_sha256
        )
        cls.root_seal_sha256 = "a" * 64

    def _key(self, leaf):
        return build_exterior_background_reuse_key(
            leaf.job,
            root_seal_sha256=self.root_seal_sha256,
        )

    def test_first_batch_uses_canonical_background_without_mechanism_support(self) -> None:
        kernel = _AnalyticKernel(self.first.job.root.omega)

        batch = kernel.fixed_root_survey_batch(
            job=self.first.job,
            fixed_root=self.first.job.root.omega,
            branch_identity=self.first.job.root.branch_id,
        )

        self.assertTrue(
            all(not hasattr(item[1], "support") for item in kernel.calls[:5])
        )
        self.assertTrue(all(hasattr(item[1], "support") for item in kernel.calls[5:]))

    def test_reuse_requires_exact_key_and_authenticated_equivalence_receipt(self) -> None:
        first_kernel = _AnalyticKernel(self.first.job.root.omega)
        first_batch = first_kernel.fixed_root_survey_batch(
            job=self.first.job,
            fixed_root=self.first.job.root.omega,
            branch_identity=self.first.job.root.branch_id,
        )
        background = canonical_background_from_binary64_batch(
            first_batch, self._key(self.first)
        )
        second_key = self._key(self.second)
        self.assertEqual(background.reuse_key, second_key)
        receipt = BackgroundEquivalenceReceipt.issue(
            reuse_key=second_key,
            job=self.second.job,
            canonical_background_sha256=background.sha256,
        )
        second_kernel = _AnalyticKernel(self.second.job.root.omega)

        reused = second_kernel.fixed_root_reused_background_batch(
            job=self.second.job,
            fixed_root=self.second.job.root.omega,
            branch_identity=self.second.job.root.branch_id,
            background=background,
            equivalence_receipt=receipt,
        )
        result = screen_binary64_reused_background_batch(background, reused)

        self.assertEqual(4, reused.sample_count)
        self.assertEqual(4, len(second_kernel.calls))
        self.assertTrue(all(sample.role.startswith("DC_") for sample in reused.samples))
        self.assertEqual("PROMOTION_PENDING_RESPONSE", result.disposition.value)
        self.assertEqual(
            "BLOCKED_BY_REVIEWED_ERROR_EVIDENCE", result.reason_code
        )
        self.assertIsNone(result.response_disk)
        self.assertEqual(BACKGROUND_EQUIVALENCE_IDENTITY, receipt.identity)
        self.assertEqual(
            CANONICAL_EXTERIOR_BACKGROUND_IDENTITY,
            second_key.background_operation_identity,
        )

    def test_missing_mismatched_or_tampered_receipt_disables_reuse(self) -> None:
        first_kernel = _AnalyticKernel(self.first.job.root.omega)
        first_batch = first_kernel.fixed_root_survey_batch(
            job=self.first.job,
            fixed_root=self.first.job.root.omega,
            branch_identity=self.first.job.root.branch_id,
        )
        background = canonical_background_from_binary64_batch(
            first_batch, self._key(self.first)
        )
        key = self._key(self.second)
        kernel = _AnalyticKernel(self.second.job.root.omega)
        with self.assertRaisesRegex(ValueError, "equivalence"):
            kernel.fixed_root_reused_background_batch(
                job=self.second.job,
                fixed_root=self.second.job.root.omega,
                branch_identity=self.second.job.root.branch_id,
                background=background,
                equivalence_receipt=None,
            )
        fallback_kernel = _AnalyticKernel(self.second.job.root.omega)
        fallback = fallback_kernel.fixed_root_survey_with_optional_background(
            job=self.second.job,
            fixed_root=self.second.job.root.omega,
            branch_identity=self.second.job.root.branch_id,
            background=background,
            equivalence_receipt=None,
        )
        self.assertEqual(9, fallback.sample_count)
        self.assertEqual(9, len(fallback_kernel.calls))

        receipt = BackgroundEquivalenceReceipt.issue(
            reuse_key=key,
            job=self.second.job,
            canonical_background_sha256=background.sha256,
        )
        raw = receipt.to_mapping()
        tampered = copy.deepcopy(raw)
        tampered["canonical_background_sha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "digest"):
            BackgroundEquivalenceReceipt.from_mapping(tampered)

    def test_reuse_key_covers_every_governing_identity_field(self) -> None:
        fields = set(self._key(self.first).to_mapping())
        self.assertEqual(
            {
                "schema",
                "root_seal_sha256",
                "root_identity",
                "branch_identity",
                "angular_identity",
                "background_operation_identity",
                "determinant_family",
                "determinant_convention",
                "determinant_normalisation",
                "match_readout_convention",
                "backend_identity",
                "numerical_controls_sha256",
                "arithmetic_tier",
                "working_precision",
                "frequency_step_policy",
            },
            fields,
        )

    def test_equivalence_receipts_cover_all_selected_mechanisms_at_spin_extremes(self) -> None:
        exterior = [
            leaf for leaf in self.plan.leaves
            if leaf.mechanism_id != "horizon-admittance"
        ]
        by_mechanism = {}
        for leaf in exterior:
            by_mechanism.setdefault(leaf.mechanism_id, []).append(leaf)
        for leaves in by_mechanism.values():
            ordered = sorted(leaves, key=lambda leaf: leaf.job.spin)
            for leaf in (ordered[0], ordered[-1]):
                key = self._key(leaf)
                receipt = BackgroundEquivalenceReceipt.issue(
                    reuse_key=key,
                    job=leaf.job,
                    canonical_background_sha256="c" * 64,
                )
                self.assertEqual(leaf.mechanism_id, receipt.mechanism_id)


if __name__ == "__main__":
    unittest.main()
