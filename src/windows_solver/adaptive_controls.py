"""Pure adaptive endpoint and request-level ODE budget contracts."""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from types import MappingProxyType
from typing import Mapping, Sequence

from .precision_tiers import (
    PrecisionTier,
    nominal_decimal_digits,
    precision_tier as normalize_precision_tier,
    working_precision_bits,
)


ODE_CALIBRATION_BLOCKER = (
    "TODO: [HUMAN MATH REVIEW REQUIRED - calibrated conversion from "
    "determinant/root error budget to ODE local tolerances is not yet established]"
)


class NoAdequateOuterEndpointError(RuntimeError):
    pass


class MissingODECalibrationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OuterEndpointCandidate:
    rho_out: float
    best_prefix_order: int
    predicted_reliable_digits: float
    last_term_ratio: float
    series_spread_abs: float
    cancellation_digits: float
    regularity_ok: bool
    last_term_ok: bool
    reason: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "rho_out", "predicted_reliable_digits", "last_term_ratio",
            "series_spread_abs", "cancellation_digits",
        ):
            value = getattr(self, name)
            if not math.isfinite(value):
                raise ValueError(f"outer endpoint {name} must be finite")
        if self.rho_out <= 0.0 or self.best_prefix_order < 1:
            raise ValueError("outer endpoint candidate geometry is invalid")
        if self.last_term_ratio < 0.0 or self.series_spread_abs < 0.0:
            raise ValueError("outer endpoint series evidence must be nonnegative")
        if self.cancellation_digits < 0.0:
            raise ValueError("outer endpoint cancellation must be nonnegative")

    def to_mapping(self) -> dict[str, object]:
        return {
            "best_prefix_order": self.best_prefix_order,
            "cancellation_digits": self.cancellation_digits,
            "last_term_ok": self.last_term_ok,
            "last_term_ratio": self.last_term_ratio,
            "predicted_reliable_digits": self.predicted_reliable_digits,
            "reason": self.reason,
            "regularity_ok": self.regularity_ok,
            "rho_out": self.rho_out,
            "series_spread_abs": self.series_spread_abs,
        }


@dataclass(frozen=True, slots=True)
class OuterEndpointSelection:
    candidates: tuple[OuterEndpointCandidate, ...]
    selected: OuterEndpointCandidate
    required_reliable_digits: float
    safety_margin_digits: float
    maximum_series_spread_abs: float
    maximum_cancellation_digits: float
    precision_tier: PrecisionTier

    def to_mapping(self) -> dict[str, object]:
        return {
            "candidates": [item.to_mapping() for item in self.candidates],
            "maximum_cancellation_digits": self.maximum_cancellation_digits,
            "maximum_series_spread_abs": self.maximum_series_spread_abs,
            "nominal_decimal_digits": nominal_decimal_digits(self.precision_tier),
            "precision_tier": self.precision_tier.value,
            "required_reliable_digits": self.required_reliable_digits,
            "safety_margin_digits": self.safety_margin_digits,
            "schema": "windows-solver.outer-endpoint-selection/1",
            "selected_rho_out": self.selected.rho_out,
            "working_precision_bits": working_precision_bits(self.precision_tier),
        }


