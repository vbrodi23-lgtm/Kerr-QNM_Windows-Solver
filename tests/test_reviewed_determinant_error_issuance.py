"""PR69 exterior determinant-error calibration gate regressions."""

from __future__ import annotations

from decimal import Decimal
import tempfile
import unittest
from pathlib import Path

from windows_solver.julia_response_backend import (
    FixedRootSurveyPlan,
    FixedRootSurveyConditioning,
    JuliaFixedRootSurveyBatch,
    JuliaFixedRootSurveySample,
)
from windows_solver.operation_control import (
    OPERATION_EXECUTION_IDENTITY_SCHEMA,
    OperationExecutionIdentity,
)
from windows_solver.precision_tiers import PrecisionTier
from windows_solver.response_batches import PrecisionCapabilities, build_campaign_plan
from windows_solver.response_engine import (
    BINARY64_FIXED_ROOT_SAMPLE_ROLES,
    Binary64SurveyDisposition,
    DecimalComplex,
    NumericalPolicy,
    VettedNativeDeterminantKernel,
    screen_promoted_fixed_root_samples,
)
from windows_solver.reviewed_determinant_error import ReviewedDeterminantErrorStore
from windows_solver.reviewed_determinant_error_issuance import (
    retain_uncalibrated_determinant_error_evidence,
)


def _job():
    plan = build_campaign_plan(
        policy=NumericalPolicy(),
        backend_identity=VettedNativeDeterminantKernel.identity,
        precision_capabilities=PrecisionCapabilities((64, 80, 120)),
    )
    return next(
        leaf.job
        for leaf in plan.leaves
        if leaf.job.mechanism_id == "exterior-light-ring"
    )


def _conditioning() -> FixedRootSurveyConditioning:
    return FixedRootSurveyConditioning({
        "schema": "windows-solver.fixed-root-survey-conditioning/2",
        "fixed_root_reliability_target_abs": "2e-11",
        "fixed_root_reliability_rule": (
            "minus-log10-target-plus-required-digit-guard/v1"
        ),
        "determinant_family": "exterior-wronskian/v1",
        "homogeneous_representation": "factored-plane-wave-gsn/v1",
        "branch_convention": "gsn-complex-rho/v1",
        "determinant_convention": "wronskian-perturbed-Xin-with-Xup/v1",
        "determinant_normalisation": "unit-asymptotic-branch-wronskian/v1",
        "maximum_series_digits_lost": "1",
        "maximum_recurrence_digits_lost": "1",
        "minimum_asymptotic_predicted_reliable_digits": "35",
        "endpoint_remainders_regular": True,
        "maximum_endpoint_reconstruction_error": "1e-30",
        "maximum_contour_angle_deformation": "0",
        "predicted_reliable_digits": "34",
        "required_reliable_digits": (
            "16.698970004336018804786261105275506973231810118538"
        ),
        "precision_limited": False,
        "determinant_count": 1,
    })


def _batch(job) -> JuliaFixedRootSurveyBatch:
    root = job.root.omega
    h = 1.0e-5 * (1.0 + abs(root))
    epsilon = float(job.policy.epsilons[0])
    points = (
        (root, 0.0), (root + h, 0.0), (root - h, 0.0),
        (root + h / 2.0, 0.0), (root - h / 2.0, 0.0),
        (root, epsilon), (root, -epsilon),
        (root, epsilon / 2.0), (root, -epsilon / 2.0),
    )
    request_sha256 = "2" * 64
    identity = OperationExecutionIdentity({
        "schema": OPERATION_EXECUTION_IDENTITY_SCHEMA,
        "scope": "REQUEST",
        "operation": "fixed-root-survey-batch",
        "request_schema": "windows-solver.fixed-root-survey-batch/2",
        "request_sha256": request_sha256,
        "leaf_id": job.leaf_id,
        "job_id": job.job_id,
        "backend_identity_sha256": job.backend_identity.identity_sha256,
        "precision_digits": 40,
        "working_precision_bits": 160,
        "semantic_precision_tier": "bigfloat-40",
        "effective_policy_identity": job.policy.identity_sha256,
        "execution_resource_policy_identity": {"sha256": "3" * 64},
        "plan": FixedRootSurveyPlan.FULL_NINE.value,
        "scientific_operation_identity": "exterior-fixed-root-survey-raw/v1",
        "root_reference_id": job.root.root_reference_id,
        "root_seal_sha256": "1" * 64,
        "branch_identity": job.root.branch_id,
        "sample_roles": list(BINARY64_FIXED_ROOT_SAMPLE_ROLES),
    })
    samples = tuple(
        JuliaFixedRootSurveySample(
            index,
            role,
            complex(omega),
            complex(amplitude),
            DecimalComplex(Decimal(str(3.0 * (omega.real - root.real))), Decimal(0)),
            _conditioning(),
            identity.select_sample(index, role).to_mapping(),
        )
        for index, (role, (omega, amplitude)) in enumerate(zip(
            BINARY64_FIXED_ROOT_SAMPLE_ROLES, points
        ))
    )
    return JuliaFixedRootSurveyBatch(
        leaf_id=job.leaf_id,
        job_id=job.job_id,
        mechanism_id=job.mechanism_id,
        root_reference_id=job.root.root_reference_id,
        root_seal_sha256="1" * 64,
        branch_identity=job.root.branch_id,
        fixed_root=root,
        frequency_step=Decimal(str(h)),
        coordinate_step=Decimal(str(epsilon)),
        scientific_operation_identity="exterior-fixed-root-survey-raw/v1",
        plan=FixedRootSurveyPlan.FULL_NINE,
        execution_identity=identity.to_mapping(),
        request_sha256=request_sha256,
        precision_tier=PrecisionTier.BIGFLOAT_40,
        working_precision_bits=160,
        samples=samples,
    )


class DeterminantErrorIssuanceTests(unittest.TestCase):
    def test_real_promoted_screening_blocks_without_calibration_but_keeps_batch(self) -> None:
        job = _job()
        batch = _batch(job)

        with tempfile.TemporaryDirectory() as temporary:
            store = ReviewedDeterminantErrorStore(Path(temporary))
            retained = retain_uncalibrated_determinant_error_evidence(
                store, job, batch, root_seal_sha256=batch.root_seal_sha256,
            )
            self.assertEqual(retained, 0)

        screening = screen_promoted_fixed_root_samples(
            batch.samples,
            frequency_step=batch.frequency_step,
            coordinate_step=batch.coordinate_step,
            determinant_error_evidence=None,
        )
        self.assertIs(
            screening.disposition,
            Binary64SurveyDisposition.PROMOTION_PENDING_RESPONSE,
        )
        self.assertEqual(
            screening.reason_code, "BLOCKED_BY_REVIEWED_ERROR_EVIDENCE"
        )
        self.assertEqual(
            screening.determinant_certificate_status,
            "blocked-by-reviewed-error-evidence",
        )
        self.assertIsNone(screening.response_disk)
        self.assertEqual(batch.sample_count, 9)

    def test_issuance_boundary_never_creates_an_unreviewed_receipt(self) -> None:
        job = _job()
        batch = _batch(job)
        with tempfile.TemporaryDirectory() as temporary:
            store = ReviewedDeterminantErrorStore(Path(temporary))
            self.assertEqual(
                retain_uncalibrated_determinant_error_evidence(
                    store, job, batch, root_seal_sha256=batch.root_seal_sha256,
                ),
                0,
            )


if __name__ == "__main__":
    unittest.main()
