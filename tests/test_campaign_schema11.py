from __future__ import annotations

import copy
import hashlib
import unittest

from windows_solver.campaign_policy import (
    EvidenceLevel,
    PromotionQueueDisposition,
    PromotionQueueKind,
    SurveyDisposition,
    SurveyPass,
    add_numerical_record,
    append_promotion,
    empty_schema11_checkpoint,
    finish_promotion,
    record_evidence,
    record_survey_disposition,
    retain_promoted_calculation,
    validate_schema11_checkpoint,
)
from windows_solver.contracts import canonical_json_bytes


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _record(leaf_id: str = "leaf-1", state: str = "PRODUCED") -> dict[str, object]:
    content: dict[str, object] = {
        "leaf_id": leaf_id,
        "state": state,
        "retained_centre": {"real": 1.25, "imag": -0.125},
        "stages": [{"stage_sha256": "a" * 64}],
    }
    return {
        **content,
        "record_sha256": hashlib.sha256(canonical_json_bytes(content)).hexdigest(),
    }


def _pass_limits() -> dict[str, object]:
    return {
        "operation_identity": "fixed-root-survey/v1",
        "precision_tiers": ["binary64"],
        "sample_count": 5,
        "sample_limit": 9,
        "root_read_count": 0,
        "root_read_limit": 0,
        "worker_launch_count": 0,
        "worker_launch_limit": 0,
        "tier_timing": [],
        "session_fragments": [],
    }
