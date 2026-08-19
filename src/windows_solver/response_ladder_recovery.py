from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
from typing import Sequence, TypeVar

from .precision_tiers import PrecisionTier, next_precision_tier


class RecoveryDisposition(StrEnum):
    RECOVERED = "RECOVERED"
    EXPAND_AMPLITUDE = "EXPAND_AMPLITUDE"
    PROMOTE_READOUTS = "PROMOTE_READOUTS"


@dataclass(frozen=True, slots=True)
class LadderReadout:
    omega: complex
    root_error: float
    branch_ok: bool
    diagnostic_ok: bool
    precision_tier: PrecisionTier

    def __post_init__(self) -> None:
        if not math.isfinite(self.omega.real) or not math.isfinite(self.omega.imag):
            raise ValueError("ladder readout omega must be finite")
        if not math.isfinite(self.root_error) or self.root_error < 0.0:
            raise ValueError("ladder readout root error must be finite and nonnegative")


@dataclass(frozen=True, slots=True)
class LadderLevel:
    epsilon: float
    real_plus: LadderReadout
    real_minus: LadderReadout
    imaginary_plus: LadderReadout
    imaginary_minus: LadderReadout

    @classmethod
    def from_signed_readouts(
        cls,
        *,
        epsilon: float,
        real_plus: LadderReadout,
        real_minus: LadderReadout,
        imaginary_plus: LadderReadout,
        imaginary_minus: LadderReadout,
    ) -> "LadderLevel":
        return cls(
            float(epsilon),
            real_plus,
            real_minus,
            imaginary_plus,
            imaginary_minus,
        )

    def __post_init__(self) -> None:
        if not math.isfinite(self.epsilon) or self.epsilon <= 0.0:
            raise ValueError("ladder epsilon must be finite and positive")

    @property
    def readouts(self) -> tuple[LadderReadout, ...]:
        return (
            self.real_plus,
            self.real_minus,
            self.imaginary_plus,
            self.imaginary_minus,
        )

    @property
    def real_secant(self) -> complex:
        return (self.real_plus.omega - self.real_minus.omega) / (2.0 * self.epsilon)

    @property
    def imaginary_secant(self) -> complex:
        return (
            self.imaginary_plus.omega - self.imaginary_minus.omega
        ) / (2.0j * self.epsilon)

    @property
    def even_remainder(self) -> float:
        real_midpoint = (self.real_plus.omega + self.real_minus.omega) / 2.0
        imaginary_midpoint = (
            self.imaginary_plus.omega + self.imaginary_minus.omega
        ) / 2.0
        return abs(real_midpoint - imaginary_midpoint)

    @property
    def even_remainder_error(self) -> float:
        return sum(item.root_error for item in self.readouts) / 2.0

    def signal_ratios(self, signal_factor: float) -> tuple[float, float]:
        if not math.isfinite(signal_factor) or signal_factor <= 0.0:
            raise ValueError("signal factor must be finite and positive")
        real_signal = abs(self.real_plus.omega - self.real_minus.omega) / 2.0
        imaginary_signal = abs(
            self.imaginary_plus.omega - self.imaginary_minus.omega
        ) / 2.0
        real_noise = signal_factor * (
            self.real_plus.root_error + self.real_minus.root_error
        )
        imaginary_noise = signal_factor * (
            self.imaginary_plus.root_error + self.imaginary_minus.root_error
        )
        return (
            math.inf if real_noise == 0.0 else real_signal / real_noise,
            math.inf if imaginary_noise == 0.0 else imaginary_signal / imaginary_noise,
        )


@dataclass(frozen=True, slots=True)
class LadderPolicy:
    signal_factor: float
    minimum_window: int
    maximum_epsilon: float
    required_order: float
    order_tolerance: float
    axis_tolerance_factor: float
    even_remainder_factor: float

    def __post_init__(self) -> None:
        finite_positive = (
            self.signal_factor,
            self.maximum_epsilon,
            self.required_order,
            self.axis_tolerance_factor,
            self.even_remainder_factor,
        )
        if not all(math.isfinite(item) and item > 0.0 for item in finite_positive):
            raise ValueError("ladder policy scales must be finite and positive")
        if self.minimum_window < 4:
            raise ValueError("ladder recovery requires windows of at least four levels")
        if not math.isfinite(self.order_tolerance) or self.order_tolerance < 0.0:
            raise ValueError("order tolerance must be finite and nonnegative")


