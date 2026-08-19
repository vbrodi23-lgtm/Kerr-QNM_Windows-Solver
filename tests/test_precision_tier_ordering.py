from __future__ import annotations

import unittest

from windows_solver.precision_tiers import (
    PrecisionTier,
    next_precision_tier,
    precision_tier,
    precision_tier_from_legacy,
    working_precision_bits,
)


class PrecisionTierOrderingTests(unittest.TestCase):
    def test_semantic_order_includes_intermediate_bigfloat_tier(self) -> None:
        tiers = [PrecisionTier.BINARY64]
        while (next_tier := next_precision_tier(tiers[-1])) is not None:
            tiers.append(next_tier)
        self.assertEqual(
            tiers,
            [
                PrecisionTier.BINARY64,
                PrecisionTier.BIGFLOAT_40,
                PrecisionTier.BIGFLOAT_80,
                PrecisionTier.BIGFLOAT_120,
            ],
        )

    def test_working_bits_are_distinct_from_nominal_decimal_digits(self) -> None:
        self.assertEqual(working_precision_bits(PrecisionTier.BINARY64), 53)
        self.assertEqual(working_precision_bits(PrecisionTier.BIGFLOAT_40), 165)
        self.assertEqual(working_precision_bits(PrecisionTier.BIGFLOAT_80), 298)
        self.assertEqual(working_precision_bits(PrecisionTier.BIGFLOAT_120), 431)

    def test_legacy_conversion_is_explicit(self) -> None:
        self.assertEqual(precision_tier("bigfloat-40"), PrecisionTier.BIGFLOAT_40)
        with self.assertRaisesRegex(ValueError, "legacy"):
            precision_tier(64)
        self.assertEqual(precision_tier_from_legacy(64), PrecisionTier.BINARY64)
        self.assertEqual(precision_tier_from_legacy(80), PrecisionTier.BIGFLOAT_80)
        self.assertEqual(precision_tier_from_legacy(120), PrecisionTier.BIGFLOAT_120)


if __name__ == "__main__":
    unittest.main()
