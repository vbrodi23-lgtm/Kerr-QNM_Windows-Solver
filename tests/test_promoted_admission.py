from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Mapping
import unittest
from unittest.mock import patch

import windows_solver.promoted_admission as promoted_admission
from windows_solver.campaign_policy import (
    PromotionQueueKind,
    SurveyDisposition,
    SurveyPass,
    append_promotion,
    empty_schema11_checkpoint,
    record_survey_disposition,
    retain_promoted_calculation,
)
from windows_solver.campaign_runtime import _reduce_retained_exterior_for_admission
from windows_solver.campaign_survey import (
    AuthenticatedRootSeal,
    _promoted_background_key,
    _promoted_background_receipt,
)
from windows_solver.contracts import canonical_json_bytes
from windows_solver.cli import build_parser
from windows_solver.promoted_control_calibration import (
    load_default_calibration_receipt,
)
from windows_solver.promoted_admission import admit_retained_promoted_checkpoint
from windows_solver.julia_response_backend import (
    ExteriorDeterminantErrorEvidence,
    FixedRootSurveyPlan,
    fixed_root_survey_request_contract,
)
from windows_solver.promoted_artifacts import (
    PromotedBackgroundBinding,
    PromotedExteriorCalculationResult,
)
from windows_solver.response_batches import (
    PrecisionCapabilities,
    build_campaign_plan,
)
from windows_solver.response_engine import NumericalPolicy, VettedNativeDeterminantKernel

from tests.test_promoted_survey_scheduler import _batch


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


