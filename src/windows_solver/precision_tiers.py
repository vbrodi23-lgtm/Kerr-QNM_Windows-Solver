"""Derived presentation metadata for legacy mixed-unit precision tiers.

The campaign/checkpoint schema historically calls all tier selectors
``precision_digits``.  Value 64 actually selects IEEE-754 binary64; only 80
and 120 denote decimal-digit Julia BigFloat working precision.  Keep the
legacy values at compatibility boundaries and use this module for display and
report projections.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PrecisionTierPresentation:
    """Unambiguous, derived metadata for one legacy precision tier value."""

    precision_tier: str
    arithmetic: str
    legacy_tier_value: int
    nominal_decimal_digits: int | float
    presentation_label: str

    def to_mapping(self) -> dict[str, object]:
        return {
            "arithmetic": self.arithmetic,
            "legacy_tier_value": self.legacy_tier_value,
            "nominal_decimal_digits": self.nominal_decimal_digits,
            "precision_tier": self.precision_tier,
            "presentation_label": self.presentation_label,
        }


_PRESENTATIONS = {
    64: PrecisionTierPresentation(
        precision_tier="binary64",
        arithmetic="IEEE-754 binary64",
        legacy_tier_value=64,
        nominal_decimal_digits=15.95,
        presentation_label="binary64 (~15.95 dec)",
    ),
    80: PrecisionTierPresentation(
        precision_tier="bigfloat-80",
        arithmetic="Julia BigFloat",
        legacy_tier_value=80,
        nominal_decimal_digits=80,
        presentation_label="BigFloat 80 dec",
    ),
    120: PrecisionTierPresentation(
        precision_tier="bigfloat-120",
        arithmetic="Julia BigFloat",
        legacy_tier_value=120,
        nominal_decimal_digits=120,
        presentation_label="BigFloat 120 dec",
    ),
}


def precision_tier_presentation(value: object) -> PrecisionTierPresentation:
    """Return derived presentation metadata without altering legacy data."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("legacy precision tier must be 64, 80, or 120")
    try:
        return _PRESENTATIONS[value]
    except KeyError as error:
        raise ValueError(
            "legacy precision tier must be 64, 80, or 120"
        ) from error
