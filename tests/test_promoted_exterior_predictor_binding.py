from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import unittest
from unittest.mock import patch

from tests.test_native_campaign_backend import _failed_preflight_attempt
import tests.test_promoted_exterior_campaign_flow as campaign_fixtures
import tests.test_promoted_exterior_derivative as derivative_fixtures
from tests.test_promoted_horizon_component import _with_worker_receipt
from windows_solver.response_batches import (
    CampaignLeafRecord,
    _campaign_stage_record,
    _primary_precision120_decision,
    _stage_with_promotion_decision,
    _validate_failed_preflight_recovery_stage,
    _validate_record_semantics,
    build_campaign_selection,
    run_campaign_selection,
    validate_campaign_checkpoint,
)
from windows_solver.response_engine import ComponentResult


class PromotedExteriorPredictorBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.flow = campaign_fixtures.PromotedExteriorCampaignFlowCanary(
            methodName=(
                "test_leaf42_native_80_stage_uses_explicit_na_response_comparison"
            )
        )
        self.flow.setUp()
        self.addCleanup(self.flow.doCleanups)

    def _binary_stage(self):
        native = self.flow._native_backend()
        with patch(
            "windows_solver.response_batches.run_component",
            return_value=self.flow._binary_result(),
        ):
            binary = native.execute_stage(self.flow.leaf, 64)
        return native, binary

    def _worker(self, digits: int, predictor: complex):
        leaf = self.flow.leaf
        baseline = replace(
            derivative_fixtures.PromotedExteriorDerivativeTests
            ._baseline_with_derivative_evidence(leaf),
            omega=leaf.job.root.omega,
        )
        baseline = _with_worker_receipt(
            leaf.job,
            baseline,
            digits,
            predictor,
        )
        return campaign_fixtures._ScientificFixedRootBackend(
            leaf.job,
            baseline,
            digits,
        )

    @staticmethod
    def _baseline_request_predictor(outcome):
        result = ComponentResult.from_mapping(
            outcome.component_result["result"]
        )
        return dict(
            result.baseline.worker_response_receipt[
                "request_binding"
            ]["primary_predictor"]
        )

    def _ordinary_record(self, predictor: complex) -> CampaignLeafRecord:
        leaf = self.flow.leaf
        native, binary = self._binary_stage()
        worker = self._worker(80, predictor)
        with patch.dict(
            "os.environ",
            {"KERR_QNM_PARTIAL_COMPONENT_JOURNAL_ROOT": ""},
        ), patch.object(
            native,
            "_julia_precision_backend_for",
            return_value=worker,
        ):
            promoted = native.execute_promoted_stage(
                leaf,
                80,
                (binary,),
            )
        promoted = _stage_with_promotion_decision(
            promoted,
            _primary_precision120_decision(
                promoted,
                predecessor=binary,
            ),
        )
        return CampaignLeafRecord(
            leaf_id=leaf.leaf_id,
            role=leaf.role,
            state="PRODUCED",
            stages=(
                _campaign_stage_record(
                    self.flow.plan,
                    self.flow.capabilities,
                    binary,
                ),
                _campaign_stage_record(
                    self.flow.plan,
                    self.flow.capabilities,
                    promoted,
                ),
            ),
        )

    def _failed_preflight_record(self, predictor: complex):
        leaf = self.flow.leaf
        native, binary = self._binary_stage()
        predecessor = _failed_preflight_attempt(leaf)
        worker = self._worker(120, predictor)
        with patch.dict(
            "os.environ",
            {"KERR_QNM_PARTIAL_COMPONENT_JOURNAL_ROOT": ""},
        ), patch.object(
            native,
            "_julia_precision_backend_for",
            return_value=worker,
        ):
            recovered = (
                native.execute_promoted_stage_after_failed_preflight(
                    leaf,
                    120,
                    predecessor,
                )
            )
        record = CampaignLeafRecord(
            leaf_id=leaf.leaf_id,
            role=leaf.role,
            state="PRODUCED",
            stages=(
                _campaign_stage_record(
                    self.flow.plan,
                    self.flow.capabilities,
                    binary,
                ),
                _campaign_stage_record(
                    self.flow.plan,
                    self.flow.capabilities,
                    recovered,
                ),
            ),
        )
        return predecessor, binary, recovered, record

    def test_ordinary_fixed_root_request_predictor_must_match_predecessor(self):
        leaf = self.flow.leaf
        honest_predictor = leaf.job.root.omega
        honest = self._ordinary_record(honest_predictor)
        expected_predictor = {
            "real": format(honest_predictor.real, ".17g"),
            "imaginary": format(honest_predictor.imag, ".17g"),
        }
        self.assertEqual(
            self._baseline_request_predictor(
                honest.stages[-1].outcome
            ),
            expected_predictor,
        )
        self.assertTrue(
            _validate_record_semantics(
                leaf,
                honest,
                self.flow.plan.precision_factory_identity,
            )
        )

        mismatched = self._ordinary_record(
            honest_predictor + complex(1.0e-5, -1.0e-5)
        )
        self.assertNotEqual(
            self._baseline_request_predictor(
                mismatched.stages[-1].outcome
            ),
            expected_predictor,
        )
        with self.assertRaisesRegex(ValueError, "predictor"):
            _validate_record_semantics(
                leaf,
                mismatched,
                self.flow.plan.precision_factory_identity,
            )

    def test_failed_preflight_fixed_root_request_predictor_must_match_attempt(self):
        leaf = self.flow.leaf
        predecessor = _failed_preflight_attempt(leaf)
        request = predecessor.failure_receipt["failure"]["request_binding"]
        raw_predictor = request.get(
            "primary_predictor",
            request["omega"],
        )
        honest_predictor = complex(
            float(Decimal(raw_predictor["real"])),
            float(Decimal(raw_predictor["imaginary"])),
        )
        embedded, binary, honest, honest_record = (
            self._failed_preflight_record(honest_predictor)
        )
        self.assertEqual(
            self._baseline_request_predictor(honest),
            dict(raw_predictor),
        )
        validated, produced = _validate_failed_preflight_recovery_stage(
            leaf,
            honest,
            binary,
        )
        self.assertEqual(validated.to_mapping(), embedded.to_mapping())
        self.assertTrue(produced)
        self.assertTrue(
            _validate_record_semantics(
                leaf,
                honest_record,
                self.flow.plan.precision_factory_identity,
            )
        )

        _, mismatched_binary, mismatched, mismatched_record = (
            self._failed_preflight_record(
                honest_predictor + complex(1.0e-5, -1.0e-5)
            )
        )
        self.assertNotEqual(
            self._baseline_request_predictor(mismatched),
            dict(raw_predictor),
        )
        with self.assertRaisesRegex(ValueError, "predictor"):
            _validate_failed_preflight_recovery_stage(
                leaf,
                mismatched,
                mismatched_binary,
            )
        with self.assertRaisesRegex(ValueError, "predictor"):
            _validate_record_semantics(
                leaf,
                mismatched_record,
                self.flow.plan.precision_factory_identity,
            )

    def test_live_failed_preflight_rejects_predictor_mismatch_before_120_write(
        self,
    ):
        """A contained attempt cannot override its binary predecessor root."""

        checkpoint = self.flow.root / "failed-preflight-predictor-mismatch.json"
        selection = build_campaign_selection(
            self.flow.plan,
            role="primary",
            leaf_ids=(self.flow.leaf.leaf_id,),
        )
        native = self.flow._native_backend()
        failure = self.flow._provisional_failed_preflight_error(self.flow.leaf)
        worker80 = campaign_fixtures._FailingScientificFixedRootBackend(
            self.flow.leaf.job,
            self._worker(
                80, self.flow.leaf.job.root.omega
            ).baseline,
            80,
            failure,
        )
        worker120 = self.flow._precision_backend(self.flow.leaf, 120)

        with patch(
            "windows_solver.response_batches.run_component",
            return_value=self.flow._binary_result(shifted_root=True),
        ), patch.object(
            native,
            "_julia_precision_backend_for",
            side_effect=lambda job, digits, refinement=0: {
                80: worker80,
                120: worker120,
            }[digits],
        ), self.assertRaisesRegex(
            ValueError,
            "promoted fixed-readout PRIMARY predictor binding is invalid",
        ):
            run_campaign_selection(
                self.flow.plan,
                selection,
                native,
                checkpoint,
                resume=False,
            )

        surviving = validate_campaign_checkpoint(self.flow.plan, checkpoint)
        self.assertEqual(
            tuple(
                stage.outcome.digits
                for stage in surviving.records[0].stages
            ),
            (64,),
        )
        self.assertEqual(len(surviving.attempts), 1)
        self.assertEqual(surviving.attempts[0].precision_digits, 80)
        self.assertEqual(
            surviving.attempts[0].failure_code,
            "INSUFFICIENT_ASYMPTOTIC_PRECISION",
        )


if __name__ == "__main__":
    unittest.main()
