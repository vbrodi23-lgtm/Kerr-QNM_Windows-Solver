from __future__ import annotations

import copy
import unittest
from pathlib import Path
import tempfile
from types import SimpleNamespace

from windows_solver import response_batches
from windows_solver.campaign_policy import (
    PROMOTED_HORIZON_CONTROL_DECISION_SCHEMA,
    PROMOTED_HORIZON_CONTROL_RETURN_SCHEMA,
    PromotionQueueDisposition,
    PromotionQueueKind,
    SurveyDisposition,
    SurveyPass,
    append_promotion,
    empty_schema11_checkpoint,
    promoted_artifact_digest,
    promoted_control_terminal_disposition_receipt,
    record_survey_disposition,
    retain_promoted_control_terminal,
    validate_schema11_checkpoint,
)
from windows_solver.campaign_recovery import RecoverySelection
from windows_solver.campaign_runtime import (
    _validated_promoted_horizon_control,
    build_schema11_horizon_stage,
)
from windows_solver.campaign_survey import PromotedPassOutcome
from windows_solver.julia_response_backend import (
    JuliaNumericalControlError,
    JuliaODEResourceLimitError,
    JuliaResponseBackendError,
    _execution_resource_policy,
)
from windows_solver.operation_control import (
    FIXED_ROOT_DETERMINANT_SAMPLE_OPERATION,
    JULIA_WORKER_ORIGIN,
    build_operation_control_receipt,
    canonical_sha256,
    execution_identity_from_request,
    validate_operation_control_receipt,
)
from windows_solver.response_batches import (
    PrecisionCapabilities,
    build_campaign_plan,
    build_campaign_selection,
    scientific_computation_identity_sha256,
)
from windows_solver.response_engine import NumericalPolicy, VettedNativeDeterminantKernel
from tests.test_horizon_record_construction import _binary64_horizon_outcome
from tests.test_promoted_survey_scheduler import _strict_run


def _resource() -> dict[str, object]:
    return _execution_resource_policy()


def _fixed_sample_request() -> dict[str, object]:
    return {
        "schema_version": 1,
        "operation": FIXED_ROOT_DETERMINANT_SAMPLE_OPERATION,
        "leaf_id": "leaf-horizon",
        "job_id": "job-horizon",
        "backend_identity_sha256": "b" * 64,
        "precision_digits": 80,
        "working_precision_bits": 298,
        "semantic_precision_tier": "bigfloat-80",
        "role": "primary-root",
        "job_policy_sha256": "d" * 64,
        "refinement_level": 0,
        "fixed_omega": {"real": "0.5", "imaginary": "-0.1"},
        "readout_role": "coordinate-real-plus-h",
        "policy": {
            "root_gate": "strict/v1",
            "branch_convention": "gsn-complex-rho/v1",
        },
        "execution_resource": _resource(),
    }


def _control_error() -> JuliaNumericalControlError:
    request = _fixed_sample_request()
    request_sha256 = canonical_sha256(request)
    identity = execution_identity_from_request(
        request,
        request_sha256=request_sha256,
    )
    receipt = build_operation_control_receipt(
        origin=JULIA_WORKER_ORIGIN,
        failure_code="INSUFFICIENT_ASYMPTOTIC_PRECISION",
        stage="asymptotic-preflight",
        identity=identity,
        retryable=False,
        retryable_basis="generic condition has no continuation authority/v1",
        diagnostics={
            "reason": "INSUFFICIENT_ASYMPTOTIC_PRECISION",
            "precision_bits": request["working_precision_bits"],
            "factored_homogeneous_rhs_evaluations": 0,
            "avoided_ode_scope": "factored-homogeneous-gsn/v1",
            "predicted_reliable_digits": "10",
            "required_reliable_digits": "20",
            "asymptotic_preflight_avoided_ode": True,
            "asymptotic_preflight_reason": (
                "INSUFFICIENT_ASYMPTOTIC_PRECISION"
            ),
            "maximum_series_digits_lost": "30",
            "maximum_recurrence_digits_lost": "5",
        },
    )
    validated = validate_operation_control_receipt(
        receipt,
        request=request,
        request_sha256=request_sha256,
    )
    return JuliaNumericalControlError(
        "bounded promoted-horizon control",
        "INSUFFICIENT_ASYMPTOTIC_PRECISION",
        control_receipt=validated,
    )


