"""Structural admission gate for genuinely independent validation routes.

TODO: [HUMAN MATH REVIEW REQUIRED - approve a genuinely independent validation route before VALIDATED can be awarded]
"""

from __future__ import annotations

import hashlib
from typing import Mapping

from .contracts import canonical_json_bytes
from .evidence_authentication import evidence_policy_identity


INDEPENDENT_VALIDATION_ROUTES = {
    "exterior-finite-amplitude-root-displacement/v1": "EXTERIOR",
    "horizon-finite-amplitude-scattering/v1": "HORIZON",
}
SAME_BACKEND_REFINEMENT_ROUTE = "same-backend-refinement/v1"
HUMAN_REVIEW_SCHEMA = "windows-solver.independent-validation-human-review/1"


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _is_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def validation_admission_status(receipt: Mapping[str, object]) -> str:
    """Return ADMITTED only for a complete reviewed route-specific receipt."""

    material = dict(receipt)
    supplied_receipt_sha256 = material.pop("receipt_sha256", None)
    if (
        not _is_sha256(supplied_receipt_sha256)
        or supplied_receipt_sha256 != _sha256(material)
    ):
        raise ValueError("independent validation source receipt digest is invalid")
    route = receipt.get("calculation_route_identity")
    if route == SAME_BACKEND_REFINEMENT_ROUTE:
        return "ROUTE_NOT_INDEPENDENT"
    if route not in INDEPENDENT_VALIDATION_ROUTES:
        return "INDEPENDENT_ROUTE_NOT_REVIEWED"
    expected_family = INDEPENDENT_VALIDATION_ROUTES[route]
    if receipt.get("calculation_route_family") != expected_family:
        return "INDEPENDENT_ROUTE_IDENTITY_MISMATCH"
    output = receipt.get("independent_result")
    output_sha = receipt.get("route_output_sha256")
    if not isinstance(output, Mapping) or not _is_sha256(output_sha):
        return "ROUTE_OUTPUT_UNAUTHENTICATED"
    if output_sha != _sha256(output):
        raise ValueError("independent validation route output digest mismatch")

    review = receipt.get("human_mathematics_review_receipt")
    if review is None:
        return "HUMAN_MATH_REVIEW_REQUIRED"
    fields = {
        "schema",
        "calculation_route_identity",
        "equations_approved",
        "normalisation_approved",
        "continuation_approved",
        "uncertainty_treatment_approved",
        "acceptance_rule_approved",
        "receipt_sha256",
    }
    if not isinstance(review, Mapping) or set(review) != fields:
        raise ValueError("independent validation human-review fields are invalid")
    content = {name: review[name] for name in fields - {"receipt_sha256"}}
    if (
        review["schema"] != HUMAN_REVIEW_SCHEMA
        or review["calculation_route_identity"] != route
        or any(
            review[name] is not True
            for name in (
                "equations_approved",
                "normalisation_approved",
                "continuation_approved",
                "uncertainty_treatment_approved",
                "acceptance_rule_approved",
            )
        )
        or review["receipt_sha256"] != _sha256(content)
    ):
        raise ValueError("independent validation human-review receipt is invalid")
    return "ADMITTED"


def validated_disposition_is_admitted(
    receipt: Mapping[str, object],
    *,
    leaf_id: str,
    central_record_sha256: str,
    central_stage_sha256: str,
) -> bool:
    """Authenticate the ledger receipt authorizing a VALIDATED transition."""

    if receipt.get("schema") != "windows-solver.evidence-pass-disposition/1":
        return False
    material = dict(receipt)
    supplied = material.pop("receipt_sha256", None)
    if not _is_sha256(supplied) or supplied != _sha256(material):
        raise ValueError("validation disposition receipt digest is invalid")
    source = receipt.get("source_receipt")
    if not isinstance(source, Mapping):
        return False
    return (
        receipt.get("profile") == "VALIDATE"
        and receipt.get("leaf_id") == leaf_id
        and receipt.get("central_record_sha256") == central_record_sha256
        and receipt.get("central_stage_sha256") == central_stage_sha256
        and receipt.get("validation_admission_status") == "ADMITTED"
        and receipt.get("evidence_policy_identity")
        == evidence_policy_identity("VALIDATE")
        and source.get("profile") == "VALIDATE"
        and source.get("leaf_id") == leaf_id
        and source.get("central_record_sha256") == central_record_sha256
        and source.get("central_stage_sha256") == central_stage_sha256
        and source.get("evidence_policy_identity")
        == evidence_policy_identity("VALIDATE")
        and source.get("operation_identity")
        == "independent-validation-comparator/v1"
        and _is_sha256(source.get("backend_identity"))
        and _is_sha256(source.get("runtime_identity"))
        and validation_admission_status(source) == "ADMITTED"
    )


__all__ = [
    "INDEPENDENT_VALIDATION_ROUTES",
    "SAME_BACKEND_REFINEMENT_ROUTE",
    "validated_disposition_is_admitted",
    "validation_admission_status",
]