@dataclass(frozen=True, slots=True)
class WindowLevelEvidence:
    epsilon: float
    real_signal_ratio: float
    imaginary_signal_ratio: float
    signal_ok: bool


@dataclass(frozen=True, slots=True)
class WindowEvidence:
    epsilons: tuple[float, ...]
    levels: tuple[WindowLevelEvidence, ...]
    real_order: float | None
    imaginary_order: float | None
    real_order_ok: bool
    imaginary_order_ok: bool
    axis_ok: bool
    even_remainder_ok: bool
    branch_ok: bool
    diagnostic_ok: bool
    reasons: tuple[str, ...]

    @property
    def admissible(self) -> bool:
        return not self.reasons


@dataclass(frozen=True, slots=True)
class ExcludedLevelEvidence:
    epsilon: float
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LadderRecoveryResult:
    disposition: RecoveryDisposition
    candidate_windows: tuple[WindowEvidence, ...]
    selected_window: WindowEvidence | None = None
    selected_epsilons: tuple[float, ...] = ()
    excluded_fine_levels: tuple[ExcludedLevelEvidence, ...] = ()
    amplitudes_to_add: tuple[float, ...] = ()
    readouts_to_promote: tuple[tuple[float, str], ...] = ()
    next_precision_tier: PrecisionTier | None = None


def _observed_order(epsilons: Sequence[float], values: Sequence[complex]) -> float | None:
    if len(values) < 3:
        return None
    coarse_difference = abs(values[-3] - values[-2])
    fine_difference = abs(values[-2] - values[-1])
    ratio = epsilons[-2] / epsilons[-1]
    if coarse_difference <= 0.0 or fine_difference <= 0.0 or ratio <= 1.0:
        return None
    return math.log(coarse_difference / fine_difference) / math.log(ratio)


def _assess_window(window: Sequence[LadderLevel], policy: LadderPolicy) -> WindowEvidence:
    level_evidence = tuple(
        WindowLevelEvidence(
            epsilon=level.epsilon,
            real_signal_ratio=level.signal_ratios(policy.signal_factor)[0],
            imaginary_signal_ratio=level.signal_ratios(policy.signal_factor)[1],
            signal_ok=all(value > 1.0 for value in level.signal_ratios(policy.signal_factor)),
        )
        for level in window
    )
    epsilons = tuple(level.epsilon for level in window)
    real_values = tuple(level.real_secant for level in window)
    imaginary_values = tuple(level.imaginary_secant for level in window)
    real_order = _observed_order(epsilons, real_values)
    imaginary_order = _observed_order(epsilons, imaginary_values)
    minimum_order = policy.required_order - policy.order_tolerance
    real_order_ok = real_order is not None and real_order >= minimum_order
    imaginary_order_ok = imaginary_order is not None and imaginary_order >= minimum_order
    root_scale = max(
        sum(readout.root_error for readout in level.readouts) / (2.0 * level.epsilon)
        for level in window
    )
    axis_difference = abs(real_values[-1] - imaginary_values[-1])
    axis_ok = axis_difference <= policy.axis_tolerance_factor * max(root_scale, 1e-15)
    even_remainder_ok = all(
        level.even_remainder
        <= policy.even_remainder_factor * max(level.even_remainder_error, 1e-15)
        for level in window
    )
    branch_ok = all(readout.branch_ok for level in window for readout in level.readouts)
    diagnostic_ok = all(
        readout.diagnostic_ok for level in window for readout in level.readouts
    )
    reasons: list[str] = []
    if not all(item.signal_ok for item in level_evidence):
        reasons.append("SIGNAL_GATE")
    if not real_order_ok or not imaginary_order_ok:
        reasons.append("ORDER_GATE")
    if not axis_ok:
        reasons.append("AXIS_GATE")
    if not even_remainder_ok:
        reasons.append("EVEN_REMAINDER_GATE")
    if not branch_ok:
        reasons.append("BRANCH_GATE")
    if not diagnostic_ok:
        reasons.append("DIAGNOSTIC_GATE")
    return WindowEvidence(
        epsilons,
        level_evidence,
        real_order,
        imaginary_order,
        real_order_ok,
        imaginary_order_ok,
        axis_ok,
        even_remainder_ok,
        branch_ok,
        diagnostic_ok,
        tuple(reasons),
    )


