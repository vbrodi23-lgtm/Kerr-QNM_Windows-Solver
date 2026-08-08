"""Deterministic signed-error geometry and projective response reduction.

The objects in this module describe numerical-error geometry.  They are not
statistical covariance, posterior, confidence, or probability objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import hashlib
import math
from types import MappingProxyType
from typing import Mapping, Sequence

from .contracts import canonical_json_bytes
from .linear_response import B_PRIME_RELEASE_DOMAIN


SIGNED_ERROR_FAMILIES = frozenset({
    "signed-root",
    "centred-step-amplitude",
    "refinement-holdout",
    "truncation",
    "resolution-angular-refinement",
    "continuation-seed-path",
    "repeat-polish",
    "precision-ladder-discrepancy",
})
EMPIRICAL_GRAM_KIND = "empirical-error-gram/deterministic-not-statistical"
PREDECLARED_REDUCTION_SMOKE_CASES = (
    ("primary-head-shared-continuation", "primary-K0-19-20-exterior-fixed-r3"),
    ("primary-middle-correlated-refinement", "primary-K1-1999-2000-exterior-alpha-half"),
    ("deep-tail-missing-promoted-precision", "deep-K22-1-1000-exterior-throat-kappa"),
    ("zero-containing-calibration-disk", "primary-K0-19-20-exterior-fixed-r3"),
    ("computed-unresolved-component", "primary-K0-19-20-exterior-fixed-r3"),
    ("resealed-empirical-gram-tamper", "empirical-error-gram-validation"),
)


def _require_text(value: str, field: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")


def _require_finite_complex(value: complex, field: str) -> None:
    if not isinstance(value, (int, float, complex)):
        raise ValueError(f"{field} must be a signed complex value")
    if not math.isfinite(complex(value).real) or not math.isfinite(complex(value).imag):
        raise ValueError(f"{field} must be finite")


@dataclass(frozen=True, slots=True)
class SignedErrorContribution:
    """One authenticated signed numerical disturbance for one component."""

    channel_id: str
    family: str
    shared_group: str
    delta: complex
    units: str
    source_receipt: str
    scope: str

    def __post_init__(self) -> None:
        for field in ("channel_id", "shared_group", "units", "source_receipt"):
            _require_text(getattr(self, field), field)
        if self.family not in SIGNED_ERROR_FAMILIES:
            raise ValueError(f"unknown signed error family: {self.family!r}")
        if self.scope not in {"local", "shared"}:
            raise ValueError("scope must be 'local' or 'shared'")
        if self.scope == "shared" and not self.channel_id.startswith("shared:"):
            raise ValueError("shared channel IDs must start with 'shared:'")
        if self.scope == "local" and not self.channel_id.startswith("local:"):
            raise ValueError("local channel IDs must start with 'local:'")
        _require_finite_complex(self.delta, "delta")

    def to_mapping(self) -> dict[str, object]:
        value = complex(self.delta)
        return {
            "channel_id": self.channel_id,
            "family": self.family,
            "shared_group": self.shared_group,
            "signed_delta": {"real": value.real, "imaginary": value.imag},
            "units": self.units,
            "source_receipt": self.source_receipt,
            "scope": self.scope,
        }


@dataclass(frozen=True, slots=True)
class ResolvedComponentEvidence:
    """A resolved complex centre with its ordered signed-error ledger."""

    component_id: str
    centre: complex
    units: str
    contributions: tuple[SignedErrorContribution, ...]
    recorded_discrepancies: tuple[float, ...] = ()
    required_families: tuple[str, ...] = ()
    evidence_kind: str = "synthetic-contract"

    def __post_init__(self) -> None:
        _require_text(self.component_id, "component_id")
        _require_text(self.units, "units")
        _require_finite_complex(self.centre, "centre")
        if not isinstance(self.contributions, tuple) or not self.contributions:
            raise ValueError("resolved components require an ordered contribution tuple")
        seen: set[str] = set()
        for contribution in self.contributions:
            if not isinstance(contribution, SignedErrorContribution):
                raise ValueError("contributions must be SignedErrorContribution values")
            if contribution.channel_id in seen:
                raise ValueError(f"duplicate channel ID in component: {contribution.channel_id}")
            seen.add(contribution.channel_id)
            if contribution.units != self.units:
                raise ValueError("signed contribution units do not match component units")
            if contribution.scope == "local" and not contribution.channel_id.startswith(
                f"local:{self.component_id}:"
            ):
                raise ValueError("local channel IDs must be component-qualified")
        for discrepancy in self.recorded_discrepancies:
            if (
                isinstance(discrepancy, bool)
                or not isinstance(discrepancy, (int, float))
                or not math.isfinite(float(discrepancy))
                or discrepancy < 0.0
            ):
                raise ValueError("recorded discrepancies must be finite magnitudes")
        if self.evidence_kind not in {"synthetic-contract", "authenticated-campaign"}:
            raise ValueError("component evidence kind is invalid")
        if (
            len(self.required_families) != len(set(self.required_families))
            or any(family not in SIGNED_ERROR_FAMILIES for family in self.required_families)
        ):
            raise ValueError("required signed-error families are invalid")
        present_families = {item.family for item in self.contributions}
        if set(self.required_families) - present_families:
            raise ValueError("a required applicable signed-error family is missing")

    def to_mapping(self) -> dict[str, object]:
        centre = complex(self.centre)
        return {
            "evidence_state": "RESOLVED",
            "evidence_kind": self.evidence_kind,
            "component_id": self.component_id,
            "centre": {"real": centre.real, "imaginary": centre.imag},
            "units": self.units,
            "contributions": [item.to_mapping() for item in self.contributions],
            "required_families": list(self.required_families),
            "recorded_discrepancies": list(self.recorded_discrepancies),
        }


@dataclass(frozen=True, slots=True)
class ComputedUnresolvedComponentEvidence:
    """A produced component retaining diagnostics but no centre, Gram, or disk."""

    component_id: str
    units: str
    contributions: tuple[SignedErrorContribution, ...]
    reason: str
    source_receipt: str
    evidence_kind: str = "synthetic-contract"

    def __post_init__(self) -> None:
        for field in ("component_id", "units", "reason", "source_receipt"):
            _require_text(getattr(self, field), field)
        if not isinstance(self.contributions, tuple) or not self.contributions:
            raise ValueError("computed unresolved components require a raw channel ledger")
        seen: set[str] = set()
        for contribution in self.contributions:
            if not isinstance(contribution, SignedErrorContribution):
                raise ValueError("unresolved channel ledger contains an invalid entry")
            if contribution.channel_id in seen:
                raise ValueError("unresolved channel ledger contains duplicate IDs")
            seen.add(contribution.channel_id)
            if contribution.units != self.units:
                raise ValueError("unresolved channel ledger units do not match")
        if self.evidence_kind not in {"synthetic-contract", "authenticated-campaign"}:
            raise ValueError("component evidence kind is invalid")

    def to_mapping(self) -> dict[str, object]:
        return {
            "evidence_state": "COMPUTED_UNRESOLVED",
            "evidence_kind": self.evidence_kind,
            "component_id": self.component_id,
            "units": self.units,
            "contributions": [item.to_mapping() for item in self.contributions],
            "reason": self.reason,
            "source_receipt": self.source_receipt,
        }


@dataclass(frozen=True, slots=True)
class EmpiricalErrorGram:
    """Exact outer-product geometry of globally aligned signed channels."""

    basis: tuple[str, ...]
    channel_ids: tuple[str, ...]
    channel_families: tuple[str, ...]
    columns: tuple[tuple[float, ...], ...]
    matrix: tuple[tuple[float, ...], ...]
    units: str
    local_disks: Mapping[str, float]
    construction_id: str
    source_hashes: tuple[str, ...]
    kind: str = EMPIRICAL_GRAM_KIND

    def __post_init__(self) -> None:
        object.__setattr__(self, "local_disks", MappingProxyType(dict(self.local_disks)))

    def to_mapping(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "basis": list(self.basis),
            "channel_ids": list(self.channel_ids),
            "channel_families": list(self.channel_families),
            "columns": [list(column) for column in self.columns],
            "matrix": [list(row) for row in self.matrix],
            "units": self.units,
            "local_disks": dict(self.local_disks),
            "construction_id": self.construction_id,
            "source_hashes": list(self.source_hashes),
        }


def _outer_product_sum(
    columns: Sequence[Sequence[float]], dimension: int
) -> tuple[tuple[float, ...], ...]:
    matrix = [[0.0 for _ in range(dimension)] for _ in range(dimension)]
    for column in columns:
        for row_index, left in enumerate(column):
            for column_index, right in enumerate(column):
                matrix[row_index][column_index] += left * right
    return tuple(tuple(row) for row in matrix)


def _is_positive_semidefinite(matrix: Sequence[Sequence[float]]) -> bool:
    """Return whether a finite symmetric matrix has a semidefinite LDL factor."""

    size = len(matrix)
    scale = max((abs(value) for row in matrix for value in row), default=1.0)
    tolerance = max(1.0, scale, float(size)) * 1.0e-12
    lower = [[0.0 for _ in range(size)] for _ in range(size)]
    for row in range(size):
        for column in range(row + 1):
            residual = matrix[row][column] - sum(
                lower[row][index] * lower[column][index]
                for index in range(column)
            )
            if row == column:
                if residual < -tolerance:
                    return False
                lower[row][column] = math.sqrt(max(0.0, residual))
            elif lower[column][column] > tolerance:
                lower[row][column] = residual / lower[column][column]
            elif abs(residual) > tolerance:
                return False
    return True


def build_empirical_error_gram(
    components: Sequence[ResolvedComponentEvidence],
    *,
    source_hashes: Sequence[str],
) -> EmpiricalErrorGram:
    """Align signed channels and form their exact empirical error Gram."""

    ordered_components = tuple(components)
    if not ordered_components:
        raise ValueError("at least one resolved component is required")
    if len({item.component_id for item in ordered_components}) != len(ordered_components):
        raise ValueError("duplicate component ID")
    units = ordered_components[0].units
    if any(item.units != units for item in ordered_components):
        raise ValueError("all Gram components must use the same units")
    hashes = tuple(source_hashes)
    if not hashes or any(not isinstance(item, str) or not item for item in hashes):
        raise ValueError("authenticated source hashes are required")

    channel_order: list[str] = []
    metadata: dict[str, tuple[str, str, str, str]] = {}
    component_deltas: list[dict[str, complex]] = []
    local_disks: dict[str, float] = {}
    for component in ordered_components:
        deltas: dict[str, complex] = {}
        local_disks[component.component_id] = 0.0
        for contribution in component.contributions:
            channel_id = contribution.channel_id
            candidate = (
                contribution.family,
                contribution.shared_group,
                contribution.units,
                contribution.source_receipt,
            )
            if channel_id in metadata and metadata[channel_id] != candidate:
                raise ValueError(f"shared channel metadata mismatch: {channel_id}")
            if contribution.scope == "local" and channel_id in metadata:
                raise ValueError(f"local channel reused across components: {channel_id}")
            if channel_id not in metadata:
                metadata[channel_id] = candidate
                channel_order.append(channel_id)
            deltas[channel_id] = complex(contribution.delta)
            local_disks[component.component_id] += abs(complex(contribution.delta))
        component_deltas.append(deltas)

    columns: list[tuple[float, ...]] = []
    for channel_id in channel_order:
        column: list[float] = []
        for deltas in component_deltas:
            delta = deltas.get(channel_id, 0.0j)
            column.extend((delta.real, delta.imag))
        columns.append(tuple(column))
    basis = tuple(
        coordinate
        for component in ordered_components
        for coordinate in (f"Re {component.component_id}", f"Im {component.component_id}")
    )
    matrix = _outer_product_sum(columns, len(basis))
    material = {
        "kind": EMPIRICAL_GRAM_KIND,
        "basis": basis,
        "channel_ids": channel_order,
        "channel_families": [metadata[item][0] for item in channel_order],
        "columns": columns,
        "matrix": matrix,
        "units": units,
        "local_disks": local_disks,
        "source_hashes": hashes,
    }
    construction_id = "empirical-error-gram-" + hashlib.sha256(
        canonical_json_bytes(material)
    ).hexdigest()
    return EmpiricalErrorGram(
        basis=basis,
        channel_ids=tuple(channel_order),
        channel_families=tuple(metadata[item][0] for item in channel_order),
        columns=tuple(columns),
        matrix=matrix,
        units=units,
        local_disks=local_disks,
        construction_id=construction_id,
        source_hashes=hashes,
    )


def validate_empirical_error_gram(
    gram: EmpiricalErrorGram,
    components: Sequence[ResolvedComponentEvidence],
) -> None:
    """Recompute every deterministic field, including 2x2 marginals and disks."""

    if not isinstance(gram, EmpiricalErrorGram):
        raise ValueError("empirical error Gram has the wrong type")
    dimension = len(gram.basis)
    if dimension == 0 or len(gram.matrix) != dimension:
        raise ValueError("empirical error Gram has the wrong dimension")
    if any(len(row) != dimension for row in gram.matrix):
        raise ValueError("empirical error Gram must be square")
    if any(not math.isfinite(value) for row in gram.matrix for value in row):
        raise ValueError("empirical error Gram entries must be finite")
    if any(
        gram.matrix[row][column] != gram.matrix[column][row]
        for row in range(dimension)
        for column in range(dimension)
    ):
        raise ValueError("empirical error Gram must be symmetric")
    if not _is_positive_semidefinite(gram.matrix):
        raise ValueError("empirical error Gram must be positive semidefinite")

    ordered_components = tuple(components)
    expected = build_empirical_error_gram(
        ordered_components, source_hashes=gram.source_hashes
    )
    for component in ordered_components:
        radius = gram.local_disks.get(component.component_id)
        if radius is None or not math.isfinite(radius) or radius < 0.0:
            raise ValueError("component local disk is absent or invalid")
        if any(discrepancy > radius for discrepancy in component.recorded_discrepancies):
            raise ValueError("component local disk does not cover a recorded discrepancy")
    for component_index, component in enumerate(ordered_components):
        start = 2 * component_index
        marginal = tuple(
            tuple(gram.matrix[row][column] for column in range(start, start + 2))
            for row in range(start, start + 2)
        )
        expected_marginal = tuple(
            tuple(expected.matrix[row][column] for column in range(start, start + 2))
            for row in range(start, start + 2)
        )
        if marginal != expected_marginal:
            raise ValueError(
                f"empirical error Gram 2x2 marginal mismatch: {component.component_id}"
            )
    comparable_fields = (
        "kind", "basis", "channel_ids", "channel_families", "columns",
        "matrix", "units", "local_disks", "construction_id", "source_hashes",
    )
    if any(getattr(gram, field) != getattr(expected, field) for field in comparable_fields):
        raise ValueError("empirical error Gram failed exact recomputation")


@dataclass(frozen=True, slots=True)
class ProjectiveRowPlan:
    """One outcome-neutral projective comparison declared by the release domain."""

    row_id: str
    role: str
    support_id: str
    mode_labels: tuple[str, ...]
    coordinate_role: str
    coordinate: Fraction
    spin_binary64_hex: str
    left_mechanism_id: str
    right_mechanism_id: str
    left_component_ids: tuple[str, ...]
    right_component_ids: tuple[str, ...]
    calibration_mode_label: str
    calibration_component_ids: tuple[str, str]
    empirical_gram_kind: str
    units: str
    separation_lower_radians: float
    equivalence_upper_radians: float
    evidence_ceiling: str

    def to_mapping(self) -> dict[str, object]:
        return {
            "row_id": self.row_id,
            "role": self.role,
            "support_id": self.support_id,
            "mode_labels": list(self.mode_labels),
            "coordinate_role": self.coordinate_role,
            "coordinate_exact": [self.coordinate.numerator, self.coordinate.denominator],
            "spin_binary64_hex": self.spin_binary64_hex,
            "left_mechanism_id": self.left_mechanism_id,
            "right_mechanism_id": self.right_mechanism_id,
            "left_component_ids": list(self.left_component_ids),
            "right_component_ids": list(self.right_component_ids),
            "calibration_mode_label": self.calibration_mode_label,
            "calibration_component_ids": list(self.calibration_component_ids),
            "empirical_gram_kind": self.empirical_gram_kind,
            "units": self.units,
            "thresholds_radians": {
                "separation_lower": self.separation_lower_radians,
                "equivalence_upper": self.equivalence_upper_radians,
            },
            "evidence_ceiling": self.evidence_ceiling,
        }


def build_projective_row_plans() -> tuple[ProjectiveRowPlan, ...]:
    """Enumerate the frozen 174 plans without computing any response result."""

    domain = B_PRIME_RELEASE_DOMAIN
    leaves = {
        (leaf.role, leaf.mode_label, leaf.coordinate, leaf.mechanism_id): leaf
        for leaf in domain.production_leaves
    }
    plans: list[ProjectiveRowPlan] = []

    def append_plan(
        *,
        row_id: str,
        role: str,
        support_id: str,
        mode_labels: tuple[str, ...],
        coordinate_role: str,
        coordinate: Fraction,
        exterior: str,
    ) -> None:
        left = tuple(
            leaves[(role, label, coordinate, "horizon-admittance")]
            for label in mode_labels
        )
        right = tuple(
            leaves[(role, label, coordinate, exterior)] for label in mode_labels
        )
        plans.append(ProjectiveRowPlan(
            row_id=row_id,
            role=role,
            support_id=support_id,
            mode_labels=mode_labels,
            coordinate_role=coordinate_role,
            coordinate=coordinate,
            spin_binary64_hex=left[0].spin.hex(),
            left_mechanism_id="horizon-admittance",
            right_mechanism_id=exterior,
            left_component_ids=tuple(item.leaf_id for item in left),
            right_component_ids=tuple(item.leaf_id for item in right),
            calibration_mode_label=mode_labels[0],
            calibration_component_ids=(left[0].leaf_id, right[0].leaf_id),
            empirical_gram_kind=EMPIRICAL_GRAM_KIND,
            units="radians",
            separation_lower_radians=1.0e-2,
            equivalence_upper_radians=1.0e-3,
            evidence_ceiling=(
                "primary-release-domain" if role == "primary"
                else "exploratory-near-extremal"
            ),
        ))

    primary_coordinates = tuple(sorted({
        leaf.coordinate for leaf in domain.production_leaves if leaf.role == "primary"
    }))
    for support_id, mode_labels in domain.primary_supports.items():
        for coordinate in primary_coordinates:
            for exterior in domain.exterior_mechanism_ids:
                append_plan(
                    row_id=(
                        f"primary-{support_id}-{coordinate.numerator}-"
                        f"{coordinate.denominator}-{exterior}"
                    ),
                    role="primary",
                    support_id=support_id,
                    mode_labels=mode_labels,
                    coordinate_role="direct",
                    coordinate=coordinate,
                    exterior=exterior,
                )
    deep_coordinates = tuple(sorted({
        leaf.coordinate for leaf in domain.production_leaves if leaf.role == "deep"
    }))
    deep_exteriors = (
        "exterior-alpha-one", "exterior-light-ring", "exterior-throat-kappa"
    )
    for coordinate in deep_coordinates:
        for exterior in deep_exteriors:
            append_plan(
                row_id=(
                    f"deep-K22-{coordinate.numerator}-{coordinate.denominator}-{exterior}"
                ),
                role="deep",
                support_id="K22",
                mode_labels=domain.deep_support,
                coordinate_role="M-kappa",
                coordinate=coordinate,
                exterior=exterior,
            )
    if tuple(plan.row_id for plan in plans) != domain.projective_row_ids:
        raise RuntimeError("projective row planner drifted from the frozen release domain")
    return tuple(plans)


@dataclass(frozen=True, slots=True)
class ProjectiveRowResult:
    """One complete, unresolved, or explicitly incomplete row reduction."""

    row_id: str
    reducer_state: str
    present_component_ids: tuple[str, ...]
    missing_component_ids: tuple[str, ...]
    produced_unresolved_component_ids: tuple[str, ...]
    projective_outcome: str | None
    scientific_state: str | None
    nominal_angle_radians: float | None
    bounded_angle_interval_radians: tuple[float, float] | None
    calibration_disk_contains_zero: bool | None
    empirical_gram_id: str | None
    linearized_angle_gram: float | None
    linearized_angle_columns: tuple[tuple[str, float], ...]
    reason: str

    def to_mapping(self) -> dict[str, object]:
        return {
            "row_id": self.row_id,
            "reducer_state": self.reducer_state,
            "present_component_ids": list(self.present_component_ids),
            "missing_component_ids": list(self.missing_component_ids),
            "produced_unresolved_component_ids": list(
                self.produced_unresolved_component_ids
            ),
            "projective_outcome": self.projective_outcome,
            "scientific_state": self.scientific_state,
            "nominal_angle_radians": self.nominal_angle_radians,
            "bounded_angle_interval_radians": (
                None if self.bounded_angle_interval_radians is None
                else list(self.bounded_angle_interval_radians)
            ),
            "calibration_disk_contains_zero": self.calibration_disk_contains_zero,
            "empirical_gram_id": self.empirical_gram_id,
            "linearized_angle_gram": self.linearized_angle_gram,
            "linearized_angle_columns": [
                {"channel_id": channel_id, "signed_angle_delta": value}
                for channel_id, value in self.linearized_angle_columns
            ],
            "reason": self.reason,
        }


def _fubini_study_angle(
    left: Sequence[complex], right: Sequence[complex]
) -> float:
    left_norm = math.sqrt(sum(abs(value) ** 2 for value in left))
    right_norm = math.sqrt(sum(abs(value) ** 2 for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        raise ValueError("projective vector has zero norm")
    inner = sum(complex(left_value).conjugate() * right_value for left_value, right_value in zip(left, right))
    cosine = min(1.0, max(0.0, abs(inner) / (left_norm * right_norm)))
    return math.acos(cosine)


def _vector_projective_radius(norm: float, disk_norm: float) -> float | None:
    if disk_norm >= norm:
        return None
    ratio = disk_norm / (norm - disk_norm)
    if ratio >= 1.0:
        return None
    return math.asin(ratio)


def reduce_projective_row(
    plan: ProjectiveRowPlan,
    components: Mapping[
        str, ResolvedComponentEvidence | ComputedUnresolvedComponentEvidence
    ],
    *,
    source_hashes: Sequence[str],
) -> ProjectiveRowResult:
    """Reduce one exact plan, returning no classification when inputs are absent."""

    frozen = {item.row_id: item for item in build_projective_row_plans()}
    if frozen.get(plan.row_id) != plan:
        raise ValueError("projective row is not an exact frozen plan")
    required = (*plan.left_component_ids, *plan.right_component_ids)
    if set(components) - set(required):
        raise ValueError("projective evidence contains an ambient component")
    present = tuple(component_id for component_id in required if component_id in components)
    missing = tuple(component_id for component_id in required if component_id not in components)
    hashes = tuple(source_hashes)
    if not hashes or any(not isinstance(item, str) or not item for item in hashes):
        raise ValueError("authenticated source hashes are required")
    if missing:
        return ProjectiveRowResult(
            row_id=plan.row_id,
            reducer_state="INCOMPLETE",
            present_component_ids=present,
            missing_component_ids=missing,
            produced_unresolved_component_ids=(),
            projective_outcome=None,
            scientific_state=None,
            nominal_angle_radians=None,
            bounded_angle_interval_radians=None,
            calibration_disk_contains_zero=None,
            empirical_gram_id=None,
            linearized_angle_gram=None,
            linearized_angle_columns=(),
            reason="required aligned component evidence is absent",
        )
    ordered_evidence = tuple(components[component_id] for component_id in required)
    if any(
        not isinstance(
            component,
            (ResolvedComponentEvidence, ComputedUnresolvedComponentEvidence),
        )
        or component.component_id != component_id
        for component_id, component in zip(required, ordered_evidence)
    ):
        raise ValueError("projective evidence is not bound to its component ID")
    unresolved_ids = tuple(
        component.component_id
        for component in ordered_evidence
        if isinstance(component, ComputedUnresolvedComponentEvidence)
    )
    if unresolved_ids:
        return ProjectiveRowResult(
            row_id=plan.row_id,
            reducer_state="COMPLETE",
            present_component_ids=required,
            missing_component_ids=(),
            produced_unresolved_component_ids=unresolved_ids,
            projective_outcome="UNRESOLVED",
            scientific_state="UNRESOLVED",
            nominal_angle_radians=None,
            bounded_angle_interval_radians=None,
            calibration_disk_contains_zero=None,
            empirical_gram_id=None,
            linearized_angle_gram=None,
            linearized_angle_columns=(),
            reason="one or more produced components are numerically unresolved",
        )
    ordered_components: tuple[ResolvedComponentEvidence, ...] = tuple(
        component for component in ordered_evidence
        if isinstance(component, ResolvedComponentEvidence)
    )
    gram = build_empirical_error_gram(
        ordered_components, source_hashes=hashes
    )
    validate_empirical_error_gram(gram, ordered_components)
    split = len(plan.left_component_ids)
    left = tuple(component.centre for component in ordered_components[:split])
    right = tuple(component.centre for component in ordered_components[split:])
    denominator = ordered_components[split]
    denominator_disk = gram.local_disks[denominator.component_id]
    calibration_zero = abs(denominator.centre) <= denominator_disk
    left_disk_norm = math.sqrt(sum(
        gram.local_disks[component.component_id] ** 2
        for component in ordered_components[:split]
    ))
    right_disk_norm = math.sqrt(sum(
        gram.local_disks[component.component_id] ** 2
        for component in ordered_components[split:]
    ))
    left_norm = math.sqrt(sum(abs(value) ** 2 for value in left))
    right_norm = math.sqrt(sum(abs(value) ** 2 for value in right))
    left_radius = _vector_projective_radius(left_norm, left_disk_norm)
    right_radius = _vector_projective_radius(right_norm, right_disk_norm)
    if calibration_zero or left_radius is None or right_radius is None:
        return ProjectiveRowResult(
            row_id=plan.row_id,
            reducer_state="COMPLETE",
            present_component_ids=required,
            missing_component_ids=(),
            produced_unresolved_component_ids=(),
            projective_outcome="UNRESOLVED",
            scientific_state="UNRESOLVED",
            nominal_angle_radians=None,
            bounded_angle_interval_radians=None,
            calibration_disk_contains_zero=calibration_zero,
            empirical_gram_id=gram.construction_id,
            linearized_angle_gram=None,
            linearized_angle_columns=(),
            reason=(
                "calibration disk contains zero" if calibration_zero
                else "component disks do not prove a bounded projective interval"
            ),
        )

    nominal = _fubini_study_angle(left, right)
    width = left_radius + right_radius
    interval = (max(0.0, nominal - width), min(math.pi / 2.0, nominal + width))
    angle_columns: list[tuple[str, float]] = []
    all_centres = (*left, *right)
    for channel_id, column in zip(gram.channel_ids, gram.columns):
        disturbance = tuple(
            complex(column[index], column[index + 1])
            for index in range(0, len(column), 2)
        )
        plus = tuple(value + delta for value, delta in zip(all_centres, disturbance))
        minus = tuple(value - delta for value, delta in zip(all_centres, disturbance))
        signed_delta = 0.5 * (
            _fubini_study_angle(plus[:split], plus[split:])
            - _fubini_study_angle(minus[:split], minus[split:])
        )
        angle_columns.append((channel_id, signed_delta))
    linearized_gram = sum(value * value for _, value in angle_columns)
    if interval[0] > plan.separation_lower_radians:
        outcome, scientific_state = "SEPARATED", "CONTRADICTED"
        reason = "conservative angle lower bound exceeds the frozen separation threshold"
    elif interval[1] < plan.equivalence_upper_radians:
        outcome, scientific_state = "EQUIVALENT_WITHIN_TOLERANCE", "SUPPORTED"
        reason = "conservative angle upper bound is below the frozen equivalence threshold"
    else:
        outcome = scientific_state = "UNRESOLVED"
        reason = "bounded angle interval crosses the frozen outcome thresholds"
    return ProjectiveRowResult(
        row_id=plan.row_id,
        reducer_state="COMPLETE",
        present_component_ids=required,
        missing_component_ids=(),
        produced_unresolved_component_ids=(),
        projective_outcome=outcome,
        scientific_state=scientific_state,
        nominal_angle_radians=nominal,
        bounded_angle_interval_radians=interval,
        calibration_disk_contains_zero=False,
        empirical_gram_id=gram.construction_id,
        linearized_angle_gram=linearized_gram,
        linearized_angle_columns=tuple(angle_columns),
        reason=reason,
    )


def _exact_mapping_fields(
    value: object, expected: frozenset[str], subject: str
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ValueError(f"{subject} fields are invalid")
    return value


def _finite_number(value: object, subject: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise ValueError(f"{subject} must be a finite number")
    return float(value)


def _complex_from_mapping(value: object, subject: str) -> complex:
    mapping = _exact_mapping_fields(
        value, frozenset({"real", "imaginary"}), subject
    )
    return complex(
        _finite_number(mapping["real"], f"{subject} real part"),
        _finite_number(mapping["imaginary"], f"{subject} imaginary part"),
    )


def signed_error_contribution_from_mapping(
    value: object,
) -> SignedErrorContribution:
    mapping = _exact_mapping_fields(
        value,
        frozenset({
            "channel_id", "family", "shared_group", "signed_delta", "units",
            "source_receipt", "scope",
        }),
        "signed error contribution",
    )
    return SignedErrorContribution(
        channel_id=mapping["channel_id"],
        family=mapping["family"],
        shared_group=mapping["shared_group"],
        delta=_complex_from_mapping(mapping["signed_delta"], "signed delta"),
        units=mapping["units"],
        source_receipt=mapping["source_receipt"],
        scope=mapping["scope"],
    )


def component_evidence_from_mapping(
    value: object,
) -> ResolvedComponentEvidence | ComputedUnresolvedComponentEvidence:
    if not isinstance(value, Mapping):
        raise ValueError("component evidence must be an object")
    state = value.get("evidence_state")
    if state == "RESOLVED":
        mapping = _exact_mapping_fields(
            value,
            frozenset({
                "evidence_state", "evidence_kind", "component_id", "centre",
                "units", "contributions", "required_families",
                "recorded_discrepancies",
            }),
            "resolved component evidence",
        )
        contributions = mapping["contributions"]
        families = mapping["required_families"]
        discrepancies = mapping["recorded_discrepancies"]
        if (
            not isinstance(contributions, list)
            or not isinstance(families, list)
            or any(not isinstance(item, str) for item in families)
            or not isinstance(discrepancies, list)
        ):
            raise ValueError("resolved component evidence arrays are invalid")
        return ResolvedComponentEvidence(
            component_id=mapping["component_id"],
            centre=_complex_from_mapping(mapping["centre"], "component centre"),
            units=mapping["units"],
            contributions=tuple(
                signed_error_contribution_from_mapping(item) for item in contributions
            ),
            recorded_discrepancies=tuple(
                _finite_number(item, "recorded discrepancy") for item in discrepancies
            ),
            required_families=tuple(families),
            evidence_kind=mapping["evidence_kind"],
        )
    if state == "COMPUTED_UNRESOLVED":
        mapping = _exact_mapping_fields(
            value,
            frozenset({
                "evidence_state", "evidence_kind", "component_id", "units",
                "contributions", "reason", "source_receipt",
            }),
            "computed unresolved component evidence",
        )
        contributions = mapping["contributions"]
        if not isinstance(contributions, list):
            raise ValueError("computed unresolved channel ledger is invalid")
        return ComputedUnresolvedComponentEvidence(
            component_id=mapping["component_id"],
            units=mapping["units"],
            contributions=tuple(
                signed_error_contribution_from_mapping(item) for item in contributions
            ),
            reason=mapping["reason"],
            source_receipt=mapping["source_receipt"],
            evidence_kind=mapping["evidence_kind"],
        )
    raise ValueError("component evidence state is invalid")


@dataclass(frozen=True, slots=True)
class CampaignReductionSummary:
    campaign_id: str
    reducer_state: str
    selected_row_ids: tuple[str, ...]
    present_component_ids: tuple[str, ...]
    missing_component_ids: tuple[str, ...]
    row_plan_sha256: str
    source_hashes: tuple[str, ...]
    plans: tuple[ProjectiveRowPlan, ...]
    results: tuple[ProjectiveRowResult, ...]
    reduction_id: str

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": "b-prime-projective-reduction",
            "campaign_id": self.campaign_id,
            "reducer_state": self.reducer_state,
            "selected_row_ids": list(self.selected_row_ids),
            "present_component_ids": list(self.present_component_ids),
            "missing_component_ids": list(self.missing_component_ids),
            "row_plan_sha256": self.row_plan_sha256,
            "source_hashes": list(self.source_hashes),
            "plans": [plan.to_mapping() for plan in self.plans],
            "results": [result.to_mapping() for result in self.results],
            "reduction_id": self.reduction_id,
            "release_admissible": False,
        }


def reduce_projective_rows(
    campaign_id: str,
    selected_row_ids: Sequence[str],
    components: Mapping[
        str, ResolvedComponentEvidence | ComputedUnresolvedComponentEvidence
    ],
    *,
    source_hashes: Sequence[str],
) -> CampaignReductionSummary:
    """Reduce only a canonical selected row set; enumeration itself does no work."""

    _require_text(campaign_id, "campaign_id")
    all_plans = build_projective_row_plans()
    requested = tuple(selected_row_ids)
    if not requested or len(requested) != len(set(requested)):
        raise ValueError("projective row selection must be nonempty and unique")
    requested_set = set(requested)
    plans = tuple(plan for plan in all_plans if plan.row_id in requested_set)
    if tuple(plan.row_id for plan in plans) != requested:
        raise ValueError("projective row selection is unknown or reordered")
    required_order = tuple(dict.fromkeys(
        component_id
        for plan in plans
        for component_id in (*plan.left_component_ids, *plan.right_component_ids)
    ))
    if set(components) - set(required_order):
        raise ValueError("reduction bundle contains ambient/control/comparator evidence")
    hashes = tuple(source_hashes)
    if not hashes or len(hashes) != len(set(hashes)):
        raise ValueError("source hashes must be nonempty and unique")
    results = tuple(
        reduce_projective_row(
            plan,
            {
                component_id: components[component_id]
                for component_id in (*plan.left_component_ids, *plan.right_component_ids)
                if component_id in components
            },
            source_hashes=hashes,
        )
        for plan in plans
    )
    present = tuple(item for item in required_order if item in components)
    missing = tuple(item for item in required_order if item not in components)
    reducer_state = "INCOMPLETE" if missing else "COMPLETE"
    row_plan_sha256 = hashlib.sha256(canonical_json_bytes(
        [plan.to_mapping() for plan in plans]
    )).hexdigest()
    material = {
        "campaign_id": campaign_id,
        "reducer_state": reducer_state,
        "selected_row_ids": requested,
        "present_component_ids": present,
        "missing_component_ids": missing,
        "row_plan_sha256": row_plan_sha256,
        "source_hashes": hashes,
        "component_evidence": [components[item].to_mapping() for item in present],
        "results": [result.to_mapping() for result in results],
    }
    reduction_id = "b-prime-reduction-" + hashlib.sha256(
        canonical_json_bytes(material)
    ).hexdigest()
    return CampaignReductionSummary(
        campaign_id=campaign_id,
        reducer_state=reducer_state,
        selected_row_ids=requested,
        present_component_ids=present,
        missing_component_ids=missing,
        row_plan_sha256=row_plan_sha256,
        source_hashes=hashes,
        plans=plans,
        results=results,
        reduction_id=reduction_id,
    )
