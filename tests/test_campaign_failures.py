from __future__ import annotations

import unittest

from windows_solver.campaign_failures import (
    CampaignSystemFailure,
    FailureDisposition,
    FailureReport,
    PROMOTION_ALLOWLIST,
    classify_failure,
    run_guarded_pass,
)
from windows_solver.campaign_policy import empty_schema11_checkpoint


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
    def test_promotion_allowlist_is_closed_and_binds_queue_kind(self) -> None:
        self.assertEqual(
            {
                "INSUFFICIENT_ASYMPTOTIC_PRECISION": "RESPONSE",
                "HORIZON_ARITHMETIC_INADEQUATE": "RESPONSE",
                "FINITE_DIFFERENCE_NOISE_LIMIT": "RESPONSE",
                "DETERMINANT_UNCERTAINTY_TOO_LARGE": "ROOT",
            },
            PROMOTION_ALLOWLIST,
        )
        for code, queue_kind in PROMOTION_ALLOWLIST.items():
            decision = classify_failure(_report(code))
            self.assertIs(FailureDisposition.PROMOTION_PENDING, decision.disposition)
            self.assertEqual(queue_kind, decision.queue_kind)

        decision = classify_failure(_report("ODE_RESOURCE_LIMIT"))
        self.assertIs(FailureDisposition.DEFERRED, decision.disposition)
        self.assertIsNone(decision.queue_kind)

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

    def test_same_leaf_local_fingerprint_twice_aborts_before_third_leaf(self) -> None:
        checkpoint = empty_schema11_checkpoint("campaign-1", "selection-1")
        started: list[str] = []
        committed: list[tuple[str, FailureDisposition]] = []
        persisted: list[dict[str, object]] = []

        def execute(leaf_id: str):
            started.append(leaf_id)
            return _report("ODE_RESOURCE_LIMIT")

        with self.assertRaisesRegex(CampaignSystemFailure, "repetition breaker"):
            run_guarded_pass(
                ("leaf-1", "leaf-2", "leaf-3"),
                checkpoint=checkpoint,
                execute_leaf=execute,
                commit_leaf_outcome=lambda leaf, outcome: committed.append(
                    (leaf, outcome.disposition)
                ),
                persist_checkpoint=lambda value: persisted.append(value),
            )

        self.assertEqual(["leaf-1", "leaf-2"], started)
        self.assertEqual(
            [
                ("leaf-1", FailureDisposition.DEFERRED),
                ("leaf-2", FailureDisposition.DEFERRED),
            ],
            committed,
        )
        self.assertEqual(1, len(persisted[-1]["system_failures"]))
        self.assertNotIn("FAILED", str(persisted[-1]))

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
