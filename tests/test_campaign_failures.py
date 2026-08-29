from __future__ import annotations

from pathlib import Path
import unittest

from windows_solver.campaign_failures import (
    CampaignSystemFailure,
    FailureDisposition,
    FailureReport,
    classify_failure,
    decision_from_control_transition,
    decision_from_survey_disposition,
    require_system_failures_resolved_for_binary64_resume,
    reviewed_screening_promotion_queue,
    resolve_layer1_system_failure_for_resume,
    run_guarded_pass,
)
from windows_solver.campaign_policy import PromotionQueueKind, empty_schema11_checkpoint
from windows_solver.operation_control import PROMOTED_CONTROL_TRANSITIONS


def _report(code: str, *, cause_type: str = "NumericalControlError") -> FailureReport:
    return FailureReport(
        failure_code=code,
        failure_class="NUMERICAL_CONTROL",
        stage="fixed-root-response",
        worker_operation="fixed-root-survey-batch",
        request_schema="fixed-root-survey-batch/v1",
        backend_identity="a" * 64,
        policy_identity="b" * 64,
        precision_tier="BF40",
        cause_type=cause_type,
        diagnostics={"schema": "numerical-control-diagnostic/v1", "complete": True},
    )


class MethodError(RuntimeError):
    pass


class CampaignFailureTests(unittest.TestCase):
    def test_prelock_system_failure_can_resume_preserved_binary64_work(self) -> None:
        checkpoint = empty_schema11_checkpoint("campaign", "selection")
        persisted = []

        with self.assertRaises(CampaignSystemFailure) as raised:
            run_guarded_pass(
                ("leaf-1",),
                checkpoint=checkpoint,
                execute_leaf=lambda _leaf_id: (_ for _ in ()).throw(
                    MethodError("stale cache contract")
                ),
                commit_leaf_outcome=lambda _leaf_id, _outcome: None,
                persist_checkpoint=lambda value: persisted.append(value),
            )
        failed = raised.exception.checkpoint
        failure_sha256 = raised.exception.receipt["receipt_sha256"]
        with self.assertRaisesRegex(ValueError, "binary64 resume is blocked"):
            require_system_failures_resolved_for_binary64_resume(failed)

        resolved, receipt = resolve_layer1_system_failure_for_resume(
            failed,
            system_failure_receipt_sha256=failure_sha256,
            repair_commit_sha="d" * 40,
            reason="version the successful root-readout cache contract",
            resolved_at_utc="2026-08-29T00:00:00Z",
        )

        self.assertEqual(
            receipt["resolution_scope"],
            "RESUME_UNRETAINED_LAYER1_WORK_ONLY",
        )
        self.assertIsNone(
            resolved["survey_pass_ledger"]["binary64"].get("leaf-1")
        )
        self.assertEqual(resolved["system_failures"], failed["system_failures"])
        self.assertEqual(
            require_system_failures_resolved_for_binary64_resume(resolved),
            (receipt,),
        )

    def test_reviewed_screening_reasons_are_closed_and_bind_queue_kind(self) -> None:
        expected = {
            "EXTERIOR_ENDPOINT_ARITHMETIC_INADEQUATE": "RESPONSE",
            "HORIZON_ARITHMETIC_INADEQUATE": "RESPONSE",
            "ROOT_UNCERTAINTY_EVIDENCE_UNAVAILABLE": "ROOT",
            "FINITE_DIFFERENCE_NOISE_LIMIT": "RESPONSE",
            "DETERMINANT_ERROR_EVIDENCE_UNAVAILABLE": "RESPONSE",
            "BLOCKED_BY_REVIEWED_ERROR_EVIDENCE": "RESPONSE",
            "DETERMINANT_UNCERTAINTY_TOO_LARGE": "ROOT",
            "ROOT_SEAL_UNAVAILABLE": "ROOT",
        }
        self.assertEqual(
            expected,
            {
                code: reviewed_screening_promotion_queue(code)
                for code in expected
            },
        )
        for code, queue_kind in expected.items():
            decision = classify_failure(_report(code))
            self.assertIs(FailureDisposition.PROMOTION_PENDING, decision.disposition)
            self.assertEqual(queue_kind, decision.queue_kind)

        root_pending = classify_failure(_report("ROOT_SEAL_UNAVAILABLE"))
        self.assertEqual(PromotionQueueKind.ROOT.value, root_pending.queue_kind)
        self.assertIs(FailureDisposition.PROMOTION_PENDING, root_pending.disposition)

        decision = classify_failure(_report("ODE_RESOURCE_LIMIT"))
        self.assertIs(FailureDisposition.DEFERRED, decision.disposition)
        self.assertIsNone(decision.queue_kind)

    def test_raw_control_report_cannot_use_screening_authority(self) -> None:
        report = _report("INSUFFICIENT_ASYMPTOTIC_PRECISION")
        raw_control = FailureReport(
            failure_code=report.failure_code,
            failure_class="CONTROL",
            stage=report.stage,
            worker_operation=report.worker_operation,
            request_schema=report.request_schema,
            backend_identity=report.backend_identity,
            policy_identity=report.policy_identity,
            precision_tier=report.precision_tier,
            cause_type=report.cause_type,
            diagnostics={"complete": True},
        )

        decision = classify_failure(raw_control)

        self.assertIs(FailureDisposition.SYSTEM_FAILURE, decision.disposition)
        self.assertIsNone(decision.queue_kind)

        raw_promoted = FailureReport(
            failure_code="EXTERIOR_ENDPOINT_ARITHMETIC_INADEQUATE",
            failure_class="PROMOTED_SURVEY_DISPOSITION",
            stage=report.stage,
            worker_operation=report.worker_operation,
            request_schema=report.request_schema,
            backend_identity=report.backend_identity,
            policy_identity=report.policy_identity,
            precision_tier=report.precision_tier,
            cause_type=report.cause_type,
            diagnostics={"complete": True},
        )
        self.assertIs(
            FailureDisposition.SYSTEM_FAILURE,
            classify_failure(raw_promoted).disposition,
        )

    def test_reporting_consumes_canonical_control_transition(self) -> None:
        transition = next(
            item
            for item in PROMOTED_CONTROL_TRANSITIONS.values()
            if item.failure_code == "EXTERIOR_ENDPOINT_ARITHMETIC_INADEQUATE"
            and item.current_tier == "BF40"
        )
        decision = decision_from_control_transition(
            _report(transition.failure_code), transition
        )

        self.assertIs(FailureDisposition.PROMOTION_PENDING, decision.disposition)
        self.assertEqual("RESPONSE", decision.queue_kind)
        self.assertEqual("BF80", decision.next_precision_tier)

        unresolved = decision_from_survey_disposition(
            _report("operator-visible-reason"), "UNRESOLVED"
        )
        self.assertIs(FailureDisposition.UNRESOLVED, unresolved.disposition)

    def test_unknown_code_and_untyped_inner_cause_are_system_failures(self) -> None:
        unknown = classify_failure(_report("NEW_UNKNOWN_CODE"))
        wrapped_method_error = classify_failure(
            _report(
                "HORIZON_ARITHMETIC_INADEQUATE",
                cause_type="MethodError",
            )
        )

        self.assertIs(FailureDisposition.SYSTEM_FAILURE, unknown.disposition)
        self.assertIs(
            FailureDisposition.SYSTEM_FAILURE,
            wrapped_method_error.disposition,
        )

    def test_method_error_aborts_before_next_leaf_without_failed_record(self) -> None:
        checkpoint = empty_schema11_checkpoint("campaign-1", "selection-1")
        started: list[str] = []
        persisted: list[dict[str, object]] = []

        def execute(leaf_id: str):
            started.append(leaf_id)
            raise MethodError("no method matching precision context")

        with self.assertRaises(CampaignSystemFailure):
            run_guarded_pass(
                ("leaf-1", "leaf-2"),
                checkpoint=checkpoint,
                execute_leaf=execute,
                commit_leaf_outcome=lambda _leaf, _outcome: self.fail(
                    "unexpected terminal outcome"
                ),
                persist_checkpoint=lambda value: persisted.append(value),
            )

        self.assertEqual(["leaf-1"], started)
        self.assertEqual(1, len(persisted))
        durable = persisted[0]
        self.assertEqual([], durable["records"])
        self.assertEqual(1, len(durable["system_failures"]))
        self.assertEqual("MethodError", durable["system_failures"][0]["cause_type"])
        self.assertNotIn("FAILED", str(durable))

    def test_repeated_leaf_local_fingerprint_is_advisory_and_third_leaf_starts(self) -> None:
        checkpoint = empty_schema11_checkpoint("campaign-1", "selection-1")
        started: list[str] = []
        committed: list[tuple[str, FailureDisposition]] = []
        persisted: list[dict[str, object]] = []

        def execute(leaf_id: str):
            started.append(leaf_id)
            return _report("ODE_RESOURCE_LIMIT")

        run_guarded_pass(
            ("leaf-1", "leaf-2", "leaf-3"),
            checkpoint=checkpoint,
            execute_leaf=execute,
            commit_leaf_outcome=lambda leaf, outcome: committed.append(
                (leaf, outcome.disposition)
            ),
            persist_checkpoint=lambda value: persisted.append(value),
        )

        self.assertEqual(["leaf-1", "leaf-2", "leaf-3"], started)
        self.assertEqual(
            [
                ("leaf-1", FailureDisposition.DEFERRED),
                ("leaf-2", FailureDisposition.DEFERRED),
                ("leaf-3", FailureDisposition.DEFERRED),
            ],
            committed,
        )
        self.assertEqual([], persisted[-1]["system_failures"])
        self.assertNotIn("FAILED", str(persisted[-1]))

    def test_classified_system_failure_aborts_on_first_outcome(self) -> None:
        checkpoint = empty_schema11_checkpoint("campaign-1", "selection-1")
        started: list[str] = []
        persisted: list[dict[str, object]] = []

        with self.assertRaises(CampaignSystemFailure):
            run_guarded_pass(
                ("leaf-1", "leaf-2"),
                checkpoint=checkpoint,
                execute_leaf=lambda leaf_id: (
                    started.append(leaf_id) or _report("NEW_UNKNOWN_CODE")
                ),
                commit_leaf_outcome=lambda _leaf, _outcome: self.fail(
                    "system failure must not commit an ordinary outcome"
                ),
                persist_checkpoint=lambda value: persisted.append(value),
            )

        self.assertEqual(["leaf-1"], started)
        self.assertEqual(1, len(persisted))
        self.assertEqual(1, len(persisted[0]["system_failures"]))

    def test_static_guard_has_no_before_leaf_repetition_abort(self) -> None:
        failures_source = (
            Path(__file__).parents[1]
            / "src"
            / "windows_solver"
            / "campaign_failures.py"
        ).read_text(encoding="utf-8")
        survey_source = (
            Path(__file__).parents[1]
            / "src"
            / "windows_solver"
            / "campaign_survey.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn("abort_before_leaf", failures_source)
        self.assertNotIn("abort_before_leaf", survey_source)
        self.assertNotIn("REPEATED_LEAF_FAILURE_FINGERPRINT", failures_source)
        self.assertIn("def observe_system_failure", failures_source)
        self.assertIn("def observe_leaf_outcome", failures_source)

    def test_operator_interrupt_is_not_relabelled_as_system_failure(self) -> None:
        persisted: list[dict[str, object]] = []
        with self.assertRaises(KeyboardInterrupt):
            run_guarded_pass(
                ("leaf-1",),
                checkpoint=empty_schema11_checkpoint(
                    "campaign-1", "selection-1"
                ),
                execute_leaf=lambda _leaf: (_ for _ in ()).throw(
                    KeyboardInterrupt()
                ),
                commit_leaf_outcome=lambda _leaf, _outcome: None,
                persist_checkpoint=lambda value: persisted.append(value),
            )

        self.assertEqual([], persisted)


if __name__ == "__main__":
    unittest.main()