def select_outer_endpoint(
    candidates: Sequence[OuterEndpointCandidate],
    *,
    required_reliable_digits: float,
    safety_margin_digits: float,
    maximum_series_spread_abs: float,
    maximum_cancellation_digits: float,
    precision_tier: PrecisionTier | str,
) -> OuterEndpointSelection:
    """Select the smallest candidate passing every declared preflight gate."""

    limits = (
        required_reliable_digits,
        safety_margin_digits,
        maximum_series_spread_abs,
        maximum_cancellation_digits,
    )
    if not candidates or any(not math.isfinite(item) for item in limits):
        raise ValueError("outer endpoint selection policy is invalid")
    if required_reliable_digits <= 0.0 or safety_margin_digits < 0.0:
        raise ValueError("outer endpoint reliable-digit policy is invalid")
    if maximum_series_spread_abs < 0.0 or maximum_cancellation_digits < 0.0:
        raise ValueError("outer endpoint series policy is invalid")
    ordered = sorted(candidates, key=lambda item: item.rho_out)
    if len({item.rho_out for item in ordered}) != len(ordered):
        raise ValueError("outer endpoint candidates must be unique")
    threshold = required_reliable_digits + safety_margin_digits
    tier = normalize_precision_tier(precision_tier)
    reasons: list[str | None] = []
    for item in ordered:
        if not item.regularity_ok:
            reasons.append("REGULARITY_GATE_FAILED")
        elif not item.last_term_ok:
            reasons.append("LAST_TERM_GATE_FAILED")
        elif item.series_spread_abs > maximum_series_spread_abs:
            reasons.append("SERIES_SPREAD_GATE_FAILED")
        elif item.cancellation_digits > maximum_cancellation_digits:
            reasons.append("CANCELLATION_GATE_FAILED")
        elif item.predicted_reliable_digits <= threshold:
            reasons.append("INSUFFICIENT_RELIABLE_DIGITS")
        else:
            reasons.append(None)
    adequate_index = next((i for i, reason in enumerate(reasons) if reason is None), None)
    if adequate_index is None:
        raise NoAdequateOuterEndpointError("no outer endpoint passed every preflight gate")
    evidence = tuple(
        replace(
            item,
            reason=(
                reason
                if reason is not None
                else "SELECTED_NEAREST_ADEQUATE"
                if index == adequate_index
                else "ADEQUATE_NOT_SELECTED"
            ),
        )
        for index, (item, reason) in enumerate(zip(ordered, reasons, strict=True))
    )
    return OuterEndpointSelection(
        candidates=evidence,
        selected=evidence[adequate_index],
        required_reliable_digits=required_reliable_digits,
        safety_margin_digits=safety_margin_digits,
        maximum_series_spread_abs=maximum_series_spread_abs,
        maximum_cancellation_digits=maximum_cancellation_digits,
        precision_tier=tier,
    )


@dataclass(frozen=True, slots=True)
class ODEToleranceCalibration:
    identity: str
    endpoint_series_fraction: float
    coordinate_inversion_fraction: float
    homogeneous_transport_fraction: float
    angular_fraction: float
    derivative_stencil_fraction: float
    coordinate_relative_factor: float
    coordinate_absolute_factor: float
    homogeneous_relative_factor: float
    homogeneous_absolute_factor: float

    def __post_init__(self) -> None:
        if not self.identity:
            raise ValueError("ODE tolerance calibration identity is required")
        values = tuple(getattr(self, name) for name in self.__dataclass_fields__ if name != "identity")
        if any(not math.isfinite(item) or item <= 0.0 for item in values):
            raise ValueError("ODE tolerance calibration values must be finite and positive")
        fractions = values[:5]
        if not math.isclose(sum(fractions), 1.0, rel_tol=0.0, abs_tol=1.0e-12):
            raise ValueError("ODE determinant allocation fractions must sum to one")


@dataclass(frozen=True, slots=True)
class ODEErrorBudget:
    required_root_correction_abs: float
    determinant_derivative_lower_bound_abs: float
    determinant_error_budget_abs: float
    determinant_allocations: Mapping[str, float]
    coordinate_reltol: float
    coordinate_abstol: float
    homogeneous_reltol: float
    homogeneous_abstol: float
    precision_tier: PrecisionTier
    calibration_identity: str

    def __post_init__(self) -> None:
        tier = normalize_precision_tier(self.precision_tier)
        object.__setattr__(self, "precision_tier", tier)
        if not self.calibration_identity:
            raise ValueError("ODE error budget calibration identity is required")
        scalars = (
            self.required_root_correction_abs,
            self.determinant_derivative_lower_bound_abs,
            self.determinant_error_budget_abs,
            self.coordinate_reltol,
            self.coordinate_abstol,
            self.homogeneous_reltol,
            self.homogeneous_abstol,
        )
        if any(not math.isfinite(item) or item <= 0.0 for item in scalars):
            raise ValueError("ODE error budget values must be finite, positive, and representable")
        derived_total = (
            self.required_root_correction_abs
            * self.determinant_derivative_lower_bound_abs
        )
        if self.determinant_error_budget_abs != derived_total:
            raise ValueError(
                "ODE determinant error budget must equal the root correction "
                "times the determinant derivative lower bound"
            )
        expected_names = (
            "endpoint_series",
            "coordinate_inversion",
            "homogeneous_radial_transport",
            "angular_calculation",
            "determinant_derivative_stencils",
        )
        if set(self.determinant_allocations) != set(expected_names):
            raise ValueError("ODE determinant allocations are incomplete")
        allocations = {
            name: self.determinant_allocations[name] for name in expected_names
        }
        if any(
            isinstance(item, bool)
            or not isinstance(item, (int, float))
            or not math.isfinite(item)
            or item <= 0.0
            for item in allocations.values()
        ):
            raise ValueError("ODE determinant allocations must be finite, positive, and representable")
        if not math.isclose(
            math.fsum(allocations.values()),
            self.determinant_error_budget_abs,
            rel_tol=1.0e-12,
            abs_tol=0.0,
        ):
            raise ValueError("ODE determinant allocations do not match the total budget")
        object.__setattr__(self, "determinant_allocations", MappingProxyType(allocations))

    def to_mapping(self) -> dict[str, object]:
        return {
            "calibration_identity": self.calibration_identity,
            "coordinate_abstol": self.coordinate_abstol,
            "coordinate_reltol": self.coordinate_reltol,
            "determinant_allocations": dict(self.determinant_allocations),
            "determinant_derivative_lower_bound_abs": self.determinant_derivative_lower_bound_abs,
            "determinant_error_budget_abs": self.determinant_error_budget_abs,
            "homogeneous_abstol": self.homogeneous_abstol,
            "homogeneous_reltol": self.homogeneous_reltol,
            "nominal_decimal_digits": nominal_decimal_digits(self.precision_tier),
            "precision_tier": self.precision_tier.value,
            "required_root_correction_abs": self.required_root_correction_abs,
            "schema": "windows-solver.ode-error-budget/1",
            "working_precision_bits": working_precision_bits(self.precision_tier),
        }


