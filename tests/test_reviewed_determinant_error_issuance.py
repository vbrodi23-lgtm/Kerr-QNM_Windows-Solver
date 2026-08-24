from __future__ import annotations

from decimal import Decimal
import tempfile
import unittest
from pathlib import Path

from windows_solver.julia_response_backend import (
    ExteriorDeterminantErrorEvidence,
    FixedRootSurveyConditioning,
    JuliaFixedRootSurveyBatch,
    JuliaFixedRootSurveySample,
)
from windows_solver.precision_tiers import PrecisionTier
from windows_solver.promoted_control_calibration import (
    load_default_calibration_receipt,
)
from windows_solver.response_batches import (
    PrecisionCapabilities,
    build_campaign_plan,
)
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
    EXTERIOR_EMPIRICAL_ERROR_MODEL_ID,
    seed_operator_approved_determinant_error_receipts,
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
        "schema": "windows-solver.fixed-root-survey-conditioning/1",
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
        "required_reliable_digits": "20",
        "precision_limited": False,
        "determinant_count": 1,
    })


def _evidence(index: int) -> ExteriorDeterminantErrorEvidence:
    delta_same_point = 1.0e-25 * (index + 1)
    delta_cross_precision = 2.0e-25 * (index + 1)
    delta_endpoint_series = 0.5e-25 * (index + 1)
    safety_factor = 64
    numerical_error_abs = safety_factor * max(
        delta_same_point, delta_cross_precision, delta_endpoint_series
    )
    return ExteriorDeterminantErrorEvidence({
        "schema": "windows-solver.exterior-determinant-error-evidence/1",
        "error_model_id": EXTERIOR_EMPIRICAL_ERROR_MODEL_ID,
        "delta_same_point": str(delta_same_point),
        "delta_cross_precision": str(delta_cross_precision),
        "delta_endpoint_series": str(delta_endpoint_series),
        "safety_factor": str(safety_factor),
        "numerical_error_abs": str(numerical_error_abs),
    })


def _batch(job, *, with_evidence: bool) -> JuliaFixedRootSurveyBatch:
    root = job.root.omega
    h = 1.0e-5 * (1.0 + abs(root))
    epsilon = float(job.policy.epsilons[0])
    points = (
        (root, 0.0),
        (root + h, 0.0),
        (root - h, 0.0),
        (root + h / 2.0, 0.0),
        (root - h / 2.0, 0.0),
        (root, epsilon),
        (root, -epsilon),
        (root, epsilon / 2.0),
        (root, -epsilon / 2.0),
    )
    samples = []
    for index, (role, (omega, amplitude)) in enumerate(
        zip(BINARY64_FIXED_ROOT_SAMPLE_ROLES, points)
    ):
        frequency = 3.0 * (omega.real - root.real)
        determinant = DecimalComplex(
            Decimal(str(frequency + 2.0 * amplitude)), Decimal(0)
        )
        samples.append(JuliaFixedRootSurveySample(
            role,
            complex(omega),
            complex(amplitude),
            determinant,
            _conditioning(),
            _evidence(index) if with_evidence else None,
        ))
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
        request_sha256="2" * 64,
        precision_tier=PrecisionTier.BIGFLOAT_40,
        working_precision_bits=160,
        samples=tuple(samples),
    )


