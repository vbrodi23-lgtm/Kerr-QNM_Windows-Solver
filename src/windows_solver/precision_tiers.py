"""Derived presentation metadata for legacy mixed-unit precision tiers.

The campaign/checkpoint schema historically calls all tier selectors
``precision_digits``.  Value 64 actually selects IEEE-754 binary64; only 80
and 120 denote decimal-digit Julia BigFloat working precision.  Keep the
legacy values at compatibility boundaries and use this module for display and
report projections.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math


class PrecisionTier(StrEnum):
    """Authoritative semantic arithmetic tiers in promotion order."""

    BINARY64 = "binary64"
    BIGFLOAT_40 = "bigfloat-40"
    BIGFLOAT_80 = "bigfloat-80"
    BIGFLOAT_120 = "bigfloat-120"


_SEMANTIC_ORDER = (
    PrecisionTier.BINARY64,
    PrecisionTier.BIGFLOAT_40,
    PrecisionTier.BIGFLOAT_80,
    PrecisionTier.BIGFLOAT_120,
)
_NOMINAL_DECIMAL_DIGITS: dict[PrecisionTier, int | float] = {
    PrecisionTier.BINARY64: 15.95,
    PrecisionTier.BIGFLOAT_40: 40,
    PrecisionTier.BIGFLOAT_80: 80,
    PrecisionTier.BIGFLOAT_120: 120,
}


def precision_tier(value: object) -> PrecisionTier:
    """Normalize semantic tier input without interpreting legacy integers."""

    if isinstance(value, PrecisionTier):
        return value
    if isinstance(value, str):
        try:
            return PrecisionTier(value)
        except ValueError as error:
            raise ValueError(f"unknown semantic precision tier: {value}") from error
    raise ValueError("integer precision values require explicit legacy conversion")


def precision_tier_from_legacy(value: object) -> PrecisionTier:
    """Convert the historical mixed-unit boundary values explicitly."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("legacy precision tier must be 64, 80, or 120")
    try:
        return {
            64: PrecisionTier.BINARY64,
            80: PrecisionTier.BIGFLOAT_80,
            120: PrecisionTier.BIGFLOAT_120,
        }[value]
    except KeyError as error:
        raise ValueError("legacy precision tier must be 64, 80, or 120") from error


def next_precision_tier(value: PrecisionTier | str) -> PrecisionTier | None:
    """Return the next semantic tier, or ``None`` at the terminal tier."""

    current = precision_tier(value)
    index = _SEMANTIC_ORDER.index(current)
    return None if index + 1 == len(_SEMANTIC_ORDER) else _SEMANTIC_ORDER[index + 1]


def nominal_decimal_digits(value: PrecisionTier | str) -> int | float:
    return _NOMINAL_DECIMAL_DIGITS[precision_tier(value)]


def working_precision_bits(value: PrecisionTier | str) -> int:
    """Return actual binary significand/work precision for a semantic tier."""

    tier = precision_tier(value)
    if tier is PrecisionTier.BINARY64:
        return 53
    digits = int(_NOMINAL_DECIMAL_DIGITS[tier])
    return math.ceil(digits * math.log2(10)) + 32


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
