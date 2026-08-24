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
class BoundedComponentEvidence:
    """An authenticated response centre with a directly retained disk radius."""

    component_id: str
    centre: complex
    disk_radius: float
    units: str
    source_receipt: str
    evidence_kind: str = "authenticated-campaign"

    def __post_init__(self) -> None:
        for field in ("component_id", "units", "source_receipt"):
            _require_text(getattr(self, field), field)
        _require_finite_complex(self.centre, "centre")
        radius = float(self.disk_radius)
        if not math.isfinite(radius) or radius < 0.0:
            raise ValueError("bounded component disk radius is invalid")
        object.__setattr__(self, "disk_radius", radius)
        if self.evidence_kind != "authenticated-campaign":
            raise ValueError("bounded component evidence kind is invalid")

    def to_mapping(self) -> dict[str, object]:
        centre = complex(self.centre)
        return {
            "evidence_state": "BOUNDED",
            "evidence_kind": self.evidence_kind,
            "component_id": self.component_id,
            "centre": {"real": centre.real, "imaginary": centre.imag},
            "disk_radius": self.disk_radius,
            "units": self.units,
            "source_receipt": self.source_receipt,
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
    local_marginals: Mapping[
        str, tuple[tuple[float, float], tuple[float, float]]
    ]
    local_disks: Mapping[str, float]
    construction_id: str
    source_hashes: tuple[str, ...]
    kind: str = EMPIRICAL_GRAM_KIND

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "local_marginals",
            MappingProxyType({
                key: tuple(tuple(row) for row in marginal)
                for key, marginal in self.local_marginals.items()
            }),
        )
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
            "local_marginals": {
                key: [list(row) for row in marginal]
                for key, marginal in self.local_marginals.items()
            },
            "local_disks": dict(self.local_disks),
            "construction_id": self.construction_id,
            "source_hashes": list(self.source_hashes),
        }

    @classmethod
    def from_mapping(cls, value: object) -> "EmpiricalErrorGram":
        mapping = _exact_mapping_fields(
            value,
            frozenset({
                "kind", "basis", "channel_ids", "channel_families", "columns",
                "matrix", "units", "local_marginals", "local_disks",
                "construction_id", "source_hashes",
            }),
            "empirical error Gram",
        )
        for name in ("basis", "channel_ids", "channel_families", "columns", "matrix", "source_hashes"):
            if not isinstance(mapping[name], list):
                raise ValueError(f"empirical error Gram {name} is invalid")
        if not isinstance(mapping["local_marginals"], Mapping) or not isinstance(
            mapping["local_disks"], Mapping
        ):
            raise ValueError("empirical error Gram local evidence is invalid")
        try:
            gram = cls(
                basis=tuple(mapping["basis"]),
                channel_ids=tuple(mapping["channel_ids"]),
                channel_families=tuple(mapping["channel_families"]),
                columns=tuple(tuple(float(item) for item in column) for column in mapping["columns"]),
                matrix=tuple(tuple(float(item) for item in row) for row in mapping["matrix"]),
                units=mapping["units"],
                local_marginals={
                    key: tuple(tuple(float(item) for item in row) for row in marginal)
                    for key, marginal in mapping["local_marginals"].items()
                },
                local_disks={key: float(item) for key, item in mapping["local_disks"].items()},
                construction_id=mapping["construction_id"],
                source_hashes=tuple(mapping["source_hashes"]),
                kind=mapping["kind"],
            )
        except (TypeError, ValueError) as error:
            raise ValueError("empirical error Gram numeric structure is invalid") from error
        _validate_serialized_empirical_error_gram(gram)
        if gram.to_mapping() != value:
            raise ValueError("empirical error Gram is not canonical")
        return gram


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


def _gram_component_ids(basis: Sequence[str]) -> tuple[str, ...]:
    if not basis or len(basis) % 2:
        raise ValueError("empirical error Gram basis has the wrong dimension")
    component_ids: list[str] = []
    for index in range(0, len(basis), 2):
        real, imaginary = basis[index:index + 2]
        if (
            not isinstance(real, str) or not isinstance(imaginary, str)
            or not real.startswith("Re ") or imaginary != "Im " + real[3:]
            or not real[3:]
        ):
            raise ValueError("empirical error Gram basis is invalid")
        component_ids.append(real[3:])
    if len(component_ids) != len(set(component_ids)):
        raise ValueError("empirical error Gram basis has duplicate components")
    return tuple(component_ids)


