"""Authenticated, human-reviewed determinant-error evidence.

This module is deliberately load-only at campaign runtime.  It authenticates
externally issued per-sample absolute-error receipts; it never derives an error
bound from conditioning telemetry, finite-difference agreement, ULPs, or
predicted reliable digits.

TODO: [HUMAN MATH REVIEW REQUIRED - approve the fixed-root exterior determinant absolute-error construction and issue the governing derivation receipt]
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Mapping, Sequence

from .contracts import canonical_json_bytes
from .response_uncertainty import ComplexDisk


REVIEWED_DETERMINANT_ERROR_CLAIM_SCHEMA = (
    "windows-solver.reviewed-determinant-error-claim/1"
)
REVIEWED_DETERMINANT_ERROR_RECEIPT_SCHEMA = (
    "windows-solver.reviewed-determinant-error-receipt/1"
)
_HEX_64 = re.compile(r"[0-9a-f]{64}")


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


class DeterminantErrorEvidenceStatus(str, Enum):
    EMPTY = "EMPTY"
    MISS = "MISS"
    HIT = "HIT"
    CORRUPT = "CORRUPT"


class DeterminantErrorEvidenceCorruption(ValueError):
    """A receipt at its trusted content address did not authenticate."""


@dataclass(frozen=True, slots=True)
class ReviewedDeterminantErrorReceipt:
    claim: Mapping[str, object]
    absolute_determinant_error_bound: float
    derivation_identity: str
    derivation_version: str
    human_mathematics_approval_receipt_sha256: str
    receipt_sha256: str

    def __post_init__(self) -> None:
        claim = json.loads(canonical_json_bytes(dict(self.claim)))
        if (
            claim.get("schema") != REVIEWED_DETERMINANT_ERROR_CLAIM_SCHEMA
            or claim.get("claim_sha256") is not None
        ):
            raise ValueError("reviewed determinant-error claim is invalid")
        _validate_claim(claim)
        bound = float(self.absolute_determinant_error_bound)
        if not math.isfinite(bound) or bound <= 0.0:
            raise ValueError(
                "reviewed determinant absolute-error bound is invalid"
            )
        if not self.derivation_identity or not self.derivation_version:
            raise ValueError("reviewed determinant-error derivation is invalid")
        if _HEX_64.fullmatch(
            self.human_mathematics_approval_receipt_sha256
        ) is None:
            raise ValueError(
                "reviewed determinant-error mathematics approval is invalid"
            )
        if _HEX_64.fullmatch(self.receipt_sha256) is None:
            raise ValueError("reviewed determinant-error receipt digest is invalid")
        object.__setattr__(self, "claim", claim)
        object.__setattr__(self, "absolute_determinant_error_bound", bound)
        if self.receipt_sha256 != _sha256(self._content_mapping()):
            raise ValueError("reviewed determinant-error receipt digest mismatch")

    @property
    def claim_sha256(self) -> str:
        return _sha256(self.claim)

    def _content_mapping(self) -> dict[str, object]:
        return {
            "schema": REVIEWED_DETERMINANT_ERROR_RECEIPT_SCHEMA,
            "claim": dict(self.claim),
            "claim_sha256": self.claim_sha256,
            "absolute_determinant_error_bound": (
                self.absolute_determinant_error_bound.hex()
            ),
            "derivation_identity": self.derivation_identity,
            "derivation_version": self.derivation_version,
            "human_mathematics_approval_receipt_sha256": (
                self.human_mathematics_approval_receipt_sha256
            ),
        }

    def to_mapping(self) -> dict[str, object]:
        return {**self._content_mapping(), "receipt_sha256": self.receipt_sha256}

    @classmethod
    def issue(
        cls,
        *,
        claim: Mapping[str, object],
        absolute_determinant_error_bound: float,
        derivation_identity: str,
        derivation_version: str,
        human_mathematics_approval_receipt_sha256: str,
    ) -> "ReviewedDeterminantErrorReceipt":
        """Seal a bound only when an external approval digest is supplied."""

        canonical_claim = json.loads(canonical_json_bytes(dict(claim)))
        _validate_claim(canonical_claim)
        bound = float(absolute_determinant_error_bound)
        content = {
            "schema": REVIEWED_DETERMINANT_ERROR_RECEIPT_SCHEMA,
            "claim": canonical_claim,
            "claim_sha256": _sha256(canonical_claim),
            "absolute_determinant_error_bound": bound.hex(),
            "derivation_identity": derivation_identity,
            "derivation_version": derivation_version,
            "human_mathematics_approval_receipt_sha256": (
                human_mathematics_approval_receipt_sha256
            ),
        }
        return cls(
            claim=canonical_claim,
            absolute_determinant_error_bound=bound,
            derivation_identity=derivation_identity,
            derivation_version=derivation_version,
            human_mathematics_approval_receipt_sha256=(
                human_mathematics_approval_receipt_sha256
            ),
            receipt_sha256=_sha256(content),
        )

    @classmethod
    def from_mapping(cls, value: object) -> "ReviewedDeterminantErrorReceipt":
        fields = {
            "schema",
            "claim",
            "claim_sha256",
            "absolute_determinant_error_bound",
            "derivation_identity",
            "derivation_version",
            "human_mathematics_approval_receipt_sha256",
            "receipt_sha256",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError("reviewed determinant-error receipt fields are invalid")
        if value["schema"] != REVIEWED_DETERMINANT_ERROR_RECEIPT_SCHEMA:
            raise ValueError("reviewed determinant-error receipt schema is invalid")
        claim = value["claim"]
        if not isinstance(claim, Mapping) or value["claim_sha256"] != _sha256(claim):
            raise ValueError("reviewed determinant-error claim digest mismatch")
        raw_bound = value["absolute_determinant_error_bound"]
        if not isinstance(raw_bound, str):
            raise ValueError("reviewed determinant-error bound encoding is invalid")
        try:
            bound = float.fromhex(raw_bound)
        except ValueError as error:
            raise ValueError(
                "reviewed determinant-error bound encoding is invalid"
            ) from error
        for name in ("derivation_identity", "derivation_version"):
            if not isinstance(value[name], str) or not value[name]:
                raise ValueError(
                    "reviewed determinant-error derivation fields are invalid"
                )
        approval = value["human_mathematics_approval_receipt_sha256"]
        receipt_sha256 = value["receipt_sha256"]
        if not isinstance(approval, str) or not isinstance(receipt_sha256, str):
            raise ValueError("reviewed determinant-error digest fields are invalid")
        return cls(
            claim=claim,
            absolute_determinant_error_bound=bound,
            derivation_identity=value["derivation_identity"],
            derivation_version=value["derivation_version"],
            human_mathematics_approval_receipt_sha256=approval,
            receipt_sha256=receipt_sha256,
        )


def _validate_claim(claim: Mapping[str, object]) -> None:
    fields = {
        "schema",
        "leaf_id",
        "job_id",
        "scientific_operation_identity",
        "root_seal_sha256",
        "fixed_root",
        "root_identity_sha256",
        "branch_identity",
        "angular_identity_sha256",
        "determinant_family",
        "determinant_convention",
        "determinant_normalisation",
        "backend_identity_sha256",
        "runtime_identity_sha256",
        "arithmetic_tier",
        "working_precision",
        "numerical_control_identity_sha256",
        "sample_role",
        "frequency",
        "amplitude",
        "determinant_centre",
    }
    if set(claim) != fields:
        raise ValueError("reviewed determinant-error claim fields are invalid")
    text_fields = (
        "leaf_id",
        "job_id",
        "scientific_operation_identity",
        "branch_identity",
        "determinant_family",
        "determinant_convention",
        "determinant_normalisation",
        "arithmetic_tier",
        "sample_role",
    )
    if any(not isinstance(claim[name], str) or not claim[name] for name in text_fields):
        raise ValueError("reviewed determinant-error claim identity is invalid")
    digest_fields = (
        "root_seal_sha256",
        "root_identity_sha256",
        "angular_identity_sha256",
        "backend_identity_sha256",
        "runtime_identity_sha256",
        "numerical_control_identity_sha256",
    )
    if any(
        not isinstance(claim[name], str)
        or _HEX_64.fullmatch(claim[name]) is None
        for name in digest_fields
    ):
        raise ValueError("reviewed determinant-error claim digest is invalid")
    if type(claim["working_precision"]) is not int or claim["working_precision"] < 2:
        raise ValueError("reviewed determinant-error working precision is invalid")
    for name in ("fixed_root", "frequency", "amplitude", "determinant_centre"):
        value = claim[name]
        if not isinstance(value, Mapping) or not value:
            raise ValueError(f"reviewed determinant-error {name} is invalid")


@dataclass(frozen=True, slots=True)
class DeterminantErrorLookup:
    status: DeterminantErrorEvidenceStatus
    receipt: ReviewedDeterminantErrorReceipt | None = None


@dataclass(frozen=True, slots=True)
class AuthenticatedDeterminantErrorBundle:
    receipts: tuple[ReviewedDeterminantErrorReceipt, ...]

    @property
    def disks_by_role(self) -> Mapping[str, ComplexDisk]:
        return {
            str(receipt.claim["sample_role"]): ComplexDisk(
                _complex_from_mapping(receipt.claim["determinant_centre"]),
                receipt.absolute_determinant_error_bound,
                exact_zero_radius=False,
            )
            for receipt in self.receipts
        }

    def to_mappings(self) -> tuple[Mapping[str, object], ...]:
        return tuple(receipt.to_mapping() for receipt in self.receipts)


def _complex_from_mapping(value: object) -> complex:
    if not isinstance(value, Mapping):
        raise ValueError("reviewed determinant-error complex value is invalid")
    try:
        real = value["real"]
        imaginary = value["imaginary"]
        if isinstance(real, str):
            real = float(real)
        if isinstance(imaginary, str):
            imaginary = float(imaginary)
        result = complex(float(real), float(imaginary))
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("reviewed determinant-error complex value is invalid") from error
    if not math.isfinite(result.real) or not math.isfinite(result.imag):
        raise ValueError("reviewed determinant-error complex value is invalid")
    return result


class ReviewedDeterminantErrorStore:
    """Content-addressed load-only store for approved sample receipts."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def lookup(self, claim: Mapping[str, object]) -> DeterminantErrorLookup:
        canonical_claim = json.loads(canonical_json_bytes(dict(claim)))
        _validate_claim(canonical_claim)
        address = _sha256(canonical_claim)
        if not self.root.exists():
            return DeterminantErrorLookup(DeterminantErrorEvidenceStatus.EMPTY)
        path = self.root / f"{address}.json"
        if not path.exists():
            return DeterminantErrorLookup(DeterminantErrorEvidenceStatus.MISS)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            receipt = ReviewedDeterminantErrorReceipt.from_mapping(raw)
            if receipt.claim_sha256 != address or dict(receipt.claim) != canonical_claim:
                raise ValueError("receipt does not bind the requested sample")
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise DeterminantErrorEvidenceCorruption(
                f"trusted reviewed determinant-error receipt is corrupt: {path}: {error}"
            ) from error
        return DeterminantErrorLookup(
            DeterminantErrorEvidenceStatus.HIT,
            receipt,
        )

    def resolve_required(
        self, claims: Sequence[Mapping[str, object]]
    ) -> AuthenticatedDeterminantErrorBundle | None:
        receipts: list[ReviewedDeterminantErrorReceipt] = []
        for claim in claims:
            result = self.lookup(claim)
            if result.status is not DeterminantErrorEvidenceStatus.HIT:
                return None
            assert result.receipt is not None
            receipts.append(result.receipt)
        return AuthenticatedDeterminantErrorBundle(tuple(receipts))


__all__ = [
    "AuthenticatedDeterminantErrorBundle",
    "DeterminantErrorEvidenceCorruption",
    "DeterminantErrorEvidenceStatus",
    "ReviewedDeterminantErrorReceipt",
    "ReviewedDeterminantErrorStore",
]
