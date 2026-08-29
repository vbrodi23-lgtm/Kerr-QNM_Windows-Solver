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


NORMALISED_HORIZON_CHART_DETERMINANT_NORMALISATION = (
    "cinc-over-cref-minus-reflectivity/v1"
)


def normalised_horizon_chart_response_disk(
    *,
    horizon_frequency: ComplexDisk,
    determinant_derivative: ComplexDisk,
    determinant_normalisation: str,
) -> ComplexDisk:
    """Return ``1 / (2 i p_H D-hat_omega)`` for the normalised horizon chart.

    The Julia worker's promoted horizon determinant is evaluated as
    ``D-hat = Cinc/Cref - R`` (``cinc-over-cref-minus-reflectivity/v1``), for
    which ``d D-hat/dR = -1`` at the unperturbed point.  That makes the
    response a genuine unit-numerator quotient under this specific chart --
    not a simplification or a stand-in for a missing numerator.

    This is NOT a general horizon response formula.  Under the raw-Wronskian
    chart (``D = W[Xin + R Xout, Xup]``), ``dD/dR = D_H`` is not 1, and
    dropping that numerator would silently discard the horizon carrier ratio.
    Use ``horizon_response_disk`` for that chart instead.

    ``determinant_normalisation`` must be supplied by the caller and is
    checked against the one identity this formula is valid for, so a future
    caller cannot feed a raw-Wronskian derivative into the unit-numerator
    quotient by mistake.
    """
    if (
        determinant_normalisation
        != NORMALISED_HORIZON_CHART_DETERMINANT_NORMALISATION
    ):
        raise ValueError(
            "normalised_horizon_chart_response_disk requires determinant "
            f"normalisation {NORMALISED_HORIZON_CHART_DETERMINANT_NORMALISATION!r}; "
            f"got {determinant_normalisation!r}"
        )
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


def horizon_response_disk(
    *,
    horizon_numerator: ComplexDisk,
    horizon_frequency: ComplexDisk,
    determinant_derivative: ComplexDisk,
) -> ComplexDisk:
    """Return ``-D_H / (2 i p_H D_0,omega)`` for the raw-Wronskian chart.

    The product is formed as one complex-ball denominator and the numerator is
    explicit.  Use this for the raw-Wronskian determinant
    (``D = W[Xin + R Xout, Xup]``); its derivative with respect to ``R`` is
    ``D_H``, not 1, so the numerator must stay explicit here.  For the
    normalised ``Cinc/Cref - R`` chart, where the derivative genuinely is a
    unit numerator, use ``normalised_horizon_chart_response_disk`` instead.
    """

    if horizon_numerator.contains_zero and horizon_numerator.radius == 0.0:
        # Exact zero is mathematically valid; ComplexDisk itself protects the
        # provenance.  Keep this branch only to make the intentional behaviour
        # explicit rather than treating numerator zero as a denominator error.
        pass
    if horizon_frequency.contains_zero:
        raise ZeroContainingDiskError("horizon_frequency")
    if determinant_derivative.contains_zero:
        raise ZeroContainingDiskError("determinant_derivative")
    exact_two_i = ComplexDisk(2.0j, 0.0, exact_zero_radius=True)
    denominator = exact_two_i * horizon_frequency * determinant_derivative
    if denominator.contains_zero:
        raise ZeroContainingDiskError("analytic_horizon_denominator")
    return (-horizon_numerator) / denominator


def horizon_frequency_disk(
    *,
    root: ComplexDisk,
    azimuthal_index: int,
    background_omega_h: ComplexDisk,
) -> ComplexDisk:
    """Construct ``p_H = omega - m Omega_H`` with rounding included.

    ``background_omega_h`` carries the exact-background transform's directed
    rounding contribution (and any declared physical background uncertainty).
    The final subtraction is rounded outward once more.
    """

    if isinstance(azimuthal_index, bool) or not isinstance(azimuthal_index, int):
        raise ValueError("horizon azimuthal index is invalid")
    centre = root.centre - azimuthal_index * background_omega_h.centre
    rounding = math.ulp(centre.real) + math.ulp(centre.imag)
    radius = (
        root.radius
        + abs(azimuthal_index) * background_omega_h.radius
        + rounding
    )
    return ComplexDisk(centre, radius)


@dataclass(frozen=True, slots=True)
class HorizonChartBasePartials:
    """Exact coordinate partials at the unperturbed ``deltaB = 0`` base."""

    dR_ddeltaB: ComplexDisk
    dR_domega_at_deltaB: complex


def horizon_chart_base_partials(
    horizon_frequency: ComplexDisk,
) -> HorizonChartBasePartials:
    """Return chart derivatives without introducing an invalid chain term."""

    exact_one = ComplexDisk(1.0 + 0.0j, 0.0, exact_zero_radius=True)
    exact_two_i = ComplexDisk(2.0j, 0.0, exact_zero_radius=True)
    return HorizonChartBasePartials(
        dR_ddeltaB=exact_one / (exact_two_i * horizon_frequency),
        dR_domega_at_deltaB=0.0j,
    )
