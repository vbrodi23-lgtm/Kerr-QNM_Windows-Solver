"""Seal the worker's own approved exterior determinant-error certificate.

``reviewed_determinant_error.py`` is deliberately load-only: it authenticates
externally issued per-sample absolute-error receipts and never derives a
bound itself. This module is that external issuer for the promoted exterior
fixed-root survey.

The construction it seals -- per sample terms ``delta_same_point``,
``delta_cross_precision``, ``delta_endpoint_series``; safety factor 64;
``absolute_determinant_error_bound = safety_factor * max(terms)`` -- is not
invented here. It is the committed
``data/promoted_control_empirical_calibration_v1.json`` receipt's
``determinant_certificate`` contract (schema
``exterior-determinant-absolute-error-certificate/empirical-v1``), which
already carries dated operator approval
(``operator_approval.status == "operator-approved/v1"``) for calculation and
checkpointing use. This module authenticates that the worker's returned
per-sample evidence is internally consistent with that exact, already-
approved contract -- same model identity, same safety factor, same term
classes, and the bound recomputed and checked bit-for-bit -- before binding
a durable receipt to that calibration receipt's own SHA-256 as its
``human_mathematics_approval_receipt_sha256``. It never fabricates a receipt
from metadata alone, and it never widens the approval's own scope: the
calibration receipt's admission boundary blocks publication and scientific
admission pending independent review, so a receipt sealed here can support
SCREENED survey evidence only, never CERTIFIED or VALIDATED status.
"""

from __future__ import annotations

import math
import os
import tempfile
from pathlib import Path
from typing import Mapping

from .contracts import canonical_json_bytes
from .julia_response_backend import JuliaFixedRootSurveyBatch
from .promoted_control_calibration import load_default_calibration_receipt
from .response_engine import (
    ResponseComponentJob,
    reviewed_determinant_error_claims_for_fixed_root_batch,
)
from .reviewed_determinant_error import (
    DeterminantErrorEvidenceStatus,
    ReviewedDeterminantErrorReceipt,
    ReviewedDeterminantErrorStore,
)

EXTERIOR_EMPIRICAL_ERROR_MODEL_ID = (
    "exterior-determinant-absolute-error-certificate/empirical-v1"
)
EXTERIOR_EMPIRICAL_ERROR_SAFETY_FACTOR = 64
EXTERIOR_EMPIRICAL_ERROR_TERM_CLASSES = (
    "delta_same_point",
    "delta_cross_precision",
    "delta_endpoint_series",
)
_DERIVATION_VERSION = "1"


def _approval_receipt_sha256() -> str:
    return load_default_calibration_receipt().sha256


def _authenticated_bound(evidence: Mapping[str, object]) -> float:
    """Recompute and check the worker's own certificate bit-for-bit."""

    if evidence.get("error_model_id") != EXTERIOR_EMPIRICAL_ERROR_MODEL_ID:
        raise ValueError("exterior determinant-error evidence model is unsupported")
    terms = {
        name: float(evidence[name]) for name in EXTERIOR_EMPIRICAL_ERROR_TERM_CLASSES
    }
    for name, value in terms.items():
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"exterior determinant-error evidence {name} is invalid")
    safety_factor = float(evidence["safety_factor"])
    if safety_factor != EXTERIOR_EMPIRICAL_ERROR_SAFETY_FACTOR:
        raise ValueError("exterior determinant-error evidence safety factor is invalid")
    numerical_error_abs = float(evidence["numerical_error_abs"])
    expected_bound = safety_factor * max(terms.values())
    if numerical_error_abs != expected_bound:
        raise ValueError(
            "exterior determinant-error evidence bound does not match "
            "safety_factor * max(delta_same_point, delta_cross_precision, "
            "delta_endpoint_series)"
        )
    if not math.isfinite(numerical_error_abs) or numerical_error_abs <= 0.0:
        raise ValueError("exterior determinant-error evidence bound is invalid")
    return numerical_error_abs


def _atomic_write_receipt(root: Path, receipt: ReviewedDeterminantErrorReceipt) -> None:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{receipt.claim_sha256}.json"
    descriptor, temporary_name = tempfile.mkstemp(
        dir=root, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json_bytes(receipt.to_mapping()))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def seed_operator_approved_determinant_error_receipts(
    store: ReviewedDeterminantErrorStore,
    job: ResponseComponentJob,
    batch: JuliaFixedRootSurveyBatch,
    *,
    root_seal_sha256: str,
) -> int:
    """Seal the worker's own certificate evidence into the durable store.

    Idempotent and additive only: a claim already sealed (``HIT``) is left
    untouched -- the first admitted receipt for an exact claim is durable and
    is never resealed from a fresh computation. A sample carrying no
    certificate evidence (a legacy or non-exterior batch) is a silent
    no-op; the caller's ordinary ``resolve_required`` lookup then reports a
    ``MISS`` for that claim and survey falls back to the full unbounded
    promotion path, exactly as if this module did not exist.
    """

    claims = reviewed_determinant_error_claims_for_fixed_root_batch(
        job,
        batch,
        root_seal_sha256=root_seal_sha256,
        arithmetic_tier=batch.precision_tier.value,
        working_precision=batch.working_precision_bits,
    )
    approval_sha256 = _approval_receipt_sha256()
    sealed = 0
    for claim, sample in zip(claims, batch.samples):
        lookup = store.lookup(claim)
        if lookup.status not in (
            DeterminantErrorEvidenceStatus.EMPTY,
            DeterminantErrorEvidenceStatus.MISS,
        ):
            continue
        evidence = sample.determinant_error_evidence
        if evidence is None:
            continue
        bound = _authenticated_bound(evidence.mapping)
        receipt = ReviewedDeterminantErrorReceipt.issue(
            claim=claim,
            absolute_determinant_error_bound=bound,
            derivation_identity=EXTERIOR_EMPIRICAL_ERROR_MODEL_ID,
            derivation_version=_DERIVATION_VERSION,
            human_mathematics_approval_receipt_sha256=approval_sha256,
        )
        _atomic_write_receipt(store.root, receipt)
        sealed += 1
    return sealed


__all__ = [
    "EXTERIOR_EMPIRICAL_ERROR_MODEL_ID",
    "EXTERIOR_EMPIRICAL_ERROR_SAFETY_FACTOR",
    "EXTERIOR_EMPIRICAL_ERROR_TERM_CLASSES",
    "seed_operator_approved_determinant_error_receipts",
]
