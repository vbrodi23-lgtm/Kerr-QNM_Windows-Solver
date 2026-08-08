"""Strict public contract for first-order complex QNM frequency shifts."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import hashlib
import math
import platform
import re
from types import MappingProxyType
from typing import Any, Mapping

from .contracts import (
    Capability,
    ModeKey,
    NumericalState,
    ScientificState,
    StudyRequest,
    canonical_json_bytes,
)
from .providers import ProviderDescriptor


LINEAR_RESPONSE_PROVIDER_ID = "kerr-qnm-linear-response"
LINEAR_RESPONSE_IMPLEMENTATION_VERSION = "1"
LINEAR_RESPONSE_EQUATIONS_ID = "simple-root-first-order-qnm-shift"
LINEAR_RESPONSE_CONVENTIONS_ID = "request-bound-linear-response"
LINEAR_RESPONSE_OUTPUT_ARTIFACT_TYPE = "kerr-qnm-linear-response"
LINEAR_RESPONSE_EVIDENCE_LEVEL = "contract-only-not-admitted"
LINEAR_RESPONSE_QUANTITY = "first-order-complex-qnm-frequency-shift"
LINEAR_RESPONSE_EVIDENCE_CEILING = (
    "component-local-empirical-not-formal-enclosure"
)

LINEAR_RESPONSE_DESCRIPTOR = ProviderDescriptor(
    capability=Capability.LINEAR_RESPONSE,
    provider_id=LINEAR_RESPONSE_PROVIDER_ID,
    implementation_version=LINEAR_RESPONSE_IMPLEMENTATION_VERSION,
    equations_id=LINEAR_RESPONSE_EQUATIONS_ID,
    conventions_id=LINEAR_RESPONSE_CONVENTIONS_ID,
    runtime_fingerprint=f"cpython-{platform.python_version()}",
    numerical_policy_fingerprint="linear-response-contract-1",
    upstream_artifact_types=("kerr-qnm-spectrum",),
    output_artifact_type=LINEAR_RESPONSE_OUTPUT_ARTIFACT_TYPE,
    available=False,
    evidence_level=LINEAR_RESPONSE_EVIDENCE_LEVEL,
)

_GENERAL_RELATIVITY = "general-relativity"
_CUBIC_THEORY = "parity-even-cubic-higher-curvature-eft"
_KERR_CONVENTION = "kerr-mass-normalized-outgoing"
_CUBIC_CONVENTION = "cubic-even-220-reference"
_HEX_40 = re.compile(r"[0-9a-f]{40}")
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_BRANCH_CLASSES = frozenset({"damped", "zero-damping", "unresolved"})
_RESOLVED_NUMERICAL_STATES = frozenset(
    {NumericalState.CONVERGED, NumericalState.ACCEPTED}
)
_EMPTY_RESULT_NUMERICAL_STATES = frozenset(
    {NumericalState.UNRESOLVED, NumericalState.REJECTED}
)
_PROJECTIVE_STATES = frozenset(
    {
        ScientificState.SUPPORTED,
        ScientificState.FRAGILE,
        ScientificState.UNRESOLVED,
        ScientificState.CONTRADICTED,
    }
)
_FROZEN_MODE_COORDINATES = frozenset(
    {
        (2, 2, 0),
        (2, 2, 1),
        (2, 2, 2),
        (3, 3, 0),
        (3, 3, 1),
        (4, 4, 0),
        (4, 4, 1),
        (2, 1, 0),
        (2, -2, 0),
        (3, 2, 0),
        (3, -3, 0),
    }
)
_FROZEN_SPINS = frozenset(
    {
        Fraction(19, 20),
        Fraction(97, 100),
        Fraction(49, 50),
        Fraction(99, 100),
        Fraction(199, 200),
        Fraction(997, 1000),
        Fraction(999, 1000),
        Fraction(1999, 2000),
        Fraction(9999, 10000),
    }
)
_FROZEN_SURFACE_GRAVITIES = frozenset(
    {
        Fraction(1, 100),
        Fraction(1, 200),
        Fraction(1, 500),
        Fraction(1, 1000),
    }
)


def _exact_fields(
    mapping: Mapping[str, Any], expected: frozenset[str], subject: str
) -> None:
    unknown = sorted(set(mapping) - expected)
    if unknown:
        raise ValueError(f"unknown {subject} fields: {', '.join(unknown)}")
    missing = sorted(expected - set(mapping))
    if missing:
        raise ValueError(f"missing {subject} fields: {', '.join(missing)}")


def _object(value: object, subject: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise ValueError(f"{subject} must be an object with string keys")
    return value


def _array(value: object, subject: str) -> list[Any]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{subject} must be an array")
    return list(value)


def _string(value: object, subject: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{subject} must be a non-empty string")
    return value


def _number(
    value: object,
    subject: str,
    *,
    minimum: float | None = None,
    strictly_positive: bool = False,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{subject} must be a finite number")
    converted = float(value)
    if not math.isfinite(converted):
        raise ValueError(f"{subject} must be a finite number")
    if strictly_positive and converted <= 0.0:
        raise ValueError(f"{subject} must be positive")
    if minimum is not None and converted < minimum:
        raise ValueError(f"{subject} must be at least {minimum}")
    return converted


def _integer(value: object, subject: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{subject} must be an integer")
    return value


def _boolean(value: object, subject: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{subject} must be boolean")
    return value


def _hex(value: object, subject: str, pattern: re.Pattern[str]) -> str:
    text = _string(value, subject)
    if pattern.fullmatch(text) is None:
        raise ValueError(f"{subject} must be a lowercase hexadecimal digest")
    return text


def _fraction_for_spin(spin: float) -> Fraction:
    return Fraction(str(float(spin)))


def _spin_identity(spin: float) -> tuple[int, int, str]:
    fraction = _fraction_for_spin(spin)
    return fraction.numerator, fraction.denominator, float(spin).hex()


def spin_from_dimensionless_surface_gravity(value: float) -> float:
    """Map the frozen Kerr Mκ coordinate to the prograde dimensionless spin."""

    kappa = _number(
        value,
        "dimensionless surface gravity",
        strictly_positive=True,
    )
    if kappa >= 0.5:
        raise ValueError("dimensionless surface gravity must be below 0.5")
    horizon_gap = 2.0 * kappa / (1.0 - 2.0 * kappa)
    radicand = 1.0 - horizon_gap * horizon_gap
    if radicand <= 0.0:
        raise ValueError("dimensionless surface gravity has no prograde Kerr spin")
    return math.sqrt(radicand)


@dataclass(frozen=True, slots=True)
class BPrimeLeaf:
    """One explicitly role-scoped B′ response leaf, before computation."""

    leaf_id: str
    role: str
    mode_label: str
    mode: tuple[int, int, int]
    spin_role: str
    coordinate: Fraction
    spin: float
    mechanism_id: str


@dataclass(frozen=True, slots=True)
class BPrimeRootSelector:
    """A root input required by B′, with its base/overlay disposition frozen."""

    selector_id: str
    role: str
    mode_label: str
    mode: tuple[int, int, int]
    spin_role: str
    coordinate: Fraction
    spin: float
    availability: str


@dataclass(frozen=True, slots=True)
class BPrimeReleaseDomain:
    """The typed, non-Cartesian M02 B′ release contract."""

    production_leaves: tuple[BPrimeLeaf, ...]
    root_selectors: tuple[BPrimeRootSelector, ...]
    projective_row_ids: tuple[str, ...]
    primary_supports: Mapping[str, tuple[str, ...]]
    deep_support: tuple[str, ...]
    exterior_mechanism_ids: tuple[str, ...]
    cubic_comparator_rows: tuple[tuple[Fraction, str], ...]
    precision_promotion_gates: tuple[str, ...]
    fixed_precision_sentinel_leaf_ids: tuple[str, ...]

    @property
    def production_leaf_ids(self) -> tuple[str, ...]:
        return tuple(leaf.leaf_id for leaf in self.production_leaves)

    @property
    def leaf_counts_by_role(self) -> dict[str, int]:
        return {
            role: sum(leaf.role == role for leaf in self.production_leaves)
            for role in ("primary", "control", "deep")
        }

    @property
    def selector_counts_by_role(self) -> dict[str, int]:
        return {
            role: sum(selector.role == role for selector in self.root_selectors)
            for role in ("primary", "control", "deep")
        }

    @property
    def missing_root_selector_ids(self) -> tuple[str, ...]:
        return tuple(
            selector.selector_id
            for selector in self.root_selectors
            if selector.availability == "missing-overlay"
        )

    @property
    def missing_selector_counts_by_role(self) -> dict[str, int]:
        return {
            role: sum(
                selector.role == role and selector.availability == "missing-overlay"
                for selector in self.root_selectors
            )
            for role in ("primary", "control", "deep")
        }

    @property
    def projective_counts(self) -> dict[str, int]:
        return {
            "primary": sum(row.startswith("primary-") for row in self.projective_row_ids),
            "deep": sum(row.startswith("deep-") for row in self.projective_row_ids),
            "total": len(self.projective_row_ids),
        }

    @property
    def cubic_comparator_row_count(self) -> int:
        return len(self.cubic_comparator_rows)


def _b_prime_identifier(kind: str, material: Mapping[str, object]) -> str:
    digest = hashlib.sha256(canonical_json_bytes(dict(material))).hexdigest()
    return f"b-prime-{kind}-{digest}"


def _build_b_prime_release_domain() -> BPrimeReleaseDomain:
    """Build only the declared role products; never complete an ambient grid."""

    modes = {
        "220": (2, 2, 0), "221": (2, 2, 1), "222": (2, 2, 2),
        "330": (3, 3, 0), "331": (3, 3, 1), "440": (4, 4, 0),
        "441": (4, 4, 1), "210": (2, 1, 0),
        "2-minus-2-0": (2, -2, 0), "320": (3, 2, 0),
        "3-minus-3-0": (3, -3, 0),
    }
    primary_modes = ("220", "221", "222", "330", "331", "440", "441")
    control_modes = ("210", "2-minus-2-0", "320", "3-minus-3-0")
    deep_modes = ("220", "221", "222", "210")
    primary_mechanisms = (
        "horizon-admittance", "exterior-fixed-r3", "exterior-light-ring",
        "exterior-throat-kappa", "exterior-alpha-zero", "exterior-alpha-half",
        "exterior-alpha-one",
    )
    exterior_mechanisms = primary_mechanisms[1:]
    deep_mechanisms = (
        "horizon-admittance", "exterior-alpha-one", "exterior-light-ring",
        "exterior-throat-kappa",
    )
    direct_spins = tuple(sorted(_FROZEN_SPINS))
    deep_coordinates = tuple(sorted(_FROZEN_SURFACE_GRAVITIES))
    control_spins = (Fraction(19, 20), Fraction(999, 1000))

    leaves: list[BPrimeLeaf] = []
    selector_by_identity: dict[tuple[tuple[int, int, int], str], BPrimeRootSelector] = {}

    def add_role(
        role: str, labels: tuple[str, ...], spin_role: str,
        coordinates: tuple[Fraction, ...], mechanisms: tuple[str, ...],
    ) -> None:
        for label in labels:
            mode = modes[label]
            for coordinate in coordinates:
                spin = (
                    float(coordinate) if spin_role == "direct"
                    else spin_from_dimensionless_surface_gravity(float(coordinate))
                )
                identity = (mode, spin.hex())
                if identity not in selector_by_identity:
                    missing = (
                        role == "deep"
                        or (role == "primary" and label in {"440", "441"})
                        or (
                            role == "primary"
                            and coordinate in {Fraction(1999, 2000), Fraction(9999, 10000)}
                        )
                    )
                    selector_material = {
                        "mode": mode, "spin_binary64_hex": spin.hex(),
                    }
                    selector_by_identity[identity] = BPrimeRootSelector(
                        selector_id=_b_prime_identifier("root", selector_material),
                        role=role, mode_label=label, mode=mode, spin_role=spin_role,
                        coordinate=coordinate, spin=spin,
                        availability="missing-overlay" if missing else "base-2736",
                    )
                for mechanism_id in mechanisms:
                    material = {
                        "role": role, "mode": mode, "spin_role": spin_role,
                        "coordinate": [coordinate.numerator, coordinate.denominator],
                        "mechanism_id": mechanism_id,
                    }
                    leaves.append(BPrimeLeaf(
                        leaf_id=_b_prime_identifier("leaf", material), role=role,
                        mode_label=label, mode=mode, spin_role=spin_role,
                        coordinate=coordinate, spin=spin, mechanism_id=mechanism_id,
                    ))

    add_role("primary", primary_modes, "direct", direct_spins, primary_mechanisms)
    add_role("control", control_modes, "direct", control_spins, exterior_mechanisms)
    add_role("deep", deep_modes, "M-kappa", deep_coordinates, deep_mechanisms)

    primary_supports = MappingProxyType({
        "K0": ("220", "330", "440"),
        "K1": ("221", "331", "441"),
        "K22": ("220", "221", "222"),
    })
    projective_rows = tuple(
        f"primary-{support}-{coordinate.numerator}-{coordinate.denominator}-{mechanism}"
        for support in primary_supports
        for coordinate in direct_spins
        for mechanism in exterior_mechanisms
    ) + tuple(
        f"deep-K22-{coordinate.numerator}-{coordinate.denominator}-{mechanism}"
        for coordinate in deep_coordinates
        for mechanism in deep_mechanisms[1:]
    )
    sentinels = tuple(
        leaf.leaf_id for leaf in leaves
        if leaf.role == "deep" and (
            (leaf.mode_label == "220" and leaf.mechanism_id == "horizon-admittance")
            or (leaf.mode_label == "222" and leaf.mechanism_id == "exterior-throat-kappa")
        )
    )
    return BPrimeReleaseDomain(
        production_leaves=tuple(leaves),
        root_selectors=tuple(selector_by_identity.values()),
        projective_row_ids=projective_rows,
        primary_supports=primary_supports,
        deep_support=("220", "221", "222"),
        exterior_mechanism_ids=exterior_mechanisms,
        cubic_comparator_rows=tuple(
            (spin, polarization)
            for spin in (Fraction(0), Fraction(3, 10), Fraction(1, 2), Fraction(7, 10))
            for polarization in ("plus", "minus")
        ),
        precision_promotion_gates=(
            "fewer-than-ten-predicted-reliable-decimal-digits",
            "step-halving-or-richardson-centres-disagree-by-more-than-quarter-local-disk",
            "repeat-polish-angular-refinement-or-independent-continuation-exceeds-ceiling",
            "denominator-or-calibration-disk-contains-zero-from-numerical-width",
        ),
        fixed_precision_sentinel_leaf_ids=sentinels,
    )


B_PRIME_RELEASE_DOMAIN = _build_b_prime_release_domain()
B_PRIME_UNRESOLVED_IS_PRODUCED = True


@dataclass(frozen=True, slots=True)
class MechanismContract:
    mechanism_id: str
    coordinate_id: str
    theory_id: str
    convention_id: str
    response_quantity_id: str
    parameter_values: tuple[tuple[str, tuple[str, ...]], ...]

    def validate_parameters(self, value: object) -> dict[str, str]:
        parameters = _object(value, f"{self.mechanism_id} parameters")
        expected = frozenset(name for name, _ in self.parameter_values)
        _exact_fields(parameters, expected, f"{self.mechanism_id} parameters")
        validated: dict[str, str] = {}
        for name, allowed in self.parameter_values:
            item = _string(
                parameters[name],
                f"{self.mechanism_id} parameter {name}",
            )
            if item not in allowed:
                raise ValueError(
                    f"{self.mechanism_id} parameters do not match the contract"
                )
            validated[name] = item
        return validated


def _mechanism_contracts() -> dict[str, MechanismContract]:
    exterior = (
        (
            "exterior-fixed-r3",
            "fixed-r3",
            "r_over_M=3",
            "0.45M",
        ),
        (
            "exterior-light-ring",
            "light-ring",
            "prograde-photon-orbit",
            "max(0.012M,0.25(r_ph-r_plus))",
        ),
        (
            "exterior-throat-kappa",
            "throat-kappa",
            "r_plus+3kappaM",
            "max(0.012M,0.6kappaM)",
        ),
        (
            "exterior-alpha-zero",
            "alpha-zero",
            "r_plus+2M",
            "0.5M",
        ),
        (
            "exterior-alpha-half",
            "alpha-half",
            "r_plus+2sqrt(kappa)M",
            "max(0.012M,0.5sqrt(kappa)M)",
        ),
        (
            "exterior-alpha-one",
            "alpha-one",
            "r_plus+4kappaM",
            "max(0.012M,kappaM)",
        ),
    )
    contracts = {
        "horizon-admittance": MechanismContract(
            mechanism_id="horizon-admittance",
            coordinate_id="unit-complex-deltaB",
            theory_id=_GENERAL_RELATIVITY,
            convention_id=_KERR_CONVENTION,
            response_quantity_id="h_B",
            parameter_values=(
                ("normalization", ("unit-common-delta-B",)),
            ),
        ),
        "cubic-eft": MechanismContract(
            mechanism_id="cubic-eft",
            coordinate_id="unit-dimensionless-cubic-coupling",
            theory_id=_CUBIC_THEORY,
            convention_id=_CUBIC_CONVENTION,
            response_quantity_id="delta-omega-cubic",
            parameter_values=(("polarization", ("plus", "minus")),),
        ),
    }
    contracts.update(
        {
            mechanism_id: MechanismContract(
                mechanism_id=mechanism_id,
                coordinate_id="unit-complex-profile-amplitude",
                theory_id=_GENERAL_RELATIVITY,
                convention_id=_KERR_CONVENTION,
                response_quantity_id="e_F",
                parameter_values=(
                    ("profile_id", (profile,)),
                    ("centre_rule", (centre_rule,)),
                    ("half_width_rule", (half_width_rule,)),
                ),
            )
            for mechanism_id, profile, centre_rule, half_width_rule in exterior
        }
    )
    return contracts


MECHANISM_CONTRACTS: Mapping[str, MechanismContract] = MappingProxyType(
    _mechanism_contracts()
)


@dataclass(frozen=True, slots=True)
class MechanismSelection:
    mechanism_id: str
    coordinate_id: str
    theory_id: str
    convention_id: str
    response_quantity_id: str
    parameters: tuple[tuple[str, str], ...]

    @classmethod
    def from_mapping(cls, value: object) -> "MechanismSelection":
        mapping = _object(value, "linear-response mechanism selection")
        _exact_fields(
            mapping,
            frozenset(
                {
                    "mechanism_id",
                    "coordinate_id",
                    "theory_id",
                    "convention_id",
                    "response_quantity_id",
                    "parameters",
                }
            ),
            "linear-response mechanism selection",
        )
        mechanism_id = _string(mapping["mechanism_id"], "mechanism_id")
        contract = MECHANISM_CONTRACTS.get(mechanism_id)
        if contract is None:
            raise ValueError(f"unsupported mechanism: {mechanism_id}")
        coordinate_id = _string(mapping["coordinate_id"], "coordinate_id")
        if coordinate_id != contract.coordinate_id:
            raise ValueError(
                f"coordinate {coordinate_id!r} is invalid for {mechanism_id}"
            )
        theory_id = _string(mapping["theory_id"], "mechanism theory_id")
        convention_id = _string(
            mapping["convention_id"], "mechanism convention_id"
        )
        response_quantity_id = _string(
            mapping["response_quantity_id"], "response_quantity_id"
        )
        if theory_id != contract.theory_id:
            raise ValueError(f"{mechanism_id} theory identity is invalid")
        if convention_id != contract.convention_id:
            raise ValueError(f"{mechanism_id} convention identity is invalid")
        if response_quantity_id != contract.response_quantity_id:
            raise ValueError(f"{mechanism_id} response quantity is invalid")
        parameters = contract.validate_parameters(mapping["parameters"])
        return cls(
            mechanism_id=mechanism_id,
            coordinate_id=coordinate_id,
            theory_id=theory_id,
            convention_id=convention_id,
            response_quantity_id=response_quantity_id,
            parameters=tuple(sorted(parameters.items())),
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "mechanism_id": self.mechanism_id,
            "coordinate_id": self.coordinate_id,
            "theory_id": self.theory_id,
            "convention_id": self.convention_id,
            "response_quantity_id": self.response_quantity_id,
            "parameters": dict(self.parameters),
        }


@dataclass(frozen=True, slots=True)
class SpinSamplingCoordinate:
    coordinate_id: str
    coordinate_value: float
    coordinate_exact: tuple[int, int]
    spin: float
    spin_exact: tuple[int, int]
    spin_binary64_hex: str
    transformation_id: str

    @classmethod
    def from_mapping(cls, value: object) -> "SpinSamplingCoordinate":
        mapping = _object(value, "linear-response sampling coordinate")
        _exact_fields(
            mapping,
            frozenset(
                {
                    "coordinate_id",
                    "coordinate_value",
                    "coordinate_exact",
                    "spin",
                    "spin_exact",
                    "spin_binary64_hex",
                    "transformation_id",
                }
            ),
            "linear-response sampling coordinate",
        )
        coordinate_id = _string(mapping["coordinate_id"], "coordinate_id")
        coordinate_value = _number(
            mapping["coordinate_value"], "sampling coordinate value"
        )
        coordinate_exact = _object(
            mapping["coordinate_exact"], "sampling coordinate exact identity"
        )
        _exact_fields(
            coordinate_exact,
            frozenset({"numerator", "denominator"}),
            "sampling coordinate exact identity",
        )
        numerator = _integer(
            coordinate_exact["numerator"], "sampling coordinate numerator"
        )
        denominator = _integer(
            coordinate_exact["denominator"], "sampling coordinate denominator"
        )
        if denominator <= 0:
            raise ValueError("sampling coordinate denominator must be positive")
        fraction = Fraction(numerator, denominator)
        if fraction != Fraction(str(float(coordinate_value))):
            raise ValueError("sampling coordinate exact identity is invalid")

        spin, spin_exact, spin_hex = _validate_spin_fields(
            mapping, "sampling coordinate"
        )
        transformation_id = _string(
            mapping["transformation_id"], "sampling transformation_id"
        )
        if coordinate_id == "a_over_M":
            if fraction not in _FROZEN_SPINS:
                raise ValueError("direct spin is outside the frozen response domain")
            expected_spin = coordinate_value
            expected_transformation = "identity-a-over-M"
        elif coordinate_id == "M-kappa":
            if fraction not in _FROZEN_SURFACE_GRAVITIES:
                raise ValueError(
                    "surface gravity is outside the frozen response domain"
                )
            expected_spin = spin_from_dimensionless_surface_gravity(
                coordinate_value
            )
            expected_transformation = (
                "kerr-prograde-spin-from-dimensionless-surface-gravity"
            )
        else:
            raise ValueError("sampling coordinate_id is invalid")
        if (
            spin != expected_spin
            or spin_hex != expected_spin.hex()
            or transformation_id != expected_transformation
        ):
            raise ValueError("sampling coordinate transformation is invalid")
        return cls(
            coordinate_id=coordinate_id,
            coordinate_value=coordinate_value,
            coordinate_exact=(numerator, denominator),
            spin=spin,
            spin_exact=spin_exact,
            spin_binary64_hex=spin_hex,
            transformation_id=transformation_id,
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "coordinate_id": self.coordinate_id,
            "coordinate_value": self.coordinate_value,
            "coordinate_exact": {
                "numerator": self.coordinate_exact[0],
                "denominator": self.coordinate_exact[1],
            },
            "spin": self.spin,
            "spin_exact": {
                "numerator": self.spin_exact[0],
                "denominator": self.spin_exact[1],
            },
            "spin_binary64_hex": self.spin_binary64_hex,
            "transformation_id": self.transformation_id,
        }


@dataclass(frozen=True, slots=True)
class RoleScopedLeaf:
    """One request leaf, explicitly bound to its B′ role and axes."""

    role: str
    mode: ModeKey
    sampling_coordinate: SpinSamplingCoordinate
    selection: MechanismSelection


def _sampling_coordinates_for_request(
    request: StudyRequest,
    section: Mapping[str, Any],
) -> tuple[SpinSamplingCoordinate, ...]:
    raw = _array(
        section["sampling_coordinates"],
        "linear-response sampling coordinates",
    )
    if not raw:
        raise ValueError("linear-response sampling coordinates must not be empty")
    coordinates = tuple(SpinSamplingCoordinate.from_mapping(item) for item in raw)
    identities = [canonical_json_bytes(item.to_mapping()) for item in coordinates]
    if len(identities) != len(set(identities)):
        raise ValueError("linear-response request contains duplicate coordinates")
    by_spin = {item.spin_binary64_hex: item for item in coordinates}
    if len(by_spin) != len(coordinates):
        raise ValueError("sampling coordinates contain duplicate derived spins")
    requested_spins = {float(spin).hex() for spin in request.spins}
    if set(by_spin) != requested_spins:
        raise ValueError(
            "sampling coordinates must exactly cover the requested spins"
        )
    return coordinates


def _role_scoped_leaves_for_request(
    request: StudyRequest,
    section: Mapping[str, Any],
    selections: tuple[MechanismSelection, ...],
    sampling_coordinates: tuple[SpinSamplingCoordinate, ...],
) -> tuple[RoleScopedLeaf, ...] | None:
    if "role_scoped_leaves" not in section:
        return None
    sampling_by_spin = {
        item.spin_binary64_hex: item for item in sampling_coordinates
    }
    leaves: list[RoleScopedLeaf] = []
    identities: set[tuple[str, ModeKey, str, str]] = set()
    for raw in _array(section["role_scoped_leaves"], "role-scoped leaves"):
        mapping = _object(raw, "role-scoped leaf")
        _exact_fields(
            mapping,
            frozenset({"role", "mode", "sampling_coordinate", "mechanism"}),
            "role-scoped leaf",
        )
        role = _string(mapping["role"], "role-scoped leaf role")
        mode = ModeKey.from_mapping(_object(mapping["mode"], "role-scoped leaf mode"))
        coordinate = SpinSamplingCoordinate.from_mapping(
            mapping["sampling_coordinate"]
        )
        selection = MechanismSelection.from_mapping(mapping["mechanism"])
        if mode not in request.modes or coordinate.spin not in request.spins:
            raise ValueError("role-scoped leaf is outside the request axes")
        if coordinate != sampling_by_spin.get(coordinate.spin_binary64_hex):
            raise ValueError("role-scoped leaf sampling coordinate is invalid")
        if selection not in selections:
            raise ValueError("role-scoped leaf mechanism is outside the request")
        identity = (role, mode, coordinate.spin_binary64_hex, selection.mechanism_id)
        if identity in identities:
            raise ValueError("role-scoped leaves contain duplicates")
        identities.add(identity)
        leaves.append(RoleScopedLeaf(role, mode, coordinate, selection))
    expected = {
        (
            leaf.role,
            ModeKey(
                -2, leaf.mode[0], leaf.mode[1], leaf.mode[2],
                "schwarzschild-overtone-continuation", "gravitational",
            ),
            leaf.spin.hex(), leaf.mechanism_id,
        )
        for leaf in B_PRIME_RELEASE_DOMAIN.production_leaves
    }
    if identities != expected:
        raise ValueError("role-scoped leaves must exactly match the B′ release domain")
    return tuple(leaves)


def validate_linear_response_request(
    request: StudyRequest,
) -> tuple[MechanismSelection, ...]:
    """Validate the complete selection before a numerical provider can run."""

    if request.target is not Capability.LINEAR_RESPONSE:
        raise ValueError("request target must be linear-response")
    if request.theory_id != _GENERAL_RELATIVITY:
        raise ValueError("linear-response baseline theory must be general-relativity")
    if request.convention_id != _KERR_CONVENTION:
        raise ValueError(
            "linear-response baseline convention must be kerr-mass-normalized-outgoing"
        )
    mode_identities = {
        canonical_json_bytes(mode.to_mapping()) for mode in request.modes
    }
    if len(request.modes) != len(mode_identities):
        raise ValueError("linear-response request contains duplicate modes")
    if len(request.spins) != len(set(request.spins)):
        raise ValueError("linear-response request contains duplicate spins")
    for mode in request.modes:
        if (
            mode.s != -2
            or (mode.ell, mode.m, mode.n) not in _FROZEN_MODE_COORDINATES
            or mode.branch != "schwarzschild-overtone-continuation"
            or mode.polarization != "gravitational"
        ):
            raise ValueError("mode is outside the frozen linear-response domain")
    section = _object(
        request.numerical_policy.get("linear-response"),
        "linear-response numerical policy",
    )
    _exact_fields(
        section,
        (
            frozenset({"mechanisms", "sampling_coordinates", "role_scoped_leaves"})
            if "role_scoped_leaves" in section
            else frozenset({"mechanisms", "sampling_coordinates"})
        ),
        "linear-response numerical policy",
    )
    sampling_coordinates = _sampling_coordinates_for_request(request, section)
    raw = _array(section["mechanisms"], "linear-response mechanisms")
    if not raw:
        raise ValueError("linear-response mechanisms must not be empty")
    selections = tuple(MechanismSelection.from_mapping(item) for item in raw)
    keys = [canonical_json_bytes(item.to_mapping()) for item in selections]
    if len(keys) != len(set(keys)):
        raise ValueError("linear-response request contains duplicate mechanisms")
    _role_scoped_leaves_for_request(request, section, selections, sampling_coordinates)
    return selections


def linear_response_leaf_id(
    mode: ModeKey,
    spin: float,
    selection: MechanismSelection,
) -> str:
    material = {
        "mode": mode.to_mapping(),
        "spin_binary64_hex": float(spin).hex(),
        "mechanism": selection.to_mapping(),
    }
    digest = hashlib.sha256(canonical_json_bytes(material)).hexdigest()
    return f"linear-response-{digest}"


def baseline_root_reference_id(mode: ModeKey, spin: float) -> str:
    material = {
        "mode": mode.to_mapping(),
        "spin_binary64_hex": float(spin).hex(),
    }
    digest = hashlib.sha256(canonical_json_bytes(material)).hexdigest()
    return f"spectral-root-reference-{digest}"


def _validate_spin_fields(
    mapping: Mapping[str, Any],
    subject: str,
) -> tuple[float, tuple[int, int], str]:
    spin = _number(mapping["spin"], f"{subject} spin")
    exact = _object(mapping["spin_exact"], f"{subject} spin_exact")
    _exact_fields(
        exact,
        frozenset({"numerator", "denominator"}),
        f"{subject} spin_exact",
    )
    numerator = _integer(exact["numerator"], f"{subject} spin numerator")
    denominator = _integer(
        exact["denominator"], f"{subject} spin denominator"
    )
    if denominator <= 0:
        raise ValueError(f"{subject} exact spin denominator must be positive")
    expected_numerator, expected_denominator, expected_hex = _spin_identity(spin)
    if (numerator, denominator) != (expected_numerator, expected_denominator):
        raise ValueError(f"{subject} exact spin identity is invalid")
    binary64_hex = _string(
        mapping["spin_binary64_hex"], f"{subject} spin_binary64_hex"
    )
    if binary64_hex != expected_hex:
        raise ValueError(f"{subject} binary64 spin identity is invalid")
    return spin, (numerator, denominator), binary64_hex


def _validate_deep_precision_evidence(
    value: object,
    numerical_state: NumericalState,
    *,
    sentinel_required: bool,
) -> None:
    evidence = _object(value, "deep precision evidence")
    _exact_fields(
        evidence,
        frozenset(
            {
                "trigger_ids", "promoted", "precision_digits",
                "repeat_precision_digits", "self_refinement_enclosed",
                "discrepancy_enclosed", "sentinel", "sentinel_comparison",
            }
        ),
        "deep precision evidence",
    )
    trigger_ids = _unique_sorted_strings(
        evidence["trigger_ids"], "deep precision trigger_ids"
    )
    if set(trigger_ids) - set(B_PRIME_RELEASE_DOMAIN.precision_promotion_gates):
        raise ValueError("deep precision evidence has an unknown promotion trigger")
    sentinel = _boolean(evidence["sentinel"], "deep precision sentinel")
    if sentinel != sentinel_required:
        raise ValueError("deep precision sentinel identity is invalid")
    comparison = evidence["sentinel_comparison"]
    if sentinel:
        sentinel_comparison = _object(
            comparison, "deep precision sentinel comparison"
        )
        _exact_fields(
            sentinel_comparison,
            frozenset(
                {
                    "binary64_to_80_discrepancy_abs",
                    "trigger_threshold_abs",
                    "trigger_policy_false_negative",
                }
            ),
            "deep precision sentinel comparison",
        )
        discrepancy = _number(
            sentinel_comparison["binary64_to_80_discrepancy_abs"],
            "deep precision sentinel binary64-to-80 discrepancy",
        )
        threshold = _number(
            sentinel_comparison["trigger_threshold_abs"],
            "deep precision sentinel trigger threshold",
        )
        if discrepancy < 0.0 or threshold <= 0.0:
            raise ValueError("deep precision sentinel comparison magnitudes are invalid")
        false_negative = _boolean(
            sentinel_comparison["trigger_policy_false_negative"],
            "deep precision sentinel false-negative outcome",
        )
        expected_false_negative = discrepancy > threshold and not bool(trigger_ids)
        if false_negative != expected_false_negative:
            raise ValueError("deep precision sentinel false-negative outcome is invalid")
        if false_negative:
            raise ValueError("deep precision sentinel false negative invalidates admission")
    elif comparison is not None:
        raise ValueError("deep precision sentinel comparison is not permitted")
    promoted = _boolean(evidence["promoted"], "deep precision promoted")
    if promoted != (bool(trigger_ids) or sentinel):
        raise ValueError("deep precision promotion rule is invalid")
    digits = _integer(evidence["precision_digits"], "deep precision digits")
    if digits != (80 if promoted else 64):
        raise ValueError("deep precision digits do not match the frozen policy")
    enclosed = _boolean(
        evidence["self_refinement_enclosed"], "deep self-refinement enclosure"
    )
    repeat = evidence["repeat_precision_digits"]
    if promoted and not enclosed:
        if (
            not isinstance(repeat, int)
            or isinstance(repeat, bool)
            or repeat != 120
        ):
            raise ValueError("deep precision repeat must run at 120 digits")
    elif repeat is not None:
        raise ValueError("deep precision repeat is not permitted")
    discrepancy_enclosed = _boolean(
        evidence["discrepancy_enclosed"], "deep precision discrepancy enclosure"
    )
    if numerical_state is NumericalState.ACCEPTED and not discrepancy_enclosed:
        raise ValueError("accepted deep component requires enclosed 80/120 discrepancy")


def _validate_complex(value: object, subject: str, units: str) -> tuple[float, float]:
    mapping = _object(value, subject)
    _exact_fields(mapping, frozenset({"real", "imaginary", "units"}), subject)
    if mapping["units"] != units:
        raise ValueError(f"{subject} units must be {units}")
    return (
        _number(mapping["real"], f"{subject} real part"),
        _number(mapping["imaginary"], f"{subject} imaginary part"),
    )


def _validate_real_symmetric_psd_matrix(
    value: object,
    dimension: int,
    subject: str,
) -> tuple[tuple[float, ...], ...]:
    rows = _array(value, f"{subject} matrix")
    if len(rows) != dimension:
        raise ValueError(f"{subject} matrix dimension is invalid")
    matrix: list[list[float]] = []
    for row_index, raw_row in enumerate(rows):
        row = _array(raw_row, f"{subject} matrix row {row_index}")
        if len(row) != dimension:
            raise ValueError(f"{subject} matrix dimension is invalid")
        matrix.append(
            [
                _number(item, f"{subject} matrix {row_index},{column_index}")
                for column_index, item in enumerate(row)
            ]
        )
    for row in range(dimension):
        if matrix[row][row] < 0.0:
            raise ValueError(f"{subject} matrix must be positive semidefinite")
        for column in range(row):
            if matrix[row][column] != matrix[column][row]:
                raise ValueError(f"{subject} matrix must be symmetric")
    lower = [[0.0 for _ in range(dimension)] for _ in range(dimension)]
    for column in range(dimension):
        diagonal = matrix[column][column] - sum(
            lower[column][item] * lower[column][item]
            for item in range(column)
        )
        if diagonal < 0.0:
            raise ValueError(f"{subject} matrix must be positive semidefinite")
        pivot = math.sqrt(diagonal)
        lower[column][column] = pivot
        for row in range(column + 1, dimension):
            residual = matrix[row][column] - sum(
                lower[row][item] * lower[column][item]
                for item in range(column)
            )
            if pivot > 0.0:
                lower[row][column] = residual / pivot
            elif residual != 0.0:
                raise ValueError(
                    f"{subject} matrix must be positive semidefinite"
                )
    return tuple(tuple(row) for row in matrix)


def _validate_covariance(
    value: object,
    subject: str,
) -> tuple[tuple[float, ...], ...]:
    mapping = _object(value, subject)
    _exact_fields(
        mapping,
        frozenset({"basis", "matrix", "representation", "kind"}),
        subject,
    )
    if mapping["basis"] != ["real", "imaginary"]:
        raise ValueError(f"{subject} basis must be ['real', 'imaginary']")
    if mapping["representation"] != "real-block-covariance":
        raise ValueError(f"{subject} representation is invalid")
    if mapping["kind"] != "component-local-empirical":
        raise ValueError(f"{subject} kind is invalid")
    return _validate_real_symmetric_psd_matrix(mapping["matrix"], 2, subject)


@dataclass(frozen=True, slots=True)
class _ComponentSummary:
    component_id: str
    mode: ModeKey
    spin: float
    spin_exact: tuple[int, int]
    spin_binary64_hex: str
    selection: MechanismSelection
    units: str
    numerical_state: NumericalState
    centre: tuple[float, float] | None
    disk_radius: float | None
    local_covariance: tuple[tuple[float, ...], ...] | None


def _validate_component(
    value: object,
    request: StudyRequest,
    selections: tuple[MechanismSelection, ...],
    sampling_by_spin: Mapping[str, SpinSamplingCoordinate],
    expected_ids: frozenset[str],
    root_reference_ids: frozenset[str],
    precision_requirements: Mapping[str, tuple[bool, bool]],
) -> _ComponentSummary:
    component = _object(value, "linear-response component")
    _exact_fields(
        component,
        frozenset(
            {
                "component_id",
                "baseline_root_reference_id",
                "mode",
                "spin",
                "spin_exact",
                "spin_binary64_hex",
                "sampling_coordinate",
                "mechanism",
                "branch_class",
                "numerical_state",
                "diagnostics",
                "result",
            }
        ),
        "linear-response component",
    )
    component_id = _string(component["component_id"], "component_id")
    if component_id not in expected_ids:
        raise ValueError("component_id is outside the requested leaf domain")
    mode = ModeKey.from_mapping(_object(component["mode"], "component mode"))
    if mode not in request.modes:
        raise ValueError("component mode is outside the request")
    spin, exact_spin, spin_hex = _validate_spin_fields(component, "component")
    if spin not in request.spins:
        raise ValueError("component spin is outside the request")
    sampling_coordinate = SpinSamplingCoordinate.from_mapping(
        component["sampling_coordinate"]
    )
    if sampling_coordinate != sampling_by_spin.get(spin_hex):
        raise ValueError("component sampling coordinate is invalid")
    selection = MechanismSelection.from_mapping(component["mechanism"])
    if selection not in selections:
        raise ValueError("component mechanism is outside the request")
    if component_id != linear_response_leaf_id(mode, spin, selection):
        raise ValueError("component_id does not match its coordinate identity")
    root_reference_id = _string(
        component["baseline_root_reference_id"],
        "baseline_root_reference_id",
    )
    if (
        root_reference_id not in root_reference_ids
        or root_reference_id != baseline_root_reference_id(mode, spin)
    ):
        raise ValueError("component baseline root reference is invalid")
    if component["branch_class"] not in _BRANCH_CLASSES:
        raise ValueError("component branch_class is invalid")
    try:
        numerical_state = NumericalState(component["numerical_state"])
    except (TypeError, ValueError) as error:
        raise ValueError("component numerical_state is invalid") from error
    if numerical_state not in (
        _RESOLVED_NUMERICAL_STATES | _EMPTY_RESULT_NUMERICAL_STATES
    ):
        raise ValueError("component numerical_state is not a produced state")

    diagnostics = _object(component["diagnostics"], "component diagnostics")
    diagnostic_fields = {
        "baseline_residual_abs", "determinant_derivative_abs",
        "signed_root_uncertainty_radius_abs", "method",
    }
    precision_requirement = precision_requirements.get(component_id)
    if precision_requirement is not None:
        diagnostic_fields.add("precision_evidence")
    _exact_fields(diagnostics, frozenset(diagnostic_fields), "component diagnostics")
    _number(
        diagnostics["baseline_residual_abs"],
        "baseline_residual_abs",
        minimum=0.0,
    )
    derivative = _number(
        diagnostics["determinant_derivative_abs"],
        "determinant_derivative_abs",
        minimum=0.0,
    )
    _number(
        diagnostics["signed_root_uncertainty_radius_abs"],
        "signed_root_uncertainty_radius_abs",
        minimum=0.0,
    )
    _string(diagnostics["method"], "component diagnostic method")
    if precision_requirement is not None:
        _validate_deep_precision_evidence(
            diagnostics["precision_evidence"], numerical_state,
            sentinel_required=precision_requirement[0],
        )

    result = _object(component["result"], "component result")
    _exact_fields(
        result,
        frozenset(
            {"centre", "local_covariance", "uncertainty_disk", "reason"}
        ),
        "component result",
    )
    units = f"Mdeltaomega-per-{selection.coordinate_id}"
    if numerical_state in _RESOLVED_NUMERICAL_STATES:
        if derivative <= 0.0:
            raise ValueError("resolved component requires a simple-root derivative")
        centre = _validate_complex(result["centre"], "response centre", units)
        local_covariance = _validate_covariance(
            result["local_covariance"],
            "local covariance",
        )
        disk = _object(result["uncertainty_disk"], "uncertainty disk")
        _exact_fields(
            disk,
            frozenset({"centre", "radius", "units", "kind"}),
            "uncertainty disk",
        )
        disk_centre = _validate_complex(disk["centre"], "disk centre", units)
        if disk_centre != centre:
            raise ValueError("disk centre must equal the response centre")
        disk_radius = _number(
            disk["radius"], "uncertainty disk radius", minimum=0.0
        )
        if disk["units"] != units:
            raise ValueError("uncertainty disk units are invalid")
        if disk["kind"] != "component-local-empirical-not-interval":
            raise ValueError("uncertainty disk kind is invalid")
        if result["reason"] is not None:
            raise ValueError("resolved result reason must be null")
    else:
        if any(
            result[field] is not None
            for field in ("centre", "local_covariance", "uncertainty_disk")
        ):
            raise ValueError("unresolved result cannot contain a response")
        _string(result["reason"], "unresolved result reason")
        centre = None
        disk_radius = None
        local_covariance = None
    return _ComponentSummary(
        component_id=component_id,
        mode=mode,
        spin=spin,
        spin_exact=exact_spin,
        spin_binary64_hex=spin_hex,
        selection=selection,
        units=units,
        numerical_state=numerical_state,
        centre=centre,
        disk_radius=disk_radius,
        local_covariance=local_covariance,
    )


def _unique_sorted_strings(value: object, subject: str) -> list[str]:
    items = [_string(item, f"{subject} item") for item in _array(value, subject)]
    if len(items) != len(set(items)):
        raise ValueError(f"{subject} contains duplicates")
    if items != sorted(items):
        raise ValueError(f"{subject} must be sorted")
    return items


def _validate_root_references(
    value: object,
    request: StudyRequest,
    sampling_by_spin: Mapping[str, SpinSamplingCoordinate],
    expected_coordinates: set[tuple[ModeKey, str]],
) -> frozenset[str]:
    references = _array(value, "baseline root references")
    seen: set[str] = set()
    coordinates: set[tuple[ModeKey, str]] = set()
    for raw in references:
        reference = _object(raw, "baseline root reference")
        _exact_fields(
            reference,
            frozenset(
                {
                    "root_reference_id",
                    "mode",
                    "spin",
                    "spin_exact",
                    "spin_binary64_hex",
                    "sampling_coordinate",
                }
            ),
            "baseline root reference",
        )
        mode = ModeKey.from_mapping(
            _object(reference["mode"], "baseline root reference mode")
        )
        if mode not in request.modes:
            raise ValueError("baseline root reference mode is outside the request")
        spin, _, spin_hex = _validate_spin_fields(
            reference, "baseline root reference"
        )
        if spin not in request.spins:
            raise ValueError("baseline root reference spin is outside the request")
        sampling_coordinate = SpinSamplingCoordinate.from_mapping(
            reference["sampling_coordinate"]
        )
        if sampling_coordinate != sampling_by_spin.get(spin_hex):
            raise ValueError("baseline root sampling coordinate is invalid")
        reference_id = _string(
            reference["root_reference_id"], "root_reference_id"
        )
        if reference_id != baseline_root_reference_id(mode, spin):
            raise ValueError("baseline root reference identity is invalid")
        if reference_id in seen:
            raise ValueError("baseline root reference IDs contain duplicates")
        seen.add(reference_id)
        coordinates.add((mode, spin_hex))
    if coordinates != expected_coordinates:
        raise ValueError("baseline root references do not cover the request")
    return frozenset(seen)


def _validate_covariance_blocks(
    value: object,
    components: Mapping[str, _ComponentSummary],
) -> dict[str, frozenset[str]]:
    blocks = _array(value, "covariance blocks")
    resolved = {
        component_id: component
        for component_id, component in components.items()
        if component.local_covariance is not None
    }
    covered_basis: set[tuple[str, str]] = set()
    validated: dict[str, frozenset[str]] = {}
    for raw in blocks:
        block = _object(raw, "covariance block")
        _exact_fields(
            block,
            frozenset(
                {
                    "covariance_id",
                    "basis",
                    "matrix",
                    "representation",
                    "kind",
                }
            ),
            "covariance block",
        )
        covariance_id = _string(block["covariance_id"], "covariance_id")
        if covariance_id in validated:
            raise ValueError("covariance IDs contain duplicates")
        if (
            block["representation"]
            != "real-block-covariance-in-declared-basis-units"
        ):
            raise ValueError("covariance block representation is invalid")
        if block["kind"] != "component-local-correlated-empirical":
            raise ValueError("covariance block kind is invalid")
        raw_basis = _array(block["basis"], "covariance block basis")
        if not raw_basis:
            raise ValueError("covariance block basis must not be empty")
        basis: list[tuple[str, str]] = []
        for raw_entry in raw_basis:
            entry = _object(raw_entry, "covariance basis entry")
            _exact_fields(
                entry,
                frozenset({"component_id", "quadrature", "units"}),
                "covariance basis entry",
            )
            component_id = _string(
                entry["component_id"], "covariance basis component_id"
            )
            quadrature = _string(
                entry["quadrature"], "covariance basis quadrature"
            )
            if quadrature not in {"real", "imaginary"}:
                raise ValueError("covariance basis quadrature is invalid")
            component = resolved.get(component_id)
            if component is None:
                raise ValueError(
                    "covariance basis references a non-resolved component"
                )
            if entry["units"] != component.units:
                raise ValueError("covariance basis units do not match component")
            key = (component_id, quadrature)
            if key in covered_basis or key in basis:
                raise ValueError("covariance basis entries contain duplicates")
            basis.append(key)
        matrix = _validate_real_symmetric_psd_matrix(
            block["matrix"], len(basis), "covariance block"
        )
        component_ids = frozenset(component_id for component_id, _ in basis)
        for component_id in component_ids:
            real_key = (component_id, "real")
            imaginary_key = (component_id, "imaginary")
            if real_key not in basis or imaginary_key not in basis:
                raise ValueError(
                    "covariance block must include both component quadratures"
                )
            real_index = basis.index(real_key)
            imaginary_index = basis.index(imaginary_key)
            local = resolved[component_id].local_covariance
            if local is None:
                raise AssertionError("resolved covariance unexpectedly missing")
            marginal = (
                (matrix[real_index][real_index], matrix[real_index][imaginary_index]),
                (
                    matrix[imaginary_index][real_index],
                    matrix[imaginary_index][imaginary_index],
                ),
            )
            if marginal != local:
                raise ValueError(
                    "covariance block marginal does not match local covariance"
                )
        covered_basis.update(basis)
        validated[covariance_id] = component_ids
    expected_basis = {
        (component_id, quadrature)
        for component_id in resolved
        for quadrature in ("real", "imaginary")
    }
    if covered_basis != expected_basis:
        raise ValueError("covariance blocks do not cover every resolved component")
    return validated


def _validate_completeness(
    value: object,
    expected_ids: frozenset[str],
    components: Mapping[str, _ComponentSummary],
) -> None:
    completeness = _object(value, "linear-response completeness")
    _exact_fields(
        completeness,
        frozenset(
            {
                "required_leaf_count",
                "produced_leaf_count",
                "unresolved_leaf_count",
                "missing_leaf_count",
                "required_leaf_ids",
                "produced_leaf_ids",
                "unresolved_leaf_ids",
                "missing_leaf_ids",
            }
        ),
        "linear-response completeness",
    )
    required = _unique_sorted_strings(
        completeness["required_leaf_ids"], "required_leaf_ids"
    )
    produced = _unique_sorted_strings(
        completeness["produced_leaf_ids"], "produced_leaf_ids"
    )
    unresolved = _unique_sorted_strings(
        completeness["unresolved_leaf_ids"], "unresolved_leaf_ids"
    )
    missing = _unique_sorted_strings(
        completeness["missing_leaf_ids"], "missing_leaf_ids"
    )
    if set(required) != set(expected_ids):
        raise ValueError("required leaf IDs do not match the request")
    if set(produced) != set(components):
        raise ValueError("produced leaf IDs do not match components")
    if set(missing) & set(unresolved):
        raise ValueError("leaf IDs cannot be both missing and unresolved")
    if set(produced) & set(missing) or set(produced) | set(missing) != set(required):
        raise ValueError("produced and missing leaf IDs must partition required leaves")
    expected_unresolved = {
        item.component_id
        for item in components.values()
        if item.numerical_state is NumericalState.UNRESOLVED
    }
    if set(unresolved) != expected_unresolved:
        raise ValueError("unresolved leaf IDs do not match component states")
    identities = (
        ("required_leaf_count", required),
        ("produced_leaf_count", produced),
        ("unresolved_leaf_count", unresolved),
        ("missing_leaf_count", missing),
    )
    for field, identifiers in identities:
        count = _integer(completeness[field], field)
        if count < 0 or count != len(identifiers):
            raise ValueError(f"{field} does not match its leaf IDs")


def _validate_projective_comparisons(
    value: object,
    components: Mapping[str, _ComponentSummary],
    covariance_blocks: Mapping[str, frozenset[str]],
) -> None:
    comparisons = _array(value, "projective comparisons")
    seen: set[str] = set()
    for raw in comparisons:
        comparison = _object(raw, "projective comparison")
        _exact_fields(
            comparison,
            frozenset(
                {
                    "comparison_id",
                    "mode_order",
                    "left_component_ids",
                    "right_component_ids",
                    "calibration_mode",
                    "calibration_numerator_component_id",
                    "calibration_denominator_component_id",
                    "covariance_id",
                    "nominal_angle_radians",
                    "bounded_angle_interval_radians",
                    "calibration_disk_contains_zero",
                    "projective_outcome",
                    "scientific_state",
                    "reason",
                }
            ),
            "projective comparison",
        )
        comparison_id = _string(comparison["comparison_id"], "comparison_id")
        if comparison_id in seen:
            raise ValueError("projective comparison IDs contain duplicates")
        seen.add(comparison_id)
        modes = tuple(
            ModeKey.from_mapping(_object(item, "projective mode"))
            for item in _array(comparison["mode_order"], "projective mode_order")
        )
        if len(modes) < 2 or len(modes) != len(set(modes)):
            raise ValueError(
                "projective comparison requires an ordered multimode support"
            )
        left_ids = tuple(
            _string(item, "left component ID")
            for item in _array(
                comparison["left_component_ids"], "left_component_ids"
            )
        )
        right_ids = tuple(
            _string(item, "right component ID")
            for item in _array(
                comparison["right_component_ids"], "right_component_ids"
            )
        )
        if (
            len(left_ids) != len(modes)
            or len(right_ids) != len(modes)
            or len(set(left_ids)) != len(left_ids)
            or len(set(right_ids)) != len(right_ids)
        ):
            raise ValueError(
                "projective comparison vectors must match the multimode support"
            )
        if set(left_ids) & set(right_ids):
            raise ValueError("projective comparison vectors must be distinct")
        if any(
            component_id not in components
            for component_id in (*left_ids, *right_ids)
        ):
            raise ValueError("projective comparison references an unknown component")
        left = tuple(components[item] for item in left_ids)
        right = tuple(components[item] for item in right_ids)
        if tuple(item.mode for item in left) != modes or tuple(
            item.mode for item in right
        ) != modes:
            raise ValueError("projective vectors do not share the declared mode order")
        spins = {item.spin_binary64_hex for item in (*left, *right)}
        if len(spins) != 1:
            raise ValueError("projective comparison components must share a spin")
        if len({item.selection for item in left}) != 1 or len(
            {item.selection for item in right}
        ) != 1:
            raise ValueError("each projective vector must use one mechanism")
        if left[0].selection == right[0].selection:
            raise ValueError("projective vectors must use distinct mechanisms")

        calibration_mode = ModeKey.from_mapping(
            _object(comparison["calibration_mode"], "calibration_mode")
        )
        if calibration_mode not in modes:
            raise ValueError("calibration mode is outside the projective support")
        calibration_index = modes.index(calibration_mode)
        numerator_id = _string(
            comparison["calibration_numerator_component_id"],
            "calibration_numerator_component_id",
        )
        denominator_id = _string(
            comparison["calibration_denominator_component_id"],
            "calibration_denominator_component_id",
        )
        if (
            numerator_id != left_ids[calibration_index]
            or denominator_id != right_ids[calibration_index]
        ):
            raise ValueError("projective calibration pair is inconsistent")
        denominator = components[denominator_id]
        covariance_id = _string(comparison["covariance_id"], "covariance_id")
        covered = covariance_blocks.get(covariance_id)
        if covered is None:
            raise ValueError("projective covariance reference is unknown")
        resolved_vector_ids = {
            item.component_id
            for item in (*left, *right)
            if item.centre is not None
        }
        if not resolved_vector_ids.issubset(covered):
            raise ValueError(
                "projective covariance block does not cover the vector"
            )
        contains_zero = _boolean(
            comparison["calibration_disk_contains_zero"],
            "calibration_disk_contains_zero",
        )
        computed_contains_zero = (
            denominator.centre is None
            or denominator.disk_radius is None
            or math.hypot(*denominator.centre) <= denominator.disk_radius
        )
        if contains_zero != computed_contains_zero:
            raise ValueError("calibration_disk_contains_zero is inconsistent")
        outcome = _string(
            comparison["projective_outcome"], "projective_outcome"
        )
        if outcome not in {
            "SEPARATED",
            "EQUIVALENT_WITHIN_TOLERANCE",
            "UNRESOLVED",
        }:
            raise ValueError("projective outcome is invalid")
        try:
            scientific_state = ScientificState(comparison["scientific_state"])
        except (TypeError, ValueError) as error:
            raise ValueError("projective scientific state is invalid") from error
        if scientific_state not in _PROJECTIVE_STATES:
            raise ValueError("projective scientific state is invalid")
        _string(comparison["reason"], "projective comparison reason")
        is_unbounded = (
            contains_zero
            or any(item.centre is None for item in (*left, *right))
        )
        if is_unbounded:
            if (
                outcome != "UNRESOLVED"
                or scientific_state is not ScientificState.UNRESOLVED
            ):
                raise ValueError(
                    "unbounded projective comparison must be UNRESOLVED"
                )
            if (
                comparison["nominal_angle_radians"] is not None
                or comparison["bounded_angle_interval_radians"] is not None
            ):
                raise ValueError(
                    "unbounded projective comparison cannot report bounded angles"
                )
            continue
        nominal = _number(
            comparison["nominal_angle_radians"],
            "nominal_angle_radians",
            minimum=0.0,
        )
        interval = _array(
            comparison["bounded_angle_interval_radians"],
            "bounded_angle_interval_radians",
        )
        if len(interval) != 2:
            raise ValueError("bounded angle interval must have two endpoints")
        lower = _number(interval[0], "bounded angle lower", minimum=0.0)
        upper = _number(interval[1], "bounded angle upper", minimum=0.0)
        if upper > math.pi / 2.0 or not lower <= nominal <= upper:
            raise ValueError("bounded angle interval is invalid")


def _validate_lineage(
    value: object,
    provider: Mapping[str, object],
) -> None:
    lineage = _object(value, "linear-response lineage")
    _exact_fields(
        lineage,
        frozenset(
            {
                "source_commit",
                "source_sha256s",
                "runtime_fingerprint",
                "numerical_policy_fingerprint",
                "evidence_ceiling",
            }
        ),
        "linear-response lineage",
    )
    _hex(lineage["source_commit"], "source_commit", _HEX_40)
    hashes = _array(lineage["source_sha256s"], "source_sha256s")
    if not hashes:
        raise ValueError("source_sha256s must not be empty")
    validated_hashes = [
        _hex(item, "source SHA-256", _HEX_64) for item in hashes
    ]
    if len(validated_hashes) != len(set(validated_hashes)):
        raise ValueError("source_sha256s contains duplicates")
    if lineage["runtime_fingerprint"] != provider.get("runtime_fingerprint"):
        raise ValueError("lineage runtime fingerprint does not match provider")
    if (
        lineage["numerical_policy_fingerprint"]
        != provider.get("numerical_policy_fingerprint")
    ):
        raise ValueError(
            "lineage numerical policy fingerprint does not match provider"
        )
    if lineage["evidence_ceiling"] != LINEAR_RESPONSE_EVIDENCE_CEILING:
        raise ValueError("linear-response evidence ceiling is invalid")


def validate_linear_response_payload(
    request: StudyRequest,
    provider: Mapping[str, object],
    payload: Mapping[str, object],
) -> None:
    """Validate candidate M02 payload semantics without admitting a provider."""

    selections = validate_linear_response_request(request)
    try:
        actual_provider = canonical_json_bytes(dict(provider))
        expected_provider = canonical_json_bytes(
            LINEAR_RESPONSE_DESCRIPTOR.to_mapping()
        )
    except (RecursionError, TypeError, ValueError) as error:
        raise ValueError("linear-response provider contract is invalid") from error
    if actual_provider != expected_provider:
        raise ValueError("linear-response provider contract is invalid")
    policy = _object(
        request.numerical_policy.get("linear-response"),
        "linear-response numerical policy",
    )
    sampling_coordinates = _sampling_coordinates_for_request(request, policy)
    sampling_by_spin = {
        item.spin_binary64_hex: item for item in sampling_coordinates
    }
    role_scoped_leaves = _role_scoped_leaves_for_request(
        request, policy, selections, sampling_coordinates
    )

    mapping = _object(payload, "linear-response payload")
    _exact_fields(
        mapping,
        frozenset(
            {
                "schema_version",
                "quantity",
                "equations_id",
                "baseline_theory_id",
                "baseline_convention_id",
                "time_dependence",
                "frequency_units",
                "spin_coordinate",
                "horizon_contact_coordinate",
                "lineage",
                "baseline_root_references",
                "response_components",
                "covariance_blocks",
                "projective_comparisons",
                "completeness",
            }
        ),
        "linear-response payload",
    )
    if _integer(mapping["schema_version"], "schema_version") != 1:
        raise ValueError("linear-response schema_version must be 1")
    identities = {
        "quantity": LINEAR_RESPONSE_QUANTITY,
        "equations_id": LINEAR_RESPONSE_EQUATIONS_ID,
        "baseline_theory_id": request.theory_id,
        "baseline_convention_id": request.convention_id,
        "time_dependence": "exp(-i omega t + i m phi)",
        "frequency_units": "Momega",
        "spin_coordinate": "a_over_M",
        "horizon_contact_coordinate": "delta-B",
    }
    for field, expected in identities.items():
        if mapping[field] != expected:
            raise ValueError(f"linear-response {field} is invalid")
    _validate_lineage(mapping["lineage"], provider)
    active_leaves = (
        role_scoped_leaves
        if role_scoped_leaves is not None
        else tuple(
            RoleScopedLeaf("unscoped", mode, sampling_by_spin[spin.hex()], selection)
            for mode in request.modes
            for spin in request.spins
            for selection in selections
        )
    )
    expected_ids = frozenset(
        linear_response_leaf_id(
            leaf.mode, leaf.sampling_coordinate.spin, leaf.selection
        )
        for leaf in active_leaves
    )
    root_reference_ids = _validate_root_references(
        mapping["baseline_root_references"], request, sampling_by_spin,
        {(leaf.mode, leaf.sampling_coordinate.spin_binary64_hex) for leaf in active_leaves},
    )
    sentinel_inputs = {
        ((2, 2, 0), "horizon-admittance"),
        ((2, 2, 2), "exterior-throat-kappa"),
    }
    precision_requirements = {
        linear_response_leaf_id(leaf.mode, leaf.sampling_coordinate.spin, leaf.selection): (
            ((leaf.mode.ell, leaf.mode.m, leaf.mode.n), leaf.selection.mechanism_id)
            in sentinel_inputs,
            True,
        )
        for leaf in active_leaves
        if leaf.role == "deep"
    }
    summaries: dict[str, _ComponentSummary] = {}
    for component in _array(
        mapping["response_components"], "linear-response components"
    ):
        summary = _validate_component(
            component,
            request,
            selections,
            sampling_by_spin,
            expected_ids,
            root_reference_ids,
            precision_requirements,
        )
        if summary.component_id in summaries:
            raise ValueError("linear-response component IDs contain duplicates")
        summaries[summary.component_id] = summary
    covariance_blocks = _validate_covariance_blocks(
        mapping["covariance_blocks"], summaries
    )
    _validate_projective_comparisons(
        mapping["projective_comparisons"], summaries, covariance_blocks
    )
    _validate_completeness(mapping["completeness"], expected_ids, summaries)


def validate_linear_response_admission(
    request: StudyRequest,
    provider: Mapping[str, object],
    payload: Mapping[str, object],
) -> None:
    """Apply the stricter production-admission gate to a valid candidate."""

    validate_linear_response_payload(request, provider, payload)
    completeness = _object(payload["completeness"], "linear-response completeness")
    if completeness["missing_leaf_ids"]:
        raise ValueError("linear-response admission cannot contain missing leaves")
    components = _array(payload["response_components"], "response_components")
    for component in components:
        mapping = _object(component, "linear-response component")
        if mapping["numerical_state"] not in {
            NumericalState.ACCEPTED.value,
            NumericalState.UNRESOLVED.value,
        }:
            raise ValueError(
                "every admitted linear-response component must be ACCEPTED or UNRESOLVED"
            )
    selections = validate_linear_response_request(request)
    policy = _object(
        request.numerical_policy.get("linear-response"),
        "linear-response numerical policy",
    )
    sampling_coordinates = _sampling_coordinates_for_request(request, policy)
    role_scoped_leaves = _role_scoped_leaves_for_request(
        request, policy, selections, sampling_coordinates
    )
    if role_scoped_leaves is None:
        raise ValueError("B′ admission requires explicit role-scoped leaves")
    expected_b_prime_inputs = {
        (leaf.role, leaf.mode, leaf.spin.hex(), leaf.mechanism_id)
        for leaf in B_PRIME_RELEASE_DOMAIN.production_leaves
    }
    requested_b_prime_inputs = {
        (
            leaf.role, (leaf.mode.ell, leaf.mode.m, leaf.mode.n),
            leaf.sampling_coordinate.spin.hex(), leaf.selection.mechanism_id,
        )
        for leaf in role_scoped_leaves
    }
    if (
        completeness["required_leaf_count"] != len(expected_b_prime_inputs)
        or completeness["produced_leaf_count"] != len(expected_b_prime_inputs)
        or requested_b_prime_inputs != expected_b_prime_inputs
    ):
        raise ValueError("B′ required leaf count and role-scoped leaf set are exact")