class Schema11CheckpointTests(unittest.TestCase):
    def test_empty_checkpoint_has_separate_state_ledgers(self) -> None:
        checkpoint = empty_schema11_checkpoint("campaign-1", "selection-1")

        self.assertEqual(11, checkpoint["schema_version"])
        self.assertEqual("PARTIAL", checkpoint["state"])
        self.assertEqual([], checkpoint["records"])
        self.assertEqual({}, checkpoint["evidence_ledger"])
        self.assertEqual(
            {"binary64": {}, "promoted": {}}, checkpoint["survey_pass_ledger"]
        )
        self.assertEqual(
            {
                "schema": "windows-solver.m02-promotion-queue/1",
                "entries": [],
            },
            checkpoint["promotion_queue"],
        )
        self.assertEqual({}, checkpoint["promoted_stage_ledger"])
        self.assertEqual({}, checkpoint["promoted_background_ledger"])
        self.assertEqual({}, checkpoint["promoted_root_ledger"])
        self.assertEqual([], checkpoint["attempts"])
        self.assertEqual([], checkpoint["system_failures"])
        self.assertEqual([], checkpoint["recovery_receipts"])
        self.assertIsNone(checkpoint["report_status_receipt"])
        validate_schema11_checkpoint(checkpoint)

    def test_evidence_and_pass_updates_do_not_change_numerical_record(self) -> None:
        original = _record()
        checkpoint = add_numerical_record(
            empty_schema11_checkpoint("campaign-1", "selection-1"), original
        )
        record_before = canonical_json_bytes(checkpoint["records"][0])

        checkpoint = record_evidence(
            checkpoint,
            leaf_id="leaf-1",
            central_record_sha256=original["record_sha256"],
            central_stage_sha256="a" * 64,
            evidence_level=EvidenceLevel.SCREENED,
            receipts=[{"schema": "screening/v1"}],
        )
        checkpoint = record_survey_disposition(
            checkpoint,
            survey_pass=SurveyPass.BINARY64,
            leaf_id="leaf-1",
            disposition=SurveyDisposition.COMPLETED,
            result_record_sha256=original["record_sha256"],
            reason_code="BOUNDED_RESPONSE",
            **_pass_limits(),
        )

        self.assertEqual(record_before, canonical_json_bytes(checkpoint["records"][0]))
        self.assertEqual(original["record_sha256"], checkpoint["records"][0]["record_sha256"])
        validate_schema11_checkpoint(checkpoint)

    def test_evidence_strengthening_rejects_unauthenticated_labels(self) -> None:
        record = _record()
        checkpoint = add_numerical_record(
            empty_schema11_checkpoint("campaign-1", "selection-1"), record
        )
        checkpoint = record_evidence(
            checkpoint,
            leaf_id="leaf-1",
            central_record_sha256=record["record_sha256"],
            central_stage_sha256="a" * 64,
            evidence_level=EvidenceLevel.SCREENED,
            receipts=[{"schema": "screening/v1"}],
        )
        with self.assertRaisesRegex(
            ValueError, "authenticated certification disposition"
        ):
            record_evidence(
                checkpoint,
                leaf_id="leaf-1",
                central_record_sha256=record["record_sha256"],
                central_stage_sha256="a" * 64,
                evidence_level=EvidenceLevel.CERTIFIED,
                receipts=[{"schema": "certification/v1"}],
            )

    def test_failed_is_not_a_schema11_numerical_state(self) -> None:
        with self.assertRaisesRegex(ValueError, "FAILED"):
            add_numerical_record(
                empty_schema11_checkpoint("campaign-1", "selection-1"),
                _record(state="FAILED"),
            )

    def test_pass_dispositions_keep_pending_unresolved_and_deferred_distinct(self) -> None:
        checkpoint = empty_schema11_checkpoint("campaign-1", "selection-1")
        for index, disposition in enumerate(
            (
                SurveyDisposition.PROMOTION_PENDING_ROOT,
                SurveyDisposition.UNRESOLVED,
                SurveyDisposition.DEFERRED,
            ),
            start=1,
        ):
            checkpoint = record_survey_disposition(
                checkpoint,
                survey_pass=SurveyPass.BINARY64,
                leaf_id=f"leaf-{index}",
                disposition=disposition,
                reason_code=disposition.value,
                **_pass_limits(),
            )

        ledger = checkpoint["survey_pass_ledger"]["binary64"]
        self.assertEqual("PROMOTION_PENDING_ROOT", ledger["leaf-1"]["disposition"])
        self.assertEqual("UNRESOLVED", ledger["leaf-2"]["disposition"])
        self.assertEqual("DEFERRED", ledger["leaf-3"]["disposition"])

        with self.assertRaisesRegex(ValueError, "promoted pass"):
            record_survey_disposition(
                checkpoint,
                survey_pass=SurveyPass.PROMOTED,
                leaf_id="leaf-4",
                disposition=SurveyDisposition.PROMOTION_PENDING_RESPONSE,
                reason_code="NEEDS_MORE_WORK",
                **_pass_limits(),
            )

    def test_promotion_queue_keeps_entry_when_it_finishes(self) -> None:
        checkpoint = append_promotion(
            empty_schema11_checkpoint("campaign-1", "selection-1"),
            leaf_id="leaf-1",
            queue_kind=PromotionQueueKind.ROOT,
            reason_code="ROOT_PRECISION_INSUFFICIENT",
            minimum_requested_tier="BF40",
            scientific_computation_identity="b" * 64,
        )
        original = dict(checkpoint["promotion_queue"]["entries"][0])

        checkpoint = finish_promotion(
            checkpoint,
            queue_ordinal=0,
            disposition=PromotionQueueDisposition.COMPLETED,
            disposition_receipt={"schema": "promotion-disposition/v1"},
        )

        entries = checkpoint["promotion_queue"]["entries"]
        self.assertEqual(1, len(entries))
        self.assertEqual(0, entries[0]["queue_ordinal"])
        self.assertEqual("COMPLETED", entries[0]["disposition"])
        self.assertEqual(
            original["scientific_computation_identity"],
            entries[0]["scientific_computation_identity"],
        )
        self.assertIn("disposition_receipt_sha256", entries[0])
        validate_schema11_checkpoint(checkpoint)

    def test_calculated_promotion_is_retained_while_admission_is_pending(self) -> None:
        checkpoint = append_promotion(
            empty_schema11_checkpoint("campaign-1", "selection-1"),
            leaf_id="leaf-1",
            queue_kind=PromotionQueueKind.RESPONSE,
            reason_code="REVIEWED_ERROR_EVIDENCE_PENDING",
            minimum_requested_tier="BF40",
            scientific_computation_identity="b" * 64,
        )
        stage_content = {
            "schema": "windows-solver.promoted-calculation-stage/1",
            "leaf_id": "leaf-1",
            "queue_ordinal": 0,
            "route": "EXTERIOR_BF40",
            "execution_mode": "CALCULATE_ONLY",
            "admission_state": "AWAITING_ADMISSION",
            "precision_tiers": ["BF40"],
            "batch": {"sample_count": 18},
            "receipts": [{"schema": "windows-solver.test-comparison/1"}],
        }
        stage = {**stage_content, "stage_sha256": _sha256(stage_content)}

        checkpoint = retain_promoted_calculation(
            checkpoint,
            queue_ordinal=0,
            promoted_stage=stage,
            execution_mode="CALCULATE_ONLY",
            disposition_receipt={
                "schema": "windows-solver.promoted-admission-pending/1"
            },
            promoted_background={
                "schema": "windows-solver.test-promoted-background/1",
                "reuse_key_sha256": "c" * 64,
                "status": "ACQUIRED",
            },
            promoted_root={
                "schema": "windows-solver.test-promoted-root/1",
                "root_seal_sha256": "d" * 64,
            },
        )
        checkpoint = record_survey_disposition(
            checkpoint,
            survey_pass=SurveyPass.PROMOTED,
            leaf_id="leaf-1",
            disposition=SurveyDisposition.CALCULATED_AWAITING_ADMISSION,
            reason_code="AWAITING_INDEPENDENT_REVIEW_ADMISSION",
            **_pass_limits(),
        )

        entry = checkpoint["promotion_queue"]["entries"][0]
        self.assertEqual("AWAITING_ADMISSION", entry["disposition"])
        self.assertEqual(stage["stage_sha256"], entry["retained_promoted_stage_sha256"])
        self.assertNotIn("retained_promoted_stage", entry)
        self.assertEqual(
            stage,
            checkpoint["promoted_stage_ledger"]["0"]["leaf-1"],
        )
        background_entry = checkpoint["promoted_background_ledger"]["0"][
            "leaf-1"
        ]
        root_entry = checkpoint["promoted_root_ledger"]["0"]["leaf-1"]
        self.assertEqual("ACQUIRED", background_entry["payload"]["status"])
        self.assertEqual("d" * 64, root_entry["payload"]["root_seal_sha256"])
        self.assertEqual({}, checkpoint["evidence_ledger"])
        self.assertEqual([], checkpoint["records"])
        self.assertEqual(
            "CALCULATED_AWAITING_ADMISSION",
            checkpoint["survey_pass_ledger"]["promoted"]["leaf-1"]["disposition"],
        )
        validate_schema11_checkpoint(checkpoint)

        corrupted = copy.deepcopy(checkpoint)
        corrupted["promoted_stage_ledger"]["0"]["leaf-1"]["batch"][
            "sample_count"
        ] = 17
        with self.assertRaisesRegex(ValueError, "retained promoted stage"):
            validate_schema11_checkpoint(corrupted)


if __name__ == "__main__":
    unittest.main()
