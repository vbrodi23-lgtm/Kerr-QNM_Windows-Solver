from __future__ import annotations

import math
from dataclasses import replace
import unittest

from windows_solver.response_reduction import (
    ResolvedComponentEvidence,
    SignedErrorContribution,
    build_empirical_error_gram,
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