_WindowItem = TypeVar("_WindowItem")


def consecutive_windows(
    levels: Sequence[_WindowItem], minimum_window: int
) -> tuple[tuple[_WindowItem, ...], ...]:
    return tuple(
        tuple(levels[start:stop])
        for length in range(minimum_window, len(levels) + 1)
        for start in range(0, len(levels) - length + 1)
        for stop in (start + length,)
    )


def _amplitudes_to_add(
    ordered: Sequence[LadderLevel], policy: LadderPolicy
) -> tuple[float, ...]:
    resolved_prefix = 0
    for level in ordered:
        if not all(value > 1.0 for value in level.signal_ratios(policy.signal_factor)):
            break
        resolved_prefix += 1
    required = max(0, policy.minimum_window - resolved_prefix)
    candidate = ordered[0].epsilon * 2.0
    additions: list[float] = []
    while len(additions) < required and candidate <= policy.maximum_epsilon * (1.0 + 1e-12):
        additions.append(candidate)
        candidate *= 2.0
    return tuple(additions) if len(additions) == required else ()


def _promotion_requests(
    ordered: Sequence[LadderLevel], policy: LadderPolicy
) -> tuple[tuple[float, str], ...]:
    requests: list[tuple[float, str]] = []
    for level in ordered:
        real_ratio, imaginary_ratio = level.signal_ratios(policy.signal_factor)
        if real_ratio <= 1.0:
            requests.extend(((level.epsilon, "real_plus"), (level.epsilon, "real_minus")))
        if imaginary_ratio <= 1.0:
            requests.extend(
                (
                    (level.epsilon, "imaginary_plus"),
                    (level.epsilon, "imaginary_minus"),
                )
            )
    return tuple(requests)


def recover_response_ladder(
    levels: Sequence[LadderLevel], *, policy: LadderPolicy
) -> LadderRecoveryResult:
    ordered = tuple(sorted(levels, key=lambda level: level.epsilon, reverse=True))
    if not ordered:
        raise ValueError("response ladder recovery requires at least one level")
    if len({level.epsilon for level in ordered}) != len(ordered):
        raise ValueError("response ladder epsilon values must be unique")

    windows = consecutive_windows(ordered, policy.minimum_window)
    evidence = tuple(_assess_window(window, policy) for window in windows)
    admissible = tuple(item for item in evidence if item.admissible)
    if admissible:
        # Finest means the admissible window with the smallest fine endpoint;
        # ties prefer the shortest window and then the coarsest start.
        selected = min(
            admissible,
            key=lambda item: (item.epsilons[-1], len(item.epsilons), -item.epsilons[0]),
        )
        excluded = tuple(
            ExcludedLevelEvidence(
                level.epsilon,
                next(
                    (
                        item.reasons
                        for item in evidence
                        if item.epsilons == (level.epsilon,)
                    ),
                    ("SIGNAL_GATE",)
                    if not all(
                        value > 1.0
                        for value in level.signal_ratios(policy.signal_factor)
                    )
                    else ("EXCLUDED_BY_FINEST_WINDOW",),
                ),
            )
            for level in ordered
            if level.epsilon < selected.epsilons[-1]
        )
        return LadderRecoveryResult(
            disposition=RecoveryDisposition.RECOVERED,
            candidate_windows=evidence,
            selected_window=selected,
            selected_epsilons=selected.epsilons,
            excluded_fine_levels=excluded,
        )

    additions = _amplitudes_to_add(ordered, policy)
    if additions:
        return LadderRecoveryResult(
            disposition=RecoveryDisposition.EXPAND_AMPLITUDE,
            candidate_windows=evidence,
            amplitudes_to_add=additions,
        )

    current_tier = min(
        (readout.precision_tier for level in ordered for readout in level.readouts),
        key=lambda tier: (
            PrecisionTier.BINARY64,
            PrecisionTier.BIGFLOAT_40,
            PrecisionTier.BIGFLOAT_80,
            PrecisionTier.BIGFLOAT_120,
        ).index(tier),
    )
    return LadderRecoveryResult(
        disposition=RecoveryDisposition.PROMOTE_READOUTS,
        candidate_windows=evidence,
        readouts_to_promote=_promotion_requests(ordered, policy),
        next_precision_tier=next_precision_tier(current_tier),
    )