def _gram_local_marginals(
    basis: Sequence[str], matrix: Sequence[Sequence[float]]
) -> dict[str, tuple[tuple[float, float], tuple[float, float]]]:
    return {
        component_id: tuple(
            tuple(matrix[row][column] for column in range(start, start + 2))
            for row in range(start, start + 2)
        )
        for start, component_id in zip(
            range(0, len(basis), 2), _gram_component_ids(basis)
        )
    }


def _gram_local_disks_from_columns(
    basis: Sequence[str], columns: Sequence[Sequence[float]]
) -> dict[str, float]:
    return {
        component_id: sum(math.hypot(column[start], column[start + 1]) for column in columns)
        for start, component_id in zip(
            range(0, len(basis), 2), _gram_component_ids(basis)
        )
    }


def _validate_serialized_empirical_error_gram(gram: EmpiricalErrorGram) -> None:
    dimension = len(gram.basis)
    component_ids = _gram_component_ids(gram.basis)
    if gram.kind != EMPIRICAL_GRAM_KIND:
        raise ValueError("empirical error Gram kind is invalid")
    if (
        len(gram.channel_ids) != len(gram.channel_families)
        or len(gram.channel_ids) != len(gram.columns)
        or len(gram.channel_ids) != len(set(gram.channel_ids))
        or any(not isinstance(item, str) or not item for item in gram.channel_ids)
        or any(item not in SIGNED_ERROR_FAMILIES for item in gram.channel_families)
    ):
        raise ValueError("empirical error Gram channel metadata is invalid")
    if any(
        len(column) != dimension or any(not math.isfinite(value) for value in column)
        for column in gram.columns
    ):
        raise ValueError("empirical error Gram signed columns are invalid")
    if (
        len(gram.matrix) != dimension
        or any(len(row) != dimension for row in gram.matrix)
        or any(not math.isfinite(value) for row in gram.matrix for value in row)
    ):
        raise ValueError("empirical error Gram matrix is invalid")
    expected_matrix = _outer_product_sum(gram.columns, dimension)
    if gram.matrix != expected_matrix:
        raise ValueError("empirical error Gram matrix failed exact recomputation")
    expected_marginals = _gram_local_marginals(gram.basis, expected_matrix)
    if dict(gram.local_marginals) != expected_marginals:
        raise ValueError("empirical error Gram local marginal failed exact recomputation")
    expected_disks = _gram_local_disks_from_columns(gram.basis, gram.columns)
    if dict(gram.local_disks) != expected_disks:
        raise ValueError("empirical error Gram local disk failed exact recomputation")
    if set(gram.local_disks) != set(component_ids):
        raise ValueError("empirical error Gram local component set is invalid")
    if (
        not isinstance(gram.units, str) or not gram.units
        or not gram.source_hashes
        or any(not isinstance(item, str) or not item for item in gram.source_hashes)
    ):
        raise ValueError("empirical error Gram provenance is invalid")
    material = gram.to_mapping()
    material.pop("construction_id")
    expected_id = "empirical-error-gram-" + hashlib.sha256(
        canonical_json_bytes(material)
    ).hexdigest()
    if gram.construction_id != expected_id:
        raise ValueError("empirical error Gram construction hash is invalid")


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
    for component in ordered_components:
        deltas: dict[str, complex] = {}
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
    local_marginals = _gram_local_marginals(basis, matrix)
    local_disks = _gram_local_disks_from_columns(basis, columns)
    material = {
        "kind": EMPIRICAL_GRAM_KIND,
        "basis": basis,
        "channel_ids": channel_order,
        "channel_families": [metadata[item][0] for item in channel_order],
        "columns": columns,
        "matrix": matrix,
        "units": units,
        "local_marginals": local_marginals,
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
        local_marginals=local_marginals,
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
    """Enumerate the frozen domain plans without computing any response result."""

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
    linearized_input_basis: tuple[str, ...]
    linearized_step_policy: Mapping[str, object] | None
    linearized_angle_jacobian: tuple[float, ...]
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
            "linearized_input_basis": list(self.linearized_input_basis),
            "linearized_step_policy": (
                None if self.linearized_step_policy is None
                else dict(self.linearized_step_policy)
            ),
            "linearized_angle_jacobian": list(self.linearized_angle_jacobian),
            "linearized_angle_gram": self.linearized_angle_gram,
            "linearized_angle_columns": [
                {"channel_id": channel_id, "signed_angle_delta": value}
                for channel_id, value in self.linearized_angle_columns
            ],
            "reason": self.reason,
        }

    @classmethod
    def from_mapping(cls, value: object) -> "ProjectiveRowResult":
        mapping = _exact_mapping_fields(
            value,
            frozenset({
                "row_id", "reducer_state", "present_component_ids",
                "missing_component_ids", "produced_unresolved_component_ids",
                "projective_outcome", "scientific_state", "nominal_angle_radians",
                "bounded_angle_interval_radians", "calibration_disk_contains_zero",
                "empirical_gram_id", "linearized_input_basis",
                "linearized_step_policy", "linearized_angle_jacobian",
                "linearized_angle_gram",
                "linearized_angle_columns", "reason",
            }),
            "projective row result",
        )
        for name in (
            "present_component_ids", "missing_component_ids",
            "produced_unresolved_component_ids", "linearized_input_basis",
            "linearized_angle_jacobian", "linearized_angle_columns",
        ):
            if not isinstance(mapping[name], list):
                raise ValueError(f"projective row result {name} is invalid")
        interval = mapping["bounded_angle_interval_radians"]
        if interval is not None and (not isinstance(interval, list) or len(interval) != 2):
            raise ValueError("projective row result angle interval is invalid")
        columns = mapping["linearized_angle_columns"]
        if any(
            not isinstance(item, Mapping)
            or set(item) != {"channel_id", "signed_angle_delta"}
            for item in columns
        ):
            raise ValueError("projective row result linearized columns are invalid")
        result = cls(
            row_id=mapping["row_id"],
            reducer_state=mapping["reducer_state"],
            present_component_ids=tuple(mapping["present_component_ids"]),
            missing_component_ids=tuple(mapping["missing_component_ids"]),
            produced_unresolved_component_ids=tuple(mapping["produced_unresolved_component_ids"]),
            projective_outcome=mapping["projective_outcome"],
            scientific_state=mapping["scientific_state"],
            nominal_angle_radians=mapping["nominal_angle_radians"],
            bounded_angle_interval_radians=(None if interval is None else tuple(interval)),
            calibration_disk_contains_zero=mapping["calibration_disk_contains_zero"],
            empirical_gram_id=mapping["empirical_gram_id"],
            linearized_input_basis=tuple(mapping["linearized_input_basis"]),
            linearized_step_policy=mapping["linearized_step_policy"],
            linearized_angle_jacobian=tuple(mapping["linearized_angle_jacobian"]),
            linearized_angle_gram=mapping["linearized_angle_gram"],
            linearized_angle_columns=tuple(
                (item["channel_id"], item["signed_angle_delta"]) for item in columns
            ),
            reason=mapping["reason"],
        )
        if result.to_mapping() != value:
            raise ValueError("projective row result is not canonical")
        return result


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


