"""PR68 regression tests for the schema-11 horizon lifecycle."""

from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import windows_solver.campaign_runtime as campaign_runtime
import windows_solver.response_batches as response_batches
from windows_solver.campaign_policy import (
    PromotionQueueKind,
    SurveyDisposition,
    add_numerical_record,
    append_promotion,
    empty_schema11_checkpoint,
)
from windows_solver.campaign_recovery import RecoverySelection
from windows_solver.campaign_runtime import (
    build_schema11_horizon_record,
    build_schema11_horizon_stage,
)
from windows_solver.campaign_survey import (
    Binary64PassOutcome,
    PromotedPassOutcome,
    _record_pass_outcome,
    run_promoted_survey,
)
from windows_solver.contracts import canonical_json_bytes
from windows_solver.native_response_kernel import VettedNativeDeterminantKernel
from windows_solver.response_batches import (
    B_PRIME_RELEASE_DOMAIN,
    NativeCampaignStageBackend,
    PrecisionCapabilities,
    StageOutcome,
    build_campaign_plan,
    build_campaign_selection,
    synthetic_stage_signed_error_channels,
)
from windows_solver.response_engine import DeterminantPartials, NumericalPolicy
from tests.test_native_campaign_backend import _result as native_component_result


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _plan():
    return build_campaign_plan(
        policy=NumericalPolicy(),
        backend_identity=VettedNativeDeterminantKernel.identity,
        precision_capabilities=PrecisionCapabilities((64, 80)),
    )


def _deep_horizon_stage(*, diagnostics: dict[str, object] | None):
    payload = {
        "evidence_kind": "synthetic-pr68-horizon-stage",
        "result": {"status": "CONVERGED"},
    }
    return StageOutcome(
        digits=64,
        numerical_state="CONVERGED",
        component_result=payload,
        local_disk_radius_abs=1.0e-6,
        signed_error_channels=synthetic_stage_signed_error_channels(
            payload, 1.0e-6
        ),
        deep_diagnostics=diagnostics,
    )


def _triggering_diagnostics() -> dict[str, object]:
    return {
        "condition_amplifier_abs": 1.0,
        "predicted_reliable_decimal_digits": 8.0,
        "step_richardson_disagreement_abs": 0.0,
        "repeat_polish_delta_abs": 0.0,
        "angular_refinement_delta_abs": 0.0,
        "independent_path_delta_abs": 0.0,
        "diagnostic_ceiling_abs": 1.0,
        "denominator_or_calibration_disk_contains_zero": False,
    }