class DeterminantErrorIssuanceTests(unittest.TestCase):
    def test_seeded_evidence_lets_promoted_survey_reach_produced(self) -> None:
        """The exact end state the governing contract requires: with the
        worker's own approved certificate evidence, promoted exterior
        survey actually bounds a response instead of always ending at
        DETERMINANT_ERROR_EVIDENCE_UNAVAILABLE."""

        job = _job()
        batch = _batch(job, with_evidence=True)

        with tempfile.TemporaryDirectory() as temporary:
            store = ReviewedDeterminantErrorStore(Path(temporary))
            sealed = seed_operator_approved_determinant_error_receipts(
                store, job, batch, root_seal_sha256=batch.root_seal_sha256,
            )
            self.assertEqual(9, sealed)

            from windows_solver.response_engine import (
                reviewed_determinant_error_claims_for_fixed_root_batch,
            )

            claims = reviewed_determinant_error_claims_for_fixed_root_batch(
                job, batch,
                root_seal_sha256=batch.root_seal_sha256,
                arithmetic_tier=batch.precision_tier.value,
                working_precision=batch.working_precision_bits,
            )
            bundle = store.resolve_required(claims)
            self.assertIsNotNone(bundle)

            screening = screen_promoted_fixed_root_samples(
                batch.samples,
                frequency_step=batch.frequency_step,
                coordinate_step=batch.coordinate_step,
                determinant_error_evidence=bundle,
            )

        self.assertIs(Binary64SurveyDisposition.PRODUCED, screening.disposition)
        self.assertIsNotNone(screening.response_disk)
        self.assertEqual(
            "approved-reviewed-error/v1", screening.determinant_certificate_status
        )

    def test_missing_evidence_stays_unavailable(self) -> None:
        job = _job()
        batch = _batch(job, with_evidence=False)

        with tempfile.TemporaryDirectory() as temporary:
            store = ReviewedDeterminantErrorStore(Path(temporary))
            sealed = seed_operator_approved_determinant_error_receipts(
                store, job, batch, root_seal_sha256=batch.root_seal_sha256,
            )
            self.assertEqual(0, sealed)

        screening = screen_promoted_fixed_root_samples(
            batch.samples,
            frequency_step=batch.frequency_step,
            coordinate_step=batch.coordinate_step,
            determinant_error_evidence=None,
        )
        self.assertIs(
            Binary64SurveyDisposition.PROMOTION_PENDING_RESPONSE,
            screening.disposition,
        )
        self.assertEqual(
            "DETERMINANT_ERROR_EVIDENCE_UNAVAILABLE", screening.reason_code
        )

    def test_second_batch_reuses_the_durable_seal_without_reissuing(self) -> None:
        job = _job()
        batch = _batch(job, with_evidence=True)

        with tempfile.TemporaryDirectory() as temporary:
            store = ReviewedDeterminantErrorStore(Path(temporary))
            first = seed_operator_approved_determinant_error_receipts(
                store, job, batch, root_seal_sha256=batch.root_seal_sha256,
            )
            second = seed_operator_approved_determinant_error_receipts(
                store, job, batch, root_seal_sha256=batch.root_seal_sha256,
            )

        self.assertEqual(9, first)
        self.assertEqual(0, second)

    def test_tampered_bound_is_rejected(self) -> None:
        """Python authenticates, never trusts, the worker's own arithmetic:
        a numerical_error_abs that does not equal
        safety_factor * max(delta terms) must be rejected."""

        job = _job()
        batch = _batch(job, with_evidence=True)
        tampered_sample = batch.samples[0]
        tampered_evidence = ExteriorDeterminantErrorEvidence({
            **tampered_sample.determinant_error_evidence.mapping,
            "numerical_error_abs": "999.0",
        })
        from dataclasses import replace
        tampered_batch = replace(
            batch,
            samples=(
                replace(
                    tampered_sample,
                    determinant_error_evidence=tampered_evidence,
                ),
                *batch.samples[1:],
            ),
        )

        with tempfile.TemporaryDirectory() as temporary:
            store = ReviewedDeterminantErrorStore(Path(temporary))
            with self.assertRaises(ValueError):
                seed_operator_approved_determinant_error_receipts(
                    store, job, tampered_batch,
                    root_seal_sha256=tampered_batch.root_seal_sha256,
                )

    def test_approval_receipt_is_the_committed_calibration_receipt(self) -> None:
        job = _job()
        batch = _batch(job, with_evidence=True)

        with tempfile.TemporaryDirectory() as temporary:
            store = ReviewedDeterminantErrorStore(Path(temporary))
            seed_operator_approved_determinant_error_receipts(
                store, job, batch, root_seal_sha256=batch.root_seal_sha256,
            )
            from windows_solver.response_engine import (
                reviewed_determinant_error_claims_for_fixed_root_batch,
            )
            claims = reviewed_determinant_error_claims_for_fixed_root_batch(
                job, batch,
                root_seal_sha256=batch.root_seal_sha256,
                arithmetic_tier=batch.precision_tier.value,
                working_precision=batch.working_precision_bits,
            )
            lookup = store.lookup(claims[0])

        self.assertEqual(
            load_default_calibration_receipt().sha256,
            lookup.receipt.human_mathematics_approval_receipt_sha256,
        )


if __name__ == "__main__":
    unittest.main()
