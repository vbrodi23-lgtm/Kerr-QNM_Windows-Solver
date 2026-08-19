"""Conservative complex-disk arithmetic for promoted response evidence."""

from __future__ import annotations

from dataclasses import dataclass
import math


class UncertaintyPropagationError(ValueError):
    """Base class for invalid or unbounded uncertainty propagation."""


class ZeroContainingDiskError(UncertaintyPropagationError):
    """Raised when an operation requires a disk that excludes zero."""

    def __init__(self, disk_name: str) -> None:
        self.disk_name = disk_name
        super().__init__(f"{disk_name} disk contains zero")


@dataclass(frozen=True, slots=True)
class ComplexDisk:
    centre: complex
    radius: float
    exact_zero_radius: bool = False

    def __post_init__(self) -> None:
        centre = complex(self.centre)
        radius = float(self.radius)
        if not math.isfinite(centre.real) or not math.isfinite(centre.imag):
            raise ValueError("complex disk centre must be finite")
        if not math.isfinite(radius) or radius < 0.0:
            raise ValueError("complex disk radius must be finite and nonnegative")
        if radius == 0.0 and not self.exact_zero_radius:
            raise ValueError("zero radius requires explicit exact-zero provenance")
        if radius != 0.0 and self.exact_zero_radius:
            raise ValueError("exact-zero provenance requires a zero radius")
        object.__setattr__(self, "centre", centre)
        object.__setattr__(self, "radius", radius)

    @property
    def contains_zero(self) -> bool:
        return abs(self.centre) <= self.radius

    def to_mapping(self) -> dict[str, object]:
        return {
            "centre": {"imaginary": self.centre.imag, "real": self.centre.real},
            "exact_zero_radius": self.exact_zero_radius,
            "radius": self.radius,
        }

    def __neg__(self) -> "ComplexDisk":
        return ComplexDisk(-self.centre, self.radius, self.exact_zero_radius)

    def __mul__(self, other: "ComplexDisk") -> "ComplexDisk":
        if not isinstance(other, ComplexDisk):
            return NotImplemented
        radius = (
            abs(self.centre) * other.radius
            + abs(other.centre) * self.radius
            + self.radius * other.radius
        )
        return ComplexDisk(
            self.centre * other.centre,
            radius,
            exact_zero_radius=(
                radius == 0.0
                and self.exact_zero_radius
                and other.exact_zero_radius
            ),
        )

    def inverse(self, *, disk_name: str = "denominator") -> "ComplexDisk":
        if self.contains_zero:
            raise ZeroContainingDiskError(disk_name)
        centre_abs = abs(self.centre)
        radius = self.radius / (centre_abs * (centre_abs - self.radius))
        return ComplexDisk(
            1.0 / self.centre,
            radius,
            exact_zero_radius=(radius == 0.0 and self.exact_zero_radius),
        )

    def __truediv__(self, other: "ComplexDisk") -> "ComplexDisk":
        if not isinstance(other, ComplexDisk):
            return NotImplemented
        if other.contains_zero:
            raise ZeroContainingDiskError("denominator")
        denominator_floor = abs(other.centre) - other.radius
        radius = (
            self.radius / denominator_floor
            + abs(self.centre) * other.radius
            / (abs(other.centre) * denominator_floor)
        )
        return ComplexDisk(
            self.centre / other.centre,
            radius,
            exact_zero_radius=(
                radius == 0.0
                and self.exact_zero_radius
                and other.exact_zero_radius
            ),
        )


def exterior_response_disk(
    *, coordinate_derivative: ComplexDisk, frequency_derivative: ComplexDisk
) -> ComplexDisk:
    if frequency_derivative.contains_zero:
        raise ZeroContainingDiskError("frequency_derivative")
    denominator_floor = abs(frequency_derivative.centre) - frequency_derivative.radius
    radius = (
        coordinate_derivative.radius / denominator_floor
        + abs(coordinate_derivative.centre) * frequency_derivative.radius
        / (abs(frequency_derivative.centre) * denominator_floor)
    )
    return ComplexDisk(
        -coordinate_derivative.centre / frequency_derivative.centre,
        radius,
        exact_zero_radius=(
            radius == 0.0
            and coordinate_derivative.exact_zero_radius
            and frequency_derivative.exact_zero_radius
        ),
    )


def horizon_response_disk(
    *, horizon_frequency: ComplexDisk, determinant_derivative: ComplexDisk
) -> ComplexDisk:
    if horizon_frequency.contains_zero:
        raise ZeroContainingDiskError("horizon_frequency")
    if determinant_derivative.contains_zero:
        raise ZeroContainingDiskError("determinant_derivative")
    denominator_centre = 2.0j * horizon_frequency.centre * determinant_derivative.centre
    denominator_radius = 2.0 * (
        abs(horizon_frequency.centre) * determinant_derivative.radius
        + abs(determinant_derivative.centre) * horizon_frequency.radius
        + horizon_frequency.radius * determinant_derivative.radius
    )
    if abs(denominator_centre) <= denominator_radius:
        raise ZeroContainingDiskError("analytic_horizon_denominator")
    centre_abs = abs(denominator_centre)
    radius = denominator_radius / (
        centre_abs * (centre_abs - denominator_radius)
    )
    return ComplexDisk(
        1.0 / denominator_centre,
        radius,
        exact_zero_radius=(
            radius == 0.0
            and horizon_frequency.exact_zero_radius
            and determinant_derivative.exact_zero_radius
        ),
    )