class HorizonRecordConstructionTests(unittest.TestCase):
    def test_authoritative_decision_derives_deep_trigger_and_sentinel(self) -> None:
        plan = _plan()
        leaf = next(
            item
            for item in plan.leaves
            if item.role == "deep"
            and item.mechanism_id == "horizon-admittance"
            and item.leaf_id
            in set(B_PRIME_RELEASE_DOMAIN.fixed_precision_sentinel_leaf_ids)
        )
        decision_builder = getattr(
            response_batches, "derive_horizon_promotion_decision", None
        )
        self.assertTrue(callable(decision_builder))

        stage = _deep_horizon_stage(diagnostics=_triggering_diagnostics())
        decision = decision_builder(leaf, stage)

        self.assertEqual(
            decision.trigger_ids,
            response_batches._deep_trigger_ids(stage),
        )
        self.assertTrue(decision.sentinel)
        self.assertTrue(decision.promotion_required)
        self.assertEqual(decision.reason_code, "DEEP_TRIGGER_AND_FIXED_SENTINEL")

    def test_deep_horizon_without_diagnostics_fails_closed(self) -> None:
        plan = _plan()
        leaf = next(
            item
            for item in plan.leaves
            if item.role == "deep" and item.mechanism_id == "horizon-admittance"
        )
        decision_builder = getattr(
            response_batches, "derive_horizon_promotion_decision", None
        )
        self.assertTrue(callable(decision_builder))

        with self.assertRaisesRegex(ValueError, "deep diagnostics"):
            decision_builder(leaf, _deep_horizon_stage(diagnostics=None))

    def test_schema11_horizon_builder_is_not_legacy_record(self) -> None:
        self.assertFalse(hasattr(campaign_runtime, "_produced_horizon_record"))
        self.assertTrue(
            callable(getattr(campaign_runtime, "build_schema11_horizon_record", None))
        )
        self.assertTrue(
            callable(getattr(response_batches, "validate_schema11_horizon_record", None))
        )

    def test_binary64_horizon_stage_is_fixed_root_analytic_and_ladder_free(self) -> None:
        plan = _plan()
        leaf = next(
            item
            for item in plan.leaves
            if item.role == "primary"
            and item.mechanism_id == "horizon-admittance"
        )

        class Kernel:
            identity = VettedNativeDeterminantKernel.identity

            def __init__(self):
                self.partial_calls = 0
                self.root_calls = 0

            def horizon_partials(self, **_kwargs):
                self.partial_calls += 1
                return DeterminantPartials(
                    frequency_derivative=1.0 + 0.25j,
                    coordinate_derivative=-0.5 + 0.1j,
                    simple_root_valid=True,
                )

            def evaluate_root(self, **_kwargs):
                self.root_calls += 1
                raise AssertionError("binary64 horizon entered root/ladders")

        kernel = Kernel()
        adapter = SimpleNamespace(identity=kernel.identity, kernel=kernel)
        generated = SimpleNamespace(
            record_artifact_ids=(),
            path=Path("synthetic-gsn-cache"),
            sha256="a" * 64,
            parameter_pairs=(),
        )
        backend = NativeCampaignStageBackend(
            adapter,
            PrecisionCapabilities((64,)),
            generated,
        )

        outcome = backend.execute_horizon_stage(leaf)
        raw = outcome.component_result["result"]
        self.assertEqual(64, outcome.digits)
        self.assertEqual(1, kernel.partial_calls)
        self.assertEqual(0, kernel.root_calls)
        self.assertEqual([], raw["levels"])
        self.assertFalse(raw["finite_amplitude_ladder_required"])
        self.assertFalse(raw["finite_amplitude_ladder_executed"])
        self.assertEqual(0, raw["finite_amplitude_readout_count"])
        self.assertEqual(0, raw["analytic_horizon_evidence"]["worker_launch_count"])
        self.assertEqual([], raw["analytic_horizon_evidence"]["levels"])

    def test_binary64_outcome_commits_record_and_promotion_queue(self) -> None:
        record_content = {
            "schema": "windows-solver.schema11-numerical-record/1",
            "leaf_id": "leaf-1",
            "role": "deep",
            "state": "PRODUCED",
            "scientific_computation_identity": "b" * 64,
            "retained_centre": {"real": 1.0, "imaginary": -0.25},
            "stages": [{"stage_sha256": "a" * 64}],
        }
        record = {**record_content, "record_sha256": _sha256(record_content)}
        selection = RecoverySelection(
            campaign_id="campaign-1",
            selection_id="selection-1",
            ordered_leaf_ids=("leaf-1",),
            roles={"leaf-1": "deep"},
            scientific_identities={"leaf-1": "b" * 64},
        )
        outcome = Binary64PassOutcome(
            disposition=SurveyDisposition.PROMOTION_PENDING_RESPONSE,
            operation_identity="binary64-horizon-production/v2",
            reason_code="DEEP_DIAGNOSTIC_PROMOTION",
            record=record,
            stage_sha256="a" * 64,
            queue_kind=PromotionQueueKind.RESPONSE,
        )

        checkpoint = _record_pass_outcome(
            empty_schema11_checkpoint("campaign-1", "selection-1"),
            selection=selection,
            leaf_id="leaf-1",
            outcome=outcome,
            root_seal_sha256=None,
        )

        self.assertEqual([record], checkpoint["records"])
        queue = checkpoint["promotion_queue"]["entries"]
        self.assertEqual(1, len(queue))
        self.assertEqual(record["record_sha256"], queue[0]["source_record_sha256"])
        self.assertEqual("a" * 64, queue[0]["source_stage_sha256"])

    def test_promoted_horizon_uses_source_record_comparison_callback(self) -> None:
        plan = _plan()
        leaf = next(
            item
            for item in plan.leaves
            if item.role == "primary"
            and item.mechanism_id == "horizon-admittance"
        )
        selected = build_campaign_selection(
            plan, role=leaf.role, leaf_ids=(leaf.leaf_id,)
        )
        selection = RecoverySelection(
            campaign_id=plan.campaign_id,
            selection_id=selected.selection_id,
            ordered_leaf_ids=(leaf.leaf_id,),
            roles={leaf.leaf_id: leaf.role},
            scientific_identities={
                leaf.leaf_id: response_batches.scientific_computation_identity_sha256(
                    plan, leaf
                )
            },
        )
        component = native_component_result(leaf.job, 0.25 + 0.1j)
        payload = {
            "evidence_kind": "native-task-008-component-engine",
            "result": component.to_mapping(),
        }
        stage_outcome = StageOutcome(
            digits=64,
            numerical_state="CONVERGED",
            component_result=payload,
            local_disk_radius_abs=1.0e-6,
            signed_error_channels=synthetic_stage_signed_error_channels(
                payload, 1.0e-6
            ),
        )
        stage, stage_sha256 = build_schema11_horizon_stage(
            stage_outcome,
            precision_tier="binary64",
            operation_identity="test-binary64-horizon/v1",
        )
        response_disk = stage["response_disk"]
        assert isinstance(response_disk, dict)
        record = build_schema11_horizon_record(
            plan,
            leaf,
            stages=(stage,),
            retained_centre=response_disk["centre"],
            state="PRODUCED",
        )
        checkpoint = add_numerical_record(
            empty_schema11_checkpoint(plan.campaign_id, selected.selection_id),
            record,
        )
        checkpoint = append_promotion(
            checkpoint,
            leaf_id=leaf.leaf_id,
            queue_kind=PromotionQueueKind.RESPONSE,
            reason_code="FIXED_PRECISION_SENTINEL_PROMOTION",
            minimum_requested_tier="BF80",
            scientific_computation_identity=selection.scientific_identities[
                leaf.leaf_id
            ],
            source_record_sha256=record["record_sha256"],
            source_stage_sha256=stage_sha256,
        )
        observed: dict[str, object] = {}

        def compare(source_leaf, entry, source_record, receipts):
            observed.update({
                "leaf_id": source_leaf.leaf_id,
                "entry": entry,
                "source_record": source_record,
                "receipts": receipts,
            })
            return PromotedPassOutcome(
                disposition=SurveyDisposition.COMPLETED,
                reason_code="PROMOTED_HORIZON_COMPARISON_AGREES",
                precision_tiers=("BF80",),
                source_record_sha256=record["record_sha256"],
                source_stage_sha256=stage_sha256,
            )

        with tempfile.TemporaryDirectory() as temporary:
            result = run_promoted_survey(
                plan,
                selection,
                checkpoint,
                checkpoint_path=Path(temporary) / "checkpoint.json",
                root_seal_lookup=lambda _leaf, _entry: None,
                backend_factory=lambda _leaf, _digits: None,
                primary_root_runner=lambda *_args: self.fail(
                    "unexpected promoted root"
                ),
                horizon_runner=lambda _leaf: self.fail(
                    "legacy promoted horizon runner was used"
                ),
                promoted_horizon_runner=compare,
                produced_record_builder=lambda *_args: self.fail(
                    "unexpected promoted record builder"
                ),
            )

        self.assertEqual(leaf.leaf_id, observed["leaf_id"])
        self.assertEqual(record, observed["source_record"])
        self.assertEqual(record, result.checkpoint["records"][0])
        self.assertEqual(
            "COMPLETED",
            result.checkpoint["promotion_queue"]["entries"][0]["disposition"],
        )


if __name__ == "__main__":
    unittest.main()
