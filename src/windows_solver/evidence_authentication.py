"""Authentication rules for schema-11 evidence-strengthening receipts."""

from __future__ import annotations

import hashlib
from typing import Mapping

from .contracts import canonical_json_bytes


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def evidence_policy_identity(profile: str) -> str:
    if profile not in {"CERTIFY", "VALIDATE"}:
        raise ValueError("evidence authentication profile is invalid")
    return _sha256({
        "schema": "windows-solver.evidence-strengthening-policy/1",
        "profile": profile,
        "precision_tiers": ["BF80"],
        "bf120_review_receipt_sha256": None,
        "certificate_path_allowed": profile == "CERTIFY",
        "independent_validation_allowed": profile == "VALIDATE",
    })


def _digest_authenticates(receipt: Mapping[str, object]) -> bool:
    material = dict(receipt)
    supplied = material.pop("receipt_sha256", None)
    if not _is_sha256(supplied):
        return False
    if supplied != _sha256(material):
        raise ValueError("evidence receipt digest is invalid")
    return True


def certified_disposition_is_admitted(
    receipt: Mapping[str, object],
    *,
    leaf_id: str,
    central_record_sha256: str,
    central_stage_sha256: str,
) -> bool:
    """Authenticate the complete disposition that authorizes CERTIFIED."""

    if receipt.get("schema") != "windows-solver.evidence-pass-disposition/1":
        return False
    if not _digest_authenticates(receipt):
        return False
    source = receipt.get("source_receipt")
    if not isinstance(source, Mapping) or not _digest_authenticates(source):
        return False
    independent_result = source.get("independent_result")
    if not isinstance(independent_result, Mapping):
        return False
    policy_identity = evidence_policy_identity("CERTIFY")
    return (
        receipt.get("profile") == "CERTIFY"
        and receipt.get("leaf_id") == leaf_id
        and receipt.get("central_record_sha256") == central_record_sha256
        and receipt.get("central_stage_sha256") == central_stage_sha256
        and receipt.get("evidence_policy_identity") == policy_identity
        and receipt.get("centre_agrees") is True
        and receipt.get("discrepancy_code") is None
        and receipt.get("validation_admission_status") == "NOT_APPLICABLE"
        and source.get("schema") == "windows-solver.native-evidence-result/1"
        and source.get("profile") == "CERTIFY"
        and source.get("leaf_id") == leaf_id
        and source.get("central_record_sha256") == central_record_sha256
        and source.get("central_stage_sha256") == central_stage_sha256
        and source.get("evidence_policy_identity") == policy_identity
        and source.get("operation_identity")
        == "production-certification-comparator/v1"
        and source.get("calculation_route_identity")
        == "same-backend-refinement/v1"
        and source.get("refinement") == 0
        and source.get("centre_agrees") is True
        and source.get("discrepancy_code") is None
        and _is_sha256(source.get("backend_identity"))
        and _is_sha256(source.get("runtime_identity"))
        and _is_sha256(source.get("route_output_sha256"))
        and source.get("route_output_sha256") == _sha256(independent_result)
    )


__all__ = [
    "certified_disposition_is_admitted",
    "evidence_policy_identity",
]