def _expected_job():
    return SimpleNamespace(
        leaf_id="leaf-horizon",
        job_id="job-horizon",
        backend_identity=SimpleNamespace(identity_sha256="b" * 64),
    )


def _horizon_checkpoint_fixture():
    plan = build_campaign_plan(
        policy=NumericalPolicy(),
        backend_identity=VettedNativeDeterminantKernel.identity,
        precision_capabilities=PrecisionCapabilities((64, 80)),
    )
    leaf = next(
        item
        for item in plan.leaves
        if item.role == "primary"
        and item.mechanism_id == "horizon-admittance"
    )
    selected = build_campaign_selection(
        plan,
        role=leaf.role,
        leaf_ids=(leaf.leaf_id,),
    )
    selection = RecoverySelection(
        campaign_id=plan.campaign_id,
        selection_id=selected.selection_id,
        ordered_leaf_ids=(leaf.leaf_id,),
        roles={leaf.leaf_id: leaf.role},
        scientific_identities={
            leaf.leaf_id: scientific_computation_identity_sha256(plan, leaf)
        },
    )
    provisional_outcome = _binary64_horizon_outcome(plan, leaf)
    provisional, provisional_sha256 = build_schema11_horizon_stage(
        provisional_outcome,
        precision_tier="binary64",
        operation_identity="binary64-horizon-production/v3",
    )
    checkpoint = record_survey_disposition(
        empty_schema11_checkpoint(plan.campaign_id, selected.selection_id),
        survey_pass=SurveyPass.BINARY64,
        leaf_id=leaf.leaf_id,
        disposition=SurveyDisposition.PROMOTION_PENDING_RESPONSE,
        operation_identity="binary64-horizon-production/v3",
        precision_tiers=("binary64",),
        reason_code="ROOT_UNCERTAINTY_EVIDENCE_UNAVAILABLE",
        sample_count=0,
        sample_limit=0,
        root_read_count=0,
        root_read_limit=0,
        worker_launch_count=0,
        worker_launch_limit=0,
        tier_timing=(),
        session_fragments=(),
    )
    binary64_receipt_sha256 = checkpoint["survey_pass_ledger"]["binary64"][
        leaf.leaf_id
    ]["disposition_receipt_sha256"]
    checkpoint = append_promotion(
        checkpoint,
        leaf_id=leaf.leaf_id,
        queue_kind=PromotionQueueKind.RESPONSE,
        reason_code="ROOT_UNCERTAINTY_EVIDENCE_UNAVAILABLE",
        minimum_requested_tier="BF80",
        scientific_computation_identity=selection.scientific_identities[
            leaf.leaf_id
        ],
        source_stage_sha256=provisional_sha256,
        source_root_seal_sha256="d" * 64,
        provisional_stage=provisional,
        provisional_stage_sha256=provisional_sha256,
        provisional_operation_identity="binary64-horizon-production/v3",
        source_binary64_disposition_receipt_sha256=binary64_receipt_sha256,
    )
    return plan, leaf, selection, checkpoint


