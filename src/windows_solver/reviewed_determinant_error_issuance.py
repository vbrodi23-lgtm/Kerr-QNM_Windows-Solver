"""Retain exterior error inputs without manufacturing an unreviewed disk.

TODO: [HUMAN NUMERICAL CALIBRATION REQUIRED — freeze and authenticate the
SCREENED exterior safety factors on a predeclared calibration/holdout set, or
supply validated determinant-ball evidence.]
"""

from __future__ import annotations

from dataclasses import dataclass

from .julia_response_backend import JuliaFixedRootSurveyBatch
from .promoted_control_calibration import (
    PromotedControlCalibrationReceipt,
    PromotedExecutionMode,
    load_default_calibration_receipt,
)
from .response_engine import ResponseComponentJob
from .reviewed_determinant_error import ReviewedDeterminantErrorStore


@dataclass(frozen=True, slots=True)
class PromotedExecutionPreflight:
    """Typed route policy; a known admission boundary is not an exception."""

    mode: PromotedExecutionMode
    route: str
    calculation_permitted: bool
    checkpointing_permitted: bool
    admission_permitted: bool
    publication_permitted: bool
    result_code: str


def require_locked_bf40_determinant_error_issuance_authority(
    receipt: PromotedControlCalibrationReceipt | None = None,
    *,
    route: str = "EXTERIOR_BF40",
) -> PromotedExecutionPreflight:
    """Return calculation/admission authority without blocking production."""

    if route not in {"EXTERIOR_BF40", "HORIZON_BF80"}:
        raise ValueError("promoted execution route is invalid")
    active = receipt or load_default_calibration_receipt()
    mode = active.execution_mode
    calculation_permitted = mode is not PromotedExecutionMode.BLOCK_ALL
    admission_permitted = mode is PromotedExecutionMode.CALCULATE_AND_ADMIT
    return PromotedExecutionPreflight(
        mode=mode,
        route=route,
        calculation_permitted=calculation_permitted,
        checkpointing_permitted=calculation_permitted,
        admission_permitted=admission_permitted,
        publication_permitted=admission_permitted,
        result_code={
            PromotedExecutionMode.CALCULATE_AND_ADMIT: "ADMISSION_AUTHORIZED",
            PromotedExecutionMode.CALCULATE_ONLY: "REVIEW_PENDING",
            PromotedExecutionMode.BLOCK_ALL: "BLOCKED_BY_ADMISSION_POLICY",
        }[mode],
    )


def retain_uncalibrated_determinant_error_evidence(
    store: ReviewedDeterminantErrorStore,
    job: ResponseComponentJob,
    batch: JuliaFixedRootSurveyBatch,
    *,
    root_seal_sha256: str,
) -> int:
    """Preserve raw channels in the durable provisional stage, never SCREENED.

    A calibration receipt must supply and authenticate the exterior safety
    factors before this boundary may issue an absolute determinant-error disk.
    Until then, the caller retains the full batch and receives no receipt.
    """

    del store, job, batch, root_seal_sha256
    return 0


__all__ = [
    "PromotedExecutionPreflight",
    "require_locked_bf40_determinant_error_issuance_authority",
    "retain_uncalibrated_determinant_error_evidence",
]