@dataclass(frozen=True, slots=True)
class CalibratedProjectiveJacobian:
    input_basis: tuple[str, ...]
    step_policy: Mapping[str, object]
    jacobian: tuple[float, ...]
    scalar_gram: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "step_policy", MappingProxyType(dict(self.step_policy)))

    def to_mapping(self) -> dict[str, object]:
        return {
            "input_basis": list(self.input_basis),
            "step_policy": dict(self.step_policy),
            "jacobian": list(self.jacobian),
            "scalar_gram": self.scalar_gram,
        }


def _calibrated_normalized_angle(
    left: Sequence[complex], right: Sequence[complex]
) -> float:
    if not left or len(left) != len(right) or left[0] == 0.0 or right[0] == 0.0:
        raise ValueError("projective calibration denominator is zero")
    calibrated_left = tuple(value / left[0] for value in left)
    calibrated_right = tuple(value / right[0] for value in right)
    left_norm = math.sqrt(sum(abs(value) ** 2 for value in calibrated_left))
    right_norm = math.sqrt(sum(abs(value) ** 2 for value in calibrated_right))
    if (
        not math.isfinite(left_norm) or not math.isfinite(right_norm)
        or left_norm == 0.0 or right_norm == 0.0
    ):
        raise ValueError("projective calibrated vector cannot be normalized")
    normalized_left = tuple(value / left_norm for value in calibrated_left)
    normalized_right = tuple(value / right_norm for value in calibrated_right)
    inner = sum(
        left_value.conjugate() * right_value
        for left_value, right_value in zip(normalized_left, normalized_right)
    )
    return math.acos(min(1.0, max(0.0, abs(inner))))