def derive_ode_error_budget(
    *,
    required_root_correction_abs: float,
    determinant_derivative_lower_bound_abs: float,
    precision_tier: PrecisionTier | str,
    calibration: ODEToleranceCalibration | None,
) -> ODEErrorBudget:
    if calibration is None:
        raise MissingODECalibrationError(ODE_CALIBRATION_BLOCKER)
    if (
        not math.isfinite(required_root_correction_abs)
        or required_root_correction_abs <= 0.0
        or not math.isfinite(determinant_derivative_lower_bound_abs)
        or determinant_derivative_lower_bound_abs <= 0.0
    ):
        raise ValueError("ODE request error inputs must be finite and positive")
    tier = normalize_precision_tier(precision_tier)
    total = required_root_correction_abs * determinant_derivative_lower_bound_abs
    if not math.isfinite(total) or total <= 0.0:
        raise ValueError("ODE determinant error budget is not finite, positive, and representable")
    fractions = (
        ("endpoint_series", calibration.endpoint_series_fraction),
        ("coordinate_inversion", calibration.coordinate_inversion_fraction),
        ("homogeneous_radial_transport", calibration.homogeneous_transport_fraction),
        ("angular_calculation", calibration.angular_fraction),
        ("determinant_derivative_stencils", calibration.derivative_stencil_fraction),
    )
    allocations: dict[str, float] = {}
    allocated = 0.0
    for name, fraction in fractions[:-1]:
        allocations[name] = total * fraction
        allocated += allocations[name]
    allocations[fractions[-1][0]] = total - allocated
    if any(not math.isfinite(item) or item <= 0.0 for item in allocations.values()):
        raise ValueError("ODE determinant allocations are not finite, positive, and representable")
    coordinate = allocations["coordinate_inversion"]
    homogeneous = allocations["homogeneous_radial_transport"]
    tolerances = (
        coordinate * calibration.coordinate_relative_factor,
        coordinate * calibration.coordinate_absolute_factor,
        homogeneous * calibration.homogeneous_relative_factor,
        homogeneous * calibration.homogeneous_absolute_factor,
    )
    if any(not math.isfinite(item) or item <= 0.0 for item in tolerances):
        raise ValueError("ODE tolerances are not finite, positive, and representable")
    return ODEErrorBudget(
        required_root_correction_abs=required_root_correction_abs,
        determinant_derivative_lower_bound_abs=determinant_derivative_lower_bound_abs,
        determinant_error_budget_abs=total,
        determinant_allocations=allocations,
        coordinate_reltol=tolerances[0],
        coordinate_abstol=tolerances[1],
        homogeneous_reltol=tolerances[2],
        homogeneous_abstol=tolerances[3],
        precision_tier=tier,
        calibration_identity=calibration.identity,
    )