class PromotedAdmissionTests(unittest.TestCase):
    def test_cli_derives_review_authority_from_the_canonical_receipt(self):
        parsed = build_parser().parse_args([
            "campaign-admit-promoted",
            "selection.json",
            "--checkpoint",
            "checkpoint.json",
            "--binary64-lock",
            "checkpoint.json.binary64-lock.json",
            "--queue-ordinal",
            "7",
            "--review-receipt",
            "review.json",
            "--calibration-receipt-path",
            "calibration.json",
            "--calibration-receipt-sha256",
            "a" * 64,
        ])

        self.assertEqual("campaign-admit-promoted", parsed.command)
        self.assertEqual(7, parsed.queue_ordinal)
        self.assertEqual(Path("review.json"), parsed.review_receipt)
        self.assertFalse(hasattr(parsed, "review_authority_sha256"))

    def _checkpoint_and_review(
        self,
        *,
        calibration_receipt_sha256: str = "c" * 64,
        authority_sha256: str = "d" * 64,
    ):
        leaf_id = "leaf-1"
        scientific_identity = "b" * 64
        central_stage_content = {
            "schema": "windows-solver.test-admitted-stage/1",
            "precision_tier": "BF40",
            "response_disk": {
                "centre": {"real": 1.0, "imaginary": -0.25},
                "radius": 0.125,
            },
        }
        central_stage = {
            **central_stage_content,
            "stage_sha256": _sha256(central_stage_content),
        }
        record_content = {
            "leaf_id": leaf_id,
            "state": "PRODUCED",
            "retained_centre": {"real": 1.0, "imaginary": -0.25},
            "stages": [central_stage],
        }
        record = {**record_content, "record_sha256": _sha256(record_content)}
        checkpoint = append_promotion(
            empty_schema11_checkpoint("campaign-1", "selection-1"),
            leaf_id=leaf_id,
            queue_kind=PromotionQueueKind.RESPONSE,
            reason_code="REVIEWED_ERROR_EVIDENCE_PENDING",
            minimum_requested_tier="BF40",
            scientific_computation_identity=scientific_identity,
        )
        source_fingerprint_sha256 = checkpoint["promotion_queue"]["entries"][0][
            "source_fingerprint_sha256"
        ]
        calculation_content = {
            "schema": "windows-solver.promoted-calculation-stage/1",
            "queue_ordinal": 0,
            "leaf_id": leaf_id,
            "scientific_computation_identity": scientific_identity,
            "route": "EXTERIOR_BF40",
            "execution_mode": "CALCULATE_ONLY",
            "admission_state": "AWAITING_ADMISSION",
            "layer1_lock_receipt_sha256": "e" * 64,
            "source_fingerprint_sha256": source_fingerprint_sha256,
            "calibration_receipt_sha256": calibration_receipt_sha256,
            "precision_tiers": ["BF40"],
            "current_run_disagreement_terms": [
                {"delta_same_point": "0.1", "delta_cross_precision": "0.2"}
            ],
            "retained_record": record,
            "retained_record_stage_sha256": central_stage["stage_sha256"],
            "receipts": [],
        }
        calculation = {
            **calculation_content,
            "stage_sha256": _sha256(calculation_content),
        }
        checkpoint = retain_promoted_calculation(
            checkpoint,
            queue_ordinal=0,
            promoted_stage=calculation,
            execution_mode="CALCULATE_ONLY",
            disposition_receipt={
                "schema": "windows-solver.promoted-admission-pending/1"
            },
        )
        checkpoint = record_survey_disposition(
            checkpoint,
            survey_pass=SurveyPass.PROMOTED,
            leaf_id=leaf_id,
            disposition=SurveyDisposition.CALCULATED_AWAITING_ADMISSION,
            operation_identity="promoted-fixed-root-survey/v1",
            precision_tiers=("BF40",),
            reason_code="AWAITING_INDEPENDENT_REVIEW_ADMISSION",
            sample_count=9,
            sample_limit=9,
            root_read_count=0,
            root_read_limit=0,
            worker_launch_count=1,
            worker_launch_limit=2,
            tier_timing=(),
            session_fragments=(),
        )
        review_content = {
            "schema": "windows-solver.independent-promoted-review-receipt/1",
            "decision": "ADMIT_SCREENED",
            "authority_sha256": authority_sha256,
            "reviewed_at_utc": "2026-08-26T00:00:00Z",
            "binary64_lock_receipt_sha256": calculation_content[
                "layer1_lock_receipt_sha256"
            ],
            "calibration_receipt_sha256": calibration_receipt_sha256,
            "queue_ordinal": 0,
            "leaf_id": leaf_id,
            "route": "EXTERIOR_BF40",
            "scientific_computation_identity": scientific_identity,
            "retained_promoted_stage_sha256": calculation["stage_sha256"],
            "source_fingerprint_sha256": source_fingerprint_sha256,
            "disagreement_term_sha256s": [
                _sha256(calculation_content["current_run_disagreement_terms"][0])
            ],
        }
        review = {**review_content, "receipt_sha256": _sha256(review_content)}
        return checkpoint, calculation, review, record

    def test_review_admission_is_durable_and_performs_zero_numerical_work(self):
        calibration = load_default_calibration_receipt()
        checkpoint, calculation, review, record = self._checkpoint_and_review(
            calibration_receipt_sha256=calibration.sha256,
            authority_sha256=calibration.independent_review_authority_sha256,
        )
        published: list[dict[str, object]] = []

        def publish(value: object) -> dict[str, object]:
            record_value = dict(value)
            published.append(record_value)
            return {
                "schema": "windows-solver.test-publication-receipt/1",
                "record_sha256": record_value["record_sha256"],
            }

        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "checkpoint.json"
            path.write_bytes(canonical_json_bytes(checkpoint))
            result = admit_retained_promoted_checkpoint(
                path,
                queue_ordinal=0,
                independent_review_receipt=review,
                calibration_receipt=calibration,
                terminal_record_committed=publish,
            )

        self.assertEqual(0, result.backend_call_count)
        self.assertEqual(0, result.julia_launch_count)
        self.assertEqual(0, result.root_read_count)
        self.assertEqual(0, result.determinant_evaluation_count)
        self.assertEqual(0, result.binary64_evaluation_count)
        self.assertEqual("COMPLETED", result.checkpoint[
            "promotion_queue"
        ]["entries"][0]["disposition"])
        self.assertEqual(
            calculation,
            result.checkpoint["promoted_stage_ledger"]["0"]["leaf-1"],
        )
        self.assertEqual([record], result.checkpoint["records"])
        self.assertEqual(
            "SCREENED",
            result.checkpoint["evidence_ledger"]["leaf-1"]["evidence_level"],
        )
        self.assertEqual([record], published)

    def test_review_receipt_cannot_inject_a_terminal_record(self):
        calibration = load_default_calibration_receipt()
        checkpoint, _calculation, review, _record = self._checkpoint_and_review(
            calibration_receipt_sha256=calibration.sha256,
            authority_sha256=calibration.independent_review_authority_sha256,
        )
        injected = dict(review)
        injected["admitted_record"] = {"leaf_id": "forged"}
        content = {
            key: value for key, value in injected.items() if key != "receipt_sha256"
        }
        injected["receipt_sha256"] = _sha256(content)

        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "checkpoint.json"
            original = canonical_json_bytes(checkpoint)
            path.write_bytes(original)
            with self.assertRaisesRegex(ValueError, "review receipt fields"):
                admit_retained_promoted_checkpoint(
                    path,
                    queue_ordinal=0,
                    independent_review_receipt=injected,
                    calibration_receipt=calibration,
                )
            self.assertEqual(original, path.read_bytes())

    def test_foreign_lock_or_calibration_fails_before_mutation(self):
        calibration = load_default_calibration_receipt()
        checkpoint, _calculation, review, _record = self._checkpoint_and_review(
            calibration_receipt_sha256=calibration.sha256,
            authority_sha256=calibration.independent_review_authority_sha256,
        )
        for field in (
            "binary64_lock_receipt_sha256",
            "calibration_receipt_sha256",
        ):
            with self.subTest(field=field):
                foreign = dict(review)
                foreign[field] = "f" * 64
                content = {
                    key: value
                    for key, value in foreign.items()
                    if key != "receipt_sha256"
                }
                foreign["receipt_sha256"] = _sha256(content)

                with TemporaryDirectory() as temporary:
                    path = Path(temporary) / "checkpoint.json"
                    original = canonical_json_bytes(checkpoint)
                    path.write_bytes(original)
                    with self.assertRaisesRegex(ValueError, "binding"):
                        admit_retained_promoted_checkpoint(
                            path,
                            queue_ordinal=0,
                            independent_review_receipt=foreign,
                            calibration_receipt=calibration,
                        )
                    self.assertEqual(original, path.read_bytes())

    def test_publication_failure_leaves_admission_pending_for_retry(self):
        calibration = load_default_calibration_receipt()
        checkpoint, _calculation, review, record = self._checkpoint_and_review(
            calibration_receipt_sha256=calibration.sha256,
            authority_sha256=calibration.independent_review_authority_sha256,
        )
        published: list[dict[str, object]] = []

        def unavailable(_record: object) -> Mapping[str, object]:
            raise RuntimeError("solved-leaf store unavailable")

        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "checkpoint.json"
            path.write_bytes(canonical_json_bytes(checkpoint))
            with self.assertRaisesRegex(RuntimeError, "solved-leaf store unavailable"):
                admit_retained_promoted_checkpoint(
                    path,
                    queue_ordinal=0,
                    independent_review_receipt=review,
                    calibration_receipt=calibration,
                    terminal_record_committed=unavailable,
                )
            durable = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                "ADMITTED_PENDING_PUBLICATION",
                durable["promotion_queue"]["entries"][0]["disposition"],
            )
            self.assertEqual([record], durable["records"])
            self.assertEqual(
                "SCREENED", durable["evidence_ledger"]["leaf-1"]["evidence_level"]
            )
            def publish(value: object) -> dict[str, object]:
                record_value = dict(value)
                published.append(record_value)
                return {
                    "schema": "windows-solver.test-publication-receipt/1",
                    "record_sha256": record_value["record_sha256"],
                }

            retried = admit_retained_promoted_checkpoint(
                path,
                queue_ordinal=0,
                independent_review_receipt=review,
                calibration_receipt=calibration,
                terminal_record_committed=publish,
            )

        self.assertEqual("COMPLETED", retried.checkpoint[
            "promotion_queue"
        ]["entries"][0]["disposition"])
        self.assertEqual([record], published)

    def test_checkpoint_interruption_retries_through_idempotent_publication(self):
        calibration = load_default_calibration_receipt()
        checkpoint, _calculation, review, record = self._checkpoint_and_review(
            calibration_receipt_sha256=calibration.sha256,
            authority_sha256=calibration.independent_review_authority_sha256,
        )
        published: list[dict[str, object]] = []

        def publish_if_missing(value: object) -> dict[str, object]:
            candidate = dict(value)
            if published and canonical_json_bytes(published[0]) != canonical_json_bytes(
                candidate
            ):
                self.fail("retry tried to publish different solved-leaf evidence")
            if not published:
                published.append(candidate)
            return {
                "schema": "windows-solver.test-publication-receipt/1",
                "record_sha256": candidate["record_sha256"],
            }

        original_write = promoted_admission._write_atomic
        attempts = 0

        def interrupt_once(path: Path, candidate: object) -> None:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise OSError("simulated checkpoint interruption")
            original_write(path, candidate)

        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "checkpoint.json"
            path.write_bytes(canonical_json_bytes(checkpoint))
            with patch.object(
                promoted_admission, "_write_atomic", side_effect=interrupt_once
            ):
                with self.assertRaisesRegex(OSError, "checkpoint interruption"):
                    admit_retained_promoted_checkpoint(
                        path,
                        queue_ordinal=0,
                        independent_review_receipt=review,
                        calibration_receipt=calibration,
                        terminal_record_committed=publish_if_missing,
                    )
                pending = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(
                    "AWAITING_ADMISSION",
                    pending["promotion_queue"]["entries"][0]["disposition"],
                )
                self.assertEqual([], published)
                result = admit_retained_promoted_checkpoint(
                    path,
                    queue_ordinal=0,
                    independent_review_receipt=review,
                    calibration_receipt=calibration,
                    terminal_record_committed=publish_if_missing,
                )

        # First admission write is interrupted; retry then writes the durable
        # admission and the publication-completion checkpoint separately.
        self.assertEqual(3, attempts)
        self.assertEqual([record], published)
        self.assertEqual(
            "COMPLETED",
            result.checkpoint["promotion_queue"]["entries"][0]["disposition"],
        )

    def test_review_authority_is_pinned_to_the_calibration_receipt(self):
        calibration = load_default_calibration_receipt()
        checkpoint, _calculation, review, _record = self._checkpoint_and_review(
            calibration_receipt_sha256=calibration.sha256,
            authority_sha256="d" * 64,
        )

        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "checkpoint.json"
            path.write_bytes(canonical_json_bytes(checkpoint))
            with self.assertRaisesRegex(ValueError, "authentication"):
                admit_retained_promoted_checkpoint(
                    path,
                    queue_ordinal=0,
                    independent_review_receipt=review,
                    calibration_receipt=calibration,
                )

    def test_solver_reduces_a_retained_exterior_batch_without_new_numerics(self):
        calibration = load_default_calibration_receipt()
        plan = build_campaign_plan(
            policy=NumericalPolicy(),
            backend_identity=VettedNativeDeterminantKernel.identity,
            precision_capabilities=PrecisionCapabilities((64, 80)),
        )
        leaf = next(
            item for item in plan.leaves
            if item.mechanism_id != "horizon-admittance"
        )
        seal = AuthenticatedRootSeal(
            leaf.job.root.omega,
            leaf.job.root.branch_id,
            "a" * 64,
        )
        raw_error = {
            "schema": "windows-solver.exterior-determinant-error-evidence/1",
            "error_model_id": "retained-test-model/v1",
            "delta_same_point": "1e-12",
            "delta_cross_precision": "1e-12",
            "delta_endpoint_series": "1e-12",
            "safety_factor": str(calibration.certificate_safety_factor),
            "numerical_error_abs": str(
                Decimal(calibration.certificate_safety_factor) * Decimal("1e-12")
            ),
        }
        full_batch = _batch(leaf, seal, 40)
        full_batch = replace(
            full_batch,
            samples=tuple(
                replace(
                    sample,
                    determinant_error_evidence=ExteriorDeterminantErrorEvidence(
                        raw_error
                    ),
                )
                for sample in full_batch.samples
            ),
        )
        background_contract = fixed_root_survey_request_contract(
            FixedRootSurveyPlan.CANONICAL_BACKGROUND_FIVE
        )
        component_contract = fixed_root_survey_request_contract(
            FixedRootSurveyPlan.MECHANISM_COMPONENT_FOUR
        )
        background_batch = replace(
            full_batch,
            scientific_operation_identity=(
                background_contract.scientific_operation_identity
            ),
            request_sha256="1" * 64,
            samples=tuple(
                sample
                for sample in full_batch.samples
                if sample.role in background_contract.sample_roles
            ),
        )
        component_batch = replace(
            full_batch,
            scientific_operation_identity=(
                component_contract.scientific_operation_identity
            ),
            request_sha256="2" * 64,
            samples=tuple(
                sample
                for sample in full_batch.samples
                if sample.role in component_contract.sample_roles
            ),
        )
        cache_key, reuse_key = _promoted_background_key(leaf, seal, 40)
        background_receipt = _promoted_background_receipt(
            batch=background_batch,
            cache_key_sha256=cache_key,
            reuse_key=reuse_key,
            source_queue_ordinal=0,
            source_leaf_id=leaf.leaf_id,
        )
        calculation = PromotedExteriorCalculationResult(
            component_batch=component_batch,
            background=PromotedBackgroundBinding(
                background_receipt_sha256=str(
                    background_receipt["receipt_sha256"]
                ),
                background_worker_request_sha256=(
                    background_batch.request_sha256
                ),
                background_sha256=str(background_receipt["background_sha256"]),
                background_reuse_key_sha256=cache_key,
            ),
        )
        retained_stage = {
            "route": "EXTERIOR_BF40",
            "source_root_seal_sha256": seal.root_seal_sha256,
            "precision_tiers": ["BF40"],
            "calculation_artifact": calculation.to_mapping(),
        }
        checkpoint = {
            "promoted_background_ledger": {
                "0": {
                    leaf.leaf_id: {
                        "payload": {
                            "background_receipts": [background_receipt]
                        }
                    }
                }
            }
        }
        reduction = _reduce_retained_exterior_for_admission(
            plan,
            leaf,
            checkpoint,
            retained_stage,
            {"receipt_sha256": "b" * 64},
            calibration,
            queue_ordinal=0,
        )

        self.assertEqual(9, len(reduction.evidence_receipts))
        self.assertEqual(leaf.leaf_id, reduction.record["leaf_id"])
        self.assertEqual("PRODUCED", reduction.record["state"])
        self.assertEqual("BF40", reduction.record["stages"][0]["precision_tier"])

    def test_review_receipt_tampering_fails_before_admission(self):
        calibration = load_default_calibration_receipt()
        checkpoint, _calculation, review, _record = self._checkpoint_and_review(
            calibration_receipt_sha256=calibration.sha256,
            authority_sha256=calibration.independent_review_authority_sha256,
        )
        review["route"] = "HORIZON_BF80"

        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "checkpoint.json"
            path.write_bytes(canonical_json_bytes(checkpoint))
            with self.assertRaisesRegex(ValueError, "review receipt"):
                admit_retained_promoted_checkpoint(
                    path,
                    queue_ordinal=0,
                    independent_review_receipt=review,
                    calibration_receipt=calibration,
                )


if __name__ == "__main__":
    unittest.main()
