from __future__ import annotations

import math
from dataclasses import replace
import unittest

from windows_solver.response_reduction import (
    ResolvedComponentEvidence,
    SignedErrorContribution,
    build_empirical_error_gram,
    build_calibrated_projective_jacobian,
    signed_error_contribution_from_mapping,
    validate_empirical_error_gram,
)


class SignedChannelGramTests(unittest.TestCase):
    @staticmethod
    def components() -> tuple[ResolvedComponentEvidence, ...]:
        shared_receipt = "sha256:" + "1" * 64
        return (
            ResolvedComponentEvidence(
                component_id="component-a",
                centre=1.0 + 2.0j,
                units="dimensionless-response",
                contributions=(
                    SignedErrorContribution(
                        channel_id="shared:continuation:root-1",
                        family="continuation-seed-path",
                        shared_group="root-1",
                        delta=1.0 + 2.0j,
                        units="dimensionless-response",
                        source_receipt=shared_receipt,
                        scope="shared",
                    ),
                    SignedErrorContribution(
                        channel_id="local:component-a:signed-root",
                        family="signed-root",
                        shared_group="component-a",
                        delta=3.0 + 4.0j,
                        units="dimensionless-response",
                        source_receipt="sha256:" + "2" * 64,
                        scope="local",
                    ),
                ),
                recorded_discrepancies=(5.0,),
            ),
            ResolvedComponentEvidence(
                component_id="component-b",
                centre=-1.0 + 0.5j,
                units="dimensionless-response",
                contributions=(
                    SignedErrorContribution(
                        channel_id="shared:continuation:root-1",
                        family="continuation-seed-path",
                        shared_group="root-1",
                        delta=-1.0 + 0.5j,
                        units="dimensionless-response",
                        source_receipt=shared_receipt,
                        scope="shared",
                    ),
                    SignedErrorContribution(
                        channel_id="local:component-b:refinement",
                        family="refinement-holdout",
                        shared_group="component-b",
                        delta=0.0 + 2.0j,
                        units="dimensionless-response",
                        source_receipt="sha256:" + "3" * 64,
                        scope="local",
                    ),
                ),
                recorded_discrepancies=(1.5,),
            ),
        )

    def test_shared_and_local_signed_columns_build_exact_gram_and_disks(self) -> None:
        components = self.components()

        gram = build_empirical_error_gram(
            components,
            source_hashes=("sha256:" + "a" * 64,),
        )

        self.assertEqual(
            gram.basis,
            ("Re component-a", "Im component-a", "Re component-b", "Im component-b"),
        )
        self.assertEqual(
            gram.channel_ids,
            (
                "shared:continuation:root-1",
                "local:component-a:signed-root",
                "local:component-b:refinement",
            ),
        )
        self.assertEqual(
            gram.columns,
            (
                (1.0, 2.0, -1.0, 0.5),
                (3.0, 4.0, 0.0, 0.0),
                (0.0, 0.0, 0.0, 2.0),
            ),
        )
        self.assertEqual(
            gram.matrix,
            (
                (10.0, 14.0, -1.0, 0.5),
                (14.0, 20.0, -2.0, 1.0),
                (-1.0, -2.0, 1.0, -0.5),
                (0.5, 1.0, -0.5, 4.25),
            ),
        )
        self.assertAlmostEqual(gram.local_disks["component-a"], math.sqrt(5.0) + 5.0)
        self.assertAlmostEqual(gram.local_disks["component-b"], math.sqrt(1.25) + 2.0)
        self.assertEqual(gram.kind, "empirical-error-gram/deterministic-not-statistical")

    def test_exact_recomputation_rejects_resealed_non_psd_and_marginal_tamper(self) -> None:
        components = self.components()
        gram = build_empirical_error_gram(
            components, source_hashes=("sha256:" + "a" * 64,)
        )
        validate_empirical_error_gram(gram, components)

        matrix = [list(row) for row in gram.matrix]
        matrix[0][0] = -1.0
        non_psd = replace(gram, matrix=tuple(tuple(row) for row in matrix))
        with self.assertRaisesRegex(ValueError, "positive semidefinite"):
            validate_empirical_error_gram(non_psd, components)

        matrix = [list(row) for row in gram.matrix]
        for row in range(2):
            for column in range(2, 4):
                matrix[row][column] = 0.0
                matrix[column][row] = 0.0
        cross_term = replace(gram, matrix=tuple(tuple(row) for row in matrix))
        with self.assertRaisesRegex(ValueError, "exact recomputation"):
            validate_empirical_error_gram(cross_term, components)

        forged_disks = dict(gram.local_disks)
        forged_disks["component-a"] = 4.0
        marginal = replace(gram, local_disks=forged_disks)
        with self.assertRaisesRegex(ValueError, "discrepancy|disk"):
            validate_empirical_error_gram(marginal, components)

    def test_calibrated_normalized_quadrature_jacobian_propagates_j_g_jt(self) -> None:
        """Catches the old full-channel-amplitude angle perturbation."""

        basis = (
            "Re left-0", "Im left-0", "Re left-1", "Im left-1",
            "Re right-0", "Im right-0", "Re right-1", "Im right-1",
        )
        columns = (
            (1.0, 0.5, 0.0, 0.0, -0.25, 0.75, 0.0, 0.0),
            (0.0, 0.0, 0.2, -0.1, 0.0, 0.0, 0.3, 0.4),
        )
        matrix = tuple(tuple(
            sum(column[row] * column[col] for column in columns)
            for col in range(8)
        ) for row in range(8))
        diagnostic = build_calibrated_projective_jacobian(
            (1.0 + 0.0j, 2.0 + 1.0j),
            (1.1 + 0.2j, 1.5 - 0.3j),
            basis,
            matrix,
        )

        self.assertEqual(diagnostic.input_basis, basis)
        self.assertEqual(
            diagnostic.step_policy["relative_step_binary64_hex"],
            float(2.0 ** -24).hex(),
        )
        expected_jacobian = (
            -0.09974497703038063, -0.3590819237234721,
            -0.03191839464059236, 0.1635817665198154,
            0.21804974635449595, 0.36608352185056503,
            -0.24672295555044751, -0.1900433580111252,
        )
        for actual, expected in zip(diagnostic.jacobian, expected_jacobian):
            self.assertAlmostEqual(actual, expected, places=12)
        direct = sum(
            diagnostic.jacobian[row] * matrix[row][col] * diagnostic.jacobian[col]
            for row in range(8) for col in range(8)
        )
        self.assertEqual(diagnostic.scalar_gram, direct)
        self.assertAlmostEqual(diagnostic.scalar_gram, 0.03336044789683155)

        scaled = build_calibrated_projective_jacobian(
            (1.0 + 0.0j, 2.0 + 1.0j),
            (1.1 + 0.2j, 1.5 - 0.3j),
            basis,
            tuple(tuple(100.0 * value for value in row) for row in matrix),
        )
        self.assertEqual(scaled.step_policy, diagnostic.step_policy)
        self.assertEqual(scaled.jacobian, diagnostic.jacobian)

    def test_signed_schema_rejects_unsigned_unknown_duplicate_and_missing_evidence(self) -> None:
        contribution = self.components()[0].contributions[0]
        unsigned = contribution.to_mapping()
        unsigned.pop("signed_delta")
        unsigned["magnitude"] = 1.0
        with self.assertRaisesRegex(ValueError, "fields"):
            signed_error_contribution_from_mapping(unsigned)

        unknown = contribution.to_mapping()
        unknown["family"] = "atlas-global-multiplier"
        with self.assertRaisesRegex(ValueError, "unknown"):
            signed_error_contribution_from_mapping(unknown)

        missing_provenance = contribution.to_mapping()
        missing_provenance["source_receipt"] = ""
        with self.assertRaisesRegex(ValueError, "source_receipt"):
            signed_error_contribution_from_mapping(missing_provenance)

        nonfinite = contribution.to_mapping()
        nonfinite["signed_delta"]["real"] = float("nan")
        with self.assertRaisesRegex(ValueError, "finite"):
            signed_error_contribution_from_mapping(nonfinite)

        with self.assertRaisesRegex(ValueError, "duplicate"):
            ResolvedComponentEvidence(
                component_id="component-a",
                centre=1.0 + 0.0j,
                units=contribution.units,
                contributions=(contribution, contribution),
            )
        with self.assertRaisesRegex(ValueError, "required applicable"):
            ResolvedComponentEvidence(
                component_id="component-a",
                centre=1.0 + 0.0j,
                units=contribution.units,
                contributions=(contribution,),
                required_families=("precision-ladder-discrepancy",),
            )



if __name__ == "__main__":
    unittest.main()
