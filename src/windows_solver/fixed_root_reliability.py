"""Committed authority for fixed-root reliability projections."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
from importlib.resources import files
import json
from typing import Mapping

from .contracts import canonical_json_bytes
from .promoted_control_calibration import (
    CALIBRATION_RECEIPT_SCHEMA,
    PROMOTED_CONTROL_EMPIRICAL_CALIBRATION_IDENTITY,
)


FIXED_ROOT_RELIABILITY_PROJECTION_AUTHORITY_SCHEMA = (
    "windows-solver.fixed-root-reliability-projection-authority/1"
)
FIXED_ROOT_RELIABILITY_PROJECTION_AUTHORITY_IDENTITY = (
    "fixed-root-reliability-projection-authority/v1"
)
FIXED_ROOT_RELIABILITY_PROJECTION_AUTHORITY_RESOURCE = (
    "data/fixed_root_reliability_projection_authority_v1.json"
)
FIXED_ROOT_POLICY_CONTROL_FIELDS = (
    "coordinate_ode_absolute_tolerance",
    "coordinate_ode_relative_tolerance",
    "homogeneous_ode_absolute_tolerance",
    "homogeneous_ode_relative_tolerance",
    "ode_absolute_tolerance",
    "ode_relative_tolerance",
)
FIXED_ROOT_RELIABILITY_TARGET_CONTROL_FIELD = "root_correction_tolerance"
_AUTHORITY_FIELDS = frozenset({
    "schema",
    "identity",
    "calibration_receipt_schema",
    "calibration_receipt_identity",
    "fixed_root_policy_control_fields",
    "fixed_root_reliability_rule",
    "fixed_root_reliability_target_control_field",
    "required_digit_guard",
    "authority_sha256",
})


class FixedRootReliabilityAuthorityError(ValueError):
    """The committed reliability-projection authority is invalid."""


@dataclass(frozen=True, slots=True)
class FixedRootReliabilityProjectionAuthority:
    schema: str
    identity: str
    calibration_receipt_schema: str
    calibration_receipt_identity: str
    fixed_root_policy_control_fields: tuple[str, ...]
    fixed_root_reliability_rule: str
    fixed_root_reliability_target_control_field: str
    required_digit_guard: int
    authority_sha256: str

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "identity": self.identity,
            "calibration_receipt_schema": self.calibration_receipt_schema,
            "calibration_receipt_identity": self.calibration_receipt_identity,
            "fixed_root_policy_control_fields": list(
                self.fixed_root_policy_control_fields
            ),
            "fixed_root_reliability_rule": self.fixed_root_reliability_rule,
            "fixed_root_reliability_target_control_field": (
                self.fixed_root_reliability_target_control_field
            ),
            "required_digit_guard": self.required_digit_guard,
            "authority_sha256": self.authority_sha256,
        }


def _parse_fixed_root_reliability_projection_authority(
    raw: bytes,
) -> FixedRootReliabilityProjectionAuthority:
    try:
        mapping = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FixedRootReliabilityAuthorityError(
            "fixed-root reliability authority is not valid JSON"
        ) from error
    if not isinstance(mapping, Mapping) or set(mapping) != _AUTHORITY_FIELDS:
        raise FixedRootReliabilityAuthorityError(
            "fixed-root reliability authority fields are invalid"
        )
    if raw != canonical_json_bytes(mapping) + b"\n":
        raise FixedRootReliabilityAuthorityError(
            "fixed-root reliability authority is not canonical JSON"
        )
    if mapping["schema"] != FIXED_ROOT_RELIABILITY_PROJECTION_AUTHORITY_SCHEMA:
        raise FixedRootReliabilityAuthorityError(
            "fixed-root reliability authority schema is invalid"
        )
    if mapping["identity"] != FIXED_ROOT_RELIABILITY_PROJECTION_AUTHORITY_IDENTITY:
        raise FixedRootReliabilityAuthorityError(
            "fixed-root reliability authority identity is invalid"
        )
    if mapping["calibration_receipt_schema"] != CALIBRATION_RECEIPT_SCHEMA:
        raise FixedRootReliabilityAuthorityError(
            "fixed-root reliability authority calibration schema is invalid"
        )
    if (
        mapping["calibration_receipt_identity"]
        != PROMOTED_CONTROL_EMPIRICAL_CALIBRATION_IDENTITY
    ):
        raise FixedRootReliabilityAuthorityError(
            "fixed-root reliability authority calibration identity is invalid"
        )
    for field in (
        "identity",
        "calibration_receipt_schema",
        "calibration_receipt_identity",
        "fixed_root_reliability_rule",
    ):
        if not isinstance(mapping[field], str) or not mapping[field]:
            raise FixedRootReliabilityAuthorityError(
                f"fixed-root reliability authority {field} is invalid"
            )
    policy_control_fields = mapping["fixed_root_policy_control_fields"]
    if (
        not isinstance(policy_control_fields, list)
        or tuple(policy_control_fields) != FIXED_ROOT_POLICY_CONTROL_FIELDS
    ):
        raise FixedRootReliabilityAuthorityError(
            "fixed-root reliability authority policy controls are invalid"
        )
    target_control_field = mapping[
        "fixed_root_reliability_target_control_field"
    ]
    if target_control_field != FIXED_ROOT_RELIABILITY_TARGET_CONTROL_FIELD:
        raise FixedRootReliabilityAuthorityError(
            "fixed-root reliability authority target control is invalid"
        )
    guard = mapping["required_digit_guard"]
    if type(guard) is not int or guard <= 0:
        raise FixedRootReliabilityAuthorityError(
            "fixed-root reliability authority digit guard is invalid"
        )
    observed_sha256 = mapping["authority_sha256"]
    if (
        not isinstance(observed_sha256, str)
        or len(observed_sha256) != 64
        or any(character not in "0123456789abcdef" for character in observed_sha256)
    ):
        raise FixedRootReliabilityAuthorityError(
            "fixed-root reliability authority digest is invalid"
        )
    binding = {
        key: value for key, value in mapping.items() if key != "authority_sha256"
    }
    expected_sha256 = hashlib.sha256(canonical_json_bytes(binding)).hexdigest()
    if observed_sha256 != expected_sha256:
        raise FixedRootReliabilityAuthorityError(
            "fixed-root reliability authority digest does not match"
        )
    return FixedRootReliabilityProjectionAuthority(
        schema=mapping["schema"],
        identity=mapping["identity"],
        calibration_receipt_schema=mapping["calibration_receipt_schema"],
        calibration_receipt_identity=mapping["calibration_receipt_identity"],
        fixed_root_policy_control_fields=tuple(policy_control_fields),
        fixed_root_reliability_rule=mapping["fixed_root_reliability_rule"],
        fixed_root_reliability_target_control_field=target_control_field,
        required_digit_guard=guard,
        authority_sha256=observed_sha256,
    )


@lru_cache(maxsize=1)
def load_fixed_root_reliability_projection_authority(
) -> FixedRootReliabilityProjectionAuthority:
    """Load and digest-verify the package-owned projection authority."""

    raw = files("windows_solver").joinpath(
        FIXED_ROOT_RELIABILITY_PROJECTION_AUTHORITY_RESOURCE
    ).read_bytes()
    return _parse_fixed_root_reliability_projection_authority(raw)