def build_calibrated_projective_jacobian(
    left: Sequence[complex],
    right: Sequence[complex],
    input_basis: Sequence[str],
    empirical_gram: Sequence[Sequence[float]],
) -> CalibratedProjectiveJacobian:
    """Propagate one empirical Gram through calibrated projective geometry."""

    left_values, right_values = tuple(left), tuple(right)
    centres = (*left_values, *right_values)
    basis = tuple(input_basis)
    dimension = 2 * len(centres)
    if len(basis) != dimension or len(empirical_gram) != dimension or any(
        len(row) != dimension for row in empirical_gram
    ):
        raise ValueError("projective Jacobian basis/Gram dimension is invalid")
    if any(
        not math.isfinite(float(value)) for row in empirical_gram for value in row
    ):
        raise ValueError("projective Jacobian Gram is non-finite")
    relative_step = 2.0 ** -24
    scale = max(1.0, *(abs(value) for value in centres))
    step = relative_step * scale
    jacobian: list[float] = []
    split = len(left_values)
    for coordinate in range(dimension):
        component_index, imaginary = divmod(coordinate, 2)
        delta = (1j if imaginary else 1.0) * step
        plus, minus = list(centres), list(centres)
        plus[component_index] += delta
        minus[component_index] -= delta
        plus_angle = _calibrated_normalized_angle(
            plus[:split], plus[split:]
        )
        minus_angle = _calibrated_normalized_angle(
            minus[:split], minus[split:]
        )
        jacobian.append((plus_angle - minus_angle) / (2.0 * step))
    vector = tuple(jacobian)
    scalar = sum(
        vector[row] * empirical_gram[row][column] * vector[column]
        for row in range(dimension)
        for column in range(dimension)
    )
    return CalibratedProjectiveJacobian(
        input_basis=basis,
        step_policy={
            "kind": "central-real-imaginary-quadrature/binary64",
            "relative_step_binary64_hex": relative_step.hex(),
            "scale_policy": "max-one-and-complex-centre-modulus",
            "step_size_binary64_hex": step.hex(),
            "calibration_policy": "divide-by-first-mode-per-vector",
            "normalization_policy": "unit-l2-before-fubini-study",
        },
        jacobian=vector,
        scalar_gram=scalar,
    )


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
        str,
        ResolvedComponentEvidence
        | BoundedComponentEvidence
        | ComputedUnresolvedComponentEvidence,
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
            linearized_input_basis=(),
            linearized_step_policy=None,
            linearized_angle_jacobian=(),
            linearized_angle_gram=None,
            linearized_angle_columns=(),
            reason="required aligned component evidence is absent",
        )
    ordered_evidence = tuple(components[component_id] for component_id in required)
    if any(
        not isinstance(
            component,
            (
                ResolvedComponentEvidence,
                BoundedComponentEvidence,
                ComputedUnresolvedComponentEvidence,
            ),
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
            linearized_input_basis=(),
            linearized_step_policy=None,
            linearized_angle_jacobian=(),
            linearized_angle_gram=None,
            linearized_angle_columns=(),
            reason="one or more produced components are numerically unresolved",
        )
    bounded_components = tuple(
        component for component in ordered_evidence
        if isinstance(component, BoundedComponentEvidence)
    )
    if bounded_components:
        if len(bounded_components) != len(ordered_evidence):
            raise ValueError(
                "projective row cannot mix retained disks with signed-channel evidence"
            )
        split = len(plan.left_component_ids)
        left = tuple(component.centre for component in bounded_components[:split])
        right = tuple(component.centre for component in bounded_components[split:])
        left_radius = _vector_projective_radius(
            math.sqrt(sum(abs(value) ** 2 for value in left)),
            math.sqrt(sum(item.disk_radius ** 2 for item in bounded_components[:split])),
        )
        right_radius = _vector_projective_radius(
            math.sqrt(sum(abs(value) ** 2 for value in right)),
            math.sqrt(sum(item.disk_radius ** 2 for item in bounded_components[split:])),
        )
        calibration_zero = (
            abs(bounded_components[0].centre) <= bounded_components[0].disk_radius
            or abs(bounded_components[split].centre)
            <= bounded_components[split].disk_radius
        )
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
                empirical_gram_id=None,
                linearized_input_basis=(),
                linearized_step_policy=None,
                linearized_angle_jacobian=(),
                linearized_angle_gram=None,
                linearized_angle_columns=(),
                reason=(
                    "calibration disk contains zero" if calibration_zero
                    else "component disks do not prove a bounded projective interval"
                ),
            )
        nominal = _calibrated_normalized_angle(left, right)
        width = left_radius + right_radius
        interval = (
            max(0.0, nominal - width),
            min(math.pi / 2.0, nominal + width),
        )
        if interval[0] > plan.separation_lower_radians:
            outcome, scientific_state = "SEPARATED", "CONTRADICTED"
            reason = (
                "conservative angle lower bound exceeds the frozen separation threshold"
            )
        elif interval[1] < plan.equivalence_upper_radians:
            outcome, scientific_state = "EQUIVALENT_WITHIN_TOLERANCE", "SUPPORTED"
            reason = (
                "conservative angle upper bound is below the frozen equivalence threshold"
            )
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
            empirical_gram_id=None,
            linearized_input_basis=(),
            linearized_step_policy=None,
            linearized_angle_jacobian=(),
            linearized_angle_gram=None,
            linearized_angle_columns=(),
            reason=reason,
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
    left_denominator = ordered_components[0]
    right_denominator = ordered_components[split]
    calibration_zero = (
        abs(left_denominator.centre) <= gram.local_disks[left_denominator.component_id]
        or abs(right_denominator.centre) <= gram.local_disks[right_denominator.component_id]
    )
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
            linearized_input_basis=(),
            linearized_step_policy=None,
            linearized_angle_jacobian=(),
            linearized_angle_gram=None,
            linearized_angle_columns=(),
            reason=(
                "calibration disk contains zero" if calibration_zero
                else "component disks do not prove a bounded projective interval"
            ),
        )

    diagnostic = build_calibrated_projective_jacobian(
        left, right, gram.basis, gram.matrix
    )
    nominal = _calibrated_normalized_angle(left, right)
    width = left_radius + right_radius
    interval = (max(0.0, nominal - width), min(math.pi / 2.0, nominal + width))
    angle_columns = tuple(
        (
            channel_id,
            sum(
                derivative * coordinate
                for derivative, coordinate in zip(diagnostic.jacobian, column)
            ),
        )
        for channel_id, column in zip(gram.channel_ids, gram.columns)
    )
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
        linearized_input_basis=diagnostic.input_basis,
        linearized_step_policy=diagnostic.step_policy,
        linearized_angle_jacobian=diagnostic.jacobian,
        linearized_angle_gram=diagnostic.scalar_gram,
        linearized_angle_columns=angle_columns,
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
    empirical_grams: tuple[EmpiricalErrorGram, ...]
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
            "empirical_grams": [gram.to_mapping() for gram in self.empirical_grams],
            "reduction_id": self.reduction_id,
            "release_admissible": False,
        }

    @classmethod
    def from_mapping(cls, value: object) -> "CampaignReductionSummary":
        mapping = _exact_mapping_fields(
            value,
            frozenset({
                "schema_version", "kind", "campaign_id", "reducer_state",
                "selected_row_ids", "present_component_ids", "missing_component_ids",
                "row_plan_sha256", "source_hashes", "plans", "results",
                "empirical_grams", "reduction_id", "release_admissible",
            }),
            "campaign reduction summary",
        )
        if (
            mapping["schema_version"] != 1
            or mapping["kind"] != "b-prime-projective-reduction"
            or mapping["release_admissible"] is not False
        ):
            raise ValueError("campaign reduction summary envelope is invalid")
        for name in (
            "selected_row_ids", "present_component_ids", "missing_component_ids",
            "source_hashes", "plans", "results", "empirical_grams",
        ):
            if not isinstance(mapping[name], list):
                raise ValueError(f"campaign reduction summary {name} is invalid")
        selected = tuple(mapping["selected_row_ids"])
        frozen = {plan.row_id: plan for plan in build_projective_row_plans()}
        if any(row_id not in frozen for row_id in selected):
            raise ValueError("campaign reduction summary row selection is invalid")
        plans = tuple(frozen[row_id] for row_id in selected)
        if [plan.to_mapping() for plan in plans] != mapping["plans"]:
            raise ValueError("campaign reduction summary plans are not frozen")
        results = tuple(ProjectiveRowResult.from_mapping(item) for item in mapping["results"])
        if tuple(result.row_id for result in results) != selected:
            raise ValueError("campaign reduction summary result order is invalid")
        grams = tuple(EmpiricalErrorGram.from_mapping(item) for item in mapping["empirical_grams"])
        gram_ids = tuple(gram.construction_id for gram in grams)
        referenced = tuple(
            result.empirical_gram_id
            for result in results
            if result.empirical_gram_id is not None
        )
        if gram_ids != referenced or len(gram_ids) != len(set(gram_ids)):
            raise ValueError("campaign reduction summary Gram references are invalid")
        expected_plan_sha = hashlib.sha256(canonical_json_bytes(mapping["plans"])).hexdigest()
        if mapping["row_plan_sha256"] != expected_plan_sha:
            raise ValueError("campaign reduction summary row plan hash is invalid")
        material = {
            key: item for key, item in mapping.items()
            if key not in {"reduction_id", "release_admissible"}
        }
        expected_id = "b-prime-reduction-" + hashlib.sha256(
            canonical_json_bytes(material)
        ).hexdigest()
        if mapping["reduction_id"] != expected_id:
            raise ValueError("campaign reduction summary hash is invalid")
        summary = cls(
            campaign_id=mapping["campaign_id"],
            reducer_state=mapping["reducer_state"],
            selected_row_ids=selected,
            present_component_ids=tuple(mapping["present_component_ids"]),
            missing_component_ids=tuple(mapping["missing_component_ids"]),
            row_plan_sha256=mapping["row_plan_sha256"],
            source_hashes=tuple(mapping["source_hashes"]),
            plans=plans,
            results=results,
            empirical_grams=grams,
            reduction_id=mapping["reduction_id"],
        )
        if summary.to_mapping() != value:
            raise ValueError("campaign reduction summary is not canonical")
        return summary