def _horizon_control_outcome(leaf, entry) -> PromotedPassOutcome:
    request = {
        "schema_version": 1,
        "operation": FIXED_ROOT_DETERMINANT_SAMPLE_OPERATION,
        "leaf_id": leaf.job.leaf_id,
        "job_id": leaf.job.job_id,
        "backend_identity_sha256": leaf.job.backend_identity.identity_sha256,
        "precision_digits": 80,
        "working_precision_bits": 298,
        "semantic_precision_tier": "bigfloat-80",
        "role": "primary-root",
        "job_policy_sha256": leaf.job.policy.identity_sha256,
        "refinement_level": 0,
        "fixed_omega": {
            "real": format(leaf.job.root.omega.real, ".17g"),
            "imaginary": format(leaf.job.root.omega.imag, ".17g"),
        },
        "readout_role": "coordinate-real-plus-h",
        "policy": {
            "root_gate": "strict/v1",
            "branch_convention": "gsn-complex-rho/v1",
        },
        "execution_resource": _resource(),
    }
    request_sha256 = canonical_sha256(request)
    identity = execution_identity_from_request(
        request,
        request_sha256=request_sha256,
    )
    receipt = validate_operation_control_receipt(
        build_operation_control_receipt(
            origin=JULIA_WORKER_ORIGIN,
            failure_code="INSUFFICIENT_ASYMPTOTIC_PRECISION",
            stage="asymptotic-preflight",
            identity=identity,
            retryable=False,
            retryable_basis="generic condition has no continuation authority/v1",
            diagnostics={
                "reason": "INSUFFICIENT_ASYMPTOTIC_PRECISION",
                "precision_bits": request["working_precision_bits"],
                "factored_homogeneous_rhs_evaluations": 0,
                "avoided_ode_scope": "factored-homogeneous-gsn/v1",
                "predicted_reliable_digits": "10",
                "required_reliable_digits": "20",
                "asymptotic_preflight_avoided_ode": True,
                "asymptotic_preflight_reason": (
                    "INSUFFICIENT_ASYMPTOTIC_PRECISION"
                ),
                "maximum_series_digits_lost": "30",
                "maximum_recurrence_digits_lost": "5",
            },
        ),
        request=request,
        request_sha256=request_sha256,
    )
    effective_policy = identity.mapping["effective_policy_identity"]
    effective_policy_sha256 = (
        str(effective_policy["sha256"])
        if isinstance(effective_policy, dict)
        else str(effective_policy)
    )
    content = {
        "schema": PROMOTED_HORIZON_CONTROL_RETURN_SCHEMA,
        "operation": identity.operation,
        "request_schema": identity.mapping["request_schema"],
        "request_sha256": identity.request_sha256,
        "execution_identity_sha256": identity.sha256,
        "effective_policy_identity": effective_policy_sha256,
        "current_tier": "BF80",
        "current_action_kind": "RESPONSE",
        "canonical_request": request,
        "control_receipt": receipt.to_mapping(),
        "control_receipt_sha256": receipt.sha256,
        "predecessor_stage_sha256": entry["source_stage_sha256"],
        "source_fingerprint_sha256": entry["source_fingerprint_sha256"],
        "layer1_lock_receipt_sha256": "f" * 64,
    }
    control_return = {
        **content,
        "control_return_sha256": canonical_sha256(content),
    }
    return PromotedPassOutcome(
        disposition=SurveyDisposition.UNRESOLVED,
        reason_code=receipt.failure_code,
        precision_tiers=("BF80",),
        operation_identity="promoted-horizon-control-return/v2",
        root_read_count=0,
        root_read_limit=1,
        worker_launch_count=1,
        worker_launch_limit=1,
        calculation_artifact=control_return,
    )


