from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from windows_solver.campaign_recovery import (
    migrate_endpoint_recovery_checkpoint_file,
    migrate_fixed_root_endpoint_policy_checkpoint,
    validate_endpoint_recovery_migration_receipt,
)
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
    promotion_source_fingerprint_sha256,
    record_evidence,
    record_survey_disposition,
    retain_promoted_calculation,
    validate_schema11_checkpoint,
)
from windows_solver.contracts import canonical_json_bytes
from windows_solver.solved_leaf_cache import SolvedLeafStore


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


def _v2_endpoint_policy() -> dict[str, object]:
    binding = {
        "schema": "windows-solver.fixed-root-endpoint-recovery-policy/1",
        "identity": (
            "cause-aware-real-inner-fixed-root-exterior-endpoint-recovery/v2"
        ),
        "endpoint_order_rule": "bounded-doubling-prefix/v1",
        "base_endpoint_order": 28,
        "generated_maximum_order": 112,
        "endpoint_order_schedule": [28, 56, 112],
        "horizon_geometry_rule": "bounded-real-inner-tortoise-depth/v1",
        "horizon_geometry_schedule": [
            "-10", "-25", "-50", "-75", "-100", "-150", "-225",
            "-337.5", "-400",
        ],
        "horizon_rho_inner_min": "-400",
        "horizon_endpoint_rho_floor": "-400",
        "horizon_maximum_endpoint_distance": "0.1",
        "infinity_geometry_rule": "bounded-positive-rho-depth/v1",
        "infinity_geometry_schedule": [
            "100", "250", "500", "1000", "2000", "5000", "10000",
            "20000",
        ],
        "fixed_root_reliability_target_abs": "2e-11",
        "fixed_root_reliability_rule": (
            "minus-log10-target-plus-required-digit-guard/v1"
        ),
        "required_digit_guard": 6,
        "precision_digits": 40,
        "semantic_precision_tier": "bigfloat-40",
    }
    return {**binding, "policy_sha256": _sha256(binding)}


