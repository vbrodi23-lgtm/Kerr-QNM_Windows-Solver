from __future__ import annotations

import unittest

from windows_solver.precision_tiers import (
    precision_tier_presentation,
    semantic_precision_presentation,
)


class PrecisionTierPresentationTests(unittest.TestCase):
    def test_m03_bigfloat_40_has_no_legacy_integer_boundary(self) -> None:
        presentation = semantic_precision_presentation("bigfloat-40")

        self.assertEqual(presentation.precision_tier, "bigfloat-40")
        self.assertEqual(presentation.nominal_decimal_digits, 40)
        self.assertGreaterEqual(presentation.working_precision_bits, 165)
        self.assertNotIn("legacy_tier_value", presentation.to_mapping())

    def test_binary64_is_not_presented_as_64_decimal_digits(self) -> None:
        presentation = precision_tier_presentation(64)

        self.assertEqual(
            presentation.to_mapping(),
            {
                "arithmetic": "IEEE-754 binary64",
                "legacy_tier_value": 64,
                "nominal_decimal_digits": 15.95,
                "precision_tier": "binary64",
                "presentation_label": "binary64 (~15.95 dec)",
            },
        )

    def test_bigfloat_tiers_retain_their_decimal_digit_meaning(self) -> None:
        precision80 = precision_tier_presentation(80)
        precision120 = precision_tier_presentation(120)

        self.assertEqual(precision80.precision_tier, "bigfloat-80")
        self.assertEqual(precision80.nominal_decimal_digits, 80)
        self.assertEqual(precision80.presentation_label, "BigFloat 80 dec")
        self.assertEqual(precision120.precision_tier, "bigfloat-120")
        self.assertEqual(precision120.nominal_decimal_digits, 120)
        self.assertEqual(precision120.presentation_label, "BigFloat 120 dec")

    def test_unknown_or_boolean_tiers_fail_closed(self) -> None:
        for value in (True, 15, 81, "64"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    ValueError, "legacy precision tier must be 64, 80, or 120"
                ):
                    precision_tier_presentation(value)


if __name__ == "__main__":
    unittest.main()