class PromotedHorizonControlAuthorityTests(unittest.TestCase):
    def _interrupt_horizon_after(self, target: str):
        plan, leaf, selection, checkpoint = _horizon_checkpoint_fixture()
        durable: list[dict[str, object]] = []
        runner_calls: list[str] = []

        def runner(source_leaf, entry, _source_record, _receipts):
            runner_calls.append(source_leaf.leaf_id)
            return _horizon_control_outcome(source_leaf, entry)

        def stop_after_commit(value):
            if value["promotion_queue"]["entries"][0]["disposition"] == target:
                durable.append(copy.deepcopy(value))
                raise KeyboardInterrupt
            return value

        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(KeyboardInterrupt):
                _strict_run(
                    plan,
                    selection,
                    checkpoint,
                    checkpoint_path=Path(temporary) / "checkpoint.json",
                    root_seal_lookup=lambda *_args: None,
                    root_seal_publish=lambda *_args: self.fail(
                        "horizon route cannot publish a root"
                    ),
                    backend_factory=lambda *_args: self.fail(
                        "horizon route cannot build an exterior backend"
                    ),
                    primary_root_runner=lambda *_args: self.fail(
                        "horizon route cannot solve an exterior root"
                    ),
                    horizon_runner=lambda *_args: self.fail(
                        "legacy horizon runner was used"
                    ),
                    promoted_horizon_runner=runner,
                    checkpoint_committed=stop_after_commit,
                )
        self.assertEqual([leaf.leaf_id], runner_calls)
        self.assertEqual(1, len(durable))
        return plan, leaf, selection, durable[0]

    def _resume_horizon(self, plan, selection, checkpoint):
        with tempfile.TemporaryDirectory() as temporary:
            return _strict_run(
                plan,
                selection,
                checkpoint,
                checkpoint_path=Path(temporary) / "checkpoint.json",
                root_seal_lookup=lambda *_args: None,
                root_seal_publish=lambda *_args: self.fail(
                    "horizon route cannot publish a root"
                ),
                backend_factory=lambda *_args: self.fail(
                    "horizon route cannot build an exterior backend"
                ),
                primary_root_runner=lambda *_args: self.fail(
                    "horizon route cannot solve an exterior root"
                ),
                horizon_runner=lambda *_args: self.fail(
                    "legacy horizon runner was used"
                ),
                promoted_horizon_runner=lambda *_args: self.fail(
                    "durable horizon CONTROL evidence must prevent worker replay"
                ),
            )

    def _terminal_horizon_checkpoint(self):
        plan, leaf, selection, interrupted = self._interrupt_horizon_after(
            PromotionQueueDisposition.CONTROL_DECISION_RETAINED.value
        )
        return leaf, self._resume_horizon(
            plan,
            selection,
            interrupted,
        ).checkpoint

    def test_horizon_control_payloads_use_typed_digests_and_v1_is_unsupported(
        self,
    ) -> None:
        return_content = {
            "schema": PROMOTED_HORIZON_CONTROL_RETURN_SCHEMA,
            "marker": "raw-receipt",
        }
        raw = {
            **return_content,
            "control_return_sha256": canonical_sha256(return_content),
        }
        decision_content = {
            "schema": PROMOTED_HORIZON_CONTROL_DECISION_SCHEMA,
            "control_return_sha256": raw["control_return_sha256"],
        }
        decision = {
            **decision_content,
            "control_decision_sha256": canonical_sha256(decision_content),
        }

        self.assertEqual(
            ("control_return_sha256", raw["control_return_sha256"]),
            promoted_artifact_digest(raw),
        )
        self.assertEqual(
            ("control_decision_sha256", decision["control_decision_sha256"]),
            promoted_artifact_digest(decision),
        )

        legacy_content = {
            "schema": "windows-solver.promoted-horizon-control-return/1",
            "policy_disposition": "UNRESOLVED",
        }
        legacy = {
            **legacy_content,
            "calculation_sha256": canonical_sha256(legacy_content),
        }
        with self.assertRaisesRegex(ValueError, "schema is unsupported"):
            promoted_artifact_digest(legacy)

        unknown_content = {
            "schema": "windows-solver.promoted-horizon-control-return/999",
            "marker": "unknown-control-shape",
        }
        unknown = {
            **unknown_content,
            "calculation_sha256": canonical_sha256(unknown_content),
        }
        with self.assertRaisesRegex(ValueError, "schema is unsupported"):
            promoted_artifact_digest(unknown)

    def test_campaign9_control_tables_are_explicitly_legacy_scoped(self) -> None:
        source = response_batches.__file__
        assert source is not None
        text = Path(source).read_text(encoding="utf-8")

        self.assertNotIn("except _CONTAINABLE_EXCEPTION_TYPES", text)
        self.assertNotIn("def _numerical_failure_promotion_decision", text)
        self.assertIn(
            "_LEGACY_CAMPAIGN9_CONTAINABLE_EXCEPTION_TYPES",
            text,
        )
        self.assertIn(
            "def _legacy_campaign9_numerical_failure_promotion_decision",
            text,
        )

    def test_authenticated_worker_control_is_bound_without_classification(self) -> None:
        error = _control_error()

        receipt = _validated_promoted_horizon_control(
            error,
            expected_job=_expected_job(),
        )

        self.assertEqual(
            FIXED_ROOT_DETERMINANT_SAMPLE_OPERATION,
            receipt.identity.operation,
        )
        self.assertEqual(
            error.control_receipt.sha256,
            receipt.sha256,
        )
        self.assertIsNotNone(receipt.canonical_request)

    def test_missing_validated_receipt_fails_closed(self) -> None:
        error = JuliaNumericalControlError(
            "unbound worker control",
            "INSUFFICIENT_ASYMPTOTIC_PRECISION",
        )

        with self.assertRaisesRegex(
            JuliaResponseBackendError,
            "validated operation-control receipt",
        ):
            _validated_promoted_horizon_control(
                error,
                expected_job=_expected_job(),
            )

    def test_exception_type_cannot_disagree_with_registry_transition(self) -> None:
        error = JuliaODEResourceLimitError("wrong exception class")
        error.control_receipt = _control_error().control_receipt

        with self.assertRaisesRegex(
            JuliaResponseBackendError,
            "exception identity",
        ):
            _validated_promoted_horizon_control(
                error,
                expected_job=_expected_job(),
            )

    def test_receipt_must_match_the_scheduler_job_and_bf80_tier(self) -> None:
        wrong_job = _expected_job()
        wrong_job.job_id = "another-job"

        with self.assertRaisesRegex(
            JuliaResponseBackendError,
            "scheduler identity",
        ):
            _validated_promoted_horizon_control(
                _control_error(),
                expected_job=wrong_job,
            )

    def test_horizon_control_return_is_durable_before_classification(self) -> None:
        plan, leaf, selection, interrupted = self._interrupt_horizon_after(
            PromotionQueueDisposition.CONTROL_RETURN_RETAINED.value
        )
        stage = interrupted["promoted_stage_ledger"]["0"][leaf.leaf_id]
        self.assertEqual(
            "windows-solver.promoted-control-return-stage/1",
            stage["schema"],
        )
        self.assertEqual(
            PROMOTED_HORIZON_CONTROL_RETURN_SCHEMA,
            stage["control_return"]["schema"],
        )
        self.assertNotIn("calculation_artifact", stage)

        resumed = self._resume_horizon(plan, selection, interrupted)
        self.assertEqual(1, resumed.unresolved_count)
        self.assertEqual(
            PromotionQueueDisposition.UNRESOLVED.value,
            resumed.checkpoint["promotion_queue"]["entries"][0]["disposition"],
        )
        decision_stage = resumed.checkpoint["promoted_stage_ledger"]["0"][
            leaf.leaf_id
        ]
        self.assertEqual(
            PROMOTED_HORIZON_CONTROL_DECISION_SCHEMA,
            decision_stage["control_decision"]["schema"],
        )

    def test_horizon_control_decision_is_durable_and_resumes_without_replay(
        self,
    ) -> None:
        plan, leaf, selection, interrupted = self._interrupt_horizon_after(
            PromotionQueueDisposition.CONTROL_DECISION_RETAINED.value
        )
        stage = interrupted["promoted_stage_ledger"]["0"][leaf.leaf_id]
        self.assertEqual(
            "windows-solver.promoted-control-decision-stage/1",
            stage["schema"],
        )
        self.assertEqual(
            PROMOTED_HORIZON_CONTROL_DECISION_SCHEMA,
            stage["control_decision"]["schema"],
        )
        self.assertEqual(
            PROMOTED_HORIZON_CONTROL_RETURN_SCHEMA,
            stage["calculation_chain"][-1]["control_return"]["schema"],
        )

        resumed = self._resume_horizon(plan, selection, interrupted)
        self.assertEqual(1, resumed.unresolved_count)
        self.assertEqual(
            PromotionQueueDisposition.UNRESOLVED.value,
            resumed.checkpoint["promotion_queue"]["entries"][0]["disposition"],
        )

    def test_resealed_horizon_decision_cannot_override_registry_authority(
        self,
    ) -> None:
        _plan, leaf, _selection, interrupted = self._interrupt_horizon_after(
            PromotionQueueDisposition.CONTROL_DECISION_RETAINED.value
        )
        forged = copy.deepcopy(interrupted)
        stage = forged["promoted_stage_ledger"]["0"][leaf.leaf_id]
        decision = stage["control_decision"]
        decision["disposition"] = "DEFERRED"
        decision_content = {
            key: value
            for key, value in decision.items()
            if key != "control_decision_sha256"
        }
        decision["control_decision_sha256"] = canonical_sha256(decision_content)
        stage_content = {
            key: value for key, value in stage.items() if key != "stage_sha256"
        }
        stage["stage_sha256"] = canonical_sha256(stage_content)
        forged["promotion_queue"]["entries"][0][
            "retained_promoted_stage_sha256"
        ] = stage["stage_sha256"]

        with self.assertRaisesRegex(ValueError, "registry authority"):
            validate_schema11_checkpoint(forged)

    def test_terminal_control_receipt_is_exact_and_recomputable(self) -> None:
        leaf, checkpoint = self._terminal_horizon_checkpoint()
        entry = checkpoint["promotion_queue"]["entries"][0]
        stage = checkpoint["promoted_stage_ledger"]["0"][leaf.leaf_id]
        expected_receipt = promoted_control_terminal_disposition_receipt(
            entry,
            stage,
        )

        self.assertEqual(
            canonical_sha256(expected_receipt),
            entry["disposition_receipt_sha256"],
        )
        self.assertEqual(
            entry["disposition"],
            stage["control_decision"]["disposition"],
        )
        self.assertEqual(
            stage["control_decision"]["control_return_sha256"],
            stage["calculation_chain"][-1]["control_return"][
                "control_return_sha256"
            ],
        )

    def test_terminal_control_rejects_arbitrary_disposition_receipt(self) -> None:
        _plan, leaf, _selection, decision_checkpoint = (
            self._interrupt_horizon_after(
                PromotionQueueDisposition.CONTROL_DECISION_RETAINED.value
            )
        )

        with self.assertRaisesRegex(ValueError, "disposition receipt"):
            retain_promoted_control_terminal(
                decision_checkpoint,
                queue_ordinal=0,
                disposition=PromotionQueueDisposition.UNRESOLVED,
                disposition_receipt={
                    "schema": "windows-solver.arbitrary-receipt/1",
                    "leaf_id": leaf.leaf_id,
                },
            )

    def test_terminal_control_proof_mutations_fail_closed(self) -> None:
        leaf, checkpoint = self._terminal_horizon_checkpoint()

        deleted_ledger = copy.deepcopy(checkpoint)
        del deleted_ledger["promoted_stage_ledger"]["0"]

        deleted_pointer = copy.deepcopy(checkpoint)
        deleted_pointer["promotion_queue"]["entries"][0][
            "retained_promoted_stage_sha256"
        ] = None

        deleted_ledger_and_pointer = copy.deepcopy(checkpoint)
        del deleted_ledger_and_pointer["promoted_stage_ledger"]["0"]
        deleted_ledger_and_pointer["promotion_queue"]["entries"][0][
            "retained_promoted_stage_sha256"
        ] = None

        erased_terminal_authority = copy.deepcopy(checkpoint)
        del erased_terminal_authority["promoted_stage_ledger"]["0"]
        erased_terminal_authority["promotion_queue"]["entries"][0][
            "retained_promoted_stage_sha256"
        ] = None
        del erased_terminal_authority["survey_pass_ledger"]["promoted"][
            leaf.leaf_id
        ]

        arbitrary_receipt = copy.deepcopy(checkpoint)
        arbitrary_receipt["promotion_queue"]["entries"][0][
            "disposition_receipt_sha256"
        ] = canonical_sha256({"schema": "windows-solver.arbitrary-receipt/1"})

        mismatched_disposition = copy.deepcopy(checkpoint)
        mismatched_disposition["promotion_queue"]["entries"][0][
            "disposition"
        ] = PromotionQueueDisposition.DEFERRED.value

        missing_raw_chain = copy.deepcopy(checkpoint)
        missing_stage = missing_raw_chain["promoted_stage_ledger"]["0"][
            leaf.leaf_id
        ]
        missing_stage["calculation_chain"] = []
        missing_stage["source_calculation_stage_sha256"] = None
        missing_stage["stage_sha256"] = canonical_sha256({
            key: value
            for key, value in missing_stage.items()
            if key != "stage_sha256"
        })
        missing_raw_chain["promotion_queue"]["entries"][0][
            "retained_promoted_stage_sha256"
        ] = missing_stage["stage_sha256"]

        downgraded_stage = copy.deepcopy(checkpoint)
        legacy = downgraded_stage["promoted_stage_ledger"]["0"][leaf.leaf_id]
        legacy["schema"] = "windows-solver.promoted-calculation-stage/1"
        legacy["stage_sha256"] = canonical_sha256({
            key: value for key, value in legacy.items() if key != "stage_sha256"
        })
        downgraded_stage["promotion_queue"]["entries"][0][
            "retained_promoted_stage_sha256"
        ] = legacy["stage_sha256"]

        for label, forged in {
            "deleted-ledger": deleted_ledger,
            "deleted-pointer": deleted_pointer,
            "deleted-ledger-and-pointer": deleted_ledger_and_pointer,
            "deleted-ledger-pointer-and-pass": erased_terminal_authority,
            "arbitrary-receipt": arbitrary_receipt,
            "decision-disposition-mismatch": mismatched_disposition,
            "missing-raw-chain": missing_raw_chain,
            "legacy-stage-downgrade": downgraded_stage,
        }.items():
            with self.subTest(label=label):
                with self.assertRaises(ValueError):
                    validate_schema11_checkpoint(forged)


if __name__ == "__main__":
    unittest.main()