def _v2_promoted_stage(
    leaf_id: str,
    queue_ordinal: int,
    *,
    premature: bool,
) -> dict[str, object]:
    receipt = {
        "schema": "windows-solver.exterior-endpoint-recovery-receipt/1",
        "endpoint_branch": "infinity-outgoing",
        "recovery_policy_identity": _v2_endpoint_policy()["identity"],
        "candidate_limitation": (
            "insufficient-series-order/v1" if premature else "adequate/v1"
        ),
        "candidate_geometry_schedule": [
            "100", "250", "500", "1000", "2000", "5000", "10000",
            "20000",
        ],
        "terminal_geometry": "100",
        "attempts": [
            {
                "attempted_endpoint_order": order,
                "attempted_geometry": "100",
                "result": (
                    "ORDER_EXHAUSTED"
                    if premature and order == 112
                    else "RETRY"
                    if premature
                    else "ADEQUATE"
                ),
            }
            for order in ([28, 56, 112] if premature else [28])
        ],
    }
    content = {
        "schema": "windows-solver.promoted-calculation-stage/1",
        "leaf_id": leaf_id,
        "queue_ordinal": queue_ordinal,
        "route": "EXTERIOR_BF40",
        "execution_mode": "CALCULATE_ONLY",
        "admission_state": "AWAITING_ADMISSION",
        "precision_tiers": ["BF40"],
        "batch": {
            "schema": "windows-solver.fixed-root-survey-batch/3",
            "fixed_root_endpoint_recovery_policy": _v2_endpoint_policy(),
            "sample_count": 5,
        },
        "receipts": [receipt],
        **(
            {"failure_code": "EXTERIOR_ENDPOINT_MAXIMUM_ORDER_INADEQUATE"}
            if premature
            else {}
        ),
    }
    return {**content, "stage_sha256": _sha256(content)}


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

    def test_fixed_root_v2_stage_becomes_forensic_and_reissues_only_exterior(self) -> None:
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
            "batch": {
                "schema": "windows-solver.fixed-root-survey-batch/2",
                "sample_count": 5,
            },
            "receipts": [],
        }
        stage = {**stage_content, "stage_sha256": _sha256(stage_content)}
        checkpoint = retain_promoted_calculation(
            checkpoint,
            queue_ordinal=0,
            promoted_stage=stage,
            execution_mode="CALCULATE_ONLY",
            disposition_receipt={"schema": "admission-pending/v1"},
            promoted_background={"status": "ACQUIRED"},
            promoted_root={"root_seal_sha256": "d" * 64},
        )
        checkpoint = record_survey_disposition(
            checkpoint,
            survey_pass=SurveyPass.PROMOTED,
            leaf_id="leaf-1",
            disposition=SurveyDisposition.CALCULATED_AWAITING_ADMISSION,
            reason_code="AWAITING_INDEPENDENT_REVIEW_ADMISSION",
            **_pass_limits(),
        )

        migrated = validate_schema11_checkpoint(checkpoint)

        entry = migrated["promotion_queue"]["entries"][0]
        self.assertEqual("PENDING", entry["disposition"])
        self.assertEqual("BF40", entry["minimum_requested_tier"])
        self.assertIsNone(entry["retained_promoted_stage_sha256"])
        self.assertEqual({}, migrated["promoted_stage_ledger"])
        self.assertEqual({}, migrated["promoted_background_ledger"])
        self.assertEqual({}, migrated["survey_pass_ledger"]["promoted"])
        self.assertEqual(
            "d" * 64,
            migrated["promoted_root_ledger"]["0"]["leaf-1"]["payload"][
                "root_seal_sha256"
            ],
        )
        history = migrated["forensic_fixed_root_v2_history"]["0:leaf-1"]
        self.assertEqual("FORENSIC_ONLY", history["authority"])
        self.assertEqual(stage, history["source_stage"])

    def test_v1_endpoint_stage_migrates_forensically_with_zero_numerics(self) -> None:
        checkpoint = append_promotion(
            empty_schema11_checkpoint("campaign-1", "selection-1"),
            leaf_id="leaf-1",
            queue_kind=PromotionQueueKind.RESPONSE,
            reason_code="REVIEWED_ERROR_EVIDENCE_PENDING",
            minimum_requested_tier="BF40",
            scientific_computation_identity="b" * 64,
        )
        source_policy_binding = {
            "schema": "windows-solver.fixed-root-endpoint-recovery-policy/1",
            "identity": "cause-aware-fixed-root-exterior-endpoint-recovery/v1",
            "endpoint_order_rule": "bounded-doubling-prefix/v1",
            "base_endpoint_order": 28,
            "generated_maximum_order": 112,
            "endpoint_order_schedule": [28, 56, 112],
            "horizon_geometry_rule": "bounded-negative-rho-depth/v1",
            "horizon_geometry_schedule": ["-5000", "-10000", "-20000"],
            "infinity_geometry_rule": "bounded-positive-rho-depth/v1",
            "infinity_geometry_schedule": [
                "100", "250", "500", "1000", "2000", "5000", "10000",
                "20000",
            ],
            "fixed_root_reliability_target_abs": "2e-11",
            "fixed_root_reliability_rule": (
                "minus-log10-target-plus-required-digit-guard/v1"
            ),
            "required_digit_guard": 6,
            "precision_digits": 40,
            "semantic_precision_tier": "bigfloat-40",
        }
        source_policy = {
            **source_policy_binding,
            "policy_sha256": _sha256(source_policy_binding),
        }
        stage_content = {
            "schema": "windows-solver.promoted-calculation-stage/1",
            "leaf_id": "leaf-1",
            "queue_ordinal": 0,
            "route": "EXTERIOR_BF40",
            "execution_mode": "CALCULATE_ONLY",
            "admission_state": "AWAITING_ADMISSION",
            "precision_tiers": ["BF40"],
            "batch": {
                "schema": "windows-solver.fixed-root-survey-batch/3",
                "fixed_root_endpoint_recovery_policy": source_policy,
                "sample_count": 5,
            },
            "receipts": [{
                "schema": "windows-solver.exterior-endpoint-recovery-receipt/1",
                "reason": "EXTERIOR_ENDPOINT_GEOMETRY_EXHAUSTED",
            }],
        }
        stage = {**stage_content, "stage_sha256": _sha256(stage_content)}
        checkpoint = retain_promoted_calculation(
            checkpoint,
            queue_ordinal=0,
            promoted_stage=stage,
            execution_mode="CALCULATE_ONLY",
            disposition_receipt={"schema": "admission-pending/v1"},
            promoted_background={"status": "ACQUIRED"},
            promoted_root={"root_seal_sha256": "d" * 64},
        )
        checkpoint = record_survey_disposition(
            checkpoint,
            survey_pass=SurveyPass.PROMOTED,
            leaf_id="leaf-1",
            disposition=SurveyDisposition.CALCULATED_AWAITING_ADMISSION,
            reason_code="AWAITING_INDEPENDENT_REVIEW_ADMISSION",
            **_pass_limits(),
        )
        checkpoint["system_failures"].append({
            "failure_code": "PRESERVED_HISTORY_FIXTURE",
            "leaf_id": "unrelated-leaf",
        })
        source_entry = copy.deepcopy(
            checkpoint["promotion_queue"]["entries"][0]
        )
        source_fingerprint = promotion_source_fingerprint_sha256(source_entry)
        preserved_binary64 = copy.deepcopy(
            checkpoint["survey_pass_ledger"]["binary64"]
        )
        preserved_failures = copy.deepcopy(checkpoint["system_failures"])
        preserved_campaign = checkpoint["campaign_id"]
        preserved_selection = checkpoint["selection_id"]

        migrated = migrate_fixed_root_endpoint_policy_checkpoint(
            checkpoint,
            endpoint_recovery_migration=True,
        )

        entry = migrated["promotion_queue"]["entries"][0]
        self.assertEqual("PENDING", entry["disposition"])
        self.assertEqual("BF40", entry["minimum_requested_tier"])
        self.assertEqual(source_fingerprint, entry["source_fingerprint_sha256"])
        self.assertEqual(source_fingerprint,
            promotion_source_fingerprint_sha256(entry))
        self.assertEqual(
            source_entry["scientific_computation_identity"],
            entry["scientific_computation_identity"],
        )
        self.assertEqual(preserved_campaign, migrated["campaign_id"])
        self.assertEqual(preserved_selection, migrated["selection_id"])
        self.assertEqual(
            preserved_binary64, migrated["survey_pass_ledger"]["binary64"]
        )
        self.assertEqual(preserved_failures, migrated["system_failures"])
        self.assertIsNone(entry["retained_promoted_stage_sha256"])
        self.assertEqual({}, migrated["promoted_stage_ledger"])
        self.assertEqual({}, migrated["promoted_background_ledger"])
        self.assertEqual({}, migrated["survey_pass_ledger"]["promoted"])
        self.assertEqual(
            "d" * 64,
            migrated["promoted_root_ledger"]["0"]["leaf-1"]["payload"][
                "root_seal_sha256"
            ],
        )
        history = migrated["forensic_fixed_root_v2_history"]["0:leaf-1"]
        self.assertEqual("FORENSIC_ONLY", history["authority"])
        self.assertEqual(stage, history["source_stage"])
        self.assertEqual(
            "cause-aware-fixed-root-exterior-endpoint-recovery/v1",
            history["source_recovery_policy_identity"],
        )
        self.assertEqual(
            "cause-aware-real-inner-fixed-root-exterior-endpoint-recovery/v2",
            history["replacement_recovery_policy_identity"],
        )
        replacement = history["replacement_recovery_policy"]
        replacement_binding = {
            name: item for name, item in replacement.items()
            if name != "policy_sha256"
        }
        self.assertEqual(
            _sha256(replacement_binding),
            history["replacement_recovery_policy_sha256"],
        )
        self.assertEqual(
            history["replacement_recovery_policy_sha256"],
            replacement["policy_sha256"],
        )
        self.assertEqual(
            "bigfloat-40",
            history["replacement_recovery_policy"]["semantic_precision_tier"],
        )
        self.assertEqual(
            [
                "-10", "-25", "-50", "-75", "-100", "-150", "-225",
                "-337.5", "-400",
            ],
            history["replacement_recovery_policy"]["horizon_geometry_schedule"],
        )
        self.assertEqual(
            {
                "root_solves": 0,
                "determinant_calls": 0,
                "ode_calls": 0,
                "sample_calls": 0,
            },
            history["numerical_migration_work"],
        )

    def test_v2_false_terminal_at_queue_146_migrates_to_v3_only(self) -> None:
        checkpoint = empty_schema11_checkpoint("campaign-1", "selection-1")
        for ordinal in range(147):
            checkpoint = append_promotion(
                checkpoint,
                leaf_id=f"leaf-{ordinal}",
                queue_kind=PromotionQueueKind.RESPONSE,
                reason_code="REVIEWED_ERROR_EVIDENCE_PENDING",
                minimum_requested_tier="BF40",
                scientific_computation_identity=f"{ordinal:064x}",
            )
        leaf_id = "leaf-146"
        stage = _v2_promoted_stage(leaf_id, 146, premature=True)
        checkpoint = retain_promoted_calculation(
            checkpoint,
            queue_ordinal=146,
            promoted_stage=stage,
            execution_mode="CALCULATE_ONLY",
            disposition_receipt={"schema": "admission-pending/v1"},
            promoted_background={"status": "ACQUIRED"},
            promoted_root={"root_seal_sha256": "d" * 64},
        )

        self.assertEqual(
            _v2_promoted_stage(leaf_id, 146, premature=True),
            validate_schema11_checkpoint(checkpoint)[
                "promoted_stage_ledger"
            ]["146"][leaf_id],
        )

        migrated = migrate_fixed_root_endpoint_policy_checkpoint(
            checkpoint,
            endpoint_recovery_migration=True,
        )

        self.assertEqual(147, len(migrated["promotion_queue"]["entries"]))
        affected = migrated["promotion_queue"]["entries"][146]
        self.assertEqual(146, affected["queue_ordinal"])
        self.assertEqual(leaf_id, affected["leaf_id"])
        self.assertEqual("PENDING", affected["disposition"])
        self.assertIsNone(affected["retained_promoted_stage_sha256"])
        self.assertEqual(
            "d" * 64,
            migrated["promoted_root_ledger"]["146"][leaf_id]["payload"][
                "root_seal_sha256"
            ],
        )
        history = migrated["forensic_fixed_root_v2_history"]["146:leaf-146"]
        self.assertEqual(
            "windows-solver.fixed-root-endpoint-forensic-history/3",
            history["schema"],
        )
        self.assertEqual(stage, history["source_stage"])
        self.assertEqual([], history["source_current_records"])
        self.assertEqual([], history["source_execution_attempts"])
        self.assertIsNone(history["source_current_evidence"])
        self.assertEqual(
            "cause-aware-real-inner-order-geometry-fixed-root-exterior-endpoint-recovery/v3",
            history["replacement_recovery_policy_identity"],
        )
        self.assertEqual(
            canonical_json_bytes(migrated),
            canonical_json_bytes(
                migrate_fixed_root_endpoint_policy_checkpoint(
                    migrated,
                    endpoint_recovery_migration=True,
                )
            ),
        )

    def test_v2_adequate_stage_is_not_invalidated(self) -> None:
        checkpoint = append_promotion(
            empty_schema11_checkpoint("campaign-1", "selection-1"),
            leaf_id="leaf-1",
            queue_kind=PromotionQueueKind.RESPONSE,
            reason_code="REVIEWED_ERROR_EVIDENCE_PENDING",
            minimum_requested_tier="BF40",
            scientific_computation_identity="b" * 64,
        )
        stage = _v2_promoted_stage("leaf-1", 0, premature=False)
        checkpoint = retain_promoted_calculation(
            checkpoint,
            queue_ordinal=0,
            promoted_stage=stage,
            execution_mode="CALCULATE_ONLY",
            disposition_receipt={"schema": "admission-pending/v1"},
        )

        validated = migrate_fixed_root_endpoint_policy_checkpoint(
            checkpoint,
            endpoint_recovery_migration=True,
        )

        self.assertEqual(
            "AWAITING_ADMISSION",
            validated["promotion_queue"]["entries"][0]["disposition"],
        )
        self.assertEqual(
            stage,
            validated["promoted_stage_ledger"]["0"]["leaf-1"],
        )
        self.assertEqual({}, validated["forensic_fixed_root_v2_history"])

    def test_partial_old_policy_control_attempt_is_archived_with_stage(self) -> None:
        checkpoint = append_promotion(
            empty_schema11_checkpoint("campaign-1", "selection-1"),
            leaf_id="leaf-1",
            queue_kind=PromotionQueueKind.RESPONSE,
            reason_code="REVIEWED_ERROR_EVIDENCE_PENDING",
            minimum_requested_tier="BF40",
            scientific_computation_identity="b" * 64,
        )
        checkpoint = retain_promoted_calculation(
            checkpoint,
            queue_ordinal=0,
            promoted_stage=_v2_promoted_stage(
                "leaf-1", 0, premature=True
            ),
            execution_mode="CALCULATE_ONLY",
            disposition_receipt={"schema": "admission-pending/v1"},
        )
        partial = {
            "leaf_id": "leaf-1",
            "schema": "windows-solver.partial-promoted-control-return/1",
            "endpoint_recovery_policy_identity": _v2_endpoint_policy()[
                "identity"
            ],
            "failure_code": "EXTERIOR_ENDPOINT_MAXIMUM_ORDER_INADEQUATE",
            "terminal_geometry": "100",
            "next_state": "CONTROL_PENDING",
        }
        checkpoint["attempts"].append(partial)

        migrated = migrate_fixed_root_endpoint_policy_checkpoint(
            checkpoint,
            endpoint_recovery_migration=True,
        )

        self.assertEqual([], migrated["attempts"])
        history = migrated["forensic_fixed_root_v2_history"]["0:leaf-1"]
        self.assertEqual([partial], history["source_execution_attempts"])

    def test_endpoint_file_migration_archives_cache_and_is_idempotent(self) -> None:
        checkpoint = append_promotion(
            empty_schema11_checkpoint("campaign-1", "selection-1"),
            leaf_id="leaf-1",
            queue_kind=PromotionQueueKind.RESPONSE,
            reason_code="REVIEWED_ERROR_EVIDENCE_PENDING",
            minimum_requested_tier="BF40",
            scientific_computation_identity="b" * 64,
        )
        checkpoint = retain_promoted_calculation(
            checkpoint,
            queue_ordinal=0,
            promoted_stage=_v2_promoted_stage("leaf-1", 0, premature=True),
            execution_mode="CALCULATE_ONLY",
            disposition_receipt={"schema": "admission-pending/v1"},
            promoted_root={"root_seal_sha256": "d" * 64},
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.json"
            output = root / "output.json"
            receipt_path = root / "migration-receipt.json"
            store = SolvedLeafStore(root / "solved")
            source.write_bytes(canonical_json_bytes(checkpoint))
            record_content = {
                "leaf_id": "leaf-1",
                "state": "UNRESOLVED",
                "computed": True,
                "stages": [{"endpoint_policy": _v2_endpoint_policy()}],
            }
            record = {
                **record_content,
                "record_sha256": _sha256(record_content),
            }
            cache_path = store.publish(
                scientific_identity_sha256="b" * 64,
                leaf_id="leaf-1",
                record=record,
                source_type="originating-campaign",
            )

            migration = migrate_endpoint_recovery_checkpoint_file(
                source,
                output_path=output,
                receipt_path=receipt_path,
                binary64_lock_receipt_sha256="a" * 64,
                solved_leaf_store=store.root,
            )

            self.assertFalse(cache_path.exists())
            archived = migration["archived_solved_leaf_receipts"]
            self.assertEqual(1, len(archived))
            self.assertTrue(Path(archived[0]["forensic_path"]).is_file())
            self.assertEqual(
                {
                    "backend_constructions": 0,
                    "julia_launches": 0,
                    "determinant_evaluations": 0,
                    "root_solves": 0,
                },
                migration["numerical_work"],
            )
            self.assertEqual(
                migration,
                validate_endpoint_recovery_migration_receipt(
                    output,
                    receipt_path,
                    binary64_lock_receipt_sha256="a" * 64,
                ),
            )
            self.assertEqual(
                migration,
                migrate_endpoint_recovery_checkpoint_file(
                    source,
                    output_path=output,
                    receipt_path=receipt_path,
                    binary64_lock_receipt_sha256="a" * 64,
                    solved_leaf_store=store.root,
                ),
            )

    def test_in_place_migration_recovers_a_missing_sidecar_receipt(self) -> None:
        checkpoint = append_promotion(
            empty_schema11_checkpoint("campaign-1", "selection-1"),
            leaf_id="leaf-1",
            queue_kind=PromotionQueueKind.RESPONSE,
            reason_code="REVIEWED_ERROR_EVIDENCE_PENDING",
            minimum_requested_tier="BF40",
            scientific_computation_identity="b" * 64,
        )
        checkpoint = retain_promoted_calculation(
            checkpoint,
            queue_ordinal=0,
            promoted_stage=_v2_promoted_stage(
                "leaf-1", 0, premature=True
            ),
            execution_mode="CALCULATE_ONLY",
            disposition_receipt={"schema": "admission-pending/v1"},
        )
        with tempfile.TemporaryDirectory() as directory:
            checkpoint_path = Path(directory) / "checkpoint.json"
            receipt_path = Path(directory) / "migration.json"
            checkpoint_path.write_bytes(canonical_json_bytes(checkpoint))
            first = migrate_endpoint_recovery_checkpoint_file(
                checkpoint_path,
                output_path=checkpoint_path,
                receipt_path=receipt_path,
                binary64_lock_receipt_sha256="a" * 64,
                replace_source=True,
            )
            receipt_path.unlink()

            recovered = migrate_endpoint_recovery_checkpoint_file(
                checkpoint_path,
                output_path=checkpoint_path,
                receipt_path=receipt_path,
                binary64_lock_receipt_sha256="a" * 64,
                replace_source=True,
            )

            self.assertEqual(
                first["affected_leaf_ids"],
                recovered["affected_leaf_ids"],
            )
            self.assertEqual(
                _sha256(validate_schema11_checkpoint(
                    json.loads(checkpoint_path.read_bytes())
                )),
                recovered["output_checkpoint_sha256"],
            )

    def test_legacy_stage_cannot_smuggle_an_unknown_typed_artifact(self) -> None:
        checkpoint = append_promotion(
            empty_schema11_checkpoint("campaign-1", "selection-1"),
            leaf_id="leaf-1",
            queue_kind=PromotionQueueKind.RESPONSE,
            reason_code="REVIEWED_ERROR_EVIDENCE_PENDING",
            minimum_requested_tier="BF40",
            scientific_computation_identity="b" * 64,
        )
        artifact_content = {
            "schema": "windows-solver.mistyped-control/999",
        }
        artifact = {
            **artifact_content,
            "calculation_sha256": _sha256(artifact_content),
        }
        stage_content = {
            "schema": "windows-solver.promoted-calculation-stage/1",
            "leaf_id": "leaf-1",
            "queue_ordinal": 0,
            "route": "EXTERIOR_BF40",
            "execution_mode": "CALCULATE_ONLY",
            "admission_state": "AWAITING_ADMISSION",
            "precision_tiers": ["BF40"],
            "batch": {"sample_count": 18},
            "receipts": [],
            "calculation_artifact": artifact,
        }
        stage = {**stage_content, "stage_sha256": _sha256(stage_content)}

        with self.assertRaisesRegex(
            ValueError,
            "legacy promoted stage cannot carry a typed artifact",
        ):
            retain_promoted_calculation(
                checkpoint,
                queue_ordinal=0,
                promoted_stage=stage,
                execution_mode="CALCULATE_ONLY",
                disposition_receipt={
                    "schema": "windows-solver.promoted-admission-pending/1"
                },
            )


if __name__ == "__main__":
    unittest.main()
