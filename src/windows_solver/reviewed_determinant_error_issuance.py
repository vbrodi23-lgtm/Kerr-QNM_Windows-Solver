"""Retain exterior error inputs without manufacturing an unreviewed disk.

TODO: [HUMAN NUMERICAL CALIBRATION REQUIRED — freeze and authenticate the
SCREENED exterior safety factors on a predeclared calibration/holdout set, or
supply validated determinant-ball evidence.]
"""

from __future__ import annotations

from .julia_response_backend import JuliaFixedRootSurveyBatch
from .response_engine import ResponseComponentJob
from .reviewed_determinant_error import ReviewedDeterminantErrorStore


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


__all__ = ["retain_uncalibrated_determinant_error_evidence"]
