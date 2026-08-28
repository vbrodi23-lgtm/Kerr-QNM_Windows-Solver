"""Typed provenance for promoted roots retained as partial-work evidence.

This module sits below campaign checkpoint policy.  It authenticates a root
receipt without importing the scheduler, while the scheduler may additionally
bind the returned authority to its live leaf object before using the root.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
import math
from typing import Mapping

from .contracts import canonical_json_bytes
from .response_engine import PROMOTED_ROOT_SEAL_SCHEMA, PromotedRootSeal
from .root_evidence import (
    AuthenticatedRootEvidence,
    ROOT_DEPENDENCY_KEY_SCHEMA,
    ROOT_EVIDENCE_SCHEMA,
    RootDependencyKey,
)


PROMOTED_ROOT_RECEIPT_SCHEMA = (
    "windows-solver.promoted-root-evidence-receipt/2"
)
ROOT_PROMOTION_ARITHMETIC_TIER = "root-promotion"


def _dependency_key_from_mapping(value: object) -> RootDependencyKey:
    fields = {
        "schema",
        "root_reference_id",
        "root_identity_sha256",
        "mode",
        "sampling_coordinate",
        "spin",
        "branch_identity",
        "equation_id",
        "backend_identity",
        "root_acceptance_policy_identity",
        "arithmetic_tier",
    }
    if (
        not isinstance(value, Mapping)
        or set(value) != fields
        or value.get("schema") != ROOT_DEPENDENCY_KEY_SCHEMA
    ):
        raise ValueError("promoted root dependency key is invalid")
    try:
        return RootDependencyKey(
            root_reference_id=str(value["root_reference_id"]),
            root_identity_sha256=str(value["root_identity_sha256"]),
            mode=value["mode"],  # type: ignore[arg-type]
            sampling_coordinate=value["sampling_coordinate"],  # type: ignore[arg-type]
            spin=value["spin"],  # type: ignore[arg-type]
            branch_identity=str(value["branch_identity"]),
            equation_id=str(value["equation_id"]),
            backend_identity=str(value["backend_identity"]),
            root_acceptance_policy_identity=str(
                value["root_acceptance_policy_identity"]
            ),
            arithmetic_tier=str(value["arithmetic_tier"]),
        )
    except (TypeError, ValueError) as error:
        raise ValueError("promoted root dependency key is invalid") from error


def _request_matches_worker_success(
    request: Mapping[str, object],
    authority: PromotedRootSeal,
    *,
    precision_tier: str,
    leaf: object | None = None,
) -> bool:
    digits = int(precision_tier[2:])
    amplitude = request.get("amplitude")
    if not isinstance(amplitude, Mapping):
        return False
    try:
        zero_amplitude = (
            Decimal(str(amplitude["real"])) == 0
            and Decimal(str(amplitude["imaginary"])) == 0
        )
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return False
    if (
        not zero_amplitude
        or request.get("operation") != "root-readout"
        or request.get("leaf_id") != authority.leaf_id
        or request.get("job_id") != authority.job_id
        or request.get("mechanism_id") != authority.mechanism_id
        or request.get("job_policy_sha256") != authority.policy_sha256
        or request.get("backend_identity_sha256")
        != authority.backend_identity_sha256
        or request.get("precision_digits") != digits
        or request.get("semantic_precision_tier") != f"bigfloat-{digits}"
    ):
        return False
    if leaf is None:
        return True
    job = leaf.job
    return (
        request.get("leaf_id") == job.leaf_id
        and request.get("job_id") == job.job_id
        and request.get("role") == job.role
        and request.get("mechanism_id") == job.mechanism_id
        and request.get("job_policy_sha256") == job.policy.identity_sha256
        and request.get("backend_identity_sha256")
        == job.backend_identity.identity_sha256
        and request.get("mode")
        == {
            "s": job.mode.s,
            "ell": job.mode.ell,
            "m": job.mode.m,
            "n": job.mode.n,
        }
        and request.get("spin") == format(job.spin, ".17g")
        and request.get("primary_predictor")
        == {
            "real": format(job.root.omega.real, ".17g"),
            "imaginary": format(job.root.omega.imag, ".17g"),
        }
    )


@dataclass(frozen=True, slots=True)
class ValidatedPromotedRootSuccessAuthority:
    canonical: Mapping[str, object]
    kind: str
    fixed_root: complex
    branch_identity: str
    root_seal_sha256: str
    precision_tier: str

    def validate_for(self, leaf: object) -> None:
        if self.kind == "WORKER_ROOT_SUCCESS":
            authority = PromotedRootSeal.from_mapping(self.canonical)
            authority.validate_for(leaf.job)
            receipt = authority.root_readout.worker_response_receipt
            request = (
                receipt.get("request_binding")
                if isinstance(receipt, Mapping)
                else None
            )
            if not isinstance(request, Mapping) or not _request_matches_worker_success(
                request,
                authority,
                precision_tier=self.precision_tier,
                leaf=leaf,
            ):
                raise ValueError(
                    "promoted worker root success request identity is invalid"
                )
            return
        authority = AuthenticatedRootEvidence.from_mapping(self.canonical)
        authority.validate_for(leaf)


def validate_promoted_root_success_authority(
    value: object,
    *,
    precision_tier: str,
) -> ValidatedPromotedRootSuccessAuthority:
    if precision_tier not in {"BF40", "BF80"} or not isinstance(value, Mapping):
        raise ValueError("promoted root success authority is invalid")
    canonical = json.loads(canonical_json_bytes(dict(value)))
    schema = canonical.get("schema")
    if schema == PROMOTED_ROOT_SEAL_SCHEMA:
        try:
            authority = PromotedRootSeal.from_mapping(canonical)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "promoted worker root success authority is invalid"
            ) from error
        receipt = authority.root_readout.worker_response_receipt
        request = (
            receipt.get("request_binding")
            if isinstance(receipt, Mapping)
            else None
        )
        if not isinstance(request, Mapping) or not _request_matches_worker_success(
            request,
            authority,
            precision_tier=precision_tier,
        ):
            raise ValueError(
                "promoted worker root success request identity is invalid"
            )
        return ValidatedPromotedRootSuccessAuthority(
            canonical,
            "WORKER_ROOT_SUCCESS",
            authority.root_readout.omega,
            authority.root_readout.branch_id,
            authority.sha256,
            precision_tier,
        )
    if schema == ROOT_EVIDENCE_SCHEMA:
        try:
            authority = AuthenticatedRootEvidence.from_mapping(canonical)
        except (TypeError, ValueError) as error:
            raise ValueError("promoted durable root authority is invalid") from error
        return ValidatedPromotedRootSuccessAuthority(
            canonical,
            "DURABLE_ROOT_AUTHORITY",
            authority.fixed_root,
            authority.branch_identity,
            authority.root_seal_sha256,
            precision_tier,
        )
    raise ValueError("promoted root success authority schema is unsupported")


@dataclass(frozen=True, slots=True)
class ValidatedPromotedRootReceipt:
    canonical: Mapping[str, object]
    dependency_key: RootDependencyKey
    success_authority: ValidatedPromotedRootSuccessAuthority
    queue_ordinal: int
    leaf_id: str
    job_id: str
    precision_tier: str

    @property
    def fixed_root(self) -> complex:
        return self.success_authority.fixed_root

    @property
    def branch_identity(self) -> str:
        return self.success_authority.branch_identity

    @property
    def root_seal_sha256(self) -> str:
        return self.success_authority.root_seal_sha256

    def validate_for(self, leaf: object) -> None:
        expected = RootDependencyKey.from_leaf(
            leaf, arithmetic_tier=ROOT_PROMOTION_ARITHMETIC_TIER
        )
        if (
            self.leaf_id != leaf.job.leaf_id
            or self.job_id != leaf.job.job_id
            or self.dependency_key != expected
        ):
            raise ValueError("promoted root work leaf binding is invalid")
        self.success_authority.validate_for(leaf)


def validate_promoted_root_receipt(
    value: object,
    *,
    queue_ordinal: int,
    leaf_id: str,
    expected_precision_tier: str | None = None,
) -> tuple[dict[str, object], ValidatedPromotedRootReceipt]:
    fields = {
        "schema",
        "queue_ordinal",
        "leaf_id",
        "job_id",
        "precision_tier",
        "root_seal_sha256",
        "branch_identity",
        "fixed_root",
        "root_dependency_key",
        "root_dependency_key_sha256",
        "root_success_authority",
        "root_success_authority_sha256",
        "receipt_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError("promoted root work receipt is invalid")
    content = {key: item for key, item in value.items() if key != "receipt_sha256"}
    precision_tier = value.get("precision_tier")
    if (
        value.get("schema") != PROMOTED_ROOT_RECEIPT_SCHEMA
        or value.get("queue_ordinal") != queue_ordinal
        or value.get("leaf_id") != leaf_id
        or precision_tier not in {"BF40", "BF80"}
        or (
            expected_precision_tier is not None
            and precision_tier != expected_precision_tier
        )
        or value.get("receipt_sha256")
        != hashlib.sha256(canonical_json_bytes(content)).hexdigest()
    ):
        raise ValueError("promoted root work receipt is invalid")
    dependency = _dependency_key_from_mapping(value["root_dependency_key"])
    if (
        value.get("root_dependency_key_sha256") != dependency.sha256
        or dependency.arithmetic_tier != ROOT_PROMOTION_ARITHMETIC_TIER
    ):
        raise ValueError("promoted root work dependency is invalid")
    authority_value = value["root_success_authority"]
    if (
        not isinstance(authority_value, Mapping)
        or value.get("root_success_authority_sha256")
        != hashlib.sha256(canonical_json_bytes(dict(authority_value))).hexdigest()
    ):
        raise ValueError("promoted root success authority digest is invalid")
    authority = validate_promoted_root_success_authority(
        authority_value,
        precision_tier=str(precision_tier),
    )
    fixed_root_mapping = value.get("fixed_root")
    if not isinstance(fixed_root_mapping, Mapping) or set(fixed_root_mapping) != {
        "real",
        "imaginary",
    }:
        raise ValueError("promoted root work fixed root is invalid")
    try:
        retained_root = complex(
            float(fixed_root_mapping["real"]),
            float(fixed_root_mapping["imaginary"]),
        )
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("promoted root work fixed root is invalid") from error
    if not math.isfinite(retained_root.real) or not math.isfinite(retained_root.imag):
        raise ValueError("promoted root work fixed root is invalid")
    if (
        retained_root != authority.fixed_root
        or value.get("branch_identity") != authority.branch_identity
        or value.get("root_seal_sha256") != authority.root_seal_sha256
        or dependency.branch_identity != authority.branch_identity
    ):
        raise ValueError("promoted root work evidence binding is invalid")
    canonical = json.loads(canonical_json_bytes(dict(value)))
    validated = ValidatedPromotedRootReceipt(
        canonical,
        dependency,
        authority,
        queue_ordinal,
        leaf_id,
        str(value["job_id"]),
        str(precision_tier),
    )
    worker_authority = authority.canonical
    if (
        worker_authority.get("leaf_id") is not None
        and (
            worker_authority.get("leaf_id") != leaf_id
            or worker_authority.get("job_id") != validated.job_id
        )
    ):
        raise ValueError("promoted root work result identity is invalid")
    return canonical, validated


__all__ = [
    "PROMOTED_ROOT_RECEIPT_SCHEMA",
    "ROOT_PROMOTION_ARITHMETIC_TIER",
    "ValidatedPromotedRootReceipt",
    "ValidatedPromotedRootSuccessAuthority",
    "validate_promoted_root_receipt",
    "validate_promoted_root_success_authority",
]
