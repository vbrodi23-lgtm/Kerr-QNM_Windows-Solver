"""Operator-approved empirical controls for promoted determinant work.

The v1 receipt deliberately does not claim a calibrated determinant-to-ODE
conversion or an archived derivative floor.  It authenticates the controls
that may be used to produce test-only evidence and requires each usable result
to carry current-run determinant and derivative error evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
from importlib.resources import files
import json
import math
from pathlib import Path
import re
from types import MappingProxyType
from typing import Mapping

from .contracts import canonical_json_bytes
from .precision_tiers import PrecisionTier


PROMOTED_CONTROL_EMPIRICAL_CALIBRATION_IDENTITY = (
    "promoted-control-empirical-calibration/v1"
)
EXTERIOR_DETERMINANT_ABSOLUTE_ERROR_CERTIFICATE = (
    "exterior-determinant-absolute-error-certificate/empirical-v1"
)
ARCHIVED_AUTHENTICATED_LOWER_BOUND_UNAVAILABLE = (
    "ARCHIVED_AUTHENTICATED_LOWER_BOUND_UNAVAILABLE"
)
EMPIRICAL_TEST_ONLY_NO_ARCHIVED_FLOOR = (
    "EMPIRICAL_TEST_ONLY_NO_ARCHIVED_FLOOR"
)
DERIVATIVE_AUTHENTICATION_UNAVAILABLE = (
    "DERIVATIVE_AUTHENTICATION_UNAVAILABLE"
)
EXTERIOR_DETERMINANT_CERTIFICATE_UNAVAILABLE = (
    "EXTERIOR_DETERMINANT_CERTIFICATE_UNAVAILABLE"
)

CALIBRATION_RECEIPT_SCHEMA = (
    "windows-solver.promoted-control-empirical-calibration-receipt/1"
)
SOURCE_AUDIT_SCHEMA = (
    "kerr-qnm.promoted-control-derivative-lower-bound-source-audit/1"
)
SOURCE_AUDIT_SHA256 = (
    "a31a266c8488a7b19510a8d3fea4497cddcb2108eb9e424e27c396fa26ad6ae0"
)
DEFAULT_CALIBRATION_RECEIPT_RESOURCE = (
    "data/promoted_control_empirical_calibration_v1.json"
)
SOURCE_AUDIT_RESOURCE = (
    "data/promoted_control_derivative_lower_bound_source_audit_v1.json"
)
# Replaced only when the canonical committed receipt changes.  It is not read
# from a sidecar that could be changed together with the receipt.
DEFAULT_CALIBRATION_RECEIPT_SHA256 = (
    "d39b7f648a7f3de3a3dcfa20de3217c8b4cd78aa7a1deb17b5483a99120bcd58"
)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_FAMILY_TIER_PAIRS = frozenset({
    ("exterior-wronskian/v1", PrecisionTier.BIGFLOAT_40),
    ("exterior-wronskian/v1", PrecisionTier.BIGFLOAT_80),
    ("exterior-wronskian/v1", PrecisionTier.BIGFLOAT_120),
    ("horizon-scattering/v1", PrecisionTier.BIGFLOAT_80),
    ("horizon-scattering/v1", PrecisionTier.BIGFLOAT_120),
})
_DIGITS_TO_TIER = {
    40: PrecisionTier.BIGFLOAT_40,
    80: PrecisionTier.BIGFLOAT_80,
    120: PrecisionTier.BIGFLOAT_120,
}
_CONTROL_FIELDS = frozenset({
    "coordinate_ode_absolute_tolerance",
    "coordinate_ode_relative_tolerance",
    "frequency_step",
    "frequency_step_maximum",
    "frequency_step_minimum",
    "homogeneous_ode_absolute_tolerance",
    "homogeneous_ode_relative_tolerance",
    "ode_absolute_tolerance",
    "ode_relative_tolerance",
    "root_correction_tolerance",
})
_ODE_CONTROL_FIELDS = frozenset({
    "coordinate_ode_absolute_tolerance",
    "coordinate_ode_relative_tolerance",
    "homogeneous_ode_absolute_tolerance",
    "homogeneous_ode_relative_tolerance",
    "ode_absolute_tolerance",
    "ode_relative_tolerance",
})


class CalibrationReceiptError(ValueError):
    """The calibration receipt is not the exact supported canonical contract."""


class DerivativeAuthenticationUnavailable(ValueError):
    """A current-run derivative lower bound or empirical disk is unavailable."""

    code = DERIVATIVE_AUTHENTICATION_UNAVAILABLE


def _exact_fields(
    value: object, expected: frozenset[str], subject: str
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise CalibrationReceiptError(f"{subject} fields are invalid")
    return value


def _positive_decimal_text(value: object, subject: str) -> str:
    if not isinstance(value, str):
        raise CalibrationReceiptError(f"{subject} must be decimal text")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise CalibrationReceiptError(f"{subject} is invalid") from error
    if not parsed.is_finite() or parsed <= 0:
        raise CalibrationReceiptError(f"{subject} must be finite and positive")
    return value


def _validated_controls(value: object, subject: str) -> Mapping[str, str]:
    mapping = _exact_fields(value, _CONTROL_FIELDS, subject)
    controls = {
        field: _positive_decimal_text(mapping[field], f"{subject} {field}")
        for field in sorted(_CONTROL_FIELDS)
    }
    if (
        Decimal(controls["frequency_step_minimum"])
        > Decimal(controls["frequency_step"])
        or Decimal(controls["frequency_step"])
        > Decimal(controls["frequency_step_maximum"])
    ):
        raise CalibrationReceiptError(f"{subject} frequency step bounds are invalid")
    return MappingProxyType(controls)


@dataclass(frozen=True, slots=True)
class EmpiricalControlProfile:
    determinant_family: str
    precision_tier: PrecisionTier
    nominal_decimal_digits: int
    base_controls: Mapping[str, str]
    refinement_controls: Mapping[str, str]

    @property
    def base_ode_controls(self) -> Mapping[str, str]:
        return MappingProxyType({
            field: self.base_controls[field]
            for field in sorted(_ODE_CONTROL_FIELDS)
        })

    @property
    def refinement_ode_controls(self) -> Mapping[str, str]:
        return MappingProxyType({
            field: self.refinement_controls[field]
            for field in sorted(_ODE_CONTROL_FIELDS)
        })

    def controls_for_refinement(self, refinement: int) -> dict[str, str]:
        if refinement not in (0, 1):
            raise ValueError("empirical control refinement must be zero or one")
        source = self.base_controls if refinement == 0 else self.refinement_controls
        return dict(source)

    def to_mapping(self) -> dict[str, object]:
        return {
            "base_controls": dict(self.base_controls),
            "determinant_family": self.determinant_family,
            "nominal_decimal_digits": self.nominal_decimal_digits,
            "precision_tier": self.precision_tier.value,
            "refinement_controls": dict(self.refinement_controls),
        }


@dataclass(frozen=True, slots=True)
class PromotedControlCalibrationReceipt:
    identity: str
    execution_status: str
    empirical: bool
    operator_approved: bool
    interval_arithmetic: bool
    independent_mathematical_proof: bool
    source_audit_sha256: str
    certificate_identity: str
    certificate_safety_factor: int
    profiles: tuple[EmpiricalControlProfile, ...]
    derivative_floor_records: Mapping[str, Mapping[str, object]]
    sha256: str
    _canonical_bytes: bytes

    @property
    def covered_pairs(self) -> frozenset[tuple[str, int]]:
        return frozenset(
            (profile.determinant_family, profile.nominal_decimal_digits)
            for profile in self.profiles
        )

    def budget_for(
        self, determinant_family: str, nominal_decimal_digits: int
    ) -> EmpiricalControlProfile:
        tier = _DIGITS_TO_TIER.get(nominal_decimal_digits)
        for profile in self.profiles:
            if (
                profile.determinant_family == determinant_family
                and profile.precision_tier is tier
            ):
                return profile
        raise CalibrationReceiptError(
            "calibration receipt does not cover determinant family and tier"
        )

    def derivative_floor_for(self, determinant_family: str) -> None:
        self.derivative_floor_status_for(determinant_family)
        return None

    def derivative_floor_status_for(self, determinant_family: str) -> str:
        record = self.derivative_floor_records.get(determinant_family)
        if record is None:
            raise CalibrationReceiptError(
                "calibration receipt does not cover determinant family floor"
            )
        return str(record["status"])

    def to_mapping(self) -> dict[str, object]:
        return json.loads(self._canonical_bytes)


def authenticated_derivative_lower_bound_abs(
    *,
    derivative_abs: float,
    step_disagreement_abs: float,
    propagated_error_abs: float,
) -> float:
    """Construct the one admitted current-run derivative lower bound."""

    values = (
        float(derivative_abs),
        float(step_disagreement_abs),
        float(propagated_error_abs),
    )
    if (
        any(not math.isfinite(value) for value in values)
        or values[0] <= 0.0
        or values[1] < 0.0
        or values[2] < 0.0
    ):
        raise DerivativeAuthenticationUnavailable(
            "current derivative evidence is not finite and admissible"
        )
    lower_bound = values[0] - values[1] - values[2]
    if not math.isfinite(lower_bound) or lower_bound <= 0.0:
        raise DerivativeAuthenticationUnavailable(
            "current derivative lower bound is not positive"
        )
    return lower_bound


def empirical_root_error_radius_abs(
    *, determinant_error_abs: float, derivative_lower_bound_abs: float
) -> float:
    """Return the empirical determinant-to-frequency disk for current evidence."""

    error = float(determinant_error_abs)
    lower_bound = float(derivative_lower_bound_abs)
    if (
        not math.isfinite(error)
        or error < 0.0
        or not math.isfinite(lower_bound)
        or lower_bound <= 0.0
    ):
        raise DerivativeAuthenticationUnavailable(
            "empirical root disk inputs are unavailable"
        )
    radius = error / lower_bound
    if not math.isfinite(radius):
        raise DerivativeAuthenticationUnavailable(
            "empirical root disk is not finite"
        )
    return radius


def _parse_receipt(mapping: Mapping[str, object], digest: str) -> PromotedControlCalibrationReceipt:
    top = _exact_fields(mapping, frozenset({
        "admission_boundary",
        "budget_entries",
        "derivative_floor_records",
        "determinant_certificate",
        "execution_status",
        "identity",
        "labels",
        "operator_approval",
        "schema",
        "source_audit",
    }), "calibration receipt")
    if top["schema"] != CALIBRATION_RECEIPT_SCHEMA:
        raise CalibrationReceiptError("calibration receipt schema is unsupported")
    if top["identity"] != PROMOTED_CONTROL_EMPIRICAL_CALIBRATION_IDENTITY:
        raise CalibrationReceiptError("calibration receipt identity is unsupported")
    if top["execution_status"] != EMPIRICAL_TEST_ONLY_NO_ARCHIVED_FLOOR:
        raise CalibrationReceiptError("calibration receipt execution status is invalid")

    labels = _exact_fields(top["labels"], frozenset({
        "derived_from_existing_authenticated_production_evidence",
        "empirical",
        "independent_mathematical_proof",
        "interval_arithmetic",
        "operator_approved",
    }), "calibration receipt labels")
    if labels != {
        "derived_from_existing_authenticated_production_evidence": True,
        "empirical": True,
        "independent_mathematical_proof": False,
        "interval_arithmetic": False,
        "operator_approved": True,
    }:
        raise CalibrationReceiptError("calibration receipt labels are invalid")

    approval = _exact_fields(top["operator_approval"], frozenset({
        "approved_at_utc", "authority", "status"
    }), "calibration receipt operator approval")
    if approval["status"] != "operator-approved/v1":
        raise CalibrationReceiptError("calibration receipt operator approval is invalid")
    if not all(isinstance(approval[field], str) and approval[field] for field in approval):
        raise CalibrationReceiptError("calibration receipt operator approval is invalid")

    audit = _exact_fields(top["source_audit"], frozenset({
        "result", "schema", "sha256"
    }), "calibration receipt source audit")
    if (
        audit["schema"] != SOURCE_AUDIT_SCHEMA
        or not isinstance(audit["sha256"], str)
        or _SHA256.fullmatch(audit["sha256"]) is None
        or audit["result"] != ARCHIVED_AUTHENTICATED_LOWER_BOUND_UNAVAILABLE
    ):
        raise CalibrationReceiptError("calibration receipt source audit is invalid")

    certificate = _exact_fields(top["determinant_certificate"], frozenset({
        "endpoint_series_rule",
        "identity",
        "missing_evidence_outcome",
        "required_term_classes",
        "safety_factor",
        "statement",
        "tight_control_rule",
    }), "calibration receipt determinant certificate")
    if (
        certificate["identity"]
        != EXTERIOR_DETERMINANT_ABSOLUTE_ERROR_CERTIFICATE
        or certificate["safety_factor"] != 64
        or certificate["missing_evidence_outcome"]
        != EXTERIOR_DETERMINANT_CERTIFICATE_UNAVAILABLE
        or certificate["required_term_classes"] != [
            "delta_same_point", "delta_cross_precision", "delta_endpoint_series"
        ]
        or not all(
            isinstance(certificate[field], str) and certificate[field]
            for field in (
                "endpoint_series_rule", "statement", "tight_control_rule"
            )
        )
    ):
        raise CalibrationReceiptError("calibration receipt certificate is invalid")

    raw_floors = top["derivative_floor_records"]
    if not isinstance(raw_floors, list) or len(raw_floors) != 2:
        raise CalibrationReceiptError("calibration receipt derivative floors are invalid")
    floor_records: dict[str, Mapping[str, object]] = {}
    for raw_floor in raw_floors:
        floor = _exact_fields(raw_floor, frozenset({
            "archived_minimum_derivative_lower_bound_abs",
            "determinant_family",
            "qualifying_source_receipt_shas",
            "receipt_derivative_floor_abs",
            "status",
        }), "calibration receipt derivative floor")
        family = floor["determinant_family"]
        if (
            family not in {"exterior-wronskian/v1", "horizon-scattering/v1"}
            or family in floor_records
            or floor["status"]
            != ARCHIVED_AUTHENTICATED_LOWER_BOUND_UNAVAILABLE
            or floor["archived_minimum_derivative_lower_bound_abs"] is not None
            or floor["receipt_derivative_floor_abs"] is not None
            or floor["qualifying_source_receipt_shas"] != []
        ):
            raise CalibrationReceiptError("calibration receipt derivative floor is invalid")
        floor_records[str(family)] = MappingProxyType(dict(floor))
    if set(floor_records) != {"exterior-wronskian/v1", "horizon-scattering/v1"}:
        raise CalibrationReceiptError("calibration receipt derivative families are invalid")

    raw_entries = top["budget_entries"]
    if not isinstance(raw_entries, list) or len(raw_entries) != 5:
        raise CalibrationReceiptError("calibration receipt budget entries are invalid")
    profiles: list[EmpiricalControlProfile] = []
    observed_pairs: set[tuple[str, PrecisionTier]] = set()
    for raw_entry in raw_entries:
        entry = _exact_fields(raw_entry, frozenset({
            "base_controls",
            "determinant_family",
            "nominal_decimal_digits",
            "precision_tier",
            "refinement_controls",
        }), "calibration receipt budget entry")
        try:
            tier = PrecisionTier(entry["precision_tier"])
        except (TypeError, ValueError) as error:
            raise CalibrationReceiptError(
                "calibration receipt precision tier is invalid"
            ) from error
        digits = entry["nominal_decimal_digits"]
        pair = (entry["determinant_family"], tier)
        if (
            isinstance(digits, bool)
            or not isinstance(digits, int)
            or _DIGITS_TO_TIER.get(digits) is not tier
            or pair not in _FAMILY_TIER_PAIRS
            or pair in observed_pairs
        ):
            raise CalibrationReceiptError("calibration receipt family/tier is invalid")
        observed_pairs.add(pair)
        profiles.append(EmpiricalControlProfile(
            determinant_family=str(entry["determinant_family"]),
            precision_tier=tier,
            nominal_decimal_digits=digits,
            base_controls=_validated_controls(
                entry["base_controls"], "base empirical controls"
            ),
            refinement_controls=_validated_controls(
                entry["refinement_controls"], "refinement empirical controls"
            ),
        ))
    if observed_pairs != set(_FAMILY_TIER_PAIRS):
        raise CalibrationReceiptError("calibration receipt coverage is incomplete")

    admission = _exact_fields(top["admission_boundary"], frozenset({
        "calculation",
        "checkpointing",
        "publication",
        "scientific_admission",
        "uncertainty_disks",
    }), "calibration receipt admission boundary")
    expected_admission = {
        "calculation": "permitted/v1",
        "checkpointing": "permitted/v1",
        "publication": "blocked-pending-independent-review/v1",
        "scientific_admission": "blocked-pending-independent-review/v1",
        "uncertainty_disks": "empirical-current-run-only/v1",
    }
    if admission != expected_admission:
        raise CalibrationReceiptError("calibration receipt admission boundary is invalid")

    return PromotedControlCalibrationReceipt(
        identity=str(top["identity"]),
        execution_status=str(top["execution_status"]),
        empirical=True,
        operator_approved=True,
        interval_arithmetic=False,
        independent_mathematical_proof=False,
        source_audit_sha256=str(audit["sha256"]),
        certificate_identity=str(certificate["identity"]),
        certificate_safety_factor=64,
        profiles=tuple(profiles),
        derivative_floor_records=MappingProxyType(floor_records),
        sha256=digest,
        _canonical_bytes=canonical_json_bytes(mapping),
    )


def _load_receipt_bytes(raw: bytes, expected_sha256: str) -> PromotedControlCalibrationReceipt:
    if not isinstance(expected_sha256, str) or _SHA256.fullmatch(expected_sha256) is None:
        raise CalibrationReceiptError("calibration receipt digest is invalid")
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected_sha256:
        raise CalibrationReceiptError("calibration receipt digest does not match")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CalibrationReceiptError("calibration receipt is not valid JSON") from error
    if not isinstance(value, dict):
        raise CalibrationReceiptError("calibration receipt must be a JSON object")
    if canonical_json_bytes(value) != raw:
        raise CalibrationReceiptError("calibration receipt bytes are not canonical")
    return _parse_receipt(value, digest)


def load_calibration_receipt(
    path: Path | str, expected_sha256: str
) -> PromotedControlCalibrationReceipt:
    """Load an explicitly SHA-pinned canonical receipt override."""

    return _load_receipt_bytes(Path(path).read_bytes(), expected_sha256)


def load_default_calibration_receipt() -> PromotedControlCalibrationReceipt:
    """Load the module-pinned committed canonical v1 receipt."""

    package = files("windows_solver")
    try:
        raw = package.joinpath(
            DEFAULT_CALIBRATION_RECEIPT_RESOURCE
        ).read_bytes()
        audit_raw = package.joinpath(SOURCE_AUDIT_RESOURCE).read_bytes()
    except OSError as error:
        raise CalibrationReceiptError(
            "committed calibration receipt resources are unavailable"
        ) from error
    receipt = _load_receipt_bytes(raw, DEFAULT_CALIBRATION_RECEIPT_SHA256)
    audit_sha256 = hashlib.sha256(audit_raw).hexdigest()
    if (
        audit_sha256 != SOURCE_AUDIT_SHA256
        or audit_sha256 != receipt.source_audit_sha256
    ):
        raise CalibrationReceiptError(
            "committed source audit digest does not match"
        )
    return receipt