def reduce_projective_rows(
    campaign_id: str,
    selected_row_ids: Sequence[str],
    components: Mapping[
        str,
        ResolvedComponentEvidence
        | BoundedComponentEvidence
        | ComputedUnresolvedComponentEvidence,
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
    empirical_grams: list[EmpiricalErrorGram] = []
    for plan, result in zip(plans, results):
        if result.empirical_gram_id is None:
            continue
        required = (*plan.left_component_ids, *plan.right_component_ids)
        ordered = tuple(components[component_id] for component_id in required)
        if not all(isinstance(item, ResolvedComponentEvidence) for item in ordered):
            raise ValueError("resolved row Gram lacks resolved component evidence")
        gram = build_empirical_error_gram(ordered, source_hashes=hashes)
        validate_empirical_error_gram(gram, ordered)
        if gram.construction_id != result.empirical_gram_id:
            raise ValueError("reduction result Gram identity drifted")
        empirical_grams.append(gram)
    present = tuple(item for item in required_order if item in components)
    missing = tuple(item for item in required_order if item not in components)
    reducer_state = "INCOMPLETE" if missing else "COMPLETE"
    row_plan_sha256 = hashlib.sha256(canonical_json_bytes(
        [plan.to_mapping() for plan in plans]
    )).hexdigest()
    material = {
        "schema_version": 1,
        "kind": "b-prime-projective-reduction",
        "campaign_id": campaign_id,
        "reducer_state": reducer_state,
        "selected_row_ids": requested,
        "present_component_ids": present,
        "missing_component_ids": missing,
        "row_plan_sha256": row_plan_sha256,
        "source_hashes": hashes,
        "plans": [plan.to_mapping() for plan in plans],
        "results": [result.to_mapping() for result in results],
        "empirical_grams": [gram.to_mapping() for gram in empirical_grams],
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
        empirical_grams=tuple(empirical_grams),
        reduction_id=reduction_id,
    )
